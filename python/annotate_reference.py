#!/usr/bin/env python3
"""Derive replicon, MOB, IS, and AMR annotations for a reference by calling
installed annotation tools, so context features stop depending on hand curation.

Design
------
PlasBench does not reimplement annotation. It shells out to whichever callers
are installed, normalises their output into one feature table, and records the
tool and database version behind every feature. A caller that is absent is
reported as `not_evaluated` for its feature class -- never as an absence of the
feature, which would silently understate recovery.

Supported callers (all optional):
  mob_typer     replicon and relaxase/MOB typing        -> replicon, mob
  abricate      AMR / plasmid-replicon databases        -> amr, replicon
  amrfinder     NCBI AMRFinderPlus                      -> amr
  isescan       insertion sequences (de novo)           -> insertion_sequence
  isfinder      insertion sequences by BLAST against a curated ISFinder FASTA (--isfinder-fasta,
                optional; the FASTA is downloaded from ISFinder by the user, never shipped)
                                                          -> insertion_sequence
  barrnap       ribosomal RNA genes                     -> rRNA
                (chromosomal evidence for label_truth_evidence.py)

Output is the `feature_truth` TSV the visualization already consumes:
sequence_id, start, end, feature_type, label, source, version
Coordinates are 0-based half-open on the reference, matching the scorer.

Standard library only; the callers themselves are external.
"""

import argparse
import csv
import hashlib
import json
import shutil
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tool_readiness  # noqa: E402  (what a tool needs to work, not only that it starts)
import awake_clock  # noqa: E402  (time the computer was asleep is not time a caller took)


FIELDS = ("sequence_id", "start", "end", "feature_type", "label", "source", "version")
CALLERS = ("mob_typer", "abricate", "amrfinder", "isescan", "isfinder", "barrnap")
# ISFinder BLAST thresholds: a hit counts as an IS copy when it aligns at least this identity over at least this share of
# the curated IS sequence (a partial hit is a fragment, not an element).
ISFINDER_MIN_IDENTITY = 90.0
ISFINDER_MIN_SUBJECT_COVERAGE = 0.80


def tool_version(executable, flags=("--version", "-v", "version")):
    for flag in flags:
        try:
            result = subprocess.run([executable, flag], text=True, capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        if output:
            return output[0].strip()
    return "unreported"


NOISE = ("running:",)          # lines a tool prints to say what it is doing (AMRFinderPlus echoes its command line): never the reason for a failure


def _reason(command, returncode, stderr, stdout):
    """One line saying WHY a caller failed: the last informative lines of its stderr (else stdout), not the first (a traceback starts with 'Traceback ...')."""
    lines = [ln.strip() for ln in ((stderr or "") + chr(10) + (stdout or "")).splitlines() if ln.strip() and not ln.strip().lower().startswith(NOISE)]
    stderr_lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip() and not ln.strip().lower().startswith(NOISE)]
    picked = (stderr_lines or lines)[-3:]
    detail = " | ".join(picked) if picked else "no output"
    return "%s exited %s: %s" % (os.path.basename(command[0]), returncode, detail[:400])


def _failed(error, version=None):
    """The status record of a caller that did not finish: timed_out when it hit its time limit, else failed. Neither is ever cached."""
    status = {"status": "timed_out" if str(error).startswith("timed out") else "failed", "reason": error}
    if version:
        status["version"] = version
    return status


POLL_SECONDS = 5.0


def run(command, timeout):
    """Return (stdout, "") or (None, reason); never raise into the run. The command's own process group is killed on a timeout (ISEScan starts workers), and it never reads
    this process's stdin."""
    try:
        proc = subprocess.Popen(command, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=(os.name == "posix"))
    except OSError as exc:
        return None, f"{command[0]} did not start: {exc}"
    # The limit counts time the computer was awake: a laptop that sleeps for an hour must not get its callers killed for being "slow" (a real run lost mob_typer,
    # AMRFinder and barrnap results that way). The wait is cut into short polls so a sleep is noticed (python/awake_clock.py).
    timer = awake_clock.AwakeTimer(expected=POLL_SECONDS)
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            timer.tick()
            if not timeout or timer.elapsed() <= timeout:
                continue
        # the awake time limit has run out
        try:
            if os.name == "posix":
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
        try:
            proc.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None, "timed out after %d s (ANNOTATION_TIMEOUT_SECONDS; the caller was stopped, its result is not used and not cached)" % int(timeout or 0)
    if proc.returncode != 0:
        return None, _reason(command, proc.returncode, stderr, stdout)
    return stdout, ""


# Typical seconds per caller for a ~4 Mbp genome on a 6-CPU laptop. ESTIMATED: abricate, barrnap and mob_typer were measured once; ISEScan's 663 s is one run that
# ended in a failure (its usual time is a few minutes), so it is the least reliable. Used only for the "still running, typical N min" note, never to stop a caller.
# Re-based 2026-11-22 on four real isolates (5 to 9 Mbp) on a 6-CPU WSL2 laptop with the data folder on a Windows drive, scaled to 4 Mbp: MEASURED, but taken while the callers
# were oversubscribed (13 threads on 6 CPUs, whole-genome ISEScan); the new thread plan and plasmid-only ISEScan should be faster, so these are upper figures. isfinder is unmeasured.
TYPICAL_SECONDS = {"mob_typer": 360, "abricate": 40, "amrfinder": 240, "isescan": 1400, "barrnap": 240, "isfinder": 30}
TYPICAL_GENOME_MBP = 4.0
SLOW_FACTOR = 2.0


def typical_seconds(name, total_bp):
    base = TYPICAL_SECONDS.get("abricate" if name.startswith("abricate") else name)
    if base is None:
        return None
    return base * max(0.25, (total_bp / 1e6) / TYPICAL_GENOME_MBP)


# One switch per caller (config/config.sh, shown in the window's Workflow and Settings): a caller switched off is not run and is recorded as not evaluated with the reason, never as
# "no such feature found". All default to on.
CALLER_SWITCHES = {"mob_typer": "ANNOTATE_WITH_MOB_TYPER", "abricate": "ANNOTATE_WITH_ABRICATE", "amrfinder": "ANNOTATE_WITH_AMRFINDER",
                   "isescan": "ANNOTATE_WITH_ISESCAN", "barrnap": "ANNOTATE_WITH_BARRNAP"}


def callers_switched_off(environ=None):
    environ = os.environ if environ is None else environ
    return sorted(name for name, key in CALLER_SWITCHES.items() if str(environ.get(key, "1")).strip().lower() in ("0", "no", "off", "false"))


def annotation_timeouts(total_bp, environ=None):
    """{caller: seconds or None}. ANNOTATION_TIMEOUT_SECONDS: a number = that many seconds for every caller; 0, off or none = no limit. Default: max(300, 150 s per Mbp)
    per caller, ISEScan three times that (it is the slow one), never below 900 s."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get("ANNOTATION_TIMEOUT_SECONDS", "")).strip().lower()
    if raw in ("0", "off", "none", "no", "false"):
        return {}
    if raw.isdigit():
        return {"*": int(raw)}
    mbp = total_bp / 1e6
    base = max(300, int(150 * mbp))
    return {"*": base, "isescan": max(900, 3 * base)}


def thread_plan(threads):
    """(quick, amrfinder, isescan) threads for a total of `threads` CPUs. The callers run at the same time, so the shares are chosen to add up near the machine's size:
    the short callers (mob_typer, the abricate runs, barrnap) get one thread each, AMRFinderPlus a third of the CPUs, and ISEScan the rest minus two (a real run gave ISEScan
    all 6 threads on top of 7 more and the "short" callers took 10 times their usual time). The share only changes speed, never a result."""
    threads = max(1, int(threads))
    return 1, max(1, threads // 3), max(1, threads - 2)


def timeout_for(timeouts, name):
    if not timeouts:
        return None
    key = "isescan" if name == "isescan" else name
    return timeouts.get(key) or timeouts.get("*")


def parse_tabular(text, mapping, feature_type, source, version, sequence_filter=None):
    """Normalise a headed TSV into feature rows using a column mapping."""
    features = []
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    for row in reader:
        try:
            sequence = (row.get(mapping["sequence"]) or "").split()[0]
            start = int(float(row.get(mapping["start"]) or 0))
            end = int(float(row.get(mapping["end"]) or 0))
        except (ValueError, IndexError):
            continue
        if not sequence or end <= start:
            continue
        if sequence_filter and sequence not in sequence_filter:
            continue
        label = (row.get(mapping["label"]) or "").strip() or feature_type
        # Callers report 1-based inclusive coordinates; the scorer is 0-based half-open.
        features.append({"sequence_id": sequence, "start": max(0, start - 1), "end": end,
                         "feature_type": feature_type, "label": label,
                         "source": source, "version": version})
    return features


def call_abricate(reference, database, timeout, sequences, kind=None, threads=1):
    executable = shutil.which("abricate")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "abricate is not installed"}
    version = tool_version(executable)
    text, error = run([executable, "--nopath", "--threads", str(threads), "--db", database, str(reference)], timeout)
    if text is None:
        return [], _failed(error, version)
    kind = kind or ("replicon" if database in ("plasmidfinder", "PlasmidFinder") else "amr")
    features = parse_tabular(text, {"sequence": "SEQUENCE", "start": "START", "end": "END",
                                    "label": "GENE"}, kind, f"abricate:{database}", version, sequences)
    return features, {"status": "ok", "version": version, "database": database, "features": len(features)}


def call_amrfinder(reference, timeout, sequences, threads=1):
    executable = shutil.which("amrfinder")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "amrfinder is not installed"}
    version = tool_version(executable)
    status, detail, fix = tool_readiness.check("amrfinder")
    if status == "miss":      # a missing database fails in 0 s and would be recorded as a failure of the isolate: say what is wrong instead
        return [], {"status": "not_evaluated", "reason": "%s: %s" % (detail, fix), "version": version}
    db = tool_readiness.amrfinder_db_dir()
    text, error = run([executable, "--threads", str(threads), "-n", str(reference)] + (["-d", db] if db else []), timeout)
    if text is None:
        return [], _failed(error, version)
    features = parse_tabular(text, {"sequence": "Contig id", "start": "Start", "end": "Stop",
                                    "label": "Element symbol"}, "amr", "amrfinderplus", version, sequences)
    if not features:
        # AMRFinderPlus renamed these columns between releases.
        features = parse_tabular(text, {"sequence": "Contig id", "start": "Start", "end": "Stop",
                                        "label": "Gene symbol"}, "amr", "amrfinderplus", version, sequences)
    return features, {"status": "ok", "version": version, "features": len(features)}


import setting_options  # noqa: E402

ISESCAN_SCOPES = tuple(setting_options.values("ISESCAN_SCOPE"))


def read_truth_molecules(truth_path):
    """{sequence_id: PLASMID|CHROMOSOME|...} from a truth.tsv, or None when it cannot be read."""
    try:
        with open(truth_path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, TypeError, UnicodeDecodeError):
        return None
    out = {}
    for row in rows:
        name = (row.get("sequence_id") or "").strip()
        if name:
            out[name] = (row.get("molecule_type") or "").strip().upper()
    return out or None


def isescan_plan(scope, truth_path, sequences):
    """What ISEScan searches. Returns a dict: scope (the requested one), effective (plasmids|all), searched (sequence ids, in file order), not_searched (ids), reason.
    plasmids = only the replicons the truth table labels PLASMID (ids and coordinates are unchanged: ISEScan reports per sequence). If the truth table is missing, empty or
    names none of this reference's sequences, everything is searched and the reason says so: scope never silently drops coverage it cannot justify."""
    scope = (scope or "plasmids").strip().lower()
    ids = list(sequences)
    if scope not in ISESCAN_SCOPES:
        scope = "plasmids"
    if scope == "all":
        return {"scope": "all", "effective": "all", "searched": ids, "not_searched": [], "reason": ""}
    molecules = read_truth_molecules(truth_path) if truth_path else None
    if molecules is None:
        return {"scope": "plasmids", "effective": "all", "searched": ids, "not_searched": [], "reason": "no readable truth table, so every sequence was searched"}
    known = [name for name in ids if name in molecules]
    if not known:
        return {"scope": "plasmids", "effective": "all", "searched": ids, "not_searched": [],
                "reason": "the truth table names none of this reference's sequences, so every sequence was searched"}
    searched = [name for name in ids if molecules.get(name) == "PLASMID"]
    return {"scope": "plasmids", "effective": "plasmids", "searched": searched, "not_searched": [name for name in ids if name not in searched], "reason": ""}


def scope_label(plan):
    """The short text stored in the cache fingerprint: scope plus the exact sequences searched, so two scopes (or two labelings of the same reference) never share a key."""
    if plan["effective"] == "all":
        return "all"
    return "plasmids:" + hashlib.sha256(("\n").join(plan["searched"]).encode("utf-8")).hexdigest()[:16]


def write_subset_fasta(reference, names, out_path):
    """The records of `reference` whose id (first word of the header) is in `names`, byte for byte."""
    keep, wanted = False, set(names)
    with open(reference, encoding="utf-8") as src, open(out_path, "w", encoding="utf-8", newline="\n") as dst:
        for line in src:
            if line.startswith(">"):
                header = line[1:].strip().split()
                keep = bool(header) and header[0] in wanted
            if keep:
                dst.write(line if line.endswith("\n") else line + "\n")


def call_isescan(reference, timeout, sequences, workdir, threads=1, plan=None):
    executable = shutil.which("isescan.py") or shutil.which("isescan")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "isescan is not installed"}
    version = tool_version(executable)
    status, detail, fix = tool_readiness.check("isescan")
    if status == "miss":      # ISEScan would search for minutes and then fail in its clustering step: do not start it
        return [], {"status": "not_evaluated", "reason": "%s: %s" % (detail, fix), "version": version}
    scope_record = {}
    seqfile, outdir = reference, Path(workdir)
    if plan is not None:
        scope_record = {"scope": plan["effective"], "requested_scope": plan["scope"], "chromosome_searched": not plan["not_searched"],
                        "sequences_searched": plan["searched"], "sequences_not_searched": plan["not_searched"]}
        if plan["reason"]:
            scope_record["scope_note"] = plan["reason"]
        if plan["effective"] == "plasmids":
            if not plan["searched"]:        # the truth table has no plasmid: there is nothing for ISEScan to search
                return [], dict({"status": "ok", "version": version, "features": 0, "note": "no plasmid sequence in the truth table: nothing to search"}, **scope_record)
            outdir = Path(workdir) / "isescan_plasmids"          # its own folder: results of an earlier scope are never read back
            shutil.rmtree(outdir, ignore_errors=True)
            outdir.mkdir(parents=True, exist_ok=True)
            seqfile = Path(workdir) / "isescan_plasmids.fna"
            write_subset_fasta(reference, plan["searched"], seqfile)
    _, error = run([executable, "--seqfile", str(seqfile), "--output", str(outdir), "--nthread", str(threads)], timeout)
    if error:
        return [], dict(_failed(error, version), **scope_record)
    features = []
    for path in outdir.rglob("*.csv"):
        features.extend(parse_tabular(path.read_text(encoding="utf-8").replace(",", "\t"),
                                      {"sequence": "seqID", "start": "isBegin", "end": "isEnd",
                                       "label": "family"}, "insertion_sequence", "isescan",
                                      version, sequences))
    return features, dict({"status": "ok", "version": version, "features": len(features)}, **scope_record)


def parse_isfinder_blast(text, sequences, version, min_identity=ISFINDER_MIN_IDENTITY,
                         min_subject_coverage=ISFINDER_MIN_SUBJECT_COVERAGE):
    """blastn -outfmt '6 qseqid sseqid pident length qstart qend sstart send slen' rows -> insertion_sequence features.
    Keeps hits of at least min_identity percent covering at least min_subject_coverage of the curated IS sequence."""
    features = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 9:
            continue
        try:
            identity, length = float(fields[2]), int(fields[3])
            qstart, qend = int(fields[4]), int(fields[5])
            slen = int(fields[8])
        except ValueError:
            continue
        sequence = fields[0].split()[0]
        if sequences and sequence not in sequences:
            continue
        if identity < min_identity or slen <= 0 or length / slen < min_subject_coverage:
            continue
        start, end = min(qstart, qend), max(qstart, qend)
        features.append({"sequence_id": sequence, "start": max(0, start - 1), "end": end,
                         "feature_type": "insertion_sequence", "label": fields[1].split()[0],
                         "source": "isfinder", "version": version})
    return features


def call_isfinder(reference, fasta, timeout, sequences):
    if not fasta:
        return [], {"status": "not_evaluated", "reason": "no --isfinder-fasta given (ISFINDER_FASTA)"}
    if not Path(fasta).is_file():
        return [], {"status": "not_evaluated", "reason": f"ISFinder FASTA not found: {fasta}"}
    executable = shutil.which("blastn")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "blastn is not installed"}
    version = tool_version(executable)
    text, error = run([executable, "-query", str(reference), "-subject", str(fasta), "-task", "blastn",
                       "-evalue", "1e-10", "-perc_identity", str(ISFINDER_MIN_IDENTITY),
                       "-outfmt", "6 qseqid sseqid pident length qstart qend sstart send slen"], timeout)
    if text is None:
        return [], _failed(error, version)
    features = parse_isfinder_blast(text, sequences, version)
    return features, {"status": "ok", "version": version, "database": Path(fasta).name, "features": len(features)}


def call_barrnap(reference, timeout, sequences, threads=1):
    """rRNA genes (barrnap GFF3, 1-based inclusive -> 0-based half-open)."""
    executable = shutil.which("barrnap")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "barrnap is not installed"}
    version = tool_version(executable)
    text, error = run([executable, "--quiet", "--threads", str(threads), "--kingdom", "bac", str(reference)], timeout)
    if text is None:
        return [], _failed(error, version)
    features = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 9 or fields[2] != "rRNA":
            continue
        sequence = fields[0]
        if sequences and sequence not in sequences:
            continue
        name = ""
        for attribute in fields[8].split(";"):
            if attribute.startswith("Name="):
                name = attribute[5:]
        features.append({"sequence_id": sequence, "start": int(fields[3]) - 1, "end": int(fields[4]),
                         "feature_type": "rRNA", "label": name or "rRNA",
                         "source": "barrnap", "version": version})
    return features, {"status": "ok", "version": version, "features": len(features)}


def mob_db_args(environ=None):
    """['-d', DIR] when the container's MOB-suite database lives in the mounted databases folder (the image's own folder is read-only and holds none), else []."""
    environ = os.environ if environ is None else environ
    if str(environ.get("PLASBENCH_IN_DOCKER", "")) != "1":
        return []
    store = Path(environ.get("PLASBENCH_DB_DIR") or Path.home() / ".plasbench" / "databases") / "mob_suite" / "databases"
    needed = ("status.txt", "ncbi_plasmid_full_seqs.fas", "ncbi_plasmid_full_seqs.fas.msh", "repetitive.dna.fas")
    return ["-d", str(store)] if all((store / n).is_file() and (store / n).stat().st_size for n in needed) else []


def call_mob_typer(reference, timeout, sequences, threads=1):
    """MOB-typer reports per-sequence typing, not coordinates."""
    executable = shutil.which("mob_typer")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "mob_typer is not installed"}
    version = tool_version(executable)
    out = Path(reference).with_suffix(".mobtyper.txt")
    text, error = run([executable, "--multi", "--num_threads", str(threads), "--infile", str(reference),
                       "--out_file", str(out)] + mob_db_args(), timeout)
    if text is None and not out.is_file():
        return [], _failed(error, version)
    if not out.is_file():
        return [], {"status": "failed", "reason": "mob_typer produced no report", "version": version}
    features = []
    with out.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            sequence = (row.get("sample_id") or "").split()[0]
            if not sequence or (sequences and sequence not in sequences):
                continue
            length = sequences.get(sequence) if sequences else None
            for column, kind in (("rep_type(s)", "replicon"), ("relaxase_type(s)", "mob")):
                for label in (row.get(column) or "").split(","):
                    label = label.strip()
                    if label and label != "-":
                        # Typing is per-replicon, so the feature spans the sequence.
                        features.append({"sequence_id": sequence, "start": 0, "end": length or 1,
                                         "feature_type": kind, "label": label,
                                         "source": "mob_typer", "version": version})
    return features, {"status": "ok", "version": version, "features": len(features),
                      "note": "MOB-typer types whole replicons; features span the sequence."}


CACHE_SCHEMA = "1"


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def caller_fingerprint(amr_database, replicon_database, isfinder_fasta):
    """What a cached annotation depends on besides the reference: each caller's version (or 'absent'), the database versions the callers can report
    (AMRFinderPlus -V, the abricate database listing), the database names and the ISFinder FASTA's checksum. Any change gives a new cache key."""
    def probe(name):
        exe = shutil.which(name)
        if not exe:
            return name, "absent"
        text = tool_version(exe)
        if name == "amrfinder":
            out, _ = run([exe, "-V"], 60)
            text = (out or text).replace("\n", " | ")
        if name == "abricate":
            out, _ = run([exe, "--list"], 60)
            text += " | " + hashlib.sha256((out or "").encode("utf-8")).hexdigest()[:16]
        return name, text
    names = ("mob_typer", "abricate", "amrfinder", "isescan.py", "isescan", "barrnap", "blastn")
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        versions = dict(pool.map(probe, names))
    fasta = str(isfinder_fasta or "")
    versions["isfinder_fasta"] = file_sha256(fasta) if fasta and Path(fasta).is_file() else "none"
    versions["amr_database"] = amr_database
    versions["replicon_database"] = " ".join(replicon_database.replace(",", " ").split())
    return versions


def cache_key(reference, fingerprint):
    payload = json.dumps({"schema": CACHE_SCHEMA, "reference_sha256": file_sha256(reference), "callers": fingerprint}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_lookup(cache_dir, key):
    """(features TSV path, saved metadata) for a cached annotation, or (None, None)."""
    table, meta = Path(cache_dir) / f"{key}.tsv", Path(cache_dir) / f"{key}.json"
    try:
        if table.is_file() and meta.is_file():
            return table, json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None, None


def cache_store(cache_dir, key, table, record, fingerprint, reference):
    """Keep this annotation for later runs. Never raises (a read-only or full cache folder just means no cache)."""
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_table, tmp_meta = cache_dir / f"{key}.tsv.tmp{os.getpid()}", cache_dir / f"{key}.json.tmp{os.getpid()}"
        shutil.copyfile(table, tmp_table)
        meta = {"key": key, "created_epoch": int(time.time()), "reference_name": Path(reference).parent.name, "fingerprint": fingerprint, "record": record}
        tmp_meta.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp_table, cache_dir / f"{key}.tsv")
        os.replace(tmp_meta, cache_dir / f"{key}.json")
        return True
    except OSError:
        return False


def reference_sequences(path):
    lengths, name, total = {}, None, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if name:
                    lengths[name] = total
                name, total = line[1:].strip().split()[0], 0
            else:
                total += len(line.strip())
    if name:
        lengths[name] = total
    return lengths


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="feature_truth TSV")
    parser.add_argument("--provenance", type=Path, help="JSON record of caller status and versions")
    parser.add_argument("--amr-database", default="ncbi", help="abricate AMR database (default: ncbi)")
    parser.add_argument("--replicon-database", default="plasmidfinder",
                        help="Abricate replicon database(s), comma or space separated (default plasmidfinder); the first is "
                             "recorded as abricate_replicon, further ones as abricate_replicon_<name>")
    parser.add_argument("--isfinder-fasta", default="",
                        help="optional curated ISFinder FASTA; adds IS annotation by BLAST (blastn -subject, no database build)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="seconds per caller (default: ANNOTATION_TIMEOUT_SECONDS, else max(300, 150 s per Mbp), ISEScan three times that; 0 = no limit)")
    parser.add_argument("--threads", type=int, default=int(os.environ.get("THREADS") or os.cpu_count() or 1),
                        help="CPU threads in total; the callers run at the same time and share them (default: THREADS)")
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--truth", type=Path, default=None,
                        help="the isolate's truth.tsv (default: truth.tsv next to --out); says which sequences are plasmids, for --isescan-scope plasmids")
    parser.add_argument("--isescan-scope", choices=ISESCAN_SCOPES, default=(os.environ.get("ISESCAN_SCOPE") or "plasmids").strip().lower() or "plasmids",
                        help="plasmids (default, ISESCAN_SCOPE): ISEScan searches only the truth-labelled plasmid replicons and the chromosome is recorded as not searched; "
                             "all: every sequence")
    parser.add_argument("--cache-dir", default=os.environ.get("ANNOTATION_CACHE_DIR", ""),
                        help="shared folder of finished annotations, keyed by the reference's checksum and the callers' versions "
                             "(default: ANNOTATION_CACHE_DIR; empty turns the cache off)")
    args = parser.parse_args()
    if not args.reference.is_file():
        raise SystemExit(f"ERROR: reference not found: {args.reference}")

    sequences = reference_sequences(args.reference)
    workdir = args.workdir or args.out.parent / "annotation_work"
    workdir.mkdir(parents=True, exist_ok=True)

    # The callers are independent, so they run at the same time (they used to run one after another, and ISEScan,
    # the slowest by far, had a single thread). ISEScan gets the whole thread allowance; the quick ones share a few.
    total_bp = sum(sequences.values())
    isescan_plan_ = isescan_plan(args.isescan_scope, args.truth or (args.out.parent / "truth.tsv"), sequences)
    timeouts = {"*": args.timeout} if args.timeout else ({} if args.timeout == 0 else annotation_timeouts(total_bp))
    threads = max(1, args.threads)
    small, amr_threads, isescan_threads = thread_plan(threads)

    def build_calls(timeouts, small, amr_threads, isescan_threads):
        return (
            ("mob_typer", lambda: call_mob_typer(args.reference, timeout_for(timeouts, "mob_typer"), sequences, small)),
            ("abricate_amr", lambda: call_abricate(args.reference, args.amr_database, timeout_for(timeouts, "abricate"), sequences, threads=small)),
            *[("abricate_replicon" if index == 0 else f"abricate_replicon_{name}",
               lambda name=name: call_abricate(args.reference, name, timeout_for(timeouts, "abricate"), sequences, kind="replicon", threads=small))
              for index, name in enumerate([n for n in args.replicon_database.replace(",", " ").split() if n]
                                           or ["plasmidfinder"])],
            ("amrfinder", lambda: call_amrfinder(args.reference, timeout_for(timeouts, "amrfinder"), sequences, amr_threads)),
            ("isescan", lambda: call_isescan(args.reference, timeout_for(timeouts, "isescan"), sequences, workdir, isescan_threads, isescan_plan_)),
            ("isfinder", lambda: call_isfinder(args.reference, args.isfinder_fasta, timeout_for(timeouts, "isfinder"), sequences)),
            ("barrnap", lambda: call_barrnap(args.reference, timeout_for(timeouts, "barrnap"), sequences, small)),
        )

    # The callers run at the same time, so together they may ask for more threads than there are CPUs (a real run: 13 threads on 6 CPUs, and three callers hit a limit
    # that assumed they had a CPU each). The time limits grow with that oversubscription, and a caller that still hits its limit is run ONCE more, alone, with twice the limit.
    n_abricate = len([n for n in args.replicon_database.replace(",", " ").split() if n] or ["plasmidfinder"]) + 1
    demanded = 2 * small + n_abricate * small + amr_threads + isescan_threads
    oversub = max(1.0, demanded / float(os.cpu_count() or threads or 1)) if threads > 0 else 1.0
    if timeouts and oversub > 1.0:
        timeouts = {key: (int(value * oversub) if value else value) for key, value in timeouts.items()}
    calls = build_calls(timeouts, small, amr_threads, isescan_threads)
    off = callers_switched_off()

    def gated(name, call):
        base = "abricate" if name.startswith("abricate") else name
        if base in off:
            return lambda: ([], {"status": "not_evaluated", "reason": "switched off (%s=0)" % CALLER_SWITCHES[base]})
        return call

    def gated_calls(items):
        return tuple((name, gated(name, call)) for name, call in items)

    calls = gated_calls(calls)
    off_names = {name for name, _ in calls if ("abricate" if name.startswith("abricate") else name) in off}
    cache_id = fingerprint = None
    if args.cache_dir:
        try:
            fingerprint = caller_fingerprint(args.amr_database, args.replicon_database, args.isfinder_fasta)
            if off:                      # a different set of callers is a different annotation: never reuse one made with all of them
                fingerprint = dict(fingerprint, switched_off=",".join(off))
            if isescan_plan_["effective"] != "all":   # a plasmid-only ISEScan search is a different annotation: the cache never mixes scopes (and "all" keeps its earlier key)
                fingerprint = dict(fingerprint, isescan_scope=scope_label(isescan_plan_))
            cache_id = cache_key(args.reference, fingerprint)
        except OSError:
            cache_id = None
        hit, saved = cache_lookup(args.cache_dir, cache_id) if cache_id else (None, None)
        if hit:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hit, args.out)
            record = dict(saved.get("record", {}))
            record["annotation_cache"] = {"hit": True, "key": cache_id, "created_epoch": saved.get("created_epoch"),
                                          "first_computed_for": saved.get("reference_name"), "fingerprint": saved.get("fingerprint")}
            if args.provenance:
                args.provenance.parent.mkdir(parents=True, exist_ok=True)
                args.provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Annotated {args.reference.name}: reused the stored annotation (same reference checksum and caller versions, key {cache_id[:12]}, "
                  f"first computed for {saved.get('reference_name', '?')}); nothing was run", flush=True)
            return 0

    # Each caller is timed, and a line says when it finishes and which are still running, so a long annotation is never silent.
    started = {}

    def timed(name, call):
        started[name] = time.time()
        found, status = call()
        why = f": {status.get('reason')}" if status.get("status") in ("failed", "timed_out", "not_evaluated") and status.get("reason") else ""
        print(f"  annotation: {name} finished in {time.time() - started[name]:.0f} s ({status.get('status')}, {len(found)} feature(s)){why}", flush=True)
        return found, status

    features, provenance, slow_noted, last_say = [], {}, set(), time.time()
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [(name, pool.submit(timed, name, call)) for name, call in calls]
        pending = {future for _, future in futures}
        t0 = time.time()
        overall = awake_clock.AwakeTimer(expected=5.0)       # progress and "slow" notes count awake time only
        while pending:
            _, pending = wait(pending, timeout=5)
            overall.tick()
            if pending and time.time() - last_say >= 60:
                last_say = time.time()
                running = sorted(name for name, future in futures if future in pending)
                print(f"  annotation: {int(overall.elapsed())} s in, still running: {', '.join(running)}", flush=True)
                for name in running:      # a caller far past its usual time: say so once (typical times are estimates for a 6-CPU laptop)
                    typical = typical_seconds(name, total_bp)
                    ran = overall.elapsed() - (started.get(name, t0) - t0)
                    if typical and ran > SLOW_FACTOR * typical and name not in slow_noted:
                        slow_noted.add(name)
                        print(f"  annotation: NOTE {name} has run {ran / 60:.0f} min; typical is about {typical / 60:.0f} min for this genome size (estimated, 6-CPU laptop). "
                              f"It is stopped at its limit ({timeout_for(timeouts, name) or 'none'} s) unless ANNOTATION_TIMEOUT_SECONDS says otherwise.", flush=True)
        results = {name: future.result() for name, future in futures}
    # One more try, alone and with twice the time, for a caller that hit its limit: a quick tool that was only starved by its neighbours then finishes and its evidence is kept.
    # A caller that fails again stays timed_out (honest), with both attempts in its reason.
    retry_calls = dict(gated_calls(build_calls({key: (value * 2 if value else value) for key, value in timeouts.items()}, min(4, threads), threads, threads))) if timeouts else {}
    for name, _ in futures:
        found, status = results[name]
        if status.get("status") == "timed_out" and name in retry_calls and name not in off_names:
            print(f"  annotation: {name} hit its limit; trying once more, alone, with twice the time", flush=True)
            first = status.get("reason", "")
            started[name] = time.time()
            found2, status2 = retry_calls[name]()
            print(f"  annotation: {name} second attempt finished in {time.time() - started[name]:.0f} s ({status2.get('status')}, {len(found2)} feature(s))", flush=True)
            if status2.get("status") == "timed_out":
                status2 = dict(status2, retried=True, reason=f"timed out twice (first attempt: {first}; second attempt alone with twice the time: {status2.get('reason', '')})")
                print(f"  annotation: {name} timed out twice (a second try, alone and with twice the time, did not finish either): its result is not used and not cached", flush=True)
                found = []
            else:
                status2 = dict(status2, retried=True, first_attempt=first)
                found = found2
            status = status2
        features.extend(found)
        provenance[name] = status

    # Deduplicate identical calls from overlapping databases, keeping provenance.
    seen, unique = set(), []
    for feature in sorted(features, key=lambda f: (f["sequence_id"], f["start"], f["end"],
                                                   f["feature_type"], f["label"], f["source"])):
        key = (feature["sequence_id"], feature["start"], feature["end"],
               feature["feature_type"], feature["label"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(feature)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique)

    evaluated = [name for name, status in provenance.items() if status.get("status") == "ok"]
    missing = [name for name, status in provenance.items() if status.get("status") == "not_evaluated"]
    record = {"schema_version": "1.0", "reference": str(args.reference),
              "features_written": len(unique), "callers": provenance,
              "feature_classes_not_evaluated": missing,
              "meaning": ("Absent callers yield 'not evaluated' for their feature class. "
                          "A missing feature class is not evidence that the feature is absent.")}
    isescan_status = provenance.get("isescan") or {}
    if isescan_status.get("status") == "ok" and isescan_status.get("chromosome_searched") is False:
        # The features of other callers are unaffected. A table that counts insertion sequences per replicon must show these sequences as "not evaluated", never as zero.
        record["not_evaluated_sequences"] = {"insertion_sequence": {"sequences": isescan_status.get("sequences_not_searched", []),
                                                                    "label": "not evaluated (chromosome not searched)",
                                                                    "why": "ISESCAN_SCOPE=plasmids: ISEScan searched only the replicons the truth table labels plasmid"}}
    stored = False
    if cache_id and not any(status.get("status") in ("failed", "timed_out") for status in provenance.values()):
        stored = cache_store(args.cache_dir, cache_id, args.out, record, fingerprint, args.reference)
    if cache_id:
        record["annotation_cache"] = {"hit": False, "key": cache_id, "stored": stored}
    if args.provenance:
        args.provenance.parent.mkdir(parents=True, exist_ok=True)
        args.provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Annotated {args.reference.name}: {len(unique)} feature(s); "
          f"ran {', '.join(evaluated) or 'no caller'}; not evaluated: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
