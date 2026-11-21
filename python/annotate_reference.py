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


def run(command, timeout):
    """Return (stdout, "") or (None, reason); never raise into the run. The command's own process group is killed on a timeout (ISEScan starts workers), and it never reads
    this process's stdin."""
    try:
        proc = subprocess.Popen(command, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=(os.name == "posix"))
    except OSError as exc:
        return None, f"{command[0]} did not start: {exc}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
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
TYPICAL_SECONDS = {"mob_typer": 108, "abricate": 13, "amrfinder": 60, "isescan": 663, "barrnap": 31, "isfinder": 30}
TYPICAL_GENOME_MBP = 4.0
SLOW_FACTOR = 2.0


def typical_seconds(name, total_bp):
    base = TYPICAL_SECONDS.get("abricate" if name.startswith("abricate") else name)
    if base is None:
        return None
    return base * max(0.25, (total_bp / 1e6) / TYPICAL_GENOME_MBP)


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


def call_isescan(reference, timeout, sequences, workdir, threads=1):
    executable = shutil.which("isescan.py") or shutil.which("isescan")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "isescan is not installed"}
    version = tool_version(executable)
    status, detail, fix = tool_readiness.check("isescan")
    if status == "miss":      # ISEScan would search for minutes and then fail in its clustering step: do not start it
        return [], {"status": "not_evaluated", "reason": "%s: %s" % (detail, fix), "version": version}
    _, error = run([executable, "--seqfile", str(reference), "--output", str(workdir), "--nthread", str(threads)], timeout)
    if error:
        return [], _failed(error, version)
    features = []
    for path in Path(workdir).rglob("*.csv"):
        features.extend(parse_tabular(path.read_text(encoding="utf-8").replace(",", "\t"),
                                      {"sequence": "seqID", "start": "isBegin", "end": "isEnd",
                                       "label": "family"}, "insertion_sequence", "isescan",
                                      version, sequences))
    return features, {"status": "ok", "version": version, "features": len(features)}


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
    timeouts = {"*": args.timeout} if args.timeout else ({} if args.timeout == 0 else annotation_timeouts(total_bp))
    threads = max(1, args.threads)
    small = max(1, min(4, threads // 4))
    calls = (
        ("mob_typer", lambda: call_mob_typer(args.reference, timeout_for(timeouts, "mob_typer"), sequences, small)),
        ("abricate_amr", lambda: call_abricate(args.reference, args.amr_database, timeout_for(timeouts, "abricate"), sequences, threads=small)),
        *[("abricate_replicon" if index == 0 else f"abricate_replicon_{name}",
           lambda name=name: call_abricate(args.reference, name, timeout_for(timeouts, "abricate"), sequences, kind="replicon", threads=small))
          for index, name in enumerate([n for n in args.replicon_database.replace(",", " ").split() if n]
                                       or ["plasmidfinder"])],
        ("amrfinder", lambda: call_amrfinder(args.reference, timeout_for(timeouts, "amrfinder"), sequences, max(1, threads // 2))),
        ("isescan", lambda: call_isescan(args.reference, timeout_for(timeouts, "isescan"), sequences, workdir, threads)),
        ("isfinder", lambda: call_isfinder(args.reference, args.isfinder_fasta, timeout_for(timeouts, "isfinder"), sequences)),
        ("barrnap", lambda: call_barrnap(args.reference, timeout_for(timeouts, "barrnap"), sequences, small)),
    )
    cache_id = fingerprint = None
    if args.cache_dir:
        try:
            fingerprint = caller_fingerprint(args.amr_database, args.replicon_database, args.isfinder_fasta)
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

    features, provenance, slow_noted = [], {}, set()
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [(name, pool.submit(timed, name, call)) for name, call in calls]
        pending = {future for _, future in futures}
        t0 = time.time()
        while pending:
            _, pending = wait(pending, timeout=60)
            if pending:
                running = sorted(name for name, future in futures if future in pending)
                print(f"  annotation: {int(time.time() - t0)} s in, still running: {', '.join(running)}", flush=True)
                for name in running:      # a caller far past its usual time: say so once (typical times are estimates for a 6-CPU laptop)
                    typical = typical_seconds(name, total_bp)
                    ran = time.time() - started.get(name, t0)
                    if typical and ran > SLOW_FACTOR * typical and name not in slow_noted:
                        slow_noted.add(name)
                        print(f"  annotation: NOTE {name} has run {ran / 60:.0f} min; typical is about {typical / 60:.0f} min for this genome size (estimated, 6-CPU laptop). "
                              f"It is stopped at its limit ({timeout_for(timeouts, name) or 'none'} s) unless ANNOTATION_TIMEOUT_SECONDS says otherwise.", flush=True)
        for name, future in futures:                  # collected in the original order: output stays the same
            found, status = future.result()
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
