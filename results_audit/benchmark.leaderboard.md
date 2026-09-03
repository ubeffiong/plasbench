# Plasmid reconstruction leaderboard

Ranked by mean base-level F1 across samples (positive class = plasmid).

| Rank | Tool | Scored | Completed | Failed | Skipped | Mean precision | Mean base recall | Mean plasmid recall | **Mean F1** | 95% F1 CI | Median F1 |
|---:|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | good | 2 | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | **1.000** | n < 5 | 1.000 |
| 2 | leaky | 2 | 2 | 0 | 0 | 0.865 | 1.000 | 1.000 | **0.927** | n < 5 | 0.927 |
| 3 | shy | 2 | 2 | 0 | 0 | 1.000 | 0.536 | 0.250 | **0.697** | n < 5 | 0.697 |

_Recall = completeness (fraction of true plasmid bases recovered). Plasmid recall = fraction of truth plasmids meeting the configured recovery threshold; it is not available for legacy score rows. Precision = 1 - chromosomal contamination._
