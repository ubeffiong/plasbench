# Panel examination and scoring specification: alignment and implementation

This records how the panel's examination (rounds 1-5 and the edge-case laboratory) and
the Scoring Specification v0.1 map onto PlasBench, and what was changed. Each panel
question is answered in
[`FAQ_QUESTION_BANK.md`](FAQ_QUESTION_BANK.md#panel-examination-rounds-1-5-and-edge-case-lab);
the frozen decisions are in [`PREREGISTRATION.md`](PREREGISTRATION.md).

## 1. Scope alignment (panel question 1.1)

PlasBench benchmarks plasmid *reconstruction* and *classification* tools on isolates with
complete reference genomes.

| | PlasBench |
|---|---|
| **Input** | Paired-end Illumina reads (assembled by PlasBench), optionally ONT/PacBio long reads, plus a complete reference assembly as truth. Local FASTA/FASTQ via `plasbench init-local`. |
| **Core operation** | Run each reconstruction or classification tool, then score its predicted-plasmid sequence and bins against the same isolate's truth. |
| **Primary output** | Per-isolate and per-tool scores, ranked leaderboards per input track and task, and an offline HTML report. An operational mode recommends a tool for an isolate without truth. |
| **Intended user** | Laboratories and pipeline maintainers choosing a reconstruction method, and tool developers. |

Plasmid clustering, communities, database search, relatedness, backbone/accessory
decomposition and phylogeny are **outside this benchmark**; the panel's questions on them
are answered in one line each.

## 2. Decisions recorded, and what they required

| Decision | Recorded | Implemented as |
|---|---|---|
| **E.15** primary labelling scheme | **Scheme 3: NCBI/database labels**, pre-registered | `TRUTH_LABEL_SCHEME=ncbi` (default) scores `truth.tsv`; the NCBI field and the sequence report's SHA-256 and date are written beside every label; a written rule marks isolates without an NCBI record `not_applicable:<truth_source>`; Scheme 1 and the evidence scheme are rank-sensitivity variants with Kendall's tau; in- vs not-in-database recovery per tool (#12). |
| **D6** tool crash or missing output | **F1 = 0, penalised in ranking** | Kept; infrastructure failures (never started, disk full) are now separated and never scored. |
| Scoring specification | Adopted items below, one branch, one PR | Contig-level scoring is a **parallel layer**; the base-level scorer stays primary. |

**Alignment problem found and fixed.** Since #7, stage 5 scored against the evidence-checked
`truth.scored.tsv`, which is the evidence scheme, not the recorded Scheme 3. The scheme is now
explicit and defaults to Scheme 3. Setting `TRUTH_LABEL_SCHEME=evidence` restores the old behaviour.

## 3. What was implemented

| # | Item | Change | Wired into |
|---|---|---|---|
| WP0 | Pre-registration freeze | `config/prereg.tsv`, `freeze_prereg.py` (`--write`, `--verify`, `--status`), `REQUIRE_PREREG` | stage 4 gate; manifest `preregistration`; report "Pre-registration"; CLI `freeze-prereg` |
| WP1 | MCC, F2, F0.5, abstention; outcome states per plasmid; ARI | `score_plasmids.py`, `score_bins.py --outcomes-out` | `scores.tsv`, leaderboard, report "MCC &amp; F-beta", "Plasmid outcomes" |
| WP2 / P1 / P3 | Label schemes, dimers, truth grades | `label_schemes.py`, `detect_dimers.py` (`COLLAPSE_DIMERS`), `truth_quality_grade` | stage 2, stage 5 truth selection, stage 6 tables, report "Label schemes" |
| WP3 | Contig-level layer | `contig_classification.py --bins` adds contig binning F1 and shared/unassigned lengths (the existing module, not a second scorer) | stage 5, leaderboard, rank axis, report "Contig layer" |
| WP4 | Outcome states and fairness | `infrastructure_failure`, `TOOL_RETRIES`, `TOOL_TIMEOUT_SECONDS`, `tool_outcomes.tsv` | stage 4, aggregation, report "Run outcomes" |
| WP5 | Recommender and warnings | `evaluate_recommender.py`, `evaluate_warnings.py` | stage 6, report "Recommender" |
| WP6 / P2 | Validation design and statistics | Wilcoxon + equivalence; `leave_taxon_out.py` with a once-only holdout; cohort columns; new rank axes | stage 6, comparisons, report "Transfer &amp; tests" |
| WP7 | AMR placement | `score_amr_placement.py`, `config/amr_gene_classes.tsv` | stages 5-6, report "AMR placement" |
| P4 | D11 performance floor | `RECOMMENDATION_MIN_EXPECTED_SCORE` (0.40) | `benchmark.recommendations.tsv` |
| P5 | D15 transparency | "Tools compared" reasons in the run-outcome section | report |
| P6 | 3.3, 2.4 refusal states | `insufficient_sequence`, `ambiguous_between_references` | operational screen, report labels |
| P7 | D13 pre-ranking gate | `assembly_qc_gate.py` (advisory) | stage 8 warning; stage 6 `benchmark.assembly_qc.tsv`, scored as a warning |
| WP8 | Report, docs, tests | `report_scoring_spec.py` (ten sections, explicit not-run notes, Markdown summary); guide, METHODS, PREREGISTRATION, FAQ, README; 15 new tests | demo, `test/run_tests.sh` |

## 4. Not implemented, and why

| Item | Status | Reason |
|---|---|---|
| D1 short-read-only plasmid absent from truth | Already handled | Unmapped predicted sequence is never a false positive; short-read-only truth plasmids are flagged by long-read depth. Laboratory confirmation needs a wet-lab step. |
| D3 conflicting labels within an assembly | Already handled (#8) | Contradictory sequence-report entries become `REVIEW` and stop stage 2. |
| D5 integrated plasmid | Partly | The truth-label audit flags chromosome-labelled replicons carrying plasmid markers; the integrated-element thresholds are `TO_FIX`. |
| D8 shared region between two plasmids | Rule stated | Contigs aligning equally well to several replicons are AMBIGUOUS and excluded (counted as shared length), not multi-assigned. |
| D9 multi-copy AMR gene | Already handled | One truth row per copy; placement matches copies by position. |
| D10 parser robustness | Partly | Fixture tests per adapter and recorded versions; no run-time schema check per version. |
| Plasmid-free isolates scored 0 in F1 | Not adopted | F1 is undefined there; reported in the negative-control table. |
| Summed contig length as the headline recall denominator | Not adopted | Kept contig-layer only. |
| Context model / contamination gate beyond the QC gate | Not adopted | Needs real data. |
| More than 100 in-house isolates; pilot, orthogonal validation, temporal holdout, protocol publication | Open | Data collection and a study protocol, not code. |
| Clustering, relatedness, database search, phylogeny | Outside this benchmark | See section 1. |

## 5. Known limits

No real-data run yet: the recommender metrics are verified mechanically on synthetic data
only. The `TO_FIX` values are the specification's proposed defaults, awaiting the panel. The
contig layer is unvalidated against a second scorer. In-house isolates are not yet included.
