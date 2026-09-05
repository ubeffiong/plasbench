# Scores Contract (optional PR-curve/PR-AUC support)

Companion to `adapters/BINS.md`, for tools that expose a per-record confidence
score (plASgraph2, geNomad, PLASMe) rather than only a hard plasmid/not-plasmid
call. This is an entirely optional, additive axis: a tool with no `.scores.tsv`
is scored exactly as every existing tool always has been -- one hard-inclusion
point (precision/recall/F1) from `pred_<tool>.plasmid.fasta` alone.

## What an adapter writes

Two new files, alongside the existing `pred_<tool>.plasmid.fasta`
(+`.bins.tsv` where applicable), which keeps its exact current meaning: the
tool's actual hard call, still what the point-estimate F1 is computed from.

- **`pred_<tool>.candidates.fasta`** -- every contig/node the tool actually
  scored, a superset of (or equal to) `.plasmid.fasta`'s record set. Not an
  extra tool invocation: geNomad, PLASMe, and plASgraph2 all natively score
  every input contig/node they receive, so this is just the adapter writing
  out that wider set instead of discarding it.
- **`pred_<tool>.scores.tsv`** -- header `record_id\tprobability` (extra
  columns are tolerated). Rules:
  - `record_id` must be unique, and the record_id set must **exactly equal**
    the record ids in `.candidates.fasta` -- not `.plasmid.fasta`'s. A
    mismatch (missing or extra ids) is a hard error, not a silent drop.
  - `probability` must parse as a float in `[0, 1]`. It is **not** required
    to sum to 1 across records -- this is a genuinely continuous, uncalibrated
    score, the same allowance `validate_gplas_classifier.py`'s
    `Prob_Plasmid`/`Prob_Chromosome` columns already make.

## Why a candidates universe, not just scores for the hard call

A PR-curve sweep must be able to both add and remove records as the threshold
moves. If `.scores.tsv` only ever covered `.plasmid.fasta`'s own records, the
sweep could only shrink the tool's hard call, never grow it -- a one-sided,
misleading curve. Lowering the threshold below the tool's native operating
point should pull in additional, lower-confidence candidates it did **not**
put in its hard call.

## How the pipeline uses this

`scripts/05_score.sh` maps `.candidates.fasta` against the reference with a
*second*, independent minimap2 call (same preset/filters as the point
estimate's own PAF), then passes `--pred-scores`/`--pred-candidates-fasta`/
`--pred-candidates-paf` to `python/score_plasmids.py`, which sweeps every
distinct probability value as a threshold and writes:

- `<tool>.pr_curve.tsv` -- `threshold, precision, recall, tp_bp, fp_bp, fn_bp`,
  one row per swept threshold, plus one synthetic row at the top
  (`threshold=inf, precision=1.0, recall=0.0`) for the empty-inclusion
  endpoint -- the standard `precision_recall_curve` convention, not the
  0/0 -> 0.0 fallback the rest of this codebase otherwise uses, which would
  spuriously depress the trapezoidal AUC.
- `<tool>.pr_summary.tsv` -- `pr_auc, pr_n_thresholds`, one row.

`python/merge_pr_metrics.py` folds `pr_auc`/`pr_n_thresholds` into `scores.tsv`
(mirroring `merge_bin_metrics.py`'s existing role for `bin_f1`), and
`aggregate_results.py` surfaces `mean_pr_auc`/`n_pr_scored` in the leaderboard
alongside `mean_f1` -- supplementary, never a ranking replacement, since it is
only defined for the subset of tools that expose probabilities.

## What this is not

This is unrelated to `evidence.tsv`'s `ml_probability` (if added there): that
column, if used, is informational-only display for a human choosing an
operational method on a new sample -- it is never read by `score_plasmids.py`
and never produces a PR curve or moves the leaderboard.
