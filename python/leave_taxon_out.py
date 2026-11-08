#!/usr/bin/env python3
"""
leave_taxon_out.py -- does the recommender transfer to a genus or phylum it never
saw? And the one-time evaluation of the locked holdout split. (Scoring
specification, section 11.)

Folds hold out one taxon at a time (genus, then phylum), train on the rest, and
score the held-out isolates exactly as evaluate_recommender.py does: regret
against the per-isolate best tool, regret of the single best training tool, the
near-optimal rate and gap closed. Genus comes from the sample sheet's `genus`
column, else the first word of `organism`; phylum only from a `phylum` column.
Isolates with no taxon are reported in their own "not_recorded" row -- counted,
not dropped, and never used as a fold.

Isolates with split=holdout are left out of every fold. They are evaluated only
with --confirm-holdout: train on all non-holdout isolates, score the holdout
once, and write a marker (<prefix>.holdout_evaluated.json). A second run with
--confirm-holdout refuses, so the holdout cannot be tuned against.

Writes <prefix>.leave_taxon_out.tsv. Standard library only.
"""

import argparse
import datetime
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_recommender as er  # noqa: E402

FIELDS = ["level", "held_out_group", "n_isolates", "n_training_isolates", "mean_regret", "single_best_mean_regret",
          "near_optimal_rate", "gap_closed", "status", "note"]


def genus_of(meta):
    genus = (meta.get("genus") or "").strip()
    if genus:
        return genus
    organism = (meta.get("organism") or "").strip()
    return organism.split()[0] if organism else ""


def fold_row(level, group, table, held, organism, min_train, margin, floor):
    regrets, _, _, _ = er.evaluate(table, {group: held}, organism, min_train, margin, floor, "f1", "f1")
    train = len([s for s in table if s not in held])
    base = {"level": level, "held_out_group": group, "n_isolates": len([s for s in held if s in table]),
            "n_training_isolates": train}
    if not regrets:
        return {**base, "mean_regret": "", "single_best_mean_regret": "", "near_optimal_rate": "", "gap_closed": "",
                "status": "not_assessed", "note": "no tool met --min-train-samples on the remaining taxa"}
    rec = [r[0] for r in regrets]
    sb = statistics.mean(r[1] for r in regrets)
    gap = (1 - statistics.mean(rec) / sb) if sb > 0 else None
    return {**base, "mean_regret": f"{statistics.mean(rec):.4f}", "single_best_mean_regret": f"{sb:.4f}",
            "near_optimal_rate": f"{sum(r <= margin + 1e-12 for r in rec) / len(rec):.4f}",
            "gap_closed": "" if gap is None else f"{gap:.4f}", "status": "assessed", "note": ""}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--tool-status")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--min-train-samples", type=int, default=int(os.environ.get("RECOMMENDATION_MIN_SAMPLES", 5)))
    ap.add_argument("--near-optimal-margin", type=float, default=float(os.environ.get("NEAR_OPTIMAL_MARGIN", 0.05)))
    ap.add_argument("--min-expected-score", type=float,
                    default=float(os.environ.get("RECOMMENDATION_MIN_EXPECTED_SCORE", 0.40)))
    ap.add_argument("--confirm-holdout", action="store_true",
                    help="evaluate the split=holdout isolates once; refuses if already done")
    args = ap.parse_args()

    metadata = {r["sample_id"]: r for r in er.read_tsv(args.samples) if r.get("sample_id")}
    organism = {s: (m.get("organism") or "not_recorded") for s, m in metadata.items()}
    table = er.score_table(er.read_tsv(args.scores), "f1", er.read_failed(args.tool_status))
    holdout = {s for s, m in metadata.items() if (m.get("split") or "").strip() == "holdout"}
    marker = Path(f"{args.out_prefix}.holdout_evaluated.json")
    if args.confirm_holdout and marker.exists():
        raise SystemExit(f"ERROR: the holdout was already evaluated ({marker}); it is evaluated once only")
    development = {s: v for s, v in table.items() if s not in holdout}

    rows = []
    for level, key in (("genus", genus_of), ("phylum", lambda m: (m.get("phylum") or "").strip())):
        groups = {}
        for sample in development:
            groups.setdefault(key(metadata.get(sample, {})) or "not_recorded", set()).add(sample)
        if set(groups) <= {"not_recorded"}:
            rows.append({"level": level, "held_out_group": "", "n_isolates": len(development), "n_training_isolates": "",
                         "mean_regret": "", "single_best_mean_regret": "", "near_optimal_rate": "", "gap_closed": "",
                         "status": "not_assessed", "note": f"no {level} recorded for any isolate"})
            continue
        for group, held in sorted(groups.items()):
            if group == "not_recorded":
                rows.append({"level": level, "held_out_group": group, "n_isolates": len(held), "n_training_isolates": "",
                             "mean_regret": "", "single_best_mean_regret": "", "near_optimal_rate": "", "gap_closed": "",
                             "status": "not_used_as_fold", "note": f"isolates without a {level}: counted, not dropped"})
                continue
            rows.append(fold_row(level, group, development, held, organism, args.min_train_samples,
                                 args.near_optimal_margin, args.min_expected_score))
    if holdout:
        if args.confirm_holdout:
            held = {s for s in holdout if s in table}
            row = fold_row("holdout", "split=holdout", table, held, organism, args.min_train_samples,
                           args.near_optimal_margin, args.min_expected_score)
            rows.append(row)
            marker.write_text(json.dumps({"evaluated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"), "n_isolates": row["n_isolates"], "mean_regret": row["mean_regret"]}, indent=2)
                + "\n", encoding="utf-8")
        else:
            rows.append({"level": "holdout", "held_out_group": "split=holdout", "n_isolates": len(holdout),
                         "n_training_isolates": "", "mean_regret": "", "single_best_mean_regret": "",
                         "near_optimal_rate": "", "gap_closed": "",
                         "status": "locked" if not marker.exists() else "already_evaluated",
                         "note": "evaluated once, with --confirm-holdout" if not marker.exists()
                         else f"see {marker.name}"})
    er.write(f"{args.out_prefix}.leave_taxon_out.tsv", FIELDS, rows)
    print(f"[leave_taxon_out] {sum(r['status'] == 'assessed' for r in rows)} assessed fold(s), "
          f"{len(holdout)} holdout isolate(s) -> {args.out_prefix}.leave_taxon_out.tsv")


if __name__ == "__main__":
    main()
