# Panel examination: alignment review and implementation plan

This records how the panel's examination (rounds 1-5 and the edge-case laboratory, "Mode D") maps
onto PlasBench as implemented, and what was changed in response. Answers to each panel question are
in [`FAQ_QUESTION_BANK.md`](FAQ_QUESTION_BANK.md#panel-examination-rounds-1-5-and-edge-case-lab).

## 1. Scope alignment (panel question 1.1)

The panel worked from an assumption that PlasBench assigns plasmids to communities against PLSDB
(typing and clustering). **It does not.** PlasBench benchmarks plasmid *reconstruction* and
*classification* tools on isolates with complete reference genomes:

| | PlasBench |
|---|---|
| **Input** | Paired-end Illumina reads (assembled by PlasBench), optionally ONT/PacBio long reads, plus a complete reference assembly as truth. Local FASTA/FASTQ via `plasbench init-local`. |
| **Core operation** | Run each reconstruction or classification tool, then score its predicted-plasmid sequence and bins against the same isolate's truth. |
| **Primary output** | Per-isolate and per-tool scores, ranked leaderboards per input track and task, and an offline HTML report. An operational mode recommends a tool for an isolate without truth. |
| **Intended user** | Laboratories and pipeline maintainers choosing a reconstruction method, and tool developers. |

So the panel's **[Reconstruction]** questions apply directly. Its **[Clustering]** questions (2.1 size
asymmetry, 2.3 label stability, 2.5 multi-membership, 2.6 database redundancy, 3.1 scalability of
all-against-all, 3.4 explaining relatedness, 4.1-4.6) apply only to the small, experimental
operational Mash screen (`classify_operational_plasmid.py`), and are answered there.

## 2. Decisions recorded by the developer, and what they require

| Decision | Recorded | What PlasBench must do |
|---|---|---|
| **E.15** primary labelling scheme | **Scheme 3: NCBI/database labels**, pre-registered | Score the headline on NCBI labels. Pin the exact field and snapshot. Run Schemes 1 (any non-chromosomal replicon) and 2 (evidence-based, chromids excluded) as sensitivity analyses. Publish every replicon's label under all three schemes, and Kendall's tau between the rankings. Report in-database versus novel plasmids. |
| **D6** tool crash or missing output | **F1 = 0, penalised in ranking** | Already the rule on main (#5); kept, and stated in the scoring specification. |

**Alignment problem found.** Since #7, stage 5 scores against `truth.scored.tsv`, where replicons whose
label conflicts with evidence are AMBIGUOUS and removed. That is close to Scheme 2, not the recorded
Scheme 3. This round makes the scheme explicit and **defaults to Scheme 3**, as recorded.

## 3. Plan: what is updated and implemented

| # | Panel item | Change | Wired into |
|---|---|---|---|
| P1 | E.15, D3, D4, D17 | `TRUTH_LABEL_SCHEME` (`ncbi` default; `nonchromosomal`; `evidence`) selects the scored truth. `python/label_schemes.py` writes every replicon's label under all three schemes, and flags where they differ. The NCBI field and snapshot are pinned in truth provenance. | stage 2/5 truth selection; stage 6 `benchmark.label_schemes.tsv`; HTML section; manifest |
| P2 | E.15 sensitivity | `rank_sensitivity.py` re-scores every (sample, tool) PAF under each scheme's truth and reports ranks and Kendall's tau against the primary scheme. | `benchmark.rank_robustness.tsv` (scheme variants); HTML |
| P3 | D2 multimer truth | `python/truth_multimers.py` detects replicons that are tandem copies of themselves (self-alignment at an offset of about L/2). They are flagged in the label table, and are AMBIGUOUS under the evidence scheme. | stage 2; label table; HTML |
| P4 | D11 absolute-performance floor | `RECOMMENDATION_MIN_EXPECTED_SCORE` (0.40). Below it, the recommendation becomes "no tool expected to reconstruct plasmids reliably" instead of naming a best tool. | `benchmark.recommendations.tsv`; HTML recommendations |
| P5 | D15 report transparency | A "Tools compared" table: which tools ran, which were skipped or failed, and why. | HTML |
| P6 | 3.3, 2.4 refusal states | The operational screen gains `insufficient_sequence` (query shorter than a floor) and `ambiguous_between_references` (the two nearest references are near-equidistant but in different clusters), next to `close_reference_match`, `no_close_reference` and `insufficient_reference`. | `classify_operational_plasmid.py`; operational report |
| P7 | D13 pre-ranking quality gate | `python/assembly_qc_gate.py` flags assemblies that look mixed or contaminated (too large for one bacterial genome, or bimodal GC across long contigs) before operational ranking. | stage 8; HTML |
| P8 | All | FAQ entries for every panel question (with status), and README rows. | `docs/FAQ_QUESTION_BANK.md`, README tables |

## 4. Not implemented, and why

| Item | Status | Reason |
|---|---|---|
| D1 short-read-only plasmid absent from truth | Already handled | Unmapped predicted sequence is never a false positive (`unmapped_pred_bp`), and short-read-only truth plasmids are flagged by long-read depth (#7). Laboratory confirmation needs a wet-lab step. |
| D2 collapsing a multimer to a monomer | Flag only | Rewriting the truth FASTA is error-prone; the replicon is flagged, and under the evidence scheme excluded. |
| D3 conflicting labels within an assembly | Already handled (#8) | Contradictory sequence-report entries become `REVIEW` and stop stage 2. Cross-assembly conflicts do not arise: each isolate has one pinned assembly. |
| D5 integrated plasmid | Partly | The truth-label audit (#8) flags chromosome-labelled replicons carrying plasmid markers; integration inside a chromosome is not called. |
| D8 shared region between two plasmids | Rule stated | Contigs aligning equally to several replicons are AMBIGUOUS and excluded (`contig_classification.py`), not multi-assigned. |
| D9 multi-copy AMR gene | Already handled | Curated AMR truth requires one row per gene copy with its own location (`validate_amr_truth.py`). |
| D10 parser robustness | Partly | Every adapter has a fixture test (`test/test_*_adapter.sh`) and tool versions are recorded; version-specific output schemas are not checked at run time. |
| D16 limits of warnings | Documented | Each operational warning states its validity range in METHODS. |
| 2.1, 2.3, 2.5, 2.6, 3.1, 3.4, 4.1-4.6 | Not applicable to the benchmark | Clustering questions; see section 1. |
| Wet-lab and design items (E.9 pilot, E.10 orthogonal validation, E.11 temporal holdout, E.13 pre-registration) | Open | They need data collection and a study protocol, not code. The temporal holdout is supported by the database-date screen and in-database recovery split. |
