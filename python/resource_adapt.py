#!/usr/bin/env python3
"""Resource adaptation: classify why a tool failed for lack of a resource, choose ONE safe response, remember what an isolate needs.

New tools and failures are added as DATA (config/resource_signatures.tsv), not code. For each failure the table gives a cause (memory, disk, tmp_space, open_files, thread_limit,
timeout_slow, db_missing, ...), an optional pattern for the amount needed, and a LADDER: an ordered list of responses, each with a precondition checked against what the machine
has right now:

  raise_memory   budget = ceil(need * 1.15 + 0.5 GB) when that fits in 85% of the free memory (else the need rounded up when it fits in 92%); with no stated need, 1.5x the
                 budget when that fits. Never lowers a budget.
  halve_threads  only for tools whose memory or thread count scales with threads (table flag); threads = max(1, threads // 2).
  move_tmp       work in the roomiest folder that is not the current one (PLASBENCH_TMP_CANDIDATES, ~/.plasbench/scratch, the system temp, the data folder) with enough free space.
  raise_ulimit   `ulimit -n` for the child up to the HARD limit (never beyond it, never a system setting).
  extend_timeout double the time limit once (capped at 7 days) only when the tool shows progress (its log grew, or it used CPU).
  skip           always applicable: the isolate (or tool) is skipped with an exact reason; the run continues.

Rules: each (tool, isolate, response) is tried at most once; at most RESOURCE_MAX_ATTEMPTS (default 2) adjustments per tool and isolate; only resources change, never a scientific
parameter (k-mer sizes, thresholds, modes); the one mode-changing option, SPAdes --only-assembler, stays opt-in elsewhere (ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1).

  python3 -I python/resource_adapt.py decide --tool T --isolate S --exit-code N [--log FILE] --threads N --memory-gb N --available-gb X [--tmpdir D] [--state FILE]
                                              [--timeout SEC] [--progress 0|1] [--max-attempts 2] [--candidates a:b]
        -> one TSV line: action(retry|skip|none) cause memory_gb threads tmpdir ulimit_n timeout needed_gb message
  python3 -I python/resource_adapt.py sig --r1 R1 --r2 R2
  python3 -I python/resource_adapt.py lookup|record|merge|manifest|estimate|plan|docs ...      (the learned resource profile; see --help of each)

Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "config" / "resource_signatures.tsv"
CAUSES = ("memory", "disk", "tmp_space", "open_files", "thread_limit", "timeout_slow", "db_missing", "gpu_missing", "network", "permission", "unknown")
RESPONSES = ("raise_memory", "halve_threads", "move_tmp", "raise_ulimit", "extend_timeout", "skip")
UNITS = {"TB": 1024.0, "TIB": 1024.0, "GB": 1.0, "GIB": 1.0, "G": 1.0, "MB": 1 / 1024.0, "MIB": 1 / 1024.0, "M": 1 / 1024.0, "KB": 1 / 1048576.0, "KIB": 1 / 1048576.0}
MAX_TIMEOUT = 7 * 24 * 3600


# ----------------------------------------------------------------------------------------------------------------------------- table
def load_table(path=None):
    rows = []
    with open(path or TABLE, encoding="utf-8") as handle:
        lines = [ln.rstrip("\n") for ln in handle if ln.strip() and not ln.startswith("#")]
    header = lines[0].split("\t")
    for ln in lines[1:]:
        parts = ln.split("\t")
        row = dict(zip(header, parts + [""] * (len(header) - len(parts))))
        rows.append(row)
    return rows


def validate(rows):
    """Problems in the table, as strings (empty = valid): bad regexes, unknown causes or responses, malformed exit codes or units."""
    problems, seen = [], set()
    for r in rows:
        rid = r.get("id", "?")
        if rid in seen:
            problems.append("%s: duplicate id" % rid)
        seen.add(rid)
        for column in ("tool", "message_regex"):
            if r.get(column) not in ("-", ""):
                try:
                    re.compile(r[column])
                except re.error as exc:
                    problems.append("%s: %s does not compile (%s)" % (rid, column, exc))
        if r.get("cause") not in CAUSES:
            problems.append("%s: unknown cause %r" % (rid, r.get("cause")))
        for step in (r.get("ladder") or "").split(","):
            if step not in RESPONSES:
                problems.append("%s: unknown response %r" % (rid, step))
        if r.get("exit_codes") not in ("-", ""):
            for code in r["exit_codes"].split(","):
                if not re.fullmatch(r"-?\d+", code.strip()):
                    problems.append("%s: bad exit code %r" % (rid, code))
        if r.get("need_unit") not in ("-", "") and r["need_unit"].upper() not in UNITS:
            problems.append("%s: unknown unit %r" % (rid, r["need_unit"]))
        if r.get("scales_with_threads") not in ("0", "1"):
            problems.append("%s: scales_with_threads must be 0 or 1" % rid)
        if r.get("label") not in ("real", "sample"):
            problems.append("%s: label must be real or sample" % rid)
        if r.get("message_regex") in ("-", "") and r.get("exit_codes") in ("-", ""):
            problems.append("%s: needs a message or an exit code" % rid)
        if not (r.get("ladder") or "").endswith("skip"):
            problems.append("%s: a ladder must end with skip" % rid)
    return problems


def classify(tool, log_text, exit_code, rows=None):
    """The first matching signature: {id, cause, ladder, needed_gb, scales, label} or None. A message match is preferred to an exit-code match."""
    rows = load_table() if rows is None else rows
    code = None
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        pass
    best = None
    for r in rows:
        if r["tool"] != "-" and not re.search(r["tool"], tool or "", re.I):
            continue
        by_message = by_code = False
        found = None
        if r["message_regex"] not in ("-", ""):
            for m in re.finditer(r["message_regex"], log_text or "", re.I):
                found = m
            by_message = found is not None
        if r["exit_codes"] not in ("-", "") and code is not None:
            by_code = code in [int(c) for c in r["exit_codes"].split(",")]
        if not (by_message or by_code):
            continue
        need = None
        if found is not None and "need" in (found.groupdict() or {}) and found.group("need"):
            unit = (found.groupdict().get("unit") or r["need_unit"] or "GB").upper()
            try:
                need = float(found.group("need")) * UNITS.get(unit, 1.0)
            except ValueError:
                need = None
        hit = {"id": r["id"], "cause": r["cause"], "ladder": r["ladder"].split(","), "needed_gb": need, "scales": r["scales_with_threads"] == "1", "label": r["label"],
               "by": "message" if by_message else "exit code"}
        if by_message:
            return hit
        best = best or hit
    return best


# ------------------------------------------------------------------------------------------------------------------------- resources
def free_gb(path):
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return __import__("shutil").disk_usage(str(probe)).free / 1e9
    except OSError:
        return None


def memory_plan(need_gb, available_gb, budget_gb):
    """(new_budget_gb, note) or (None, reason). Never below the current budget."""
    if need_gb:
        wanted = int(math.ceil(need_gb * 1.15 + 0.5))
        bare = int(math.ceil(need_gb))
        if available_gb is None:
            return max(wanted, budget_gb), "memory available now is unknown; need + 15% + 0.5 GB"
        if wanted <= available_gb * 0.85:
            return max(wanted, budget_gb), "need %.2f GB + 15%% + 0.5 GB, %.1f GB free" % (need_gb, available_gb)
        if bare <= available_gb * 0.92:
            return max(bare, budget_gb), "need %.2f GB rounded up, %.1f GB free (tight)" % (need_gb, available_gb)
        return None, "needs %.1f GB, %.1f GB are free" % (need_gb, available_gb)
    target = int(math.ceil(budget_gb * 1.5))
    if available_gb is None or target <= available_gb * 0.85:
        return target, "no amount stated; 1.5 x the budget, %s GB free" % ("%.1f" % available_gb if available_gb is not None else "?")
    return None, "the amount needed is not stated and 1.5 x the %d GB budget does not fit in the %.1f GB free" % (budget_gb, available_gb)


def tmp_candidates(env, data_dir=None):
    out = [p for p in (env.get("PLASBENCH_TMP_CANDIDATES") or "").split(os.pathsep) if p]
    home = env.get("HOME") or os.path.expanduser("~")
    out += [os.path.join(home, ".plasbench", "scratch", "_tmp"), tempfile.gettempdir()]
    if data_dir:
        out.append(str(data_dir))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def ulimit_plan(soft_hard=None):
    """(new_soft, hard, note) for `ulimit -n` or (None, hard, reason). The hard limit is never exceeded."""
    if soft_hard is None:
        try:
            import resource
            soft_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        except (ImportError, OSError, ValueError):
            return None, None, "n/a: this system has no per-process open-file limit to raise"
    soft, hard = soft_hard
    infinity = getattr(__import__("resource"), "RLIM_INFINITY", -1) if os.name == "posix" else -1
    cap = 1048576 if hard == infinity else hard
    if soft >= cap:
        return None, hard, "the open-files limit is already at its hard limit (%d); raising it needs a system change PlasBench never makes" % cap
    return min(cap, max(4096, soft * 4)), hard, "open-files limit %d -> %d (hard limit %s)" % (soft, min(cap, max(4096, soft * 4)), "unlimited" if hard == infinity else hard)


def read_state(path):
    try:
        return [ln.strip() for ln in open(path, encoding="utf-8") if ln.strip()]
    except OSError:
        return []


def decide(tool, isolate, exit_code, log_text, ctx, rows=None, state_file=None, max_attempts=2, soft_hard=None):
    """The verdict: dict(action, cause, memory_gb, threads, tmpdir, ulimit_n, timeout, needed_gb, message, response, id, label). action is retry, skip or none (not recognised)."""
    hit = classify(tool, log_text, exit_code, rows)
    out = {"action": "none", "cause": "unknown", "memory_gb": "", "threads": "", "tmpdir": "", "ulimit_n": "", "timeout": "", "needed_gb": "", "message": "", "response": "", "id": "", "label": ""}
    if not hit:
        return out
    out.update(cause=hit["cause"], id=hit["id"], label=hit["label"], needed_gb=("%.3f" % hit["needed_gb"]) if hit["needed_gb"] else "")
    done = read_state(state_file) if state_file else []
    key = lambda response: "%s|%s|%s|%s" % (tool, isolate, hit["cause"], response)  # noqa: E731
    mem, threads = int(ctx.get("memory_gb") or 0), int(ctx.get("threads") or 1)
    avail = ctx.get("available_gb")
    spent = len([d for d in done if d.startswith("%s|%s|" % (tool, isolate)) and not d.endswith("|skip")])
    reasons = []
    for response in hit["ladder"]:
        if response == "skip":
            break
        if key(response) in done:
            reasons.append("%s was already tried" % response)
            continue
        if spent >= max_attempts:
            reasons.append("the limit of %d adjustments for this tool and isolate is reached" % max_attempts)
            break
        if response == "raise_memory":
            new, note = memory_plan(hit["needed_gb"], avail, mem)
            if new is None:
                reasons.append(note)
                continue
            if new <= mem:
                reasons.append("the budget (%d GB) already covers the need" % mem)
                continue
            out.update(action="retry", response=response, memory_gb=str(new),
                       message="%s needs about %s for this isolate; raising memory from %d to %d GB (%s GB are free) and retrying"
                       % (tool, ("%.1f GB" % hit["needed_gb"]) if hit["needed_gb"] else "more memory", mem, new, ("%.1f" % avail) if avail is not None else "?"))
        elif response == "halve_threads":
            if not hit["scales"] or threads <= 1:
                reasons.append("threads do not apply (%s)" % ("this tool's memory does not scale with threads" if not hit["scales"] else "already 1 thread"))
                continue
            new = max(1, threads // 2)
            out.update(action="retry", response=response, threads=str(new), message="%s ran out of %s; halving its threads from %d to %d and retrying" % (tool, hit["cause"], threads, new))
        elif response == "move_tmp":
            current = os.path.realpath(ctx.get("tmpdir") or "") if ctx.get("tmpdir") else ""
            need = max(5.0, hit["needed_gb"] or 0)
            best = None
            for cand in (ctx.get("candidates") or tmp_candidates(os.environ, ctx.get("data_dir"))):
                if current and os.path.realpath(cand) == current:
                    continue
                f = free_gb(cand)
                if f is not None and f >= need and (best is None or f > best[1]):
                    best = (cand, f)
            if not best:
                reasons.append("no other folder has %.0f GB free" % need)
                continue
            out.update(action="retry", response=response, tmpdir=best[0], message="%s ran out of temporary space%s; moving its work folder to %s (%.0f GB free) and retrying"
                       % (tool, (" in " + ctx["tmpdir"]) if ctx.get("tmpdir") else "", best[0], best[1]))
        elif response == "raise_ulimit":
            new, hard, note = ulimit_plan(soft_hard)
            if new is None:
                reasons.append(note)
                continue
            out.update(action="retry", response=response, ulimit_n=str(new), message="%s hit the open-files limit; %s and retrying" % (tool, note))
        elif response == "extend_timeout":
            current = int(ctx.get("timeout") or 0)
            if not ctx.get("progress") or current <= 0:
                reasons.append("it shows no progress (log unchanged, CPU idle), so it is treated as stuck, not slow" if current > 0 else "there is no time limit to extend")
                continue
            new = min(MAX_TIMEOUT, current * 2)
            if new <= current:
                reasons.append("the time limit is already at its cap")
                continue
            out.update(action="retry", response=response, timeout=str(new), message="%s was stopped at its time limit but is still making progress; doubling the limit from %d to %d s and retrying" % (tool, current, new))
        if out["action"] == "retry":
            break
    if out["action"] != "retry":
        out.update(action="skip", response="skip", message="%s: %s (%s). %s" % (tool, hit["cause"].replace("_", " "), "; ".join(reasons) or "no adjustment applies", skip_advice(hit["cause"], hit["needed_gb"], avail)))
    return out


def skip_advice(cause, needed, avail):
    return {"memory": "Close programs or raise WSL memory in C:\\Users\\<you>\\.wslconfig (memory=%dGB) then `wsl --shutdown`, or raise MEMORY_GB." % (int(math.ceil(needed)) + 2 if needed else 8),
            "tmp_space": "Free space in the temporary folder or set TMPDIR to a bigger drive.", "disk": "Free disk space, then run the same command again.",
            "open_files": "Raise the hard open-files limit for your user (ulimit -Hn) or run fewer jobs at once.",
            "thread_limit": "Lower THREADS (plasbench run --threads N).", "timeout_slow": "Raise TOOL_TIMEOUT_SECONDS or look at the tool's log: it may be stuck.",
            "db_missing": "Install the tool's database (plasbench check --yes).", "gpu_missing": "This tool needs a GPU; it is skipped on this computer.",
            "permission": "Make the folder writable (ls -ld).", "network": "Check the connection and run again."}.get(cause, "See the tool's log.")


# --------------------------------------------------------------------------------------------------------- the learned resource profile
PROFILE_COLUMNS = ("tool", "sample", "signature", "needed_gb", "budget_gb", "threads", "tmp_gb", "attempts", "mode", "status", "source", "learned_at")


def signature(paths):
    digest = hashlib.sha256()
    for path in paths:
        try:
            size = os.path.getsize(path)
            digest.update(("%d|" % size).encode())
            with open(path, "rb") as handle:
                digest.update(handle.read(1 << 20))
                if size > (2 << 20):
                    handle.seek(size - (1 << 20))
                    digest.update(handle.read(1 << 20))
        except OSError:
            digest.update(b"missing|")
    return digest.hexdigest()[:24]


def _pfile(directory, tool, sample):
    safe = lambda s: "".join(c if c.isalnum() or c in "._-" else "_" for c in s)  # noqa: E731
    return Path(directory) / "resource_profile.d" / ("%s.%s.tsv" % (safe(tool), safe(sample)))


def read_row(path):
    try:
        lines = [ln.rstrip("\n").split("\t") for ln in open(path, encoding="utf-8") if ln.strip()]
    except OSError:
        return None
    return dict(zip(lines[0], lines[1] + [""] * (len(lines[0]) - len(lines[1])))) if len(lines) >= 2 else None


def lookup(directory, tool, sample, sig):
    row = read_row(_pfile(directory, tool, sample))
    if not row or row.get("signature") != sig:
        return None
    try:
        return {"needed_gb": float(row.get("needed_gb") or 0), "budget_gb": int(float(row.get("budget_gb") or 0)), "threads": row.get("threads", ""), "mode": row.get("mode") or "spades",
                "attempts": int(float(row.get("attempts") or 1)), "status": row.get("status", ""), "source": row.get("source", "")}
    except ValueError:
        return None


def record(directory, tool, sample, sig, needed=0.0, budget=0, threads="", tmp_gb="", attempts=1, mode="spades", status="completed", source="message"):
    path = _pfile(directory, tool, sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp%d" % os.getpid())
    row = (tool, sample, sig, ("%.2f" % needed) if needed else "", str(budget), str(threads), str(tmp_gb), str(attempts), mode, status, source, time.strftime("%Y-%m-%dT%H:%M:%S"))
    tmp.write_text("\t".join(PROFILE_COLUMNS) + "\n" + "\t".join(row) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def merge(directory, out):
    rows = []
    folder = Path(directory) / "resource_profile.d"
    for path in sorted(folder.glob("*.tsv")) if folder.is_dir() else []:
        row = read_row(path)
        if row:
            rows.append(row)
    if not rows:
        return 0
    tmp = Path(str(out) + ".tmp%d" % os.getpid())
    tmp.write_text("\t".join(PROFILE_COLUMNS) + "\n" + "".join("\t".join(r.get(c, "") for c in PROFILE_COLUMNS) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, out)
    return len(rows)


def estimate(table, tool, reads_gb, minimum=5):
    """(needed_gb, note) from a least-squares line through the learned (reads size, needed) rows of this tool, or None with fewer than `minimum` rows. Always labelled estimated."""
    try:
        lines = [ln.rstrip("\n").split("\t") for ln in open(table, encoding="utf-8") if ln.strip()]
    except OSError:
        return None
    header = lines[0] if lines else []
    pts = []
    for r in lines[1:]:
        d = dict(zip(header, r + [""] * (len(header) - len(r))))
        if d.get("tool") == tool and d.get("needed_gb") and d.get("reads_gb"):
            pts.append((float(d["reads_gb"]), float(d["needed_gb"])))
    if len(pts) < minimum:
        return None
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return my, "estimated from %d learned isolates (no spread in read size)" % n
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return max(0.0, my + slope * (reads_gb - mx)), "estimated from %d learned isolates" % n


def manifest(table, manifest_path, events=None):
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    try:
        lines = [ln.rstrip("\n").split("\t") for ln in open(table, encoding="utf-8") if ln.strip()]
    except OSError:
        lines = []          # no learned profile (nothing was adapted or learned): the section still lists the adjustments, if any
    header = lines[0] if lines else []
    items = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in lines[1:]]
    adjustments = []
    try:
        for ln in open(events, encoding="utf-8"):
            if '"resource_adjust"' in ln:
                try:
                    adjustments.append({k: v for k, v in json.loads(ln).items() if k not in ("pid", "ts")})
                except ValueError:
                    pass
    except (OSError, TypeError):
        pass
    data["resources"] = {
        "note": "Final threads, memory budget (GB), assembly mode and attempts per tool and isolate, and every automatic adjustment (AUTO_RESOURCES). Adjustments change resources only, never k-mer sizes, "
                "thresholds or scientific parameters; mode 'only-assembler' (opt-in ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1) skips SPAdes read error correction and is a different assembly.",
        "profile": [{k: i.get(k, "") for k in ("tool", "sample", "budget_gb", "needed_gb", "threads", "attempts", "mode", "status", "source")} for i in items],
        "adjustments": adjustments}
    tmp = Path(str(manifest_path) + ".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    return True


def docs(rows):
    out = ["# Resource adaptation", "",
           "Generated from `config/resource_signatures.tsv` by `python3 python/resource_adapt.py docs` (a test keeps it current). `real` = the wording was captured from a log or test in this repository;",
           "`sample` = the wording comes from the tool's documentation or source and was not captured here.", "",
           "| id | tool | cause | matches | exit codes | ladder | label |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | `%s` | %s | `%s` | %s | %s | %s |" % (r["id"], r["tool"], r["cause"], (r["message_regex"] if r["message_regex"] != "-" else "-").replace("|", "\\|"), r["exit_codes"], r["ladder"].replace(",", " > "), r["label"]))
    out += ["", "## What each response does", ""]
    for name, text in (("raise_memory", "budget = ceil(need x 1.15 + 0.5 GB) when it fits in 85% of the memory free now (else the need rounded up when it fits in 92%); with no stated need 1.5 x the budget when it fits. Never lowers a budget."),
                       ("halve_threads", "threads = max(1, threads / 2), only for tools flagged `scales_with_threads`."),
                       ("move_tmp", "moves the tool's work folder (TMPDIR) to the roomiest other folder with enough free space (scratch on the local disk, the system temp, the data folder)."),
                       ("raise_ulimit", "`ulimit -n` for the tool up to the hard limit; never beyond it, never a system setting; says so when the hard limit is the problem."),
                       ("extend_timeout", "doubles the time limit once (cap 7 days), only when the tool shows progress."),
                       ("skip", "always possible: the isolate or tool is skipped with the exact need and what is free, and the run continues.")):
        out.append("- **%s**: %s" % (name, text))
    out += ["", "## Limits", "", "- Each response is tried at most once per tool, isolate and cause; at most `RESOURCE_MAX_ATTEMPTS` (default 2) adjustments per tool and isolate.",
            "- Only resources change: never k-mer sizes, thresholds or modes. The one mode-changing option, SPAdes `--only-assembler`, is opt-in (`ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1`) and recorded as a different assembly mode.",
            "- The budget never exceeds what the machine has free now (cgroup and WSL aware, MB-precise).", "- Learned needs are kept in `results/resource_profile.tsv`, keyed by a checksum of the isolate's reads; a changed read set invalidates them.",
            "", "## Adding a signature", "", "Add one row to `config/resource_signatures.tsv` (tab-separated): `tool` and `message_regex` are regular expressions (use named groups `need` and `unit` to read an amount), `exit_codes` a comma list or `-`,",
            "`cause` one of the known causes, `ladder` the ordered responses (ending in `skip`), `label` `real` or `sample`. `python3 test/test_resource_adapt.py` validates the table.", "",
            "## Turning it off", "", "`AUTO_RESOURCES=0` (config/config.sh, or the environment) restores fixed behaviour: one attempt with the budget you set. `RESOURCE_MAX_ATTEMPTS` caps the adjustments."]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------------------------------------------------ CLI
def read_tail(path, max_bytes=200000):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--tool", required=True)
    d.add_argument("--isolate", default="-")
    d.add_argument("--exit-code")
    d.add_argument("--log")
    d.add_argument("--threads", type=int, default=1)
    d.add_argument("--memory-gb", type=int, default=0)
    d.add_argument("--available-gb", type=float)
    d.add_argument("--tmpdir", default="")
    d.add_argument("--state")
    d.add_argument("--timeout", type=int, default=0)
    d.add_argument("--progress", type=int, default=0)
    d.add_argument("--max-attempts", type=int, default=int(os.environ.get("RESOURCE_MAX_ATTEMPTS", "2") or 2))
    d.add_argument("--candidates", default="")
    s = sub.add_parser("sig")
    s.add_argument("--r1", required=True)
    s.add_argument("--r2", required=True)
    for name in ("lookup", "record"):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True)
        p.add_argument("--tool", default="spades")
        p.add_argument("--sample", required=True)
        p.add_argument("--sig", required=True)
        if name == "record":
            p.add_argument("--needed", type=float, default=0)
            p.add_argument("--budget", type=int, default=0)
            p.add_argument("--threads", default="")
            p.add_argument("--attempts", type=int, default=1)
            p.add_argument("--mode", default="spades")
            p.add_argument("--status", default="completed")
            p.add_argument("--source", default="message")
    pl = sub.add_parser("plan")
    pl.add_argument("--need", type=float, required=True)
    pl.add_argument("--available-gb", type=float)
    pl.add_argument("--budget", type=int, default=0)
    m = sub.add_parser("merge")
    m.add_argument("--dir", required=True)
    m.add_argument("--out", required=True)
    mf = sub.add_parser("manifest")
    mf.add_argument("--table", required=True)
    mf.add_argument("--manifest", required=True)
    mf.add_argument("--events")
    sub.add_parser("docs")
    args = ap.parse_args(argv)
    if args.cmd == "decide":
        ctx = {"memory_gb": args.memory_gb, "threads": args.threads, "available_gb": args.available_gb, "tmpdir": args.tmpdir, "timeout": args.timeout, "progress": args.progress,
               "candidates": [c for c in args.candidates.split(os.pathsep) if c]}
        v = decide(args.tool, args.isolate, args.exit_code, read_tail(args.log), ctx, state_file=args.state, max_attempts=args.max_attempts)
        if v["action"] != "none" and args.state:
            Path(args.state).parent.mkdir(parents=True, exist_ok=True)
            with open(args.state, "a", encoding="utf-8") as handle:
                handle.write("%s|%s|%s|%s\n" % (args.tool, args.isolate, v["cause"], v["response"]))
        print("\t".join(str(v[k]).replace("\t", " ").replace("\n", " ") or "-" for k in ("action", "cause", "memory_gb", "threads", "tmpdir", "ulimit_n", "timeout", "needed_gb", "message")))
    elif args.cmd == "sig":
        print(signature([args.r1, args.r2]))
    elif args.cmd == "lookup":
        got = lookup(args.dir, args.tool, args.sample, args.sig)
        print("none" if not got else "%.3f %d %s %d" % (got["needed_gb"], got["budget_gb"], got["mode"], got["attempts"]))
    elif args.cmd == "record":
        record(args.dir, args.tool, args.sample, args.sig, args.needed, args.budget, args.threads, "", args.attempts, args.mode, args.status, args.source)
    elif args.cmd == "plan":
        new, note = memory_plan(args.need, args.available_gb, args.budget)
        print("none %s" % note if new is None else "%d %s" % (new, note))
    elif args.cmd == "merge":
        merge(args.dir, args.out)
    elif args.cmd == "manifest":
        manifest(args.table, args.manifest, args.events)
    else:
        sys.stdout.write(docs(load_table()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
