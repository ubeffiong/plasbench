# Scientific and statistical validation

Hand-calculated fixtures were run through the real scripts (`python/score_plasmids.py`, `python/score_bins.py`). The fixture script is `scratchpad/fx/run_fixtures.py`; commands and raw output are in `TEST_LOG.md` (T3-T5). No minimap2 was available, so PAF files were written by hand; this tests the scoring code, not alignment.

## Executed validations

| # | Metric | Fixture | Expected (hand calc) | Actual | Verdict |
|---|---|---|---|---|---|
| V1 | Base precision / F1 | Chromosome 1000 bp, plasmid 100 bp. Prediction = the plasmid (100 bp, aligned) + 5000 bp contig that does not align | Precision on mapped bases = 100/100 = 1. Whole-output precision = 100/5100 = 0.0196 | precision 1.0000, F1 1.0000, strict_precision 0.0196 | Code matches its documented definition; the definition lets junk output go unpenalised (PB-001) |
| V2 | Redundancy | Same plasmid emitted twice | TP counted once; duplicate not penalised | precision = recall = F1 = 1.0; redundant_pred_bp = 100 | As designed; inflation is free (PB-002) |
| V3 | Fragmentation | Plasmid as 20 x 5 bp contigs, tiling it | Union coverage = 100% | recall 1.0, ge90 1.0 | As designed; fragmentation invisible at base level (PB-002) |
| V4 | lw_bin_f1 on zero-plasmid isolate | Chromosome-only truth, empty bins | Undefined (no plasmid to find) | lw_bin_f1 = 0.0000, bin_f1 = 0.0000 (score_plasmids F1 = blank on the same isolate) | **Discrepancy.** Inconsistent undefined/zero convention (PB-003) |
| V5 | Chromosome contamination, two chromosomes | Bin aligns 1000 bp plasmid + 1000 bp chrA + 1000 bp chrB | chromosome bp = 2000; share = 1000/3000 = 0.333 | chromosome_aligned_bp = 1000; bin_share = 0.5000 | **Discrepancy.** Intervals merged across replicons (PB-004) |
| V6 | Report warning logic | recall = "0.0000" | `(recall or 1) < 0.9` should be True | False | **Bug** (PB-019) |

## Endpoint review (static, with the evidence from the scoring pass)

| Endpoint | Implemented at | Definition as coded | Discrepancy / consequence | Recommended correction |
|---|---|---|---|---|
| Base precision / recall / F1 | score_plasmids.py:286-301 | TP = covered plasmid bp; FP = covered chromosome bp; FN = missed plasmid bp | Unmapped and filtered output not in the denominator (V1). The documentation says so, but the leaderboard does not make it visible | Report strict_precision beside F1; version the endpoint |
| plasmid_recall / ge50 / ge90 | score_plasmids.py:741-756 | Merged coverage from any record | Chimeric and duplicate records still contribute | Add best-candidate and off-target columns |
| Circular recall | score_plasmids.py:772,780 | Coverage >= 0.9 or 0.99995 | Topology of the prediction is never checked; name implies closure | Rename or add a real circularity check |
| lw_bin_f1 | score_bins.py:304-313 | Ungated Hungarian by aligned bp | Zero-plasmid case returns 0 (V4); chromosome merge (V5) | Fix both |
| CPRR | score_bins.py:316-343 | Per truth plasmid: matched, coverage >= 0.95, share >= 0.95, not split, identity >= 0.99 | Bin-level, so contig fragmentation within a bin is invisible; share inflated by V5 | Keep as headline; add contigs-per-plasmid |
| bin_f1 (count) | score_bins.py:434-451 | Gated Hungarian, completeness and purity >= 0.9 | Count-based, 0 on zero-plasmid | Blank on zero-plasmid |
| NMI / VI / ARI | score_bins.py:110-227 | bp-weighted contingency table with unassigned row | NMI cliff: 1% unassigned can take NMI from 1 to 0 on a single-plasmid isolate; duplicate bins double-count (static, not executed) | Mark supplementary only; do not rank on it |
| Bootstrap / permutation | resampling.py:109-226 | Cluster-level resampling, 1000 / 10000 draws, fixed seeds | Correct unit. With 5 clusters min two-sided p about 0.0625; same seed reused for all comparisons | Suppress p-values below 6 clusters |
| Holm correction | aggregate_results.py:657-819 | Within (track, task) pairwise | Family includes baselines and failed-tool rows; no correction across endpoints | Define the family explicitly |
| Ranking | aggregate_results.py:410-614 | ranking_score by group metric; ties broken by name | Ties get sequential ranks; top-vs-runner-up tested only | Report tied ranks |
| Failure handling | headline_design.py:223-264 | Failure counts as 0 on the headline only | Secondary means and cprr columns omit failures (PB-017) | One policy, labelled n per column |

## Items I could not validate
- Alignment-dependent behaviour (MAPQ >= 20 filter, query-coverage filter, repeat handling): needs minimap2 and real or simulated genomes. Reading the code suggests repeat-borne AMR genes (for example in transposons with a chromosomal copy) are dropped for every tool by the MAPQ filter. This is a Static risk and is not a register row, because its effect size is unmeasured.
- Truth-label quality, database leakage magnitude, clonal-group chaining: need the real cohort and tool databases.
- Power and equivalence procedures: read only.

## Primary-endpoint separation
The code does separate classification (F1), binning (lw_bin_f1) and reconstruction (sample_cprr) per track and per `binning_capable`. The separation is not complete: reassemblers that are `binning_capable` are ranked with contig binners (PB-014), and one leaderboard row mixes sample sets (PB-017).
