#!/usr/bin/env python3
"""
Failure handling in the leaderboard: a tool that fails everywhere must be ranked
(not dropped), failures must stay inside their own track, equal scores must rank
deterministically, and a timeout/out-of-memory kill must be distinguishable from
a tool getting the answer wrong.
"""

import os
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from aggregate_results import (  # noqa: E402
    failure_class, ranked_tracks, read_failed_samples, read_resource_failure_counts,
)

SAMPLES = [f"s{i}" for i in range(6)]


def status_counts():
    return defaultdict(lambda: {"completed": 0, "reused": 0, "failed": 0, "skipped": 0})


def row(sample, tool, f1, track="short_read"):
    return {
        "sample": sample, "tool": tool, "precision": f1, "recall": f1, "f1": f1,
        "analysis_track": track, "plasmid_recall": f1, "bin_f1": None,
        "pr_auc": None, "perfect_reference_recovery": "", "strict_reference_reconstruction": "",
        "isolate_specificity": None, "chromosome_fp_bp": None, "true_plasmid_count": 1,
        "nmi": None, "variation_of_information": None,
        "plasmid_recall_ge50": None, "plasmid_recall_ge90": None,
        "complete_circular_plasmid_recall": None,
    }


def by_track(result):
    """{track: {tool: summary row}}. ranked_tracks returns (track, task, rows, summary,
    comparisons); this fixture has no binning tools, so every group is one task."""
    out = defaultdict(dict)
    for track, _task, _rows, summary, _comparisons in result:
        out[track].update({s["tool"]: s for s in summary})
    return out


def write_status(path, lines):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n")
        for sample, tool, status, reason in lines:
            handle.write(f"{sample}\t{tool}\t{status}\t\t{reason}\t5\t\n")


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    # 1. A tool that failed on EVERY sample has no score rows. It must still be
    #    ranked, last, with F1 = 0 on every plasmid-bearing sample.
    rows = [row(s, "good", 0.9) for s in SAMPLES] + [row(s, "ok", 0.6) for s in SAMPLES]
    failed = {"crashy": set(SAMPLES)}
    tracks = by_track(ranked_tracks(rows, status_counts(), failed, tool_tracks={"crashy": "short_read"}))
    short = tracks["short_read"]
    print("tool that failed on every sample")
    check("it appears on the leaderboard", "crashy" in short)
    check("mean_f1 == 0.0", short["crashy"]["mean_f1"] == 0.0)
    check("n_failures_scored_zero == 6", short["crashy"]["n_failures_scored_zero"] == 6)
    check("it ranks last", short["crashy"]["rank"] == 3)
    check("other tools keep their full shared-sample set", short["good"]["n_ranking_samples"] == 6)

    # 2. Without the fix a total failure beat partial failure; prove partial is not ranked below total.
    rows = [row(s, "partial", 0.9) for s in SAMPLES[:3]]
    failed = {"partial": set(SAMPLES[3:]), "total": set(SAMPLES)}
    rows += [row(s, "partial_anchor", 0.5) for s in SAMPLES]
    tracks = by_track(ranked_tracks(rows, status_counts(), failed, tool_tracks={"total": "short_read"}))
    short = tracks["short_read"]
    check("partial failure (0.9 on half, 0 on half) outranks total failure",
          short["partial"]["mean_f1"] > short["total"]["mean_f1"])

    # 3. Failures stay inside their own track. A short-read tool failing must not
    #    appear in, or change, the long-read leaderboard, and vice versa.
    rows = ([row(s, "sr_good", 0.9) for s in SAMPLES]
            + [row(s, "lr_good", 0.8, track="long_read") for s in SAMPLES])
    failed = {"lr_broken": set(SAMPLES)}
    tracks = by_track(ranked_tracks(rows, status_counts(), failed,
                                    tool_tracks={"lr_broken": "long_read"}))
    print("track isolation")
    check("long-read failure shows in long_read", "lr_broken" in tracks["long_read"])
    check("and not in short_read", "lr_broken" not in tracks["short_read"])
    check("short_read ranking unchanged", tracks["short_read"]["sr_good"]["n_ranking_samples"] == 6)

    # 4. A track in which every tool failed everywhere still gets a leaderboard.
    rows = [row(s, "sr_good", 0.9) for s in SAMPLES]
    failed = {"lr_only": set(SAMPLES)}
    tracks = by_track(ranked_tracks(rows, status_counts(), failed, tool_tracks={"lr_only": "long_read"}))
    check("an all-failed track is created", "lr_only" in tracks.get("long_read", {}))

    # 5. Failures on a sample with no true plasmid are not scored (no F1 exists there).
    rows = [row("s0", "good", 0.9), dict(row("s1", "good", None), true_plasmid_count=0)]
    failed = {"crashy": {"s1"}}
    tracks = by_track(ranked_tracks(rows, status_counts(), failed, tool_tracks={"crashy": "short_read"}))
    check("failure on a plasmid-free sample creates no entry", "crashy" not in tracks["short_read"])

    # 6. Equal scores rank by tool name regardless of input order.
    forward = [row(s, t, 0.7) for s in SAMPLES for t in ("zeta", "alpha", "mid")]
    backward = list(reversed(forward))
    order_a = [s["tool"] for _, _, _, summary, _ in ranked_tracks(forward, status_counts()) for s in summary]
    order_b = [s["tool"] for _, _, _, summary, _ in ranked_tracks(backward, status_counts()) for s in summary]
    print("tie-break")
    check("ranking is alphabetical on an exact tie", order_a == ["alpha", "mid", "zeta"])
    check("and independent of input order", order_a == order_b)

    # 7. Failure classification and the resource-failure policy.
    print("resource failures")
    check("exit 137 is a resource failure", failure_class("see log; exit_code=137") == "resource")
    check("exit 124 is a resource failure", failure_class("exit_code=124") == "resource")
    check("exit 1 is a tool failure", failure_class("see log; exit_code=1") == "tool")
    check("no exit code recorded is a tool failure", failure_class("see log") == "tool")
    check("empty reason is a tool failure", failure_class("") == "tool")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tool_status.tsv")
        write_status(path, [
            ("s0", "big", "failed", "see log; exit_code=137"),
            ("s1", "big", "failed", "see log; exit_code=1"),
            ("s2", "big", "completed", ""),
            ("s3", "big", "skipped", "command unavailable"),
        ])
        zero = read_failed_samples(path)
        excl = read_failed_samples(path, "exclude")
        check("score-zero keeps both failures", zero["big"] == {"s0", "s1"})
        check("exclude drops only the resource failure", excl["big"] == {"s1"})
        check("resource failures are counted", read_resource_failure_counts(path)["big"] == 1)
        check("skipped is never a failure", "s3" not in zero["big"])

        rows = [row(s, "big", 0.9) for s in ("s2", "s3")] + [row(s, "ref", 0.5) for s in SAMPLES[:4]]
        tracks_zero = by_track(ranked_tracks(rows, status_counts(), zero,
                                             resource_failures=read_resource_failure_counts(path)))
        tracks_excl = by_track(ranked_tracks(rows, status_counts(), excl,
                                             resource_failures=read_resource_failure_counts(path)))
        check("n_failed_resource is reported", tracks_zero["short_read"]["big"]["n_failed_resource"] == 1)
        check("score-zero counts the OOM sample as 0",
              tracks_zero["short_read"]["big"]["n_failures_scored_zero"] == 2)
        check("exclude scores only the tool failure as 0",
              tracks_excl["short_read"]["big"]["n_failures_scored_zero"] == 1)

    print()
    if not ok:
        print("AGGREGATE FAILURE TESTS FAILED")
        sys.exit(1)
    print("ALL AGGREGATE FAILURE TESTS PASSED")


if __name__ == "__main__":
    main()
