#!/usr/bin/env python3
"""HTML sections for the further benchmark dimensions, built from stage-6 tables.

build_html_report.py calls `render(prefix, esc, link)` once and places the returned
(navigation, sections) in the page. Every section is advisory: it never changes the leaderboard,
says what its numbers are and are not, shows an explicit empty state when its table was not
produced (a missing table means "not evaluated", never "zero"), and links the raw table.

Tables read, all written beside the leaderboard as <prefix>.<name>.tsv:
  accuracy, missing_regions, feature_preservation, ngoc, bin_quality, performance, power,
  scenarios, scenario_performance, composite, composite_sensitivity, reproducibility_tools
"""
import csv
import os
from collections import defaultdict

TABLES = ("accuracy", "missing_regions", "feature_preservation", "ngoc", "bin_quality", "performance", "power",
          "scenarios", "scenario_performance", "composite", "composite_sensitivity", "reproducibility_tools")


def read_tsv(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def empty(message):
    return f"<div class='panel'><p>{message}</p></div>"


def section(esc, sid, title, lead, body, link_html=""):
    return (f"<section id='{sid}'><h2>{esc(title)}</h2><p class='lead'>{lead}{link_html}</p>{body}</section>")


def render(prefix, esc, link):
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
        cols = total(items, "aligned_columns")
        m = miss.get((track, tool), [])
        plasmids = len(m)
        rows.append([track, tool, len(items), pct(ratio(total([{"v": (num(i["identity"]) or 0) * (num(i["aligned_columns"]) or 0)}
                                                                for i in items if i.get("identity")], "v"),
                                                        total([i for i in items if i.get("identity")], "aligned_columns")), 2),
                     pct(ratio(total(items, "mismatch_bp"), cols), 2), pct(ratio(total(items, "inserted_bp"), cols), 2),
                     pct(ratio(total(items, "deleted_bp"), cols), 2), int(total(items, "n_blocks_without_cigar") or 0),
                     plasmids, flt(ratio(total(m, "missing_regions"), plasmids), 2),
                     int(total(m, "missing_bp") or 0), int(max([num(x["longest_missing_bp"]) or 0 for x in m] or [0]))])
    add("accuracy-dimension", "Sequence accuracy and missing regions",
        "Coverage says how much of a plasmid was recovered; this says whether the recovered bases are right. Identity, "
        "mismatch, insertion and deletion are shares of the alignment columns of the retained blocks on truth plasmids, "
        "so they sum to 100%. Blocks without a CIGAR cannot be decoded and are counted, never guessed. Missing regions "
        "are reference stretches no retained alignment covers (a circular plasmid's gap across the origin counts as two). "
        "<strong>Descriptive only: it never changes the leaderboard.</strong> SNP concordance is not computed: it needs "
        "known variant positions, which a single same-isolate reference does not have.",
        table(esc, ["Track", "Tool", "Samples", "Identity", "Mismatch", "Insertion", "Deletion", "Blocks without CIGAR",
                    "Plasmids", "Missing regions per plasmid", "Missing bp", "Longest gap (bp)"], rows)
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
        body += table(esc, ["Track", "Tool", "Feature kind", "Expected", "Full length", "Truncated", "Missed",
                            "Full-length rate", "Mean covered fraction"], rows)
    if ngoc_rows:
        body += table(esc, ["Track", "Tool", "Features used", "Adjacent pairs", "Conserved", "NGOC"], ngoc_rows)
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
        "Would a surveillance laboratory trust the bin? Each bin is matched to its best truth plasmid: <em>high</em> is at "
        "least 90% complete and at most 5% contaminated, <em>medium</em> at least 50% and at most 10%, <em>low</em> is any "
        "other bin on a plasmid, <em>spurious</em> aligns to no plasmid. Yield is the share of truth plasmids with such a "
        "bin (a split plasmid is judged by its best bin). Homogeneity, completeness and V-measure use the same "
        "base-pair weighted table as NMI: informative about binning behaviour, not primary evidence, and not repeat-aware. "
        "<strong>Descriptive only.</strong> Binning-capable tools only.",
        table(esc, ["Track", "Tool", "Bins", "High", "Medium", "Low", "Spurious", "High-quality yield",
                    "Medium-or-better yield", "Homogeneity", "Completeness", "V-measure"], rows)
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
        table(esc, ["Tool", "Runs", "Success rate", "Resource failures", "Median runtime (s)", "P90 runtime (s)",
                    "Median peak memory (GB)", "Threads", "Thread-s per recovered plasmid", "CPU utilisation",
                    "Runtime exponent", "Memory exponent"], rows)
        if rows else empty("No performance table was available. It needs <code>tool_status.tsv</code> from stage 4."),
        "performance")

    # 5. Statistical power --------------------------------------------------------------------
    rows = [[r["analysis_track"], f"{r['tool_a']} vs {r['tool_b']}", r.get("paired_samples", ""), r.get("clusters", ""),
             flt(num(r.get("mean_difference")), 3), flt(num(r.get("min_detectable_difference")), 3),
             r.get("clusters_needed_for_target", ""), r.get("status", "").replace("_", " ")] for r in data["power"]]
    add("power", "Statistical power",
        "How large a difference between two tools this cohort can actually detect. Paired differences are averaged within "
        "each cluster (shared BioProject or study) first, because isolates from one study are not independent. The "
        "minimum detectable difference is the smallest true mean difference detected with 80% power at the 5% level; "
        "an observed difference below it is <em>not distinguishable</em> at this sample size however different the means "
        "look. A pair with fewer than 5 clusters gets no estimate. Normal approximation, optimistic for very small "
        "samples. <strong>A planning aid; it never changes a ranking.</strong>",
        table(esc, ["Track", "Pair", "Paired samples", "Clusters", "Mean difference", "Minimum detectable difference",
                    "Clusters needed for a 0.05 difference", "Status"], rows)
        if rows else empty("No power table was available. It needs at least two tools scored on shared samples."),
        "power")

    # 6. Scenarios ----------------------------------------------------------------------------
    counts = defaultdict(int)
    for r in data["scenarios"]:
        counts[r["scenario"]] += 1
    summary = ", ".join(f"{esc(k)}: {v}" for k, v in sorted(counts.items())) or "no scenario table"
    rows = [[r["analysis_track"], r["scenario"], r["tool"], r.get("n_samples", ""), flt(num(r.get("mean_f1"))),
             flt(num(r.get("mean_plasmid_recall"))), "underpowered (small n)" if r.get("underpowered") == "true" else ""]
            for r in data["scenario_performance"]]
    add("scenarios", "Performance by scenario",
        f"A tool should not look better because it met easier isolates. Each isolate is tagged simple, complex (three or "
        f"more plasmids, a plasmid of at least 100 kb, or repeat-rich), annotated, challenging (low read depth) or "
        f"plasmid-free, from facts on disk. Isolates per scenario: {summary}. Scenarios with few isolates are flagged; "
        f"read patterns, not ranks. <strong>Descriptive only.</strong>",
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
        table(esc, ["Track", "Tool", "Accuracy", "Completeness", "Structure", "Biology", "Performance", "Composite",
                    "Rank", "Status", "Gates failed", "Mean rank under reweighting", "Best-worst rank",
                    "First under reweighting", "Dimensions dropped"], rows)
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
    return "".join(nav), "".join(sections)
