#!/usr/bin/env python3
"""
truth_exclusion_sensitivity.py -- the headline with and without the evidence-based truth exclusion (audit AU-051).

The evidence-based truth labels (python/label_truth_evidence.py, scheme "evidence") drop a plasmid-labelled replicon from scoring when no plasmid marker is
found on it. The markers come from the replicon and MOB-typing databases (config/truth_marker_databases.tsv) that replicon-based tools (baseline_replicon, mob_recon)
also use, so removing marker-free plasmids can favour those tools by construction. The pre-registered primary scheme is the NCBI labels (no exclusion); this table
puts the two side by side so the size of that effect is read, not argued.

For every analysis track and tool it reports the mean base-level F1 under the scheme WITHOUT the exclusion (ncbi) and WITH it (evidence), the change, the rank under
each, whether the top tool changes, and whether the tool shares a database with the truth markers (python/truth_marker_overlap.py: yes / possible / no / unknown).
Two group rows per track average the change over tools that share a database (yes or possible) and over those that do not, which is the quantity the
circularity concern is about. Cohort-level columns count the plasmids excluded because they carry no marker and the replicons excluded for any other reason.

Inputs are tables the aggregate stage already writes: benchmark.rank_robustness.tsv (rank_sensitivity.py re-scores every PAF under each labelling scheme),
benchmark.truth_marker_overlap.tsv and benchmark.label_schemes.tsv.

Limits, stated so they are not mistaken for features:
  * Base-level F1 only. The reconstruction headlines (length-weighted binning F1, CPRR) are not re-scored under another truth by rank_sensitivity.py, so this
    table says nothing about them; it must not be read as a robustness proof for a reconstruction headline.
  * The evidence scheme removes more than marker-free plasmids (chromid-like, rRNA-bearing, short-read-only, multimers); the cohort columns separate the marker-free
    count so the share that can favour replicon tools is visible. The F1 change itself is the effect of ALL exclusions together.
  * A name-level database screen, not a sequence-level proof. Advisory: it never changes a score or a rank.

Output: benchmark.truth_exclusion_sensitivity.tsv. Standard library only.
"""
import argparse
import csv
import os
import sys

FIELDS = ["analysis_track", "row_kind", "tool", "shares_truth_database", "mean_f1_without_exclusion", "mean_f1_with_exclusion", "delta_with_minus_without",
          "n_samples", "rank_without_exclusion", "rank_with_exclusion", "rank_change", "top_without_exclusion", "top_with_exclusion", "top_changes",
          "plasmids_excluded_marker_free", "replicons_excluded_other", "scope"]
SCOPE = "base-level F1 only; reconstruction headlines (binning F1, CPRR) are not re-scored under another truth"
SHARED_RANK = {"yes": 3, "possible": 2, "no": 1, "unknown": 0}


def read_tsv(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def tool_sharing(overlap_rows):
    """tool -> the strongest sharing recorded against any truth marker caller (yes > possible > no > unknown)."""
    best = {}
    for row in overlap_rows:
        tool, shared = row.get("tool", ""), (row.get("shared") or "unknown").strip().lower()
        if tool and SHARED_RANK.get(shared, 0) >= SHARED_RANK.get(best.get(tool, "unknown"), 0):
            best[tool] = shared if shared in SHARED_RANK else "unknown"
    return best


def exclusion_counts(label_rows):
    """(plasmids excluded for having no marker, replicons excluded for any other reason), from benchmark.label_schemes.tsv."""
    marker_free = other = 0
    for row in label_rows:
        if (row.get("evidence_label") or "").strip().upper() != "AMBIGUOUS":
            continue
        if (row.get("evidence_reason") or "").lower().startswith("no plasmid marker"):
            marker_free += 1
        else:
            other += 1
    return marker_free, other


def variant_means(rank_rows, variant):
    """(analysis_track, tool) -> (mean F1, n_samples) for one variant of benchmark.rank_robustness.tsv."""
    out = {}
    for row in rank_rows:
        if row.get("variant") == variant:
            try:
                out[(row["analysis_track"], row["tool"])] = (float(row["mean_value"]), row.get("n_samples", ""))
            except (KeyError, ValueError):
                continue
    return out


def ranked(means):
    """tool -> rank (1 = best); ties broken by tool name, as rank_sensitivity.py does."""
    ordered = sorted(means, key=lambda tool: (-means[tool], tool))
    return {tool: i for i, tool in enumerate(ordered, start=1)}


def build(rank_rows, overlap_rows, label_rows, primary_scheme="ncbi"):
    """Rows of the sensitivity table. The scheme without the exclusion is ncbi, the one with it is evidence; whichever is primary is the baseline variant."""
    without = variant_means(rank_rows, "baseline" if primary_scheme == "ncbi" else "scheme:ncbi")
    with_exclusion = variant_means(rank_rows, "baseline" if primary_scheme == "evidence" else "scheme:evidence")
    if primary_scheme not in ("ncbi", "evidence"):
        raise ValueError("the sensitivity compares the ncbi and evidence schemes; the primary scheme must be one of them")
    sharing = tool_sharing(overlap_rows)
    marker_free, other = exclusion_counts(label_rows)
    rows = []
    for track in sorted({track for track, _ in without} & {track for track, _ in with_exclusion}):
        tools = sorted({tool for t, tool in without if t == track} & {tool for t, tool in with_exclusion if t == track})
        if not tools:
            continue
        a = {tool: without[(track, tool)][0] for tool in tools}
        b = {tool: with_exclusion[(track, tool)][0] for tool in tools}
        rank_a, rank_b = ranked(a), ranked(b)
        top_a, top_b = min(rank_a, key=rank_a.get), min(rank_b, key=rank_b.get)
        common = {"analysis_track": track, "top_without_exclusion": top_a, "top_with_exclusion": top_b,
                  "top_changes": "yes" if top_a != top_b else "no", "plasmids_excluded_marker_free": marker_free,
                  "replicons_excluded_other": other, "scope": SCOPE}
        deltas = {"yes_or_possible": [], "no_or_unknown": []}
        for tool in tools:
            share = sharing.get(tool, "unknown")
            delta = b[tool] - a[tool]
            deltas["yes_or_possible" if share in ("yes", "possible") else "no_or_unknown"].append(delta)
            rows.append({**common, "row_kind": "tool", "tool": tool, "shares_truth_database": share,
                         "mean_f1_without_exclusion": f"{a[tool]:.4f}", "mean_f1_with_exclusion": f"{b[tool]:.4f}",
                         "delta_with_minus_without": f"{delta:+.4f}", "n_samples": without[(track, tool)][1],
                         "rank_without_exclusion": rank_a[tool], "rank_with_exclusion": rank_b[tool],
                         "rank_change": rank_a[tool] - rank_b[tool]})
        for group, values in deltas.items():
            rows.append({**common, "row_kind": "group", "tool": ("mean over tools sharing a truth database (yes or possible)"
                                                   if group == "yes_or_possible" else "mean over tools not sharing one (no or unknown)"),
                         "shares_truth_database": group, "mean_f1_without_exclusion": "", "mean_f1_with_exclusion": "",
                         "delta_with_minus_without": f"{sum(values) / len(values):+.4f}" if values else "",
                         "n_samples": len(values), "rank_without_exclusion": "", "rank_with_exclusion": "", "rank_change": ""})
    return rows


def summary(rows):
    lines = []
    for track in sorted({r["analysis_track"] for r in rows}):
        group = {r["shares_truth_database"]: r for r in rows if r["analysis_track"] == track and r["row_kind"] == "group"}
        tools = [r for r in rows if r["analysis_track"] == track and r["row_kind"] == "tool"]
        first = tools[0]
        shared, unshared = group.get("yes_or_possible", {}).get("delta_with_minus_without", ""), group.get("no_or_unknown", {}).get("delta_with_minus_without", "")
        lines.append(f"  [{track}] top without exclusion: {first['top_without_exclusion']}, with: {first['top_with_exclusion']}"
                     f" (changes: {first['top_changes']}); mean F1 change, tools sharing a truth database: {shared or 'n/a'}, others: {unshared or 'n/a'}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rank-robustness", required=True, help="benchmark.rank_robustness.tsv (rank_sensitivity.py)")
    ap.add_argument("--truth-marker-overlap", help="benchmark.truth_marker_overlap.tsv (truth_marker_overlap.py)")
    ap.add_argument("--label-schemes", help="benchmark.label_schemes.tsv (label_schemes.py collect)")
    ap.add_argument("--label-scheme", default=os.environ.get("TRUTH_LABEL_SCHEME", "ncbi"), help="the primary scheme rank_sensitivity.py used as its baseline")
    ap.add_argument("--out", required=True, help="benchmark.truth_exclusion_sensitivity.tsv")
    args = ap.parse_args()
    rank_rows = read_tsv(args.rank_robustness)
    if not rank_rows:
        raise SystemExit(f"ERROR: {args.rank_robustness} is missing or empty; run rank_sensitivity.py first")
    try:
        rows = build(rank_rows, read_tsv(args.truth_marker_overlap), read_tsv(args.label_schemes), args.label_scheme)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    if not rows:
        raise SystemExit("ERROR: rank_robustness.tsv has no scheme:evidence (or scheme:ncbi) rows, so there is no with/without comparison to report; "
                         "stage 2 writes truth.scored.tsv when the truth evidence callers ran")
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    sys.stderr.write(f"[truth_exclusion_sensitivity] {sum(r['row_kind'] == 'tool' for r in rows)} tool rows -> {args.out}\n" + "\n".join(summary(rows)) + "\n")


if __name__ == "__main__":
    main()
