#!/usr/bin/env python3
"""Compare a PlasBench run with the outcomes a publication reported for the same isolates.

Run PlasBench on a publication's cohort (cohorts/pub-*.tsv or publication-v1.tsv), then:

  plasbench compare-published --results-dir results --samples cohorts/pub-plsmd-filtered.tsv [--html results/published_comparison.html]

For every study with a table in cohorts/published/ whose isolates appear in the sample sheet (matched by BioSample) it writes

  <prefix>.tsv         one row per tool, metric and stratum: pairs, published mean, PlasBench mean, difference, correlation, agreement
  <prefix>_pairs.tsv   every matched pair (isolate or plasmid) with both values
  <prefix>.json        the verdict per study and metric, tool-ranking agreement, tools with no counterpart, caveats, definitions

This is a comparison for the user's own judgement, not a gate and not a ranking: the two sides use different assemblies, tool versions,
databases and metric definitions, which the output states beside every number (the meta file of each study lists them). Studies are
compared separately and never pooled. A published value with no PlasBench counterpart (tool not run or failed, plasmid not in PlasBench's
truth) is counted as "published only", never scored as zero. Standard library only.
"""
import argparse
import csv
import html
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PUBLISHED_DIR = os.path.join(HERE, "..", "cohorts", "published")
TAB, NL = chr(9), chr(10)
MIN_PAIRS = 5
PAIR_COLUMNS = ["study", "metric", "tool", "published_tool", "sample", "item", "stratum", "published", "plasbench", "difference"]
SUMMARY_COLUMNS = ["study", "metric", "tool", "published_tool", "stratum", "n_pairs", "n_published_only", "published_mean", "plasbench_mean",
                   "mean_difference", "mean_abs_difference", "correlation", "share_within_tolerance", "tolerance", "comparability", "verdict"]


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter=TAB))


def fnum(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def mean(values):
    return sum(values) / len(values) if values else None


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys)) if len(xs) >= 3 else None


def strip_version(accession):
    """An accession without its version and its RefSeq prefix: papers cite GenBank (CP011606.1), a RefSeq assembly's FASTA says NZ_CP011606.1."""
    return re.sub(r"^(NZ_|NC_|AC_)", "", re.sub(r"\.\d+$", "", str(accession).strip()))


def fmt(value, digits=4):
    return "" if value is None else f"{value:.{digits}f}"


def load_studies(published_dir):
    studies = []
    if not os.path.isdir(published_dir):
        return studies
    for name in sorted(os.listdir(published_dir)):
        if not name.endswith(".meta.json"):
            continue
        study = name[:-len(".meta.json")]
        with open(os.path.join(published_dir, name), encoding="utf-8") as handle:
            meta = json.load(handle)
        rows = read_tsv(os.path.join(published_dir, f"{study}.published.tsv")) or []
        studies.append((study, meta, rows))
    return studies


def score_index(scores):
    index = {}
    for row in scores or []:
        key = (row.get("sample"), row.get("tool"))
        if key not in index or row.get("analysis_track") == "short_read":
            index[key] = row
    return index


def per_plasmid_values(results_dir, sample, tool, cache):
    key = (sample, tool)
    if key not in cache:
        rows = read_tsv(os.path.join(results_dir, sample, f"{tool}.per_plasmid.tsv"))
        cache[key] = None if rows is None else {strip_version(r["sequence_id"]): fnum(r.get("completeness")) for r in rows}
    return cache[key]


def compare_study(study, meta, published, results_dir, samples, scores):
    """Pairs and summary rows for one study, restricted to the isolates present in the sample sheet."""
    by_biosample = {}
    for row in samples:
        if row.get("biosample"):
            by_biosample.setdefault(row["biosample"], []).append(row["sample_id"])
    present = [r for r in published if r.get("biosample") in by_biosample]
    result = {"study": study, "isolates_in_cohort": len({r["biosample"] for r in present}), "isolates_published": len({r["biosample"] for r in published if r.get("biosample")}),
              "pairs": [], "summary": [], "published_only_tools": [], "plasbench_only_tools": []}
    if not present:
        return result
    tool_map = meta.get("tool_map", {})
    sidx = score_index(scores)
    cache = {}
    run_tools = {r.get("tool") for r in scores or []}
    result["published_only_tools"] = sorted(t for t in {r["tool"] for r in present} if not tool_map.get(t))
    mapped = {tool_map[t] for t in tool_map if tool_map.get(t)}
    result["plasbench_only_tools"] = sorted(t for t in run_tools if t not in mapped and not t.startswith(("baseline_", "weak_", "mob_like", "platon_like", "spades_like", "gplas_like")))
    for metric in meta.get("metrics", []):
        pm, level = metric["published_metric"], metric.get("level", "per_isolate")
        for prow in present:
            if prow["metric"] != pm:
                continue
            pb_tool = tool_map.get(prow["tool"])
            if not pb_tool:
                continue
            published_value = fnum(prow["value"])
            for sample in by_biosample[prow["biosample"]]:
                if level == "per_plasmid":
                    values = per_plasmid_values(results_dir, sample, pb_tool, cache)
                    own = None if values is None else values.get(strip_version(prow["item"]))
                else:
                    srow = sidx.get((sample, pb_tool))
                    own = fnum(srow.get(metric["plasbench_metric"])) if srow else None
                stratum = prow.get("size_class") or "all"
                result["pairs"].append({"study": study, "metric": pm, "tool": pb_tool, "published_tool": prow["tool"], "sample": sample, "item": prow["item"],
                                        "stratum": stratum, "published": published_value, "plasbench": own,
                                        "difference": None if own is None or published_value is None else own - published_value})
    groups = {}
    for pair in result["pairs"]:
        for stratum in {"all", pair["stratum"]}:
            groups.setdefault((pair["metric"], pair["tool"], pair["published_tool"], stratum), []).append(pair)
    metrics = {m["published_metric"]: m for m in meta.get("metrics", [])}
    for (pm, tool, ptool, stratum), items in sorted(groups.items()):
        both = [p for p in items if p["published"] is not None and p["plasbench"] is not None]
        tol = metrics[pm].get("tolerance", 0.05)
        diffs = [p["plasbench"] - p["published"] for p in both]
        verdict = "too few pairs" if len(both) < MIN_PAIRS else ("consistent" if mean([abs(d) for d in diffs]) <= tol else "differs")
        result["summary"].append({
            "study": study, "metric": pm, "tool": tool, "published_tool": ptool, "stratum": stratum, "n_pairs": len(both),
            "n_published_only": len([p for p in items if p["published"] is not None and p["plasbench"] is None]),
            "published_mean": mean([p["published"] for p in both]), "plasbench_mean": mean([p["plasbench"] for p in both]),
            "mean_difference": mean(diffs), "mean_abs_difference": mean([abs(d) for d in diffs]),
            "correlation": pearson([p["published"] for p in both], [p["plasbench"] for p in both]),
            "share_within_tolerance": (sum(1 for d in diffs if abs(d) <= tol) / len(diffs)) if diffs else None,
            "tolerance": tol, "comparability": metrics[pm].get("comparability", ""), "verdict": verdict})
    return result


def study_verdict(result, meta):
    """One status per study and metric from the 'all' rows, plus the agreement of the tool ordering."""
    out = []
    for metric in meta.get("metrics", []):
        rows = [r for r in result["summary"] if r["metric"] == metric["published_metric"] and r["stratum"] == "all"]
        usable = [r for r in rows if r["n_pairs"] >= MIN_PAIRS]
        entry = {"metric": metric["published_metric"], "label": metric.get("label", metric["published_metric"]), "tools_compared": len(rows),
                 "tools_with_enough_pairs": len(usable), "comparability": metric.get("comparability", ""), "note": metric.get("note", "")}
        if not rows:
            entry.update(status="NOT_RUN", detail="No PlasBench result matches a published row: the mapped tools were not run, or no isolate scored.")
        elif not usable:
            entry.update(status="TOO_FEW", detail=f"Fewer than {MIN_PAIRS} matched pairs for every tool.")
        else:
            agree = sum(1 for r in usable if r["verdict"] == "consistent")
            entry["tools_consistent"] = agree
            entry["mean_abs_difference"] = mean([r["mean_abs_difference"] for r in usable])
            entry["status"] = "CONSISTENT" if agree == len(usable) else ("PARTLY" if agree else "DIFFERENT")
            entry["detail"] = f"{agree} of {len(usable)} tools within the {metric.get('tolerance', 0.05)} tolerance on average."
            if len(usable) >= 3:
                xs = [r["published_mean"] for r in usable]
                ys = [r["plasbench_mean"] for r in usable]
                entry["rank_correlation"] = spearman(xs, ys)
                entry["same_leader"] = usable[xs.index(max(xs))]["tool"] == usable[ys.index(max(ys))]["tool"]
        out.append(entry)
    return out


def write_tsv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row.get(c) is None else (fmt(row[c]) if isinstance(row[c], float) else row[c]) for c in columns])


def svg_scatter(rows, title):
    """Tool means: published (x) against PlasBench (y), with the diagonal. Inline SVG, no script."""
    pts = [(r["published_mean"], r["plasbench_mean"], r["tool"]) for r in rows if r["published_mean"] is not None and r["plasbench_mean"] is not None]
    if not pts:
        return ""
    w, h, m = 360, 300, 44
    lo = min(0.0, min(min(p[0], p[1]) for p in pts))
    hi = max(1.0, max(max(p[0], p[1]) for p in pts)) if max(max(p[0], p[1]) for p in pts) <= 1.0 else max(max(p[0], p[1]) for p in pts)
    sx = lambda v: m + (v - lo) / (hi - lo) * (w - m - 12)  # noqa: E731
    sy = lambda v: h - m - (v - lo) / (hi - lo) * (h - m - 12)  # noqa: E731
    parts = [f"<svg role='img' aria-label='{html.escape(title)}' viewBox='0 0 {w} {h}' width='100%' style='max-width:{w}px'>",
             f"<line x1='{sx(lo)}' y1='{sy(lo)}' x2='{sx(hi)}' y2='{sy(hi)}' stroke='currentColor' stroke-dasharray='4 3' opacity='.45'/>",
             f"<line x1='{m}' y1='{h - m}' x2='{w - 12}' y2='{h - m}' stroke='currentColor' opacity='.6'/><line x1='{m}' y1='{h - m}' x2='{m}' y2='12' stroke='currentColor' opacity='.6'/>",
             f"<text x='{(w + m) / 2}' y='{h - 8}' text-anchor='middle' font-size='11' fill='currentColor'>published</text>",
             f"<text x='12' y='{h / 2}' text-anchor='middle' font-size='11' fill='currentColor' transform='rotate(-90 12 {h / 2})'>PlasBench</text>"]
    for v in (lo, (lo + hi) / 2, hi):
        parts.append(f"<text x='{sx(v)}' y='{h - m + 14}' text-anchor='middle' font-size='10' fill='currentColor'>{v:.2f}</text>")
        parts.append(f"<text x='{m - 5}' y='{sy(v) + 3}' text-anchor='end' font-size='10' fill='currentColor'>{v:.2f}</text>")
    for x, y, tool in pts:
        parts.append(f"<circle cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='5' fill='#2a78c2'><title>{html.escape(tool)}: published {x:.3f}, PlasBench {y:.3f}</title></circle>")
        parts.append(f"<text x='{sx(x) + 7:.1f}' y='{sy(y) + 3:.1f}' font-size='9' fill='currentColor'>{html.escape(tool)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def html_body(report):
    """The comparison as HTML (shared by the stand-alone page and the report section)."""
    esc = html.escape
    if not report["studies"]:
        return ("<p class='muted'>Not run: no isolate of this cohort matches a publication with a published outcome table (cohorts/published/). "
                "Run PlasBench on a publication cohort (for example cohorts/pub-plsmd-filtered.tsv) to compare.</p>")
    out = []
    for st in report["studies"]:
        out.append(f"<h3>{esc(st['citation'])}</h3>")
        out.append(f"<p class='muted'>{st['isolates_in_cohort']} of the publication's {st['isolates_published']} isolates are in this cohort. {esc(st['what_it_is'])}</p>")
        rows = []
        for v in st["verdicts"]:
            extra = ""
            if v.get("rank_correlation") is not None:
                extra = f" Tool order: Spearman {v['rank_correlation']:.2f}, same leader: {'yes' if v.get('same_leader') else 'no'}."
            rows.append(f"<tr><td>{esc(v['label'])}</td><td><b>{esc(v['status'])}</b></td><td>{esc(v.get('detail', ''))}{esc(extra)}</td><td>{esc(v['comparability'])}</td></tr>")
        out.append("<div class='panel'><table class='sortable'><thead><tr><th>Metric</th><th>Result</th><th>Detail</th><th>Comparable</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
        for metric in st["metric_defs"]:
            sub = [r for r in st["summary"] if r["metric"] == metric["published_metric"] and r["stratum"] == "all"]
            if not sub:
                continue
            out.append(f"<h4>{esc(metric.get('label', metric['published_metric']))}</h4>")
            out.append(f"<p class='muted'>{esc(metric.get('note', ''))}</p>")
            body = "".join(
                f"<tr><td>{esc(r['tool'])}</td><td>{esc(r['published_tool'])}</td><td>{r['n_pairs']}</td><td>{r['n_published_only']}</td><td>{fmt(r['published_mean'])}</td>"
                f"<td>{fmt(r['plasbench_mean'])}</td><td>{fmt(r['mean_difference'])}</td><td>{fmt(r['mean_abs_difference'])}</td><td>{fmt(r['correlation'], 2)}</td>"
                f"<td>{fmt(r['share_within_tolerance'], 2)}</td><td>{esc(r['verdict'])}</td></tr>" for r in sub)
            out.append("<div class='panel'><table class='sortable'><thead><tr><th>PlasBench tool</th><th>Published tool</th><th>Pairs</th><th>Published only</th><th>Published mean</th>"
                       "<th>PlasBench mean</th><th>Mean difference</th><th>Mean |difference|</th><th>Correlation</th><th>Within tolerance</th><th>Verdict</th></tr></thead><tbody>" + body + "</tbody></table></div>")
            chart = svg_scatter(sub, f"{metric.get('label', '')}: published against PlasBench, mean per tool")
            if chart:
                out.append("<div class='panel' style='padding:12px'>" + chart + "<p class='muted'>Each point is one tool. On the dashed line PlasBench equals the publication.</p></div>")
            strata = [r for r in st["summary"] if r["metric"] == metric["published_metric"] and r["stratum"] != "all"]
            if strata:
                body = "".join(f"<tr><td>{esc(r['stratum'])}</td><td>{esc(r['tool'])}</td><td>{r['n_pairs']}</td><td>{fmt(r['published_mean'])}</td><td>{fmt(r['plasbench_mean'])}</td><td>{fmt(r['mean_difference'])}</td></tr>" for r in strata)
                out.append("<details><summary>By plasmid size class</summary><div class='panel'><table class='sortable'><thead><tr><th>Size class</th><th>Tool</th><th>Pairs</th><th>Published mean</th><th>PlasBench mean</th><th>Mean difference</th></tr></thead><tbody>" + body + "</tbody></table></div></details>")
        if st["published_only_tools"]:
            out.append(f"<p class='muted'>Published tools with no PlasBench counterpart (shown for context, not compared): {esc(', '.join(st['published_only_tools']))}.</p>")
        out.append("<ul class='muted'>" + "".join(f"<li>{esc(c)}</li>" for c in st["caveats"]) + "</ul>")
    out.append("<p class='muted'>This is a comparison for your own judgement, not a ranking or a pass-fail gate. A gap can come from the assembly, tool or database version, "
               "or the metric definition rather than from either result being wrong. Studies are never pooled.</p>")
    return "".join(out)


def page(report):
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>PlasBench versus published outcomes</title><style>:root{color-scheme:light dark}body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px}"
            "table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #8884;padding:4px 8px;text-align:left}.muted{opacity:.75}.panel{overflow-x:auto;margin:8px 0}</style></head><body>"
            "<h1>PlasBench versus published outcomes</h1>" + html_body(report) + "</body></html>")


def run(results_dir, samples_path, scores_path, out_prefix, published_dir=PUBLISHED_DIR, html_path=None):
    samples = read_tsv(samples_path)
    if samples is None:
        sys.exit(f"ERROR: sample sheet not found: {samples_path}")
    scores = read_tsv(scores_path) or []
    report = {"status": "NO_DATA", "studies": [], "scores_rows": len(scores)}
    all_pairs, all_summary = [], []
    for study, meta, published in load_studies(published_dir):
        result = compare_study(study, meta, published, results_dir, samples, scores)
        if not result["isolates_in_cohort"]:
            continue
        verdicts = study_verdict(result, meta)
        report["studies"].append({"study": study, "citation": meta.get("citation", study), "what_it_is": meta.get("what_it_is", ""), "isolates_in_cohort": result["isolates_in_cohort"],
                                  "isolates_published": result["isolates_published"], "verdicts": verdicts, "summary": result["summary"], "metric_defs": meta.get("metrics", []),
                                  "published_only_tools": result["published_only_tools"], "plasbench_only_tools": result["plasbench_only_tools"], "caveats": meta.get("caveats", []),
                                  "source": meta.get("source", {})})
        all_pairs += result["pairs"]
        all_summary += result["summary"]
    if report["studies"]:
        statuses = [v["status"] for s in report["studies"] for v in s["verdicts"]]
        report["status"] = "NOT_RUN" if all(s == "NOT_RUN" for s in statuses) else ("CONSISTENT" if all(s == "CONSISTENT" for s in statuses if s not in ("NOT_RUN", "TOO_FEW")) and any(s == "CONSISTENT" for s in statuses) else "COMPARED")
    write_tsv(out_prefix + ".tsv", SUMMARY_COLUMNS, all_summary)
    write_tsv(out_prefix + "_pairs.tsv", PAIR_COLUMNS, all_pairs)
    slim = dict(report)
    slim["studies"] = [{k: v for k, v in s.items() if k != "summary"} for s in report["studies"]]
    with open(out_prefix + ".json", "w", encoding="utf-8", newline="") as handle:
        json.dump(slim, handle, indent=2, ensure_ascii=False)
        handle.write(NL)
    if html_path:
        with open(html_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(page(report))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--samples", required=True, help="the cohort sample sheet that was run (needs sample_id and biosample)")
    ap.add_argument("--scores", help="default: <results-dir>/scores.tsv")
    ap.add_argument("--out-prefix", help="default: <results-dir>/benchmark.published_comparison")
    ap.add_argument("--html", help="also write a stand-alone page")
    ap.add_argument("--published-dir", default=PUBLISHED_DIR)
    args = ap.parse_args()
    prefix = args.out_prefix or os.path.join(args.results_dir, "benchmark.published_comparison")
    report = run(args.results_dir, args.samples, args.scores or os.path.join(args.results_dir, "scores.tsv"), prefix, args.published_dir, args.html)
    if not report["studies"]:
        print("No isolate of this sample sheet matches a publication with a published outcome table (matched by BioSample); nothing to compare.")
        return
    for st in report["studies"]:
        print(f"{st['citation']}: {st['isolates_in_cohort']} of {st['isolates_published']} published isolates in this cohort")
        for v in st["verdicts"]:
            print(f"  {v['label']}: {v['status']}  {v.get('detail', '')}")
    print(f"wrote {prefix}.tsv, {prefix}_pairs.tsv, {prefix}.json" + (f" and {args.html}" if args.html else ""))


if __name__ == "__main__":
    main()
