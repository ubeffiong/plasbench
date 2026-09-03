#!/usr/bin/env python3
"""Regression checks for the linked visual explorer in the HTML report.

The offline demo produces no visualization payload, so this exercises the
build_visualization_data -> build_html_report path directly.
"""

import csv
import re
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VISUAL = os.path.join(ROOT, "python", "build_visualization_data.py")
REPORT = os.path.join(ROOT, "python", "build_html_report.py")

PAF = [
    # q1 recovers pA cleanly; q2 recovers pB; q3 is a chromosomal record wrongly
    # called plasmid; q4 is chimeric -- it supports pA but also maps to pB.
    ("q1", 2000, 0, 2000, "+", "pA", 2000, 0, 2000),
    ("q2", 1500, 0, 1500, "+", "pB", 1500, 0, 1500),
    ("q3", 400, 0, 400, "+", "chr1", 8000, 0, 400),
    ("q4", 300, 0, 300, "-", "pA", 2000, 100, 400),
    ("q4", 300, 0, 300, "+", "pB", 1500, 10, 310),
]


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="visual_report_") as tmp:
        results = os.path.join(tmp, "results")
        sample_dir = os.path.join(results, "s1")
        os.makedirs(sample_dir)
        truth = os.path.join(tmp, "truth.tsv")
        write(truth, [["sequence_id", "molecule_type", "length"],
                      ["chr1", "CHROMOSOME", 8000], ["pA", "PLASMID", 2000], ["pB", "PLASMID", 1500]])
        circular = os.path.join(tmp, "circular.tsv")
        write(circular, [["sequence_id"], ["pA"]])
        with open(os.path.join(sample_dir, "toolx.pred_vs_ref.paf"), "w", encoding="utf-8") as handle:
            for row in PAF:
                handle.write("\t".join(str(x) for x in row) + "\t100\t100\t60\n")

        blocks = os.path.join(sample_dir, "visualization", "alignment_blocks.json")
        subprocess.run([sys.executable, VISUAL, "--truth", truth, "--results-dir", results,
                        "--sample", "s1", "--circular-truth", circular, "--out", blocks], check=True)
        assert os.path.isfile(blocks), "visualization payload was not written"

        scores = os.path.join(results, "scores.tsv")
        write(scores, [["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                        "unmapped_pred_bp", "plasmid_recall", "precision", "recall", "f1"],
                       ["s1", "toolx", 3500, 3500, 400, 0, 0, "1.0000", "0.8974", "1.0000", "0.9459"]])
        leaderboard = os.path.join(results, "benchmark.leaderboard.tsv")
        write(leaderboard, [["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped",
                             "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1",
                             "mean_f1", "f1_ci_low", "f1_ci_high", "median_f1"],
                            [1, "toolx", 1, 1, 0, 0, "0.8974", "1.0000", "1.0000", "",
                             "0.9459", "0.9459", "0.9459", "0.9459"]])
        out = os.path.join(results, "report.html")
        subprocess.run([sys.executable, REPORT, "--project-root", ROOT, "--scores", scores,
                        "--tool-status", os.path.join(results, "absent.tsv"),
                        "--leaderboard", leaderboard, "--out", out], check=True)
        page = open(out, encoding="utf-8").read()

    # The retained canvas matrix exposes an accessible description, receives
    # keyboard focus, and supports keyboard movement and modal drilldown.
    for needed in ("tabindex=\"0\"", "aria-label", "ArrowDown", "focus-visible",
                   "openDrilldown"):
        assert needed in page, f"accessibility affordance missing: {needed}"
    # Selections must be shareable.
    assert "history.replaceState" in page and "URLSearchParams" in page, "URL state missing"
    # Cohort narrowing and the visible-record count are owned by the retained
    # dashboard, including every former metadata filter.
    for needed in ("originFilter", "tierFilter", "sampleSearch", "resetFiltersBtn", "Showing "):
        assert needed in page, f"filter affordance missing: {needed}"
    assert 'id="vq-filter"' not in page, "legacy duplicate visual filters must not be emitted"
    # Per-plasmid summary and the contamination surfacing that completeness hides.
    for needed in ("vq-summary", "Impure records", "Chromosomal contamination for",
                   "not attributable to any truth plasmid", "vq-impure"):
        assert needed in page, f"plasmid summary affordance missing: {needed}"
    # Dot plots retain one query-coordinate system per selected predicted record,
    # while diagnostics and curated context are visibly wired into the report.
    for needed in ("Predicted record", "One predicted-record coordinate system",
                   "Structural alignment diagnostics", "data-context-feature",
                   "Concordance proxy"):
        assert needed in page, f"visual diagnostic affordance missing: {needed}"
    # The adopted enterprise iframe has its own unrelated renderer names. Check
    # the retired mixed-query-coordinate implementation by its old semantics.
    assert "Reference coordinate is horizontal; predicted-record coordinate is vertical." not in page, \
        "legacy mixed-coordinate dot-plot renderer must not be emitted"
    for needed in ("Protein annotations and coordinate recovery", "vq-protein-category",
                   "coordinate-complete", "not amino-acid identity"):
        assert needed in page, f"protein viewer affordance missing: {needed}"

    # The embedded cohort dashboard owns summary cards and distribution plots.
    # The legacy renderer must not add a second copy below it.
    for needed in ("Best Tool", "Top Sample", "Failures", "Plasmids",
                   "Protein coordinate recovery", "Runtime (min)", "Memory (GB)"):
        assert needed in page, f"cohort dashboard affordance missing: {needed}"
    assert 'id="vq-stats"' not in page and 'id="vq-dist"' not in page, \
        "legacy overview cards and distribution plots must not be emitted"
    # An unmeasured metric must say so rather than plot fabricated zeros.
    assert "not measured" in page, "missing-metric wording absent"
    assert "not counted as zero" in page or "rather than as zero" in page or         "excluded rather than counted as zero" in page, "zero-substitution caveat absent"
    # The programme rename must hold in the shipped page.
    assert "PlasBench plasmid benchmark report" in page, "report title not renamed"
    assert "PlasBench plasmid reconstruction benchmark" in page, "report heading not renamed"
    # Only the report's own branding is asserted: a user's directory may legitimately
    # contain "SPREAD" and would surface through the artifact explorer's file paths.
    for banner in ("SPREAD plasmid benchmark report", "SPREAD plasmid reconstruction benchmark"):
        assert banner not in page, f"legacy programme branding remains: {banner}"

    # The enterprise Sample-Tool Heatmap is the single matrix. It retains
    # filtering, canvas tooltip, clustering, and drilldown; the detailed tracks
    # now live beneath the same dashboard rather than beside another matrix.
    for needed in ("Sample–Tool Heatmap", "heatmapCanvas", "heatmapTooltip",
                   "clusterBtn", "drilldownModal", "getContext"):
        assert needed in page, f"sample-tool heatmap affordance missing: {needed}"
    assert "cv-canvas" not in page, "duplicate Sample x method matrix must not be emitted"
    assert "vq-heatmap" not in page and "vq-cell" not in page, \
        "legacy Sample x method matrix must not be emitted"
    assert "cohort-evidence-explorer" in page, "detailed evidence must be nested in the cohort dashboard"
    assert "href='#enterprise'>Interactive dashboard" in page, \
        "report navigation must target the consolidated dashboard"
    # Vendored faces: no CDN request may remain, and the fonts must be embedded.
    for banned in ("fonts.googleapis.com", "cdnjs.cloudflare.com", "fonts.gstatic.com"):
        assert banned not in page, f"report still references a CDN: {banned}"
    assert "data:font/woff2;base64," in page, "web fonts are not vendored into the report"
    assert "PlasBenchIcons" in page, "icon face not vendored"
    # The retained dashboard owns keyboard navigation from a document listener.
    assert "document.addEventListener('keydown'" in page, "dashboard keyboard navigation missing"

    # Adopted enterprise dashboard: present, isolated, and driven by measurements.
    for needed in ("pb-enterprise", "pb-enterprise-doc", "pb-data", "heatmapCanvas",
                   "drilldownModal", "PlasBench · Enterprise Report"):
        assert needed in page, f"enterprise dashboard affordance missing: {needed}"
    assert "srcdoc" in page, "dashboard must be isolated in a frame"
    # Nothing in the adopted view may simulate data. The upstream prototype
    # generated its dataset, highlighted random mismatches, jittered dot plots
    # and added noise to sorting; none of that may survive.
    assert "Math.random" not in page, "the report must not contain any random data generation"
    assert "generateContigs(" not in page, "contig fabrication fallback must be removed"
    assert '"simulated":false' in page or '"simulated": false' in page,         "dashboard payload must declare it is not simulated"
    # Helpers the removed generator owned must still be defined for the renderer.
    assert "function clamp(" in page, "clamp helper missing after generator removal"
    for needed in ("Protein coordinate recovery", "Named proteins", "totalProteins",
                   "Metric Distribution by Tool", "Per-Sample Distribution"):
        assert needed in page, f"consolidated dashboard feature missing: {needed}"

    # The embedded dashboard matches the surrounding light report and carries no
    # prototype branding or hardcoded cohort figures.
    assert "--bg-primary: #f3f6f4" in page, "dashboard must use the light surface set"
    assert "#080b11" not in page and "#151e2b" not in page, "dark prototype surfaces remain"
    assert "logo-icon" not in page, "prototype badge mark must be removed"
    assert "Reconstruction quality explorer" in page, "dashboard heading not retitled"
    for stale in ("132 samples", "487 plasmids", "v3.0"):
        assert stale not in page, f"prototype header figure remains: {stale}"
    assert "hdrScope" in page and "hdrPlasmids" in page, "header must be run-driven"
    # Heatmap and plasmid panels share a row down to laptop widths.
    assert "@media (max-width: 900px)" in page, "grid must stay two-column above 900px"

    # Layout: 40/60 columns, with the heatmap column split into two equal rows.
    assert "minmax(0, 2fr) minmax(0, 3fr)" in page, "heatmap/plasmid split must be 40/60"
    # Row one is matrix beside plasmid recovery at equal height; the drilldown
    # spans the full width beneath, so contig evidence gets the horizontal room.
    assert "grid-column: 1 / -1" in page, "drilldown must span both columns"
    assert "left-stack" not in page, "the stacked left column has been replaced by explicit placement"
    # The drilldown belongs to the layout; only .expanded promotes it to an overlay.
    assert ".modal-overlay.expanded" in page, "drilldown must have an expanded state"
    assert "expandDrilldownBtn" in page, "drilldown must offer a full-screen control"
    assert "collapseDrilldown" in page, "escape and close must collapse, not hide"
    # Heading is readable on the light surface; the gradient fill was invisible.
    assert "-webkit-text-fill-color: transparent" not in page,         "gradient text fill is unreadable on the light surface"
    assert "color: #000;" in page, "dashboard heading must be black"

    # Capabilities restored after the consolidation regression.
    for needed in ("vq-nav", "vq-q", "vq-rows", "pointerdown", "vq-next-ev", "vq-sankey"):
        assert needed in page, f"restored explorer capability missing: {needed}"
    # Per-region agreement is a support count, never a correctness claim.
    for needed in ("vq-agree", "Method agreement across",
                   "Agreement is shared support, not evidence of correctness"):
        assert needed in page, f"tool agreement affordance missing: {needed}"
    # Baseline versus comparator, with the small-n caveat attached.
    for needed in ("vq-base", "vq-comp", "is not evidence of superiority"):
        assert needed in page, f"method comparison affordance missing: {needed}"
    # Accessibility and interoperability gaps closed.
    assert "prefers-reduced-motion" in page, "reduced-motion support missing"
    assert "vq-bed" in page, "BED export missing"
    assert "Arrow keys pan" in page, "tracks must be keyboard reachable"
    # Full segment and recovery vocabularies.
    for needed in ("seg-duplicated", "unsupported_join", "wrong_plasmid",
                   "complete_discordant", "chromosomal_contam"):
        assert needed in page, f"vocabulary term missing: {needed}"

    # Explorer chrome: titled cards with collapse, full-screen expand, and one
    # toolbar driving zoom, track height and density.
    for needed in ("vq-shell", "vq-toolbar", "vq-card", "vq-scrim",
                   "vq-expand-all", "vq-collapse-all", "vq-stretch", "vq-density",
                   "Truth plasmids", "Alignment tracks", "aria-expanded"):
        assert needed in page, f"explorer chrome affordance missing: {needed}"

    # The selected block reports the evidence measured from the alignment
    # record. Only the nucleotide view needs a CIGAR, so a block without one
    # must still show its spans, orientation, identity and mapping quality.
    for needed in ("Selected alignment block", "vq-kv", "Mapping quality",
                   "matching bases", "Orientation"):
        assert needed in page, f"selected-block evidence missing: {needed}"
    assert "No bounded CIGAR local alignment is available" not in page,         "a missing CIGAR must not replace the block's measured evidence"

    # Distribution plots are part of the default view, not hidden behind a toggle.
    for needed in ("boxPlotCanvas", "dotPlotCanvas", "Metric Distribution by Tool",
                   "Per-Sample Distribution"):
        assert needed in page, f"distribution plot missing: {needed}"
    assert 'id="statsPanel" style="display:none;"' not in page,         "distribution plots must not start hidden"
    assert "statsVisible: true" in page, "distribution plots must default to visible"

    # The adopted evidence explorer: its own chrome, controls and sub-views,
    # rendered in an isolated frame and driven by this report's selection.
    for needed in ("pb-explorer", "pb-explorer-doc", "explorerSample", "explorerPlasmid",
                   "splitMergeCanvas", "mainCanvas", "jumpMismatch", "jumpGap",
                   "jumpInversion", "jumpBreakpoint", "categoryChips", "colorMode",
                   "minAlignLen", "pinReference", "collapseContigs", "syncZoom",
                   "modeToggle", "detailsOverlay", "exportModal"):
        assert needed in page, f"explorer affordance missing: {needed}"
    assert "pbExplorer" in page, "report-to-explorer selection link missing"
    # The design shipped a dark application palette; the report is a light page.
    assert "--bg-primary: #f4f7f5" in page, "explorer must use the report's light ground"
    assert "--bg-primary: #080b11" not in page, "dark palette leaked into the report"
    # Nine measured segment types, not the design's six.
    for needed in ("low_identity", "unsupported_join", "wrong_plasmid", "chromosomal"):
        assert needed in page, f"explorer segment vocabulary incomplete: {needed}"
    # Unmeasured fields must say so.
    assert "read depth is not computed by projection scoring" in page,         "the unmeasured coverage field is not explained"
    assert "not measured" in page

    # Every method gets its own labelled row, sized to the space available.
    # The design used a fixed 20px track and a 7px label: with five methods the
    # rows were drawn but unreadable, so the view looked like it held one.
    assert "const trackH = state.mode === 'A' ? 20 : 32;" not in page,         "fixed track height must not come back; rows have to fit the container"
    for needed in ("const rowGap", "const rowCount", "clamp(fitted",
                   "state.rowOrder.map(id => TOOL_TRACKS.find"):
        assert needed in page, f"adaptive row layout missing: {needed}"
    # Scope the type checks to the explorer document: the report embeds two
    # vendored designs and only this one was rescaled.
    start = page.index("id='pb-explorer-doc'")
    explorer_doc = page[start:page.index("</script>", start)]
    # Canvas labels are drawn in JS and cannot inherit the CSS scale.
    assert "'7px Inter" not in explorer_doc and "'6px Inter" not in explorer_doc,         "explorer canvas labels must not be drawn at 6-7px"
    # No CSS declaration below 11px anywhere in the explorer.
    small = sorted({int(m) for m in re.findall(r"font-size: ?(\d+)px", explorer_doc)
                    if int(m) < 11})
    assert not small, f"explorer type scale still has unreadable sizes: {small}px"

    print("ALL VISUAL REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
