#!/usr/bin/env python3
"""Build the self-contained HTML dashboard emitted after benchmark aggregation."""

import argparse
import re
import base64
import csv
import datetime as dt
import html
import json
import os
import shutil
import sys
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
    """Map report tool labels to versions recorded at the time of the run.

    Two sources, in order. The executable map covers the adapters that ship
    here, whose report label differs from the command they invoke. A run may
    also record ``method_versions`` keyed by report label, which is the only
    way a method outside that fixed list -- a new adapter, or a synthetic
    method -- can report a version at all; it wins where both are present.
    """
    if not path or not Path(path).is_file():
        return {}
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    tools = manifest.get("tools", {}) or {}
    executable = {
        "mob_recon": "mob_recon", "platon": "platon",
        "plasmidspades": "plasmidspades.py", "gplas": "gplas",
        "gplas2_external": "gplas", "gplas2_mob": "gplas",
    }
    versions = {label: details.get("version", "unreported")
                for label, name in executable.items()
                if (details := tools.get(name, {})).get("available")}
    declared = manifest.get("method_versions", {}) or {}
    if isinstance(declared, dict):
        versions.update({str(label): str(value) for label, value in declared.items() if value})
    return versions


def number(value):
    return float(value) if value not in (None, "") else 0.0


def optional_number(value):
    return float(value) if value not in (None, "") else None


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
    # Candidates live in one collection directory, each file carrying its sample
    # id; the older per-sample location is still read so existing runs open.
    directory = results_dir / "selected_candidates" / sample
    report_file = directory / f"{sample}.selection_report.json"
    for fallback in (directory / "selection_report.json",
                     results_dir / sample / "selected_candidate" / "selection_report.json",
                     results_dir / sample / "selection_report.json"):
        if report_file.is_file():
            break
        report_file = fallback
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
    structural_text = (f"{len(structural.get('items', []))} validated source-evidence item(s), including {len(structural.get('validated_closure_items', []))} supported closure item(s)."
                       if structural.get("status") == "validated_source_evidence" else "No validated replicon, MOB, or closure evidence was supplied.")
    return """<div class='selection-card {tone}'>
<div><span class='selection-label'>{status}</span><h3>{sample}: {tool}</h3><p>{score}</p><p><strong>Confidence:</strong> {confidence}</p></div>
<div class='selection-actions'>{fasta}<br>{report}</div>
<details><summary>Why this selection needs review</summary><ul>{reasons}</ul><p><strong>Agreement between methods:</strong> {agreement}</p><p><strong>Structural evidence:</strong> {structural}</p><p><strong>Other evaluated methods:</strong> {alternatives}</p><p class='muted'>This card does not claim that the sequence is closed, circular, or clinically validated.</p></details>
</div>""".format(
        tone="confirmation" if confidence != "high" else "confident", status=esc(status), sample=esc(sample),
        tool=esc(selected_tool), score=score_text, confidence=esc(confidence_label), fasta=fasta_link,
        report=report_link, reasons=reasons, alternatives=alternatives, agreement=esc(agreement_text), structural=esc(structural_text))


INLINE_VISUALIZATION_BUDGET = 6 * 1024 * 1024


def stage_visualizations(scores, results_dir, report_path, inline_budget=INLINE_VISUALIZATION_BUDGET):
    """Inline small visualization payloads; publish large ones as sibling files.

    Every sample's alignment blocks embedded in one page does not survive a real
    cohort: at ~219 bytes per retained block a 32-sample run reaches tens of
    megabytes, all parsed before anything renders. Small runs stay a single
    portable file; larger ones are fetched per sample on selection.
    """
    available, inline, total = {}, {}, 0
    for sample in sorted({row["sample"] for row in scores}):
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        available[sample] = len(text)
        total += len(text)
        inline[sample] = payload
    if total <= inline_budget:
        return inline, {}, {"mode": "inline", "bytes": total, "samples": len(inline)}
    # Publish beside the report so the browser can fetch one sample at a time.
    out_dir = report_path.parent / "visualization"
    out_dir.mkdir(parents=True, exist_ok=True)
    external = {}
    for sample in available:
        source = results_dir / sample / "visualization" / "alignment_blocks.json"
        target = out_dir / f"{sample}.json"
        try:
            shutil.copyfile(source, target)
        except OSError:
            continue
        external[sample] = f"visualization/{quote(sample, safe='')}.json"
    return {}, external, {"mode": "external", "bytes": total, "samples": len(external)}


def visual_quality_section(scores, status, results_dir, report_path=None):
    """Return a linked heatmap and reference-coordinate alignment explorer."""
    report_path = report_path or (results_dir / "benchmark.report.html")
    visualizations, external, staging = stage_visualizations(scores, results_dir, report_path)
    state = {(row.get("sample"), row.get("tool")): row.get("status", "scored") for row in status}
    # Runtime and peak RSS are recorded in stage 4; collinear_fraction in stage 5.
    profile = {}
    for row in status:
        try:
            runtime = float(row["runtime_seconds"]) / 60 if row.get("runtime_seconds") else None
            memory = float(row["peak_rss_kb"]) / (1024 * 1024) if row.get("peak_rss_kb") else None
        except (TypeError, ValueError):
            runtime = memory = None
        profile[(row.get("sample"), row.get("tool"))] = {"runtime_seconds": runtime, "peak_rss_kb": memory}
    structural = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "structural_summary.tsv"
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    value = row.get("collinear_fraction")
                    structural[(sample, row.get("tool"))] = float(value) if value else None
        except (OSError, ValueError):
            continue
    matrix = []
    for row in scores:
        tp, fp = number(row.get("TP_bp")), number(row.get("FP_bp"))
        base_f1, plasmid_recall = optional_number(row.get("f1")), optional_number(row.get("plasmid_recall"))
        bin_f1 = optional_number(row.get("bin_f1"))
        contamination = fp / (tp + fp) if tp + fp else None
        components = [(0.45, base_f1), (0.25, plasmid_recall), (0.15, bin_f1),
                      (0.15, 1 - contamination if contamination is not None else None)]
        available = [(weight, value) for weight, value in components if value is not None]
        composite = sum(weight * value for weight, value in available) / sum(weight for weight, _ in available) if available else None
        matrix.append({"sample": row["sample"], "tool": row["tool"], "status": state.get((row["sample"], row["tool"]), "scored"),
                       "f1": number(row.get("f1")), "precision": number(row.get("precision")), "recall": number(row.get("recall")),
                       "plasmid_recall": plasmid_recall, "bin_f1": number(row["bin_f1"]) if row.get("bin_f1") else None,
                       "contamination": contamination, "unmapped": number(row.get("unmapped_pred_bp")), "composite": composite,
                       # Execution cost and structural concordance are already measured;
                       # surfacing them as heatmap metrics needs no new computation.
                       "runtime_min": (profile.get((row["sample"], row["tool"]), {}).get("runtime_seconds") or None),
                       "memory_gb": (profile.get((row["sample"], row["tool"]), {}).get("peak_rss_kb") or None),
                       "collinear": structural.get((row["sample"], row["tool"]))})
    payload = json.dumps({"matrix": matrix, "visualizations": visualizations,
                          "visualization_sources": external, "staging": staging},
                         separators=(",", ":")).replace("<", "\\u003c")
    return """<div id='cohort-evidence-explorer'><h3>Reconstruction evidence explorer</h3>
<p class='lead'>This detailed evidence panel is part of the interactive cohort dashboard. Select a sample and method here to follow a dashboard finding to one truth plasmid. It uses retained primary PAF blocks on truth-reference coordinates; it is not a raw nucleotide alignment or an independent structural-validation claim.</p>
<div class='controls'><label>Sample <select id='vq-sample'></select></label><label>Tool <select id='vq-tool'></select></label><label>Truth plasmid <select id='vq-plasmid'></select></label><button id='vq-fit' type='button'>Fit</button><button id='vq-in' type='button'>Zoom in</button><button id='vq-out' type='button'>Zoom out</button><label>Start <input id='vq-start' type='number' min='0'></label><label>End <input id='vq-end' type='number' min='1'></label><a id='vq-download' class='download-button' download>Download JSON</a></div>
<div class='panel'><div id='vq-tracks' class='muted'>Choose a sample with visualization data.</div><div id='vq-detail' class='insight neutral'>Click a coloured block to inspect its alignment evidence. Mouse-wheel over tracks zooms the selected reference interval.</div></div>
<details class='sample'><summary><strong>Legend and limits</strong><span>how to interpret this dashboard evidence</span></summary><div class='method'><p><strong>Sample-Tool Heatmap:</strong> the dashboard canvas is the single cohort matrix. Its metric selector, filters, tooltip, clustering, keyboard navigation, drilldown modal, and exports apply there. Grey is unavailable; failed and skipped states are never converted to zero.</p><p><strong>Tracks:</strong> green blocks align in the forward orientation; purple blocks align in reverse. White is not recovered by the displayed blocks. Blue triangles mark curated AMR features. The JSON records omitted blocks when a display cap applies.</p><p><strong>AliView-like drill-down:</strong> use zoom, coordinates, and block clicks to investigate a region. Whole-plasmid base letters are deliberately not rendered because they are slow and misleading without a region-specific multiple alignment.</p></div></details>
<script id='vq-data' type='application/json'>__PAYLOAD__</script><script>
(()=>{const d=JSON.parse(document.getElementById('vq-data').textContent),m=d.matrix,v=d.visualizations,$=id=>document.getElementById(id),samples=[...new Set(m.map(x=>x.sample))].sort(),tools=[...new Set(m.map(x=>x.tool))].sort();let range=null;
const select=(e,items)=>e.innerHTML=items.map(x=>`<option value="${x}">${x}</option>`).join('');
function setTools(){select($('vq-tool'),tools.filter(t=>m.some(r=>r.sample===$('vq-sample').value&&r.tool===t)))}function setPlasmids(){let a=v[$('vq-sample').value];select($('vq-plasmid'),a?Object.keys(a.truth_plasmids).sort():[])}
function draw(){let s=$('vq-sample').value,t=$('vq-tool').value,p=$('vq-plasmid').value,a=v[s];if(!a||!p){$('vq-tracks').textContent='No visualization data. Re-run stage 5 after retaining PAF scoring alignments.';return}let len=a.truth_plasmids[p].length,[lo,hi]=range||[0,len];lo=Math.max(0,Math.min(lo,len-1));hi=Math.max(lo+1,Math.min(hi,len));range=[lo,hi];$('vq-start').value=Math.floor(lo);$('vq-end').value=Math.ceil(hi);$('vq-download').href=s+'/visualization/alignment_blocks.json';let names=Object.keys(a.tools),scale=x=>180+(x-lo)/(hi-lo)*880,svg=`<svg viewBox="0 0 1100 ${55+names.length*38}"><text x="180" y="15" font-size="12">${p}: ${Math.floor(lo).toLocaleString()}–${Math.ceil(hi).toLocaleString()} / ${len.toLocaleString()} bp</text>`;names.forEach((name,i)=>{let y=40+i*38,z=a.tools[name],rec=z.plasmid_recovery[p]||{},bs=z.blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi);svg+=`<text x="4" y="${y+7}" font-size="12">${name}</text><text x="105" y="${y+7}" font-size="11">${((rec.completeness||0)*100).toFixed(1)}%</text><rect x="180" y="${y-8}" width="880" height="16" fill="#f7f8f5" stroke="#d6ddd5"/>`;bs.forEach((b,i)=>{let x=Math.max(180,scale(b.target_start)),r=Math.min(1060,scale(b.target_end));svg+=`<rect class="vq-block" data-n="${name}" data-i="${i}" x="${x}" y="${y-8}" width="${Math.max(1,r-x)}" height="16" fill="${b.strand==='-'?'#7f5aa2':'#16805a'}"><title>${b.record_id}</title></rect>`})});a.amr_features.filter(f=>f.sequence_id===p&&f.start>=lo&&f.start<=hi).forEach(f=>{let x=scale(f.start);svg+=`<path d="M${x} 25 l5 -9 l5 9z" fill="#2275ad"><title>${f.label}</title></path>`});svg+='</svg>';$('vq-tracks').innerHTML=svg+'<p class="muted">Displayed primary blocks; '+names.map(n=>n+': '+a.tools[n].blocks_omitted+' omitted').join(' · ')+'</p>';document.querySelectorAll('.vq-block').forEach(e=>e.onclick=()=>{let b=a.tools[e.dataset.n].blocks.filter(x=>x.target===p&&x.target_end>lo&&x.target_start<hi)[e.dataset.i];$('vq-detail').textContent=`${e.dataset.n} | ${b.record_id} | query ${b.query_start}-${b.query_end}/${b.query_length} | reference ${b.target_start}-${b.target_end} | ${b.strand} strand | identity ${(100*b.matches/Math.max(1,b.block_length)).toFixed(2)}% | MAPQ ${b.mapq}`})}
$('vq-sample').onchange=()=>{range=null;setTools();setPlasmids();draw()};$('vq-tool').onchange=draw;$('vq-plasmid').onchange=()=>{range=null;draw()};$('vq-start').onchange=()=>{range=[+$('vq-start').value,+$('vq-end').value];draw()};$('vq-end').onchange=()=>{range=[+$('vq-start').value,+$('vq-end').value];draw()};$('vq-fit').onclick=()=>{range=null;draw()};$('vq-in').onclick=()=>{if(range){let c=(range[0]+range[1])/2,z=(range[1]-range[0])/2;range=[c-z/2,c+z/2];draw()}};$('vq-out').onclick=()=>{if(range){let c=(range[0]+range[1])/2,z=(range[1]-range[0])*2;range=[c-z/2,c+z/2];draw()}};$('vq-tracks').addEventListener('wheel',e=>{if(!range)return;e.preventDefault();let c=(range[0]+range[1])/2,z=(range[1]-range[0])*(e.deltaY<0?.7:1.4);range=[c-z/2,c+z/2];draw()},{passive:false});select($('vq-sample'),samples);setTools();setPlasmids();draw()})();
</script></div>""".replace("__PAYLOAD__", payload)


def advanced_visual_script():
    """Enhance the base explorer with dot plot, flows, exports, and local bases."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),data=JSON.parse($('vq-data').textContent),tracks=$('vq-tracks'),detail=$('vq-detail');
const dot=document.createElement('div'),flow=document.createElement('div'),actions=document.createElement('span');dot.id='vq-dotplot';flow.id='vq-flow';tracks.after(dot,flow);actions.innerHTML='<button id="vq-svg" type="button">Download track SVG</button><button id="vq-png" type="button">Download track PNG</button>';$('vq-download').after(actions);
function current(){let a=data.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;let lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||a.truth_plasmids[p].length;return {a,p,t,lo,hi,blocks:a.tools[t].blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi)}}
function renderFlow(){let x=current();if(!x){flow.innerHTML='';return}let f=x.a.tools[x.t].bin_assignment_flows||[];flow.innerHTML=f.length?'<h3>Bin-to-truth assignment flow</h3><p class="muted">Only scored bin assignments are shown; unobserved alternative links are not fabricated.</p><ul>'+f.map(r=>`<li>${r.bin_id||'no bin'} → ${r.true_plasmid||r.status}: ${r.aligned_bp.toLocaleString()} bp (${r.status})</li>`).join('')+'</ul>':''}
function local(e){let x=current();if(!x)return;let b=x.blocks[Number(e.target.dataset.i)];if(!b)return;const n=v=>Number(v).toLocaleString();
// Every block carries measured alignment evidence. Only the nucleotide view
// needs a CIGAR, so a block without one still has something to report.
let pct=b.block_length?100*b.matches/b.block_length:0;
let rows=[['Predicted record',b.record_id],
 ['Truth reference',b.target+' ('+String(b.molecule_type||'unknown').toLowerCase()+')'],
 ['Reference span',n(b.target_start)+'–'+n(b.target_end)+'  ('+n(b.target_end-b.target_start)+' bp)'],
 ['Record span',n(b.query_start)+'–'+n(b.query_end)+' of '+n(b.query_length)+' bp'],
 ['Orientation',b.strand==='-'?'reverse (−)':'forward (+)'],
 ['Identity',pct.toFixed(1)+'%  ('+n(b.matches)+'/'+n(b.block_length)+' matching bases)'],
 ['Mapping quality',String(b.mapq)]];
let html='<strong>Selected alignment block</strong><table class="vq-kv">'+rows.map(r=>'<tr><th>'+r[0]+'</th><td>'+r[1]+'</td></tr>').join('')+'</table>';
let a=b.local_alignment;
if(a){let marks=[...a.reference].map((c,i)=>c===a.prediction[i]?' ':'^').join('');
 html+='<strong>Local nucleotide alignment</strong><code>Reference  '+a.reference+'<br>           '+marks+'<br>Prediction '+a.prediction+'</code><p class="muted">'+a.meaning+'</p>'}
else{html+='<p class="muted">No nucleotide view for this block: it carries no <code>cg:Z:</code> CIGAR tag, or it is longer than the display cap. The evidence above is measured from the alignment record itself.</p>'}
detail.innerHTML=html}
document.addEventListener('click',e=>{if(e.target.classList.contains('vq-block'))setTimeout(()=>local(e),0)});['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end','vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(renderFlow,0)));$('vq-fit').addEventListener('click',()=>setTimeout(renderFlow,0));$('vq-in').addEventListener('click',()=>setTimeout(renderFlow,0));$('vq-out').addEventListener('click',()=>setTimeout(renderFlow,0));
function download(name,blob){let a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0)}$('vq-svg').onclick=()=>{let svg=tracks.querySelector('svg');if(svg)download('plasbench-recovery-tracks.svg',new Blob([svg.outerHTML],{type:'image/svg+xml'}))};$('vq-png').onclick=()=>{let svg=tracks.querySelector('svg');if(!svg)return;let image=new Image(),url=URL.createObjectURL(new Blob([svg.outerHTML],{type:'image/svg+xml'}));image.onload=()=>{let c=document.createElement('canvas');c.width=1100;c.height=svg.viewBox.baseVal.height;c.getContext('2d').drawImage(image,0,0);c.toBlob(b=>download('plasbench-recovery-tracks.png',b));URL.revokeObjectURL(url)};image.src=url};renderFlow();})();
</script>"""


def evidence_selection_script():
    """Keep evidence-explorer deep links after retiring its duplicate matrix."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),keys=[['sample','vq-sample'],['tool','vq-tool'],['plasmid','vq-plasmid'],['start','vq-start'],['end','vq-end']];let restoring=false;
function write(){if(restoring)return;const params=new URLSearchParams();keys.forEach(([key,id])=>{const value=$(id)?.value;if(value)params.set(key,value)});history.replaceState(null,'','#'+params.toString())}
function read(){const params=new URLSearchParams(location.hash.slice(1));if(![...params].length)return;restoring=true;for(const [key,id]of keys){const value=params.get(key),element=$(id);if(value!=null&&element){element.value=value;element.dispatchEvent(new Event('change'))}}restoring=false}
window.addEventListener('message',event=>{if(event.source!==$('pb-enterprise')?.contentWindow)return;const value=event.data;if(!value||value.type!=='plasbench-selection'||!value.sample)return;const sample=$('vq-sample');sample.value=value.sample;sample.dispatchEvent(new Event('change'));const tool=$('vq-tool');if(value.tool&&[...tool.options].some(option=>option.value===value.tool)){tool.value=value.tool;tool.dispatchEvent(new Event('change'))}const plasmid=$('vq-plasmid');if(value.plasmid&&[...plasmid.options].some(option=>option.value===value.plasmid)){plasmid.value=value.plasmid;plasmid.dispatchEvent(new Event('change'))}});
keys.forEach(([,id])=>$(id)?.addEventListener('change',()=>setTimeout(write,0)));read();})();
</script>"""


def bin_flow_script():
    """Interactive alluvial bin-to-truth flow.

    Clustering moved to the dashboard's own control; this keeps the flow, which
    is the only rendering of bin_assignment_flows in the report.
    """
    return """<style>
#vq-sankey svg{max-width:100%;height:auto}
#vq-sankey .lnk{fill-opacity:.45;cursor:pointer}
#vq-sankey .lnk:hover,#vq-sankey .lnk.on{fill-opacity:.85}
#vq-sankey .nd{fill:#2f4f45}
#vq-sankey text{font:11px Arial,sans-serif;fill:#26332d}
#vq-sankey-detail{font:12px Arial,sans-serif;color:#3b4746;margin-top:6px}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
// ---- alluvial flow ----
const host=document.createElement('div');host.id='vq-sankey';
const detail=document.createElement('div');detail.id='vq-sankey-detail';
($('vq-flow')||$('vq-tracks')).after(host);host.after(detail);
function render(){const a=d.visualizations[$('vq-sample').value],t=$('vq-tool').value;
 if(!a||!a.tools[t]){host.innerHTML='';detail.textContent='';return}
 const flows=(a.tools[t].bin_assignment_flows||[]).filter(f=>f.bin_id&&f.true_plasmid&&f.aligned_bp>0);
 if(!flows.length){host.innerHTML='<h3>Bin-to-truth flow</h3><p class="muted">No scored bin assignments for this method; contig-level classifiers do not declare bins.</p>';detail.textContent='';return}
 const bins=[...new Set(flows.map(f=>f.bin_id))],truths=[...new Set(flows.map(f=>f.true_plasmid))];
 const total=flows.reduce((s,f)=>s+f.aligned_bp,0);
 const H=Math.max(160,Math.max(bins.length,truths.length)*46),W=760,gap=6;
 const lay=(names,x)=>{let y=20,m={};const tot=names.reduce((s,n)=>s+flows.filter(f=>(x?f.true_plasmid:f.bin_id)===n).reduce((q,f)=>q+f.aligned_bp,0),0)||1;
  names.forEach(n=>{const bp=flows.filter(f=>(x?f.true_plasmid:f.bin_id)===n).reduce((q,f)=>q+f.aligned_bp,0);
   const h=Math.max(12,(H-40)*bp/tot-gap);m[n]={y,h,bp,cursor:y};y+=h+gap});return m};
 const L=lay(bins,0),R=lay(truths,1);
 let paths='';flows.sort((a2,b2)=>b2.aligned_bp-a2.aligned_bp).forEach((f,i)=>{
  const l=L[f.bin_id],r=R[f.true_plasmid];const lh=Math.max(2,l.h*f.aligned_bp/l.bp),rh=Math.max(2,r.h*f.aligned_bp/r.bp);
  const y1=l.cursor,y2=r.cursor;l.cursor+=lh;r.cursor+=rh;
  paths+=`<path class="lnk" data-i="${i}" fill="${f.status==='matched'?'#16805a':'#9a5a05'}" d="M150 ${y1} C 380 ${y1}, 380 ${y2}, 610 ${y2} L610 ${y2+rh} C 380 ${y2+rh}, 380 ${y1+lh}, 150 ${y1+lh} Z"><title>${f.bin_id} → ${f.true_plasmid}: ${f.aligned_bp.toLocaleString()} bp (${f.status})</title></path>`});
 const nodes=bins.map(n=>`<rect class="nd" x="140" y="${L[n].y}" width="10" height="${L[n].h}"/><text x="134" y="${L[n].y+12}" text-anchor="end">${n}</text>`).join('')
  +truths.map(n=>`<rect class="nd" x="610" y="${R[n].y}" width="10" height="${R[n].h}"/><text x="626" y="${R[n].y+12}">${n}</text>`).join('');
 host.innerHTML=`<h3>Bin-to-truth flow: ${t}</h3><p class="muted">Ribbon width is aligned bases. Left is predicted bins, right is truth plasmids. Amber ribbons are assignments the scorer did not accept as a one-to-one match. Only observed assignments are drawn.</p>`
  +`<svg viewBox="0 0 ${W} ${H+20}" role="img" aria-label="Bin to truth assignment flow">${paths}${nodes}</svg>`;
 const splits=truths.filter(n=>new Set(flows.filter(f=>f.true_plasmid===n).map(f=>f.bin_id)).size>1);
 const merges=bins.filter(n=>new Set(flows.filter(f=>f.bin_id===n).map(f=>f.true_plasmid)).size>1);
 detail.textContent=`${flows.length} assignment(s), ${total.toLocaleString()} aligned bp. `
  +(splits.length?`Split across bins: ${splits.join(', ')}. `:'')+(merges.length?`Bins spanning several truth plasmids: ${merges.join(', ')}.`:'')
  +(!splits.length&&!merges.length?'Every assignment is one-to-one.':'');
 host.querySelectorAll('.lnk').forEach(p=>p.onclick=()=>{
  host.querySelectorAll('.lnk').forEach(x=>x.classList.remove('on'));p.classList.add('on');
  const f=flows[+p.dataset.i];detail.textContent=`${f.bin_id} → ${f.true_plasmid}: ${f.aligned_bp.toLocaleString()} aligned bp, status ${f.status}.`;
  if([...$('vq-plasmid').options].some(o=>o.value===f.true_plasmid)){$('vq-plasmid').value=f.true_plasmid;$('vq-plasmid').dispatchEvent(new Event('change'))}})}
['vq-sample','vq-tool'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(render,0)));
render();})();
</script>"""


def agreement_and_comparison_script():
    """Per-region tool agreement, and a baseline-versus-comparator view.

    Agreement counts how many methods cover each reference interval. It is a
    support count, not a correctness claim: methods sharing a bias agree with
    each other and with nothing else, which the caption states plainly.
    """
    return """<style>
#vq-agree{margin:14px 0}
#vq-agree svg{max-width:100%;height:auto}
#vq-agree .lgd{display:flex;gap:14px;flex-wrap:wrap;font:11px Arial,sans-serif;color:#5f6d6b;margin-top:6px}
#vq-agree .lgd i{display:inline-block;width:12px;height:12px;margin-right:5px;vertical-align:-2px}
#vq-compare{margin:14px 0}
#vq-compare table{width:100%;border-collapse:collapse;font:12.5px Arial,sans-serif}
#vq-compare th{background:#edf2ec;text-align:left;padding:7px;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
#vq-compare td{border-top:1px solid #e3e9e8;padding:6px 8px;font-variant-numeric:tabular-nums}
#vq-compare .up{color:#17805a;font-weight:600}
#vq-compare .down{color:#b23b30;font-weight:600}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const agree=document.createElement('div');agree.id='vq-agree';
const comp=document.createElement('div');comp.id='vq-compare';
($('vq-summary')||$('vq-tracks')).before(agree);($('vq-tracks')).after(comp);
function ctx(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value;
 return a&&p&&a.truth_plasmids[p]?{a,p,len:a.truth_plasmids[p].length}:null}
function renderAgreement(){const c=ctx();if(!c){agree.innerHTML='';return}
 const names=Object.keys(c.a.tools),M=names.length;
 // Sweep the interval endpoints so every change in support becomes a boundary.
 const cuts=new Set([0,c.len]);
 names.forEach(n=>c.a.tools[n].blocks.filter(b=>b.target===c.p).forEach(b=>{
  cuts.add(Math.max(0,b.target_start));cuts.add(Math.min(c.len,b.target_end))}));
 const edges=[...cuts].sort((x,y)=>x-y);
 const bands=[];
 for(let i=0;i<edges.length-1;i++){const s=edges[i],e=edges[i+1];if(e<=s)continue;
  const mid=(s+e)/2;
  const supporters=names.filter(n=>c.a.tools[n].blocks.some(b=>b.target===c.p&&b.target_start<=mid&&b.target_end>=mid));
  bands.push({s,e,n:supporters.length,who:supporters})}
 if(!bands.length){agree.innerHTML='';return}
 const W=1100,L=180,PW=880,x=v=>L+v/c.len*PW;
 const shade=n=>n===0?'#eef1ee':['#dbeadf','#a9d3ba','#6fb894','#2f9068','#12664a'][Math.min(4,Math.max(0,Math.round((n/M)*4)))];
 const rects=bands.map((b,i)=>`<rect class="agr" data-i="${i}" x="${x(b.s).toFixed(1)}" y="16" width="${Math.max(1,x(b.e)-x(b.s)).toFixed(1)}" height="18" fill="${shade(b.n)}"><title>${b.s.toLocaleString()}-${b.e.toLocaleString()}: ${b.n}/${M} methods</title></rect>`).join('');
 const covered=bands.filter(b=>b.n===M).reduce((s,b)=>s+(b.e-b.s),0);
 agree.innerHTML=`<h3 style="font:600 13px Arial,sans-serif;margin:0 0 6px">Method agreement across ${c.p}</h3>`
  +`<svg viewBox="0 0 ${W} 44" role="img" aria-label="Number of methods covering each reference interval"><text x="4" y="29" font-size="12">${M} methods</text>${rects}</svg>`
  +`<div class="lgd"><span><i style="background:${shade(0)}"></i>0 of ${M}</span><span><i style="background:${shade(M)}"></i>${M} of ${M}</span>`
  +`<span>${(covered/c.len*100).toFixed(1)}% of the plasmid is supported by every method</span></div>`
  +`<p class="muted" style="font:11px Arial,sans-serif;margin:6px 0 0">Agreement is shared support, not evidence of correctness: methods can share a bias. Select a band to list the supporting methods.</p>`
  +`<div id="vq-agree-detail" class="muted" style="font:12px Arial,sans-serif"></div>`;
 agree.querySelectorAll('.agr').forEach(r=>r.onclick=()=>{const b=bands[+r.dataset.i];
  $('vq-agree-detail').textContent=`${b.s.toLocaleString()}-${b.e.toLocaleString()}: ${b.n}/${M} — ${b.who.join(', ')||'no method covers this interval'}`})}
function renderComparison(){const tools=[...new Set(d.matrix.map(r=>r.tool))].sort();
 if(tools.length<2){comp.innerHTML='';return}
 if(!$('vq-base')){comp.innerHTML=`<h3 style="font:600 13px Arial,sans-serif;margin:0 0 6px">Method comparison</h3>`
  +`<div style="display:flex;gap:10px;flex-wrap:wrap;font:12px Arial,sans-serif;margin-bottom:8px">`
  +`<label>Baseline <select id="vq-base">${tools.map(t=>`<option>${t}</option>`).join('')}</select></label>`
  +`<label>Comparator <select id="vq-comp">${tools.map((t,i)=>`<option${i===1?' selected':''}>${t}</option>`).join('')}</select></label></div>`
  +`<div id="vq-compare-body"></div>`;
  $('vq-base').onchange=renderComparison;$('vq-comp').onchange=renderComparison}
 const a=$('vq-base').value,b=$('vq-comp').value;
 const rows=[];[...new Set(d.matrix.map(r=>r.sample))].sort().forEach(s=>{
  const ra=d.matrix.find(r=>r.sample===s&&r.tool===a),rb=d.matrix.find(r=>r.sample===s&&r.tool===b);
  if(!ra||!rb||ra.f1==null||rb.f1==null)return;
  rows.push({s,a:ra,b:rb,d:rb.f1-ra.f1})});
 if(!rows.length){$('vq-compare-body').innerHTML='<p class="muted">No sample has a scored result for both methods.</p>';return}
 const mean=rows.reduce((x,r)=>x+r.d,0)/rows.length;
 const fmt=v=>v==null?'not measured':v.toFixed(3);
 const dcell=v=>`<span class="${v>0?'up':v<0?'down':''}">${v>0?'+':''}${v.toFixed(3)}</span>`;
 $('vq-compare-body').innerHTML=`<table><thead><tr><th>Sample</th><th>${a} F1</th><th>${b} F1</th><th>&Delta; F1</th><th>&Delta; contamination</th><th>&Delta; runtime (min)</th></tr></thead><tbody>`
  +rows.map(r=>`<tr><td>${r.s}</td><td>${fmt(r.a.f1)}</td><td>${fmt(r.b.f1)}</td><td>${dcell(r.d)}</td>`
   +`<td>${r.a.contamination==null||r.b.contamination==null?'not measured':dcell(r.b.contamination-r.a.contamination)}</td>`
   +`<td>${r.a.runtime_min==null||r.b.runtime_min==null?'not measured':dcell(r.b.runtime_min-r.a.runtime_min)}</td></tr>`).join('')
  +`</tbody></table><p class="muted" style="font:11px Arial,sans-serif;margin:6px 0 0">`
  +`${b} minus ${a} on ${rows.length} shared sample(s); mean &Delta; F1 ${mean>0?'+':''}${mean.toFixed(3)}. `
  +`Wins ${rows.filter(r=>r.d>0).length} / ties ${rows.filter(r=>r.d===0).length} / losses ${rows.filter(r=>r.d<0).length}. `
  +`A difference on few samples is not evidence of superiority; see the paired comparison table for interval and permutation evidence.</p>`}
['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(renderAgreement,0)));
renderAgreement();renderComparison();})();
</script>"""


def explorer_chrome_script():
    """Give the evidence explorer panel chrome: collapse, expand, zoom, stretch.

    The explorer grew as a flat stack of unlabelled panels emitted by several
    independent fragments. This wraps each one in a titled card without moving
    it out of the DOM position its fragment re-renders into, and adds a single
    toolbar for the controls those panels share.
    """
    return """<style>
#vq-shell{--pad:16px;margin:18px 0}
#vq-toolbar{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;gap:10px;align-items:center;
  background:#f3f6f4;border:1px solid #d3ddd6;border-radius:8px;padding:9px 13px;margin-bottom:14px;
  font:13px Arial,sans-serif;box-shadow:0 1px 3px rgba(22,33,28,.06)}
#vq-toolbar .grp{display:flex;gap:5px;align-items:center}
#vq-toolbar .sep{width:1px;height:22px;background:#d3ddd6}
#vq-toolbar label{color:#4a5a52;font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
#vq-toolbar button{font:12px Arial,sans-serif;padding:5px 10px;border:1px solid #c3cec7;background:#fff;
  border-radius:5px;cursor:pointer;color:#16211c;transition:background .15s,border-color .15s}
#vq-toolbar button:hover{background:#eaf2ec;border-color:#17805a}
#vq-toolbar button:focus-visible{outline:2px solid #12403a;outline-offset:2px}
#vq-toolbar input[type=range]{width:120px;accent-color:#17805a}
.vq-card{background:#fff;border:1px solid #d3ddd6;border-radius:8px;margin-bottom:14px;overflow:hidden;
  box-shadow:0 1px 3px rgba(22,33,28,.05)}
.vq-card>header{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#f7faf8;
  border-bottom:1px solid #e3e9e8;cursor:pointer;user-select:none}
.vq-card>header:focus-visible{outline:2px solid #12403a;outline-offset:-2px}
.vq-card>header h3{margin:0;font:600 13px Arial,sans-serif;color:#16211c;flex:none}
.vq-card>header .hint{font:11px Arial,sans-serif;color:#7b8a83;flex:1}
.vq-card>header .chev{transition:transform .18s;color:#4a5a52;font-size:10px}
.vq-card.collapsed>header .chev{transform:rotate(-90deg)}
.vq-card.collapsed>.vq-body{display:none}
.vq-card>header button{font:11px Arial,sans-serif;padding:3px 9px;border:1px solid #c3cec7;background:#fff;
  border-radius:4px;cursor:pointer;color:#16211c}
.vq-card>header button:hover{background:#eaf2ec;border-color:#17805a}
.vq-body{padding:var(--pad);overflow:auto}
.vq-card.expanded{position:fixed;inset:16px;z-index:60;margin:0;display:flex;flex-direction:column;
  box-shadow:0 24px 60px rgba(22,33,28,.35)}
.vq-card.expanded>.vq-body{flex:1;min-height:0}
#vq-scrim{position:fixed;inset:0;background:rgba(18,28,23,.5);z-index:55;display:none}
#vq-scrim.on{display:block}
#vq-tracks svg,#vq-agree svg,#vq-sankey svg{width:100%;height:auto}
.vq-kv{border-collapse:collapse;margin:8px 0 14px;font:13px Arial,sans-serif;width:100%;max-width:620px}
.vq-kv th{text-align:left;font-weight:600;color:#4a5a52;padding:5px 14px 5px 0;white-space:nowrap;
  vertical-align:top;width:1%;border-bottom:1px solid #eef2f0}
.vq-kv td{padding:5px 0;color:#16211c;border-bottom:1px solid #eef2f0;font-variant-numeric:tabular-nums}
#vq-detail code{display:block;white-space:pre;overflow-x:auto;background:#f5f8f6;border:1px solid #e3e9e8;
  border-radius:5px;padding:10px 12px;margin:6px 0;font:12px/1.5 'IBM Plex Mono',ui-monospace,Menlo,monospace}
@media (prefers-reduced-motion:reduce){.vq-card>header .chev{transition:none}}
</style><script>
(()=>{const $=id=>document.getElementById(id);
if(!$('vq-tracks'))return;
// One card per panel. Panels are moved into a card body but keep their ids, so
// the fragments that own them go on re-rendering into the same element.
const PANELS=[['vq-summary','Truth plasmids','one row per truth plasmid for the selected method'],
 ['vq-nav','Navigation and search','find a gene, coordinate range or contig id'],
 ['vq-tracks','Alignment tracks','predicted records on truth-reference coordinates'],
 ['vq-detail','Selected block','alignment evidence for the block you clicked'],
 ['vq-agree','Method agreement','how many methods support each reference interval'],
 ['vq-sankey','Bin-to-truth flow','which predicted bin carries which truth plasmid'],
 ['vq-flow','Bin assignments','scored bin membership'],
 ['vq-compare','Method comparison','baseline against comparator on shared samples'],
 ['vq-dotplot','Dot plot','reference against predicted-record coordinates'],
 ['vq-context','Context and circular view','curated features and circular truth'],
 ['vq-proteins','Protein recovery','coordinate recovery of named coding sequences'],
 ['vq-structural','Structural diagnostics','alignment-derived discordance']];
const shell=document.createElement('div');shell.id='vq-shell';
const first=$('vq-summary')||$('vq-nav')||$('vq-tracks');
first.parentElement.insertBefore(shell,first);
const bar=document.createElement('div');bar.id='vq-toolbar';
bar.innerHTML='<span class="grp"><label>View</label>'
 +'<button id="vq-expand-all" type="button">Expand all</button>'
 +'<button id="vq-collapse-all" type="button">Collapse all</button></span>'
 +'<span class="sep"></span>'
 +'<span class="grp"><label>Zoom</label>'
 +'<button id="vq-tb-out" type="button" title="Zoom out">\u2212</button>'
 +'<button id="vq-tb-in" type="button" title="Zoom in">+</button>'
 +'<button id="vq-tb-fit" type="button" title="Fit the whole plasmid">Fit</button></span>'
 +'<span class="sep"></span>'
 +'<span class="grp"><label for="vq-stretch">Track height</label>'
 +'<input id="vq-stretch" type="range" min="140" max="760" step="20" value="340"></span>'
 +'<span class="sep"></span>'
 +'<span class="grp"><label for="vq-density">Density</label>'
 +'<input id="vq-density" type="range" min="6" max="28" step="2" value="16" title="Padding inside each card"></span>'
 +'<span class="grp" style="margin-left:auto;color:#7b8a83;font-size:11px">Select a card title to collapse it</span>';
shell.append(bar);
const scrim=document.createElement('div');scrim.id='vq-scrim';document.body.append(scrim);
function card(id,title,hint){const el=$(id);if(!el)return null;
 const box=document.createElement('section');box.className='vq-card';
 box.innerHTML='<header tabindex="0" role="button" aria-expanded="true">'
  +'<span class="chev">\u25BC</span><h3>'+title+'</h3><span class="hint">'+hint+'</span>'
  +'<button type="button" class="exp">Expand</button></header><div class="vq-body"></div>';
 shell.append(box);
 box.querySelector('.vq-body').append(el);
 const head=box.querySelector('header'),btn=box.querySelector('.exp');
 function toggle(){const collapsed=box.classList.toggle('collapsed');
  head.setAttribute('aria-expanded',String(!collapsed))}
 head.addEventListener('click',e=>{if(e.target!==btn)toggle()});
 head.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle()}});
 btn.addEventListener('click',()=>{const on=box.classList.toggle('expanded');
  scrim.classList.toggle('on',on);btn.textContent=on?'Close':'Expand';
  if(on)box.scrollIntoView({block:'nearest'})});
 return box}
const cards=PANELS.map(entry=>card(entry[0],entry[1],entry[2])).filter(Boolean);
scrim.addEventListener('click',()=>{cards.forEach(c=>{c.classList.remove('expanded');
 const b=c.querySelector('.exp');if(b)b.textContent='Expand'});scrim.classList.remove('on')});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&scrim.classList.contains('on'))scrim.click()});
$('vq-expand-all').onclick=()=>cards.forEach(c=>{c.classList.remove('collapsed');
 c.querySelector('header').setAttribute('aria-expanded','true')});
$('vq-collapse-all').onclick=()=>cards.forEach(c=>{c.classList.add('collapsed');
 c.querySelector('header').setAttribute('aria-expanded','false')});
// The toolbar drives the explorer's own controls rather than duplicating them.
$('vq-tb-in').onclick=()=>$('vq-in')&&$('vq-in').click();
$('vq-tb-out').onclick=()=>$('vq-out')&&$('vq-out').click();
$('vq-tb-fit').onclick=()=>$('vq-fit')&&$('vq-fit').click();
// Stretch: taller tracks when several methods are shown, shorter when comparing.
$('vq-stretch').addEventListener('input',e=>{const tracks=$('vq-tracks');
 if(tracks){tracks.style.maxHeight=e.target.value+'px';tracks.style.overflowY='auto'}});
$('vq-stretch').dispatchEvent(new Event('input'));
$('vq-density').addEventListener('input',e=>{shell.style.setProperty('--pad',e.target.value+'px')});
})();
</script>"""


def explorer_navigation_script():
    """Search, row management, drag navigation, and event-to-event jumping."""
    return """<style>
#vq-nav{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:12px 0}
#vq-nav .grp{display:flex;gap:6px;align-items:end}
#vq-rows{display:flex;flex-wrap:wrap;gap:10px;font:12px Arial,sans-serif;margin:8px 0}
#vq-rows label{display:flex;gap:4px;align-items:center;border:1px solid #d2dad8;padding:3px 7px;background:#fff}
#vq-rows label.solo{outline:2px solid #12403a}
#vq-tracks svg{cursor:grab}
#vq-tracks svg.dragging{cursor:grabbing}
#vq-hits{font:12px Arial,sans-serif;color:#5f6d6b}
#vq-hits ul{margin:4px 0 0;padding-left:18px}
#vq-hits button{font:11px Arial,sans-serif;margin-left:6px}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const nav=document.createElement('div');nav.id='vq-nav';
nav.innerHTML=`<label>Find <input id="vq-q" type="search" placeholder="gene, contig, or 1200-3400" size="26"></label>`
 +`<span class="grp"><button id="vq-bed" type="button" title="Download the visible interval as BED">Export BED</button></span>`
 +`<span class="grp"><button id="vq-prev-ev" type="button">\\u2190 Event</button><button id="vq-next-ev" type="button">Event \\u2192</button></span>`
 +`<span class="grp"><button id="vq-prev-p" type="button">\\u2190 Plasmid</button><button id="vq-next-p" type="button">Plasmid \\u2192</button></span>`
 +`<span class="grp"><button id="vq-back" type="button">Back</button></span>`;
$('vq-tracks').before(nav);
const rows=document.createElement('div');rows.id='vq-rows';nav.after(rows);
const hits=document.createElement('div');hits.id='vq-hits';rows.after(hits);
const hidden=new Set();let solo=null,history=[],cursor=null;
function ctx(){const a=d.visualizations[$('vq-sample').value];const p=$('vq-plasmid').value;
 return a&&p?{a,p,len:a.truth_plasmids[p]?.length||0}:null}
function setRange(lo,hi){const c=ctx();if(!c)return;
 lo=Math.max(0,Math.floor(lo));hi=Math.min(c.len,Math.ceil(hi));if(hi-lo<20)hi=Math.min(c.len,lo+20);
 history.push([$('vq-start').value,$('vq-end').value]);
 $('vq-start').value=lo;$('vq-end').value=hi;$('vq-start').dispatchEvent(new Event('change'))}
// --- row management -------------------------------------------------------
function renderRows(){const c=ctx();if(!c){rows.innerHTML='';return}
 const names=Object.keys(c.a.tools);
 rows.innerHTML='<strong style="font:12px Arial,sans-serif">Tool rows</strong>'+names.map(n=>
  `<label class="${solo===n?'solo':''}"><input type="checkbox" data-n="${n}" ${hidden.has(n)?'':'checked'}> ${n}`
  +` <button type="button" data-solo="${n}">${solo===n?'all':'only'}</button></label>`).join('');
 rows.querySelectorAll('input').forEach(i=>i.onchange=()=>{i.checked?hidden.delete(i.dataset.n):hidden.add(i.dataset.n);solo=null;apply()});
 rows.querySelectorAll('button[data-solo]').forEach(b=>b.onclick=()=>{
  const n=b.dataset.solo;if(solo===n){solo=null;hidden.clear()}else{solo=n;hidden.clear();Object.keys(c.a.tools).forEach(x=>{if(x!==n)hidden.add(x)})}
  renderRows();apply()})}
function apply(){
 // The base view draws one <text> label plus one lane per tool; hide by label.
 const svg=$('vq-tracks').querySelector('svg');if(!svg)return;
 svg.querySelectorAll('text').forEach(t=>{if(hidden.has(t.textContent.trim()))t.style.opacity=.25});
 svg.querySelectorAll('.vq-block').forEach(b=>{b.style.display=hidden.has(b.dataset.n)?'none':''})}
// --- search ---------------------------------------------------------------
function search(){const c=ctx();const q=$('vq-q').value.trim();if(!c||!q){hits.innerHTML='';return}
 const coord=q.match(/^(\\d[\\d,]*)\\s*[-:.]+\\s*(\\d[\\d,]*)$/);
 if(coord){setRange(+coord[1].replace(/,/g,''),+coord[2].replace(/,/g,''));hits.innerHTML='<em>Jumped to coordinate range.</em>';return}
 const needle=q.toLowerCase(),found=[];
 (c.a.amr_features||[]).concat(c.a.context_features||[]).forEach(f=>{
  if(f.sequence_id===c.p&&String(f.label||'').toLowerCase().includes(needle))
   found.push({what:(f.feature_type||'AMR')+': '+f.label,lo:f.start,hi:f.end})});
 Object.entries(c.a.tools).forEach(([n,t])=>t.blocks.forEach(b=>{
  if(b.target===c.p&&b.record_id.toLowerCase().includes(needle))
   found.push({what:n+' record '+b.record_id,lo:b.target_start,hi:b.target_end})}));
 hits.innerHTML=found.length?'<strong>'+found.length+' match(es)</strong><ul>'+found.slice(0,25).map((f,i)=>
   `<li>${f.what} — ${f.lo.toLocaleString()}\\u2013${f.hi.toLocaleString()}<button type="button" data-i="${i}">go</button></li>`).join('')+'</ul>'
  :'<em>No gene, feature, or record matched on this plasmid.</em>';
 hits.querySelectorAll('button[data-i]').forEach(b=>b.onclick=()=>{const f=found[+b.dataset.i];
  const pad=Math.max(50,(f.hi-f.lo));setRange(f.lo-pad,f.hi+pad)})}
$('vq-q').addEventListener('change',search);
$('vq-q').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();search()}});
// --- event jumping --------------------------------------------------------
function events(){const c=ctx();if(!c)return[];const list=[];
 Object.entries(c.a.tools).forEach(([n,t])=>{if(hidden.has(n))return;
  const bs=t.blocks.filter(b=>b.target===c.p).sort((x,y)=>x.target_start-y.target_start);
  bs.forEach((b,i)=>{
   if(b.strand==='-')list.push({at:b.target_start,why:n+': reverse-orientation block'});
   // A gap between consecutive blocks on the same reference is a breakpoint.
   if(i&&b.target_start>bs[i-1].target_end)list.push({at:bs[i-1].target_end,why:n+': breakpoint gap'});
   const a=b.local_alignment;
   if(a){let off=0;for(let k=0;k<a.reference.length;k++){if(a.reference[k]!=='-')off++;
     if(a.reference[k]!==a.prediction[k]){list.push({at:b.target_start+off,why:n+': mismatch or gap'});break}}}})});
 return list.sort((x,y)=>x.at-y.at)}
function jump(dir){const c=ctx();if(!c)return;const list=events();if(!list.length){hits.innerHTML='<em>No orientation, breakpoint, or mismatch event on this plasmid.</em>';return}
 // Walk from the last visited event, not the window midpoint: fitting the whole
 // plasmid would otherwise skip every event in the left half.
 const lo=Number($('vq-start').value),hi=Number($('vq-end').value);
 const from=cursor!=null?cursor:(dir>0?lo-1:hi+1);
 let next=dir>0?list.find(e=>e.at>from):[...list].reverse().find(e=>e.at<from);
 if(!next){next=dir>0?list[0]:list[list.length-1];
  hits.innerHTML='<em>Wrapped to the '+(dir>0?'first':'last')+' event. </em>'}
 else hits.innerHTML='';
 cursor=next.at;
 const span=Math.max(400,hi-lo);
 setRange(next.at-span/2,next.at+span/2);
 hits.innerHTML+='<em>'+next.why+' near '+next.at.toLocaleString()+'</em>'}
$('vq-next-ev').onclick=()=>jump(1);$('vq-prev-ev').onclick=()=>jump(-1);
function stepPlasmid(dir){const sel=$('vq-plasmid'),i=sel.selectedIndex+dir;
 if(i>=0&&i<sel.options.length){sel.selectedIndex=i;sel.dispatchEvent(new Event('change'))}}
$('vq-next-p').onclick=()=>stepPlasmid(1);$('vq-prev-p').onclick=()=>stepPlasmid(-1);
$('vq-back').onclick=()=>{const prev=history.pop();if(!prev)return;
 $('vq-start').value=prev[0];$('vq-end').value=prev[1];$('vq-start').dispatchEvent(new Event('change'))};
// --- drag to pan, drag ruler to select ------------------------------------
function bindDrag(){const svg=$('vq-tracks').querySelector('svg');if(!svg||svg.dataset.drag)return;svg.dataset.drag='1';
 const LEFT=180,W=880;let anchor=null;
 const at=e=>{const r=svg.getBoundingClientRect();const c=ctx();if(!c)return null;
  const x=(e.clientX-r.left)*(1100/r.width);const lo=Number($('vq-start').value),hi=Number($('vq-end').value);
  return lo+Math.min(1,Math.max(0,(x-LEFT)/W))*(hi-lo)};
 svg.addEventListener('pointerdown',e=>{const v=at(e);if(v===null)return;
  anchor={v,y:e.clientY,ruler:e.offsetY<26,moved:false};svg.setPointerCapture(e.pointerId);svg.classList.add('dragging')});
 svg.addEventListener('pointermove',e=>{if(!anchor)return;const v=at(e);if(v===null)return;
  anchor.moved=true;
  if(!anchor.ruler){const lo=Number($('vq-start').value),hi=Number($('vq-end').value),shift=anchor.v-v;
   if(Math.abs(shift)>(hi-lo)/200){$('vq-start').value=Math.round(lo+shift);$('vq-end').value=Math.round(hi+shift);
    $('vq-start').dispatchEvent(new Event('change'));anchor.v=v}}});
 svg.addEventListener('pointerup',e=>{if(!anchor){return}const v=at(e);svg.classList.remove('dragging');
  if(anchor.ruler&&anchor.moved&&v!==null&&Math.abs(v-anchor.v)>10)setRange(Math.min(anchor.v,v),Math.max(anchor.v,v));
  anchor=null});
 svg.addEventListener('pointercancel',()=>{anchor=null;svg.classList.remove('dragging')})}
function refresh(){renderRows();apply();bindDrag()}
['vq-sample','vq-plasmid'].forEach(id=>$(id)?.addEventListener('change',()=>{cursor=null}));
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(refresh,0)));
['vq-fit','vq-in','vq-out'].forEach(id=>$(id)?.addEventListener('click',()=>setTimeout(refresh,0)));
document.addEventListener('keydown',e=>{if(e.target?.matches?.('input,select,textarea'))return;
 if(e.key==='n'){jump(1)}else if(e.key==='p'){jump(-1)}});
// BED of the visible window. Reference coordinates are already 0-based
// half-open, which is exactly what BED expects, so nothing is converted.
$('vq-bed').onclick=()=>{const c=ctx();if(!c)return;
 const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||c.len;
 const lines=['track name="PlasBench '+c.p+'" description="visible predicted blocks"'];
 Object.entries(c.a.tools).forEach(([n,t])=>{if(hidden.has(n))return;
  t.blocks.filter(b=>b.target===c.p&&b.target_end>lo&&b.target_start<hi).forEach(b=>{
   lines.push([c.p,Math.max(lo,b.target_start),Math.min(hi,b.target_end),
               n+':'+b.record_id,b.mapq,b.strand].join('\\t'))})});
 const blob=new Blob([lines.join('\\n')+'\\n'],{type:'text/plain'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download=c.p+'_'+Math.round(lo)+'-'+Math.round(hi)+'.bed';a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),0)};
// Keyboard reach for the tracks, not only the matrix.
const tk=$('vq-tracks');
tk.setAttribute('tabindex','0');tk.setAttribute('role','group');
tk.setAttribute('aria-label','Predicted alignment tracks. Arrow keys pan, plus and minus zoom, Home fits the plasmid, n and p step between events.');
tk.addEventListener('keydown',e=>{const c=ctx();if(!c)return;
 const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||c.len,span=hi-lo;
 const K={ArrowLeft:()=>setRange(lo-span*0.25,hi-span*0.25),
          ArrowRight:()=>setRange(lo+span*0.25,hi+span*0.25),
          '+':()=>setRange(lo+span*0.25,hi-span*0.25),
          '=':()=>setRange(lo+span*0.25,hi-span*0.25),
          '-':()=>setRange(lo-span*0.5,hi+span*0.5),
          Home:()=>$('vq-fit').click(),
          n:()=>jump(1),p:()=>jump(-1)};
 if(K[e.key]){e.preventDefault();K[e.key]()}});
refresh();})();
</script>"""


def evidence_explorer_section(project_root, scores, results_dir, vendor_html):
    """Embed the vendored reconstruction evidence explorer.

    Like the cohort dashboard, the design ships as a whole document that styles
    bare ``*`` and ``body``, so it runs in an isolated frame. Selection changes
    in this report are forwarded to it by postMessage.
    """
    template = Path(project_root) / "assets" / "explorer" / "template.html"
    if not template.is_file():
        return ""
    try:
        import build_explorer_view as explorer
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_explorer_view as explorer

    visualizations, structural = {}, {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if path.is_file():
            try:
                visualizations[sample] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        calls = results_dir / sample / "visualization" / "structural_calls.json"
        if calls.is_file():
            try:
                structural[sample] = json.loads(calls.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    if not visualizations:
        return ""

    versions = read_tool_versions(results_dir / "run_manifest.json")
    data = explorer.build(visualizations, structural, versions)
    if not data["samples"]:
        return ""
    document = explorer.render(template, data, vendor_html)
    encoded = document.replace("</script", "<\\/script")
    # The report's own sample and plasmid controls drive the frame, so one
    # selection is followed everywhere instead of being re-picked inside it.
    return ("<div id='pb-explorer-view'><h3>Reconstruction evidence explorer</h3>"
            "<p class='lead'>Alignment blocks, structural calls, bin relationships and reference "
            "annotation for one truth plasmid at a time. Identity, mapping quality and every span are "
            "measured from this run. Read depth is not computed by projection scoring, so per-segment "
            "coverage reads “not measured” rather than zero, and the nucleotide view resolves only "
            "where a CIGAR-bounded local alignment exists.</p>"
            "<div class='panel' style='padding:0'><iframe id='pb-explorer' "
            "title='PlasBench reconstruction evidence explorer' "
            "style='width:100%;height:1180px;border:0;display:block'></iframe></div>"
            f"<script id='pb-explorer-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-explorer');"
            "const raw=document.getElementById('pb-explorer-doc').textContent;"
            "f.srcdoc=raw.split('<\\\\/script').join('</scr'+'ipt');"
            "const push=()=>{const s=document.getElementById('vq-sample'),"
            "p=document.getElementById('vq-plasmid');if(!f.contentWindow)return;"
            "f.contentWindow.postMessage({pbExplorer:'select',"
            "sample:s?s.value:null,plasmid:p?p.value:null},'*')};"
            # The explorer is emitted above the controls it follows, so the
            # listener is delegated rather than bound to elements that do not
            # exist yet when this runs.
            "document.addEventListener('change',e=>{"
            "if(e.target&&(e.target.id==='vq-sample'||e.target.id==='vq-plasmid'))"
            "setTimeout(push,60)},true);"
            "f.addEventListener('load',()=>setTimeout(push,150));})();</script></div>")


def enterprise_view_section(project_root, scores, status, leaderboard, metadata,
                            results_dir, vendor_html, evidence_html=""):
    """Embed the vendored enterprise dashboard, driven by measured results.

    The dashboard is rendered inside an isolated iframe. Its stylesheet styles
    bare `*` and `body`, so inlining it into this page would restyle the whole
    report; the iframe keeps the adopted look byte-for-byte without leaking.
    """
    template = Path(project_root) / "assets" / "enterprise" / "template.html"
    if not template.is_file():
        return ""
    try:
        import build_enterprise_view as enterprise
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_enterprise_view as enterprise

    visualizations = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if path.is_file():
            try:
                visualizations[sample] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    structural = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "structural_summary.tsv"
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    value = row.get("collinear_fraction")
                    structural[(sample, row.get("tool"))] = float(value) if value else None
        except (OSError, ValueError):
            continue
    capabilities = {}
    registry = Path(project_root) / "config" / "tool_capabilities.tsv"
    if registry.is_file():
        with registry.open(encoding="utf-8", newline="") as handle:
            capabilities = {row["tool"]: row for row in csv.DictReader(handle, delimiter="\t")}
    versions = read_tool_versions(results_dir / "run_manifest.json")

    manifest_version = "version not recorded"
    manifest_path = results_dir / "run_manifest.json"
    if manifest_path.is_file():
        try:
            manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "tool_version", manifest_version)
        except (OSError, json.JSONDecodeError):
            pass
    data = enterprise.build(scores, status, leaderboard, metadata, capabilities,
                            versions, visualizations, structural, manifest_version)
    document = enterprise.render(template, data, vendor_html)
    # The iframe is written from a template script tag rather than srcdoc so the
    # document needs no HTML-entity escaping of its own markup.
    # Escape only what would close the outer template tag; the frame script
    # restores it before handing the document to srcdoc.
    encoded = document.replace("</script", "<\\/script")
    return ("<section id='enterprise'><h2>Interactive cohort dashboard</h2>"
            "<p class='lead'>The adopted enterprise dashboard, driven entirely by this run's measured "
            "results. Values that were never measured render as “not measured” rather than as zero. "
            "It runs in an isolated frame so its own stylesheet cannot restyle this report.</p>"
            "<div class='panel' style='padding:0'><iframe id='pb-enterprise' title='PlasBench interactive cohort dashboard' "
            "style='width:100%;height:1240px;border:0;display:block'></iframe></div>"
            f"<script id='pb-enterprise-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-enterprise');"
            "const raw=document.getElementById('pb-enterprise-doc').textContent;"
            "f.srcdoc=raw.split('<\\\\/script').join('</scr'+'ipt');})();</script>"
            + evidence_html + "</section>")


def vendor_assets(project_root):
    """Inline the vendored font and icon assets as base64.

    The report must render identically offline and years later, so it carries
    its own faces rather than requesting a CDN at view time. A missing vendor
    directory degrades to system fonts instead of failing the build.
    """
    vendor = Path(project_root) / "assets" / "vendor"
    fonts = vendor / "fonts"
    inter_css, icon_css = vendor / "inter.css", vendor / "fontawesome-subset.css"
    if not (inter_css.is_file() and icon_css.is_file()):
        return ("<style>/* Vendored web fonts absent; falling back to system faces. "
                "Run assets/vendor setup to restore the packaged appearance. */</style>")

    def data_uri(name):
        path = fonts / name
        if not path.is_file():
            return None
        return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    inter = inter_css.read_text(encoding="utf-8")
    inter_uri = data_uri("inter-variable.woff2")
    if inter_uri:
        inter = re.sub(r"url\(fonts/inter-[^)]+\)", f"url({inter_uri})", inter)
    icons = icon_css.read_text(encoding="utf-8")
    icon_uri = data_uri("fa-solid-900.woff2")
    icons = icons.replace("__FA_WOFF2__", icon_uri) if icon_uri else ""
    return f"<style>\n{inter}\n{icons}\n</style>"


def lazy_visualization_script():
    """Fetch per-sample alignment payloads on demand when they were published.

    Loading every sample up front is what makes a large cohort report unusable,
    so external mode resolves one sample at a time and caches it. A file:// open
    cannot fetch siblings, so that failure is reported as an instruction rather
    than as missing data.
    """
    return """<style>
#vq-loading{font:12px Arial,sans-serif;color:#5f6d6b;margin:6px 0}
#vq-loading.busy::before{content:'\\u25CF ';color:#c68221}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const sources=d.visualization_sources||{},staging=d.staging||{};
if(!Object.keys(sources).length)return;                    // inline mode: nothing to do
const note=document.createElement('div');note.id='vq-loading';$('vq-tracks').before(note);
note.textContent=`Alignment detail is published per sample (${staging.samples} file(s), ${(staging.bytes/1048576).toFixed(1)} MB total) and loads on selection.`;
const cache=new Map();let token=0;
async function load(sample){
 if(d.visualizations[sample])return d.visualizations[sample];
 if(cache.has(sample))return cache.get(sample);
 const url=sources[sample];if(!url)return null;
 const mine=++token;note.className='busy';note.textContent=`Loading alignment detail for ${sample}\\u2026`;
 try{const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);
  const payload=await r.json();cache.set(sample,payload);d.visualizations[sample]=payload;
  if(mine===token){note.className='';note.textContent=`Loaded ${sample}. Detail for other samples loads on selection.`}
  return payload}
 catch(err){if(mine===token){note.className='';
   note.innerHTML='Could not load <code>'+url+'</code>. A report opened directly from the file system cannot read sibling files. Serve the report directory instead, for example <code>python -m http.server</code> in the results folder, then reload over http://localhost:8000.'}
  return null}}
// Re-dispatch the selection once data has arrived so the existing views redraw.
async function ensure(){const s=$('vq-sample').value;if(!s||d.visualizations[s])return;
 const payload=await load(s);if(payload){$('vq-sample').dispatchEvent(new Event('change'))}}
$('vq-sample').addEventListener('change',()=>{setTimeout(ensure,0)},true);
ensure();})();
</script>"""


def plasmid_summary_script():
    """Add a per-truth-plasmid summary table and surface contamination on tracks.

    The base track view filters blocks to the selected plasmid, so a predicted
    record that is partly chromosomal renders identically to a clean one. This
    flags those records instead of leaving the contamination invisible.
    """
    return """<style>
.vq-block.vq-impure{stroke:#a53028;stroke-width:2;stroke-dasharray:3 2}
#vq-summary table{width:100%;border-collapse:collapse;font:13px Arial,sans-serif}
#vq-summary th{background:#edf2ec;text-align:left;padding:8px;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
#vq-summary td{border-top:1px solid #d2dad8;padding:7px 8px;white-space:nowrap}
#vq-summary tr.sel td{background:#eef5ee;font-weight:bold}
#vq-summary tbody tr{cursor:pointer}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const host=document.createElement('div');host.id='vq-summary';$('vq-tracks').before(host);
// Thresholds are display bands for triage, not acceptance criteria; they mirror
// the recovery threshold documented in the scoring method.
function classify(c,records,impure){if(impure&&c>=.9)return'Complete, contaminated record';
 if(c>=.99)return'Complete';if(c>=.9)return'Near complete';if(c>=.5)return records>2?'Partial, fragmented':'Partial';
 if(c>0)return'Minimal';return'Not recovered'}
function render(){const a=d.visualizations[$('vq-sample').value],t=$('vq-tool').value;
 if(!a||!a.tools[t]){host.innerHTML='';return}
 const tool=a.tools[t],circ=new Set(a.circular_truth_plasmids||[]);
 // A record that also aligns to the chromosome or to another truth plasmid is
 // evidence of contamination or a merge, even where this plasmid looks complete.
 const elsewhere={};tool.blocks.forEach(b=>{(elsewhere[b.record_id]??=new Set()).add(b.molecule_type==='CHROMOSOME'?'chromosome':b.target)});
 const rows=Object.entries(a.truth_plasmids).map(([id,info])=>{
  const rec=tool.plasmid_recovery[id]||{completeness:0};
  const records=[...new Set(tool.blocks.filter(b=>b.target===id).map(b=>b.record_id))];
  const impure=records.filter(r=>[...elsewhere[r]].some(x=>x!==id));
  return {id,len:info.length,circular:circ.has(id),c:rec.completeness||0,n:records.length,impure};});
 rows.sort((x,y)=>y.c-x.c);
 host.innerHTML='<h3>Truth plasmids for '+t+'</h3><p class="muted">One row per truth plasmid. “Impure records” are predicted records that also align to the chromosome or another truth plasmid; completeness alone cannot reveal them. Select a row to load its tracks.</p>'
  +'<div class="panel"><table><thead><tr><th>Truth plasmid</th><th>Length</th><th>Circular truth</th><th>Completeness</th><th>Contributing records</th><th>Impure records</th><th>Classification</th></tr></thead><tbody>'
  +rows.map(r=>`<tr data-p="${r.id}" class="${r.id===$('vq-plasmid').value?'sel':''}"><td>${r.id}</td><td>${r.len.toLocaleString()} bp</td><td>${r.circular?'yes':'not declared'}</td><td>${(r.c*100).toFixed(1)}%</td><td>${r.n}</td><td>${r.impure.length||'0'}</td><td>${classify(r.c,r.n,r.impure.length>0)}</td></tr>`).join('')
  +'</tbody></table></div>';
 const bad=rows.filter(r=>r.impure.length&&r.c>=.9);
 if(bad.length)host.insertAdjacentHTML('beforeend','<div class="vq-warn"><strong>High completeness with impure records:</strong> '+bad.map(r=>r.id).join(', ')+'. High recovery does not imply a clean reconstruction.</div>');
 // Contamination usually arrives as a whole chromosomal record called plasmid,
 // which no per-plasmid row can show. Report it against the tool instead.
 const chrRecords=[...new Set(tool.blocks.filter(b=>b.molecule_type==='CHROMOSOME').map(b=>b.record_id))];
 const chrBp=tool.chromosome_aligned_bp||0;
 if(chrRecords.length)host.insertAdjacentHTML('beforeend','<div class="vq-warn"><strong>Chromosomal contamination for '+t+':</strong> '
  +chrBp.toLocaleString()+' bp across '+chrRecords.length+' predicted record(s) — '+chrRecords.join(', ')
  +'. These are counted as false positives and are not attributable to any truth plasmid, so they do not appear in the rows above.</div>');
 const mean=rows.length?rows.reduce((s,r)=>s+r.c,0)/rows.length:0;
 if(!chrRecords.length&&!bad.length&&rows.length)host.insertAdjacentHTML('beforeend',
  '<p class="muted">No chromosomal or cross-plasmid record contamination among retained blocks (mean completeness '+(mean*100).toFixed(1)+'%).</p>');
 host.querySelectorAll('tbody tr').forEach(tr=>tr.onclick=()=>{$('vq-plasmid').value=tr.dataset.p;$('vq-plasmid').dispatchEvent(new Event('change'))});
 markTracks(tool,elsewhere)}
function markTracks(tool,elsewhere){const p=$('vq-plasmid').value;
 document.querySelectorAll('#vq-tracks .vq-block').forEach(el=>{
  const name=el.dataset.n;if(!name||!d.visualizations[$('vq-sample').value]?.tools[name])return;
  const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||Infinity;
  const list=d.visualizations[$('vq-sample').value].tools[name].blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi);
  const b=list[Number(el.dataset.i)];if(!b)return;
  const others=[...(elsewhere[b.record_id]||[])].filter(x=>x!==p);
  if(others.length){el.classList.add('vq-impure');
   const title=el.querySelector('title');if(title)title.textContent=b.record_id+' — also aligns to '+others.join(', ')}})}
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(render,0)));
['vq-fit','vq-in','vq-out'].forEach(id=>$(id)?.addEventListener('click',()=>setTimeout(render,0)));
render();})();
</script>"""


def context_visual_script():
    """Render supplied contextual annotations and a truth-scoped circular map."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),host=document.createElement('div');host.id='vq-context';$('vq-dotplot').after(host);
function render(){let a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t]){host.innerHTML='';return}let features=(a.context_features||[]).filter(f=>f.sequence_id===p),types={};features.forEach(f=>(types[f.feature_type]??=[]).push(f));let html='<h3>Context and circular-truth view</h3>';if(a.circular_truth_plasmids?.includes(p)){let len=a.truth_plasmids[p].length,intervals=a.tools[t].plasmid_recovery[p]?.covered_intervals||[],arc=(s,e)=>{let A=s/len*2*Math.PI-Math.PI/2,B=e/len*2*Math.PI-Math.PI/2,x1=120+80*Math.cos(A),y1=100+80*Math.sin(A),x2=120+80*Math.cos(B),y2=100+80*Math.sin(B),large=B-A>Math.PI?1:0;return `<path d="M${x1} ${y1} A80 80 0 ${large} 1 ${x2} ${y2}" fill="none" stroke="#16805a" stroke-width="14"/>`};html+='<p class="muted">Circular truth plasmid only. Green arcs are recovered reference intervals; this does not claim the predicted output is circular or closed.</p><svg viewBox="0 0 240 200" width="240"><circle cx="120" cy="100" r="80" fill="none" stroke="#e2e8e2" stroke-width="14"/>'+intervals.map(x=>arc(x[0],x[1])).join('')+'<text x="75" y="104" font-size="11">truth circular</text></svg>'}if(features.length){html+='<p><strong>Curated contextual features</strong></p><ul>'+Object.entries(types).map(([k,v])=>`<li>${k}: ${v.map(f=>`${f.label} (${f.start}-${f.end}; ${f.source} ${f.version})`).join(', ')}</li>`).join('')+'</ul>'}else html+='<p class="muted">No versioned replicon, MOB, insertion-sequence, or AMR-context feature table was supplied.</p>';host.innerHTML=html}['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));render()})();
</script>"""


def record_dotplot_script():
    """Use one predicted-record coordinate system per dot plot."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),select=document.createElement('select'),label=document.createElement('label');label.textContent='Predicted record ';label.append(select);$('vq-tool').closest('label').after(label);
function state(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;return a&&a.tools[t]?{a,p,t}:null}
function render(){const x=state();if(!x||!x.p){select.innerHTML='';return}const records=[...new Set(x.a.tools[x.t].blocks.filter(b=>b.target===x.p).map(b=>b.record_id))].sort();select.innerHTML=records.map(r=>`<option value="${r}">${r}</option>`).join('');draw()}
function draw(){const x=state(),record=select.value;if(!x||!record)return;const blocks=x.a.tools[x.t].blocks.filter(b=>b.target===x.p&&b.record_id===record),query=Math.max(...blocks.map(b=>b.query_length),1),truth=x.a.truth_plasmids[x.p].length,sx=v=>30+v/truth*420,sy=v=>450-v/query*420;const lines=blocks.map(b=>`<line x1="${sx(b.target_start)}" y1="${sy(b.query_start)}" x2="${sx(b.target_end)}" y2="${sy(b.query_end)}" stroke="${b.strand==='-'?'#7f5aa2':'#16805a'}" stroke-width="2"/>`).join('');$('vq-dotplot').innerHTML=`<h3>Dot plot: ${record} vs ${x.p}</h3><p class="muted">One predicted-record coordinate system is shown at a time. Forward diagonals support collinearity; reverse diagonals show reverse orientation. This is a diagnostic, not structural validation.</p><svg viewBox="0 0 480 480" width="480" role="img" aria-label="Dot plot"><rect x="30" y="30" width="420" height="420" fill="#f7f8f5" stroke="#849387"/>${lines}<text x="180" y="475" font-size="11">truth plasmid coordinate</text><text x="2" y="20" font-size="11">predicted-record coordinate</text></svg>`}
['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(draw,0));select.addEventListener('change',draw);render()})();
</script>"""


def structural_and_feature_tracks_script():
    """Overlay contextual features and expose structural diagnostics in HTML."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const host=document.createElement('div');host.id='vq-structural';$('vq-context').after(host);
const colors={replicon:'#5b7fb6',mob:'#9b59b6',insertion_sequence:'#d06d28',amr_context:'#1f8a70'};
function current(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;return {a,p,t,lo:Number($('vq-start').value)||0,hi:Number($('vq-end').value)||a.truth_plasmids[p].length}}
function overlay(){const x=current();if(!x)return;const svg=$('vq-tracks').querySelector('svg');if(!svg)return;svg.querySelectorAll('[data-context-feature]').forEach(n=>n.remove());const scale=v=>180+(v-x.lo)/(x.hi-x.lo)*880;(x.a.context_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi).forEach(f=>{const y=17,color=colors[f.feature_type]||'#5f6d6b',left=Math.max(180,scale(f.start)),right=Math.min(1060,scale(f.end));const r=document.createElementNS('http://www.w3.org/2000/svg','rect');r.setAttribute('data-context-feature','1');r.setAttribute('x',left);r.setAttribute('y',y);r.setAttribute('width',Math.max(2,right-left));r.setAttribute('height','6');r.setAttribute('fill',color);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${f.feature_type}: ${f.label} (${f.source} ${f.version})`;r.append(title);svg.append(r)});}
function render(){const x=current();if(!x){host.innerHTML='';return}const s=x.a.tools[x.t].structural_diagnostics||{};host.innerHTML='<h3>Structural alignment diagnostics</h3><p class="muted">Computed from all retained scoring blocks, not only blocks displayed in the SVG. This is a triage proxy, not a validated misassembly call.</p><div class="panel"><table><thead><tr><th>Concordance proxy</th><th>Breakpoints</th><th>Reverse blocks</th><th>Multi-target records</th><th>Order conflicts</th></tr></thead><tbody><tr><td>'+((s.structural_concordance_proxy??'-'))+'</td><td>'+(s.alignment_breakpoints??'-')+'</td><td>'+(s.reverse_orientation_blocks??'-')+'</td><td>'+(s.multi_truth_target_records??'-')+'</td><td>'+(s.order_conflicts??'-')+'</td></tr></tbody></table></div>';overlay()}
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('click',()=>setTimeout(render,0));render()})();
</script>"""


def protein_annotation_script():
    """Render standardized protein labels without overstating functional proof."""
    return """<style>
#vq-proteins{margin-top:16px}.vq-protein-controls{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0;font:12px Arial,sans-serif}
#vq-proteins table{min-width:680px}.vq-protein-status{font-weight:bold}.vq-protein-status.complete{color:#087250}.vq-protein-status.partial{color:#9a5b00}.vq-protein-status.missing{color:#a53028}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),host=document.createElement('div');host.id='vq-proteins';($('vq-structural')||$('vq-tracks')).after(host);
const high=new Set(['amr','replication','mobility','maintenance','mobile_element']),colors={amr:'#2275ad',replication:'#5b7fb6',mobility:'#9b59b6',maintenance:'#16805a',mobile_element:'#d06d28',hypothetical:'#8b9292',other:'#64736a'};
function state(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;return {a,p,t,lo:Number($('vq-start').value)||0,hi:Number($('vq-end').value)||a.truth_plasmids[p].length}}
function label(f){return f.gene||f.product||f.feature_id||'CDS'}
function status(f,pred){const n=Math.max(0,...pred.filter(x=>x.sequence_id===f.sequence_id&&x.end>f.start&&x.start<f.end).map(x=>x.projection_fraction||0));return n>=.95?'complete':n>=.3?'partial':'missing'}
function overlay(){const x=state(),svg=$('vq-tracks').querySelector('svg');if(!x||!svg)return;svg.querySelectorAll('[data-protein-feature]').forEach(n=>n.remove());const width=Math.max(1,x.hi-x.lo),scale=v=>180+(v-x.lo)/width*880,truth=(x.a.protein_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi),pred=(x.a.tools[x.t].protein_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi),names=Object.keys(x.a.tools),row=names.indexOf(x.t);
 function arrow(f,y,opacity){const left=Math.max(180,scale(f.start)),right=Math.min(1060,scale(f.end)),tip=Math.min(7,Math.max(2,right-left));const forward=f.strand!=='-';const points=forward?`${left},${y} ${right-tip},${y} ${right},${y+4} ${right-tip},${y+8} ${left},${y+8}`:`${right},${y} ${left+tip},${y} ${left},${y+4} ${left+tip},${y+8} ${right},${y+8}`;const n=document.createElementNS('http://www.w3.org/2000/svg','polygon');n.setAttribute('data-protein-feature','1');n.setAttribute('points',points);n.setAttribute('fill',colors[f.category]||colors.other);n.setAttribute('fill-opacity',opacity);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${label(f)} | ${f.product||'unlabelled CDS'} | ${f.category||'other'} | ${f.source} ${f.version}`;n.append(title);svg.append(n);if(high.has(f.category)&&right-left>28){const text=document.createElementNS('http://www.w3.org/2000/svg','text');text.setAttribute('data-protein-feature','1');text.setAttribute('x',left);text.setAttribute('y',y-2);text.setAttribute('font-size','9');text.textContent=label(f);svg.append(text)}}
 truth.forEach(f=>arrow(f,26,.9));pred.forEach(f=>arrow(f,40+row*38+10,.72));}
 function render(){const x=state();if(!x)return;const truth=(x.a.protein_features||[]).filter(f=>f.sequence_id===x.p),pred=x.a.tools[x.t].protein_features||[];const categories=[...new Set(truth.map(f=>f.category||'other'))].sort();host.innerHTML='<h3>Protein annotations and coordinate recovery</h3><p class="muted">Names are standardized annotation products. Recovery is projected through nucleotide alignments and is not amino-acid identity, orthology, frameshift, or closure evidence.</p><div class="vq-protein-controls"><label>Category <select id="vq-protein-category"><option value="">All</option>'+categories.map(c=>`<option value="${c}">${c}</option>`).join('')+'</select></label><label>Search <input id="vq-protein-search" type="search" placeholder="gene or product"></label><span>Truth CDS: '+truth.length+' · mapped predicted CDS: '+pred.length+'</span></div><div class="panel"><table><thead><tr><th>Protein</th><th>Product</th><th>Category</th><th>Truth coordinates</th><th>Projected recovery</th><th>Annotation provenance</th></tr></thead><tbody id="vq-protein-body"></tbody></table></div>';
 const refresh=()=>{const q=($('vq-protein-search').value||'').toLowerCase(),c=$('vq-protein-category').value,shown=truth.filter(f=>(!c||f.category===c)&&(!q||(`${label(f)} ${f.product||''} ${f.dbxref||''}`).toLowerCase().includes(q)));$('vq-protein-body').innerHTML=shown.map(f=>{const s=status(f,pred);return `<tr><td>${label(f)}</td><td>${f.product||'hypothetical protein'}</td><td>${f.category||'other'}</td><td>${f.start}-${f.end} (${f.strand})</td><td><span class="vq-protein-status ${s}">${s==='complete'?'coordinate-complete':s==='partial'?'coordinate-partial':'not projected'}</span></td><td>${f.source} ${f.version} · ${f.confidence}</td></tr>`}).join('')||'<tr><td colspan="6">No protein annotations match this filter. Enable standardized annotation to populate this view.</td></tr>'};$('vq-protein-category').addEventListener('change',refresh);$('vq-protein-search').addEventListener('input',refresh);refresh();overlay()}
 ['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('click',()=>setTimeout(render,0));render()})();
</script>"""


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
        selection = out.parent / "selected_candidates" / sample / f"{sample}.selection_report.json"
        if not selection.is_file():
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
    vendor_html = vendor_assets(args.project_root)
    visual_html = (visual_quality_section(scores, status, out.parent, out) + advanced_visual_script()
                   + record_dotplot_script() + context_visual_script() + evidence_selection_script()
                   + plasmid_summary_script() + structural_and_feature_tracks_script() + protein_annotation_script()
                   + bin_flow_script() + explorer_navigation_script()
                   + agreement_and_comparison_script()
                   + explorer_chrome_script()
                   + lazy_visualization_script())
    explorer_html = evidence_explorer_section(args.project_root, scores, out.parent, vendor_html)
    enterprise_html = enterprise_view_section(args.project_root, scores, status, leaderboard,
                                              metadata, out.parent, vendor_html,
                                              explorer_html + visual_html)
    page = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PlasBench plasmid benchmark report</title>
{vendor_html}
<style>
:root{{--ink:#17231d;--muted:#627067;--line:#d9e1da;--paper:#f6f8f4;--card:#fff;--green:#0c6b4f;--lime:#dcefdc;--amber:#9a5b00;--red:#a53028;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}} header{{background:#183a2d;color:#fff;padding:48px max(24px,calc((100vw - 1320px)/2));border-bottom:6px solid #a8d29b}} h1,h2,h3,th,.nav,button,select,input,.metric,.status,.selection-card{{font-family:Arial,sans-serif}} h1{{font-size:clamp(28px,5vw,48px);margin:0 0 8px;letter-spacing:-.04em}} header p{{margin:0;color:#d9e7de}} main{{max-width:1320px;margin:auto;padding:28px 24px 64px}} .nav{{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 28px}} .nav a{{color:var(--green);border:1px solid var(--line);background:#fff;padding:7px 10px;text-decoration:none;font-size:12px;font-weight:bold}} .metrics{{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:12px;margin-bottom:28px}} .metric{{background:var(--card);border-top:4px solid var(--green);padding:15px;box-shadow:0 1px 3px #15241c12}} .metric small{{color:var(--muted);display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em}} .metric strong{{font-size:27px;display:block;margin-top:4px}} section{{margin:38px 0}} h2{{font-size:21px;margin:0 0 5px}} h3{{margin:6px 0;font-size:17px}} .lead,.muted{{color:var(--muted)}} .panel{{background:var(--card);border:1px solid var(--line);overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:760px;font-family:Arial,sans-serif;font-size:13px}} th{{background:#edf2ec;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .sortable th{{cursor:pointer}} .sortable th:hover{{background:#dcebdc}} td{{border-top:1px solid var(--line);padding:9px 10px;white-space:nowrap}} tr:hover td{{background:#f5faf4}} .f1-bar{{display:block;width:100%;height:5px;background:#deeadf;margin-top:4px;min-width:64px}} .f1-bar i{{display:block;height:100%;background:var(--green)}} .f1-bar.medium i{{background:#c68221}} .f1-bar.low i{{background:#bd4b42}} .score.high{{color:#087250}} .score.medium{{color:#9a5b00}} .score.low{{color:#a53028}} .insight{{border-left:6px solid var(--green);background:#e7f1e7;padding:16px 20px}} .insight.caution{{border-color:var(--amber);background:#fbf2df}} .insight ul{{margin:6px 0 0;padding-left:20px}} .chart-card{{background:#fff;border:1px solid var(--line);padding:18px;overflow:auto}} .performance-chart{{display:block;min-width:650px;width:100%;height:auto}} .performance-chart .axis,.performance-chart .label{{font:12px Arial,sans-serif;fill:#536158}} .chart-legend,.legend{{display:flex;gap:16px;flex-wrap:wrap;font:12px Arial,sans-serif;margin:10px 0}} .chart-legend i,.legend i{{display:inline-block;width:10px;height:10px;margin-right:5px}} .metadata{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);font-family:Arial,sans-serif;font-size:13px}} .metadata div{{background:#fff;padding:12px}} .metadata small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.06em}} .controls{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}} select,input{{padding:7px;border:1px solid var(--line);background:#fff}} .count{{font:12px Arial,sans-serif;color:var(--muted);align-self:center}} .status,.selection-label{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold}} .completed,.reused{{background:#dcefdc;color:#07573e}} .failed{{background:#f7ddda;color:var(--red)}} .skipped{{background:#f6ead1;color:var(--amber)}} .selection-card{{display:grid;grid-template-columns:1fr auto;gap:14px;background:#fff;border:1px solid var(--line);border-left:6px solid var(--amber);padding:18px;margin:12px 0}} .selection-card.confident{{border-left-color:var(--green)}} .selection-label{{background:#f6ead1;color:#765000}} .confident .selection-label{{background:#dcefdc;color:#07573e}} .selection-actions{{text-align:right;min-width:190px}} .download-button{{display:inline-block;background:var(--green);color:#fff!important;padding:8px 10px;text-decoration:none;font-weight:bold}} .selection-card details{{grid-column:1/-1;border-top:1px solid var(--line)}} .selection-card summary{{padding:10px 0;cursor:pointer;font-weight:bold}} .selection-card ul{{margin:0;padding-left:20px}} details.sample,.explorer{{background:var(--card);border:1px solid var(--line);margin:10px 0;padding:0 14px}} details summary{{cursor:pointer;padding:13px 0;font-family:Arial,sans-serif}} details summary span{{float:right;color:var(--muted);font-size:12px}} .file-tree{{list-style:none;padding-left:18px;margin:0 0 15px;font-family:Arial,sans-serif;font-size:13px}} .file-tree li{{padding:3px 0}} .file-tree details summary{{padding:3px 0}} .file-tree a{{color:var(--green);text-decoration:none;font-weight:600}} .file-tree .file span{{color:var(--muted);font-size:11px;margin-left:8px}} .method{{columns:2;column-gap:32px;background:#ebf2ea;padding:18px 22px}} .method p{{margin-top:0;break-inside:avoid}} footer{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}} @media(max-width:700px){{main{{padding:20px 14px}}header{{padding:32px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metadata{{grid-template-columns:1fr}}.method{{columns:1}}.selection-card{{grid-template-columns:1fr}}.selection-actions{{text-align:left}}}}
</style></head><body>
<header><h1>PlasBench plasmid reconstruction benchmark</h1><p>Detailed run report · generated {esc(generated)} · offline HTML with direct artifact downloads</p></header>
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
    page = page.replace("<a href='#selected'>", "<a href='#enterprise'>Interactive dashboard</a><a href='#selected'>")
    page = page.replace("<section id='scores'>", enterprise_html + "<section id='scores'>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote HTML report: {out}")


if __name__ == "__main__":
    main()
