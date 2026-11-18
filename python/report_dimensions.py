#!/usr/bin/env python3
"""HTML sections for the further benchmark dimensions, built from stage-6 tables.

build_html_report.py calls `render(prefix, esc, link)` once and places the returned
(navigation, sections) in the page. Every section is advisory: it never changes the leaderboard,
says what its numbers are and are not, shows an explicit empty state when its table was not
produced (a missing table means "not evaluated", never "zero"), and links the raw table.

Tables read, all written beside the leaderboard as <prefix>.<name>.tsv:
  accuracy, missing_regions, feature_preservation, ngoc, bin_quality, performance, power,
  scenarios, scenario_performance, composite, composite_sensitivity, reproducibility_tools, stats_validation, stats_validation_by_studies
"""
import csv
import os
from collections import defaultdict
from plasbench_common import number as num  # noqa: E402
from plasbench_common import display_tool_name  # noqa: E402
import report_compare_apply as apply  # noqa: E402  (comparison tables that keep each plain table in a closed fold)

TABLES = ("accuracy", "missing_regions", "feature_preservation", "ngoc", "bin_quality", "performance", "power",
          "scenarios", "scenario_performance", "composite", "composite_sensitivity", "reproducibility_tools", "stats_validation", "stats_validation_by_studies")


def read_tsv(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def pct(value, digits=1):
    return "-" if value is None else f"{100 * value:.{digits}f}%"


def flt(value, digits=3):
    return "-" if value is None else f"{value:.{digits}f}"


def total(rows, key):
    values = [v for v in (num(r.get(key)) for r in rows) if v is not None]
    return sum(values) if values else None


def ratio(a, b):
    return None if a is None or not b else a / b


def group(rows, *keys):
    out = defaultdict(list)
    for row in rows:
        out[tuple(row.get(k) or "" for k in keys)].append(row)
    return dict(sorted(out.items()))


def table(esc, headers, body, empty_cols=None):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    rows = "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in row) + "</tr>" for row in body)
    return f"<div class='panel'><table class='sortable'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>"


def per_isolate(rows, column, scale=1.0):
    """(track, tool) -> {isolate: value} of one column of a per-sample table (a blank is left out, never zero); `scale` 100 puts a fraction on the percent scale of the cell."""
    def get(track, tool):
        out = {}
        for r in rows:
            if r.get("tool") == tool and (not track or (r.get("analysis_track") or "") == track):
                v = num(r.get(column))
                if v is not None:
                    out[r.get("sample", "")] = v * scale
        return out
    return get


def empty(message):
    return f"<div class='panel'><p>{message}</p></div>"


def section(esc, sid, title, lead, body, link_html=""):
    return (f"<section id='{sid}'><h2>{esc(title)}</h2><p class='lead'>{lead}{link_html}</p>{body}</section>")


def render(prefix, esc, link, scores_path=None, samples_path=None):
    """(nav_html, sections_html). `link(path)` returns a relative href for a downloadable table."""
    data = {name: read_tsv(f"{prefix}.{name}.tsv") for name in TABLES}

    def download(*names):
        parts = [f" <a href='{esc(link(f'{prefix}.{n}.tsv'))}' download>{esc(n.replace('_', ' '))} table</a>"
                 for n in names if os.path.isfile(f"{prefix}.{n}.tsv")]
        return (" Download:" + ",".join(parts) + ".") if parts else ""

    sections, nav = [], []

    def add(sid, title, lead, body, *names):
        sections.append(section(esc, sid, title, lead, body, download(*names)))
        nav.append(f"<a href='#{sid}'>{esc(title)}</a>")

    # 1. Accuracy and missing regions ---------------------------------------------------------
    rows = []
    miss = group(data["missing_regions"], "analysis_track", "tool")
    for (track, tool), items in group(data["accuracy"], "analysis_track", "tool").items():
        assessable = [i for i in items if i.get("identity")]
        not_assessable = len([i for i in items if i.get("accuracy_status", "").startswith("not_assessable")])
        cols = total(assessable, "aligned_columns")
        m = miss.get((track, tool), [])
        plasmids = len(m)
        rows.append([track, tool, len(items), pct(ratio(total([{"v": (num(i["identity"]) or 0) * (num(i["aligned_columns"]) or 0)}
                                                                for i in assessable], "v"), cols), 2),
                     pct(ratio(total(assessable, "mismatch_bp"), cols), 2), pct(ratio(total(assessable, "inserted_bp"), cols), 2),
                     pct(ratio(total(assessable, "deleted_bp"), cols), 2), not_assessable,
                     int(total(items, "n_blocks_without_cigar") or 0),
                     plasmids, flt(ratio(total(m, "missing_regions"), plasmids), 2),
                     int(total(m, "missing_bp") or 0), int(max([num(x["longest_missing_bp"]) or 0 for x in m] or [0]))])
    add("accuracy-dimension", "Sequence accuracy and missing regions",
        "Coverage says how much of a plasmid was recovered; this says whether the recovered bases are right. Identity, "
        "mismatch, insertion and deletion are shares of the alignment columns of the retained blocks on truth plasmids, "
        "so they sum to 100%. They are blank for samples whose truth was polished with the benchmark's own reads (not assessable: "
        "the truth would carry the reads' own errors), the same rule the CPRR identity criterion uses. Blocks without a CIGAR cannot be decoded and are counted, never guessed. Missing regions "
        "are reference stretches no retained alignment covers (a circular plasmid's gap across the origin counts as two). "
        "<strong>Descriptive only: it never changes the leaderboard.</strong> SNP concordance is not computed: it needs "
        "known variant positions, which a single same-isolate reference does not have.",
        apply.from_table("accuracy", "Sequence accuracy", rows, 1, [
            ("Alignment accuracy", 3, "identity", "Identity", dict(source="accuracy", column="identity", unit="% of aligned columns", iso=per_isolate(data["accuracy"], "identity", 100))),
            ("Alignment accuracy", 4, "mismatch", "Mismatch", dict(source="accuracy", column="mismatch_rate", unit="% of aligned columns", iso=per_isolate(data["accuracy"], "mismatch_rate", 100))),
            ("Alignment accuracy", 5, "insertion", "Insertion", dict(dir="lower", unit="% of aligned columns", definition="Share of aligned columns that are insertions. A component of indel accuracy (A3 = 1 - insertions - deletions), so lower is better.", source="accuracy", column="insertion_rate", iso=per_isolate(data["accuracy"], "insertion_rate", 100))),
            ("Alignment accuracy", 6, "deletion", "Deletion", dict(dir="lower", unit="% of aligned columns", definition="Share of aligned columns that are deletions. A component of indel accuracy (A3 = 1 - insertions - deletions), so lower is better.", source="accuracy", column="deletion_rate", iso=per_isolate(data["accuracy"], "deletion_rate", 100))),
            ("Missing regions", 10, "missing_per", "Missing regions per plasmid", dict(dir=None, definition="Reference stretches no retained alignment covers, per plasmid. No direction is defined in the metric registry, so it is not shaded.")),
            ("Missing regions", 11, "missing_bp", "Missing bp", dict(dir=None, unit="bp", definition="Reference bases in missing regions. No direction is defined in the metric registry, so it is not shaded.")),
            ("Missing regions", 12, "longest_gap", "Longest gap (bp)", dict(dir=None, unit="bp", definition="The longest missing region. No direction is defined in the metric registry, so it is not shaded.")),
            ("Counts", 2, "samples", "Samples", dict(dir=None, definition="Isolates scored for this tool. A count.")),
            ("Counts", 7, "not_assessable", "Samples not assessable", dict(dir=None, definition="Samples whose truth was polished with the benchmark's own reads, so accuracy cannot be assessed.")),
            ("Counts", 8, "no_cigar", "Blocks without CIGAR", dict(dir=None, definition="Alignment blocks that cannot be decoded; counted, never guessed.")),
            ("Counts", 9, "plasmids", "Plasmids", dict(dir=None, definition="Truth plasmids examined for missing regions.")),
        ], track_col=0, table_html=table(esc, ["Track", "Tool", "Samples", "Identity", "Mismatch", "Insertion", "Deletion", "Samples not assessable", "Blocks without CIGAR",
                    "Plasmids", "Missing regions per plasmid", "Missing bp", "Longest gap (bp)"], rows), label=display_tool_name)
        if rows else empty("No accuracy table was available. It needs a PAF with CIGAR tags (<code>minimap2 -c</code>); "
                           "stage 5 writes it when <code>RUN_DIMENSION_ANALYSES=1</code>."),
        "accuracy", "missing_regions")

    # 2. Feature preservation and NGOC --------------------------------------------------------
    rows = []
    for (track, tool, kind), items in group(data["feature_preservation"], "analysis_track", "tool", "feature_kind").items():
        n = total(items, "n_expected")
        rows.append([track, tool, kind, int(n or 0), int(total(items, "n_full_length") or 0),
                     int(total(items, "n_truncated") or 0), int(total(items, "n_missed") or 0),
                     pct(ratio(total(items, "n_full_length"), n)),
                     pct(ratio(total([{"v": (num(i["mean_covered_fraction"]) or 0) * (num(i["n_expected"]) or 0)}
                                      for i in items], "v"), n))])
    ngoc_rows = []
    for (track, tool), items in group(data["ngoc"], "analysis_track", "tool").items():
        pairs = total(items, "n_pairs")
        ngoc_rows.append([track, tool, int(max(num(i["ngoc_features"]) or 0 for i in items)), int(pairs or 0),
                          int(total(items, "n_conserved") or 0), pct(ratio(total(items, "n_conserved"), pairs))])
    body = ""
    if rows:
        body += apply.features(rows, table(esc, ["Track", "Tool", "Feature kind", "Expected", "Full length", "Truncated", "Missed",
                            "Full-length rate", "Mean covered fraction"], rows), display_tool_name)
    if ngoc_rows:
        body += apply.from_table("ngoc", "Gene-order conservation (NGOC)", ngoc_rows, 1, [
            ("Gene order", 5, "ngoc", "NGOC", dict(source="ngoc", column="ngoc", iso=per_isolate(data["ngoc"], "ngoc", 100), unit="%")),
            ("Gene order", 2, "features", "Features used", dict(dir=None, definition="Features the order was judged on. A count.")),
            ("Gene order", 3, "pairs", "Adjacent pairs", dict(dir=None, definition="Adjacent feature pairs in the reference. A count.")),
            ("Gene order", 4, "conserved", "Conserved", dict(dir=None, definition="Pairs still adjacent, in the same orientation, on the same predicted record. A count.")),
        ], track_col=0, table_html=table(esc, ["Track", "Tool", "Features used", "Adjacent pairs", "Conserved", "NGOC"], ngoc_rows), label=display_tool_name)
    add("feature-preservation", "Feature preservation and gene order",
        "Whether the genes and functional elements survive, and stay in order. Each truth feature is projected through the "
        "alignments: <em>full length</em> means at least 95% covered, <em>truncated</em> means covered but less, "
        "<em>missed</em> means not covered; a truncated gene is not counted as recovered. NGOC is the share of adjacent "
        "feature pairs in the reference that are still adjacent, in the same orientation, on the same predicted record "
        "(strand and circularity aware); a missed feature breaks its pairs. With a gene table it is gene-order "
        "conservation, with landmark features only it is landmark-order conservation (the feature count says which). "
        "<strong>Descriptive only.</strong>",
        body or empty("No feature-preservation table was available. It needs an annotated truth (<code>truth_proteins.tsv</code> "
                      "or <code>truth_features.tsv</code>); samples without annotation are not evaluated, not scored zero."),
        "feature_preservation", "ngoc")

    # 3. Bin quality --------------------------------------------------------------------------
    rows = []
    for (track, tool), items in group(data["bin_quality"], "analysis_track", "tool").items():
        plasmids = total(items, "n_truth_plasmids")
        mean = lambda k: (sum(v for v in (num(i.get(k)) for i in items) if v is not None) /
                          len([1 for i in items if num(i.get(k)) is not None])) if any(num(i.get(k)) is not None for i in items) else None
        rows.append([track, tool, int(total(items, "n_bins") or 0), int(total(items, "n_high") or 0),
                     int(total(items, "n_medium") or 0), int(total(items, "n_low") or 0),
                     int(total(items, "n_spurious") or 0), pct(ratio(total(items, "plasmids_with_high_bin"), plasmids)),
                     pct(ratio(total(items, "plasmids_with_medium_or_better_bin"), plasmids)),
                     flt(mean("homogeneity")), flt(mean("completeness")), flt(mean("v_measure"))])
    add("bin-quality", "Bin quality tiers",
        "Would a surveillance laboratory trust the bin? <strong>These are secondary diagnostics: the binning endpoint is the length-weighted binning F1 and CPRR in the leaderboard, and nothing here competes with it.</strong> Each bin is matched to its best truth plasmid: <em>high</em> is at "
        "least 90% complete and at most 5% contaminated, <em>medium</em> at least 50% and at most 10%, <em>low</em> is any "
        "other bin on a plasmid, <em>spurious</em> aligns to no plasmid. Yield is the share of truth plasmids with such a "
        "bin (a split plasmid is judged by its best bin). Homogeneity, completeness and V-measure use the same "
        "base-pair weighted table as NMI: informative about binning behaviour, not primary evidence, and not repeat-aware. "
        "<strong>Descriptive only.</strong> Binning-capable tools only.",
        apply.from_table("binquality", "Bin quality tiers", rows, 1, [
            ("Yield", 7, "hq_yield", "High-quality yield", dict(dir="higher", unit="% of truth plasmids", definition="Share of truth plasmids with a high-quality bin (at least 90% complete, at most 5% contaminated). Higher is better.", iso=per_isolate(data["bin_quality"], "high_quality_yield", 100))),
            ("Yield", 8, "mq_yield", "Medium-or-better yield", dict(dir="higher", unit="% of truth plasmids", definition="Share of truth plasmids with a medium or better bin (at least 50% complete, at most 10% contaminated). Higher is better.", iso=per_isolate(data["bin_quality"], "medium_or_better_yield", 100))),
            ("Agreement with the truth", 9, "homogeneity", "Homogeneity", dict(dir="higher", definition="Each bin holds sequence of one plasmid only (0 to 1; 1 is best).", iso=per_isolate(data["bin_quality"], "homogeneity"))),
            ("Agreement with the truth", 10, "completeness", "Completeness", dict(dir="higher", definition="Each plasmid is held in one bin (0 to 1; 1 is best). Base-pair weighted, like NMI.", iso=per_isolate(data["bin_quality"], "completeness"))),
            ("Agreement with the truth", 11, "v_measure", "V-measure", dict(dir="higher", definition="The harmonic mean of homogeneity and completeness (0 to 1; 1 is best).", iso=per_isolate(data["bin_quality"], "v_measure"))),
            ("Bins by tier (counts)", 2, "bins", "Bins", dict(dir=None, definition="Bins produced. A count.")),
            ("Bins by tier (counts)", 3, "high", "High", dict(dir=None, definition="High-quality bins. A count; it depends on how many plasmids the isolates hold.")),
            ("Bins by tier (counts)", 4, "medium", "Medium", dict(dir=None, definition="Medium-quality bins. A count.")),
            ("Bins by tier (counts)", 5, "low", "Low", dict(dir=None, definition="Low-quality bins on a plasmid. A count.")),
            ("Bins by tier (counts)", 6, "spurious", "Spurious", dict(dir=None, definition="Bins that align to no plasmid. A count.")),
        ], track_col=0, table_html=table(esc, ["Track", "Tool", "Bins", "High", "Medium", "Low", "Spurious", "High-quality yield",
                    "Medium-or-better yield", "Homogeneity", "Completeness", "V-measure"], rows), label=display_tool_name)
        if rows else empty("No bin-quality table was available. It needs bins from a binning-capable tool."),
        "bin_quality")

    # 4. Performance --------------------------------------------------------------------------
    rows = [[r["tool"], r.get("n_runs", ""), pct(num(r.get("success_rate"))), r.get("n_resource_failures", ""),
             flt(num(r.get("median_runtime_seconds")), 1), flt(num(r.get("p90_runtime_seconds")), 1),
             flt(num(r.get("median_peak_memory_gb")), 2), r.get("threads", ""),
             flt(num(r.get("thread_seconds_per_recovered_plasmid")), 1), pct(num(r.get("cpu_utilisation"))),
             flt(num(r.get("runtime_scaling_exponent")), 2), flt(num(r.get("memory_scaling_exponent")), 2)]
            for r in data["performance"]]
    add("performance", "Computational performance",
        "Speed, memory and reliability from what stage 4 recorded. Success rate counts completed over attempted runs "
        "(a skipped run is not a failure); resource failures are timeouts and out-of-memory kills, kept apart from tool "
        "failures. Cost per recovered plasmid is thread-seconds divided by truth plasmids recovered, so a fast tool that "
        "recovers nothing is not called efficient. Scaling exponents are the log-log slope of runtime or memory on "
        "reference size (about 1 is linear) and are shown only with enough samples spanning a real size range; CPU "
        "utilisation only where CPU times were recorded. Wall-clock figures are comparable only on identical hardware and "
        "thread counts. <strong>Descriptive only.</strong>",
        apply.from_table("performance", "Computational performance", rows, 0, [
            ("Reliability", 2, "success", "Success rate", dict(source="performance", column="success_rate", unit="% of runs")),
            ("Reliability", 1, "runs", "Runs", dict(dir=None, definition="Runs attempted. A count.")),
            ("Reliability", 3, "resource_failures", "Resource failures", dict(dir=None, definition="Timeouts and out-of-memory kills, kept apart from tool failures. A count.")),
            ("Speed and memory", 4, "runtime", "Median runtime (s)", dict(source="performance", column="median_runtime_seconds", unit="s")),
            ("Speed and memory", 5, "p90", "P90 runtime (s)", dict(dir=None, unit="s", definition="The 90th percentile of the wall-clock runtime. No direction is defined in the metric registry, so it is not shaded.")),
            ("Speed and memory", 6, "memory", "Median peak memory (GB)", dict(source="performance", column="median_peak_memory_gb", unit="GB")),
            ("Speed and memory", 7, "threads", "Threads", dict(dir=None, definition="Threads the tool was given. A setting, not a result.")),
            ("Cost and scaling", 8, "thread_seconds", "Thread-s per recovered plasmid", dict(dir=None, definition="Thread-seconds divided by truth plasmids recovered. No direction is defined in the metric registry, so it is not shaded.")),
            ("Cost and scaling", 9, "cpu", "CPU utilisation", dict(dir=None, definition="Share of the allotted CPU actually used. No direction is defined, so it is not shaded.")),
            ("Cost and scaling", 10, "rt_exp", "Runtime exponent", dict(dir=None, definition="Log-log slope of runtime on reference size (about 1 is linear). No direction is defined, so it is not shaded.")),
            ("Cost and scaling", 11, "mem_exp", "Memory exponent", dict(dir=None, definition="Log-log slope of memory on reference size (about 1 is linear). No direction is defined, so it is not shaded.")),
        ], track_col=None, table_html=table(esc, ["Tool", "Runs", "Success rate", "Resource failures", "Median runtime (s)", "P90 runtime (s)",
                    "Median peak memory (GB)", "Threads", "Thread-s per recovered plasmid", "CPU utilisation",
                    "Runtime exponent", "Memory exponent"], rows), label=display_tool_name)
        if rows else empty("No performance table was available. It needs <code>tool_status.tsv</code> from stage 4."),
        "performance")

    # 5. Statistical power --------------------------------------------------------------------
    metric_names = {"lw_bin_f1": "length-weighted binning F1", "f1": "base-level F1", "sample_cprr": "isolate-level CPRR"}
    rows = [[r["analysis_track"], f"{r['tool_a']} vs {r['tool_b']}", metric_names.get(r.get("metric"), r.get("metric") or "f1"),
             r.get("paired_samples", ""), r.get("clusters", ""),
             flt(num(r.get("mean_difference")), 3), flt(num(r.get("min_detectable_difference")), 3),
             r.get("clusters_needed_for_target", ""), r.get("status", "").replace("_", " ")] for r in data["power"]]
    add("power", "Statistical power",
        "How large a difference between two tools this cohort can actually detect. Paired differences are averaged within "
        "each cluster (shared BioProject or study) first, because isolates from one study are not independent. The "
        "minimum detectable difference is the smallest true mean difference detected with 80% power at the 5% level; "
        "an observed difference below it is <em>not distinguishable</em> at this sample size however different the means "
        "look. A pair with fewer than 5 clusters gets no estimate. Normal approximation, optimistic for very small "
        "samples. The Metric column names what is compared: the ranking metric of the pair's track and task when the table was "
        "built with the leaderboard (the same metric as the paired-comparison table), otherwise base-level F1. Completed runs "
        "only, so a failed run is not counted as 0 here. <strong>A planning aid; it never changes a ranking.</strong>",
        table(esc, ["Track", "Pair", "Metric", "Paired samples", "Clusters", "Mean difference", "Minimum detectable difference",
                    "Clusters needed for a 0.05 difference", "Status"], rows)
        if rows else empty("No power table was available. It needs at least two tools scored on shared samples."),
        "power")

    # 6. Scenarios ----------------------------------------------------------------------------
    # One definition: the tags in benchmark.scenarios.tsv, read through report_scorecard (the scorecard's scenario
    # views use the same function). This table counts each isolate once (a partition of those tags); the scorecard
    # counts every isolate under every tag it has.
    import report_scorecard as sc
    import report_common as rc
    note_text, rows, derived = "", [], False
    scores = rc.read_tsv(scores_path) if scores_path and os.path.isfile(scores_path) else None
    if data["scenarios"] and scores:
        quality = sc._quality_bands(samples_path) if samples_path and os.path.isfile(samples_path) else {}
        members = sc.scenario_membership(data["scenarios"], quality)
        groups = sc.exclusive_groups(sc.exclusive_scenarios(data["scenarios"], members))
        derived = True
        for name in sc.EXCLUSIVE_ORDER:
            for (track, tool), cell in sorted(sc.scenario_performance(scores, groups[name]).items()):
                rows.append([track, name, tool, cell["n"], flt(cell["mean_f1"]), flt(cell["mean_plasmid_recall"]),
                             "underpowered (small n)" if sc.underpowered(cell["n"]) else ""])
        summary = sc.exclusive_counts_text(groups)
        note_text = (f" The <a href='#scorecard-scenarios'>scorecard by scenario</a> uses the same tags but lets an isolate "
                     f"count under every tag it has (<span data-tag-counts='{esc(sc.tag_counts_text(members))}'>"
                     f"{esc(sc.tag_counts_text(members))}</span>).")
    else:
        counts = defaultdict(int)
        for r in data["scenarios"]:
            counts[r["scenario"]] += 1
        summary = ", ".join(f"{esc(k)}: {v}" for k, v in sorted(counts.items())) or "no scenario table"
        rows = [[r["analysis_track"], r["scenario"], r["tool"], r.get("n_samples", ""), flt(num(r.get("mean_f1"))),
                 flt(num(r.get("mean_plasmid_recall"))), "underpowered (small n)" if r.get("underpowered") == "true" else ""]
                for r in data["scenario_performance"]]
    add("scenarios", "Performance by scenario",
        f"A tool should not look better because it met easier isolates. Each isolate is counted once, in the first of: "
        f"plasmid-free, challenging (low read depth or low read quality), complex (three or more plasmids, a plasmid of at "
        f"least 100 kb, or repeat-rich), annotated, or simple (the rest), from facts on disk. Isolates per scenario: "
        f"{summary}.{note_text} Scenarios with few isolates are flagged; read patterns, not ranks. "
        f"<strong>Descriptive only.</strong>",
        table(esc, ["Track", "Scenario", "Tool", "Isolates", "Mean F1", "Mean per-plasmid recall", "Note"], rows)
        if rows else empty("No scenario table was available."),
        "scenarios", "scenario_performance")

    # 7. Composite ----------------------------------------------------------------------------
    sens = {(r["analysis_track"], r["tool"]): r for r in data["composite_sensitivity"]
            if r["variant"].startswith("random_weights")}
    rows = []
    for r in data["composite"]:
        s = sens.get((r["analysis_track"], r["tool"]), {})
        rows.append([r["analysis_track"], r["tool"], flt(num(r.get("accuracy")), 1), flt(num(r.get("completeness")), 1),
                     flt(num(r.get("structure")), 1), flt(num(r.get("biology")), 1), flt(num(r.get("performance")), 1),
                     flt(num(r.get("composite")), 1), r.get("rank") or "-", r.get("status", ""),
                     r.get("gates_failed") or "-", flt(num(s.get("mean_rank")), 2),
                     f"{s.get('best_rank', '-')}-{s.get('worst_rank', '-')}" if s else "-",
                     pct(num(s.get("share_first")), 0) if s else "-", r.get("dimensions_dropped") or "-"])
    add("composite", "Five-dimension view (optional composite)",
        "Accuracy, completeness, structure, biology and performance, each scored 0-100, and a weighted composite "
        "(initial weights 30, 20, 25, 15 and 10; a proposal, not a standard, in <code>config/composite_weights.tsv</code>). "
        "<strong>This is not the benchmark ranking</strong> (that is the headline score and CPRR in the leaderboard) and it "
        "never changes it. A dimension is used only if every tool in the track has it, otherwise it is dropped for all "
        "and listed. A tool below the accuracy or completeness gate is shown but not ranked, however fast it is. The "
        "last columns show how the rank moves under 500 random reweightings: a ranking that does not survive them should "
        "not be reported as one. Always read the dimension scores, not only the composite.",
        apply.from_table("composite", "Five-dimension view", rows, 1, [
            ("Dimension scores (0-100)", 2, "dim_accuracy", "Accuracy", dict(dir="higher", unit="0-100", definition="The accuracy dimension scored 0 to 100 (config/composite_weights.tsv). Higher is better.")),
            ("Dimension scores (0-100)", 3, "dim_completeness", "Completeness", dict(dir="higher", unit="0-100", definition="The completeness dimension scored 0 to 100. Higher is better.")),
            ("Dimension scores (0-100)", 4, "dim_structure", "Structure", dict(dir="higher", unit="0-100", definition="The structure dimension scored 0 to 100. Higher is better.")),
            ("Dimension scores (0-100)", 5, "dim_biology", "Biology", dict(dir="higher", unit="0-100", definition="The biology dimension scored 0 to 100. Higher is better.")),
            ("Dimension scores (0-100)", 6, "dim_performance", "Performance", dict(dir="higher", unit="0-100", definition="The performance dimension scored 0 to 100. Higher is better.")),
            ("Composite (not the benchmark ranking)", 7, "composite", "Composite", dict(dir="higher", unit="0-100", definition="The weighted composite of the dimension scores. It is not the benchmark ranking and never changes it.")),
            ("Composite (not the benchmark ranking)", 11, "mean_rank", "Mean rank under reweighting", dict(dir="lower", definition="Mean rank over 500 random reweightings (rank 1 is best), so lower is better.")),
            ("Composite (not the benchmark ranking)", 13, "first", "First under reweighting", dict(dir="higher", definition="Share of the random reweightings in which the tool ranked first. Higher is better.")),
        ], track_col=0, lead="Rank, status, gates failed, best-worst rank and dimensions dropped are in the Table below.", table_html=table(esc, ["Track", "Tool", "Accuracy", "Completeness", "Structure", "Biology", "Performance", "Composite",
                    "Rank", "Status", "Gates failed", "Mean rank under reweighting", "Best-worst rank",
                    "First under reweighting", "Dimensions dropped"], rows), label=display_tool_name)
        if rows else empty("No composite table was available. It needs the dimension tables above."),
        "composite", "composite_sensitivity")

    # 8. Reproducibility ----------------------------------------------------------------------
    rows = [[r["analysis_track"], r["tool"], r.get("n_pairs", ""), r.get("n_incomplete", ""),
             pct(num(r.get("fraction_identical_scores"))), pct(num(r.get("fraction_identical_predictions"))),
             flt(num(r.get("max_f1_range")), 4), r.get("verdict", "")] for r in data["reproducibility_tools"]]
    add("reproducibility", "Reproducibility across runs",
        "Whether repeating the benchmark gives the same answer. Produced by <code>plasbench analysis compare-runs</code> "
        "from two or more results directories: <em>reproducible</em> means identical scores and identical predicted "
        "sequences, <em>score stable</em> means the same scores from different sequences, <em>variable</em> means the "
        "scores moved. A single run proves nothing, so without repeated runs this section is empty by design.",
        table(esc, ["Track", "Tool", "Sample pairs", "Incomplete", "Identical scores", "Identical predictions",
                    "Largest F1 range", "Verdict"], rows)
        if rows else empty("No repeated runs were compared. Run the benchmark twice and "
                           "<code>plasbench analysis compare-runs --run DIR --run DIR ...</code>."),
        "reproducibility_tools")

    # 9. Statistical validation (simulation) --------------------------------------------------
    rows = [[r.get("family", "") or "studies", r.get("scenario", ""), r.get("n_clusters", ""), r.get("isolates_per_cluster", ""), r.get("icc", ""), r.get("missing", ""),
             r.get("failure", "") or "-", r.get("effect", ""), r.get("replicates", ""), (r.get("ci_coverage", "") + (f" (SE {r['ci_coverage_se']})" if r.get("ci_coverage_se") else "")) or "-",
             r.get("ci_verdict", "") or "-", (r.get("rejection_rate", "") + (f" (SE {r['rejection_se']})" if r.get("rejection_se") else "")) or "-",
             (f"{r['fwer_holm']} / {r['fwer_unadjusted']}" if r.get("fwer_holm") else "-"), r.get("test_method", ""), r.get("test_verdict", "")] for r in data["stats_validation"]]
    by_studies_rows = [[r.get("n_studies", ""), r.get("mode", ""), r.get("scenarios", ""), r.get("lowest_coverage", "") or "-", r.get("interval_status", ""), r.get("highest_type_i_error", "") or "-",
                        r.get("test_status", ""), r.get("holm_status", ""), r.get("status", ""), r.get("limiting_scenarios", "") or "-"] for r in data["stats_validation_by_studies"]]
    if rows and not by_studies_rows:
        import simulate_validation as sv   # an older run wrote only the scenario table: the summary is derived from it
        by_studies_rows = [[r["n_studies"], r["mode"], r["scenarios"], r["lowest_coverage"] or "-", r["interval_status"], r["highest_type_i_error"] or "-", r["test_status"], r["holm_status"],
                            r["status"], r["limiting_scenarios"] or "-"] for r in sv.by_studies(data["stats_validation"])]
    status_line = ""
    if rows:
        import simulate_validation as sv
        status_line = f"<p><strong>Status of the statistical procedures: {esc(sv.overall_status(data['stats_validation']))}.</strong></p>"
    add("stats-validation", "Statistical validation (simulation)",
        "Do the intervals and tests behave as they claim? Data are simulated with study-to-study differences, correlated isolates, unequal study sizes, one dominant study or "
        "species, missing outputs, resource failures (a tool scored 0, also a whole study failing) and many tools compared at once with Holm, and the report's own functions are run on "
        "them. Results are summarised <strong>by the number of independent studies</strong>, because that limits what the statistics can show. The procedures stay "
        "<strong>provisional</strong> until a full run supports them for the number of studies and the cohort structure they are used on. <em>Interval coverage</em> should be near 95%; <em>rejection rate</em> is the type-I error "
        "when the true effect is 0 (it should be near 5%) and the power when the effect is above 0. A run of <code>smoke</code> mode (100 replicates) can only expose a "
        "gross failure; <code>full</code> mode (1,000) is the evidence. <strong>Read a shortfall as a limit:</strong> an interval that covers less than 95% is too narrow, "
        "so treat it as optimistic. It never changes a score or a rank.",
        (status_line + "<h3>By number of independent studies</h3>"
         + table(esc, ["Studies", "Run", "Scenarios", "Lowest interval coverage", "Interval", "Highest type-I error", "Test", "Holm", "Status", "Limiting scenarios"], by_studies_rows)
         + "<h3>Every scenario</h3>"
         + table(esc, ["Family", "Scenario", "Studies", "Isolates per study", "Within-study correlation (icc)", "Missing", "Failures", "True effect", "Replicates", "Interval coverage",
                       "Interval verdict", "Test rejects at 0.05", "Holm family-wise error (adjusted / unadjusted)", "Test", "Test verdict"], rows))
        if rows else empty("Not run: no simulation table was produced. Run <code>plasbench analysis simulate-validation --mode smoke --out benchmark.stats_validation.tsv</code> "
                           "or set <code>RUN_STATS_VALIDATION=1</code> for stage 6 (<code>STATS_VALIDATION_MODE=full</code> for the full run)."),
        "stats_validation")
    return "".join(nav), "".join(sections)
