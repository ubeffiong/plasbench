#!/usr/bin/env python3
"""Score the PlasEval paper's published plasmid bins with PlasBench, and compare with the original program.

Input is the PlasEval paper's own data (Mane et al. 2024; Zenodo 10.5281/zenodo.10785150, CC BY 4.0), shipped in
cohorts/plaseval_ecoli53/bins: for each of 53 E. coli isolates a ground_truth_bins.tsv and the bins of four tools (MOB-recon,
HyAsP, gplas2, PlasBin-flow), all on the contigs of the isolate's short-read assembly. Nothing is re-run: the tools' predictions
are the paper's. PlasBench computes best-match precision/recall/F1 and the repeat-aware PlasEval-style dissimilarity for every
isolate and tool, the tool-versus-tool agreement, and writes the tables and an HTML page with the error-profile charts.

When the original program is found (--plaseval-src, PLASEVAL_SRC, or the usual places; --no-original skips it) it is run on the
same pairs and its normalised dissimilarity is written beside PlasBench's, so agreement is measured on real bins and not only on
constructed cases. The same check runs inside a benchmark as the comparison gate (python/plaseval_gate.py).

  python3 python/plaseval_replication.py --out-dir results_plaseval \\
      [--alpha 0.5] [--plaseval-src PATH --plaseval-python PYTHON --original-timeout 300 --workers 2]
"""
import argparse
import csv
import os
import subprocess
import sys
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bin_agreement as ba  # noqa: E402
import plaseval_gate as gate  # noqa: E402
import report_fig_binerrors as fig  # noqa: E402

DEFAULT_BINS = os.path.join(HERE, "..", "cohorts", "plaseval_ecoli53", "bins")
TOOL_FILES = OrderedDict([("mob_recon", "mob_recon_bins.tsv"), ("hyasp", "hyasp_bins.tsv"), ("gplas2", "gplas2_bins.tsv"),
                          ("plasbin_flow", "plasbin_flow_bins.tsv")])
TAB, NL = chr(9), chr(10)


def read_bins(path):
    """PlasEval format (plasmid, contig, contig_len; whitespace separated): bin -> [contigs], contig -> length."""
    bins, lengths = OrderedDict(), {}
    with open(path, encoding="utf-8") as handle:
        rows = [line.split() for line in handle if line.strip()]
    for plasmid, contig, length in rows[1:]:
        members = bins.setdefault(plasmid, [])
        if contig not in members:
            members.append(contig)
        lengths[contig] = int(length)
    return bins, lengths


def labels_for(truth, pred, lengths):
    """The contig label table bin_agreement expects: a contig in a truth bin is PLASMID (listing every truth bin), any other chromosome."""
    member = {}
    for plasmid, contigs in truth.items():
        for contig in contigs:
            member.setdefault(contig, []).append(plasmid)
    return {c: {"length": n, "label": "PLASMID" if c in member else "CHROMOSOME", "plasmids": sorted(member.get(c, []))}
            for c, n in lengths.items()}


def samples_in(bins_dir):
    return sorted(d for d in os.listdir(bins_dir) if os.path.isfile(os.path.join(bins_dir, d, "ground_truth_bins.tsv")))


def score_all(bins_dir, alpha, repeats, max_calls):
    scores, pairs, matrix_acc = [], [], {}
    for sample in samples_in(bins_dir):
        truth, tl = read_bins(os.path.join(bins_dir, sample, "ground_truth_bins.tsv"))
        tools = OrderedDict()
        lengths = dict(tl)
        for tool, name in TOOL_FILES.items():
            path = os.path.join(bins_dir, sample, name)
            if os.path.isfile(path):
                tools[tool], tool_lengths = read_bins(path)
                lengths.update(tool_lengths)
        labels = labels_for(truth, None, lengths)
        for tool, pred in tools.items():
            e = ba.eval_bestmatch(pred, labels)
            d = ba.dissim_row(pred, labels, alpha, 0, repeats, max_calls)
            scores.append({
                "sample": sample, "tool": tool, "analysis_track": "short_read",
                "bestmatch_status": e["status"],
                **{f"bestmatch_{k}": ba._fmt(e[k]) for k in ("precision_count", "recall_count", "f1_count", "precision_bp",
                                                              "recall_bp", "f1_bp")},
                "dissim_status": d["status"], "bin_dissimilarity": ba._fmt(d["dissim"]), "dissim_split_cost": ba._fmt(d["split"]),
                "dissim_join_cost": ba._fmt(d["join"]), "dissim_extra_cost": ba._fmt(d["extra"]),
                "dissim_missing_cost": ba._fmt(d["missing"]), "dissim_norm": ba._fmt(d["norm"]),
                "dissim_repeats_dropped": d["repeats"], "dissim_repeat_families": d["families"],
                "dissim_repeat_search": d["search"], "bin_dissimilarity_alpha0": ba._fmt(d["alpha0"]),
                "bin_dissimilarity_alpha1": ba._fmt(d["alpha1"]),
                "n_truth_plasmids": len(truth), "n_predicted_bins": len(pred),
            })
            pairs.append((sample, tool))
            matrix_acc.setdefault((tool, "truth"), []).append(float(ba._fmt(d["dissim"])))
        names = list(tools)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                matrix_acc.setdefault((x, y), []).append(ba.pairwise_dissimilarity(tools[x], tools[y], lengths, alpha, repeats, max_calls))
    matrix = [{"tool_a": a, "tool_b": b, "n_samples": len(v), "mean_dissimilarity": ba._fmt(sum(v) / len(v))}
              for (a, b), v in sorted(matrix_acc.items())]
    return scores, matrix


def run_original(src, python, sample_dir, tool, alpha, timeout):
    """The original program's normalised dissimilarity for one pair, or (None, reason)."""
    return gate.original_dissimilarity(src, python, os.path.join(sample_dir, TOOL_FILES[tool]),
                                       os.path.join(sample_dir, "ground_truth_bins.tsv"), alpha, timeout)


def compare_original(scores, bins_dir, src, python, alpha, timeout, workers):
    def one(row):
        value, status = run_original(src, python, os.path.join(bins_dir, row["sample"]), row["tool"], alpha, timeout)
        return row, value, status
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for row, value, status in pool.map(one, scores):
            row["original_dissimilarity"] = "" if value is None else f"{value:.6f}"
            row["original_status"] = status
            if value is not None:
                row["abs_difference"] = f"{abs(value - float(row['bin_dissimilarity'])):.6f}"
            else:
                row["abs_difference"] = ""


def write_tsv(path, rows, fields=None):
    fields = fields or list(rows[0])
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, delimiter=TAB, lineterminator=NL)
        w.writeheader()
        w.writerows(rows)


PAGE_CSS = ("body{font-family:system-ui,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;line-height:1.5}"
            ".insight{border-left:4px solid #0072B2;background:rgba(0,114,178,.08);padding:2px 14px;margin:14px 0}"
            ".caution{border-color:#D55E00;background:rgba(213,94,0,.08)}.panel{overflow-x:auto}"
            "table{border-collapse:collapse;font-size:.9em}th,td{border:1px solid rgba(128,128,128,.4);padding:3px 8px;text-align:right}"
            "th:first-child,td:first-child{text-align:left}figure{margin:22px 0}figcaption{margin-bottom:6px}"
            "svg{max-width:100%;height:auto}")


def html_page(scores, matrix, alpha, n_samples, comparison):
    body = fig.section_html(scores, matrix)
    note = ("<p>PlasBench scores the <strong>published bins</strong> of four tools from the PlasEval paper "
            "(Mane et al. 2024, <a href='https://doi.org/10.1186/s12859-024-05941-0'>doi 10.1186/s12859-024-05941-0</a>; data "
            "<a href='https://doi.org/10.5281/zenodo.10785150'>Zenodo 10.5281/zenodo.10785150</a>, CC BY 4.0) on "
            f"{n_samples} <em>E. coli</em> isolates. No tool was re-run. Length exponent alpha = {alpha:g}. The ground truth is the "
            "paper's: hybrid contigs labelled by length and circularity, mapped onto the short-read assembly's contigs.</p>")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>PlasEval replication</title><style>{PAGE_CSS}</style></head><body><h1>PlasEval replication on 53 E. coli isolates</h1>"
            f"{note}{comparison}{body}</body></html>")


def comparison_html(scores):
    rows = [r for r in scores if r.get("original_status")]
    if not rows:
        return ("<div class='insight caution'><p>The original PlasEval program was not run here, so agreement with it on these "
                "bins is not shown (use --plaseval-src).</p></div>")
    ok = [r for r in rows if r["original_status"] == "ok"]
    diffs = [float(r["abs_difference"]) for r in ok if r["abs_difference"] != ""]
    worst = max(diffs) if diffs else 0.0
    other = {s: sum(r["original_status"] == s for r in rows) for s in ("timeout", "failed", "no_result")}
    text = (f"The original program was run on the same {len(rows)} isolate-tool pairs: {len(ok)} finished and PlasBench agreed on "
            f"{sum(d < 1e-3 for d in diffs)} of them to three decimals; the largest absolute difference is {worst:.6f}.")
    if any(other.values()):
        text += " Not compared: " + ", ".join(f"{n} {s}" for s, n in other.items() if n) + "."
    return f"<div class='insight{'' if worst < 1e-3 and not any(other.values()) else ' caution'}'><p>{text}</p></div>"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bins-dir", default=DEFAULT_BINS)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--repeats", choices=("aware", "drop"), default="aware")
    ap.add_argument("--max-calls", type=int, default=200000)
    ap.add_argument("--plaseval-src", help="src/ of a PlasEval checkout; found automatically when omitted (see plaseval_gate.py)")
    ap.add_argument("--no-original", action="store_true", help="do not look for or run the original program")
    ap.add_argument("--plaseval-python", default=sys.executable)
    ap.add_argument("--original-timeout", type=int, default=300)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    scores, matrix = score_all(a.bins_dir, a.alpha, a.repeats, a.max_calls)
    src = None if a.no_original else gate.find_original(a.plaseval_src)
    if src:
        compare_original(scores, a.bins_dir, src, a.plaseval_python, a.alpha, a.original_timeout, a.workers)
    write_tsv(os.path.join(a.out_dir, "plaseval_replication.scores.tsv"), scores)
    write_tsv(os.path.join(a.out_dir, "benchmark.tool_agreement.tsv"), matrix)
    n_samples = len({r["sample"] for r in scores})
    with open(os.path.join(a.out_dir, "plaseval_replication.html"), "w", encoding="utf-8") as handle:
        handle.write(html_page(scores, matrix, a.alpha, n_samples, comparison_html(scores)))
    agg = fig.aggregate(scores)
    print(f"{n_samples} isolates, {len(scores)} isolate-tool pairs -> {a.out_dir}")
    for e in agg:
        print(f"  {e['tool']:<13} n={e['n']:<3} dissimilarity {e['dissim']:.4f}  F1(bp) {e['f1']:.4f}  capped {e['capped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
