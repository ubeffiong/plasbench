#!/usr/bin/env python3
"""Turn the supplementary data of published plasmid benchmarks into long-format "published outcome" tables.

A user who runs PlasBench on a publication's isolates can then put PlasBench's result beside the publication's own
(`plasbench compare-published`). This script builds the tables from the papers' own supplementary workbooks. It writes, per study,

  cohorts/published/<study>.published.tsv   one row per (isolate, tool, metric[, item]) the publication reports or implies
  cohorts/published/<study>.meta.json       citation, where the data came from (URL, SHA-256), how each published metric
                                            maps to a PlasBench metric, which tools have a PlasBench counterpart, caveats

Studies:
  plsmd2026    Lotfi et al. 2026 (BMC Bioinformatics, doi 10.1186/s12859-026-06585-y), Additional file 2, sheets Dataset A and B:
               the paper's own per-plasmid recall of plsMD, MOB-suite and gplas. Copied, not recomputed.
  teixeira2025 Teixeira et al. 2025 (Briefings in Bioinformatics, doi 10.1093/bib/bbaf589), data/predictions.xlsx of
               github.com/broadinstitute/plasmid-detection-benchmark (MIT): the published contig-level calls of 13 tools beside the hybrid
               ground truth. The per-isolate precision, recall and F1 are COMPUTED HERE from those published calls (the paper's
               figures are not read), so they are the paper's data under one stated definition, not the paper's printed numbers.

Raw workbooks are not committed (Teixeira's is 2.8 MB); their SHA-256 is recorded so the tables can be rebuilt and checked:

  python python/build_published_outcomes.py --plsmd-xlsx 12859_2026_6585_MOESM2_ESM.xlsx --teixeira-xlsx predictions.xlsx

Needs openpyxl (only to read the workbooks; the comparison itself needs only the standard library).
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT_DIR = os.path.join(ROOT, "cohorts", "published")
CAND = os.path.join(ROOT, "cohorts", "candidates")
TAB = chr(9)

COLUMNS = ["study", "subset", "paper_sample", "biosample", "tool", "metric", "item", "value", "n_items", "size_bp", "size_class", "replicon"]

PLSMD_URL = "https://static-content.springer.com/esm/art%3A10.1186%2Fs12859-026-06585-y/MediaObjects/12859_2026_6585_MOESM2_ESM.xlsx"
TEIXEIRA_URL = "https://raw.githubusercontent.com/broadinstitute/plasmid-detection-benchmark/main/data/predictions.xlsx"

PLSMD_TOOLS = OrderedDict([("plsMD_recall", "plsMD"), ("mobsuite_recall", "MOB-suite"), ("gplas_recall", "gplas")])
TEIXEIRA_ALIASES = {"UCICRE123": "UCI123", "UCICRE141": "UCI141"}  # the repository's spelling versus Supplementary Table 1
NOT_PLASMID = {"chromosome", "none", "unknown", "unclassified", "repeat", ""}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


def biosample_map(candidates_file):
    return {r["paper_identifier"]: r["biosample"] for r in read_tsv(os.path.join(CAND, candidates_file)) if r.get("biosample")}


def fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value):
    return "" if value is None else f"{value:.6g}"


def sheet_rows(workbook, name):
    return [row for row in workbook[name].iter_rows(values_only=True)]


def plsmd_rows(xlsx):
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    biosamples = biosample_map("plsmd2026_filtered_candidates.tsv")
    biosamples.update(biosample_map("plsmd2026_novel_candidates.tsv"))
    out = []
    for sheet, subset in (("Dataset A", "filtered"), ("Dataset B", "novel")):
        rows = sheet_rows(wb, sheet)
        head = list(rows[0])
        index = {name: head.index(name) for name in head if name}
        sample_col = head[0]
        acc_col = head[1]
        for row in rows[1:]:
            if not row or row[0] in (None, ""):
                continue
            sample = str(row[0]).strip()
            for column, tool in PLSMD_TOOLS.items():
                value = fnum(row[index[column]])
                out.append({"study": "plsmd2026", "subset": subset, "paper_sample": sample, "biosample": biosamples.get(sample, ""),
                            "tool": tool, "metric": "plasmid_recall", "item": str(row[1]).strip(),
                            "value": fmt(value / 100 if value is not None else None), "n_items": "1",
                            "size_bp": str(row[index["Plasmid_size"]] or ""), "size_class": str(row[index["Plasmid_size_category"]] or ""),
                            "replicon": str(row[index["Replicon_plasmid_type"]] or "")})
    return out, (sample_col, acc_col)


def teixeira_rows(xlsx):
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    biosamples = biosample_map("teixeira2025_candidates.tsv")
    truth = {}
    for row in sheet_rows(wb, "Ground-truth")[1:]:
        if row[0] is None:
            continue
        truth[(str(row[0]), str(row[1]))] = (str(row[3]).strip().lower() == "plasmid", fnum(row[7]) or 0.0)
    calls = OrderedDict()  # tool -> {(sample, contig): is_plasmid}
    detection = sheet_rows(wb, "Plasmid Detection")
    for j, tool in enumerate(detection[0][2:], 2):
        calls[tool] = {(str(r[0]), str(r[1])): str(r[j]).strip().lower() not in NOT_PLASMID for r in detection[1:] if r[0] is not None}
    best = sheet_rows(wb, "Plasmid Reconst. (Best Det.)")
    for j, tool in enumerate(best[0][2:], 2):
        if tool == "PlasBin-Flow":  # gplas2 is already in the detection sheet; its best-detection copy would double count
            calls[tool] = {(str(r[0]), str(r[1])): str(r[j]).strip().lower() not in NOT_PLASMID for r in best[1:] if r[0] is not None}
    per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0.0, 0]))  # (sample, tool) -> TP FP FN bpTP bpFP bpFN contigs
    for tool, mapping in calls.items():
        for key, predicted in mapping.items():
            actual, length = truth.get(key, (None, 0.0))
            if actual is None:
                continue
            cell = per[tool][key[0]]
            cell[6] += 1
            if predicted and actual:
                cell[0] += 1
                cell[3] += length
            elif predicted:
                cell[1] += 1
                cell[4] += length
            elif actual:
                cell[2] += 1
                cell[5] += length
    out = []
    for tool, samples in per.items():
        for sample, (tp, fp, fn, btp, bfp, bfn, n) in samples.items():
            paper_sample = TEIXEIRA_ALIASES.get(sample, sample)
            base = {"study": "teixeira2025", "subset": "", "paper_sample": paper_sample, "biosample": biosamples.get(paper_sample, ""),
                    "tool": tool, "item": sample, "n_items": str(n), "size_bp": "", "size_class": "", "replicon": ""}
            for suffix, (a, b, c) in (("count", (tp, fp, fn)), ("bp", (btp, bfp, bfn))):
                precision = a / (a + b) if a + b else None
                recall = a / (a + c) if a + c else None
                f1 = 2 * a / (2 * a + b + c) if 2 * a + b + c else None
                for metric, value in ((f"contig_precision_{suffix}", precision), (f"contig_recall_{suffix}", recall), (f"contig_f1_{suffix}", f1)):
                    out.append(dict(base, metric=metric, value=fmt(value)))
    return out, sorted(calls)


def write_table(study, rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{study}.published.tsv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(f"# Published outcomes of {study}, long format. Built by python/build_published_outcomes.py; see {study}.meta.json for sources and definitions.\n")
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=TAB, lineterminator=chr(10))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_meta(study, meta):
    path = os.path.join(OUT_DIR, f"{study}.meta.json")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
        handle.write(chr(10))
    return path


PLSMD_META = {
    "study": "plsmd2026",
    "title": "plsMD: a plasmid reconstruction tool from short-read assemblies",
    "citation": "Lotfi et al. 2026, BMC Bioinformatics, doi 10.1186/s12859-026-06585-y",
    "licence": "CC BY 4.0 (article and supplement)",
    "cohorts": ["pub-plsmd-filtered", "pub-plsmd-novel"],
    "what_it_is": "The paper's own per-plasmid recall for plsMD, MOB-suite and gplas on its 80-isolate filtered benchmark (244 plasmids) and "
                  "its 68-isolate novel set (269 plasmids). Values are copied from Additional file 2 and divided by 100.",
    "source": {"url": PLSMD_URL, "file": "12859_2026_6585_MOESM2_ESM.xlsx"},
    "tool_map": {"plsMD": "plsmd", "MOB-suite": "mob_recon", "gplas": "gplas2_mob"},
    "tool_map_notes": {"gplas": "The paper ran gplas; PlasBench's tool is gplas2 (its successor), so this pair is similar, not identical."},
    "metrics": [{
        "published_metric": "plasmid_recall", "label": "Per-plasmid recall",
        "plasbench_metric": "completeness", "plasbench_source": "{sample}/{tool}.per_plasmid.tsv, column completeness (matched on the truth plasmid accession)",
        "level": "per_plasmid", "comparability": "similar", "tolerance": 0.05,
        "note": "plsMD's recall is the share of a reference plasmid's bases found in the reconstructed plasmid; PlasBench's completeness is the "
                "share of the truth plasmid's bases covered by aligned predicted sequence (MAPQ and identity filters apply). The same idea, "
                "not the same code."}],
    "caveats": [
        "plsMD's own tool column is the tool's published run on the paper's assemblies; a PlasBench run of plsmd uses your assembly, assembler and PLSDB release.",
        "The filtered set was chosen by the authors for samples whose Unicycler assembly is explained by the closed genome, which favours every tool.",
        "plsMD queries PLSDB, which probably contains the truth plasmids of the filtered set; the novel set is the paper's claim of absence from PLSDB 2024_05_31_v2, not verified here.",
        "Truth plasmids are the paper's GenBank accessions; PlasBench's truth for the same isolate comes from the resolved assembly and is matched by accession, so a plasmid absent from it is reported as unmatched, not as zero.",
    ],
}

TEIXEIRA_META = {
    "study": "teixeira2025",
    "title": "Circling in on plasmids: benchmarking plasmid detection and reconstruction tools for short-read data from diverse species",
    "citation": "Teixeira et al. 2025, Briefings in Bioinformatics, doi 10.1093/bib/bbaf589",
    "licence": "MIT (analysis repository data file); article open access",
    "cohorts": ["pub-teixeira2025"],
    "what_it_is": "The published contig-level calls of 13 tools on 250 isolates (12,795 short-read contigs) beside the hybrid-assembly ground truth. "
                  "Per-isolate precision, recall and F1 are computed by PlasBench from those published calls (plasmid is positive; chromosome, "
                  "unknown, unclassified and repeat calls count as not plasmid), by contig count and weighted by contig length.",
    "source": {"url": TEIXEIRA_URL, "file": "predictions.xlsx"},
    "tool_map": {"MOB-recon": "mob_recon", "PLASMe": "plasme", "PlaScope": "plascope", "Plasmer": "plasmer", "Platon": "platon",
                 "RFPlasmid": "rfplasmid", "geNomad": "genomad", "gplas2": "gplas2_mob", "plASgraph2": "plasgraph2", "PlasBin-Flow": "plasbin_flow",
                 "HyAsP": None, "PlasmidEC": None, "PlasmidFinder": None},
    "tool_map_notes": {"HyAsP": "No PlasBench adapter; published only.", "PlasmidEC": "No PlasBench adapter; published only.",
                       "PlasmidFinder": "A replicon marker, not a classifier; PlasBench scores a replicon baseline instead."},
    "metrics": [
        {"published_metric": "contig_precision_count", "label": "Contig precision (by contig count)", "plasbench_metric": "contig_precision_count",
         "plasbench_source": "scores.tsv, column contig_precision_count", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05,
         "note": "Both score contigs of the short-read assembly against a hybrid truth. PlasBench drops contigs under CONTIG_MIN_LENGTH and labels ambiguous and chimeric contigs unscorable; the published table keeps every contig."},
        {"published_metric": "contig_recall_count", "label": "Contig recall (by contig count)", "plasbench_metric": "contig_recall_count",
         "plasbench_source": "scores.tsv, column contig_recall_count", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "As above."},
        {"published_metric": "contig_f1_count", "label": "Contig F1 (by contig count)", "plasbench_metric": "contig_f1_count",
         "plasbench_source": "scores.tsv, column contig_f1_count", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "As above."},
        {"published_metric": "contig_precision_bp", "label": "Contig precision (length-weighted)", "plasbench_metric": "contig_precision_bp",
         "plasbench_source": "scores.tsv, column contig_precision_bp", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "As above."},
        {"published_metric": "contig_recall_bp", "label": "Contig recall (length-weighted)", "plasbench_metric": "contig_recall_bp",
         "plasbench_source": "scores.tsv, column contig_recall_bp", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "As above."},
        {"published_metric": "contig_f1_bp", "label": "Contig F1 (length-weighted)", "plasbench_metric": "contig_f1_bp",
         "plasbench_source": "scores.tsv, column contig_f1_bp", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "As above."}],
    "caveats": [
        "The published truth is a hybrid assembly built on the same Illumina reads used as benchmark input; 45 of 250 hybrids are not complete (see teixeira2025_repo_ground_truth_summary.tsv).",
        "The published contigs come from the authors' own assembly of each isolate; a PlasBench run assembles the reads again, so contig sets differ and per-isolate numbers are compared as means, not contig by contig.",
        "PlasBench's tool versions and databases differ from the paper's; a gap can be a version effect.",
        "Most of the 250 isolates have no deposited complete assembly: running them in PlasBench needs a hybrid truth rebuilt from the deposited reads (python/build_hybrid_truth.py).",
        "The precision, recall and F1 here are computed from the published calls under the definition above; they are not the figures printed in the paper.",
    ],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plsmd-xlsx")
    ap.add_argument("--teixeira-xlsx")
    ap.add_argument("--retrieved", default="2026-11-17", help="date the workbooks were downloaded (recorded in the metadata)")
    args = ap.parse_args()
    if not (args.plsmd_xlsx or args.teixeira_xlsx):
        ap.error("give --plsmd-xlsx and/or --teixeira-xlsx")
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        sys.exit("ERROR: openpyxl is needed to read the workbooks (pip install openpyxl)")
    if args.plsmd_xlsx:
        rows, _ = plsmd_rows(args.plsmd_xlsx)
        meta = json.loads(json.dumps(PLSMD_META))
        meta["source"].update({"sha256": sha256(args.plsmd_xlsx), "retrieved": args.retrieved})
        meta["rows"] = len(rows)
        write_table("plsmd2026", rows)
        write_meta("plsmd2026", meta)
        print(f"plsmd2026: {len(rows)} rows")
    if args.teixeira_xlsx:
        rows, tools = teixeira_rows(args.teixeira_xlsx)
        meta = json.loads(json.dumps(TEIXEIRA_META))
        meta["source"].update({"sha256": sha256(args.teixeira_xlsx), "retrieved": args.retrieved})
        meta["rows"] = len(rows)
        meta["published_tools"] = tools
        write_table("teixeira2025", rows)
        write_meta("teixeira2025", meta)
        print(f"teixeira2025: {len(rows)} rows; tools {', '.join(tools)}")


if __name__ == "__main__":
    main()
