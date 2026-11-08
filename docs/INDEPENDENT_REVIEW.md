# Independent scientific, technical and innovation review: PlasBench

**Reviewed object:** PlasBench, a benchmark of plasmid reconstruction and classification tools, at `main` commit `52f3b2a` (8 November 2026), with the documentation PR #13 applied.
**Stance:** sceptical and constructive. Every criticism carries a reason, a consequence and a recommendation.
**Scope (agreed with the project lead):** PlasBench is assessed as the benchmark it is. Questions about functions outside a benchmarking pipeline are not part of this review.

---

## 0. Evidence basis and limits (read this first)

**Established by reading code, configuration and data, with a file and line in Appendix A:** how truth is labelled, how scores, bins and rankings are computed, what the statistics do, what the tests cover, how the install pipeline is wired, the composition of the shipped cohorts.

**Established by running something:** the cohort composition and reference-tier counts were recomputed with the project's own `python/truth_provenance.py` and a script over `cohorts/public-v3.tsv`; the full offline test suite and the stage-level tests were run on Linux with real minimap2 for the changes merged in PRs #10 to #12.

**Not established:** no benchmark was run on real data (none exists, see Part 8). No plasmid reconstruction tool other than the aligner was executed by any test. Statements about how the tools behave rest on their publications and on the adapters, not on a run.

**Verified references (the only ones cited):** Robertson and Nash 2018, *Microbial Genomics* 4(8):e000206 (MOB-suite); Camargo et al., *Nature Biotechnology*, doi 10.1038/s41587-023-01953-y (geNomad); Mane et al. 2024, *BMC Bioinformatics*, doi 10.1186/s12859-024-05941-0 (PlasEval); Teixeira et al. 2025, *Briefings in Bioinformatics* 26(6):bbaf589, doi 10.1093/bib/bbaf589; Arredondo-Alonso et al. 2017, *Microbial Genomics* (limits of short-read plasmid reconstruction); Schmartz et al. 2022, *Nucleic Acids Research* 50:D273-D278, doi 10.1093/nar/gkab1111 (PLSDB, cited only as the source of some tools' own databases). Any other tool name is mentioned without a citation.

**Decisions taken with the project lead during this review (recorded in Parts 12 and 15):**

| # | Decision |
|---|---|
| D1 | Keep the headline over reference Tiers 1 and 2. Add a mandatory sensitivity analysis on independent-polish truth only, and state it wherever the headline appears. |
| D2 | Report recovery on truth plasmids absent from each tool's own database beside the headline. |
| D3 | The README tagline and concept note say what the tool does (benchmarking reconstruction and classification tools against complete reference assemblies). |
| D4 | Functions that are not part of a benchmarking pipeline are removed from the documents rather than listed as gaps. |

---

## Part 1. Executive assessment

**What the tool is.** PlasBench maps the predicted-plasmid output of each tool onto a complete reference assembly with minimap2 and scores it per reference base, per plasmid and per bin. Binning-capable tools are ranked on a length-weighted binning F1 with a correct-plasmid-reconstruction rate (CPRR) as the secondary endpoint; classifiers are ranked on base-level F1. Ranking is within track and task, species-balanced where data allow, with cluster-aware intervals. It sits on top of about 165 test files, a locked container, and an HTML report with explicit empty states.

**What problem it addresses.** Choosing a plasmid reconstruction or classification tool without evidence. The published benchmark in this area reports that less than half of plasmids were perfectly reconstructed by the best reconstruction tool and that accuracy depends on database representation and assembly contiguity (Teixeira et al. 2025), and an earlier study found that no tested program could fully and unambiguously predict distinct plasmid sequences (Arredondo-Alonso et al. 2017). A reproducible, well-controlled benchmark is a real need.

**Overall assessment.**
1. The **framework** is careful and unusually honest about its limits: failure scores zero, ranking uses shared samples, resampling is by cluster, long-read tools are guarded against circular truth, base-level accuracy is withheld where truth is not independent, and the docs state their own weaknesses.
2. It is **not yet demonstrated**. There is no real-data result; the shipped leaderboards are synthetic. The statistics have never been checked by simulation, no plasmid tool is exercised by any test, and the truth the benchmark depends on is, for 91 of 98 shipped isolates, polished with the same Illumina reads the tools are scored on.
3. Several **choices are not justified**: the alignment filters, the binning gates, and the CPRR thresholds have no derivation or sensitivity test, and the minimum of five clusters makes a conventional significance level unreachable.
4. The **leakage control is weak on `main`**: a release-date screen cannot show that a plasmid is novel to a tool's database; a sequence-level check exists only for databases on disk.
5. The **install pipeline was inconsistent** (fixed in a pending PR): samtools, mash and barrnap, used by default or opt-in stages, were not wired like minimap2.

**Most important findings, ranked.**
1. No real-data evidence (Part 8).
2. Truth independence: 0 of 98 isolates are Tier 1; 91 are polished with the benchmark's own reads (Part 5.1).
3. Leakage is date-based on `main` (Part 5.4).
4. The significance test cannot reach p < 0.05 with five clusters, and two different intervals are reported side by side (Part 5.3).
5. Unjustified thresholds throughout (Part 5.2).
6. The headline silently falls back to all samples when no reference reaches Tier 2 (Part 5.1).
7. The accuracy dimension added by this project is assessable for only 2 of 98 isolates (Part 5.2).

**Verdict:** promising but requires methodological refinement (Part 16).

---

## Part 2. Understanding of the project

**Workflow (verified in `scripts/` and `python/`).** Stage 1 downloads a complete reference and matched reads. Stage 2 labels each reference sequence plasmid or chromosome and builds an evidence-checked truth (`label_truth_evidence.py`), a reference tier (`truth_provenance.py`) and a reference annotation (`annotate_reference.py`). Stage 3 assembles reads. Stage 4 runs each tool and records status, runtime and memory. Stage 5 aligns each prediction to the reference and scores it (`score_plasmids.py`, `score_bins.py`, plus contig-level and further per-run analyses). Stage 6 aggregates, ranks, tests, and builds the report. Optional stages cover long-read tools, a metagenomic track, and an operational recommendation for a sample without truth.

**Feature status ledger.**

| Feature | Proposed | Designed | Implemented | Tested | Validated on real data |
|---|---|---|---|---|---|
| Base-level, plasmid-level and bin-level scoring | yes | yes | yes | yes (hand-computed cases, real aligner) | no |
| Headline ranking, species balance, tiers | yes | yes | yes | partly (control flow; one worked case each) | no |
| Cluster-aware intervals and permutation tests | yes | yes | yes | consistency only (Part 5.3) | no |
| Truth evidence labels and provenance tiers | yes | yes | yes | yes (unit) | no |
| Date-based leakage screen | yes | yes | yes | yes | no |
| Sequence-level database membership | yes | yes | implemented (PR #12, merged) | yes (real aligner) | no |
| Nucleotide accuracy, feature preservation, NGOC, bin quality, performance, power, scenarios | yes | yes | yes | yes (hand-computed) | no |
| Optional five-dimension composite | yes | yes | yes | yes | no |
| Operational tool recommendation | yes | yes | yes | unit only | no |
| Mash nearest-reference screen | yes | yes | yes, off by default | unit only (faked mash) | no |
| Metagenomic track | yes | yes | yes | unit only | negative-control and review panels only |

**Cohorts.** `public-v3` has 98 isolates from 81 BioProjects (largest: 7 isolates), in 7 species: *E. coli* 36, *K. pneumoniae* 17, *Salmonella enterica* 16, *A. baumannii* 13, *E. faecium* 10, *E. hormaechei* 5, *S. aureus* 1. Technology: 93 hybrid, 5 long-read.

---

## Part 3. Scientific problem assessment

**Is the problem real and well defined?** Yes. The question "which tool should I trust for plasmid reconstruction on my kind of isolate, and how much?" is concrete, answerable with a reference, and unanswered by single-study benchmarks that use few species. The unit of analysis is stated: reference base, plasmid, bin, isolate.

**Is it the right size?** Mostly. The benchmark tries to serve three audiences (tool developers, laboratories choosing a tool, reviewers) with one framework, and it adds an operational recommender, a metagenomic track and long-read tracks. Each is defensible, but each multiplies what must be validated. Recommendation: pre-state the one primary claim (below) and treat everything else as supporting.

**Suggested primary claim.** *On a stated, independent, taxonomically described reference panel, tool A recovers a larger share of truth plasmids correctly than tool B, by an amount the panel is large enough to detect.* Everything in the report should serve that sentence or say why it does not.

**What would make the problem statement stronger.** An explicit statement of the population the cohort represents (clinical Enterobacterales and a few others, public hybrid assemblies) and of the population it does not (Gram-positives other than one species, plasmid-free isolates, isolates without long-read finishing).

---

## Part 4. Novelty assessment

| Level | Assessment |
|---|---|
| A. Conceptual | Low. Scoring a prediction against a complete reference is the standard benchmarking idea. |
| B. Methodological | Moderate, by combination: failure-as-zero with shared-sample ranking, cluster-aware resampling, reference tiers recorded from provenance, evidence-checked truth labels, a length-weighted binning endpoint with CPRR, and masking of base-level accuracy where truth is not independent. Each is individually known; the combination and the explicitness are the contribution. |
| C. Computational | Low to moderate. Scoring is standard-library Python over minimap2 alignments; the Hungarian matching and interval merging are standard. |
| D. Biological | None claimed. |
| E. Operational | Moderate. A reproducible, locked, one-command pipeline with a legible report lowers the cost of repeating a benchmark. |
| F. Public health | None demonstrated. The tool produces no epidemiological output. |

**What already exists.** PlasEval (Mane et al. 2024) is a repeat-aware, contig-length-aware framework for evaluating plasmid binning and was applied to four tools on a set of *E. coli* genomes; the Teixeira et al. 2025 benchmark evaluated 12 detection tools and four reconstruction tools on assemblies from Enterobacterales and Enterococcus. PlasBench's scoring is not repeat-aware and PlasEval is only an imported cross-check.

**Strongest defensible novelty claim.** A reusable, provenance-aware benchmarking framework that makes the weaknesses of benchmark design (truth independence, leakage, abstention, non-independent samples) explicit and measurable. Not a new algorithm.

**Evidence that would establish it.** A side-by-side demonstration that, on the same data, PlasBench's controls change a ranking that a naive F1 benchmark would report, and that the change is in the direction the controls predict.

**Sufficient for a publication?** As a resource or benchmark paper, yes once real-data results exist. Not as a methods paper.

---

## Part 5. Methodological assessment

### 5.1 Truth

- **Source label.** Plasmid versus chromosome comes from the submitter's `assigned_molecule_location_type`; unresolvable sequences are `REVIEW` and stop the stage (E52, E53). A legacy option restores the guess.
- **Evidence labels.** Where marker callers ran, plasmid-labelled replicons without a marker, with rRNA, or under 5x long-read depth, and chromosome-labelled replicons carrying a marker, become `AMBIGUOUS` and are excluded from scoring (E32, E54). The markers come from MOB-suite and PlasmidFinder-type databases, the same evidence several benchmarked tools use, which favours those tools (acknowledged in the code).
- **Tiers.** Tier 3: short-read-first or unknown assembly strategy. Tier 2: long-read-first that fails a Tier-1 condition. Tier 1: long-read-first, polishing reads `none` or `independent`, and evidence-checked labels (E33). Strategy and polish are inferred from NCBI free text by pattern matching, with a conservative default that treats Illumina-polished long-read-first truth as `same_as_benchmark`.

**Findings.**

| Finding | Reason | Consequence | Recommendation |
|---|---|---|---|
| In `public-v3`, **0 of 98 isolates are Tier 1**, 79 are Tier 2 and 19 are Tier 3; **91 are polished with the benchmark's own reads**, 5 unknown, 2 none (E56). | Tier 1 is almost unreachable under the conservative polish default. | The headline rests on Tier 2 truth. Coverage and labels are not corrupted by read polishing, but the assumption is not quantified. | Per decision D1: keep the headline, add a mandatory sensitivity analysis restricted to independent-polish truth, and state it wherever the headline appears. Grow the independent-polish subset. |
| `base_level_metrics_valid` is `yes` for only **2 of 98** isolates (E56). | Identity-type metrics need independent truth. | The nucleotide-accuracy dimension (added by this project) is not assessable for 96 of 98 isolates. | Say so in every accuracy table (the report already shows "samples not assessable"); prioritise independent-polish isolates. |
| If no sample reaches Tier 2 the headline **silently falls back to all samples** (E27). | A convenience default. | A reader could take a Tier-3 headline for a Tier-1/2 one; only a label records it. | Make the fallback a visible warning in the leaderboard and report header, not a label. |
| The cohort column `truth_quality_tier` disagrees with the provenance tier: **8 of 15 short-read-first isolates are cohort tier "A"** but provenance Tier 3 (E56). | Two independent grading systems. | A curator reading the cohort file overestimates quality. | Drop or rename the cohort column; show the provenance tier only. |
| Marker evidence uses the tools' own databases (E32). | Practical: no independent marker source. | Mob_recon and platon see truth filtered by their own evidence. | Report scores with and without evidence-based exclusion (the label-scheme comparison). |
| A chromid labelled plasmid with a replicon marker passes as a plasmid; truth multimers and collapsed repeats are not detected. | No core-gene or multimer check. | Correct tools can be penalised; ranking is distorted on such isolates. | Add a core-gene/size sanity check and a multimer check to the truth audit; report the affected isolates. |
| Short-read tools get no technology-based block; their protection is only the tier labels. | The circularity guard covers long-read tools only (E34). | Acceptable if the tier labels are right, which depends on regex inference. | Read provenance from structured fields where they exist; list inferred values as such. |

### 5.2 Scoring and binning

**Definitions (E1 to E3).** TP is the reference plasmid bases covered by a retained alignment; FP is chromosome bases covered; FN is the plasmid bases missed. Unmapped, filtered or off-truth predicted bases are never FP (E3).

**Findings.**

| Finding | Reason | Consequence | Recommendation |
|---|---|---|---|
| The alignment filters (200 bp, identity 0.90, query coverage 0.20) and the recovery bands (0.5, 0.9, 0.99995) have **no derivation or sensitivity test** (E8 to E12). Only MAPQ 20 has a rationale. The script's own defaults are off (1, 0, 0, 0) (E4 to E7). | Chosen by convention. | The leaderboard depends on them in an unknown way. The 200 bp minimum is never varied by the robustness analysis. | Run a grid over every threshold on real data; report rank stability; document the reason for each default. |
| Predicted bases that do not align never count against precision (E3). | The scoring projects predictions onto the reference. | A tool that emits chimeric or repeat-rich output that fails MAPQ pays no precision penalty on the base-level metric. | Keep `strict_precision` and the robustness table; add a contamination-by-unmapped-bases column to the leaderboard. |
| Length-weighted binning precision counts only bases that aligned (E15); bins made of unmapped contigs cost nothing, and a mixed plasmid/chromosome bin is still matched (ungated match). | Design: ungated Hungarian match (E16). | The headline cannot see an assembly-error bin. | Report the count-based bin precision beside it (already a column) and CPRR (which does gate). |
| Binning gates `--min-bin-purity` 0.9 and `--split-threshold` 0.1 and the CPRR thresholds 0.95, 0.95, 0.99 are **hard-coded or pre-specified without justification** (E13, E14, E18, E19). | Pre-registered, not derived. | Pre-registration prevents fishing but not arbitrariness. | Justify each threshold by a simulation or a published criterion, or show the ranking is insensitive to it. |
| Empty-bin cases return 0.0 rather than undefined; the PAF is not checked for secondary rows or target-length consistency in the bin scorer (unlike the base scorer). | Inconsistent conventions between two scorers. | A malformed PAF could be scored silently. | Share one PAF reader between the scorers. |

### 5.3 Ranking and statistics

- **Headline.** Tools are ranked within (track, task); only reference Tiers 1 and 2 enter; species with at least 20 independent clusters are averaged, others fall back (E28); failure is zero on plasmid-bearing isolates; the ranking set is the intersection of samples across all tools in the group (E29).
- **Clusters.** BioProject (else study), then merged by clonal group with a union-find (E26). Intervals are percentile cluster bootstraps with 1,000 draws and a fixed seed (E24); p-values are Monte Carlo sign-flip tests on whole clusters (E21); Holm is applied across all pairs in a (track, task) group (E22). A minimum of five clusters is required for an interval or a test (E20, E21).

| Finding | Reason | Consequence | Recommendation |
|---|---|---|---|
| With five clusters a sign-flip test has 32 patterns; the smallest two-sided p is **about 0.0625**, so p < 0.05 is **unreachable** below six clusters (E21). | The minimum was chosen for interval availability, not for test power. | A "tied or not significant" verdict at five clusters is not informative. | Require at least six clusters for a test and say what the floor is when fewer are present. |
| **Two different intervals** sit in one table: the legacy F1 columns use BioProject-only clusters and no species balance; the headline columns use merged clusters and species balance (E25, E26). | The legacy columns were kept for continuity. | A reader can quote the narrower interval. | Show one interval per metric, or label which is which in the table header. |
| The bootstrap and permutation "tests" re-implement the same algorithm with the same seed and compare (E38). | Easy to test; checks consistency only. | No test would catch a flaw in the algorithm itself. | A simulation of coverage and false-positive rate under clustered sampling, using the real headline metric. |
| `rank_sensitivity.py` ranks all tools in a track by base F1 on the all-tool shared samples (E30): it ignores the task split, species balance, the tier filter and the headline metric. | Written for the earlier base-F1 ranking. | Its stability statement is about a different ranking than the headline. | Re-run it on the headline metric with the same design object. |
| `power_analysis.py` uses a normal approximation, BioProject-only clusters and raw F1 (E31). | Added as a planning aid. | It models neither the headline nor the permutation test, so its minimum detectable difference is indicative only. | Align it with the headline design, or label it indicative wherever it appears. |
| Significance is checked only for the top tool against the runner-up, and Holm counts baselines. | Simplification. | Lower-ranked differences have no verdict. | State this in the leaderboard footer. |
| A documented "about 15% non-parametric inflation" in the cohort-size formula is **not implemented**. | Documentation ahead of code. | Cohort-size guidance is optimistic. | Implement or remove the statement. |

### 5.4 Leakage

On `main`, leakage is a **release-date screen**: a truth assembly released on or before a tool's database date is `possible_overlap`, otherwise `after_database` (E35). Exclusion is off by default (E35). Eight of 19 database rows have dates; nine tools have no installed database (E41). Recovery inside versus outside each tool's own database is reported by the sequence-level check merged in PR #12 for databases on disk.

| Finding | Reason | Consequence | Recommendation |
|---|---|---|---|
| A date cannot show that a plasmid is novel to a database: an `after_database` truth can be near-identical to an older record (same study, same clone). | Plasmids are highly redundant. | "F1 on samples the database cannot contain" (METHODS) overclaims. | Reword; use the sequence-level result as the novelty stratum (decision D2) and report it beside the headline. |
| Nine tools have no database installed here, so their dates and containment are blank. | Tools not installed or database not pinned. | Their leakage is `unknown`, not controlled. | Fill them as the tools are installed; show `unknown` prominently. |
| Evidence-based truth filtering and tool databases share sources (5.1). | Same markers. | Circular for a subset of tools. | Show the label-scheme sensitivity. |

### 5.5 The nearest-reference Mash screen

Off by default and marked **experimental and unvalidated** in its own docstring (E36). The reference set has 16 plasmids from five species, none from *Enterococcus*, while `public-v3` has 10 *E. faecium* isolates. The 0.05 distance threshold corresponds to about 35% shared k-mers for equal-size sequences, not 95% identity (E36). It should not be presented as a novelty test; its calls are `close_reference_match`, `no_close_reference` and `insufficient_reference`. **Recommendation:** validate on stress sets (fragmented and mosaic plasmids at known fractions) before any use, extend the reference set, or retire the screen from the operational output.

### 5.6 The operational recommender

Evidence-gated (at least 5 scored samples, at least 0.80 coverage, leave-one-study-out validation) and the learned model is off by default and ready only with enough studies and training rows. Its own report states that the ridge penalty is chosen on the same folds used to report error and so is optimistic (E37). With the current cohort most strata are empty and the recommendation is withheld, which is the right behaviour. **Recommendation:** nested cross-validation before the model is ever enabled; keep the gating text prominent.

---

## Part 6. Workflow and architecture assessment

**Strengths.** Numbered, idempotent stages with reuse; per-run manifests and image digests; cohort lock files with checksums; one adapter contract per tool; a per-run failure table that separates resource failures from tool failures; a scorer that depends only on the standard library; a locked, digest-pinned container.

**Weaknesses and recommendations.**

| Finding | Consequence | Recommendation |
|---|---|---|
| **No real plasmid tool is exercised by any test or CI job.** Adapters are tested on hand-written fixtures; only the aligner runs for real (E39). | An upstream tool change can break an adapter unnoticed. | One CI job that runs a single real tool (for example `mob_recon`) on a tiny dataset and checks the adapter output. |
| The install pipeline was inconsistent: samtools and mash were in the environment file and lock but in no profile and no default check; barrnap was in the environment file but not the lock; abricate, AMRFinderPlus, ISEScan and mob_typer, used by the default annotation stage, were in no route (E43, E44; fixed in PR #15). | An environment built by a profile lacked tools the default stage uses; an absent tool silently left feature classes `not_evaluated`. | Fixed in PR #15, with a drift test (`test/test_install_wiring.py`); the barrnap lock entry needs the lock regenerated with conda. |
| Linux only (Windows needs WSL2); bash orchestration. | Adoption barrier for the intended laboratories. | A container or notebook route documented as the default for non-Linux users. |
| Databases and several tools are not pinned; the container fetches databases at first use. | Results are not reproducible across database updates. | Record database versions and checksums in the manifest (partly done), pin tool versions in a lock for every profile. |
| A hard-coded dependence on `contigs.fasta` and per-tool contig identifiers for contig-level scoring. | A tool that renames contigs is marked not applicable, correctly, but silently from the user's view. | Show the not-applicable reason in the report. |

**Order of stages.** Defensible. One missing step: a truth-quality gate between stages 2 and 5 that fails loudly (rather than falls back) when no reference reaches Tier 2.

---

## Part 7. Edge-case and failure-mode assessment

Columns: expected scientific result, what could go wrong, whether PlasBench handles it, and the basis (D documented, T tested, U untested).

| # | Scenario | Expected | Risk | Handled | Basis |
|---|---|---|---|---|---|
| 1 | Several plasmids in one isolate | Per-base, per-plasmid and per-bin scores | Bins split or merged | Yes | T |
| 2 | Highly similar co-resident plasmids | Ambiguity reported, recall ceiling | Shared regions fall below MAPQ 20 and cap recall | Partly | D, T |
| 3 | Very large plasmids | Per-plasmid recovery shown | Dominate pooled F1 | Partly | D |
| 4 | Small cryptic plasmids | Reported by size band | Missed by tools; low weight in F1 | Partly | T |
| 5 | Highly divergent plasmids | Unmapped, not FP | Optimism (5.2) | Yes | D, T |
| 6 | Plasmid absent from tool databases | Sequence-level stratum | Date screen only for tools without a database on disk | Partly | T |
| 7 | Incomplete assemblies | Recovery bands, missing regions | Base F1 does not penalise splitting | Yes | T |
| 8 | Fragmented plasmid | Split events, bin quality | Hidden by base F1 | Yes | T |
| 9 | Circular and linear plasmids | Circular recall against curated truth | Closure never inferred | Yes | D |
| 10 | Insertion-sequence-rich plasmids | Recall ceiling and ambiguity diagnostics | MAPQ filtering hides contamination | Partly | D |
| 11 | Plasmid-chromosome integration, chromids | `AMBIGUOUS`, set aside | A chromid with a marker passes as plasmid | Partly | D, U |
| 12 | Chromosome called plasmid | Counted as FP | Repeats escape via MAPQ | Partly | T |
| 13 | Contaminated reads | Unmapped output reported | Not scored as FP | Yes | D |
| 14 | Low-depth data | Depth ladder | Long-read ladder absent | Partly | D |
| 15 | Hybrid assemblies | Separate track | Truth built from the same reads | Partly | D |
| 16 | Plasmids from different species | Species-balanced where data allow | Most species below the 20-cluster minimum | Partly | D |
| 17 | Different geographic origin | Origin metadata | 66 of 98 origins blank | No | D |
| 18 | Plasmids sampled at different times | Release-date screen | No temporal hold-out | No | D |
| 19 | Database duplication, inconsistent annotation | Evidence labels | Same markers as tools | Partly | D |
| 20 | Truth multimer | Detected | Not detected | No | U |
| 21 | Truth with a missed small plasmid | Penalises a correct tool | Cannot be fixed in software | No | D |
| 22 | No sample reaches Tier 2 | Fail loudly | Silent fallback to all samples | No | D |
| 23 | Same-read-polished truth, accuracy metrics | Not assessable | Handled (masked) | Yes | T |
| 24 | A tool predicts nothing on a plasmid-bearing isolate | F1 = 0 | Handled | Yes | T |
| 25 | A tool crashes or is killed by memory | Zero and counted as a resource failure | Handled | Yes | T |
| 26 | Five clusters | No test | Floor of about 0.0625 (5.3) | Partly | D |
| 27 | Plasmid-free isolates | Specificity | None in the shipped cohorts | No | U |
| 28 | A tool renames contigs | Contig-level not applicable | Reason not shown to the user | Partly | T |

---

## Part 8. Validation and benchmarking assessment

**Analytical validation of the benchmark itself.** Hand-computed expectations exist for the scorer, the real aligner path, control predictions (oracle, empty, whole genome, chromosome-only, half, plasmid-free), binning (a worked length-weighted example and CPRR counts), the new dimensions and the stage scripts. What is missing is the check that the **statistics behave as claimed**: simulate samples with known true tool differences under clustered sampling and report the coverage of the interval and the false-positive rate of the permutation test, using the real headline metric.

**Real-data performance: none.** `results_demo/` is fabricated by design and `results_audit/` is synthetic. Every statement about ranking, stability and generalisation is unsupported until a run exists.

**Metrics suited to each task.** Precision, recall, F1 and MCC for classification; length-weighted binning F1, CPRR, ARI and the count-based bin metrics for reconstruction; NMI and variation of information descriptive only; identity and indel rates only on independent truth; runtime and memory per tool. These are what the tool reports.

**Datasets and controls.** The shipped cohorts are public hybrid and long-read assemblies. Missing controls: plasmid-free isolates (none shipped), hard-structure isolates, and independent laboratory confirmation. Negative and positive controls exist as synthetic tests only.

**Leakage and bias.** See 5.4. Selection bias: only isolates with finished long-read or hybrid assemblies and matched public reads can be truth, which favours less repeat-rich genomes.

**External validation.** None. Needed: different platforms, species and geographies, AMR-positive and AMR-negative isolates, and independent confirmation of at least some truth replicons. Computational concordance is not biological validity, and the documents say so.

**Fair comparison against established tools.** The tools in the registry are the subjects; a trivial baseline (a depth rule and a reference match) is scored like a tool so every tool can be asked whether it beats a rule. A first-class PlasEval comparison is open.

---

## Part 9. Results and interpretation assessment

**Do the outputs answer the question?** The leaderboard, per-plasmid recovery, bin diagnostics and robustness tables answer "which tool recovers more of a known reference". They do not answer "is this candidate a real, closed plasmid?", and the documents say so.

**Strengths.** Plain-language metric explanations; explicit empty states; separate tracks that are never pooled; a `not_evaluated` state distinct from zero; sections that state what they do and do not show.

**Concerns.**
- Two intervals for the same metric (5.3).
- Too many metrics may obscure the one decision; the README itself warns that `mean_f1` and plasmid recall are different numbers.
- No per-plasmid explanation of *why* a plasmid was missed (alignment blocks exist per sample but not as a ranked list of failure causes).
- Confidence is not calibrated for tools without probabilities, and calibration is reported only for those that expose them.

**Recommended outputs.** One interval per metric; a header line stating the reference tiers used, the number of independent clusters and whether a fallback occurred; the independent-truth sensitivity result and the database-membership result beside the headline (decisions D1 and D2).

---

## Part 10. Practical usefulness and use cases

| Audience | Value | Limit |
|---|---|---|
| Tool developers | A reproducible, controlled way to compare against others | Needs the real-data run |
| Laboratories choosing a tool | Evidence-gated recommendation with an interval | Withheld for most strata today |
| AMR researchers | AMR gene recall against curated truth, recovery by resistance-gene carriage | Curated AMR truth is scarce |
| Epidemiologists, public health | None directly: no epidemiological output | By design |
| Non-computational researchers | A report with plain-language explanations | Linux or WSL install |
| Programme implementers | Locked container, one command | Databases and some tools unpinned |
| Funders | Open, reproducible benchmark framework | Not yet demonstrated |

**Strongest use case:** auditing a published ranking and choosing a reconstruction tool for a stated taxon. **Weakest:** anything surveillance-related; the benchmark does not produce surveillance data.

---

## Part 11. Risk assessment

| Risk | Type | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Rankings reflect shared errors between truth and tools (same-read polishing, shared databases) | Scientific | Medium | High | D1 sensitivity; label-scheme comparison |
| Intervals or tests are miscalibrated | Statistical | Medium | High | Simulation (Recommendation C4) |
| Thresholds drive the ranking | Methodological | Medium | High | Grid and sensitivity (C6) |
| An adapter silently breaks | Operational | Medium | Medium | Real-tool CI job (H5) |
| Environment drift makes a run irreproducible | Operational | Medium | Medium | Pin tools and databases (H7) |
| A reader quotes the narrower interval or a fallback headline | Interpretation | Medium | Medium | One interval; visible fallback warning |
| A single maintainer and a very large surface | Sustainability | High | Medium | Freeze features; split the README |

---

## Part 12. Recommendations

**Critical (before any scientific claim can be trusted).**
- **C1.** Run `public-v3` for every default tool and archive the scores, manifest, robustness and leakage tables. Nothing here is demonstrated without it.
- **C2.** Add the independent-truth sensitivity beside the headline (decision D1). Today only 2 of 98 isolates qualify; growing that subset is part of the work.
- **C3.** Report recovery inside versus outside each tool's database beside the headline (decision D2) and extend containment to the tools whose databases are not yet installed.
- **C4.** Validate the intervals and the permutation test by simulation under clustered sampling with the real headline metric; require at least six clusters for a test.
- **C5.** Show one interval per metric.
- **C6.** Run a grid over every scoring threshold and report rank stability; document the reason for each default.

**High priority (research-grade maturity).**
- **H1.** Re-run the robustness analysis on the headline metric with the headline design.
- **H2.** Align the power analysis with the headline design or label it indicative.
- **H3.** Strengthen the truth audit: chromid and multimer checks; structured provenance where available.
- **H4.** Make the Tier fallback a visible warning.
- **H5.** One real-tool CI job.
- **H6.** Add plasmid-free and hard-structure isolates; fill blank metadata.
- **H7.** Pin tools and databases; add barrnap to the lock.
- **H8.** Reword "F1 on samples the database cannot contain".
- **H9.** Validate or retire the Mash screen.

**Medium priority.** A container route for non-Linux users; fix the Scientific Guide drift (release dates, cohort figures); nested cross-validation for the recommender; repeated-run reproducibility (`compare-runs`) on the real run; show not-applicable reasons for contig-level scoring.

**Future development.** A first-class PlasEval comparison and repeat-aware matching; NGA50 and abstention rate; scenario-specific cohorts.

---

## Part 13. Research and publication potential

**Credible paper type:** a resource or benchmark paper (for example in *Briefings in Bioinformatics* or *NAR Genomics and Bioinformatics*; confirm fit with each journal's scope).
**Central hypothesis (suggested):** on an independent reference panel, tool differences in plasmid recovery exceed what clustering of isolates and database leakage would produce.
**Missing for submission:** the real-data run; the statistical validation; the independent-truth and database-membership analyses; at least one external cohort; a comparison with PlasEval on shared data.
**What reviewers would challenge:** truth independence, the five-cluster floor, unjustified thresholds, leakage, species imbalance (36 of 98 are *E. coli*), the absence of plasmid-free isolates, and any claim beyond tool ranking.

---

## Part 14. Funding and implementation readiness

| Question | Answer |
|---|---|
| Would you fund it? | A pilot, conditional on the real-data run and the statistical validation. |
| What would make you reject it? | Claims beyond tool ranking; no real data by the end of the pilot; unaddressed truth independence. |
| Strongest competitive advantage | Explicit, tested handling of benchmark pitfalls and a reproducible one-command pipeline. |
| Greatest scientific weakness | No real-data demonstration and unvalidated statistics. |
| Missing evidence | Real results; coverage simulation; external validation. |
| First pilot | `public-v3`, the default tools, with archived outputs and all sensitivity analyses. |
| Minimum viable research-grade product | The short-read, default-tool benchmark on the independent-polish subset plus the Tier 2 headline. |
| Defer | Metagenomic and long-read tracks, the learned recommender, the Mash screen. |

**Readiness:** suitable for a pilot and external validation; not yet for broad adoption.

---

## Part 15. Expert examination questions

**Asked of the developer during this review, with the answers recorded:**
1. *Truth independence.* In `public-v3` none of 98 isolates is Tier 1 and 91 are polished with the benchmark's own reads. What is the primary analysis? **Answer:** keep the Tier 1 and 2 headline and add a mandatory independent-truth sensitivity (D1).
2. *Leakage.* Should recovery on plasmids absent from each tool's own database be a primary generalisation claim? **Answer:** yes, reported beside the headline (D2).
3. *Claims.* The tagline and parts of the concept note promised more than the code delivers. **Answer:** state what the tool does (D3, D4).

**Unresolved:**
4. Why five clusters as the minimum for a test, given the floor it implies? What number would you defend and why?
5. What justifies 200 bp, 0.90 identity and 0.20 query coverage, the 0.5/0.9/0.99995 bands, and the CPRR 0.95/0.95/0.99? Has the ranking been shown stable to each?
6. How do you know the intervals have their stated coverage under clustered sampling with the real headline metric?
7. How will you distinguish a tool that benefits from sharing markers with the truth labelling from one that is genuinely better?
8. Which isolates in `public-v3` have truth that could contain chromids or multimers, and how would you know?
9. What would convince an independent scientist that the benchmark changes a ranking a naive F1 benchmark would report, and that the change is correct?
10. What is the plan for the nine tools whose databases are not installed?
11. How will the Mash screen be validated, or will it be retired?
12. Who maintains this, and what is frozen until the real-data run exists?

---

## Part 16. Final verdict

**Promising but requires methodological refinement.**

The framework is carefully designed, candid about its limits and well tested for arithmetic and control flow. It is not yet a research-grade result: nothing has been shown on real data, the statistics have not been validated, several scoring choices are unjustified, the truth is only partly independent of the benchmark's own reads, and leakage is controlled by date rather than sequence for most tools on `main`. None of this is hidden by the documents, which is a strength. The distance to a credible resource paper is mostly *evidence and validation work*, not new code, and Part 12 orders it.

---

## Scorecard (0 to 10; N/A where not yet assessable)

| Domain | Score | Evidence | Weaknesses | Missing evidence | What would improve it |
|---|---|---|---|---|---|
| Problem significance | 7 | Teixeira et al. 2025: less than half of plasmids perfectly reconstructed | Population served is narrow | Statement of covered and uncovered populations | State the population; broaden the cohort |
| Scientific rationale | 7 | Reference-based scoring with controls (E1 to E3, E15 to E17) | Primary claim not stated | A pre-registered primary claim | Adopt the suggested primary claim |
| Conceptual novelty | 3 | Standard benchmarking idea | Little new concept | A demonstration that the controls change a ranking | Naive-versus-controlled comparison on real data |
| Methodological novelty | 4 | Combination of failure-as-zero, tiers, cluster-aware resampling, masking | Each element is known; PlasEval exists | Direct comparison with PlasEval | Run PlasEval on the same data |
| Biological validity | 4 | Evidence labels, tiers (E32, E33) | 0 Tier 1; 91 same-read truth; shared markers | Independent truth audit | D1 sensitivity; chromid and multimer checks |
| Computational validity | 6 | Hand-computed scoring and binning tests; real-aligner golden test | Statistics unvalidated; thresholds unjustified | Coverage simulation; threshold grid | C4, C6 |
| Similarity assessment (prediction vs truth) | 6 | Local alignment, identity and coverage reported separately | Accuracy assessable for 2 of 98 isolates | Independent-polish isolates | Grow that subset |
| Edge-case robustness | 5 | Adversarial scoring tests; documented behaviours (Part 7) | Many scenarios untested on real data; silent fallback | Hard-structure isolates | H3, H4, H6 |
| Validation and benchmarking | 3 | Unit and stage tests | No real data, no external validation, no plasmid-free isolates | Real run; external cohort | C1 |
| Interpretability | 6 | Report with caveats and empty states | Two intervals; many metrics | Per-plasmid failure causes | C5; one header line |
| Computational efficiency | N/A | Measured by `performance_summary.py`, but no real run | No data | A real run | C1 |
| Practical usefulness | 5 | Reproducible pipeline; evidence-gated recommendation | Withheld for most strata | Real results | C1, H6 |
| Public health relevance | 3 | No epidemiological output by design | Not a surveillance tool | None needed | Keep claims within scope |
| Reproducibility | 5 | Lock file, manifest, seeds, checksums | Unpinned databases and tools; install inconsistency; no repeated-run evidence | Repeated-run comparison | H7; run `compare-runs` twice |
| Scalability | N/A | Parallel samples; no measurements | Unmeasured | Scaling data | Real run |
| Implementation readiness | 5 | One-command pipeline; container | Linux only; no real-tool CI | A real-tool test | H5; container route |
| Funding readiness | 4 | Clear gap, open design | No real data; unvalidated statistics | Pilot results | C1, C4 |

---

## Appendix A. Evidence ledger

Each row names the claim, the file and line (`path:line`), and a short string that must appear on that line. `test/test_independent_review_ledger.py` re-checks every row so a moved line fails loudly.

| ID | Claim | Evidence | Symbol |
|---|---|---|---|
| E1 | TP is reference plasmid bases covered by the prediction | `python/score_plasmids.py:344` | `tp = 0` |
| E2 | FN is plasmid bases minus TP | `python/score_plasmids.py:354` | `fn = total_plasmid - tp` |
| E3 | Unmapped predicted bases are counted separately and are not FP | `python/score_plasmids.py:252` | `unmapped_pred_bp += max` |
| E4 | Scorer CLI default minimum alignment length is 1 | `python/score_plasmids.py:633` | `--min-alignment-length` |
| E5 | Scorer CLI default minimum identity is 0 | `python/score_plasmids.py:635` | `--min-alignment-identity` |
| E6 | Scorer CLI default minimum MAPQ is 0 | `python/score_plasmids.py:637` | `--min-alignment-mapq` |
| E7 | Scorer CLI default query coverage is 0 | `python/score_plasmids.py:639` | `--min-alignment-query-coverage` |
| E8 | Pipeline default minimum alignment length is 200 | `config/config.sh:497` | `MIN_ALIGNMENT_LENGTH` |
| E9 | Pipeline default identity is 0.90 | `config/config.sh:498` | `MIN_ALIGNMENT_IDENTITY` |
| E10 | Pipeline default MAPQ is 20 | `config/config.sh:499` | `MIN_ALIGNMENT_MAPQ` |
| E11 | Pipeline default query coverage is 0.20 | `config/config.sh:500` | `MIN_ALIGNMENT_QUERY_COVERAGE` |
| E12 | A fixed 0.99995 completeness band | `python/score_plasmids.py:779` | `0.99995` |
| E13 | Bin purity gate default 0.9 | `python/score_bins.py:405` | `--min-bin-purity` |
| E14 | Split threshold default 0.1 | `python/score_bins.py:406` | `--split-threshold` |
| E15 | Length-weighted binning precision uses bases that aligned | `python/score_bins.py:360` | `def length_weighted_binning` |
| E16 | Ungated one-to-one Hungarian match | `python/score_bins.py:315` | `def maximum_weight` |
| E17 | CPRR is computed after the match | `python/score_bins.py:372` | `def correct_reconstruction` |
| E18 | CPRR minimum coverage 0.95 | `config/config.sh:50` | `CPRR_MIN_COVERAGE` |
| E19 | CPRR minimum identity 0.99 | `config/config.sh:52` | `CPRR_MIN_IDENTITY` |
| E20 | Interval requires at least five clusters | `python/aggregate_results.py:658` | `len(values) < 5 or len(units) < 5` |
| E21 | Permutation test requires at least five clusters | `python/aggregate_results.py:674` | `len(differences) < 5 or len(units) < 5` |
| E22 | Holm adjustment across pairs | `python/aggregate_results.py:689` | `def holm_adjust` |
| E23 | Significance attached to top versus runner-up | `python/aggregate_results.py:822` | `def attach_significance` |
| E24 | Percentile cluster bootstrap | `python/aggregate_results.py:649` | `def bootstrap_ci` |
| E25 | Legacy clusters are BioProject or study only | `python/aggregate_results.py:76` | `def sample_clusters` |
| E26 | Headline clusters merge clonal groups with union-find | `python/headline_design.py:82` | `def find` |
| E27 | Headline falls back to all samples when no sample reaches the tiers | `python/headline_design.py:132` | `FALLBACK: no sample in reference tiers` |
| E28 | Species need 20 clusters to enter the species-balanced mean | `python/headline_design.py:60` | `min_species_clusters=20` |
| E29 | Ranking set is shared across all tools in the group | `python/headline_design.py:247` | `def shared_values` |
| E30 | Robustness variants are built from base F1 | `python/rank_sensitivity.py:196` | `def build_variants` |
| E31 | Power analysis uses a normal approximation | `python/power_analysis.py:69` | `NormalDist().inv_cdf` |
| E32 | Plasmid replicons under the long-read depth floor become ambiguous (default 5x) | `python/label_truth_evidence.py:153` | `--min-long-read-depth` |
| E33 | Tier is decided from strategy, polish and cohort tier | `python/truth_provenance.py:200` | `reference_tier, tier_reason = tier(` |
| E34 | Circularity guard for long-read tools | `scripts/lib.sh:244` | `truth_independent_of_long_reads` |
| E35 | Date-based overlap screen | `python/flag_database_overlap.py:92` | `possible_overlap` |
| E36 | Mash screen is marked experimental and unvalidated | `python/classify_operational_plasmid.py:4` | `EXPERIMENTAL AND UNVALIDATED` |
| E37 | The recommender's ridge penalty is chosen on the folds it reports | `python/fit_recommendation_model.py:196` | `lambda was selected on the same LOSO folds` |
| E38 | The bootstrap test re-implements the algorithm | `test/test_robustness_diagnostics.py:48` | `def reference_bootstrap` |
| E39 | CI installs minimap2 so the aligner test runs for real | `.github/workflows/ci.yml:28` | `apt-get install -y -qq minimap2` |
| E40 | Base-level metrics valid only without same-read polishing | `python/truth_provenance.py:205` | `base_level_metrics_valid` |
| E41 | Tool database dates (first row) | `config/tool_database_releases.tsv:2` | `mob_recon` |
| E42 | Exclusion of possible overlaps is off by default | `config/config.sh:505` | `EXCLUDE_DATABASE_OVERLAP` |
| E43 | barrnap is in the environment file | `env/environment.yml:23` | `barrnap` |
| E44 | minimap2 is a hard requirement of scoring | `scripts/05_score.sh:21` | `need minimap2` |
| E52 | Unresolvable truth sequences are labelled REVIEW | `python/make_truth.py:50` | `REVIEW = "REVIEW"` |
| E53 | A legacy option restores the chromosome guess | `python/make_truth.py:18` | `--allow-default` |
| E54 | Conflicting evidence is labelled AMBIGUOUS and excluded | `python/label_truth_evidence.py:125` | `AMBIGUOUS` |
| E55 | Samples polished with the benchmark's reads | `python/truth_provenance.py:114` | `same_as_benchmark` |
| E56 | Cohort counts and tiers | `cohorts/public-v3.tsv:6` | `sample_id` |

**Reproduce E56's numbers:** `python3 python/truth_provenance.py --sample-sheet cohorts/public-v3.tsv --data-dir <empty dir> --out prov.tsv` reports `tier 2=79, tier 3=19`; the species, BioProject and metadata counts in Part 2 and Part 5.1 come from reading `cohorts/public-v3.tsv` with comment lines removed (98 isolates, 81 BioProjects; 330 of 392 cells blank across `sample_origin`, `read_depth_x`, `assembly_plasmid_count` and `source_study`).
