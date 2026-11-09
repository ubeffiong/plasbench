#!/usr/bin/env python3
"""
report_scoring_spec.py -- HTML report sections for the scoring specification and
the panel examination (docs/PANEL_ALIGNMENT.md, docs/PREREGISTRATION.md).

One call from build_html_report.py:
    page = report_scoring_spec.inject(page, sources)
where `sources` maps a name to the explicit file build_html_report.py was given
(06_aggregate.sh passes each one). Every section renders its values, or an
explicit "not run" note with the reason and the setting that controls it -- a
disabled feature never silently disappears.

Sections:
  prereg            pre-registration status (hash, lock, TO_FIX, departures)
  scoring-additions MCC / F2 / F0.5 / abstention, micro vs macro, per tool
  plasmid-outcomes  perfect / fragmented / merged / missed per tool, ARI
  label-schemes     the three labelling schemes, differing replicons, truth
                    grades, dimer corrections
  contig-layer      contig layer vs base layer, shared / unassigned lengths
  outcome-states    how every run ended, per tool
  recommender-eval  regret, near-optimal, gap closed, verdict; warning PPV
  taxon-transfer    leave-taxon-out and Wilcoxon / equivalence in comparisons
  amr-placement     AMR gene copies on the right plasmid, by gene class
  validity          tiered validity statement (validated / partly / extrapolated)

Standard library only.
"""

import csv
import html
import json
from collections import Counter
from pathlib import Path

import report_3d
import report_aliases

SECTIONS = (("prereg", "Pre-registration"), ("scoring-additions", "MCC &amp; F-beta"),
            ("plasmid-outcomes", "Plasmid outcomes"), ("label-schemes", "Label schemes"),
            ("contig-layer", "Contig layer"), ("outcome-states", "Run outcomes"),
            ("recommender-eval", "Recommender"), ("taxon-transfer", "Transfer &amp; tests"),
            ("amr-placement", "AMR placement"), ("validity", "Validity"))


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def read_tsv(path):
    if not path or not Path(path).is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    except ValueError:
        return {}


def cell(value):
    return esc(value) if value not in (None, "") else "-"


def table(headers, rows):
    return ("<div class='panel'><table class='sortable'><thead><tr>"
            + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>" for row in rows)
            + "</tbody></table></div>")


def not_run(what, why):
    return f"<p class='muted'><strong>Not run:</strong> {esc(what)}. {esc(why)}</p>"


def collapsible(inner, summary="Show the data table"):
    """The raw table behind a 3D view: collapsed, but in the page for print, screen readers and no-JS."""
    return f"<details class='rpt-collapsible'><summary>{esc(summary)}</summary>{inner}</details>"


def section(section_id, title, lead, body):
    return f"<section id='{section_id}'><h2>{title}</h2><p class='lead'>{lead}</p>{body}</section>"


def prereg_section(manifest):
    pre = (manifest or {}).get("preregistration") or {}
    if not pre or pre.get("error") and not pre.get("sha256"):
        body = not_run("pre-registration status", f"no prereg record in the run manifest {pre.get('error', '')}".strip())
    else:
        state = ("frozen and unchanged" if pre.get("locked") and pre.get("matches")
                 else "frozen, but prereg.tsv CHANGED after the freeze" if pre.get("locked")
                 else "not frozen yet (run: plasbench analysis freeze-prereg --write)")
        departures = pre.get("env_mismatches") or []
        body = table(["Item", "Value"], [
            ("prereg.tsv SHA-256", pre.get("sha256", "")), ("State", state), ("Frozen at", pre.get("frozen_at") or "-"),
            ("Parameters", pre.get("parameters", "")),
            ("Still TO_FIX", ", ".join(pre.get("to_fix") or []) or "none"),
            ("Settings departing from the plan",
             "; ".join(f"{m['config_variable']}={m['actual']} (planned {m['planned']})" for m in departures) or "none")])
    return section("prereg", "Pre-registration", "Every scoring decision is fixed in config/prereg.tsv before results "
                   "are seen (docs/PREREGISTRATION.md). This run's settings are checked against it.", body)


def scoring_additions_section(leaderboard):
    rows = [r for r in leaderboard if r.get("tool")]
    if not rows or not any(r.get("mean_mcc") or r.get("mean_f2") for r in rows):
        body = not_run("MCC / F2 / F0.5", "the leaderboard has no mcc/f2/f0_5 columns (scores from before this version)")
    else:
        body = table(["Track / task", "Tool", "F1 (macro)", "F1 (micro)", "MCC", "F2 (recall-weighted)",
                      "F0.5 (precision-weighted)", "Abstention rate"],
                     [(f"{r.get('analysis_track')} / {r.get('task')}", r["tool"], r.get("mean_f1"), r.get("micro_f1"),
                       r.get("mean_mcc"), r.get("mean_f2"), r.get("mean_f0_5"), r.get("mean_abstention_rate"))
                      for r in rows])
    return section("scoring-additions", "MCC, F2, F0.5 and abstention",
                   "Base-level, against the reference. MCC uses chromosome bases not predicted as true negatives and "
                   "is blank (undefined) on plasmid-free isolates. F2 favours recall, F0.5 precision. Abstention rate "
                   "is the share of isolates on which the tool returned nothing. Macro averages isolates; micro pools "
                   "bases. None of these changes the ranking metric.", body)


def outcomes_section(leaderboard):
    keys = ("total_outcome_perfect", "total_outcome_fragmented", "total_outcome_merged",
            "total_outcome_fragmented_and_merged", "total_outcome_partial", "total_outcome_missed")
    rows = [r for r in leaderboard if r.get("tool") and any(r.get(k) not in (None, "") for k in keys)]
    if not rows:
        body = not_run("per-plasmid outcome states", "no binning tool was scored (score_bins.py runs only for "
                       "binning-capable tools with a bins file)")
    else:
        body = table(["Track / task", "Tool", "Perfect", "Fragmented", "Merged", "Fragmented and merged", "Partial",
                      "Missed", "ARI"],
                     [(f"{r.get('analysis_track')} / {r.get('task')}", r["tool"], *(r.get(k) for k in keys),
                       r.get("mean_bin_ari")) for r in rows])
    return section("plasmid-outcomes", "Per-plasmid outcomes",
                   "Each truth plasmid, judged on the bin holding most of it: perfect when that bin's precision and "
                   "recall reach PERFECT_THRESHOLD (0.95); fragmented when another bin holds at least FRAGMENT_SHARE "
                   "(0.20) of it; merged when its bin also holds that share of another plasmid; missed when best-bin "
                   "recall is below MISSED_RECALL (0.50). Counts summed over isolates; ARI is the bp-weighted "
                   "Adjusted Rand Index of the bins.", body)


def label_schemes_section(summary, schemes, provenance, data_dir):
    parts = []
    if summary:
        parts.append(table(["Scheme", "Role", "Samples", "Replicons", "Plasmids", "Plasmid bp", "Excluded (AMBIGUOUS)",
                            "Plasmid calls differing from primary", "Scored file"],
                           [(r["scheme"], r["role"], r["samples"], r["replicons"], r["plasmids"], r["plasmid_bp"],
                             r["excluded_replicons"], r["plasmids_differing_from_primary"], r["scored_file"])
                            for r in summary]))
        differing = [r for r in schemes if r.get("schemes_agree") == "no"]
        if differing:
            parts.append("<h3>Replicons labelled differently across schemes</h3>" + table(
                ["Sample", "Replicon", "Length", "NCBI (primary)", "Non-chromosomal", "Evidence", "Why", "Multimer"],
                [(r["sample"], r["sequence_id"], r["length"], r["ncbi_label"], r["nonchromosomal_label"],
                  r["evidence_label"], r.get("evidence_reason"), r.get("multimer")) for r in differing[:200]]))
        fields = Counter(r.get("ncbi_label_field", "") for r in schemes)
        parts.append("<p class='muted'>NCBI label field per replicon: "
                     + esc(", ".join(f"{k or 'unknown'} {v}" for k, v in sorted(fields.items()))) + ".</p>")
    else:
        parts.append(not_run("label-scheme table", "stage 2 wrote no <sample>/label_schemes.tsv"))
    grades = Counter(r.get("truth_quality_grade", "") for r in provenance if r.get("truth_quality_grade"))
    parts.append("<p>Truth quality grades: " + (esc(", ".join(f"{g} {n}" for g, n in sorted(grades.items())))
                                                if grades else "not recorded in this run") +
                 ". A needs reference tier 1 and same_extraction=yes in the sample sheet; tier 3 is C.</p>")
    corrections = []
    if data_dir and Path(data_dir).is_dir():
        for path in sorted(Path(data_dir).glob("*/truth.corrections.tsv")):
            corrections += [(path.parent.name, r) for r in read_tsv(path)]
    parts.append("<h3>Dimer corrections</h3>" + (table(
        ["Sample", "Replicon", "Original length", "Scored length", "Half identity", "Method", "Action"],
        [(s, r["sequence_id"], r["original_length"], r["corrected_length"], r["identity"], r["method"], r["action"])
         for s, r in corrections]) if corrections else
        "<p class='muted'>No tandem-dimer truth plasmid was found (or RUN_DIMER_DETECTION=0).</p>"))
    return section("label-schemes", "Labelling schemes, truth grades and dimers",
                   "The headline is scored on the pre-registered Scheme 3, NCBI sequence-report labels. Scheme 1 "
                   "(every replicon but the main chromosome is a plasmid) and the evidence scheme (labels confirmed by "
                   "plasmid markers, rRNA genes and long reads; conflicts excluded) are re-ranked as sensitivity "
                   "analyses in the " + report_aliases.link("rank-robustness", "ranking robustness") + " table (variants scheme:...).", "".join(parts))


def crosscheck_summary(rows):
    """(status text, basis) for the contig layer from contig_crosscheck.py compare rows."""
    if not rows:
        return "implemented, not cross-checked in this run", "no independent-scorer table (RUN_CONTIG_CROSSCHECK=0, or no contigs)"
    deltas = [float(r["delta_f1_bp"]) for r in rows if r.get("delta_f1_bp")]
    disagree = sum(r.get("status") == "disagree" for r in rows)
    worst = f"max |delta F1| {max(deltas):.4f}" if deltas else "no defined F1"
    if disagree:
        return "cross-checked: disagreements", f"{disagree} of {len(rows)} (sample, tool) pairs differ beyond 0.02; {worst}"
    return "cross-checked against an independent scorer", f"{len(rows)} (sample, tool) pairs agree within 0.02; {worst}"


def contig_layer_section(leaderboard, scores, crosscheck=()):
    rows = [r for r in leaderboard if r.get("tool")]
    have = [r for r in rows if r.get("mean_contig_f1_bp")]
    status, basis = crosscheck_summary(crosscheck)
    tables = ""
    drawn = False          # the 3D view carries its own "Independent second scorer" card; the paragraph below is only for when it is not drawn
    if not have:
        body = not_run("contig layer", "no tool was scored at contig level (RUN_CONTIG_CLASSIFICATION=0, no "
                       "contigs.fasta, or every tool outputs reassembled sequences)")
    else:
        shared = sum(int(r.get("contigs_ambiguous_bp") or 0) for r in scores)
        unassigned = sum(int(r.get("contigs_unplaced_bp") or 0) for r in scores)
        payload = report_3d.bars_payload(leaderboard, scores, crosscheck)
        scene = report_3d.build_bars(payload)
        body = report_3d.host("bars", "v3-data-contig", payload, scene, -28, 24) if scene["prims"] else ""
        drawn = bool(scene["prims"])
        body += (f"<p class='muted'>Excluded contig length summed over scored runs: shared (AMBIGUOUS) {shared:,} bp, "
                 f"unassigned (UNPLACED) {unassigned:,} bp.</p>")
        tables = table(["Track / task", "Tool", "Base F1 (reference layer)", "Contig F1 (length)", "Contig MCC (length)",
                        "Contig binning F1 (length)"],
                       [(f"{r.get('analysis_track')} / {r.get('task')}", r["tool"], r.get("mean_f1"),
                         r.get("mean_contig_f1_bp"), r.get("mean_contig_mcc_bp"), r.get("mean_contig_bin_f1_bp"))
                        for r in have])
    if not drawn:
        body += f"<h3>Independent second scorer</h3><p>{esc(status)}: {esc(basis)}.</p>"
    if crosscheck:
        tables += table(report_3d.XC_HEADER, [[r.get(f, "") for f in report_3d.XC_FIELDS] for r in crosscheck])
    else:
        body += not_run("independent contig scorer", "no benchmark.contig_crosscheck.tsv (RUN_CONTIG_CROSSCHECK=0 or no contig labels)")
    if tables:
        body += collapsible(tables)
    return section("contig-layer", "Contig layer beside the reference layer",
                   "A parallel layer, never the headline: assembly contigs are labelled against the reference and each "
                   "tool's calls scored per contig, weighted by length. Its recall denominator is the summed length of "
                   "the contigs assigned to each plasmid, a contig-layer-only definition.", body)


def outcome_states_section(states, status_rows=()):
    if not states:
        body = not_run("run outcome states", "no tool_status.tsv was given to aggregation")
    else:
        body = table(["Track", "Tool", "Runs", "Completed", "Reused", "Failed (tool)", "Failed (resource)",
                      "Infrastructure failure", "Not applicable", "Retried"],
                     [(r.get("analysis_track"), r["tool"], r["n_runs"], r["completed"], r["reused"], r["failed_tool"],
                       r["failed_resource"], r["infrastructure_failure"], r["not_applicable"], r["retried"])
                      for r in states])
        # Tools compared (panel D15): why each tool did not run or did not finish.
        reasons = {}
        for row in status_rows:
            if row.get("status") not in ("completed", "reused") and row.get("tool"):
                reason = (row.get("reason") or "no reason recorded").split("; exit_code")[0]
                reasons.setdefault((row["tool"], row.get("status")), Counter())[reason] += 1
        if reasons:
            body += "<h3>Tools compared: why runs were skipped or failed</h3>" + table(
                ["Tool", "Status", "Runs", "Reason (most common)"],
                [(tool, status, sum(c.values()), c.most_common(1)[0][0]) for (tool, status), c in sorted(reasons.items())])
        else:
            body += "<p class='muted'>Every run of every tool completed.</p>"
    return section("outcome-states", "How every run ended",
                   "Decision D6: a tool crash or missing output scores F1 = 0 and counts in the ranking. A resource "
                   "failure (timeout 124, out-of-memory 137) is scored 0 by default. An infrastructure failure (the "
                   "container or command never started, exit 125-127, or the disk filled) says nothing about the tool: "
                   "it is never scored and should be rerun. Not applicable = skipped (input the tool cannot use). "
                   "Failed runs are retried TOOL_RETRIES times; every tool gets the same TOOL_TIMEOUT_SECONDS.", body)


def recommender_section(evaluation, verdict, warnings, regret=(), taxon=()):
    tables = ""
    if not evaluation:
        body = not_run("recommender evaluation", "RUN_RECOMMENDER_EVAL=0, or evaluate_recommender.py failed")
    else:
        payload = report_3d.recs_payload(evaluation, regret, verdict, warnings, taxon)
        scene = report_3d.build_recs(payload)
        banner = report_3d.verdict_banner(verdict) if verdict else ""
        if scene["prims"]:
            body = report_3d.host("recs", "v3-data-recs", payload, scene, -24, 36, banner)
        else:
            body = banner + ("<p class='muted'>The per-isolate regret table (benchmark.recommender_regret.tsv) is not available, "
                             "so the strategies cannot be drawn in 3D; the profile summary is below.</p>")
            if verdict:
                body += f"<p><strong>Verdict:</strong> {esc(verdict.get('verdict'))} -- {esc(verdict.get('note'))}</p>"
        tables = table(report_3d.EVAL_HEADER, [[r.get(f, "") for f in report_3d.EVAL_FIELDS] for r in evaluation])
    if warnings:
        tables += "<h3>Warnings scored against failed recommendations</h3>" + table(
            ["Warning", "Evaluated", "Fired", "Failed", "Firing rate", "PPV", "Sensitivity", "Could not be applied",
             "Status"],
            [(r["warning"], r["n_evaluated"], r["n_fired"], r["n_failed"], r["firing_rate"], r["ppv"], r["sensitivity"],
              r["n_could_not_be_applied"], r["status"]) for r in warnings])
    else:
        body += not_run("warning scoring", "no warnings table (needs the recommender evaluation and at least one warning "
                        "source: cohort QC flags or the assembly QC gate)")
    if tables:
        body += collapsible(tables)
    return section("recommender-eval", "Does recommending per isolate beat the single best tool?",
                   "Leave-one-study-out. Regret = best tool's F1 on the isolate minus the recommended tool's. "
                   "Near-optimal = regret within NEAR_OPTIMAL_MARGIN (0.05). Gap closed = 1 - recommender regret / "
                   "single-best regret. When the oracle gap is below ORACLE_GAP_FLOOR (0.02) the verdict is "
                   "benchmark_only: report the leaderboard and do not recommend per isolate. A recommendation failed "
                   "when its regret exceeds RECOMMENDATION_FAILURE_REGRET (0.10).", body)


def transfer_section(taxon_rows, comparisons):
    parts = []
    if taxon_rows:
        parts.append(table(["Level", "Held-out group", "Isolates", "Training isolates", "Mean regret",
                            "Single-best regret", "Near-optimal", "Gap closed", "Status", "Note"],
                           [(r["level"], r["held_out_group"], r["n_isolates"], r["n_training_isolates"],
                             r["mean_regret"], r["single_best_mean_regret"], r["near_optimal_rate"], r["gap_closed"],
                             r["status"], r["note"]) for r in taxon_rows]))
    else:
        parts.append(not_run("leave-taxon-out", "RUN_RECOMMENDER_EVAL=0 or no genus/phylum recorded"))
    # The paired comparisons (permutation, Wilcoxon, equivalence) are shown once, in the Paired tests tab of Ranking confidence: a second
    # copy here could drift from it. This section keeps the transfer evidence and points to the one table.
    parts.append("<p class='muted'>Paired comparisons between tools (permutation, Wilcoxon and equivalence) are in "
                 "<a href='#statistics'>Ranking confidence, Paired tests</a>.</p>")
    return section("taxon-transfer", "Transfer to unseen taxa, and paired tests",
                   "Leave-one-genus-out and leave-one-phylum-out regret; isolates without a taxon are counted, not "
                   "dropped. split=holdout isolates stay locked until evaluated once with --confirm-holdout.",
                   "".join(parts))


AMR_LEAD = ("Each curated AMR gene copy is matched by position. Level 2: the bin holding it is matched "
            "one-to-one to the gene's own plasmid. Level 1: that plasmid shares a replicon type with the gene's "
            "plasmid. Copies on shared or unassigned contigs are their own category. Gene classes come from "
            "config/amr_gene_classes.tsv.")


def amr_section(rows, data_dir=None):
    if not rows:
        return section("amr-placement", "AMR genes on the right plasmid", AMR_LEAD,
                       not_run("AMR placement", "no curated truth_amr.tsv passed validation, or RUN_AMR_PLACEMENT=0"))
    tables = table(["Tool", "Gene class", "Gene copies", "Recovered", "Correct plasmid", "Wrong plasmid",
                    "Shared contig", "Unassigned contig", "Correct-plasmid rate", "Replicon-type correct"],
                   [(r["tool"], r["gene_class"], r["n_gene_copies"], r["n_recovered"], r["n_correct_plasmid"],
                     r["n_wrong_plasmid"], r["n_shared_contig"], r["n_unassigned_contig"], r["correct_plasmid_rate"],
                     r["replicon_type_correct_rate"]) for r in rows])
    payload = report_3d.rings_payload(data_dir)
    scene = report_3d.build_rings(payload) if payload else {"prims": []}
    if not scene["prims"]:
        note = ("<p class='muted'>The per-sample placement files (&lt;sample&gt;/&lt;tool&gt;.amr_placement.tsv) were not found, "
                "so the ring view is unavailable; the summary table is below.</p>")
        return section("amr-placement", "AMR genes on the right plasmid", AMR_LEAD, note + tables)
    return section("amr-placement", "AMR genes on the right plasmid", AMR_LEAD,
                   report_3d.host("rings", "v3-data-amr", payload, scene, -18, 26) + collapsible(tables))


def validity_section(leaderboard, provenance, evaluation, crosscheck=()):
    tiers = Counter(r.get("reference_tier", "") for r in provenance)
    studies = max((int(r.get("n_folds") or 0) for r in evaluation), default=0)
    validated = tiers.get("1", 0) + tiers.get("2", 0)
    if validated and studies >= 3:
        level, why = "validated", f"{validated} long-read-first isolate(s) across {studies} held-out studies"
    elif validated:
        level, why = "partially validated", (f"{validated} long-read-first isolate(s), but only {studies} held-out "
                                             "stud(ies) for the recommender")
    else:
        level, why = "extrapolated", "no long-read-first (tier 1-2) truth in this run"
    body = table(["Claim", "Status", "Basis"], [
        ("Tool ranking on these isolates", level, why),
        ("Recommendation for a new isolate of a species in the cohort",
         "partially validated" if studies >= 2 else "extrapolated", f"leave-one-study-out over {studies} fold(s)"),
        ("Recommendation for a species or genus not in the cohort", "extrapolated",
         "see leave-taxon-out; no claim beyond the genera evaluated"),
        ("Contig layer", *crosscheck_summary(crosscheck)),
    ])
    return section("validity", "What these results are valid for",
                   "Tiered from the reference tiers, the number of independent studies and the evaluation coverage. "
                   "Validated means measured on held-out data here; extrapolated means it is not.", body)


def markdown(sources):
    """Plain-text summary written next to the report (benchmark.scoring_spec.md)."""
    pre = (read_json(sources.get("manifest")) or {}).get("preregistration") or {}
    verdict = read_json(sources.get("recommender_verdict"))
    lines = ["# Scoring specification summary", "",
             f"- Pre-registration: sha256 {pre.get('sha256', 'n/a')[:12]}..., "
             f"{'frozen' if pre.get('locked') else 'not frozen'}"
             f"{', matches' if pre.get('matches') else ''}; TO_FIX: {', '.join(pre.get('to_fix') or []) or 'none'}",
             f"- Recommender verdict: {verdict.get('verdict', 'not run')} (oracle gap {verdict.get('oracle_gap', 'n/a')}, "
             f"gap closed {verdict.get('gap_closed', 'n/a')})", ""]
    summary = read_tsv(sources.get("label_scheme_summary"))
    if summary:
        lines += ["| Scheme | Role | Plasmids | Differing from primary |", "|---|---|---|---|"]
        lines += [f"| {r['scheme']} | {r['role']} | {r['plasmids']} | {r['plasmids_differing_from_primary']} |"
                  for r in summary]
        lines.append("")
    states = read_tsv(sources.get("outcome_states"))
    if states:
        lines += ["| Tool | Runs | Failed (tool) | Failed (resource) | Infrastructure | Not applicable |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {r['tool']} | {r['n_runs']} | {r['failed_tool']} | {r['failed_resource']} | "
                  f"{r['infrastructure_failure']} | {r['not_applicable']} |" for r in states]
    return "\n".join(lines) + "\n"


def regret_path(sources):
    """benchmark.recommender_regret.tsv sits beside benchmark.recommender_eval.tsv (an explicit source wins)."""
    if sources.get("recommender_regret"):
        return sources["recommender_regret"]
    eval_path = sources.get("recommender_eval")
    if eval_path:
        path = Path(eval_path)
        if "recommender_eval" in path.name:
            return path.with_name(path.name.replace("recommender_eval", "recommender_regret"))
    return None


def inject(page, sources):
    """Insert every section before Recommendations, with nav links."""
    leaderboard = read_tsv(sources.get("leaderboard"))
    provenance = read_tsv(sources.get("truth_provenance"))
    evaluation = read_tsv(sources.get("recommender_eval"))
    crosscheck = read_tsv(sources.get("contig_crosscheck"))
    taxon = read_tsv(sources.get("leave_taxon_out"))
    html_sections = (
        prereg_section(read_json(sources.get("manifest")))
        + scoring_additions_section(leaderboard)
        + outcomes_section(leaderboard)
        + label_schemes_section(read_tsv(sources.get("label_scheme_summary")), read_tsv(sources.get("label_schemes")),
                                provenance, sources.get("data_dir"))
        + contig_layer_section(leaderboard, read_tsv(sources.get("scores")), crosscheck)
        + outcome_states_section(read_tsv(sources.get("outcome_states")), read_tsv(sources.get("tool_status")))
        + recommender_section(evaluation, read_json(sources.get("recommender_verdict")),
                              read_tsv(sources.get("warning_eval")), read_tsv(regret_path(sources)), taxon)
        + transfer_section(taxon, read_tsv(sources.get("comparisons")))
        + amr_section(read_tsv(sources.get("amr_placement")), sources.get("data_dir"))
        + validity_section(leaderboard, provenance, evaluation, crosscheck))
    if "class='v3'" in html_sections:
        html_sections = report_3d.assets() + html_sections   # the 3D engine, once, before the first view
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, html_sections + anchor, 1)
        nav_anchor = "<a href='#recommendations'>Recommendations</a>"
        links = "".join(f"<a href='#{section_id}'>{label}</a>" for section_id, label in SECTIONS)
        page = page.replace(nav_anchor, links + nav_anchor, 1)
    return page
