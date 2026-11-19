#!/usr/bin/env python3
"""
regenerate_visuals.py -- say which report sections a finished results folder can draw, and rebuild the cheap missing inputs in place.

`plasbench check-results RESULTS_DIR` and `plasbench regenerate-visuals RESULTS_DIR` (alias rebuild-report) are thin wrappers over this script.

What it does, in order:
  1. Inspect the folder (its run manifest, scores.tsv, tool_status.tsv, the per-sample folders) and the optional data folder.
  2. Using config/report_inputs.tsv (python/report_inputs.py), list the report sections that cannot draw because a required file is absent, and
     for every absent file whether it can be REGENERATED from inputs that are present, or what it needs that is absent.
  3. Regenerate the cheap ones by calling the scripts the pipeline stages call (same arguments, same settings as the run's manifest), so the
     files are byte-identical to a fresh run on the same inputs:

       --only key        writes                                                          from
       truth             <sample>/truth.tsv                                              sequence_report.jsonl + reference.fna (make_truth.py), or a copy from the data folder
       paf               <sample>/<tool>.pred_vs_ref.paf                                 pred_<tool>.plasmid.fasta + reference.fna (minimap2), or predictions given with --predictions-dir
       alignments        <sample>/visualization/alignment_blocks.json, structural_metrics.tsv, structural_calls.json,
                         <sample>/structural_events.tsv, structural_summary.tsv          truth.tsv + the PAFs (build_visualization_data.py, call_structural_variants.py)
       truth-features    <sample>/truth_features.tsv                                     reference.fna (annotate_reference.py) when an annotation caller is installed
       qc                short_read_qc.tsv, short_read_qc_status.tsv                     the read pairs in the data folder (short_read_qc.py)
       keep              truth_amr/circular/proteins/... tables and <tool>.prediction_summary.tsv   copied from the data folder / written from the predictions
       scores            never rebuilt here: scores.tsv and the benchmark.* tables are the run's result (re-run stage 5 and 6 for new ones)

  4. Record every file it wrote in <results>/regenerated_inputs.json (what, when, versions, hash of inputs); the report shows it under Run metadata.

An existing file is never overwritten unless --force; the benchmark.* tables and scores.tsv are never touched. Without --yes it prints the plan and asks first.

  python3 python/regenerate_visuals.py check RESULTS_DIR [--data-dir D] [--samples SHEET] [--json]
  python3 python/regenerate_visuals.py regenerate RESULTS_DIR [--data-dir D] [--samples SHEET] [--only a,b] [--dry-run] [--yes] [--force]
                                       [--predictions-dir P] [--report] [--json]

Exit codes: 0 nothing is missing (or everything that was missing is now regenerated); 3 something required is still missing; 2 bad arguments.
Standard library only.
"""
import argparse
import csv
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import keep_report_inputs  # noqa: E402
import report_inputs  # noqa: E402

PROVENANCE_FILE = "regenerated_inputs.json"
SCHEMA_VERSION = "1"
DEFAULT_ONLY = ("truth", "paf", "alignments", "truth-features", "qc", "keep")
ALL_KEYS = DEFAULT_ONLY + ("scores",)
PRESENT, REGENERABLE, BLOCKED, NA = "present", "regenerable", "blocked", "not applicable"
EXIT_OK, EXIT_USAGE, EXIT_MISSING = 0, 2, 3

SECTION_LABELS = {
    "samples": "Sample drill-down and sequence view", "plasmid-maps": "Plasmid maps", "learn-synteny": "Synteny ribbons",
    "learn-readqc": "Short-read QC panel", "fig-presence": "Presence/absence matrix (figure branch not yet merged)",
    "fig-facets": "Plasmid-level facets (figure branch not yet merged)", "fig-fingerprint": "Fingerprints at plasmid level (figure branch not yet merged)",
    "replicon-recovery": "Recovery by replicon", "amr-placement": "AMR placement", "scores": "All scores", "leaderboard": "Method ranking",
    "per-plasmid-detail": "Per-plasmid detail", "bin-diagnostics": "Bin diagnostics", "method": "Method",
}


# ------------------------------------------------------------------------------------------------ small helpers
def config_default(name, fallback=""):
    """The default of a setting in config/config.sh (export NAME="${NAME:-value}")."""
    try:
        text = open(os.path.join(ROOT, "config", "config.sh"), encoding="utf-8").read()
    except OSError:
        return fallback
    found = re.search(r'export\s+%s="\$\{%s:-([^}]*)\}"' % (re.escape(name), re.escape(name)), text)
    if not found:
        return fallback
    return found.group(1).replace("$PROJECT_ROOT", ROOT.replace("\\", "/"))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def read_tsv_rows(path):
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            lines = [line for line in handle if line.strip() and not line.startswith("#")]
        return list(csv.DictReader(lines, delimiter="\t"))
    except OSError:
        return []


def file_digest(path, full_limit=256 * 2 ** 20):
    """sha256 of a file; for files over 256 MB the size plus the hash of the first and last MB (marked partial)."""
    size = os.path.getsize(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        if size <= full_limit:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
            return {"sha256": digest.hexdigest(), "bytes": size, "partial": False}
        digest.update(handle.read(1 << 20))
        handle.seek(max(0, size - (1 << 20)))
        digest.update(handle.read(1 << 20))
        digest.update(str(size).encode())
        return {"sha256": digest.hexdigest(), "bytes": size, "partial": True}


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plasbench_version():
    try:
        text = open(os.path.join(ROOT, "plasbench", "__init__.py"), encoding="utf-8").read()
        return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)
    except (OSError, AttributeError):
        return "unknown"


def version_tuple(text):
    parts = re.findall(r"\d+", str(text or ""))[:3]
    return tuple(int(p) for p in parts) + (0,) * (3 - len(parts)) if parts else None


def tool_version(command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "unknown"


# ------------------------------------------------------------------------------------------------ context
class Ctx:
    def __init__(self, results_dir, data_dir=None, sheet=None, only=None, force=False, predictions_dir=None):
        self.results = os.path.abspath(results_dir)
        self.data = os.path.abspath(data_dir) if data_dir else None
        self.predictions = os.path.abspath(predictions_dir) if predictions_dir else None
        self.only = tuple(only) if only else DEFAULT_ONLY
        self.force = force
        self.sheet_path = sheet
        self.sheet = {}
        if sheet:
            for row in read_tsv_rows(sheet):
                name = row.get("sample_id") or row.get("sample") or ""
                if name:
                    self.sheet[name] = row
        self.manifest = read_json(os.path.join(self.results, "run_manifest.json")) or {}
        self.settings = self.manifest.get("settings") if isinstance(self.manifest.get("settings"), dict) else {}
        self.scores = read_tsv_rows(os.path.join(self.results, "scores.tsv"))
        self.status = read_tsv_rows(os.path.join(self.results, "tool_status.tsv"))
        self.samples = self._samples()

    def setting(self, name, fallback=""):
        if os.environ.get(name):
            return os.environ[name]
        if name in self.settings and self.settings[name] not in (None, ""):
            return str(self.settings[name])
        return config_default(name, fallback)

    def _samples(self):
        names = []

        def add(value):
            if value and value not in names:
                names.append(value)
        if self.sheet:
            ran = {row.get("sample") for row in self.scores + self.status if row.get("sample")}
            for name in self.sheet:
                if not ran or name in ran:     # a cohort file lists more isolates than one run may have scored
                    add(name)
            return names
        for row in read_tsv_rows(os.path.join(self.results, "samples.tsv")):
            add(row.get("sample_id") or row.get("sample"))
        for row in self.scores + self.status:
            add(row.get("sample"))
        try:
            for entry in sorted(os.listdir(self.results)):
                path = os.path.join(self.results, entry)
                if os.path.isdir(path) and not entry.startswith((".", "_")) and entry not in ("logs", "selected_candidates") and (
                        glob.glob(os.path.join(path, "pred_*.plasmid.fasta")) or os.path.isdir(os.path.join(path, "visualization"))
                        or os.path.isfile(os.path.join(path, "truth.tsv"))):
                    add(entry)
        except OSError:
            pass
        return names

    def tools(self, sample):
        """Tools of a sample: those with a prediction FASTA here, plus those the run record says completed."""
        found = []
        sdir = os.path.join(self.results, sample)
        for path in sorted(glob.glob(os.path.join(sdir, "pred_*.plasmid.fasta"))):
            found.append(os.path.basename(path)[len("pred_"):-len(".plasmid.fasta")])
        for row in self.status + self.scores:
            if row.get("sample") == sample and row.get("tool") and row.get("status", "completed") in ("completed", "reused") and row["tool"] not in found:
                found.append(row["tool"])
        return found

    def find(self, sample, name):
        """(where, path) of a per-sample input, results folder first, then the data folder; (None, None) when neither has it."""
        for where, base in (("results", self.results), ("data", self.data)):
            if base:
                path = os.path.join(base, sample, name)
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return where, path
        return None, None

    def sra(self, sample):
        row = self.sheet.get(sample) or {}
        return row.get("sra_run") or row.get("sra") or ""

    def reads(self, sample):
        if not self.data:
            return None
        sdir = os.path.join(self.data, sample)
        sra = self.sra(sample)
        candidates = [(os.path.join(sdir, f"{sra}_1.fastq.gz"), os.path.join(sdir, f"{sra}_2.fastq.gz"))] if sra else []
        for first in sorted(glob.glob(os.path.join(sdir, "*_1.fastq.gz"))):
            if ".trim." not in first:
                candidates.append((first, first[:-len("_1.fastq.gz")] + "_2.fastq.gz"))
        for r1, r2 in candidates:
            if os.path.isfile(r1) and os.path.isfile(r2) and os.path.getsize(r1) and os.path.getsize(r2):
                return r1, r2
        return None

    def accession(self, sample):
        row = self.sheet.get(sample) or {}
        return row.get("assembly_accession") or ""


# ------------------------------------------------------------------------------------------------ layout and version
def run_info(ctx):
    version = ctx.manifest.get("tool_version") or ""
    tuple_ = version_tuple(version)
    notes = []
    has_sample_dirs = any(os.path.isdir(os.path.join(ctx.results, s)) for s in ctx.samples)
    if not os.path.isdir(ctx.results) or not os.listdir(ctx.results):
        layout = "empty"
        notes.append("The folder is empty or does not exist: there is nothing to inspect.")
    elif not has_sample_dirs:
        layout = "top-level tables only"
        notes.append("There are no per-sample folders: this is a curated or published copy that kept the benchmark.* tables and scores.tsv only. "
                     "Predictions and alignments are not in it, so nothing per sample can be rebuilt from it alone.")
    else:
        layout = "per-sample folders"
        legacy = [s for s in ctx.samples if glob.glob(os.path.join(ctx.results, s, "*.paf")) and not glob.glob(os.path.join(ctx.results, s, "*.pred_vs_ref.paf"))]
        if legacy:
            layout = "per-sample folders (legacy PAF names)"
            notes.append("In " + ", ".join(legacy[:5]) + " the alignments are named <tool>.paf, not <tool>.pred_vs_ref.paf (before 0.2); they are not read. "
                         "Regenerating the PAF files with minimap2 from the predictions gives the current names.")
    if tuple_ is not None and tuple_ < (0, 2, 0):
        notes.append(f"Written by PlasBench {version}, older than 0.2: the per-sample layout is read as found, but settings are not recorded in "
                     "its manifest, so current defaults are used to rebuild; hashes may then differ from the original run.")
    if not ctx.manifest and layout not in ("empty",):
        notes.append("There is no run_manifest.json: the PlasBench version and settings of the run are unknown, so current defaults are used.")
    return {"plasbench_version": version or "not recorded", "layout": layout, "samples": len(ctx.samples),
            "tools": sorted({t for s in ctx.samples for t in ctx.tools(s)}), "notes": notes,
            "generated_at": ctx.manifest.get("generated_at") or ""}


# ------------------------------------------------------------------------------------------------ planning
def item(key, files, status, how="", needs=None, optional=False, sample="", tool="", kind="", **extra):
    return dict({"key": key, "files": files, "status": status, "how": how, "needs": needs or [], "optional": optional, "sample": sample, "tool": tool, "kind": kind}, **extra)


def rel(sample, name):
    return f"{sample}/{name}" if sample else name


def minimap2_missing():
    return None if shutil.which("minimap2") else "minimap2 is not installed (conda install -c bioconda minimap2)"


def prediction_check(ctx, sample, tool, fasta_path):
    """Is a prediction FASTA the one that was scored? (True, why) / (False, why). Uses the kept summary, else the scores.tsv row."""
    rows = keep_report_inputs.summary_rows(fasta_path)
    kept = keep_report_inputs.read_summary(os.path.join(ctx.results, sample, f"{tool}.prediction_summary.tsv"))
    if kept is not None:
        theirs = {name: (length, digest) for name, length, digest in rows}
        return (theirs == kept, "records, lengths and sequence hashes match the kept prediction summary" if theirs == kept
                else "records or sequences differ from the prediction summary kept with the run")
    for row in ctx.scores:
        if row.get("sample") == sample and row.get("tool") == tool:
            try:
                want_records = int(float(row.get("predicted_record_count") or ""))
                want_bp = int(float(row.get("mapped_pred_bp") or 0)) + int(float(row.get("unmapped_pred_bp") or 0))
            except ValueError:
                return False, "the scores.tsv row does not record the predicted records, so the predictions cannot be verified"
            bp = sum(length for _n, length, _h in rows)
            ok = len(rows) == want_records and bp == want_bp
            return ok, (f"record count ({len(rows)}) and total length ({bp} bp) match the scores.tsv row" if ok else
                        f"{len(rows)} records / {bp} bp, but scores.tsv scored {want_records} records / {want_bp} bp")
    return False, "no scores.tsv row or prediction summary to verify these predictions against"


def plan_sample(ctx, sample):
    items = []
    sdir = os.path.join(ctx.results, sample)
    tools = ctx.tools(sample)
    where_ref, ref = ctx.find(sample, "reference.fna")
    where_rep, seqrep = ctx.find(sample, "sequence_report.jsonl")
    where_truth, truth = ctx.find(sample, "truth.tsv")
    mm_problem = minimap2_missing()

    # truth.tsv
    if where_truth == "results":
        items.append(item("truth", [rel(sample, "truth.tsv")], PRESENT, sample=sample))
    elif where_truth == "data":
        items.append(item("truth", [rel(sample, "truth.tsv")], REGENERABLE, "copied from the data folder", sample=sample, kind="copy", src=truth))
    elif seqrep and ref:
        items.append(item("truth", [rel(sample, "truth.tsv")], REGENERABLE, "built from sequence_report.jsonl and reference.fna (make_truth.py)", sample=sample, kind="make_truth"))
    else:
        needs = []
        if not ref:
            needs.append("reference.fna of the sample (the data folder, or a download from ENA/NCBI: needs internet access" +
                         ", the assembly accession is in the sample sheet)")
        if not seqrep:
            needs.append("sequence_report.jsonl (written by the download stage) or the truth.tsv itself")
        items.append(item("truth", [rel(sample, "truth.tsv")], BLOCKED, sample=sample, needs=needs))
    truth_will_exist = where_truth is not None or (seqrep and ref)

    # predictions and PAFs
    pafs_will_exist = False
    paf_ok, paf_missing = [], []
    if not tools:
        items.append(item("paf", [rel(sample, "<tool>.pred_vs_ref.paf")], BLOCKED, sample=sample,
                          needs=["predictions: no pred_<tool>.plasmid.fasta in the results folder and no tool in tool_status.tsv. "
                                 "Predictions come from running the tools (stage 4); supply the original results folder with --predictions-dir"]))
    for tool in tools:
        pred = os.path.join(sdir, f"pred_{tool}.plasmid.fasta")
        paf = os.path.join(sdir, f"{tool}.pred_vs_ref.paf")
        have_pred = os.path.isfile(pred)
        import_from = None
        if not have_pred and ctx.predictions:
            candidate = os.path.join(ctx.predictions, sample, f"pred_{tool}.plasmid.fasta")
            if os.path.isfile(candidate):
                import_from = candidate
        if os.path.isfile(paf) and os.path.getsize(paf) >= 0 and (have_pred or os.path.isfile(paf)):
            items.append(item("paf", [rel(sample, f"{tool}.pred_vs_ref.paf")], PRESENT, sample=sample, tool=tool))
            pafs_will_exist = True
            paf_ok.append(tool)
            if not have_pred and not import_from:
                items.append(item("predictions", [rel(sample, f"pred_{tool}.plasmid.fasta")], BLOCKED, sample=sample, tool=tool, optional=True,
                                  needs=[f"pred_{tool}.plasmid.fasta (only the alignments were kept); rebuilding the alignment tables does not need it, "
                                         "but the CIGAR local alignments of the sequence view do"]))
            continue
        if import_from:
            ok, why = prediction_check(ctx, sample, tool, import_from)
            if not ok:
                items.append(item("paf", [rel(sample, f"{tool}.pred_vs_ref.paf")], BLOCKED, sample=sample, tool=tool,
                                  needs=[f"predictions in {ctx.predictions} are not the ones this run scored: {why}"]))
                paf_missing.append(tool)
                continue
            src_paf = os.path.join(ctx.predictions, sample, f"{tool}.pred_vs_ref.paf")
            items.append(item("paf", [rel(sample, f"pred_{tool}.plasmid.fasta"), rel(sample, f"{tool}.pred_vs_ref.paf")], REGENERABLE,
                              f"predictions copied from --predictions-dir (verified: {why})" + ("; alignments copied with them" if os.path.isfile(src_paf)
                                                                                           else "; alignments rebuilt with minimap2"),
                              sample=sample, tool=tool, kind="import_predictions", src=import_from, src_paf=src_paf if os.path.isfile(src_paf) else ""))
            pafs_will_exist = pafs_will_exist or os.path.isfile(src_paf) or (ref and not mm_problem)
            paf_ok.append(tool)
            continue
        if have_pred and ref and not mm_problem:
            items.append(item("paf", [rel(sample, f"{tool}.pred_vs_ref.paf")], REGENERABLE,
                              "aligned with minimap2 from the prediction and the reference", sample=sample, tool=tool, kind="minimap2"))
            pafs_will_exist = True
            paf_ok.append(tool)
            continue
        paf_missing.append(tool)
        needs = []
        if not have_pred:
            needs.append(f"pred_{tool}.plasmid.fasta: the prediction was not kept; it needs the tool re-run (stage 4: reads, the tool and its database) "
                         "or the original results folder via --predictions-dir")
        if not ref:
            needs.append("reference.fna (the data folder, or a download: needs internet access)")
        if mm_problem:
            needs.append(mm_problem)
        items.append(item("paf", [rel(sample, f"{tool}.pred_vs_ref.paf")], BLOCKED, sample=sample, tool=tool, needs=needs))

    # alignments, structural events
    viz = rel(sample, "visualization/alignment_blocks.json")
    present_blocks = os.path.isfile(os.path.join(sdir, "visualization", "alignment_blocks.json"))
    blockers = []
    if not truth_will_exist:
        blockers.append("truth.tsv (see above)")
    if not pafs_will_exist:
        blockers.append("the predictions' alignments to the reference (<tool>.pred_vs_ref.paf; see above)")
    if present_blocks:
        items.append(item("alignments", [viz, rel(sample, "visualization/structural_metrics.tsv")], PRESENT, sample=sample, kind="viz"))
    elif blockers:
        items.append(item("alignments", [viz, rel(sample, "visualization/structural_metrics.tsv")], BLOCKED, sample=sample, kind="viz",
                          needs=["needs " + " and ".join(blockers)]))
    else:
        partial = f"; only for the tools whose alignments exist ({', '.join(paf_ok)}), not {', '.join(paf_missing)}" if paf_missing else ""
        items.append(item("alignments", [viz, rel(sample, "visualization/structural_metrics.tsv")], REGENERABLE,
                          "built from truth.tsv, the alignments and the predictions (build_visualization_data.py)" + partial, sample=sample, kind="viz"))
    struct_files = ["visualization/structural_calls.json", "structural_events.tsv", "structural_summary.tsv"]
    if all(os.path.isfile(os.path.join(sdir, f)) for f in struct_files):
        items.append(item("alignments", [rel(sample, f) for f in struct_files], PRESENT, sample=sample, kind="structural", optional=True))
    elif blockers:
        items.append(item("alignments", [rel(sample, f) for f in struct_files], BLOCKED, sample=sample, kind="structural", optional=True,
                          needs=["needs " + " and ".join(blockers)]))
    else:
        items.append(item("alignments", [rel(sample, f) for f in struct_files], REGENERABLE,
                          "called from truth.tsv and the alignments (call_structural_variants.py)", sample=sample, kind="structural", optional=True))

    # truth features
    where_feat, feat = ctx.find(sample, "truth_features.tsv")
    callers = ("abricate", "amrfinder", "isescan.py", "isescan", "mob_typer", "barrnap")
    if where_feat == "results":
        items.append(item("truth-features", [rel(sample, "truth_features.tsv")], PRESENT, sample=sample, optional=True))
    elif where_feat == "data" and len(read_tsv_rows(feat)) == 0:
        items.append(item("truth-features", [rel(sample, "truth_features.tsv")], BLOCKED, sample=sample, optional=True,
                          needs=["the data folder's truth_features.tsv has no rows (no annotation caller was installed when it was made, see annotation_provenance.json), "
                                 "so there is nothing to keep; annotate again with a caller installed"]))
    elif where_feat == "data":
        items.append(item("truth-features", [rel(sample, "truth_features.tsv")], REGENERABLE, "copied from the data folder", sample=sample, optional=True, kind="copy", src=feat))
    elif ref and any(shutil.which(c) for c in callers):
        items.append(item("truth-features", [rel(sample, "truth_features.tsv")], REGENERABLE,
                          "annotated from reference.fna with the installed callers (annotate_reference.py)", sample=sample, optional=True, kind="annotate"))
    else:
        needs = []
        if not ref:
            needs.append("reference.fna (the data folder, or a download: needs internet access)")
        if not any(shutil.which(c) for c in callers):
            needs.append("an annotation caller on PATH (abricate, amrfinder, isescan, mob_typer or barrnap) and its database")
        items.append(item("truth-features", [rel(sample, "truth_features.tsv")], BLOCKED, sample=sample, optional=True, needs=needs))

    # small tables that only live in the data folder, and the prediction summaries
    for name in ("truth_amr.tsv", "truth_circular.tsv", "truth_proteins.tsv", "truth_repeat_content.tsv", "truth_repeat_regions.tsv"):
        where, path = ctx.find(sample, name)
        if where == "results":
            items.append(item("keep", [rel(sample, name)], PRESENT, sample=sample, optional=True))
        elif where == "data":
            items.append(item("keep", [rel(sample, name)], REGENERABLE, "copied from the data folder", sample=sample, optional=True, kind="copy", src=path))
        elif name == "truth_amr.tsv":
            draft = ctx.find(sample, "truth_amr.draft.tsv")[0]
            items.append(item("keep", [rel(sample, name)], BLOCKED, sample=sample, optional=True,
                              needs=["a curated AMR truth table: " + ("a draft exists; review it and run plasbench promote-amr-truth" if draft
                                                                       else "none is in the results or data folder (it is curated by a person, never generated)")]))
    for tool in tools:
        if os.path.isfile(os.path.join(sdir, f"pred_{tool}.plasmid.fasta")) or (ctx.predictions and os.path.isfile(os.path.join(ctx.predictions, sample, f"pred_{tool}.plasmid.fasta"))):
            summary = os.path.join(sdir, f"{tool}.prediction_summary.tsv")
            items.append(item("keep", [rel(sample, f"{tool}.prediction_summary.tsv")], PRESENT if os.path.isfile(summary) else REGENERABLE,
                              "" if os.path.isfile(summary) else "written from the prediction (keep_report_inputs.py)", sample=sample, tool=tool, optional=True, kind="summary"))
    return items


def plan_global(ctx):
    items = []
    qc_files = ["short_read_qc.tsv", "short_read_qc_status.tsv"]
    mode = ctx.setting("SHORT_READ_QC_MODE", "report")
    tracks = {row.get("analysis_track") for row in ctx.scores if row.get("analysis_track")}
    sheet_rows = list(ctx.sheet.values()) or read_tsv_rows(os.path.join(ctx.results, "samples.tsv"))
    origins = {row.get("sample_origin") for row in sheet_rows if row.get("sample_id") in ctx.samples or row.get("sample") in ctx.samples} - {None, ""}
    if os.path.isfile(os.path.join(ctx.results, "short_read_qc.tsv")):
        have = {r.get("sample") for r in read_tsv_rows(os.path.join(ctx.results, "short_read_qc.tsv"))}
        gaps = [s for s in ctx.samples if s not in have]
        gap_reads = [g for g in gaps if ctx.reads(g)]
        items.append(item("qc", qc_files, PRESENT, sample="", kind="qc", gaps=gaps,
                          how=(f"{len(gaps)} of {len(ctx.samples)} samples have no row"
                               + ("" if gap_reads else "; their read pairs are not in the data folder, so the rows cannot be added") if gaps else "")))
    elif origins and origins == {"synthetic"}:
        items.append(item("qc", qc_files, NA, "every sample is synthetic (sample_origin=synthetic): there are no reads to measure", kind="qc"))
    elif mode == "off":
        items.append(item("qc", qc_files, NA, "SHORT_READ_QC_MODE=off in the run's settings: the run did not measure read quality", kind="qc"))
    elif tracks and tracks <= {"long_read"}:
        items.append(item("qc", qc_files, NA, "a long-read-only run has no short-read QC", kind="qc"))
    else:
        with_reads = [s for s in ctx.samples if ctx.reads(s)]
        if with_reads:
            skipped = len(ctx.samples) - len(with_reads)
            items.append(item("qc", qc_files, REGENERABLE,
                              f"measured from the read pairs of {len(with_reads)} sample(s) (short_read_qc.py)" + (f"; {skipped} sample(s) without reads will have no row" if skipped else ""),
                              kind="qc", samples=with_reads))
        else:
            needs = ["the raw read pairs <run>_1.fastq.gz / <run>_2.fastq.gz of the samples in the data folder (--data-dir)" if not ctx.data else
                     "no read pairs were found under " + ctx.data + "; re-download them from ENA (needs internet access; the run accessions are in the sample sheet)"]
            items.append(item("qc", qc_files, BLOCKED, kind="qc", needs=needs))
    return items


def build_plan(ctx):
    items = plan_global(ctx)
    for sample in ctx.samples:
        items.extend(plan_sample(ctx, sample))
    return items


def selected(ctx, entry):
    return entry["key"] in ctx.only or (entry["key"] == "predictions")


# ------------------------------------------------------------------------------------------------ sections
def coverage(ctx, pattern):
    """(have, total): how many of the files a pattern stands for exist. {sample} is each sample, {tool} each of its tools; other placeholders are globbed."""
    def exists(path_pattern):
        return bool(glob.glob(os.path.join(ctx.results, re.sub(r"\{[a-z0-9_]+\}", "*", path_pattern))))
    if pattern == "short_read_qc.tsv" and ctx.samples:     # one table, one row per sample
        have_rows = {r.get("sample") for r in read_tsv_rows(os.path.join(ctx.results, pattern))}
        return sum(1 for sample in ctx.samples if sample in have_rows), len(ctx.samples)
    if "{sample}" not in pattern:
        return (1 if exists(pattern) else 0), 1
    have = total = 0
    for sample in ctx.samples:
        tools = (ctx.tools(sample) or [None]) if "{tool}" in pattern else [None]
        for tool in tools:
            total += 1
            path = pattern.replace("{sample}", sample)
            if tool:
                path = path.replace("{tool}", tool)
            have += 1 if exists(path) else 0
    return (have, total) if total else ((1 if exists(pattern) else 0), 1)


def section_report(ctx, plan):
    """Per report section with a required input: available (every sample has it), partial (some do) or unavailable, and what regeneration would change."""
    rows = [r for r in report_inputs.load() if r["sections"]]
    blocked_keys = {e["key"] for e in plan if e["status"] == BLOCKED and not e["optional"]}
    blocked_keys |= {e["key"] for e in plan if e.get("gaps") and not any(ctx.reads(g) for g in e["gaps"])}
    na_keys = {e["key"] for e in plan if e["status"] == NA} - {e["key"] for e in plan if e["status"] != NA}
    sections = {}
    for row in rows:
        for sid in [s for s in row["sections"].split(",") if s]:
            sections.setdefault(sid, []).append(row)
    out = []
    for sid, srows in sorted(sections.items()):
        required = [r for r in srows if r["role"] == "required"]
        if not required:
            continue
        if all(r["regen_key"] in na_keys for r in required):
            out.append({"id": sid, "label": SECTION_LABELS.get(sid, sid), "status": "not applicable", "available": True, "missing": [],
                        "available_after_regeneration": True, "still_missing_after": []})
            continue
        required = [r for r in required if r["regen_key"] not in na_keys]
        cover = {r["pattern"]: coverage(ctx, r["pattern"]) for r in required}
        incomplete = [r for r in required if cover[r["pattern"]][0] < cover[r["pattern"]][1]]
        started = any(h > 0 for h, _t in cover.values())
        after_missing = [r for r in incomplete if not (r["regen_key"] and r["regen_key"] not in blocked_keys)]
        status = "available" if not incomplete else ("partial" if started and all(h > 0 or t == 0 for h, t in cover.values()) else "unavailable")
        out.append({"id": sid, "label": SECTION_LABELS.get(sid, sid), "status": status, "available": not incomplete,
                    "missing": [f"{r['pattern']} ({cover[r['pattern']][0]} of {cover[r['pattern']][1]})" for r in incomplete],
                    "available_after_regeneration": not after_missing, "still_missing_after": [r["pattern"] for r in after_missing]})
    return out


# ------------------------------------------------------------------------------------------------ rendering
def _group(plan):
    """Entries that say the same thing about different samples or tools are shown once, with their samples."""
    groups = {}
    for entry in plan:
        tool = entry["tool"]
        norm = (lambda text: text.replace(tool, "<tool>")) if tool else (lambda text: text)
        files = tuple(norm(re.sub(r"^[^/]+/", "", f)) if entry["sample"] else f for f in entry["files"])
        key = (entry["key"], entry["kind"], entry["status"], norm(entry["how"]), tuple(norm(n) for n in entry["needs"]), entry["optional"], files)
        groups.setdefault(key, []).append(entry)
    return groups


def render(ctx, info, plan, sections, dry_run=True, title="check"):
    lines = [f"PlasBench {title}: {ctx.results}", ""]
    lines.append(f"Run: PlasBench {info['plasbench_version']}, {info['samples']} sample(s), {len(info['tools'])} tool(s), layout: {info['layout']}")
    for note in info["notes"]:
        lines.append(f"  Note: {note}")
    lines += ["", "Report sections that need per-sample files:"]
    if not sections:
        lines.append("  (none listed)")
    for s in sections:
        word = "PARTIAL" if s["status"] == "partial" else "NOT AVAILABLE"
        mark = "not applicable to this run" if s["status"] == "not applicable" else "available" if s["available"] else (word + "; can be regenerated" if s["available_after_regeneration"] else word)
        lines.append(f"  [{mark}] {s['label']} ({s['id']})")
        if s["missing"]:
            lines.append("      missing: " + ", ".join(s["missing"]))
        if s["still_missing_after"] and not s["available"]:
            lines.append("      still missing after regeneration: " + ", ".join(s["still_missing_after"]))
    lines += ["", "Files:"]
    for (key, kind, status, how, needs, optional, files), entries in _group(plan).items():
        samples = sorted({e["sample"] for e in entries if e["sample"]}, key=lambda n: ctx.samples.index(n) if n in ctx.samples else 0)
        who = f" for {len(samples)} sample(s)" + (f" x {len(entries) // max(1, len(samples))} tool(s)" if len(entries) > len(samples) else "") if samples else ""
        if status == PRESENT and len(entries) > 3:
            lines.append(f"  present   {key}: {', '.join(files)}{who}")
            continue
        tag = {"present": "present   ", "regenerable": "REGEN     ", "blocked": "MISSING   ", "not applicable": "n/a       "}[status]
        lines.append(f"  {tag}{key}{' (optional)' if optional else ''}: {', '.join(files)}{who}")
        if how:
            lines.append(f"      {how}")
        for need in needs:
            lines.append(f"      needs: {need}")
        if samples and status in (REGENERABLE, BLOCKED):
            lines.append("      samples: " + ", ".join(samples[:12]) + (f" (+{len(samples) - 12} more)" if len(samples) > 12 else ""))
    counts = {s: sum(1 for e in plan if e["status"] == s and selected(ctx, e)) for s in (PRESENT, REGENERABLE, BLOCKED)}
    lines += ["", f"Summary: {counts[PRESENT]} present, {counts[REGENERABLE]} can be regenerated, {counts[BLOCKED]} cannot be regenerated from what is present."]
    return "\n".join(lines)


def outstanding(ctx, plan):
    """Required (non-optional) selected items that are blocked."""
    return [e for e in plan if e["status"] == BLOCKED and not e["optional"] and selected(ctx, e)]


# ------------------------------------------------------------------------------------------------ provenance
def load_provenance(results):
    data = read_json(os.path.join(results, PROVENANCE_FILE))
    return data if isinstance(data, dict) and isinstance(data.get("entries"), list) else {"schema_version": SCHEMA_VERSION, "entries": []}


def record(results, entries, command):
    data = load_provenance(results)
    mine = {e["file"] for e in entries}
    data["entries"] = [e for e in data["entries"] if e.get("file") not in mine] + entries
    data["entries"].sort(key=lambda e: e["file"])
    data["schema_version"] = SCHEMA_VERSION
    data["note"] = "These files were regenerated after the run by plasbench regenerate-visuals; they were not written by the original run."
    data["last_command"] = command
    tmp = os.path.join(results, PROVENANCE_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, os.path.join(results, PROVENANCE_FILE))


def make_entry(ctx, files, key, how, inputs, versions):
    digests = []
    for label, path in inputs:
        try:
            info = file_digest(path)
            digests.append({"input": label, **info})
        except OSError:
            digests.append({"input": label, "sha256": "", "bytes": 0, "partial": False})
    combined = hashlib.sha256("".join(d["sha256"] for d in digests).encode()).hexdigest()
    return [{"file": f, "kind": key, "action": how, "regenerated_at": now_utc(), "plasbench_version": plasbench_version(),
             "run_plasbench_version": ctx.manifest.get("tool_version") or "not recorded", "tool_versions": versions,
             "inputs": digests, "inputs_sha256": combined} for f in files]


# ------------------------------------------------------------------------------------------------ actions
def run_script(args, log_lines):
    result = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    if result.returncode != 0:
        log_lines.append((result.stderr or result.stdout).strip()[-600:])
        return False
    return True


def atomic_copy(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def execute(ctx, plan, command):
    """Do the REGENERABLE selected items in dependency order. Returns [{item, outcome, message}]."""
    results = []
    entries = []
    order = {"truth": 0, "paf": 1, "alignments": 2, "truth-features": 3, "keep": 4, "qc": 5}
    todo = sorted([e for e in plan if e["status"] == REGENERABLE and e["key"] in ctx.only], key=lambda e: (order.get(e["key"], 9), e["sample"]))
    versions = {}
    config = {
        "preset": ctx.setting("MINIMAP2_PRESET", "asm5"), "blocks": ctx.setting("VISUALIZATION_MAX_BLOCKS_PER_TOOL", "2000"),
        "bp": ctx.setting("VISUALIZATION_MAX_NUCLEOTIDE_ALIGNMENT_BP", "2000"), "scheme": ctx.setting("TRUTH_LABEL_SCHEME", "ncbi"),
    }
    for entry in todo:
        sample, tool = entry["sample"], entry["tool"]
        sdir = os.path.join(ctx.results, sample) if sample else ctx.results
        log = []
        ok = True
        inputs = []
        how = entry["how"]
        try:
            if entry["kind"] == "copy":
                for f in entry["files"]:
                    atomic_copy(entry["src"], os.path.join(ctx.results, f))
                inputs = [("data:" + entry["files"][0], entry["src"])]
            elif entry["kind"] == "make_truth":
                _w, seqrep = ctx.find(sample, "sequence_report.jsonl")
                _w, ref = ctx.find(sample, "reference.fna")
                os.makedirs(sdir, exist_ok=True)
                extra = ["--allow-default"] if os.environ.get("ALLOW_DEFAULTED_TRUTH") == "1" else []
                tmp = os.path.join(sdir, "truth.tsv.tmp")
                ok = run_script([os.path.join(HERE, "make_truth.py"), "--report", seqrep, "--fasta", ref, "--out", tmp] + extra, log)
                if ok:
                    os.replace(tmp, os.path.join(sdir, "truth.tsv"))
                inputs = [(f"{sample}/sequence_report.jsonl", seqrep), (f"{sample}/reference.fna", ref)]
            elif entry["kind"] == "import_predictions":
                os.makedirs(sdir, exist_ok=True)
                atomic_copy(entry["src"], os.path.join(sdir, f"pred_{tool}.plasmid.fasta"))
                inputs = [(f"predictions:{sample}/pred_{tool}.plasmid.fasta", entry["src"])]
                paf = os.path.join(sdir, f"{tool}.pred_vs_ref.paf")
                if entry.get("src_paf"):
                    atomic_copy(entry["src_paf"], paf)
                    inputs.append((f"predictions:{sample}/{tool}.pred_vs_ref.paf", entry["src_paf"]))
                else:
                    ok, inputs_extra = _minimap2(ctx, sample, tool, config, log, versions)
                    inputs += inputs_extra
            elif entry["kind"] == "minimap2":
                ok, inputs = _minimap2(ctx, sample, tool, config, log, versions)
            elif entry["kind"] == "viz":
                ok, inputs = _viz(ctx, sample, config, log)
            elif entry["kind"] == "structural":
                _w, truth = ctx.find(sample, "truth.tsv")
                ok = run_script([os.path.join(HERE, "call_structural_variants.py"), "--truth", truth, "--results-dir", ctx.results, "--sample", sample,
                                 "--events-out", os.path.join(sdir, "structural_events.tsv"), "--summary-out", os.path.join(sdir, "structural_summary.tsv"),
                                 "--json-out", os.path.join(sdir, "visualization", "structural_calls.json")], log)
                inputs = [(f"{sample}/truth.tsv", truth)] + [(f"{sample}/{os.path.basename(p)}", p) for p in sorted(glob.glob(os.path.join(sdir, "*.pred_vs_ref.paf")))]
            elif entry["kind"] == "annotate":
                _w, ref = ctx.find(sample, "reference.fna")
                versions["annotate_reference"] = "installed callers on PATH"
                ok = run_script([os.path.join(HERE, "annotate_reference.py"), "--reference", ref, "--out", os.path.join(sdir, "truth_features.tsv"),
                                 "--provenance", os.path.join(sdir, "annotation_provenance.json"),
                                 "--amr-database", ctx.setting("ANNOTATION_AMR_DB", "ncbi"), "--replicon-database", ctx.setting("ANNOTATION_REPLICON_DB", "plasmidfinder"),
                                 "--isfinder-fasta", ctx.setting("ISFINDER_FASTA", ""), "--threads", str(os.cpu_count() or 1)], log)
                inputs = [(f"{sample}/reference.fna", ref)]
            elif entry["kind"] == "summary":
                pred = os.path.join(sdir, f"pred_{tool}.plasmid.fasta")
                keep_report_inputs.write_summary(pred, os.path.join(sdir, f"{tool}.prediction_summary.tsv"))
                inputs = [(f"{sample}/pred_{tool}.plasmid.fasta", pred)]
            elif entry["kind"] == "qc":
                ok, inputs = _qc(ctx, entry, log)
            else:
                ok = False
                log.append(f"no action for {entry['kind']}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            ok = False
            log.append(f"{type(exc).__name__}: {exc}")
        if ok:
            entries += make_entry(ctx, entry["files"], entry["key"], how, inputs, dict(versions, python=sys.version.split()[0]))
        results.append({"key": entry["key"], "files": entry["files"], "sample": sample, "outcome": "regenerated" if ok else "failed", "message": "" if ok else " ".join(log)[-400:]})
    if entries:
        record(ctx.results, entries, command)
    return results


def _minimap2(ctx, sample, tool, config, log, versions):
    sdir = os.path.join(ctx.results, sample)
    _w, ref = ctx.find(sample, "reference.fna")
    pred = os.path.join(sdir, f"pred_{tool}.plasmid.fasta")
    versions["minimap2"] = tool_version(["minimap2", "--version"])
    paf = os.path.join(sdir, f"{tool}.pred_vs_ref.paf")
    tmp = paf + ".tmp"
    if os.path.getsize(pred) == 0:
        open(tmp, "w").close()
        os.replace(tmp, paf)
        return True, [(f"{sample}/pred_{tool}.plasmid.fasta", pred)]
    with open(tmp, "wb") as handle:
        result = subprocess.run(["minimap2", "--secondary=no", "-c", "-x", config["preset"], "-t", str(min(os.cpu_count() or 1, 4)), ref, pred],
                                stdout=handle, stderr=subprocess.PIPE)
    if result.returncode != 0:
        log.append(result.stderr.decode(errors="replace")[-400:])
        os.path.exists(tmp) and os.remove(tmp)
        return False, []
    os.replace(tmp, paf)
    return True, [(f"{sample}/pred_{tool}.plasmid.fasta", pred), (f"{sample}/reference.fna", ref)]


def _viz(ctx, sample, config, log):
    sdir = os.path.join(ctx.results, sample)
    _w, truth = ctx.find(sample, "truth.tsv")
    _w, ref = ctx.find(sample, "reference.fna")
    scored_scheme = config["scheme"] != "ncbi"

    def optional(name):
        w, path = ctx.find(sample, name)
        return path or os.path.join(sdir, name)
    amr = optional("truth_amr.scored.tsv") if scored_scheme and ctx.find(sample, "truth_amr.scored.tsv")[0] else optional("truth_amr.tsv")
    circ = optional("truth_circular.scored.tsv") if scored_scheme and ctx.find(sample, "truth_circular.scored.tsv")[0] else optional("truth_circular.tsv")
    os.makedirs(os.path.join(sdir, "visualization"), exist_ok=True)
    args = [os.path.join(HERE, "build_visualization_data.py"), "--truth", truth]
    if ref:
        args += ["--reference", ref]
    args += ["--results-dir", ctx.results, "--sample", sample, "--amr-truth", amr, "--feature-truth", optional("truth_features.tsv"),
             "--protein-truth", optional("truth_proteins.tsv"), "--circular-truth", circ, "--max-blocks-per-tool", config["blocks"],
             "--max-nucleotide-bp", config["bp"], "--out", os.path.join(sdir, "visualization", "alignment_blocks.json"),
             "--structural-out", os.path.join(sdir, "visualization", "structural_metrics.tsv")]
    ok = run_script(args, log)
    inputs = [(f"{sample}/truth.tsv", truth)] + ([(f"{sample}/reference.fna", ref)] if ref else [])
    for path in sorted(glob.glob(os.path.join(sdir, "*.pred_vs_ref.paf")) + glob.glob(os.path.join(sdir, "pred_*.plasmid.fasta"))):
        inputs.append((f"{sample}/{os.path.basename(path)}", path))
    for label, path in (("truth_amr.tsv", amr), ("truth_features.tsv", optional("truth_features.tsv")), ("truth_proteins.tsv", optional("truth_proteins.tsv")),
                        ("truth_circular.tsv", circ)):
        if os.path.isfile(path):
            inputs.append((f"{sample}/{label}", path))
    return ok, inputs


def _qc(ctx, entry, log):
    samples = entry.get("samples") or []
    shards = os.path.join(ctx.results, ".regenerate_qc_shards")
    shutil.rmtree(shards, ignore_errors=True)
    os.makedirs(shards)
    inputs = []
    try:
        for sample in samples:
            r1, r2 = ctx.reads(sample)
            args = [os.path.join(HERE, "short_read_qc.py"), "qc", "--sample", sample, "--r1", r1, "--r2", r2, "--out", os.path.join(shards, f"{sample}.tsv"),
                    "--thresholds", ctx.setting("SHORT_READ_QC_THRESHOLDS", os.path.join(ROOT, "config", "short_read_qc_thresholds.tsv")),
                    "--max-pairs", ctx.setting("SHORT_READ_QC_MAX_PAIRS", "200000")]
            genome = ctx.setting("SHORT_READ_QC_GENOME_MB", "")
            if genome:
                args += ["--genome-size-mb", genome]
            if not run_script(args, log):
                return False, []
            inputs += [(f"{sample}/{os.path.basename(r1)}", r1), (f"{sample}/{os.path.basename(r2)}", r2)]
        ok = run_script([os.path.join(HERE, "short_read_qc.py"), "merge", "--shards", shards, "--out", os.path.join(ctx.results, "short_read_qc.tsv"),
                         "--status-out", os.path.join(ctx.results, "short_read_qc_status.tsv"), "--mode", ctx.setting("SHORT_READ_QC_MODE", "report")], log)
        return ok, inputs
    finally:
        shutil.rmtree(shards, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ commands
def prepare(args):
    only = None
    if getattr(args, "only", None):
        only = [k.strip() for k in args.only.split(",") if k.strip()]
        bad = [k for k in only if k not in ALL_KEYS]
        if bad:
            print(f"error: unknown --only key(s) {', '.join(bad)}; choose from {', '.join(ALL_KEYS)}", file=sys.stderr)
            return None
    sheet = args.samples or getattr(args, "cohort", None)
    if sheet and not os.path.isfile(sheet):
        print(f"error: the sample sheet {sheet} does not exist", file=sys.stderr)
        return None
    for label, value in (("--data-dir", args.data_dir), ("--predictions-dir", getattr(args, "predictions_dir", None))):
        if value and not os.path.isdir(value):
            print(f"error: {label} {value} is not a folder", file=sys.stderr)
            return None
    if not os.path.isdir(args.results_dir):
        print(f"error: the results folder {args.results_dir} does not exist", file=sys.stderr)
        return None
    return Ctx(args.results_dir, args.data_dir, sheet, only, getattr(args, "force", False), getattr(args, "predictions_dir", None))


def to_force(ctx, plan):
    """--force: every present item of a selected key is redone (when its inputs allow); scores and benchmark tables are never in the plan."""
    if not ctx.force:
        return plan
    redo = []
    for e in plan:
        if e["status"] == PRESENT and e["key"] in ctx.only and e["kind"] in ("viz", "structural", "minimap2", "qc", "summary", "make_truth", "annotate"):
            redo.append(e)
    if not redo:
        return plan
    # re-plan with the existing outputs treated as missing, but only for items whose inputs are still there
    forced = []
    for e in plan:
        if e in redo and e["kind"] in ("viz", "structural", "summary", "qc"):
            copy = dict(e, status=REGENERABLE, how="rebuilt (--force)")
            if e["kind"] == "qc":
                with_reads = [s for s in ctx.samples if ctx.reads(s)]
                if not with_reads:
                    continue
                copy["samples"] = with_reads
            forced.append(copy)
        else:
            forced.append(e)
    return forced


def cmd_check(args):
    ctx = prepare(args)
    if ctx is None:
        return EXIT_USAGE
    info = run_info(ctx)
    plan = build_plan(ctx)
    sections = section_report(ctx, plan)
    if args.json:
        print(json.dumps({"results": ctx.results, "run": info, "sections": sections, "files": plan}, indent=2, default=str))
    else:
        print(render(ctx, info, plan, sections, title="check-results"))
        print("")
        print("Sections that would render now: " + (", ".join(s["label"] for s in sections if s["available"]) or "none of the listed ones"))
    return EXIT_MISSING if any(not s["available"] for s in sections) else EXIT_OK


def cmd_regenerate(args):
    ctx = prepare(args)
    if ctx is None:
        return EXIT_USAGE
    info = run_info(ctx)
    plan = to_force(ctx, build_plan(ctx))
    sections = section_report(ctx, plan)
    command = "regenerate-visuals " + " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "regenerate-visuals"
    explicit_scores = "scores" in ctx.only
    if not args.json:
        print(render(ctx, info, plan, sections, title="regenerate-visuals" + (" (dry run)" if args.dry_run else "")))
        if explicit_scores:
            print("\n--only scores: scores.tsv and the benchmark.* tables are the run's result and are not rebuilt by this command. "
                  "To score again, re-run stage 5 and then stage 6 (plasbench run --stages 5 6 ... or plasbench report) with the run's data folder and sample sheet.")
    todo = [e for e in plan if e["status"] == REGENERABLE and e["key"] in ctx.only]
    outcomes = []
    if args.dry_run or not todo:
        if not todo and not args.dry_run and not args.json:
            print("\nNothing to regenerate.")
    else:
        if not args.yes:
            if not sys.stdin.isatty():
                print(f"\nNot regenerating: {len(todo)} step(s) planned and neither --yes nor a terminal to ask on. Re-run with --yes (or --dry-run to only look).", file=sys.stderr)
                return EXIT_USAGE
            try:
                answer = input(f"\nRegenerate {len(todo)} item(s) in {ctx.results}? [y/N] ").strip().lower()
            except EOFError:
                print("\nNot regenerating: nothing answered the question. Re-run with --yes (or --dry-run to only look).", file=sys.stderr)
                return EXIT_USAGE
            if answer not in ("y", "yes"):
                print("Nothing changed.")
                return EXIT_MISSING
        outcomes = execute(ctx, plan, command)
        if not args.json:
            print("")
            for o in outcomes:
                where = f" ({o['sample']})" if o["sample"] else ""
                print(f"  {o['outcome']:11s} {o['key']}{where}: {', '.join(o['files'])}" + (f"\n      {o['message']}" if o["message"] else ""))
            print(f"\nRecorded in {os.path.join(ctx.results, PROVENANCE_FILE)}" if any(o["outcome"] == "regenerated" for o in outcomes) else "")
        plan = build_plan(Ctx(ctx.results, ctx.data, ctx.sheet_path, ctx.only, False, ctx.predictions))
        sections = section_report(ctx, plan)
    failed = [o for o in outcomes if o["outcome"] == "failed"]
    if args.report and not args.dry_run and not failed:
        code = rebuild_report(ctx)
        if code != 0:
            print(f"The report rebuild exited with {code}.", file=sys.stderr)
    remaining = outstanding(ctx, plan)
    if args.json:
        print(json.dumps({"results": ctx.results, "run": info, "sections": sections, "outcomes": outcomes, "still_missing": [e["files"] for e in remaining]}, indent=2, default=str))
    elif remaining:
        print("\nStill missing (cannot be regenerated from what is present):")
        for e in remaining[:20]:
            print(f"  {', '.join(e['files'])}" + (": " + "; ".join(e["needs"]) if e["needs"] else ""))
        if len(remaining) > 20:
            print(f"  ... and {len(remaining) - 20} more")
        print("Supply the data folder with --data-dir (reads, reference FASTAs, truth tables) and, if predictions were not kept, the original results folder with --predictions-dir.")
    return EXIT_MISSING if (remaining or failed) else EXIT_OK


def rebuild_report(ctx):
    command = [sys.executable, "-m", "plasbench", "report", "--results-dir", ctx.results, "--no-report-prompt"]
    if ctx.data:
        command += ["--data-dir", ctx.data]
    if ctx.sheet_path:
        command += ["--samples", ctx.sheet_path]
    print("\nRebuilding the report: " + " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("check", "regenerate"):
        p = sub.add_parser(name)
        p.add_argument("results_dir")
        p.add_argument("--data-dir")
        p.add_argument("--cohort", help="the cohort or sample sheet TSV of the run (same as --samples)")
        p.add_argument("--samples", help="the sample sheet TSV of the run")
        p.add_argument("--json", action="store_true")
        if name == "regenerate":
            p.add_argument("--only", help="comma-separated parts to rebuild: " + ", ".join(ALL_KEYS))
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--yes", action="store_true")
            p.add_argument("--force", action="store_true")
            p.add_argument("--report", action="store_true")
            p.add_argument("--predictions-dir", help="the original results folder, when predictions were not kept in this one (verified against scores.tsv)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return cmd_check(args) if args.action == "check" else cmd_regenerate(args)


if __name__ == "__main__":
    sys.exit(main())
