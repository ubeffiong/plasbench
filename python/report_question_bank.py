#!/usr/bin/env python3
"""
report_question_bank.py -- HTML report sections that answer reviewer
questions the benchmark tables alone cannot (docs/FAQ_QUESTION_BANK.md):

* Baselines and calibration (Q62, Q66, Q78, Q108): does each tool beat the
  trivial baselines ranked alongside it, and are probability-emitting tools
  calibrated (Brier score, expected calibration error, reliability diagram)?
* Interpretation limits (Q41-43, Q68-73): what these results support and what
  they must not be used to claim.
* Metadata completeness (Q85): which samples lack fields that change how they
  are analysed, and what that changes.

Kept as a separate module so build_html_report.py needs only one call:
    page = report_question_bank.inject(page, out_dir, leaderboard_rows)
Every section renders an explicit empty state rather than disappearing.

Standard library only.
"""

import csv
import html
from collections import defaultdict
from pathlib import Path

SECTIONS = (("metric-framework", "Metrics"),
            ("database-membership", "Database membership"),
            ("baselines-calibration", "Baselines &amp; calibration"),
            ("interpretation-limits", "Interpretation limits"),
            ("metadata-completeness", "Metadata completeness"),
            ("excluded-replicons", "Excluded replicons"))


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_tsv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def pooled_reliability(out_dir, tool):
    """Pool every sample's <tool>.calibration.tsv bins, weighted by aligned bp."""
    bins = defaultdict(lambda: [0.0, 0.0, 0.0])  # bin_low -> [weight, sum p*w, sum y*w]
    for path in Path(out_dir).glob(f"*/{tool}.calibration.tsv"):
        for row in read_tsv(path):
            weight = number(row.get("weight_bp")) or 0.0
            p, y = number(row.get("mean_probability")), number(row.get("observed_plasmid_fraction"))
            if weight and p is not None and y is not None:
                acc = bins[row.get("bin_low")]
                acc[0] += weight
                acc[1] += p * weight
                acc[2] += y * weight
    return sorted(((acc[1] / acc[0], acc[2] / acc[0], acc[0]) for acc in bins.values() if acc[0]),
                  key=lambda item: item[0])


def reliability_chart(tool, points):
    """Mean predicted probability (x) against observed plasmid fraction (y)."""
    size, pad = 220, 30
    plot = size - pad - 12

    def sx(v):
        return pad + v * plot

    def sy(v):
        return pad + (1 - v) * plot

    total = sum(w for _, _, w in points) or 1.0
    dots = "".join(
        f"<circle cx='{sx(p):.1f}' cy='{sy(y):.1f}' r='{3 + 6 * (w / total) ** 0.5:.1f}' fill='#174b3a' "
        f"fill-opacity='0.8'><title>predicted {p:.2f}, observed {y:.2f} ({int(w):,} aligned bp)</title></circle>"
        for p, y, w in points)
    line = " ".join(f"{sx(p):.1f},{sy(y):.1f}" for p, y, _ in points)
    return (
        f"<figure class='chart-card'><svg class='pr-chart' viewBox='0 0 {size} {size}' role='img' "
        f"aria-label='Reliability diagram for {esc(tool)}'>"
        f"<rect x='{pad}' y='{pad}' width='{plot}' height='{plot}' fill='none' stroke='#d9e1da'/>"
        f"<line x1='{sx(0)}' y1='{sy(0)}' x2='{sx(1)}' y2='{sy(1)}' stroke='#c68221' stroke-dasharray='4 3'/>"
        f"<polyline points='{line}' fill='none' stroke='#174b3a' stroke-width='1.5'/>{dots}"
        f"<text x='{pad}' y='{pad + plot + 14}' class='axis'>0</text>"
        f"<text x='{pad + plot - 52}' y='{pad + plot + 14}' class='axis'>predicted 1.0</text>"
        f"<text x='0' y='{pad + 4}' class='axis'>1.0</text><text x='0' y='{pad + plot}' class='axis'>obs.</text>"
        f"</svg><figcaption>{esc(tool)}: dots on the dashed diagonal are perfectly calibrated</figcaption></figure>"
    )


def baselines_section(out_dir, leaderboard):
    rows = [r for r in leaderboard if r.get("tool")]
    has_baseline = any(r.get("is_baseline") == "yes" for r in rows)
    body = []
    for r in rows:
        verdict = r.get("beats_best_baseline") or "-"
        verdict_text = {"yes": "beats baseline", "no": "does NOT beat baseline", "baseline": "baseline",
                        "no baseline": "no baseline scored"}.get(verdict, verdict)
        body.append(
            f"<tr><td>{esc(r.get('analysis_track'))} / {esc(r.get('task'))}</td><td>{esc(r['tool'])}</td>"
            f"<td>{esc(r.get('ranking_score') or '-')}</td><td><strong>{esc(verdict_text)}</strong></td>"
            f"<td>{esc(r.get('mean_brier_score') or 'no probabilities')}</td>"
            f"<td>{esc(r.get('mean_expected_calibration_error') or 'no probabilities')}</td>"
            f"<td>{esc(r.get('n_calibrated') or '0')}</td></tr>")
    charts = []
    for r in rows:
        if number(r.get("n_calibrated")):
            points = pooled_reliability(out_dir, r["tool"])
            if points:
                charts.append(reliability_chart(r["tool"], points))
    note = ("" if has_baseline else
            "<p class='muted'>No trivial baseline was scored in this run (RUN_BASELINE_COVERAGE / "
            "RUN_BASELINE_REFERENCE, or the assembly had no depth headers and no plasmid reference set was "
            "built). Without one, the leaderboard cannot show that any tool adds value over an obvious rule.</p>")
    return (
        "<section id='baselines-calibration'><h2>Baselines and calibration</h2>"
        "<p class='lead'>Two trivial baselines are scored like tools: <strong>baseline_coverage</strong> calls "
        "contigs with assembler depth well above the median plasmid (plasmids are often multi-copy), and "
        "<strong>baseline_reference</strong> calls contigs that align to the local plasmid reference set (a "
        "stand-in for a PLSDB search). A tool ranked below a baseline adds nothing that rule does not already "
        "give. For tools that report a plasmid probability per contig, calibration asks whether a probability of "
        "0.8 is right about 80% of the time: <strong>Brier score</strong> (lower is better, 0 is perfect) and "
        "<strong>expected calibration error</strong> (ECE, weighted gap between predicted and observed). "
        "Calibration is not accuracy: a tool can rank contigs well and still be over-confident.</p>" + note
        + "<div class='panel'><table class='sortable'><thead><tr><th>Track / task</th><th>Tool</th>"
          "<th>Ranking score</th><th>Versus best baseline</th><th>Mean Brier score</th><th>Mean ECE</th>"
          "<th>Samples calibrated</th></tr></thead><tbody>"
        + ("".join(body) or "<tr><td colspan='7'>No scored tools.</td></tr>") + "</tbody></table></div>"
        + ("<div class='pr-grid'>" + "".join(charts) + "</div>" if charts else
           "<p class='muted'>No tool exposed per-contig probabilities, so no reliability diagram is shown.</p>")
        + "</section>")


def interpretation_section():
    supports = [
        "Which tool recovered more of the truth plasmid sequence, grouped it more correctly, and contaminated it "
        "less, on these isolates and this truth.",
        "How confident that ranking is (cluster-aware intervals, paired tests, rank robustness).",
        "Where a tool fails: by species, reference tier, replicon or size stratum, and per plasmid (CPRR).",
    ]
    does_not = [
        ("Plasmid relatedness or lineage.", "PlasBench never compares plasmids with each other; it compares each "
         "prediction with the truth genome of the same isolate."),
        ("Transmission, common source or outbreak membership.", "Benchmark scores carry no epidemiological "
         "information; genomic similarity is not transmission (question bank Q68-Q69)."),
        ("Spread of a resistance gene versus spread of a plasmid.", "AMR gene recall says whether a tool recovered "
         "a gene inside its plasmid, not how either moves between hosts (Q71)."),
        ("Biological novelty.", "Absence from a reference set is not novelty; the operational Mash screen reports "
         "only distance to its small reference set (Q10, Q25)."),
        ("Clinical validity or performance on unseen species.", "Results generalise only to species, platforms and "
         "truth tiers represented in this cohort (Q65, Q67)."),
        ("That a predicted sequence is a real, closed plasmid.", "Scores describe agreement with a reference; they "
         "are not experimental confirmation (PCR, conjugation, long-read closure)."),
    ]
    vocabulary = [("recovered", "aligned to truth plasmid bases above the configured threshold"),
                  ("correctly reconstructed (CPRR)", "matched, covered, uncontaminated, not split, and -- where "
                   "valid -- high identity"),
                  ("close reference match", "within a Mash distance of the reference set; not 'known lineage'"),
                  ("significant", "Holm-adjusted paired permutation p < 0.05 on shared samples; not 'better in "
                   "every sample'")]
    return (
        "<section id='interpretation-limits'><h2>Interpretation limits</h2>"
        "<p class='lead'>What these results support, and what they must not be used to claim. A benchmark of "
        "reconstruction tools answers a methods question; it does not answer surveillance or lineage questions.</p>"
        "<div class='insight neutral'><h3>These results support</h3><ul>"
        + "".join(f"<li>{esc(item)}</li>" for item in supports) + "</ul>"
        "<h3>These results do NOT show</h3><ul>"
        + "".join(f"<li><strong>{esc(claim)}</strong> {esc(why)}</li>" for claim, why in does_not) + "</ul>"
        "<h3>Words used in this report</h3><ul>"
        + "".join(f"<li><strong>{esc(term)}</strong>: {esc(meaning)}</li>" for term, meaning in vocabulary)
        + "</ul></div></section>")


def metadata_section(out_dir):
    rows = read_tsv(Path(out_dir) / "benchmark.metadata_completeness.tsv")
    incomplete = [r for r in rows if (number(r.get("n_missing")) or 0) > 0]
    if not rows:
        body = "<p class='muted'>No metadata-completeness table (no sample sheet was given to aggregation).</p>"
    elif not incomplete:
        body = f"<p class='muted'>All {len(rows)} scored sample(s) carry every consequential field.</p>"
    else:
        body = ("<div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Missing</th>"
                "<th>Fields</th><th>What it changes</th></tr></thead><tbody>"
                + "".join(f"<tr><td>{esc(r.get('sample'))}</td><td>{esc(r.get('n_missing'))}</td>"
                          f"<td>{esc(r.get('missing_fields'))}</td><td>{esc(r.get('consequences'))}</td></tr>"
                          for r in incomplete)
                + "</tbody></table></div>")
    return ("<section id='metadata-completeness'><h2>Metadata completeness</h2>"
            "<p class='lead'>Samples still run when metadata is missing, but some analyses change: a sample "
            "without a species leaves the species-balanced headline, one without a study counts as its own "
            f"cluster, and missing truth provenance falls back to NCBI-derived tiers. "
            f"{len(incomplete)} of {len(rows)} scored sample(s) are affected.</p>{body}</section>")


def excluded_replicons_section(data_dir):
    """Replicons evidence labelling removed from scoring (AMBIGUOUS), with the reason."""
    rows = []
    if data_dir and Path(data_dir).is_dir():
        for path in sorted(Path(data_dir).glob("*/truth_labels.tsv")):
            for row in read_tsv(path):
                if row.get("final_label") == "AMBIGUOUS":
                    rows.append((path.parent.name, row))
    if not rows:
        body = ("<p class='muted'>No replicon was excluded: either every source label was confirmed by evidence, "
                "or evidence labelling did not run (RUN_TRUTH_LABEL_EVIDENCE / RUN_REFERENCE_ANNOTATION).</p>")
    else:
        body = ("<div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Replicon</th>"
                "<th>Length</th><th>Source label</th><th>Plasmid markers</th><th>rRNA genes</th>"
                "<th>Long-read depth</th><th>Marker-free</th><th>Why excluded</th></tr></thead><tbody>"
                + "".join(f"<tr><td>{esc(sample)}</td><td>{esc(r.get('sequence_id'))}</td><td>{esc(r.get('length'))}</td>"
                          f"<td>{esc(r.get('source_label'))}</td><td>{esc(r.get('plasmid_markers') or '-')}</td>"
                          f"<td>{esc(r.get('rrna_genes') or '-')}</td><td>{esc(r.get('long_read_depth') or '-')}</td>"
                          f"<td>{esc(r.get('marker_free') or '-')}</td><td>{esc(r.get('reason'))}</td></tr>"
                          for sample, r in rows)
                + "</tbody></table></div>")
    marker_free = sum(1 for _, r in rows if r.get("marker_free") == "yes")
    return ("<section id='excluded-replicons'><h2>Replicons excluded from scoring</h2>"
            "<p class='lead'>Truth replicons whose plasmid/chromosome label conflicted with plasmid markers, rRNA "
            "genes or long-read support are AMBIGUOUS: predictions on them are neither credited nor penalised. "
            f"{len(rows)} replicon(s) excluded, {marker_free} of them plasmids with no marker at all -- the stratum "
            "a marker-based labeller cannot confirm, reported here rather than hidden.</p>" + body + "</section>")


def metric_framework_section(leaderboard, data_dir):
    """The headline metric set, per tool, with how contigs were labelled."""
    rows = [r for r in leaderboard if r.get("tool")]

    def cell(row, key):
        value = row.get(key)
        return esc(value) if value not in (None, "") else "-"

    body = "".join(
        f"<tr><td>{esc(r.get('analysis_track'))} / {esc(r.get('task'))}</td><td>{esc(r['tool'])}</td>"
        f"<td>{cell(r, 'mean_f1')}</td><td>{cell(r, 'micro_f1')}</td>"
        f"<td>{cell(r, 'mean_contig_f1_count')}</td><td>{cell(r, 'mean_contig_f1_bp')}</td>"
        f"<td>{cell(r, 'mean_contig_mcc_count')}</td><td>{cell(r, 'mean_contig_mcc_bp')}</td>"
        f"<td>{cell(r, 'mean_lw_bin_f1')}</td><td>{cell(r, 'mean_lw_bin_f1_assembly_aware')}</td>"
        f"<td>{cell(r, 'mean_bin_ari')}</td><td>{cell(r, 'cprr')}</td></tr>" for r in rows)
    label_counts = defaultdict(int)
    if data_dir and Path(data_dir).is_dir():
        for path in Path(data_dir).glob("*/contig_labels.tsv"):
            for row in read_tsv(path):
                label_counts[row.get("label", "")] += 1
    labels = (", ".join(f"{esc(k)} {v}" for k, v in sorted(label_counts.items()))
              if label_counts else "contig labels not computed in this run")
    return (
        "<section id='metric-framework'><h2>Classification and reconstruction metrics</h2>"
        "<p class='lead'>Two tasks, scored separately. <strong>Classification</strong> (is a contig plasmid?): "
        "base-level F1 as the <em>macro</em> average (per isolate, then averaged) and the <em>micro</em> average "
        "(bases pooled over all isolates), plus contig-level precision/recall/F1/MCC counted per contig and "
        "weighted by contig length. MCC is shown because plasmid contigs are a small minority. <strong>"
        "Reconstruction</strong> (which contigs form one plasmid?): length-weighted binning F1 from a one-to-one "
        "Hungarian match, the same with recall measured against the plasmid length the assembly actually covers, "
        "base-pair-weighted Adjusted Rand Index, and CPRR (share of truth plasmids reconstructed correctly).</p>"
        "<p class='muted'>Contig labels: contigs shorter than CONTIG_MIN_LENGTH (default 1 kb) are excluded; a contig "
        "is PLASMID or CHROMOSOME when at least 80% of it aligns to that kind of truth at 95% identity; one that "
        "aligns that well to both is AMBIGUOUS and excluded, not multi-assigned; one that aligns to neither is "
        f"UNPLACED and excluded. This run: {labels}. Tools that output reassembled sequences instead of assembly "
        "contigs are not scored at contig level. Abstention is not measured: no wrapped tool reports an explicit "
        "unclassified call.</p>"
        "<div class='panel'><table class='sortable'><thead><tr><th>Track / task</th><th>Tool</th>"
        "<th>Base F1 (macro)</th><th>Base F1 (micro)</th><th>Contig F1 (count)</th><th>Contig F1 (length)</th>"
        "<th>MCC (count)</th><th>MCC (length)</th><th>Binning F1 (length)</th><th>Binning F1 (assembly-aware)</th>"
        "<th>ARI</th><th>CPRR</th></tr></thead><tbody>"
        + (body or "<tr><td colspan='12'>No scored tools.</td></tr>") + "</tbody></table></div></section>")


def database_membership_section(leaderboard, out_dir):
    """Recovery of truth plasmids inside vs outside each tool's own database."""
    rows = [r for r in leaderboard if r.get("n_plasmids_in_tool_database") not in (None, "")]
    containment = read_tsv(Path(out_dir) / "benchmark.database_containment.tsv")
    if not rows:
        note = ("No tool database was checked in this run (RUN_DATABASE_CONTAINMENT, minimap2, or no installed "
                "database such as MOB-suite's). The date-based screen in Robustness diagnostics still applies.")
        body = f"<p class='muted'>{esc(note)}</p>"
    else:
        def gap(r):
            a, b = number(r.get("mean_recovery_in_tool_database")), number(r.get("mean_recovery_not_in_tool_database"))
            return f"{a - b:+.3f}" if a is not None and b is not None else "-"
        body = ("<div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Truth plasmids in its "
                "database</th><th>Mean recovery, in database</th><th>Mean recovery, not in database</th>"
                "<th>Gap</th></tr></thead><tbody>"
                + "".join(f"<tr><td>{esc(r['tool'])}</td><td>{esc(r['n_plasmids_in_tool_database'])}</td>"
                          f"<td>{esc(r.get('mean_recovery_in_tool_database') or '-')}</td>"
                          f"<td>{esc(r.get('mean_recovery_not_in_tool_database') or '-')}</td>"
                          f"<td><strong>{esc(gap(r))}</strong></td></tr>" for r in rows)
                + "</tbody></table></div>")
    inside = sum(1 for r in containment if r.get("in_database") == "yes")
    return ("<section id='database-membership'><h2>Truth plasmids in tool databases</h2>"
            "<p class='lead'>Sequence-level leakage check: a truth plasmid is <em>in</em> a tool's database when one "
            "database record covers at least 95% of it at 99% identity. A tool that recovers in-database plasmids "
            "far better than novel ones is partly recognising rather than inferring, so its score overstates "
            f"performance on new isolates. {inside} of {len(containment)} truth plasmid x database pair(s) were "
            "contained.</p>" + body + "</section>")


def inject(page, out_dir, leaderboard, data_dir=None):
    """Insert the question-bank sections before Recommendations, and their nav links."""
    sections = (metric_framework_section(leaderboard, data_dir) + database_membership_section(leaderboard, out_dir)
                + baselines_section(out_dir, leaderboard) + interpretation_section() + metadata_section(out_dir)
                + excluded_replicons_section(data_dir))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, sections + anchor, 1)
        nav_anchor = "<a href='#recommendations'>Recommendations</a>"
        links = "".join(f"<a href='#{section_id}'>{label}</a>" for section_id, label in SECTIONS)
        page = page.replace(nav_anchor, links + nav_anchor, 1)
    return page
