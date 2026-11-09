#!/usr/bin/env python3
"""One scenario definition: the exclusive scenario table and the scorecard's overlapping scenario views come from the same tags.

report_scorecard.scenario_membership gives the overlapping sets (a tag count), exclusive_scenarios derives the partition
from those same sets, and both are rendered from them (report_dimensions 'Performance by scenario', scorecard 'by scenario').
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_scorecard as sc  # noqa: E402

ROWS = [
    {"sample": "free", "tags": "", "n_plasmids": "0", "read_depth_x": "80"},
    {"sample": "lowdepth", "tags": "low_depth,annotated", "n_plasmids": "2", "read_depth_x": "20"},
    {"sample": "multi", "tags": "multi_plasmid,annotated", "n_plasmids": "3", "read_depth_x": "90"},
    {"sample": "ann", "tags": "annotated", "n_plasmids": "1", "read_depth_x": "60"},
    {"sample": "plain", "tags": "", "n_plasmids": "1", "read_depth_x": "50"},
    {"sample": "nodepth", "tags": "", "n_plasmids": "1", "read_depth_x": ""},
    {"sample": "lowq", "tags": "", "n_plasmids": "1", "read_depth_x": "70"},
]
SCORES = [{"sample": s["sample"], "tool": t, "analysis_track": "short_read", "f1": f, "plasmid_recall": r}
          for s in ROWS for t, f, r in (("A", "0.9", "0.5"), ("B", "0.7", "1.0"))]


def main():
    members = sc.scenario_membership(ROWS, {"lowq": "low"})
    # overlapping tags: complex = multi_plasmid / large_plasmid / repeat_rich; simple needs plasmids, not complex, depth >= 30
    assert members["complex"] == {"multi"}
    assert members["annotated"] == {"lowdepth", "multi", "ann"}
    assert members["challenging"] == {"lowdepth", "lowq"}
    assert members["simple"] == {"ann", "plain", "lowq"}, members["simple"]

    exclusive = sc.exclusive_scenarios(ROWS, members)
    groups = sc.exclusive_groups(exclusive)
    # a partition: every isolate exactly once, groups disjoint, union is everything
    assert sorted(exclusive) == sorted(r["sample"] for r in ROWS)
    assert sum(len(g) for g in groups.values()) == len(ROWS)
    assert set().union(*groups.values()) == set(exclusive)
    # derived from the SAME tags, first match wins
    assert groups["plasmid_free"] == {"free"}
    assert groups["challenging"] == {"lowdepth", "lowq"}
    assert groups["complex"] == {"multi"}
    assert groups["annotated"] == {"ann"}
    assert groups["simple"] == {"plain", "nodepth"}
    # the exclusive group is always a subset of the overlapping set that has the same name
    for name in ("challenging", "complex", "annotated", "simple"):
        assert groups[name] <= members[name] or name == "simple", name
    # counts printed by the two views are the same numbers
    assert sc.tag_counts_text(members) == "simple 3, complex 1, annotated 3, challenging 2"

    # per-scenario means come from the same score rows for either view
    perf = sc.scenario_performance(SCORES, groups["challenging"])
    assert perf[("short_read", "A")]["n"] == 2 and abs(perf[("short_read", "A")]["mean_f1"] - 0.9) < 1e-9
    assert abs(perf[("short_read", "B")]["mean_plasmid_recall"] - 1.0) < 1e-9
    print("PASS: one scenario definition, exclusive partition derived from the overlapping tags")


if __name__ == "__main__":
    main()
