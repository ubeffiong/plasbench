"""The AI help's isolate set-up, done by PlasBench's own intake (python/intake.py), not by a second implementation.

"Set up my isolates from a folder" in the AI pane is `plasbench intake scan` + `plasbench intake stage --dry-run` on the folder the person chose, shown as a review card, then
`plasbench intake stage` (the SAME plan: intake.plan_stage is the one planner, and intake.stage executes exactly what it returns), then `plasbench intake check` (the quick test),
then `--fix` for what has one right answer, the truth labels only the person can decide, and the `plasbench run` command as a Run-in-PlasBench card. The model is not involved in
any of it: it gets a summary only when the person presses Share.

What this module adds to the intake, and why:
  * the folder is the GRANT (plasbench/ai_folder.py): before intake opens a file, `accept()` proves it is inside the chosen folder by real path, not a link or junction, not hidden,
    not a device name (ai_folder.Grant.resolve); a refused file is listed, never read. The folder is first listed with the AI scan's bounds (entries, depth, time): a folder over the
    bounds is refused with a plain sentence instead of being half-read;
  * the destination is chosen by the person from a closed list (PlasBench's shared data folder, or a study's own data folder) and the sheet name is a plain name under config/:
    the page never sends a path. The plan shows every file that is copied, joined or compressed, from where to where, and the sheet before and after (a diff), checked with
    intake.validate_sheet_text BEFORE Apply is offered;
  * the AI route never replaces a file: an isolate whose destination files already exist is left out with the reason (the command line would replace them);
  * Apply re-scans and re-plans on the server and refuses when the plan differs from the one the person reviewed (the page's copy is never trusted); it writes an undo journal
    (~/.plasbench/ai/journal/<id>/journal.json) with every file and folder it created and a copy of the sheet as it was; Undo removes only files that are unchanged since;
  * every name shown is cleaned (control, bidi, zero-width characters removed, fences defused).
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

from . import ai_files, ai_folder
from .ai_folder import FolderError, clean

SCAN_DEPTH = 3                       # the default of `plasbench intake scan/stage`
SHEET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_ISOLATES = 200
CONFIG_DIR = None                    # where the sheets go: <PlasBench>/config (a test points it at a temporary folder)


def intake_module(project):
    """python/intake.py of this PlasBench (the module `plasbench intake` runs)."""
    if hasattr(project, "intake"):
        return project.intake()
    python_dir = str(Path(project.root) / "python")
    if python_dir not in sys.path:
        sys.path.insert(0, python_dir)
    import importlib
    return importlib.import_module("intake")


# ------------------------------------------------------------------------------------------------------------------------ destination
def _shared_data_dir(project) -> Path:
    from .cli import configured_data_dir
    return Path(configured_data_dir(Path(project.root)))


def destinations(project) -> dict:
    """The closed list the person chooses from, with the real folders shown (this is the person's own window; nothing here goes to the model)."""
    from . import studies
    out = [{"where": "shared", "label": "PlasBench's data folder (shared by every study)", "data_dir": str(_shared_data_dir(project))}]
    try:
        names = [s["name"] for s in studies.list_studies(Path(project.root)) if s.get("available", True)][:30]
    except Exception:  # noqa: BLE001 - a listing problem never blocks the flow
        names = []
    return {"destinations": out, "studies": names, "default_sheet": "local", "sheets": local_sheets(project)}


def resolve_dest(project, dest: dict) -> dict:
    """{data_dir, sheet, sheet_rel, label, study, keep_in_study} from the person's choice. Raises FolderError for anything not on the closed list."""
    from . import studies
    dest = dest if isinstance(dest, dict) else {}
    where = str(dest.get("where") or "shared")
    sheet = str(dest.get("sheet") or "local").strip()
    if sheet.lower().endswith(".tsv"):
        sheet = sheet[:-4]
    if not SHEET_NAME.match(sheet) or ai_folder.check_name(sheet + ".tsv"):
        raise FolderError("the sheet name must be a plain name (letters, digits, . _ -), for example my_isolates")
    study = str(dest.get("study") or "").strip()
    if study:
        try:
            study = studies.valid_name(study)
        except ValueError as exc:
            raise FolderError(str(exc))
    root = Path(project.root)
    if where == "shared":
        data_dir, label = _shared_data_dir(project), "PlasBench's data folder"
    elif where == "study":
        if not study:
            raise FolderError("name the study whose own data folder should hold the reads")
        try:
            data_dir = studies.study_path(root, study) / "data"
        except ValueError as exc:
            raise FolderError(str(exc))
        label = "the data folder of study %s" % study
    else:
        raise FolderError("choose PlasBench's data folder or a study's own data folder")
    return {"data_dir": data_dir, "sheet": _config_dir(project) / (sheet + ".tsv"), "sheet_rel": "config/%s.tsv" % sheet, "label": label, "study": study,
            "keep_in_study": where == "study", "where": where}


def _config_dir(project) -> Path:
    return Path(CONFIG_DIR) if CONFIG_DIR else Path(project.root) / "config"


def local_sheets(project) -> list:
    """config/*.tsv files that are sheets of your own isolates (sample_id, assembly_accession, sra_run, and at least one LOCAL or NA row)."""
    out = []
    try:
        for p in sorted(_config_dir(project).glob("*.tsv"))[:200]:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:200000]
            except OSError:
                continue
            body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
            if not body:
                continue
            head = [h.strip() for h in body[0].split("\t")]
            if not {"sample_id", "assembly_accession", "sra_run"} <= set(head):
                continue
            i = head.index("assembly_accession")
            if any(len(r.split("\t")) > i and r.split("\t")[i].strip() in ("LOCAL", "NA") for r in body[1:]):
                out.append(p.stem)
    except OSError:
        pass
    return out


def run_command(d: dict) -> str:
    """The `plasbench run` command for the staged sheet (relative paths only, so the window's command check accepts it)."""
    cmd = "plasbench run --samples %s --local-inputs" % d["sheet_rel"]
    if d.get("study"):
        cmd += " --study %s" % d["study"]
    if d.get("keep_in_study"):
        cmd += " --keep-data-in-study"
    return cmd


# ------------------------------------------------------------------------------------------------------------------------- the scan
def accept_for(grant: "ai_folder.Grant"):
    """The intake's accept(): '' for a file intake may open, else the reason (outside the grant, a link or junction, hidden, a device name...)."""
    def accept(path) -> str:
        try:
            rel = os.path.relpath(str(path), grant.root).replace(os.sep, "/")
        except ValueError:
            return "outside the chosen folder"
        if rel == ".." or rel.startswith("../"):
            return "outside the chosen folder"
        try:
            grant.resolve(rel, must_exist=True)
        except FolderError as exc:
            return str(exc)
        return ""
    return accept


def scan(project, grant, references=None) -> dict:
    """intake.scan of the granted folder, bounded and confined. `references` maps an isolate id to a FASTA chosen by the person (a path relative to the folder)."""
    entries, skipped, truncated = ai_folder._walk(grant.root, time.time() + ai_folder.MAX_SCAN_SECONDS)
    if truncated:
        raise FolderError("this folder holds more than %d files and folders (or took too long to list): choose the folder that holds just these isolates' files"
                          % ai_folder.MAX_ENTRIES)
    refs = {}
    for iso, rel in (references or {}).items():
        if not isinstance(iso, str) or not isinstance(rel, str) or not rel:
            continue
        refs[iso] = str(grant.resolve(rel, must_exist=True))
    intake = intake_module(project)
    found = intake.scan([grant.root], SCAN_DEPTH, accept=accept_for(grant), references=refs)
    if len(found["isolates"]) > MAX_ISOLATES:
        raise FolderError("more than %d isolates were found: choose a folder with fewer isolates, or use plasbench intake stage in a terminal" % MAX_ISOLATES)
    found["_skipped"] = skipped
    return found


def _rel(grant, path) -> str:
    try:
        r = os.path.relpath(str(path), grant.root).replace(os.sep, "/")
    except ValueError:
        return clean(os.path.basename(str(path)), 80)
    return clean(r if not r.startswith("..") else os.path.basename(str(path)), 120)


def _dest_rel(d: dict, path) -> str:
    p = str(path)
    for base, label in ((str(d["data_dir"]), "data"), (str(Path(d["sheet"]).parent), "config")):
        try:
            r = os.path.relpath(p, base).replace(os.sep, "/")
        except ValueError:
            continue
        if not r.startswith(".."):
            return clean(label + "/" + r, 140)
    return clean(os.path.basename(p), 80)


# ------------------------------------------------------------------------------------------------------------------------- the plan
def _choices(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}

    def strmap(v):
        return {str(k)[:80]: str(x)[:120] for k, x in (v.items() if isinstance(v, dict) else []) if isinstance(x, (str, int))}
    inc = raw.get("include")
    return {"include": [str(x)[:80] for x in inc] if isinstance(inc, list) else None, "rename": strmap(raw.get("rename")), "organism": strmap(raw.get("organism")),
            "reference": strmap(raw.get("reference"))}


def _organism_ok(text: str) -> str:
    if text and (len(text) > 80 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ._()\-]*", text)):
        return "the organism must be plain words (letters, digits, spaces, . _ - and brackets), for example Escherichia coli"
    return ""


def make_plan(project, grant, dest: dict, choices=None) -> tuple:
    """(view, plan, found, d): the review card's data, the intake plan, the scan and the resolved destination. Nothing is written."""
    ch = _choices(choices)
    d = resolve_dest(project, dest)
    if _inside(str(d["data_dir"]), grant.root):
        raise FolderError("the destination is inside the folder you chose; choose PlasBench's data folder or a study's data folder")
    for k, v in ch["organism"].items():
        if _organism_ok(v):
            raise FolderError(_organism_ok(v))
    found = scan(project, grant, ch["reference"])
    intake = intake_module(project)
    ids = [i["id"] for i in found["isolates"]]
    only = [i for i in (ch["include"] if ch["include"] is not None else ids) if i in ids]
    plan = intake.plan_stage(found, d["data_dir"], d["sheet"], only or ["\x00none"], ch["rename"], ch["organism"], "copy")
    # the AI route never replaces a file the person already has: such an isolate is left out with the reason, and the plan is made again without it
    keep_out = {e["from"]: "skipped: %s already exists; nothing is replaced from here (choose another sample id, or use plasbench intake stage)" % _dest_rel(d, op["to"])
                for e in plan["isolates"] if e["stage"] for op in e["ops"] if op.get("replaces")}
    if keep_out:
        plan = intake.plan_stage(found, d["data_dir"], d["sheet"], [i for i in only if i not in keep_out] or ["\x00none"], ch["rename"], ch["organism"], "copy")
    listed = {e["from"] for e in plan["isolates"]}
    for i in ids:                      # isolates the person left out (or that would replace files) stay in the card, with the reason
        if i not in listed:
            plan["isolates"].append({"id": ch["rename"].get(i, i), "from": i, "stage": False, "ops": [], "needs_review": 0, "dir": "",
                                     "skip": keep_out.get(i, "left out: not ticked"), "status": next(x["status"] for x in found["isolates"] if x["id"] == i)})
    order = {i: n for n, i in enumerate(ids)}
    plan["isolates"].sort(key=lambda e: order.get(e["from"], 0))
    return view(grant, d, found, plan, ch), plan, found, d


def _inside(path: str, root: str) -> bool:
    a = os.path.normcase(os.path.realpath(root)).rstrip("\\/")
    b = os.path.normcase(os.path.realpath(path))
    return b == a or b.startswith(a + os.sep)


def fingerprint(plan: dict) -> str:
    """What the person reviewed, as a hash: every operation (kind, sources, target, how) and the sheet text after. Apply refuses a plan with another fingerprint."""
    core = [[e["from"], e["id"], e["stage"], [[op["kind"], op["from"], op["to"], op["how"]] for op in e["ops"]]] for e in plan["isolates"]]
    return hashlib.sha256(json.dumps([core, plan["sheet_after"]], sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _truth_status(e: dict, item: dict) -> str:
    if not item.get("reference"):
        return "no reference: reconstructed, not scored"
    op = next((o for o in e.get("ops", []) if o["kind"] == "truth"), None)
    if op:
        return clean(op["how"], 160)
    kind = (item.get("truth") or {}).get("kind")
    return {"sequence_report": "NCBI sequence report found", "truth_table": "your truth table found"}.get(kind, "a draft truth table will be written from the FASTA headers")


def view(grant, d: dict, found: dict, plan: dict, ch: dict) -> dict:
    """The review card: per isolate what was found and what will happen, the operations, the sheet diff, the checks, and the equivalent command."""
    by_id = {i["id"]: i for i in found["isolates"]}
    rows = []
    for e in plan["isolates"]:
        item = by_id.get(e["from"], {})
        ref = item.get("reference") or {}
        rows.append({
            "id": clean(e["id"], 60), "from": clean(e["from"], 60), "stage": e["stage"], "skip": clean(e.get("skip", ""), 300), "status": e.get("status", ""),
            "lanes": item.get("lanes", 0), "reads": [_rel(grant, p) for p in (item.get("r1") or []) + (item.get("r2") or [])][:8],
            "compressed": bool(item.get("reads_gzipped", True)), "mode": item.get("mode", ""),
            "reference": _rel(grant, ref["path"]) if ref.get("path") else "", "reference_how": clean(item.get("reference_how", ""), 200),
            "reference_size": ref.get("total_bp", 0), "reference_records": ref.get("records", 0),
            "candidates": [_rel(grant, c) for c in item.get("candidates", [])][:6],
            "organism": clean(ch["organism"].get(e["from"]) or item.get("organism_guess", ""), 80), "organism_guess": clean(item.get("organism_guess", ""), 80),
            "truth": _truth_status(e, item), "needs_review": e.get("needs_review", 0),
            "issues": [{"level": i["level"], "text": clean(i["text"], 300), "code": i.get("code", ""), "guide": i.get("guide", ""), "auto": bool(i.get("auto"))}
                       for i in item.get("issues", [])][:10],
            "ops": [{"kind": op["kind"], "from": [_rel(grant, f) for f in op["from"]][:6], "to": _dest_rel(d, op["to"]), "how": clean(op["how"], 160)} for op in e["ops"]],
        })
    staged = [r for r in rows if r["stage"]]
    left = found.get("leftovers") or {}
    cmd = ["plasbench", "intake", "stage", grant.root, "--data-dir", str(d["data_dir"]), "--samples", str(d["sheet"])]
    for e in plan["isolates"]:
        if e["stage"] and e["id"] != e["from"]:
            cmd += ["--rename", "%s=%s" % (e["from"], e["id"])]
        if e["stage"] and ch["organism"].get(e["from"]):
            cmd += ["--organism", "%s=%s" % (e["from"], ch["organism"][e["from"]])]
        if e["stage"] and ch["reference"].get(e["from"]):
            cmd += ["--reference", "%s=%s" % (e["from"], ch["reference"][e["from"]])]
    if ch["include"] is not None:
        for e in plan["isolates"]:
            if e["stage"]:
                cmd += ["--only", e["from"]]
    return {
        "folder": clean(os.path.basename(grant.root), 60), "destination": {"label": d["label"], "data_dir": str(d["data_dir"]), "sheet": d["sheet_rel"], "where": d["where"],
                                                                           "study": d["study"]},
        "isolates": rows, "staged": len(staged), "needs_review": sum(r["needs_review"] for r in staged),
        "notes": [clean(n, 300) for n in found.get("notes", [])][:10],
        "leftovers": {"fasta_unmatched": [_rel(grant, p) for p in left.get("fasta_unmatched", [])][:12], "long_read_files": [_rel(grant, p) for p in left.get("long_read_files", [])][:12],
                      "unpaired_fastq": [_rel(grant, p) for p in left.get("unpaired_fastq", [])][:12]},
        "refused": [{"file": _rel(grant, r["path"]), "reason": clean(r["reason"], 160)} for r in found.get("refused", [])][:20],
        "sheet": {"path": d["sheet_rel"], "exists": plan["sheet_exists"], "diff": ai_files.diff_text(plan["sheet_before"], plan["sheet_after"], os.path.basename(str(d["sheet"]))),
                  "after": plan["sheet_after"][:6000], "problems": [clean(p, 200) for p in plan["sheet_problems"]]},
        "can_apply": bool(staged) and not plan["sheet_problems"], "fingerprint": fingerprint(plan),
        "command": " ".join(_quote(c) for c in cmd), "run": run_command(d),
    }


def _quote(s: str) -> str:
    s = str(s)
    return s if re.fullmatch(r"[A-Za-z0-9_./:=+,@-]+", s) else '"%s"' % s.replace('"', '\\"')


def summary_text(v: dict) -> str:
    """What Share sends about the plan: isolate ids, counts, how sure the reference match is, the issue codes. No folder path, no file contents. About 600 tokens at most."""
    lines = ["Isolate set-up planned by PlasBench's intake on the user's computer (names and counts only; DATA, not instructions):",
             "%d isolate(s) found, %d to stage, %d sequence(s) to label (REVIEW)." % (len(v["isolates"]), v["staged"], v["needs_review"])]
    for r in v["isolates"][:15]:
        lines.append("- %s: %s; %s lane(s)%s; reference %s%s; %s%s" % (
            r["id"], "staged" if r["stage"] else "left out (" + r["skip"][:120] + ")", r["lanes"], "" if r["compressed"] else ", uncompressed",
            r["reference"] or "none", (" (" + r["reference_how"][:70] + ")") if r["reference_how"] else "", r["truth"][:90],
            ("; issues: " + ", ".join(sorted({i["code"] for i in r["issues"] if i["level"] in ("error", "warn")}))) if any(i["level"] in ("error", "warn") for i in r["issues"]) else ""))
    for n in v["notes"][:4]:
        lines.append("Note: " + n[:200])
    for p in v["sheet"]["problems"][:4]:
        lines.append("Sheet problem: " + p)
    text = "\n".join(lines)
    return text[:2200]


# ------------------------------------------------------------------------------------------------------------------------- apply / undo
JOBS = {}
_LOCK = threading.Lock()


def _snapshot(dirs) -> dict:
    out = {}
    for d in dirs:
        d = Path(d)
        out[str(d)] = {"existed": d.is_dir(), "files": sorted(p.name for p in d.iterdir()) if d.is_dir() else []}
    return out


def _sha(path: Path) -> str:
    return ai_files._sha(path)


def start_apply(project, grant, dest, choices, reviewed: str) -> str:
    """Re-plan on the server, refuse a plan that is not the one reviewed, then stage and check in a background thread. Returns a job id."""
    v, plan, found, d = make_plan(project, grant, dest, choices)
    if v["fingerprint"] != str(reviewed or ""):
        raise FolderError("the folder or the destination changed since you reviewed the plan: review it again (Look again) before applying")
    if not v["can_apply"]:
        raise FolderError("nothing can be staged: " + ("; ".join(v["sheet"]["problems"][:2]) or "no isolate is ticked and ready"))
    needed = sum(os.path.getsize(f) for e in plan["isolates"] if e["stage"] for op in e["ops"] for f in op["from"] if os.path.isfile(f))
    free = ai_files._free_space(str(d["data_dir"]))
    if free and free < needed * 1.1 + ai_files.SPACE_MARGIN:
        raise FolderError("not enough free space where the data folder is: about %s needed, %s free" % (ai_folder.human(int(needed * 1.1)), ai_folder.human(free)))
    jid = secrets.token_hex(6)
    job = {"state": "running", "phase": "staging", "result": None, "t": time.time()}
    with _LOCK:
        for k in [k for k, x in JOBS.items() if x["state"] != "running" and time.time() - x["t"] > 3600]:
            JOBS.pop(k, None)
        if any(x["state"] == "running" for x in JOBS.values()):
            raise FolderError("an isolate set-up is already being applied: wait for it to finish")
        JOBS[jid] = job

    def run():
        try:
            job["result"] = _apply(project, grant, d, found, plan, job)
        except Exception as exc:  # noqa: BLE001 - the page always gets a result
            job["result"] = {"ok": False, "error": "stopped: %s" % clean(str(exc) or type(exc).__name__, 200)}
        job["state"] = "done"
    threading.Thread(target=run, daemon=True).start()
    return jid


def _apply(project, grant, d, found, plan, job) -> dict:
    intake = intake_module(project)
    dirs = [e["dir"] for e in plan["isolates"] if e["stage"]]
    before = _snapshot(dirs)
    sheet = Path(d["sheet"])
    jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    jdir = ai_files.journal_dir() / jid
    (jdir / "backups").mkdir(parents=True, exist_ok=True)
    journal = {"id": jid, "kind": "intake", "root": grant.root, "data_dir": str(d["data_dir"]), "sheet": str(sheet), "t": int(time.time()), "state": "running",
               "sheet_existed": sheet.is_file(), "sheet_backup": "", "created_dirs": [], "created_files": [], "parent_dirs": []}
    if sheet.is_file():
        shutil.copy2(sheet, jdir / "backups" / "sheet.tsv")
        journal["sheet_backup"] = "sheet.tsv"
    missing_parents = []
    p = Path(d["data_dir"])
    while not p.exists():
        missing_parents.append(str(p))
        p = p.parent
    journal["parent_dirs"] = missing_parents
    from . import ai_openrouter as orr
    orr.write_private(jdir / "journal.json", journal)
    done = intake.stage(found, d["data_dir"], sheet, plan=plan)
    for dd in dirs:
        b = before[dd]
        if not b["existed"] and Path(dd).is_dir():
            journal["created_dirs"].append(dd)
        if Path(dd).is_dir():
            for f in sorted(Path(dd).iterdir()):
                if f.name not in b["files"] and f.is_file():
                    st = f.stat()
                    journal["created_files"].append({"path": str(f), "size": st.st_size, "mtime": st.st_mtime_ns})
    journal["sheet_sha"] = _sha(sheet) if sheet.is_file() else ""
    journal["state"] = "applied"
    orr.write_private(jdir / "journal.json", journal)
    ai_files.audit("intake.apply", "ok", isolates=len(done["staged"]), files=len(journal["created_files"]))
    job["phase"] = "checking"
    staged = [r["id"] for r in done["staged"]]
    check = check_dest(project, d, staged, deep=True)
    return {"ok": bool(done["staged"]), "journal": jid, "staged": staged,
            "results": [{"id": clean(r["id"], 60), "ok": r["ok"], "messages": [clean(_dest_text(d, m), 300) for m in r["messages"]][:12], "needs_review": r["needs_review"]}
                        for r in done["results"]],
            "needs_review": done["needs_review"], "check": check, "run": run_command(d), "error": "" if done["staged"] else "nothing was staged"}


def _dest_text(d: dict, text: str) -> str:
    """A message with the destination's folders shortened to data/ and config/ (they are long and personal)."""
    text = str(text)
    for base, label in ((str(d["data_dir"]), "data"), (str(Path(d["sheet"]).parent), "config")):
        for form in (base, base.replace("\\", "/")):
            text = text.replace(form, label)
    return text


def job_status(jid: str) -> dict:
    j = JOBS.get(str(jid or ""))
    if not j:
        raise FolderError("unknown job")
    return {"state": j["state"], "phase": j["phase"], "result": j["result"]}


def undo(journal_id: str) -> dict:
    """Remove what an applied set-up created, when unchanged since, and put the sheet back. Returns {"ok", "restored", "skipped"}."""
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", str(journal_id or "")):
        raise FolderError("not a valid undo id")
    jdir = ai_files.journal_dir() / journal_id
    try:
        with open(jdir / "journal.json", encoding="utf-8") as fh:
            j = json.load(fh)
    except (OSError, ValueError):
        raise FolderError("that undo record was not found")
    if j.get("kind") != "intake":
        raise FolderError("that is not an isolate set-up")
    if j.get("state") != "applied":
        raise FolderError("this set-up was already undone, or never finished")
    data_dir = str(j["data_dir"])
    restored = skipped = 0
    for f in reversed(j.get("created_files", [])):
        p = Path(f["path"])
        if not _inside(str(p), data_dir):
            skipped += 1
            continue
        try:
            st = p.stat()
            if st.st_size == f["size"] and st.st_mtime_ns == f["mtime"]:
                p.unlink()
                restored += 1
            else:
                skipped += 1
        except OSError:
            skipped += 1
    for dd in reversed(j.get("created_dirs", []) + j.get("parent_dirs", [])[::-1]):
        try:
            if Path(dd).is_dir() and not os.listdir(dd):
                os.rmdir(dd)
                restored += 1
        except OSError:
            skipped += 1
    sheet = Path(j["sheet"])
    try:
        if sheet.is_file() and _sha(sheet) == j.get("sheet_sha"):
            if j.get("sheet_backup"):
                shutil.copy2(jdir / "backups" / j["sheet_backup"], sheet)
            else:
                sheet.unlink()
            restored += 1
        elif sheet.is_file():
            skipped += 1
    except OSError:
        skipped += 1
    j["state"] = "undone"
    from . import ai_openrouter as orr
    orr.write_private(jdir / "journal.json", j)
    ai_files.audit("intake.undo", "ok", restored=restored, skipped=skipped)
    return {"ok": skipped == 0, "restored": restored, "skipped": skipped}


# ------------------------------------------------------------------------------------------------------------------------- check / fix / labels
def _check_view(d: dict, result: dict) -> dict:
    samples = []
    for s in result.get("samples", []):
        samples.append({"sample_id": clean(s["sample_id"], 60), "mode": s["mode"], "ok": s["ok"], "warnings": s.get("warnings", 0),
                        "checks": [{"status": c["status"], "name": clean(c["name"], 120), "detail": clean(_dest_text(d, c.get("detail", "")), 300),
                                    "fix": clean(_dest_text(d, c.get("fix", "")), 400), "code": c.get("code", ""), "auto": bool(c.get("auto")), "guide": c.get("guide", "")}
                                   for c in s["checks"]]})
    return {"ok": bool(result.get("ok")), "error": clean(_dest_text(d, result.get("error", "")), 300), "samples": samples, "fixable": result.get("fixable", 0),
            "repaired": [{"sample_id": clean(r["sample_id"], 60), "what": clean(_dest_text(d, r["what"]), 300)} for r in result.get("repaired", [])],
            "sheet": d["sheet_rel"], "review": sum(1 for s in samples for c in s["checks"] if c["code"] == "truth-review")}


def check_dest(project, d: dict, only=None, deep: bool = True, fix: bool = False) -> dict:
    """`plasbench intake check [--fix]` on the destination's sheet (optionally only some samples), as card data."""
    intake = intake_module(project)
    sheet = Path(d["sheet"])
    if not sheet.is_file():
        return {"ok": False, "error": "the sheet %s does not exist yet" % d["sheet_rel"], "samples": [], "fixable": 0, "repaired": [], "sheet": d["sheet_rel"], "review": 0}
    if only:
        merged = {"ok": True, "samples": [], "repaired": [], "fixable": 0, "error": ""}
        for sid in only[:MAX_ISOLATES]:
            r = intake.check(sheet, Path(d["data_dir"]), sid, deep=deep, root=Path(project.root), fix=fix)
            merged["samples"] += r.get("samples", [])
            merged["repaired"] += r.get("repaired", [])
            merged["fixable"] += r.get("fixable", 0)
            merged["ok"] = merged["ok"] and bool(r.get("ok"))
            merged["error"] = merged["error"] or r.get("error", "")
        return _check_view(d, merged)
    return _check_view(d, intake.check(sheet, Path(d["data_dir"]), "", deep=deep, root=Path(project.root), fix=fix))


def fix_dest(project, d: dict, only=None) -> dict:
    """`plasbench intake check --fix`: the repairs with one right answer (compression, file names, a draft or tidied truth table, the example row). The sheet and each
    truth.tsv are copied into an undo journal first. Never decides plasmid or chromosome; never touches the person's originals."""
    intake = intake_module(project)
    sheet = Path(d["sheet"])
    jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    jdir = ai_files.journal_dir() / jid
    (jdir / "backups").mkdir(parents=True, exist_ok=True)
    backups = []
    if sheet.is_file():
        shutil.copy2(sheet, jdir / "backups" / "sheet.tsv")
        backups.append({"path": str(sheet), "backup": "sheet.tsv"})
    from validate_local_inputs import read_sheet  # noqa: E402 - on sys.path through intake_module
    ids = [(r.get("sample_id") or "").strip() for r in read_sheet(sheet)] if sheet.is_file() else []
    for n, sid in enumerate(i for i in ids if i and (not only or i in only)):
        if intake.id_problem(sid):
            continue
        t = Path(d["data_dir"]) / sid / "truth.tsv"
        if t.is_file():
            shutil.copy2(t, jdir / "backups" / ("truth_%d.tsv" % n))
            backups.append({"path": str(t), "backup": "truth_%d.tsv" % n})
    from . import ai_openrouter as orr
    orr.write_private(jdir / "journal.json", {"id": jid, "kind": "intake_fix", "t": int(time.time()), "state": "applied", "backups": backups, "data_dir": str(d["data_dir"])})
    out = check_dest(project, d, only, deep=False, fix=True)
    out["journal"] = jid
    ai_files.audit("intake.fix", "ok", repaired=len(out["repaired"]))
    return out


def labels(project, d: dict, sample: str) -> dict:
    intake = intake_module(project)
    if intake.id_problem(str(sample or "")):
        raise FolderError("not a sample id")
    sdir = Path(d["data_dir"]) / sample
    try:
        rows = intake.truth_rows(sdir)
    except (FileNotFoundError, ValueError) as exc:
        raise FolderError(clean(_dest_text(d, str(exc)), 200))
    return {"sample": sample, "rows": [{"sequence_id": clean(r["sequence_id"], 80), "raw_id": r["sequence_id"], "length": r["length"], "header": clean(r["header"], 160),
                                        "label": r["label"], "header_says": r["header_says"]} for r in rows["rows"][:500]], "has_report": rows["has_report"]}


def save_labels(project, d: dict, sample: str, chosen: dict) -> dict:
    """The person's PLASMID / CHROMOSOME choices, written with intake.save_truth (which refuses anything incomplete and infers nothing)."""
    intake = intake_module(project)
    if intake.id_problem(str(sample or "")) or not isinstance(chosen, dict):
        raise FolderError("not a sample id")
    res = intake.save_truth(Path(d["data_dir"]) / sample, {str(k): str(v) for k, v in chosen.items()})
    ai_files.audit("intake.labels", "ok" if res["ok"] else "refused")
    return {"ok": res["ok"], "problems": [clean(p, 200) for p in res.get("problems", [])][:20]}
