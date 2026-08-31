#!/usr/bin/env python3
"""Build the self-contained HTML dashboard emitted after benchmark aggregation."""

import argparse
import csv
import datetime as dt
import html
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def number(value):
    return float(value) if value not in (None, "") else 0.0


def esc(value):
    return html.escape(str(value), quote=True)


def relative_link(target, report_path):
    relative = os.path.relpath(target, report_path.parent).replace(os.sep, "/")
    return quote(relative, safe="/._-~")


def size_text(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


def file_tree(root, report_path):
    root = Path(root)
    if not root.exists():
        return "<p class='muted'>Not created in this run.</p>", 0, 0

    entries = []
    for path in sorted(root.rglob("*"), key=lambda p: (p.is_file(), str(p).lower())):
        if path.is_file() and path.resolve() != report_path.resolve():
            rel = path.relative_to(root).as_posix()
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            entries.append((rel, path, path.stat().st_size, modified))

    tree = {"dirs": {}, "files": []}
    for rel, path, size, modified in entries:
        node = tree
        parts = rel.split("/")
        for part in parts[:-1]:
            node = node["dirs"].setdefault(part, {"dirs": {}, "files": []})
        node["files"].append((parts[-1], path, size, modified))

    def render(node):
        chunks = ["<ul class='file-tree'>"]
        for name, child in sorted(node["dirs"].items()):
            chunks.append(f"<li><details><summary>{esc(name)}/</summary>{render(child)}</details></li>")
        for name, path, size, modified in node["files"]:
            href = relative_link(path, report_path)
            chunks.append(
                "<li class='file'><a href='{}' download>{}</a>"
                "<span>{} · {}</span></li>".format(href, esc(name), size_text(size), esc(modified))
            )
        chunks.append("</ul>")
        return "".join(chunks)

    return render(tree), len(entries), sum(entry[2] for entry in entries)


def score_band(value):
    """Return a display class; thresholds are visual aids, not pass/fail calls."""
    if value >= 0.90:
        return "high"
    if value >= 0.70:
        return "medium"
    return "low"


def interpretation(leaderboard, status_counts):
    """Only report directly observed comparisons from the report input tables."""
    notes = []
    if not leaderboard:
        return ["No tool has a score row yet, so performance cannot be interpreted."], "neutral"

    winner = leaderboard[0]
    winner_f1 = number(winner["mean_f1"])
    if len(leaderboard) == 1:
        notes.append(f"{winner['tool']} is the only scored tool (mean F1 {winner_f1:.3f}); no between-tool comparison is available.")
    else:
        runner = leaderboard[1]
        gap = winner_f1 - number(runner["mean_f1"])
        if gap >= 0.05:
            notes.append(f"{winner['tool']} leads {runner['tool']} by {gap:.3f} mean F1 ({winner_f1:.3f} versus {number(runner['mean_f1']):.3f}).")
        else:
            notes.append(f"The top two tools are close: {winner['tool']} leads {runner['tool']} by {gap:.3f} mean F1. This run alone does not establish a clear winner.")

    for row in leaderboard:
        precision, recall = number(row["mean_precision"]), number(row["mean_recall"])
        delta = precision - recall
        if delta >= 0.15:
            notes.append(f"{row['tool']} is more precise than complete (precision {precision:.3f}, recall {recall:.3f}); missed plasmid sequence is the larger limitation.")
        elif delta <= -0.15:
            notes.append(f"{row['tool']} recovers more plasmid sequence than it classifies cleanly (recall {recall:.3f}, precision {precision:.3f}); chromosomal contamination is the larger limitation.")

    issues = status_counts["failed"] + status_counts["skipped"]
    if issues:
        notes.append(f"{issues} tool-sample execution(s) were not scored ({status_counts['failed']} failed, {status_counts['skipped']} skipped); compare completed and scored counts before relying on rank order.")
        tone = "caution"
    else:
        notes.append("All recorded tool-sample executions completed or were reused; the coverage columns still show the number of scored samples per tool.")
        tone = "positive"
    return notes, tone


def performance_chart(leaderboard):
    if not leaderboard:
        return "<p class='muted'>No scored tools yet.</p>"
    row_height = 42
    width, label_width, chart_width = 760, 145, 520
    height = 42 + len(leaderboard) * row_height
    colors = [("Precision", "#2c7a62"), ("Recall", "#d18b2a"), ("F1", "#174b3a")]
    parts = [f"<svg class='performance-chart' viewBox='0 0 {width} {height}' role='img' aria-label='Mean precision, recall, and F1 by tool'>"]
    parts.append("<text x='145' y='16' class='axis'>0</text><text x='638' y='16' class='axis'>1.0</text>")
    for index, row in enumerate(leaderboard):
        y = 30 + index * row_height
        parts.append(f"<text x='0' y='{y + 14}' class='label'>{esc(row['tool'])}</text>")
        for metric_index, (label, color) in enumerate(colors):
            value = number(row[f"mean_{label.lower()}"])
            bar_y = y + metric_index * 9
            parts.append(f"<rect x='{label_width}' y='{bar_y}' width='{chart_width}' height='6' fill='#e0e8e1'/>")
            parts.append(f"<rect x='{label_width}' y='{bar_y}' width='{chart_width * value:.1f}' height='6' fill='{color}'><title>{esc(row['tool'])} {label}: {value:.3f}</title></rect>")
    legend = "".join(f"<span><i style='background:{color}'></i>{label}</span>" for label, color in colors)
    return "<div class='chart-legend'>" + legend + "</div>" + "".join(parts) + "</svg>"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--tool-status", required=True)
    ap.add_argument("--leaderboard", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    project = Path(args.project_root).resolve()
    out = Path(args.out).resolve()
    scores = read_tsv(args.scores)
    status = read_tsv(args.tool_status) if Path(args.tool_status).is_file() else []
    leaderboard = read_tsv(args.leaderboard)
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    tools = sorted({row["tool"] for row in scores} | {row["tool"] for row in status})
    samples = sorted({row["sample"] for row in scores} | {row["sample"] for row in status})
    status_counts = Counter(row["status"] for row in status)
    best = leaderboard[0] if leaderboard else None
    score_by_sample = defaultdict(list)
    score_by_tool = defaultdict(list)
    for row in scores:
        score_by_sample[row["sample"]].append(row)
        score_by_tool[row["tool"]].append(row)

    leaderboard_rows = "".join(
        "<tr><td>{rank}</td><td>{tool}</td><td>{scored}</td><td>{completed}</td>"
        "<td>{failed}</td><td>{skipped}</td><td>{precision}</td><td>{recall}</td>"
        "<td><strong class='score {band}'>{f1}</strong><span class='f1-bar {band}'><i style='width:{f1_width}%'></i></span></td></tr>".format(
            rank=esc(row.get("rank", "-")), tool=esc(row["tool"]),
            scored=esc(row.get("n_samples", "0")), completed=esc(row.get("n_completed", "0")),
            failed=esc(row.get("n_failed", "0")), skipped=esc(row.get("n_skipped", "0")),
            precision=esc(row["mean_precision"]), recall=esc(row["mean_recall"]), f1=esc(row["mean_f1"]),
            f1_width=max(0, min(100, round(number(row["mean_f1"]) * 100))),
            band=score_band(number(row["mean_f1"])),
        ) for row in leaderboard
    ) or "<tr><td colspan='9'>No scored tools yet.</td></tr>"

    score_rows = "".join(
        "<tr data-sample='{sample}' data-tool='{tool}' data-band='{band}'><td>{sample}</td><td>{tool}</td>"
        "<td>{truth:,}</td><td>{tp:,}</td><td>{fp:,}</td><td>{fn:,}</td><td>{unmapped:,}</td>"
        "<td>{precision}</td><td>{recall}</td><td><strong class='score {band}'>{f1}</strong></td></tr>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]),
            truth=int(number(row["true_plasmid_bp"])), tp=int(number(row["TP_bp"])),
            fp=int(number(row["FP_bp"])), fn=int(number(row["FN_bp"])),
            unmapped=int(number(row["unmapped_pred_bp"])), precision=esc(row["precision"]),
            recall=esc(row["recall"]), f1=esc(row["f1"]),
            band=score_band(number(row["f1"])),
        ) for row in scores
    ) or "<tr><td colspan='10'>No score rows were produced.</td></tr>"

    status_rows = "".join(
        "<tr data-status='{state}'><td>{sample}</td><td>{tool}</td><td><span class='status {state}'>{state}</span></td>"
        "<td>{reason}</td></tr>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]), state=esc(row["status"]),
            reason=esc(row.get("reason") or "-"),
        ) for row in status
    ) or "<tr><td colspan='4'>Stage 4 status was not available.</td></tr>"

    sample_sections = []
    for sample in samples:
        rows = score_by_sample.get(sample, [])
        body = "".join(
            "<tr><td>{tool}</td><td>{p}</td><td>{r}</td><td><strong>{f1}</strong></td><td>{fp:,}</td><td>{unmapped:,}</td></tr>".format(
                tool=esc(row["tool"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                fp=int(number(row["FP_bp"])), unmapped=int(number(row["unmapped_pred_bp"])),
            ) for row in rows
        ) or "<tr><td colspan='6'>No completed tool was scored for this sample.</td></tr>"
        sample_sections.append(
            "<details class='sample'><summary><strong>{}</strong><span>{} scored tool(s)</span></summary>"
            "<table><thead><tr><th>Tool</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th>"
            "</tr></thead><tbody>{}</tbody></table></details>".format(esc(sample), len(rows), body)
        )

    tool_sections = []
    for tool in tools:
        rows = score_by_tool.get(tool, [])
        if rows:
            mean_f1 = sum(number(row["f1"]) for row in rows) / len(rows)
            range_text = f"{min(number(row['f1']) for row in rows):.3f}–{max(number(row['f1']) for row in rows):.3f}"
            body = "".join(
                "<tr><td>{sample}</td><td>{p}</td><td>{r}</td><td><strong class='score {band}'>{f1}</strong></td>"
                "<td>{fp:,}</td><td>{unmapped:,}</td></tr>".format(
                    sample=esc(row["sample"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                    band=score_band(number(row["f1"])), fp=int(number(row["FP_bp"])),
                    unmapped=int(number(row["unmapped_pred_bp"])),
                ) for row in sorted(rows, key=lambda item: number(item["f1"]), reverse=True)
            )
            summary = f"{len(rows)} scored sample(s) · mean F1 {mean_f1:.3f} · F1 range {range_text}"
        else:
            body = "<tr><td colspan='6'>No completed sample was scored for this tool; consult execution health.</td></tr>"
            summary = "No score rows"
        tool_sections.append(
            "<details class='sample tool-detail'><summary><strong>{}</strong><span>{}</span></summary>"
            "<table class='sortable'><thead><tr><th>Sample</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th>"
            "</tr></thead><tbody>{}</tbody></table></details>".format(esc(tool), esc(summary), body)
        )

    roots = [("Results", out.parent), ("Logs", project / "logs"), ("Data", project / "data")]
    explorers = []
    artifact_count = 0
    artifact_bytes = 0
    for label, root in roots:
        tree, count, bytes_total = file_tree(root, out)
        artifact_count += count
        artifact_bytes += bytes_total
        explorers.append(f"<details class='explorer' open><summary><strong>{label}</strong><span>{count} downloadable file(s)</span></summary>{tree}</details>")

    best_value = esc(best["tool"]) if best else "No scored tool"
    best_f1 = esc(best["mean_f1"]) if best else "-"
    insight_notes, insight_tone = interpretation(leaderboard, status_counts)
    insight_html = "".join(f"<li>{esc(note)}</li>" for note in insight_notes)
    chart_html = performance_chart(leaderboard)
    page = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>SPREAD plasmid benchmark report</title>
<style>
:root{{--ink:#17231d;--muted:#627067;--line:#d9e1da;--paper:#f6f8f4;--card:#fff;--green:#0c6b4f;--lime:#dcefdc;--amber:#9a5b00;--red:#a53028;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}} header{{background:#183a2d;color:#fff;padding:48px max(24px,calc((100vw - 1320px)/2));border-bottom:6px solid #a8d29b}} h1,h2,h3,th,.nav,button,select,input,.metric,.status{{font-family:Arial,sans-serif}} h1{{font-size:clamp(28px,5vw,48px);margin:0 0 8px;letter-spacing:-.04em}} header p{{margin:0;color:#d9e7de}} main{{max-width:1320px;margin:auto;padding:28px 24px 64px}} .nav{{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 28px}} .nav a{{color:var(--green);border:1px solid var(--line);background:#fff;padding:7px 10px;text-decoration:none;font-size:12px;font-weight:bold}} .metrics{{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:12px;margin-bottom:28px}} .metric{{background:var(--card);border-top:4px solid var(--green);padding:15px;box-shadow:0 1px 3px #15241c12}} .metric small{{color:var(--muted);display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em}} .metric strong{{font-size:27px;display:block;margin-top:4px}} section{{margin:38px 0}} h2{{font-size:21px;margin:0 0 5px}} .lead,.muted{{color:var(--muted)}} .panel{{background:var(--card);border:1px solid var(--line);overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:760px;font-family:Arial,sans-serif;font-size:13px}} th{{background:#edf2ec;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .sortable th{{cursor:pointer}} .sortable th:hover{{background:#dcebdc}} td{{border-top:1px solid var(--line);padding:9px 10px;white-space:nowrap}} tr:hover td{{background:#f5faf4}} .f1-bar{{display:block;width:100%;height:5px;background:#deeadf;margin-top:4px;min-width:64px}} .f1-bar i{{display:block;height:100%;background:var(--green)}} .f1-bar.medium i{{background:#c68221}} .f1-bar.low i{{background:#bd4b42}} .score.high{{color:#087250}} .score.medium{{color:#9a5b00}} .score.low{{color:#a53028}} .insight{{border-left:6px solid var(--green);background:#e7f1e7;padding:16px 20px}} .insight.caution{{border-color:var(--amber);background:#fbf2df}} .insight ul{{margin:6px 0 0;padding-left:20px}} .chart-card{{background:#fff;border:1px solid var(--line);padding:18px;overflow:auto}} .performance-chart{{display:block;min-width:650px;width:100%;height:auto}} .performance-chart .axis,.performance-chart .label{{font:12px Arial,sans-serif;fill:#536158}} .chart-legend,.legend{{display:flex;gap:16px;flex-wrap:wrap;font:12px Arial,sans-serif;margin:10px 0}} .chart-legend i,.legend i{{display:inline-block;width:10px;height:10px;margin-right:5px}} .metadata{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);font-family:Arial,sans-serif;font-size:13px}} .metadata div{{background:#fff;padding:12px}} .metadata small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.06em}} .controls{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}} select,input{{padding:7px;border:1px solid var(--line);background:#fff}} .count{{font:12px Arial,sans-serif;color:var(--muted);align-self:center}} .status{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold}} .completed,.reused{{background:#dcefdc;color:#07573e}} .failed{{background:#f7ddda;color:var(--red)}} .skipped{{background:#f6ead1;color:var(--amber)}} details.sample,.explorer{{background:var(--card);border:1px solid var(--line);margin:10px 0;padding:0 14px}} details summary{{cursor:pointer;padding:13px 0;font-family:Arial,sans-serif}} details summary span{{float:right;color:var(--muted);font-size:12px}} .file-tree{{list-style:none;padding-left:18px;margin:0 0 15px;font-family:Arial,sans-serif;font-size:13px}} .file-tree li{{padding:3px 0}} .file-tree details summary{{padding:3px 0}} .file-tree a{{color:var(--green);text-decoration:none;font-weight:600}} .file-tree .file span{{color:var(--muted);font-size:11px;margin-left:8px}} .method{{columns:2;column-gap:32px;background:#ebf2ea;padding:18px 22px}} .method p{{margin-top:0;break-inside:avoid}} footer{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}} @media(max-width:700px){{main{{padding:20px 14px}}header{{padding:32px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metadata{{grid-template-columns:1fr}}.method{{columns:1}}}}
</style></head><body>
<header><h1>SPREAD plasmid reconstruction benchmark</h1><p>Detailed run report · generated {esc(generated)} · offline HTML with direct artifact downloads</p></header>
<main><nav><a href='#insights'>Interpretation</a><a href='#chart'>Metric chart</a><a href='#leaderboard'>Leaderboard</a><a href='#scores'>All scores</a><a href='#health'>Run health</a><a href='#tools'>Tool drill-down</a><a href='#samples'>Sample drill-down</a><a href='#keys'>Keys and legend</a><a href='#files'>File explorer</a><a href='#method'>Method</a></nav>
<div class='metrics'><div class='metric'><small>Samples observed</small><strong>{len(samples)}</strong></div><div class='metric'><small>Tools observed</small><strong>{len(tools)}</strong></div><div class='metric'><small>Best mean F1</small><strong>{best_f1}</strong><small>{best_value}</small></div><div class='metric'><small>Execution issues</small><strong>{status_counts['failed'] + status_counts['skipped']}</strong><small>{status_counts['failed']} failed · {status_counts['skipped']} skipped</small></div></div>
<section id='metadata'><h2>Run and output metadata</h2><div class='metadata'><div><small>Report generated</small>{esc(generated)}</div><div><small>Score observations</small>{len(scores)} sample-tool row(s)</div><div><small>Tracked artifacts</small>{artifact_count} file(s) · {esc(size_text(artifact_bytes))}</div><div><small>Execution states</small>{status_counts['completed']} completed · {status_counts['reused']} reused · {status_counts['failed']} failed · {status_counts['skipped']} skipped</div><div><small>Scoring inputs</small>scores.tsv, tool_status.tsv, benchmark.leaderboard.tsv</div><div><small>Reference scope</small>Complete assembly reference bases; plasmid is the positive class</div></div></section>
<section id='insights'><h2>Automated interpretation</h2><div class='insight {insight_tone}'><p class='lead'>Generated from the score and execution-status tables. These are descriptive comparisons, not statistical significance tests.</p><ul>{insight_html}</ul></div></section>
<section id='chart'><h2>Performance profile</h2><p class='lead'>Mean precision, recall, and F1 by tool. Green is precision, amber is recall, and dark green is F1; bar length spans 0 to 1.</p><div class='chart-card'>{chart_html}</div></section>
<section id='leaderboard'><h2>Benchmark leaderboard</h2><p class='lead'>Ranked by mean base-level F1. Coverage counts disclose how many samples each tool actually completed, so partial execution cannot be mistaken for comparable evidence. Select a column heading to sort.</p><div class='panel'><table class='sortable'><thead><tr><th>Rank</th><th>Tool</th><th>Scored</th><th>Completed</th><th>Failed</th><th>Skipped</th><th>Mean precision</th><th>Mean recall</th><th>Mean F1</th></tr></thead><tbody>{leaderboard_rows}</tbody></table></div></section>
<section id='scores'><h2>All sample-tool scores</h2><p class='lead'>TP/FP/FN are reference base pairs. Unmapped predicted bp signals predicted sequence that did not align to the complete reference and is reported separately from chromosomal contamination.</p><div class='controls'><label>Sample <select id='sample-filter'><option value=''>All samples</option>{''.join(f"<option>{esc(s)}</option>" for s in samples)}</select></label><label>Tool <select id='tool-filter'><option value=''>All tools</option>{''.join(f"<option>{esc(t)}</option>" for t in tools)}</select></label><label>F1 band <select id='band-filter'><option value=''>All bands</option><option value='high'>High (≥0.90)</option><option value='medium'>Medium (0.70–0.89)</option><option value='low'>Low (&lt;0.70)</option></select></label><span id='score-count' class='count'></span></div><div class='panel'><table id='score-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>True plasmid bp</th><th>TP bp</th><th>FP bp</th><th>FN bp</th><th>Unmapped predicted bp</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{score_rows}</tbody></table></div></section>
<section id='health'><h2>Execution health</h2><p class='lead'>A failed or unavailable tool is excluded from F1 aggregation. “Completed” can include a valid empty prediction; that is scored honestly as no recovered plasmid bases.</p><div class='controls'><label>Status <select id='status-filter'><option value=''>All states</option><option value='completed'>Completed</option><option value='reused'>Reused</option><option value='failed'>Failed</option><option value='skipped'>Skipped</option></select></label><span id='status-count' class='count'></span></div><div class='panel'><table id='status-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Status</th><th>Reason / log location</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
<section id='tools'><h2>Tool drill-down</h2><p class='lead'>Open a tool to inspect its score distribution across samples. Rows are initially ordered by F1.</p>{''.join(tool_sections) or "<p class='muted'>No tools were found.</p>"}</section>
<section id='samples'><h2>Sample drill-down</h2><p class='lead'>Open a sample to compare every completed tool side-by-side.</p>{''.join(sample_sections) or "<p class='muted'>No samples were found.</p>"}</section>
<section id='keys'><h2>Keys, legend, and metric definitions</h2><div class='legend'><span><i style='background:#087250'></i>High F1: ≥0.90</span><span><i style='background:#c68221'></i>Medium F1: 0.70–0.89</span><span><i style='background:#bd4b42'></i>Low F1: &lt;0.70</span><span><i style='background:#2c7a62'></i>Precision chart bar</span><span><i style='background:#d18b2a'></i>Recall chart bar</span></div><div class='method'><p><strong>TP (true positive) bp:</strong> plasmid-reference bases covered by a predicted-plasmid alignment.</p><p><strong>FP (false positive) bp:</strong> chromosome-reference bases covered by a predicted-plasmid alignment; this is chromosomal contamination.</p><p><strong>FN (false negative) bp:</strong> true plasmid-reference bases not covered by a predicted-plasmid alignment.</p><p><strong>Precision:</strong> TP / (TP + FP). Higher means less chromosome sequence among the claimed plasmid sequence.</p><p><strong>Recall / completeness:</strong> TP / (TP + FN). Higher means more of the true plasmid sequence was recovered.</p><p><strong>F1:</strong> harmonic mean of precision and recall, from 0 (worst) to 1 (best). The color bands are visual aids, not acceptance thresholds.</p><p><strong>Unmapped predicted bp:</strong> predicted-plasmid bases with no alignment to any labelled reference sequence. They are reported separately, not added to FP.</p><p><strong>Scored / completed / failed / skipped:</strong> scored is the number contributing to the metric; completed and reused are valid tool results; failed and skipped are exposed for coverage transparency.</p></div></section>
<section id='files'><h2>Artifact explorer</h2><p class='lead'>All files created or consumed by this project are listed below. Select a filename to open or download it; directory branches can be expanded independently.</p>{''.join(explorers)}</section>
<section id='method'><h2>Scoring method and interpretation</h2><div class='method'><p><strong>Truth:</strong> sequences in each complete reference assembly are labelled plasmid or chromosome from the NCBI sequence report.</p><p><strong>Prediction:</strong> each tool’s standardized predicted-plasmid FASTA is aligned to the reference using minimap2.</p><p><strong>Metrics:</strong> covered plasmid reference bases are TP; covered chromosome reference bases are FP; uncovered plasmid bases are FN. Precision measures contamination control; recall measures plasmid completeness; F1 balances both.</p><p><strong>Run integrity:</strong> failed tool execution, failed adaptation, and mapping failure do not become zero-score observations. They appear in execution health and reduce the completed/scored counts shown in the leaderboard.</p></div></section>
<footer>Inputs: <a href='scores.tsv'>scores.tsv</a>, <a href='tool_status.tsv'>tool_status.tsv</a>, <a href='benchmark.leaderboard.tsv'>benchmark.leaderboard.tsv</a>. Report location: {esc(out.name)}.</footer></main>
<script>
const sf=document.getElementById('sample-filter'),tf=document.getElementById('tool-filter'),bf=document.getElementById('band-filter');
function filterScores(){{let visible=0;document.querySelectorAll('#score-table tbody tr').forEach(r=>{{const hide=(sf.value&&r.dataset.sample!==sf.value)||(tf.value&&r.dataset.tool!==tf.value)||(bf.value&&r.dataset.band!==bf.value);r.hidden=hide;if(!hide)visible++;}});document.getElementById('score-count').textContent=visible+' visible score row(s)';}}
[sf,tf,bf].forEach(el=>el.onchange=filterScores);filterScores();
const statusFilter=document.getElementById('status-filter');function filterStatus(){{let visible=0;document.querySelectorAll('#status-table tbody tr').forEach(r=>{{const hide=statusFilter.value&&r.dataset.status!==statusFilter.value;r.hidden=hide;if(!hide)visible++;}});document.getElementById('status-count').textContent=visible+' visible execution row(s)';}}statusFilter.onchange=filterStatus;filterStatus();
document.querySelectorAll('table.sortable th').forEach((head,index)=>head.addEventListener('click',()=>{{const table=head.closest('table'),body=table.tBodies[0],rows=Array.from(body.rows),ascending=head.dataset.order!=='asc';rows.sort((a,b)=>{{const av=a.cells[index]?.innerText.trim()||'',bv=b.cells[index]?.innerText.trim()||'',an=Number(av.replace(/[^0-9.-]/g,'')),bn=Number(bv.replace(/[^0-9.-]/g,''));const result=Number.isNaN(an)||Number.isNaN(bn)?av.localeCompare(bv):an-bn;return ascending?result:-result;}});rows.forEach(row=>body.appendChild(row));table.querySelectorAll('th').forEach(h=>delete h.dataset.order);head.dataset.order=ascending?'asc':'desc';}}));
</script>
</body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote HTML report: {out}")


if __name__ == "__main__":
    main()
