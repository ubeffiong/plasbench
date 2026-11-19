#!/usr/bin/env python3
"""plasbench regenerate-visuals / check-results (python/regenerate_visuals.py) and the kept report inputs (python/keep_report_inputs.py).

Fixtures are built here from the committed results_audit sample (truth, predictions and alignments) plus a tiny reference, sequence report and read pair;
the "fresh run" files are written by the same scripts stage 5 and stage 3 call, with the same arguments, so the byte-identity check is against what
a run writes, not against a stored copy. What this does NOT run: minimap2 (not needed when alignments are present or copied) and a whole stage 5.

  1  the dry run: sections, files, REGEN / MISSING words, nothing written, JSON shape
  2  byte-identical regeneration of alignments, structural files, QC tables and truth.tsv, and the provenance file
  3  no overwrite without --force; scores.tsv and benchmark.* tables never touched; --only scores explained
  4  missing inputs are explained (tool re-run, internet, reads, curated AMR table) and the exit code is 3
  5  layouts: a 0.2.3-style top-level-only folder, a current one, a partly deleted one, an empty one, a pre-0.2 one, legacy PAF names
  6  --predictions-dir: predictions are verified against scores.tsv / the kept summary before use
  7  the report's Run metadata names regenerated files
  8  keep_report_inputs: copies, budget, summaries, no sequences copied; KEEP_REPORT_INPUTS default and stage 5 / manifest wiring
  9  CLI: exit codes through `python -m plasbench`
"""
import gzip
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")
sys.path.insert(0, PY)
import keep_report_inputs  # noqa: E402
import regenerate_visuals as rv  # noqa: E402
import report_regenerated  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {str(detail)[:600]}"))
    ok = ok and bool(good)


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def run(*args, expect=None):
    result = subprocess.run([sys.executable, os.path.join(PY, "regenerate_visuals.py")] + [str(a) for a in args], capture_output=True, text=True, cwd=ROOT, stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout + result.stderr


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def fastq(path, seed, pairs=3000, length=100):
    rng = random.Random(seed)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.GzipFile(path, "wb", mtime=0) as handle:
        for i in range(pairs):
            seq = "".join(rng.choice("ACGT") for _ in range(length))
            handle.write(f"@r{i}/1\n{seq}\n+\n{'I' * length}\n".encode())


AUDIT = os.path.join(ROOT, "results_audit", "sample1")


def build(base, with_qc=True):
    """A finished-run fixture: results/ (what a run keeps) and data/ (what only the data folder has). Returns (results, data)."""
    results, data = os.path.join(base, "results"), os.path.join(base, "data")
    s = "iso1"
    for name in ("truth.tsv", "pred_good.plasmid.fasta", "pred_shy.plasmid.fasta", "good.pred_vs_ref.paf", "shy.pred_vs_ref.paf"):
        os.makedirs(os.path.join(results, s), exist_ok=True)
        shutil.copyfile(os.path.join(AUDIT, name), os.path.join(results, s, name))
    # data folder: reference + report (truth.tsv is rebuilt from them), annotation, AMR, circular, reads
    rng = random.Random(7)
    seqs = {"chr1": 8000, "pA": 2000, "pB": 1500}
    write(os.path.join(data, s, "reference.fna"), "".join(f">{n}\n" + "".join(rng.choice("ACGT") for _ in range(l)) + "\n" for n, l in seqs.items()))
    write(os.path.join(data, s, "sequence_report.jsonl"), "".join(
        json.dumps({"refseqAccession": n, "assignedMoleculeLocationType": "Chromosome" if n == "chr1" else "Plasmid", "length": l}) + "\n" for n, l in seqs.items()))
    write(os.path.join(data, s, "truth_amr.tsv"), "sequence_id\tstart\tend\tgene\tevidence_tier\npA\t100\t900\tblaTEM-1\tcurated\n")
    write(os.path.join(data, s, "truth_circular.tsv"), "sequence_id\tcircular\npA\ttrue\n")
    write(os.path.join(data, s, "truth_features.tsv"), "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\npA\t10\t500\tamr\tblaTEM-1\tabricate\t1\n")
    fastq(os.path.join(data, s, "SRRFAKE_1.fastq.gz"), 1)
    fastq(os.path.join(data, s, "SRRFAKE_2.fastq.gz"), 2)
    sheet = os.path.join(base, "samples.tsv")
    write(sheet, "sample_id\tassembly_accession\tsra_run\niso1\tGCF_000000001.1\tSRRFAKE\n")
    write(os.path.join(results, "scores.tsv"),
          "sample\ttool\tanalysis_track\tmapped_pred_bp\tunmapped_pred_bp\tpredicted_record_count\niso1\tgood\tshort_read\t3500\t0\t2\niso1\tshy\tshort_read\t1500\t0\t1\n")
    write(os.path.join(results, "tool_status.tsv"), "sample\ttool\tstatus\niso1\tgood\tcompleted\niso1\tshy\tcompleted\n")
    write(os.path.join(results, "benchmark.leaderboard.tsv"), "rank\ttool\n1\tgood\n")
    write(os.path.join(results, "run_manifest.json"), json.dumps({"tool_version": "0.5.0", "settings": {"MINIMAP2_PRESET": "asm5"}}))
    return results, data, sheet


def fresh_run_files(results, data, sheet):
    """Write the per-sample files exactly as stages 3 and 5 do (same scripts, same arguments); returns {relative path: sha256}."""
    s = "iso1"
    sdir = os.path.join(results, s)
    subprocess.run([sys.executable, os.path.join(PY, "make_truth.py"), "--report", os.path.join(data, s, "sequence_report.jsonl"), "--fasta",
                    os.path.join(data, s, "reference.fna"), "--out", os.path.join(base_truth(results), "truth.tsv")], check=True, capture_output=True)
    os.makedirs(os.path.join(sdir, "visualization"), exist_ok=True)
    d = os.path.join(data, s)
    subprocess.run([sys.executable, os.path.join(PY, "call_structural_variants.py"), "--truth", os.path.join(sdir, "truth.tsv"), "--results-dir", results, "--sample", s,
                    "--events-out", os.path.join(sdir, "structural_events.tsv"), "--summary-out", os.path.join(sdir, "structural_summary.tsv"),
                    "--json-out", os.path.join(sdir, "visualization", "structural_calls.json")], check=True, capture_output=True)
    subprocess.run([sys.executable, os.path.join(PY, "build_visualization_data.py"), "--truth", os.path.join(sdir, "truth.tsv"), "--reference", os.path.join(d, "reference.fna"),
                    "--results-dir", results, "--sample", s, "--amr-truth", os.path.join(d, "truth_amr.tsv"), "--feature-truth", os.path.join(d, "truth_features.tsv"),
                    "--protein-truth", os.path.join(d, "truth_proteins.tsv"), "--circular-truth", os.path.join(d, "truth_circular.tsv"),
                    "--max-blocks-per-tool", "2000", "--max-nucleotide-bp", "2000", "--out", os.path.join(sdir, "visualization", "alignment_blocks.json"),
                    "--structural-out", os.path.join(sdir, "visualization", "structural_metrics.tsv")], check=True, capture_output=True)
    shards = os.path.join(results, ".shards")
    os.makedirs(shards, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(PY, "short_read_qc.py"), "qc", "--sample", s, "--r1", os.path.join(d, "SRRFAKE_1.fastq.gz"), "--r2", os.path.join(d, "SRRFAKE_2.fastq.gz"),
                    "--out", os.path.join(shards, f"{s}.tsv"), "--thresholds", os.path.join(ROOT, "config", "short_read_qc_thresholds.tsv"), "--max-pairs", "200000"],
                   check=True, capture_output=True)
    subprocess.run([sys.executable, os.path.join(PY, "short_read_qc.py"), "merge", "--shards", shards, "--out", os.path.join(results, "short_read_qc.tsv"),
                    "--status-out", os.path.join(results, "short_read_qc_status.tsv"), "--mode", "report"], check=True, capture_output=True)
    shutil.rmtree(shards)
    return {f: sha(os.path.join(results, f)) for f in GENERATED}


def base_truth(results):
    return os.path.join(results, "iso1")


GENERATED = ["iso1/truth.tsv", "iso1/visualization/alignment_blocks.json", "iso1/visualization/structural_metrics.tsv", "iso1/visualization/structural_calls.json",
             "iso1/structural_events.tsv", "iso1/structural_summary.tsv", "short_read_qc.tsv", "short_read_qc_status.tsv"]


def delete_generated(results):
    for f in GENERATED:
        os.remove(os.path.join(results, f))


tmp = tempfile.mkdtemp(prefix="regen_")
try:
    # ---------------------------------------------------------------- 2 (done first: it builds the reference hashes) and 1
    results, data, sheet = build(os.path.join(tmp, "a"))
    originals = fresh_run_files(results, data, sheet)
    check("the fixture's fresh run wrote every file the regeneration is to rebuild", all(os.path.isfile(os.path.join(results, f)) for f in GENERATED), originals)
    protected = {f: sha(os.path.join(results, f)) for f in ("scores.tsv", "tool_status.tsv", "benchmark.leaderboard.tsv", "run_manifest.json")}
    delete_generated(results)

    code, out = run("check", results, "--data-dir", data, "--samples", sheet)
    check("check-results exits 3 while a section cannot draw, and names the section", code == 3 and "NOT AVAILABLE" in out and "Synteny ribbons" in out, (code, out[:500]))
    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--dry-run")
    check("the dry run lists what can be regenerated and exits 0 when everything can", code == 0 and "REGEN" in out, (code, out[-900:]))
    check("the dry run names the sections and the files behind them",
          "Report sections that need per-sample files" in out and "alignment_blocks.json" in out and "short_read_qc.tsv" in out and "Summary:" in out, out[:900])
    check("the dry run wrote nothing", not any(os.path.exists(os.path.join(results, f)) for f in GENERATED) and not os.path.exists(os.path.join(results, "regenerated_inputs.json")))
    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--dry-run", "--json")
    try:
        doc = json.loads(out)
    except ValueError:
        doc = {}
    check("--json prints sections, files and the run", {"run", "sections", "outcomes"} <= set(doc) or {"run", "sections", "files"} <= set(doc), out[:300])

    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet)
    check("without --yes and without a terminal nothing is written (exit 2) and it says so", code == 2 and "--yes" in out and not os.path.exists(os.path.join(results, GENERATED[1])), (code, out[-300:]))

    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--yes")
    check("regenerate --yes exits 0 and says what it wrote", code == 0 and "regenerated" in out, (code, out[-1200:]))
    redone = {f: sha(os.path.join(results, f)) for f in GENERATED if os.path.isfile(os.path.join(results, f))}
    check("every regenerated file is byte-identical to what the pipeline's own scripts wrote",
          redone == originals, {f: (originals[f][:8], redone.get(f, "missing")[:8]) for f in originals if redone.get(f) != originals[f]})
    check("scores.tsv, the manifest and the benchmark tables were not touched", {f: sha(os.path.join(results, f)) for f in protected} == protected)
    prov = json.load(open(os.path.join(results, "regenerated_inputs.json"), encoding="utf-8"))
    files = {e["file"] for e in prov["entries"]}
    check("regenerated_inputs.json records every file, when, the versions and a hash of the inputs",
          set(GENERATED) <= files and all(e["regenerated_at"] and e["plasbench_version"] and e["inputs_sha256"] and e["inputs"] and "tool_versions" in e for e in prov["entries"]), prov["entries"][:1])
    check("the provenance names the data folder files by label, not by machine path", all(":" not in i["input"] or i["input"].startswith(("data:", "predictions:")) for e in prov["entries"] for i in e["inputs"]) and
          all(os.path.abspath(data) not in json.dumps(e) for e in prov["entries"]), prov["entries"][0]["inputs"])
    kept = {"iso1/truth_amr.tsv", "iso1/truth_circular.tsv", "iso1/truth_features.tsv"}
    check("the small data-folder tables were copied into the results folder", all(os.path.isfile(os.path.join(results, f)) for f in kept), os.listdir(os.path.join(results, "iso1")))
    check("prediction summaries were written", os.path.isfile(os.path.join(results, "iso1", "good.prediction_summary.tsv")))

    # ---------------------------------------------------------------- 3 refuse to overwrite
    sentinel = os.path.join(results, "iso1", "visualization", "alignment_blocks.json")
    write(sentinel, "SENTINEL\n")
    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--yes")
    check("an existing file is never overwritten without --force", open(sentinel).read() == "SENTINEL\n" and code == 0, (code, out[-400:]))
    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--yes", "--force", "--only", "alignments")
    check("--force rebuilds it (and only it, with --only)", sha(sentinel) == originals["iso1/visualization/alignment_blocks.json"] and code == 0, (code, out[-400:]))
    code, out = run("regenerate", results, "--data-dir", data, "--samples", sheet, "--yes", "--only", "scores")
    check("--only scores never rebuilds scores and explains what to run instead", "not rebuilt by this command" in out and {f: sha(os.path.join(results, f)) for f in protected} == protected, out[-400:])
    code, out = run("regenerate", results, "--only", "nonsense", "--yes")
    check("an unknown --only key is a usage error", code == 2 and "unknown --only" in out, (code, out))

    # ---------------------------------------------------------------- 4 missing inputs explained
    results2, data2, sheet2 = build(os.path.join(tmp, "b"))
    os.remove(os.path.join(results2, "iso1", "pred_good.plasmid.fasta"))
    os.remove(os.path.join(results2, "iso1", "good.pred_vs_ref.paf"))
    shutil.rmtree(data2)
    code, out = run("check", results2, "--samples", sheet2)
    check("with predictions deleted it says a tool re-run is needed", "re-run" in out and "pred_<tool>.plasmid.fasta" in out, out[-900:])
    check("with the reference missing it says a download needs internet access", "internet access" in out, out[-900:])
    check("with reads missing it says what to supply", "read pairs" in out, out[-900:])
    check("a curated AMR table is never promised", "curated" in out and "never generated" in out, out[-900:])
    code, out = run("regenerate", results2, "--samples", sheet2, "--yes")
    check("regenerate exits 3 when something required is still missing", code == 3 and "Still missing" in out, (code, out[-500:]))

    # ---------------------------------------------------------------- 5 layouts
    old = os.path.join(tmp, "old023")
    write(os.path.join(old, "scores.tsv"), "sample\ttool\tanalysis_track\tpredicted_record_count\tmapped_pred_bp\tunmapped_pred_bp\nx1\tmob_recon\tshort_read\t3\t10\t0\n")
    write(os.path.join(old, "tool_status.tsv"), "sample\ttool\tstatus\tprediction_fasta\nx1\tmob_recon\tcompleted\t/gone/pred.fasta\n")
    write(os.path.join(old, "run_manifest.json"), json.dumps({"tool_version": "0.2.3"}))
    write(os.path.join(old, "benchmark.leaderboard.tsv"), "rank\n1\n")
    code, out = run("check", old)
    check("a 0.2.3-style top-level-only folder is read, called curated or published, and exits 3", code == 3 and "0.2.3" in out and "top-level tables only" in out and "curated or published" in out, (code, out[:600]))
    code, out = run("regenerate", old, "--dry-run")
    check("its dry run says what is missing and does not crash", code == 3 and "Summary: 0 present, 0 can be regenerated" in out, (code, out[-400:]))
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    code, out = run("check", empty)
    check("an empty folder is reported as empty, not as an error", code == 3 and "layout: empty" in out and "nothing to inspect" in out, (code, out[:400]))
    code, out = run("check", os.path.join(tmp, "does-not-exist"))
    check("a missing folder is a usage error", code == 2, (code, out))
    partial, pdata, psheet = build(os.path.join(tmp, "c"))
    originals_c = fresh_run_files(partial, pdata, psheet)
    os.remove(os.path.join(partial, "iso1", "visualization", "alignment_blocks.json"))
    code, out = run("check", partial, "--data-dir", pdata, "--samples", psheet)
    check("a partly deleted folder says only the alignments are missing and that they can be rebuilt", "present   alignments" not in out and "REGEN" in out and "can be regenerated" in out.lower() or "REGEN" in out, out[:900])
    ancient = os.path.join(tmp, "ancient")
    shutil.copytree(partial, ancient)
    write(os.path.join(ancient, "run_manifest.json"), json.dumps({"tool_version": "0.1.5"}))
    code, out = run("check", ancient)
    check("a pre-0.2 folder is read but the folder's age is said precisely", "older than 0.2" in out and "0.1.5" in out, out[:500])
    legacy = os.path.join(tmp, "legacy")
    shutil.copytree(partial, legacy)
    for f in os.listdir(os.path.join(legacy, "iso1")):
        if f.endswith(".pred_vs_ref.paf"):
            os.rename(os.path.join(legacy, "iso1", f), os.path.join(legacy, "iso1", f.replace(".pred_vs_ref.paf", ".paf")))
    code, out = run("check", legacy)
    check("legacy PAF names (<tool>.paf) are called out", "legacy PAF names" in out and "<tool>.paf" in out, out[:600])

    # ---------------------------------------------------------------- 6 --predictions-dir
    results3, data3, sheet3 = build(os.path.join(tmp, "d"))
    original_dir = os.path.join(tmp, "original_results")
    shutil.copytree(os.path.join(results3, "iso1"), os.path.join(original_dir, "iso1"))
    for f in ("pred_good.plasmid.fasta", "pred_shy.plasmid.fasta", "good.pred_vs_ref.paf", "shy.pred_vs_ref.paf"):
        os.remove(os.path.join(results3, "iso1", f))
    code, out = run("regenerate", results3, "--data-dir", data3, "--samples", sheet3, "--predictions-dir", original_dir, "--dry-run")
    check("predictions from --predictions-dir are accepted when they match the scores.tsv row", "verified: record count (2)" in out and "match the scores.tsv row" in out, out[:1500])
    with open(os.path.join(original_dir, "iso1", "pred_good.plasmid.fasta"), "a") as handle:
        handle.write(">extra\nACGT\n")
    code, out = run("regenerate", results3, "--data-dir", data3, "--samples", sheet3, "--predictions-dir", original_dir, "--dry-run")
    check("predictions that are not the scored ones are refused with the numbers", "not the ones this run scored" in out and "scores.tsv scored 2 records" in out, out[:1500])
    shutil.copyfile(os.path.join(AUDIT, "pred_good.plasmid.fasta"), os.path.join(original_dir, "iso1", "pred_good.plasmid.fasta"))
    code, out = run("regenerate", results3, "--data-dir", data3, "--samples", sheet3, "--predictions-dir", original_dir, "--yes")
    check("verified predictions are copied with their alignments and the alignment files are built", os.path.isfile(os.path.join(results3, "iso1", "visualization", "alignment_blocks.json"))
          and os.path.isfile(os.path.join(results3, "iso1", "good.pred_vs_ref.paf")), (code, out[-600:]))
    prov3 = json.load(open(os.path.join(results3, "regenerated_inputs.json"), encoding="utf-8"))
    check("their provenance says they came from the predictions folder", any(i["input"].startswith("predictions:") for e in prov3["entries"] for i in e["inputs"]))

    # ---------------------------------------------------------------- 7 the report says so
    note = report_regenerated.note_html(results)
    check("the Run metadata item says the files were regenerated after the run", "regenerated after the run" in note and "file(s)" in note and "regenerated_inputs.json" in note and "Scores and the benchmark tables are the run" in note, note)
    check("no item without a provenance file", report_regenerated.note_html(os.path.join(tmp, "empty")) == "")
    source = open(os.path.join(PY, "build_html_report.py"), encoding="utf-8").read()
    check("the report build calls it where Run metadata is made", "report_regenerated.note_html(results_dir)" in source)

    # ---------------------------------------------------------------- 8 keep_report_inputs
    kdata, kres = os.path.join(tmp, "kdata"), os.path.join(tmp, "kres")
    write(os.path.join(kdata, "s", "truth.tsv"), "sequence_id\tmolecule_type\tlength\npA\tPLASMID\t10\n")
    write(os.path.join(kdata, "s", "truth_amr.tsv"), "a\tb\n1\t2\n")
    write(os.path.join(kdata, "s", "reference.fna"), ">pA\nACGTACGTAC\n")
    write(os.path.join(kdata, "s", "reads_1.fastq.gz"), "not reads")
    write(os.path.join(kres, "s", "pred_t.plasmid.fasta"), ">r1\nACGT\n>r2\nGGCC\n")
    manifest = keep_report_inputs.keep(kdata, kres, "s", max_kb=64)
    names = sorted(os.listdir(os.path.join(kres, "s")))
    check("the truth tables, a prediction summary and report_inputs.json are kept", {"truth.tsv", "truth_amr.tsv", "t.prediction_summary.tsv", "report_inputs.json"} <= set(names), names)
    check("reads and reference FASTAs are never copied", not any(n.startswith("reads") or n == "reference.fna" for n in names), names)
    summary = keep_report_inputs.read_summary(os.path.join(kres, "s", "t.prediction_summary.tsv"))
    check("the summary has the record, length and hash but not the sequence", set(summary) == {"r1", "r2"} and summary["r1"][0] == 4 and "ACGT" not in open(os.path.join(kres, "s", "t.prediction_summary.tsv")).read(), summary)
    big = os.path.join(kdata, "s", "truth_features.tsv")
    write(big, "sequence_id\tx\n" + "pA\t1\n" * 40000)
    manifest = keep_report_inputs.keep(kdata, kres, "s", max_kb=16)
    check("a file over the budget is skipped and listed with the reason", any(s["file"] == "truth_features.tsv" and "budget" in s["reason"] for s in manifest["skipped"]) and not os.path.exists(os.path.join(kres, "s", "truth_features.tsv")), manifest["skipped"])
    check("the manifest records sizes and hashes", all(k["bytes"] > 0 and len(k["sha256"]) == 64 for k in manifest["kept"]), manifest)
    check("KEEP_REPORT_INPUTS is on by default and off with 0", keep_report_inputs.enabled({}) and not keep_report_inputs.enabled({"KEEP_REPORT_INPUTS": "0"}) and keep_report_inputs.enabled({"KEEP_REPORT_INPUTS": "1"}))
    config = open(os.path.join(ROOT, "config", "config.sh"), encoding="utf-8").read()
    check("config.sh defaults KEEP_REPORT_INPUTS to 1 with a budget", 'export KEEP_REPORT_INPUTS="${KEEP_REPORT_INPUTS:-1}"' in config and "KEEP_REPORT_INPUTS_MAX_KB" in config)
    score = open(os.path.join(ROOT, "scripts", "05_score.sh"), encoding="utf-8").read()
    check("stage 5 calls keep_report_inputs.py when KEEP_REPORT_INPUTS=1, after the visualization step", score.index("build_visualization_data.py") < score.index("keep_report_inputs.py") and 'KEEP_REPORT_INPUTS:-1}" == "1"' in score)
    manifest_py = open(os.path.join(PY, "write_manifest.py"), encoding="utf-8").read()
    check("the run manifest records the settings regeneration needs", all(k in manifest_py for k in ("VISUALIZATION_MAX_BLOCKS_PER_TOOL", "KEEP_REPORT_INPUTS")))
    # a results folder that kept its inputs can be rebuilt with no data folder at all
    selfish, sdata, ssheet = build(os.path.join(tmp, "e"))
    originals_e = fresh_run_files(selfish, sdata, ssheet)
    keep_report_inputs.keep(sdata, selfish, "iso1", 2048)
    shutil.copytree(selfish, os.path.join(tmp, "moved"))
    moved = os.path.join(tmp, "moved")
    os.remove(os.path.join(moved, "iso1", "visualization", "alignment_blocks.json"))
    code, out = run("regenerate", moved, "--yes", "--only", "alignments")
    check("a results folder that kept its inputs rebuilds its alignment blocks with no data folder", code == 0 and sha(os.path.join(moved, "iso1", "visualization", "alignment_blocks.json")) == originals_e["iso1/visualization/alignment_blocks.json"], (code, out[-500:]))

    # ---------------------------------------------------------------- 9 the CLI
    def cli(*args):
        r = subprocess.run([sys.executable, "-m", "plasbench"] + [str(a) for a in args], capture_output=True, text=True, cwd=ROOT)
        return r.returncode, r.stdout + r.stderr
    code, out = cli("check-results", results2)
    check("`plasbench check-results` exits 3 when sections cannot draw", code == 3 and "NOT AVAILABLE" in out, (code, out[-300:]))
    full, fdata, fsheet = build(os.path.join(tmp, "f"))
    fresh_run_files(full, fdata, fsheet)
    code, out = cli("check-results", full, "--samples", fsheet)
    check("a complete folder exits 0 from check-results except for the QC section it has", code in (0, 3), (code, out[-300:]))
    os.remove(os.path.join(full, "iso1", "visualization", "alignment_blocks.json"))
    code, out = cli("regenerate-visuals", full, "--data-dir", fdata, "--samples", fsheet, "--yes")
    check("`plasbench regenerate-visuals` exits 0 when everything missing was regenerated", code == 0 and os.path.isfile(os.path.join(full, "iso1", "visualization", "alignment_blocks.json")), (code, out[-500:]))
    code, out = cli("rebuild-report", full, "--dry-run")
    check("`plasbench rebuild-report` is the same command", code == 0 and "regenerate-visuals" in out, (code, out[-300:]))
    code, out = cli("regenerate-visuals", results2, "--samples", sheet2, "--dry-run")
    check("`plasbench regenerate-visuals` exits 3 when something stays missing", code == 3, (code, out[-300:]))

    # ---------------------------------------------------------------- 10 the committed results folders
    import glob as _glob
    folders = sorted(d for d in _glob.glob(os.path.join(ROOT, "results_*")) if os.path.isdir(d))
    check("the repository has results folders to inspect (cohort 1 among them)", any(d.endswith("results_real_cohort1") for d in folders), folders)
    for folder in folders:
        code, out = run("check", folder, "--json")
        try:
            report = json.loads(out)
        except ValueError:
            report = {}
        check(f"{os.path.basename(folder)}: check-results inspects it without error and returns a layout and sections", code in (0, 3) and report.get("run", {}).get("layout") and report.get("sections"), (code, out[:200]))
    cohort1 = os.path.join(ROOT, "results_real_cohort1")
    prov1 = os.path.join(cohort1, "regenerated_inputs.json")
    if os.path.isfile(prov1):
        entries = json.load(open(prov1, encoding="utf-8"))["entries"]
        check("cohort 1: every regenerated file is recorded with the hash of its inputs", entries and all(e["inputs_sha256"] and e["inputs"] for e in entries), entries[:1])
        check("cohort 1: only the two isolates whose predictions matched scores.tsv were regenerated", {e["file"].split("/")[0] for e in entries if "/" in e["file"]} <= {"upec_ecpf5", "upec_ecpf7"})
        check("cohort 1: no table of the published run is among the regenerated files", not any(e["file"].startswith(("benchmark.", "scores.tsv", "tool_status", "run_manifest")) for e in entries))
        code, out = run("check", cohort1, "--cohort", os.path.join(ROOT, "cohorts", "public-v1.tsv"))
        check("cohort 1 is reported as partial, not available, until the data folder is supplied (exit 3)", code == 3 and "PARTIAL" in out and "2 of 10" in out, (code, out[:500]))
    status_doc = open(os.path.join(ROOT, "docs", "COHORT1_REBUILD_STATUS.md"), encoding="utf-8").read()
    check("the cohort 1 status page gives the command to run once the data folder is supplied",
          "plasbench regenerate-visuals results_real_cohort1" in status_doc and "--data-dir <path-to-data>" in status_doc and "--predictions-dir" in status_doc)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL REGENERATE-VISUALS TESTS PASSED" if ok else "REGENERATE-VISUALS TESTS FAILED")
sys.exit(0 if ok else 1)
