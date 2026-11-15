#!/usr/bin/env python3
"""The burden of predicted sequence that precision does not charge (plan B2): aggregation, leaderboard columns, registry and report."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import aggregate_results as ar  # noqa: E402
import metric_registry as mr  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    d = {"unmapped_pred_bp": [100, 100], "off_truth_pred_bp": [50, 50], "mapped_pred_bp": [350, 350], "ambiguously_mapped_pred_bp": [70, 70],
         "precision": [0.9, 0.8], "strict_precision": [0.6, 0.5]}
    f = ar.burden_fields(d)
    check("totals pool the isolates", f["total_predicted_bp"] == 1000 and f["total_unmapped_pred_bp"] == 200 and f["total_off_truth_pred_bp"] == 100, f)
    check("shares", abs(f["unmapped_fraction"] - 0.2) < 1e-9 and abs(f["off_truth_fraction"] - 0.1) < 1e-9 and abs(f["ambiguous_fraction"] - 0.2) < 1e-9, f)
    check("precision gap is permissive minus strict", abs(f["precision_gap"] - 0.3) < 1e-9, f)
    empty = ar.burden_fields({k: [] for k in d})
    check("missing columns stay blank, never zero", all(v is None for v in empty.values()), empty)
    partial = ar.burden_fields({"unmapped_pred_bp": [100], "off_truth_pred_bp": [], "mapped_pred_bp": [400], "ambiguously_mapped_pred_bp": [], "precision": [0.9], "strict_precision": [0.8]})
    check("a missing part gives no shares at all (it must not shrink the denominator)", partial["total_predicted_bp"] is None and partial["unmapped_fraction"] is None, partial)
    import tempfile
    import score_plasmids as sp
    with tempfile.TemporaryDirectory() as t:
        missing, empty = f"{t}/none.paf", f"{t}/empty.paf"
        open(empty, "w").close()
        check("an ambiguity alignment that was not made is not measured (None), never 0", sp.ambiguous_query_bp(missing, {}, {}, 1, 0, 0, 0) is None and sp.ambiguous_query_bp(None, {}, {}, 1, 0, 0, 0) is None)
        check("an empty ambiguity alignment is a real 0", sp.ambiguous_query_bp(empty, {}, {}, 1, 0, 0, 0) == 0)
    ids = {r["id"] for r in mr.load()}
    check("the registry lists the burden metrics", {"unmapped_fraction", "off_truth_fraction", "ambiguous_fraction", "precision_gap"} <= ids)
    print()
    if not ok:
        print("BURDEN TESTS FAILED")
        sys.exit(1)
    print("ALL BURDEN TESTS PASSED")


if __name__ == "__main__":
    main()
