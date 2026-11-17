# Plasmid reconstruction leaderboard

Tools are ranked only within their own input track and task, never across them. **Reconstruction** (binning-capable tools) is ranked by length-weighted binning F1 on the short-read track and by isolate-level CPRR on the long-read and hybrid tracks; **classification** (classifier-only tools) by base-level F1. The ranking score averages per-species means when enough independent isolates exist, over reference tiers 1-2 only, using the samples every ranked tool shares.

## reconstruction (ranked by length-weighted binning F1)

| Rank | Tool | Scored | Completed | Failed | Skipped | **Ranking score** | 95% CI | Basis | CPRR | Mean base F1 | Mean precision | Mean base recall | Significant vs runner-up |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|---:|---:|---:|---:|:---|
| 1 | mob_recon | 1 | 10 | 0 | 0 | **0.838** | < 5 independent units | pooled (no species with enough independent clusters); 1 shared sample(s), 1 cluster(s) | 0.0% (0/2); per isolate 0.0%; AUC 0.80–0.99 0.368 | 0.838 | 0.808 | 0.871 | not assessed |

## classification (ranked by base-level classification F1)

| Rank | Tool | Scored | Completed | Failed | Skipped | **Ranking score** | 95% CI | Basis | CPRR | Mean base F1 | Mean precision | Mean base recall | Significant vs runner-up |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|---:|---:|---:|---:|:---|
| 1 | platon | 1 | 10 | 0 | 0 | **0.861** | < 5 independent units | pooled (no species with enough independent clusters); 1 shared sample(s), 1 cluster(s) | not bin-scored | 0.861 | 0.852 | 0.871 | not assessed |
| 2 | plasmidspades | 1 | 10 | 0 | 0 | **0.833** | < 5 independent units | pooled (no species with enough independent clusters); 1 shared sample(s), 1 cluster(s) | not bin-scored | 0.833 | 0.816 | 0.851 | not assessed |
| 3 | baseline_coverage | 1 | 10 | 0 | 0 | **0.000** | < 5 independent units | pooled (no species with enough independent clusters); 1 shared sample(s), 1 cluster(s) | not bin-scored | 0.000 | 0.000 | 0.000 | not assessed |


_Length-weighted binning F1: bases placed in the correct (one-to-one matched) bin, over all truth-plasmid bases (recall) and over all bases the bins align to (precision). CPRR = share of truth plasmids reconstructed correctly (matched, covered, uncontaminated, not split, and -- where truth was not polished with the benchmark's own reads -- high identity). A tool that predicts nothing, or whose run failed, on a plasmid-bearing sample scores 0 there; a sample missing for any other reason is removed from every tool's ranking. CIs resample independent clusters (shared BioProject or clonal group) within each species._
