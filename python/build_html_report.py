#!/usr/bin/env python3
"""Build the self-contained HTML dashboard emitted after benchmark aggregation."""

import argparse
import csv
import datetime as dt
import html
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_sample_metadata(path):
    if not path or not Path(path).is_file():
        return {}
    return {row["sample_id"]: row for row in read_tsv(path) if row.get("sample_id")}


def read_tool_versions(path):
    """Map report tool labels to versions recorded at the time of the run."""
    if not path or not Path(path).is_file():
        return {}
    try:
        tools = json.loads(Path(path).read_text(encoding="utf-8")).get("tools", {})
    except (json.JSONDecodeError, OSError):
        return {}
    executable = {
        "mob_recon": "mob_recon", "platon": "platon",
        "plasmidspades": "plasmidspades.py", "gplas": "gplas",
        "gplas2_external": "gplas", "gplas2_mob": "gplas",
    }
    return {label: details.get("version", "unreported")
            for label, name in executable.items()
            if (details := tools.get(name, {})).get("available")}


def number(value):
    return float(value) if value not in (None, "") else 0.0


def esc(value):
    return html.escape(str(value), quote=True)


def relative_link(target, report_path):
    try:
        relative = os.path.relpath(target, report_path.parent).replace(os.sep, "/")
    except ValueError:
        # Windows cannot compute a relative path across drive letters. A file
        # URI preserves the report's direct-download explorer in that case.
        return Path(target).resolve().as_uri()
    return quote(relative, safe="/._-~")


def size_text(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


def file_tree(root, report_path, excluded_paths=()):
    root = Path(root)
    if not root.exists():
        return "<p class='muted'>Not created in this run.</p>", 0, 0

    excluded = {Path(path).resolve() for path in excluded_paths if path}

    entries = []
    for path in sorted(root.rglob("*"), key=lambda p: (p.is_file(), str(p).lower())):
        if path.is_file() and path.resolve() != report_path.resolve() and path.resolve() not in excluded:
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


def size_band(bp):
    if bp < 10_000:
        return "small"
    if bp < 100_000:
        return "medium"
    return "large"


def score_row(row, metadata, tool_versions):
    sample_metadata = metadata.get(row["sample"], {})
    depth = sample_metadata.get("read_depth_x", "")
    try:
        depth_value = float(depth) if depth else None
    except ValueError:
        depth_value = None
    truth_bp = int(number(row["true_plasmid_bp"]))
    version = tool_versions.get(row["tool"], "not recorded")
    band = score_band(number(row["f1"]))
    return (
        "<tr data-sample='{sample}' data-tool='{tool}' data-band='{band}' "
        "data-organism='{organism}' data-tech='{tech}' data-tier='{tier}' "
        "data-origin='{origin}' data-size='{size}' data-depth='{depth}' data-version='{version}' data-track='{track}'>"
        "<td>{sample}</td><td>{tool}</td><td>{version}</td><td>{origin}</td><td>{depth_text}</td>"
        "<td>{truth:,}</td><td>{tp:,}</td><td>{fp:,}</td><td>{fn:,}</td><td>{unambiguous:,}</td><td>{ambiguous:,}</td><td>{unmapped:,}</td>"
        "<td>{precision}</td><td>{recall}</td><td>{amr}</td><td>{circular}</td>"
        "<td><strong class='score {band}'>{f1}</strong></td></tr>"
    ).format(
        sample=esc(row["sample"]), tool=esc(row["tool"]), version=esc(version),
        organism=esc(sample_metadata.get("organism", "")), tech=esc(sample_metadata.get("truth_technology", "")),
        tier=esc(sample_metadata.get("truth_quality_tier", "")), origin=esc(sample_metadata.get("sample_origin", "")),
        track=esc(row.get("analysis_track") or "short_read"),
        size=size_band(truth_bp), depth="" if depth_value is None else depth_value,
        depth_text=esc(depth) if depth_value is not None else "-", truth=truth_bp,
        tp=int(number(row["TP_bp"])), fp=int(number(row["FP_bp"])), fn=int(number(row["FN_bp"])),
        unmapped=int(number(row["unmapped_pred_bp"])), unambiguous=int(number(row.get("unambiguously_mapped_pred_bp"))),
        ambiguous=int(number(row.get("ambiguously_mapped_pred_bp"))), precision=esc(row["precision"]),
        recall=esc(row["recall"]), amr=esc(row.get("amr_gene_recall") or "-"),
        circular=esc(row.get("circular_plasmid_recall") or "-"), f1=esc(row["f1"]), band=band,
    )


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


def selection_card(sample, results_dir, report_path):
    """Render a plain-language view of a machine-readable selection report."""
    directory = results_dir / sample / "selected_candidate"
    report_file = directory / "selection_report.json"
    if not report_file.is_file():
        return "<p class='muted'>No selected reconstruction was created for this sample.</p>"
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "<p class='muted'>The selected-reconstruction record could not be read; download the JSON file for inspection.</p>"
    selected_tool = report.get("selected_tool") or "No method selected"
    truth_set = report.get("selection_type") == "truth_set_best_candidate"
    confidence = report.get("confidence_tier", "requires_confirmation")
    confirmation = report.get("long_read_confirmation_reasons") or []
    status = "Benchmark-validated candidate" if truth_set else "Candidate only: operational method recommendation"
    confidence_label = "Ready for routine research review" if confidence == "high" else "Long-read confirmation required"
    metrics = report.get("candidate_metrics") or {}
    score_text = "No complete-reference score is available for this sample."
    if metrics:
        score_text = "Reference comparison: F1 {f1}, plasmid recovery {plasmid}, precision {precision}.".format(
            f1=esc(metrics.get("f1", "-")), plasmid=esc(metrics.get("plasmid_recall", "-")),
            precision=esc(metrics.get("precision", "-")))
    fasta = directory / "candidate.plasmid.fasta"
    fasta_link = (f"<a class='download-button' href='{relative_link(fasta, report_path)}' download>Download selected plasmid FASTA</a>"
                  if fasta.is_file() else "<span class='muted'>No standardized candidate FASTA was available.</span>")
    report_link = f"<a href='{relative_link(report_file, report_path)}' download>Download technical JSON record</a>"
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in confirmation) or "<li>No automated confirmation trigger was recorded.</li>"
    rejected = report.get("rejected_candidates") or []
    alternatives = ", ".join(esc(item.get("tool", "unnamed method")) for item in rejected) or "No alternative scored candidate was recorded."
    agreement = report.get("cross_tool_agreement") or {}
    agreement_text = agreement.get("reason") or (
        f"{agreement.get('status', 'not assessed')} agreement (mean reference-footprint overlap "
        f"{agreement.get('mean_reference_footprint_jaccard', '-')}).")
    structural = report.get("structural_evidence") or {}
    structural_text = (f"{len(structural.get('items', []))} source-reported structural evidence item(s) available."
                       if structural.get("status") == "reported_by_source" else "No source-reported replicon, MOB, or closure evidence was supplied.")
    return """<div class='selection-card {tone}'>
<div><span class='selection-label'>{status}</span><h3>{sample}: {tool}</h3><p>{score}</p><p><strong>Confidence:</strong> {confidence}</p></div>
<div class='selection-actions'>{fasta}<br>{report}</div>
<details><summary>Why this selection needs review</summary><ul>{reasons}</ul><p><strong>Agreement between methods:</strong> {agreement}</p><p><strong>Structural evidence:</strong> {structural}</p><p><strong>Other evaluated methods:</strong> {alternatives}</p><p class='muted'>This card does not claim that the sequence is closed, circular, or clinically validated.</p></details>
</div>""".format(
        tone="confirmation" if confidence != "high" else "confident", status=esc(status), sample=esc(sample),
        tool=esc(selected_tool), score=score_text, confidence=esc(confidence_label), fasta=fasta_link,
        report=report_link, reasons=reasons, alternatives=alternatives, agreement=esc(agreement_text), structural=esc(structural_text))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--tool-status", required=True)
    ap.add_argument("--leaderboard", required=True)
    ap.add_argument("--sample-sheet", help="Optional curated sample-sheet TSV for cohort filters.")
    ap.add_argument("--manifest", help="Optional run manifest used to show/filter tool versions.")
    ap.add_argument("--comparisons", help="Optional paired-comparison TSV from aggregation.")
    ap.add_argument("--score-failures", help="Optional score failure TSV from stage 5.")
    ap.add_argument("--recommendations", help="Optional coverage-gated operational recommendation TSV.")
    ap.add_argument("--recommendation-validation", help="Optional leave-one-study-out recommendation validation TSV.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    project = Path(args.project_root).resolve()
    out = Path(args.out).resolve()
    scores = read_tsv(args.scores)
    status = read_tsv(args.tool_status) if Path(args.tool_status).is_file() else []
    leaderboard = read_tsv(args.leaderboard)
    metadata = read_sample_metadata(args.sample_sheet)
    tool_versions = read_tool_versions(args.manifest)
    comparisons = read_tsv(args.comparisons) if args.comparisons and Path(args.comparisons).is_file() else []
    score_failures = read_tsv(args.score_failures) if args.score_failures and Path(args.score_failures).is_file() else []
    recommendations = read_tsv(args.recommendations) if args.recommendations and Path(args.recommendations).is_file() else []
    recommendation_validation = read_tsv(args.recommendation_validation) if args.recommendation_validation and Path(args.recommendation_validation).is_file() else []
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    tools = sorted({row["tool"] for row in scores} | {row["tool"] for row in status})
    samples = sorted({row["sample"] for row in scores} | {row["sample"] for row in status})
    organisms = sorted({row.get("organism") or "" for row in metadata.values()} - {""})
    technologies = sorted({row.get("truth_technology") or "" for row in metadata.values()} - {""})
    tiers = sorted({row.get("truth_quality_tier") or "" for row in metadata.values()} - {""})
    origins = sorted({row.get("sample_origin") or "" for row in metadata.values()} - {""})
    versions = sorted(set(tool_versions.values()))
    tracks = sorted({row.get("analysis_track") or "short_read" for row in scores})
    status_counts = Counter(row["status"] for row in status)
    best = leaderboard[0] if leaderboard else None
    score_by_sample = defaultdict(list)
    score_by_tool = defaultdict(list)
    for row in scores:
        score_by_sample[row["sample"]].append(row)
        score_by_tool[row["tool"]].append(row)

    leaderboard_rows = "".join(
        "<tr><td>{rank}</td><td>{tool}</td><td>{scored}</td><td>{completed}</td>"
        "<td>{failed}</td><td>{skipped}</td><td>{precision}</td><td>{recall}</td><td>{plasmid_recall}</td><td>{bin_f1}</td>"
        "<td><strong class='score {band}'>{f1}</strong><span class='f1-bar {band}'><i style='width:{f1_width}%'></i></span></td></tr>".format(
            rank=esc(row.get("rank", "-")), tool=esc(row["tool"]),
            scored=esc(row.get("n_samples", "0")), completed=esc(row.get("n_completed", "0")),
            failed=esc(row.get("n_failed", "0")), skipped=esc(row.get("n_skipped", "0")),
            precision=esc(row["mean_precision"]), recall=esc(row["mean_recall"]),
            plasmid_recall=esc(row.get("mean_plasmid_recall") or "not annotated"),
            bin_f1=esc(row.get("mean_bin_f1") or "not bin-scored"), f1=esc(row["mean_f1"]),
            f1_width=max(0, min(100, round(number(row["mean_f1"]) * 100))),
            band=score_band(number(row["mean_f1"])),
        ) for row in leaderboard
    ) or "<tr><td colspan='11'>No scored tools yet.</td></tr>"

    score_rows = "".join(score_row(row, metadata, tool_versions) for row in scores)
    score_rows = score_rows or "<tr><td colspan='13'>No score rows were produced.</td></tr>"

    bin_rows = []
    for row in scores:
        if not row.get("bin_f1"):
            continue
        sample, tool = row["sample"], row["tool"]
        matches = out.parent / sample / f"{tool}.bin_matches.tsv"
        detail = "-"
        if matches.is_file():
            detail = f"<a href='{relative_link(matches, out)}' download>Download matches TSV</a>"
        bin_rows.append(
            "<tr><td>{sample}</td><td>{tool}</td><td>{precision}</td><td>{recall}</td><td><strong class='score {band}'>{f1}</strong></td>"
            "<td>{matched}</td><td>{unmatched}</td><td>{missed}</td><td>{splits}</td><td>{merges}</td><td>{contaminated}</td><td>{repeat}</td><td>{contamination}</td><td>{detail}</td></tr>".format(
                sample=esc(sample), tool=esc(tool), precision=esc(row.get("bin_precision") or "-"),
                recall=esc(row.get("bin_recall") or "-"), f1=esc(row.get("bin_f1") or "-"),
                band=score_band(number(row.get("bin_f1"))), matched=esc(row.get("matched_bins") or "0"),
                unmatched=esc(row.get("unmatched_bins") or "0"), missed=esc(row.get("missed_plasmids") or "0"),
                splits=esc(row.get("split_events") or "0"), merges=esc(row.get("merge_events") or "0"),
                contaminated=esc(row.get("contaminated_bins") or "0"),
                repeat=esc(row.get("repeat_ambiguity_bp") or "0"),
                contamination=esc(row.get("contamination_fraction") or "-"), detail=detail,
            )
        )
    bin_diagnostics_html = "".join(bin_rows) or "<tr><td colspan='14'>No tool supplied validated bin membership in this run.</td></tr>"

    recommendation_rows = "".join(
        "<tr><td>{scope}</td><td>{group}</td><td>{tool}</td><td>{state}</td><td>{n}</td><td>{coverage}</td>"
        "<td>{f1}</td><td>{plasmid}</td><td>{runtime}</td><td>{memory}</td><td>{reason}</td></tr>".format(
            scope=esc(row.get("scope", "-")), group=esc(row.get("group", "-")),
            tool=esc(row.get("tool", "-")),
            state="Eligible operational method" if row.get("recommendation") == "primary" else "Candidate only",
            n=esc(row.get("n_scored", "0")), coverage=esc(row.get("coverage", "-")),
            f1=esc(row.get("mean_f1", "-")), plasmid=esc(row.get("mean_plasmid_recall", "-")),
            runtime=esc(row.get("median_runtime_seconds") or "not recorded"),
            memory=esc(row.get("median_peak_rss_kb") or "not recorded"),
            reason=esc(row.get("reason", "-")),
        ) for row in recommendations if row.get("recommendation") == "primary"
    ) or "<tr><td colspan='11'>No coverage-gated recommendation was produced for this cohort or stratum.</td></tr>"

    validation_rows = "".join(
        "<tr><td>{study}</td><td>{held}</td><td>{tool}</td><td>{train}</td><td>{f1}</td><td>{status}</td><td>{note}</td></tr>".format(
            study=esc(row.get("held_out_study") or "-"), held=esc(row.get("held_out_samples") or "0"),
            tool=esc(row.get("selected_method_from_training") or "No selection"),
            train=esc(row.get("training_samples") or "0"), f1=esc(row.get("held_out_mean_f1") or "-"),
            status=esc(row.get("status") or "not assessed"), note=esc(row.get("note") or "-"))
        for row in recommendation_validation
    ) or "<tr><td colspan='7'>No leave-one-study-out validation file was available.</td></tr>"

    comparison_rows = "".join(
        "<tr><td>{a}</td><td>{b}</td><td>{n}</td><td>{difference}</td><td>{ci}</td><td>{p}</td><td>{holm}</td><td>{wins}/{ties}/{losses}</td></tr>".format(
            a=esc(row["tool_a"]), b=esc(row["tool_b"]), n=esc(row["paired_samples"]),
            difference=esc(row["mean_f1_difference"]),
            ci=esc((row.get("difference_ci_low") and row.get("difference_ci_high") and
                    f"{row['difference_ci_low']} to {row['difference_ci_high']}") or "not estimated (n < 5)"),
            p=esc(row.get("permutation_p_value") or "not estimated (n < 5)"),
            holm=esc(row.get("permutation_p_value_holm") or "not estimated (n < 5)"),
            wins=esc(row["wins_a"]), ties=esc(row["ties"]), losses=esc(row["wins_b"]),
        ) for row in comparisons
    ) or "<tr><td colspan='8'>No paired score rows are available.</td></tr>"
    score_failure_html = "".join(
        "<li><strong>{sample} / {tool}</strong> at {stage}: {reason}</li>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]), stage=esc(row["stage"]), reason=esc(row["reason"])
        ) for row in score_failures
    ) or "<li>No score-stage failures were recorded.</li>"

    status_rows = "".join(
        "<tr data-status='{state}'><td>{sample}</td><td>{tool}</td><td><span class='status {state}'>{state}</span></td>"
        "<td>{runtime}</td><td>{memory}</td><td>{reason}</td></tr>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]), state=esc(row["status"]),
            runtime=esc(row.get("runtime_seconds") or "-"), memory=esc(row.get("peak_rss_kb") or "-"),
            reason=esc(row.get("reason") or "-"),
        ) for row in status
    ) or "<tr><td colspan='4'>Stage 4 status was not available.</td></tr>"

    sample_sections = []
    selection_cards = []
    for sample in samples:
        rows = score_by_sample.get(sample, [])
        body = "".join(
            "<tr><td>{tool}</td><td>{p}</td><td>{r}</td><td><strong>{f1}</strong></td><td>{fp:,}</td><td>{unmapped:,}</td></tr>".format(
                tool=esc(row["tool"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                fp=int(number(row["FP_bp"])), unmapped=int(number(row["unmapped_pred_bp"])),
            ) for row in rows
        ) or "<tr><td colspan='6'>No completed tool was scored for this sample.</td></tr>"
        selection = out.parent / sample / "selected_candidate" / "selection_report.json"
        selection_link = (f" <a href='{relative_link(selection, out)}' download>Download selected-candidate report</a>"
                          if selection.is_file() else "")
        selection_cards.append(selection_card(sample, out.parent, out))
        sample_sections.append(
            "<details class='sample'><summary><strong>{}</strong><span>{} scored tool(s)</span></summary>"
            "<p class='lead'>{} </p><table><thead><tr><th>Tool</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th>"
            "</tr></thead><tbody>{}</tbody></table></details>".format(
                esc(sample), len(rows), selection_link or "No selected-candidate report was produced.", body)
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
    # Inputs can be outside the run directory. Do not accidentally expose their
    # raw TSV contents merely because a temporary report shares their folder.
    report_inputs = (args.scores, args.tool_status, args.leaderboard, args.sample_sheet,
                     args.manifest, args.comparisons, args.score_failures, args.recommendations, args.recommendation_validation)
    for label, root in roots:
        tree, count, bytes_total = file_tree(root, out, report_inputs if label == "Results" else ())
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
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}} header{{background:#183a2d;color:#fff;padding:48px max(24px,calc((100vw - 1320px)/2));border-bottom:6px solid #a8d29b}} h1,h2,h3,th,.nav,button,select,input,.metric,.status,.selection-card{{font-family:Arial,sans-serif}} h1{{font-size:clamp(28px,5vw,48px);margin:0 0 8px;letter-spacing:-.04em}} header p{{margin:0;color:#d9e7de}} main{{max-width:1320px;margin:auto;padding:28px 24px 64px}} .nav{{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 28px}} .nav a{{color:var(--green);border:1px solid var(--line);background:#fff;padding:7px 10px;text-decoration:none;font-size:12px;font-weight:bold}} .metrics{{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:12px;margin-bottom:28px}} .metric{{background:var(--card);border-top:4px solid var(--green);padding:15px;box-shadow:0 1px 3px #15241c12}} .metric small{{color:var(--muted);display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em}} .metric strong{{font-size:27px;display:block;margin-top:4px}} section{{margin:38px 0}} h2{{font-size:21px;margin:0 0 5px}} h3{{margin:6px 0;font-size:17px}} .lead,.muted{{color:var(--muted)}} .panel{{background:var(--card);border:1px solid var(--line);overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:760px;font-family:Arial,sans-serif;font-size:13px}} th{{background:#edf2ec;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .sortable th{{cursor:pointer}} .sortable th:hover{{background:#dcebdc}} td{{border-top:1px solid var(--line);padding:9px 10px;white-space:nowrap}} tr:hover td{{background:#f5faf4}} .f1-bar{{display:block;width:100%;height:5px;background:#deeadf;margin-top:4px;min-width:64px}} .f1-bar i{{display:block;height:100%;background:var(--green)}} .f1-bar.medium i{{background:#c68221}} .f1-bar.low i{{background:#bd4b42}} .score.high{{color:#087250}} .score.medium{{color:#9a5b00}} .score.low{{color:#a53028}} .insight{{border-left:6px solid var(--green);background:#e7f1e7;padding:16px 20px}} .insight.caution{{border-color:var(--amber);background:#fbf2df}} .insight ul{{margin:6px 0 0;padding-left:20px}} .chart-card{{background:#fff;border:1px solid var(--line);padding:18px;overflow:auto}} .performance-chart{{display:block;min-width:650px;width:100%;height:auto}} .performance-chart .axis,.performance-chart .label{{font:12px Arial,sans-serif;fill:#536158}} .chart-legend,.legend{{display:flex;gap:16px;flex-wrap:wrap;font:12px Arial,sans-serif;margin:10px 0}} .chart-legend i,.legend i{{display:inline-block;width:10px;height:10px;margin-right:5px}} .metadata{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);font-family:Arial,sans-serif;font-size:13px}} .metadata div{{background:#fff;padding:12px}} .metadata small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.06em}} .controls{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}} select,input{{padding:7px;border:1px solid var(--line);background:#fff}} .count{{font:12px Arial,sans-serif;color:var(--muted);align-self:center}} .status,.selection-label{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold}} .completed,.reused{{background:#dcefdc;color:#07573e}} .failed{{background:#f7ddda;color:var(--red)}} .skipped{{background:#f6ead1;color:var(--amber)}} .selection-card{{display:grid;grid-template-columns:1fr auto;gap:14px;background:#fff;border:1px solid var(--line);border-left:6px solid var(--amber);padding:18px;margin:12px 0}} .selection-card.confident{{border-left-color:var(--green)}} .selection-label{{background:#f6ead1;color:#765000}} .confident .selection-label{{background:#dcefdc;color:#07573e}} .selection-actions{{text-align:right;min-width:190px}} .download-button{{display:inline-block;background:var(--green);color:#fff!important;padding:8px 10px;text-decoration:none;font-weight:bold}} .selection-card details{{grid-column:1/-1;border-top:1px solid var(--line)}} .selection-card summary{{padding:10px 0;cursor:pointer;font-weight:bold}} .selection-card ul{{margin:0;padding-left:20px}} details.sample,.explorer{{background:var(--card);border:1px solid var(--line);margin:10px 0;padding:0 14px}} details summary{{cursor:pointer;padding:13px 0;font-family:Arial,sans-serif}} details summary span{{float:right;color:var(--muted);font-size:12px}} .file-tree{{list-style:none;padding-left:18px;margin:0 0 15px;font-family:Arial,sans-serif;font-size:13px}} .file-tree li{{padding:3px 0}} .file-tree details summary{{padding:3px 0}} .file-tree a{{color:var(--green);text-decoration:none;font-weight:600}} .file-tree .file span{{color:var(--muted);font-size:11px;margin-left:8px}} .method{{columns:2;column-gap:32px;background:#ebf2ea;padding:18px 22px}} .method p{{margin-top:0;break-inside:avoid}} footer{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}} @media(max-width:700px){{main{{padding:20px 14px}}header{{padding:32px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metadata{{grid-template-columns:1fr}}.method{{columns:1}}.selection-card{{grid-template-columns:1fr}}.selection-actions{{text-align:left}}}}
</style></head><body>
<header><h1>SPREAD plasmid reconstruction benchmark</h1><p>Detailed run report · generated {esc(generated)} · offline HTML with direct artifact downloads</p></header>
<main><nav><a href='#insights'>Interpretation</a><a href='#chart'>Metric chart</a><a href='#leaderboard'>Method ranking</a><a href='#recommendations'>Recommendations</a><a href='#validation'>Study validation</a><a href='#selected'>Selected reconstructions</a><a href='#scores'>All scores</a><a href='#statistics'>Statistics</a><a href='#health'>Run health</a><a href='#tools'>Tool drill-down</a><a href='#samples'>Sample drill-down</a><a href='#keys'>Keys and legend</a><a href='#files'>File explorer</a><a href='#method'>Method</a></nav>
<div class='metrics'><div class='metric'><small>Samples observed</small><strong>{len(samples)}</strong></div><div class='metric'><small>Tools observed</small><strong>{len(tools)}</strong></div><div class='metric'><small>Benchmark winner: mean F1</small><strong>{best_f1}</strong><small>{best_value} · method ranking only</small></div><div class='metric'><small>Execution issues</small><strong>{status_counts['failed'] + status_counts['skipped']}</strong><small>{status_counts['failed']} failed · {status_counts['skipped']} skipped</small></div></div>
<section id='metadata'><h2>Run and output metadata</h2><div class='metadata'><div><small>Report generated</small>{esc(generated)}</div><div><small>Score observations</small>{len(scores)} sample-tool row(s)</div><div><small>Tracked artifacts</small>{artifact_count} file(s) · {esc(size_text(artifact_bytes))}</div><div><small>Execution states</small>{status_counts['completed']} completed · {status_counts['reused']} reused · {status_counts['failed']} failed · {status_counts['skipped']} skipped</div><div><small>Scoring inputs</small>scores.tsv, tool_status.tsv, benchmark.leaderboard.tsv</div><div><small>Reference scope</small>Complete assembly reference bases; plasmid is the positive class</div></div></section>
<section id='insights'><h2>Automated interpretation</h2><div class='insight {insight_tone}'><p class='lead'>Generated from the score and execution-status tables. Where at least five shared samples exist, the statistics section adds paired confidence intervals and permutation evidence with Holm adjustment.</p><ul>{insight_html}</ul></div></section>
<section id='chart'><h2>Performance profile</h2><p class='lead'>Mean precision, recall, and F1 by tool. Green is precision, amber is recall, and dark green is F1; bar length spans 0 to 1.</p><div class='chart-card'>{chart_html}</div></section>
<section id='leaderboard'><h2>Benchmark method ranking</h2><p class='lead'>This compares methods across this benchmark cohort. It is not, by itself, a claim that the top method has produced a biologically confirmed plasmid for every sample. Plasmid recall gives equal weight to each truth plasmid, limiting domination by a large replicon. Mean bin F1 is shown only for declared binning methods; “not applicable” is not a zero. Select a column heading to sort.</p><div class='panel'><table class='sortable'><thead><tr><th>Rank</th><th>Tool</th><th>Scored</th><th>Completed</th><th>Failed</th><th>Skipped</th><th>Mean precision</th><th>Mean base recall</th><th>Mean plasmid recall</th><th>Mean bin F1</th><th>Mean F1</th></tr></thead><tbody>{leaderboard_rows}</tbody></table></div></section>
<section id='recommendations'><h2>Operational method recommendations</h2><p class='lead'>These are coverage-gated, multi-objective method recommendations, not proof that any individual predicted sequence is correct. Accuracy is primary; failure rate, structural diagnostics, runtime, and memory are included as lower-weighted practical considerations. Each scored isolate also has a reusable <code>selected_candidate/</code> folder containing the chosen already-generated FASTA and a JSON explanation.</p><div class='panel'><table class='sortable'><thead><tr><th>Scope</th><th>Group</th><th>Primary method</th><th>State</th><th>Scored</th><th>Coverage</th><th>Mean F1</th><th>Mean plasmid recall</th><th>Median runtime s</th><th>Median peak RSS KiB</th><th>Decision note</th></tr></thead><tbody>{recommendation_rows}</tbody></table></div></section>
<section id='validation'><h2>Leave-one-study-out validation</h2><p class='lead'>For each source study, the method is selected using all other studies and then evaluated only on the held-out study. A withheld result means the cohort does not yet have enough independent study evidence; it is not a failed method.</p><div class='panel'><table class='sortable'><thead><tr><th>Held-out study</th><th>Held-out samples</th><th>Training-selected method</th><th>Training samples</th><th>Held-out mean F1</th><th>Status</th><th>Interpretation</th></tr></thead><tbody>{validation_rows}</tbody></table></div></section>
<section id='selected'><h2>Selected reconstructions</h2><p class='lead'>Each card translates its <code>selection_report.json</code> into a research-facing decision. Downloading the selected FASTA does not rerun any reconstruction; it retrieves the original output retained from the completed tool run.</p>{''.join(selection_cards) or "<p class='muted'>No sample-level selection reports were produced.</p>"}</section>
<section id='scores'><h2>All sample-tool scores</h2><p class='lead'>Filter by performance, tool provenance, or cohort metadata; export the exact visible subset. Unambiguous, ambiguous, and unmapped predicted bases are separate categories. AMR and circular-truth recovery are unavailable (-) unless curated truth annotations were supplied. Circular-truth recovery is not evidence that a predicted sequence is closed.</p><div class='controls'><label>Sample <select id='sample-filter'><option value=''>All samples</option>{''.join(f"<option>{esc(s)}</option>" for s in samples)}</select></label><label>Tool <select id='tool-filter'><option value=''>All tools</option>{''.join(f"<option>{esc(t)}</option>" for t in tools)}</select></label><label>Tool version <select id='version-filter'><option value=''>All versions</option><option>not recorded</option>{''.join(f"<option>{esc(v)}</option>" for v in versions)}</select></label><label>Organism <select id='organism-filter'><option value=''>All organisms</option>{''.join(f"<option>{esc(v)}</option>" for v in organisms)}</select></label><label>Origin <select id='origin-filter'><option value=''>All origins</option>{''.join(f"<option>{esc(v)}</option>" for v in origins)}</select></label><label>Truth technology <select id='tech-filter'><option value=''>All technologies</option>{''.join(f"<option>{esc(v)}</option>" for v in technologies)}</select></label><label>Truth tier <select id='tier-filter'><option value=''>All tiers</option>{''.join(f"<option>{esc(v)}</option>" for v in tiers)}</select></label><label>Plasmid size <select id='size-filter'><option value=''>All sizes</option><option value='small'>Small (&lt;10 kb)</option><option value='medium'>Medium (10–100 kb)</option><option value='large'>Large (≥100 kb)</option></select></label><label>Depth ≥ <input id='depth-min' type='number' min='0' step='any' placeholder='any'></label><label>Depth ≤ <input id='depth-max' type='number' min='0' step='any' placeholder='any'></label><label>F1 band <select id='band-filter'><option value=''>All bands</option><option value='high'>High (≥0.90)</option><option value='medium'>Medium (0.70–0.89)</option><option value='low'>Low (&lt;0.70)</option></select></label><button id='export-scores' type='button'>Download filtered CSV</button><span id='score-count' class='count'></span></div><div class='panel'><table id='score-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Tool version</th><th>Origin</th><th>Read depth ×</th><th>True plasmid bp</th><th>TP bp</th><th>FP bp</th><th>FN bp</th><th>Unambiguous predicted bp</th><th>Ambiguous predicted bp</th><th>Unmapped predicted bp</th><th>Precision</th><th>Recall</th><th>AMR recovery</th><th>Circular truth recovery</th><th>F1</th></tr></thead><tbody>{score_rows}</tbody></table></div></section>
<section id='statistics'><h2>Paired tool comparisons</h2><p class='lead'>Differences are tool A minus tool B on shared samples. Confidence intervals and two-sided sign-flip permutation p-values require at least five pairs. Holm values control family-wise error across comparisons and remain descriptive evidence, not a substitute for study design.</p><div class='panel'><table class='sortable'><thead><tr><th>Tool A</th><th>Tool B</th><th>Pairs</th><th>Mean F1 difference</th><th>95% bootstrap CI</th><th>Permutation p</th><th>Holm-adjusted p</th><th>A wins / ties / B wins</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><p class='lead'>Score-stage isolation events:</p><ul>{score_failure_html}</ul></section>
<section id='bin-diagnostics'><h2>Bin reconstruction diagnostics</h2><p class='lead'>Only tools with validated bin membership are shown. A split is one truth plasmid represented by multiple candidate bins; a merge is one candidate bin with high-completeness evidence for multiple truth plasmids. Repeat ambiguity is bin sequence with both plasmid and chromosome mapping alternatives. Contamination fraction is chromosome-aligned bp divided by all truth-mapped bin bp. Open each matches TSV for bin-to-truth assignments, unmatched bins, and missed plasmids.</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Bin precision</th><th>Bin recall</th><th>Bin F1</th><th>Matched bins</th><th>Unmatched bins</th><th>Missed plasmids</th><th>Split events</th><th>Merge events</th><th>Contaminated bins</th><th>Repeat ambiguity bp</th><th>Contamination fraction</th><th>Record-level detail</th></tr></thead><tbody>{bin_diagnostics_html}</tbody></table></div></section>
<section id='health'><h2>Execution health</h2><p class='lead'>A failed or unavailable tool is excluded from F1 aggregation. Runtime is elapsed wall-clock seconds; peak RSS is shown when the host profiler provides it.</p><div class='controls'><label>Status <select id='status-filter'><option value=''>All states</option><option value='completed'>Completed</option><option value='reused'>Reused</option><option value='failed'>Failed</option><option value='skipped'>Skipped</option></select></label><span id='status-count' class='count'></span></div><div class='panel'><table id='status-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Status</th><th>Runtime s</th><th>Peak RSS KiB</th><th>Reason / log location</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
<section id='tools'><h2>Tool drill-down</h2><p class='lead'>Open a tool to inspect its score distribution across samples. Rows are initially ordered by F1.</p>{''.join(tool_sections) or "<p class='muted'>No tools were found.</p>"}</section>
<section id='samples'><h2>Sample drill-down</h2><p class='lead'>Open a sample to compare every completed tool side-by-side.</p>{''.join(sample_sections) or "<p class='muted'>No samples were found.</p>"}</section>
<section id='keys'><h2>Keys, legend, and metric definitions</h2><div class='legend'><span><i style='background:#087250'></i>High F1: ≥0.90</span><span><i style='background:#c68221'></i>Medium F1: 0.70–0.89</span><span><i style='background:#bd4b42'></i>Low F1: &lt;0.70</span><span><i style='background:#2c7a62'></i>Precision chart bar</span><span><i style='background:#d18b2a'></i>Recall chart bar</span></div><div class='method'><p><strong>TP (true positive) bp:</strong> plasmid-reference bases covered by a predicted-plasmid alignment.</p><p><strong>FP (false positive) bp:</strong> chromosome-reference bases covered by a predicted-plasmid alignment; this is chromosomal contamination.</p><p><strong>FN (false negative) bp:</strong> true plasmid-reference bases not covered by a predicted-plasmid alignment.</p><p><strong>Precision:</strong> TP / (TP + FP). Higher means less chromosome sequence among the claimed plasmid sequence.</p><p><strong>Recall / completeness:</strong> TP / (TP + FN). Higher means more of the true plasmid sequence was recovered.</p><p><strong>AMR recovery:</strong> fraction of supplied curated AMR genes recovered above the configured threshold.</p><p><strong>Circular-truth recovery:</strong> fraction of circular reference plasmids recovered above the configured threshold. It does not establish circularity or closure of a predicted sequence.</p><p><strong>F1:</strong> harmonic mean of precision and recall, from 0 (worst) to 1 (best). The color bands are visual aids, not acceptance thresholds.</p><p><strong>Unmapped predicted bp:</strong> predicted-plasmid bases with no alignment to any labelled reference sequence. They are reported separately, not added to FP.</p><p><strong>Scored / completed / failed / skipped:</strong> scored is the number contributing to the metric; completed and reused are valid tool results; failed and skipped are exposed for coverage transparency.</p></div></section>
<section id='files'><h2>Artifact explorer</h2><p class='lead'>All files created or consumed by this project are listed below. Select a filename to open or download it; directory branches can be expanded independently.</p>{''.join(explorers)}</section>
<section id='method'><h2>Scoring method and interpretation</h2><div class='method'><p><strong>Truth:</strong> sequences in each complete reference assembly are labelled plasmid or chromosome from the NCBI sequence report.</p><p><strong>Prediction:</strong> each tool’s standardized predicted-plasmid FASTA is aligned to the reference using minimap2.</p><p><strong>Metrics:</strong> covered plasmid reference bases are TP; covered chromosome reference bases are FP; uncovered plasmid bases are FN. Precision measures contamination control; recall measures plasmid completeness; F1 balances both.</p><p><strong>Run integrity:</strong> failed tool execution, failed adaptation, and mapping failure do not become zero-score observations. They appear in execution health and reduce the completed/scored counts shown in the leaderboard.</p></div></section>
<footer>Inputs: <a href='scores.tsv'>scores.tsv</a>, <a href='tool_status.tsv'>tool_status.tsv</a>, <a href='benchmark.leaderboard.tsv'>benchmark.leaderboard.tsv</a>. Report location: {esc(out.name)}.</footer></main>
<script>
const sf=document.getElementById('sample-filter'),tf=document.getElementById('tool-filter'),vf=document.getElementById('version-filter'),bf=document.getElementById('band-filter'),of=document.getElementById('organism-filter'),originf=document.getElementById('origin-filter'),cf=document.getElementById('tech-filter'),qf=document.getElementById('tier-filter'),sizef=document.getElementById('size-filter'),depthMin=document.getElementById('depth-min'),depthMax=document.getElementById('depth-max');
function filterScores(){{let visible=0;const min=depthMin.value===''?null:Number(depthMin.value),max=depthMax.value===''?null:Number(depthMax.value);document.querySelectorAll('#score-table tbody tr').forEach(r=>{{const depth=r.dataset.depth===''?null:Number(r.dataset.depth),outsideDepth=(min!==null&&(depth===null||depth<min))||(max!==null&&(depth===null||depth>max));const hide=(sf.value&&r.dataset.sample!==sf.value)||(tf.value&&r.dataset.tool!==tf.value)||(vf.value&&r.dataset.version!==vf.value)||(bf.value&&r.dataset.band!==bf.value)||(of.value&&r.dataset.organism!==of.value)||(originf.value&&r.dataset.origin!==originf.value)||(cf.value&&r.dataset.tech!==cf.value)||(qf.value&&r.dataset.tier!==qf.value)||(sizef.value&&r.dataset.size!==sizef.value)||outsideDepth;r.hidden=hide;if(!hide)visible++;}});document.getElementById('score-count').textContent=visible+' visible score row(s)';}}
[sf,tf,vf,bf,of,originf,cf,qf,sizef].forEach(el=>el.onchange=filterScores);[depthMin,depthMax].forEach(el=>el.oninput=filterScores);filterScores();
document.getElementById('export-scores').onclick=()=>{{const rows=Array.from(document.querySelectorAll('#score-table tr')).filter(r=>!r.hidden).map(r=>Array.from(r.cells).map(c=>'"'+c.innerText.replaceAll('"','""')+'"').join(','));const blob=new Blob([rows.join('\n')+'\n'],{{type:'text/csv'}}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='plasbench-filtered-scores.csv';link.click();URL.revokeObjectURL(link.href);}};
const statusFilter=document.getElementById('status-filter');function filterStatus(){{let visible=0;document.querySelectorAll('#status-table tbody tr').forEach(r=>{{const hide=statusFilter.value&&r.dataset.status!==statusFilter.value;r.hidden=hide;if(!hide)visible++;}});document.getElementById('status-count').textContent=visible+' visible execution row(s)';}}statusFilter.onchange=filterStatus;filterStatus();
document.querySelectorAll('table.sortable th').forEach((head,index)=>head.addEventListener('click',()=>{{const table=head.closest('table'),body=table.tBodies[0],rows=Array.from(body.rows),ascending=head.dataset.order!=='asc';rows.sort((a,b)=>{{const av=a.cells[index]?.innerText.trim()||'',bv=b.cells[index]?.innerText.trim()||'',an=Number(av.replace(/[^0-9.-]/g,'')),bn=Number(bv.replace(/[^0-9.-]/g,''));const result=Number.isNaN(an)||Number.isNaN(bn)?av.localeCompare(bv):an-bn;return ascending?result:-result;}});rows.forEach(row=>body.appendChild(row));table.querySelectorAll('th').forEach(h=>delete h.dataset.order);head.dataset.order=ascending?'asc':'desc';}}));
</script>
</body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote HTML report: {out}")


if __name__ == "__main__":
    main()
