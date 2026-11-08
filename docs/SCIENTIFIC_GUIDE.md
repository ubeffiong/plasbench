# PlasBench Scientific Guide

**What PlasBench does, how it does it, why, and how to check it.**
This guide is for the people who must decide whether to trust and use the tool: microbiologists, bioinformaticians, AMR and public-health scientists, laboratory leads, programme implementers and reviewers. It describes PlasBench at version 0.1.5. It does not require you to read the source code, and it tells you where the code is when you want to.

<!-- TOC -->
- [1. What PlasBench is, and what it is not](#1-what-plasbench-is-and-what-it-is-not)
  - [1.1 The question PlasBench answers](#11-the-question-plasbench-answers)
  - [1.2 Why this is worth doing](#12-why-this-is-worth-doing)
  - [1.3 What it is not](#13-what-it-is-not)
  - [1.4 What you can decide with it](#14-what-you-can-decide-with-it)
  - [1.5 Who should use it, and when not to](#15-who-should-use-it-and-when-not-to)
- [2. Concepts and vocabulary](#2-concepts-and-vocabulary)
- [3. How it works in one page](#3-how-it-works-in-one-page)
- [4. Inputs](#4-inputs)
  - [4.1 What a sample needs](#41-what-a-sample-needs)
  - [4.2 Where truth comes from](#42-where-truth-comes-from)
  - [4.3 How a sequence gets its label](#43-how-a-sequence-gets-its-label)
  - [4.4 Reference tiers](#44-reference-tiers)
  - [4.5 Evidence labels, and what is set aside](#45-evidence-labels-and-what-is-set-aside)
  - [4.6 Independence of observations](#46-independence-of-observations)
  - [4.7 The shipped cohorts](#47-the-shipped-cohorts)
- [5. The pipeline, stage by stage](#5-the-pipeline-stage-by-stage)
- [6. The tools evaluated](#6-the-tools-evaluated)
- [7. Scoring: what is measured, how, and why](#7-scoring-what-is-measured-how-and-why)
  - [7.1 Projection onto the reference](#71-projection-onto-the-reference)
  - [7.2 The confusion matrix (positive class = plasmid)](#72-the-confusion-matrix-positive-class--plasmid)
  - [7.3 What the base-level metric hides, and the diagnostics that expose it](#73-what-the-base-level-metric-hides-and-the-diagnostics-that-expose-it)
  - [7.4 Plasmid-level recovery](#74-plasmid-level-recovery)
  - [7.5 Bin-level metrics (binning-capable tools only)](#75-bin-level-metrics-binning-capable-tools-only)
  - [7.6 Threshold-free ranking quality](#76-threshold-free-ranking-quality)
  - [7.7 Structural evidence](#77-structural-evidence)
- [8. Ranking and statistics](#8-ranking-and-statistics)
  - [8.1 Tracks and tasks](#81-tracks-and-tasks)
  - [8.2 The headline](#82-the-headline)
  - [8.3 Failures](#83-failures)
  - [8.4 Uncertainty](#84-uncertainty)
  - [8.5 How fragile is the ranking?](#85-how-fragile-is-the-ranking)
- [9. Truth quality and leakage controls](#9-truth-quality-and-leakage-controls)
- [10. Long-read and hybrid tracks](#10-long-read-and-hybrid-tracks)
- [11. The metagenomic track](#11-the-metagenomic-track)
- [12. Operational mode: using the evidence](#12-operational-mode-using-the-evidence)
- [13. Outputs and how to read them](#13-outputs-and-how-to-read-them)
  - [13.1 The files](#131-the-files)
  - [13.2 The scores.tsv columns](#132-the-scorestsv-columns)
  - [13.3 The HTML report](#133-the-html-report)
  - [13.4 How to read a leaderboard](#134-how-to-read-a-leaderboard)
  - [13.5 What you can and cannot conclude](#135-what-you-can-and-cannot-conclude)
- [14. Reproducibility and provenance](#14-reproducibility-and-provenance)
- [15. Configuration reference](#15-configuration-reference)
- [16. A guide for domain experts: how to check it yourself](#16-a-guide-for-domain-experts-how-to-check-it-yourself)
  - [16.1 For a microbiologist or AMR scientist: is the biology right?](#161-for-a-microbiologist-or-amr-scientist-is-the-biology-right)
  - [16.2 For a bioinformatician: is the computation right?](#162-for-a-bioinformatician-is-the-computation-right)
  - [16.3 For a public-health or programme lead: is it usable and safe to rely on?](#163-for-a-public-health-or-programme-lead-is-it-usable-and-safe-to-rely-on)
  - [16.4 For a reviewer or funder: what would count as evidence?](#164-for-a-reviewer-or-funder-what-would-count-as-evidence)
- [17. Validation status and known limitations](#17-validation-status-and-known-limitations)
  - [17.1 What has been established](#171-what-has-been-established)
  - [17.2 What has not been shown yet](#172-what-has-not-been-shown-yet)
  - [17.3 What would establish the claims](#173-what-would-establish-the-claims)
  - [17.4 Methodological limits](#174-methodological-limits)
  - [17.5 Behaviour in difficult cases](#175-behaviour-in-difficult-cases)
- [18. Scope matrix](#18-scope-matrix)
- [19. Further documentation](#19-further-documentation)
<!-- /TOC -->

---

## 1. What PlasBench is, and what it is not

### 1.1 The question PlasBench answers

> *For short-read bacterial isolate data of a given kind, which plasmid-reconstruction method recovers the true plasmids most accurately, how sure can we be, and where does each method fail?*

PlasBench is a **benchmarking framework**. It takes bacterial isolates for which a complete, long-read or hybrid reference genome exists, runs plasmid-reconstruction and plasmid-classification tools on the isolate's short reads, and scores each tool's output against the complete reference. It reports the result as a ranked, uncertainty-aware leaderboard, with the diagnostics needed to interpret it.

### 1.2 Why this is worth doing

Plasmids carry much of the antimicrobial-resistance (AMR) burden, but they are hard to reconstruct from short reads: they contain repeats, vary in copy number, and share sequence with chromosomes and with each other. Different tools therefore give different answers for the same isolate. Published comparisons use different datasets and different definitions of success, so they cannot be combined. PlasBench exists so that:

- every tool is judged **by the same ground truth and the same metrics**;
- the evidence behind a ranking (samples, species, studies, reference quality, database overlap) is **visible and reproducible**;
- a laboratory can run the **same comparison on its own isolates** before choosing a pipeline for its own work.

### 1.3 What it is not

| PlasBench is not | What to use instead, or what is true |
|---|---|
| A plasmid **identification** tool for your sample | Run a reconstruction tool (PlasBench can recommend one). PlasBench scores tools; it is not itself a caller. |
| A plasmid **clustering, taxonomy, community or relatedness** tool | Not implemented. See [section 18](#18-scope-matrix). |
| A **PLSDB search** or reference-comparison tool | Not implemented. PLSDB appears only as the source of some tools' own databases. |
| A **surveillance, outbreak or transmission** system | It produces no epidemiological output. Genomic similarity, a shared resistance gene and a shared replicon are not evidence of transmission, and PlasBench makes no such claim. |
| A **diagnostic** or clinical-validation tool | It is research software. Its outputs are computational candidates and are never a substitute for laboratory confirmation. |
| A way to prove a plasmid is **closed, circular or biologically intact** | Base-level and plasmid-level recovery against a reference do not prove closure. Closure needs separate evidence. |

### 1.4 What you can decide with it

- Which tool to adopt for short-read plasmid reconstruction in a given taxon, with an interval around the answer.
- Whether a tool's apparent accuracy survives a change of scoring choice, a different reference standard, or removal of isolates it may have seen during training.
- How often, and how, each tool fails: contamination with chromosome, split or merged plasmids, missed small plasmids, incomplete AMR-gene recovery.
- Whether a result from your own isolates agrees with a published ranking.

### 1.5 Who should use it, and when not to

**Use PlasBench if** you need an evidence-based choice between plasmid tools, you want to audit a published ranking, you are building a surveillance pipeline and need to know which plasmid caller to trust, or you are developing a tool and need a fair test.

**Do not use PlasBench if** you want to *annotate or interpret the plasmids in your sample*, compare plasmids between isolates, or infer spread between patients. It does none of these.

---

## 2. Concepts and vocabulary

| Term | Meaning in PlasBench |
|---|---|
| **Truth / reference** | A complete assembly of the isolate (long-read or hybrid) in which every sequence is labelled PLASMID or CHROMOSOME. |
| **Prediction** | The FASTA of sequence a tool believes is plasmid, after PlasBench's adapter standardises it. |
| **Projection** | Mapping a prediction onto the truth with minimap2, so that every tool is scored on the same reference bases. |
| **Base-level scoring** | TP, FP and FN are counted per reference base. |
| **Binning / reconstruction** | Grouping contigs into per-plasmid bins. Tools that do this are scored on bins as well. |
| **Classification** | Calling each contig plasmid or chromosome without grouping. These tools are scored on base-level F1 only. |
| **Track** | The kind of input a tool consumes: `short_read`, `long_read` or `hybrid`. Tracks are never ranked against each other. |
| **Task** | `reconstruction` (binning-capable tools) or `classification`. Each task has its own headline metric. |
| **Reference tier** | How trustworthy a sample's truth is: tier 1 (validated), 2, or 3 (provisional). |
| **Cluster** | A set of isolates that are not independent (same BioProject or study, or the same clonal group). Statistics resample clusters, not isolates. |
| **Headline** | The pre-specified ranking: task metric, reference tiers 1 to 2, species-balanced where data allow. |
| **Failure-as-zero** | A tool that crashes or predicts nothing on a plasmid-bearing isolate scores 0 there, so it cannot gain by failing on hard isolates. |
| **Circularity** | Scoring a tool on truth that was built from the same reads the tool uses. PlasBench blocks this. |
| **Operational mode** | Running one tool on a sample that has no truth, chosen from benchmark evidence. |

---

## 3. How it works in one page

```
 matched data                        PlasBench                                    output
 ────────────                        ─────────                                    ──────
 complete reference  ──►  2 truth: label every sequence PLASMID / CHROMOSOME
 (long-read/hybrid)             │   (evidence-checked; ambiguous replicons set aside)
                                ▼
 paired short reads  ──►  1 download ► 3 trim (fastp) + assemble (SPAdes)
                                │
                                ▼
                          4 run each tool ► adapter ► predicted-plasmid FASTA (+ bins, + scores)
                                │
                                ▼
                          5 map prediction onto truth (minimap2, primary only, filtered)
                            score bases, plasmids, bins, AMR genes, structure
                                │
                                ▼
                          6 aggregate: per-track, per-task ranking with intervals,
                            robustness, leakage and reference-tier analyses ──►  leaderboard,
                                                                                 HTML report,
                                                                                 manifest
```

**Design principles, and the reason for each**

1. **One metric for every tool.** Classifiers and assemblers produce different outputs, so each prediction is projected onto the same reference and scored per base. This is the only way a contig classifier and a plasmid assembler can be compared fairly.
2. **The truth never comes from a tool under test.** Labels come from the deposited record or from assembly topology, never from a gene-content classifier, because a tool scored on labels it helped create would score trivially well.
3. **Failure counts.** Abstaining or crashing scores 0 on isolates that have plasmids, so a tool cannot rise by avoiding hard cases.
4. **Compare like with like.** Tracks and tasks are separate leaderboards. A tool is never penalised for a task it does not attempt.
5. **Uncertainty is part of the result.** Samples from one study are correlated, so intervals resample clusters, and no interval or p-value is reported when there are too few independent units.
6. **Undefined is not zero.** Where a metric has no meaning (recall on an isolate with no plasmid) it is left blank, never `0`.
7. **Every number is traceable.** Run manifests, lock files and checksums let a second group reproduce a result.
8. **Say what is not assessed.** Missing evidence is reported as missing (for example, database leakage that could not be checked), not silently dropped.

---

## 4. Inputs

### 4.1 What a sample needs

| Item | Detail |
|---|---|
| Paired short reads | Usually Illumina `*_1.fastq.gz` and `*_2.fastq.gz`. A single-end run counts as failed. |
| A complete reference | A long-read or hybrid assembly of **the same isolate**, with plasmids present. |
| Metadata | `sample_id`, `assembly_accession`, `sra_run`, `organism`, `truth_technology`, `truth_quality_tier`, `biosample`, `bioproject`. Optional: origin, read depth, plasmid count, source study, clonal group, provenance columns. |

You can use public NCBI data (PlasBench downloads and checks it) or your own files (`plasbench init-local`). Cohort rules are in [docs/COHORTS.md](COHORTS.md).

### 4.2 Where truth comes from

| `truth_source` | What it is | Independent of long reads? |
|---|---|---|
| `ncbi_deposited` (default) | The deposited Complete Genome assembly, labelled from NCBI's `assigned_molecule_location_type`. | Depends on the cohort row. |
| `self_assembled_hybrid` | PlasBench builds the truth with a Unicycler hybrid assembly when no assembly was deposited. Labels come from circularity and length only. Rejected if the chromosome is shorter than 1,500,000 bp or any contig is not circular. | **Never.** It cannot declare independence. |
| `simulated` | A real Complete Genome plus reads simulated from it (InSilicoSeq short, Badread long). | Yes, by construction. Reports mark these samples "simulated reads". |

### 4.3 How a sequence gets its label

`python/make_truth.py` reads the NCBI sequence report and labels each reference sequence. A sequence that cannot be labelled unambiguously is written as **`REVIEW`**, never guessed. That covers an id absent from the report, a location type other than Plasmid or Chromosome (for example Segment or Unlocalized), and a report that labels the same accession both plasmid and chromosome. `validate_truth_table.py` rejects `REVIEW`, so stage 2 stops until a person decides.

*Why:* a wrongly guessed CHROMOSOME label would charge every tool that correctly calls a real plasmid with false-positive bases and remove those bases from recall's denominator, biasing every score. `ALLOW_DEFAULTED_TRUTH=1` restores the old guess-chromosome behaviour for users who have reviewed the warnings.

### 4.4 Reference tiers

`python/truth_provenance.py` assigns each sample a tier from how its reference was built:

| Tier | Meaning | In the headline? |
|---|---|---|
| **1 validated** | Long-read-only or long-read-first truth; polishing reads `none` or independent of the benchmark; cohort quality tier A; replicon labels evidence-checked. | Yes |
| **2** | Long-read-first truth that fails a tier-1 condition (for example polished with the benchmark's own reads, cohort tier B, or labels not evidence-checked). | Yes |
| **3 provisional** | Short-read-first hybrid, unknown strategy, or cohort tier C. | No. Reported as a sensitivity analysis. |

Tier values come, in priority order, from sample-sheet columns (`truth_assembly_strategy`, `truth_polish_reads`), from `truth_source`, and from NCBI's assembly method and sequencing technology by pattern matching. Derived values are heuristics and say so in `provenance_source`. A long-read-first assembly with Illumina recorded is *assumed* to have been polished with the benchmark's own run.

`base_level_metrics_valid` is `yes` only when polish is `none` or `independent`. It controls whether the CPRR identity criterion applies (section 7.5).

### 4.5 Evidence labels, and what is set aside

When reference annotation has run (default on), `python/label_truth_evidence.py` checks each truth replicon against replicon type, MOB relaxase, a Mash match to a plasmid reference sketch, rRNA genes, and long-read depth. It labels each replicon `PLASMID`, `CHROMOSOME` or `AMBIGUOUS`:

- **AMBIGUOUS** covers a plasmid carrying rRNA genes, a chromosome-labelled secondary replicon without rRNA or with plasmid markers (chromid-like), a marker-free plasmid, or a plasmid with long-read depth under the threshold.
- Ambiguous replicons are **removed from `truth.scored.tsv`**, so predictions on them are neither credited nor penalised (they appear as `off_truth_pred_bp`). `truth.tsv` is never modified.
- If the annotation callers did not run, source labels are kept and the row says `not_evaluated`. This is never read as "consistent".

*Known limit:* the markers come from databases similar to those several tools use, so marker-free plasmids are under-represented in scored truth.

### 4.6 Independence of observations

Isolates from one study or one clone are not independent. A **cluster** joins isolates that share a BioProject (or study) **or** a clonal group. Clonal groups come from a declared `clonal_group` column, else from single-linkage Mash clustering of the reference genomes at distance 0.0005 (about 99.95% identity), else each isolate stands alone. All bootstrap and permutation procedures resample whole clusters.

### 4.7 The shipped cohorts

| Cohort | Size | Composition | Status |
|---|---|---|---|
| `public-v1` | 10 isolates | 9 *E. coli* (clinical urine, one study) and 1 *Salmonella* Tennessee, all tier A, all hybrid truth | Frozen smoke-test panel. |
| `public-v2` | 32 isolates | 17 *E. coli*, 6 *Salmonella*, 5 *Klebsiella*, 3 *Acinetobacter*, 1 *S. aureus*; 10 tier A and 22 tier B; 22 isolates with African origin metadata (Egypt 9, South Africa 4, Nigeria 4, Tanzania 3, Kenya 2) | Working panel. The added rows lack read depth and plasmid counts, and geography is deposited metadata, not curator-verified. |

Neither public panel declares truth independence, so the long-read and hybrid tools are skipped on them unless explicitly overridden (section 10). Discovery of candidate cohorts is covered in [docs/COHORTS.md](COHORTS.md). `plasbench discover-cohort` rejects any assembly that is not a Complete Genome, does not declare plasmid replicons, lacks explicit long-read evidence, or has no linked paired-Illumina run from the same BioSample and BioProject, so many public genomes do not qualify.

---

## 5. The pipeline, stage by stage

`plasbench run` runs stages 0 1 2 3 4 7 5 6 (stage 7 precedes scoring so its predictions are scored in the same pass). Finished work is reused, so an interrupted run resumes.

| Stage | Script | What it does | How | Why |
|---|---|---|---|---|
| 0 | `00_setup.sh` (`plasbench check`) | Checks the software and databases that the enabled tools need; offers to install what is missing. | Looks for core binaries and, for each enabled `RUN_*` flag, its databases. | Fail early, before hours of computation. |
| 1 | `01_download.sh` | Downloads the reference and the reads. | `datasets download genome ... --include genome,seq-report,gff3`; `prefetch` then `fasterq-dump --split-files`, compressed. Shows a size estimate and asks first on a terminal. | Provenance and reproducibility; the user sees what will be fetched. `LOCAL_INPUTS_ONLY=1` never contacts NCBI. |
| 2 | `02_truth.sh` | Builds and validates truth, computes reference statistics, annotates, assigns evidence labels. | `make_truth.py`, `validate_truth_table.py` (hard gate), `annotate_reference.py`, `label_truth_evidence.py`. | Scores are only as good as the truth. |
| 3 | `03_assemble.sh` | Trims reads and assembles them. | `fastp --length_required 50`, otherwise fastp defaults; `spades.py` with its own k-mer selection and a memory cap (or Unicycler). | This is the realistic starting point for most laboratories. |
| 4 | `04_run_tools.sh` | Runs each enabled tool and standardises its output. | Per-tool commands in [section 6](#6-the-tools-evaluated); adapters write `pred_<tool>.plasmid.fasta`. A failed run records its exit code. | One output contract for every tool. |
| 7 | `07_long_read_reconstruct.sh` | Runs the long-read and hybrid tools. | See [section 10](#10-long-read-and-hybrid-tracks). Off unless a tool flag is set. | Same scoring for long-read methods, behind the circularity guard. |
| 5 | `05_score.sh` | Scores every prediction. | minimap2, then `score_plasmids.py`, `score_bins.py`, merge scripts, structural calls. | Section 7. |
| 6 | `06_aggregate.sh` | Ranks tools and writes the report. | `aggregate_results.py` plus the design, robustness and leakage analyses and `build_html_report.py`. | Section 8. |
| 8 | `08_operational_reconstruct.sh` (`plasbench reconstruct`) | Runs one tool on a sample with no truth. | Section 12. | Turns benchmark evidence into a practical choice. |

**Recording failures.** Each stage records what did not work instead of hiding it: `download_status.tsv`, `assembly_status.tsv`, `tool_status.tsv` (completed, reused, failed with `exit_code=N`, or skipped with a reason), `score_failures.tsv`. A tool run that fails is the tool's result and is scored accordingly (section 8.3).

**Equal compute.** Every tool gets its own `<TOOL>_THREADS` setting defaulting to the same `THREADS`, so no tool is silently favoured. `scripts/thread_scaling_sweep.sh` tests whether results depend on the thread count.

---

## 6. The tools evaluated

The registry is `config/tool_capabilities.tsv`. Only `mob_recon`, `platon` and `plasmidspades` run by default; everything else is opt-in.

| Tool | Class | Bins | Input | Track | Needs independent long-read truth |
|---|---|---|---|---|---|
| mob_recon | binning | yes | assembly | short_read | no |
| platon | classification | no | assembly | short_read | no |
| plasmidspades | reassembly | no | paired reads | short_read | no |
| gplas2_mob | binning | yes | assembly graph | short_read | no |
| gplas2_external | binning | yes | assembly graph | short_read | no |
| genomad, plasme, rfplasmid, plasmidhunter, plasmer | ML classification | no | assembly | short_read | no |
| plasgraph2 | ML classification | no | assembly graph | short_read | no |
| plascope | classification | no | assembly | short_read | no |
| flye_mob_recon, trycycler_mob_recon | binning | yes | long reads | long_read | yes |
| hybracter_long | reassembly | yes | long reads | long_read | yes |
| plassembler, hybracter_hybrid | reassembly | yes | hybrid reads | hybrid | yes |

**How each is run** (details in `scripts/04_run_tools.sh` and `07_long_read_reconstruct.sh`):

- **mob_recon** `--infile contigs --outdir ... --num_threads N --force`; its plasmid FASTAs are concatenated and each file is one bin.
- **platon** with its database; every contig is its own bin but, because it is a classifier, it is not bin-scored.
- **plasmidspades** `-1 -2 -o ... --threads --memory`; every contig is treated as a plasmid prediction.
- **gplas2_mob** converts MOB hard labels into a seed classifier and runs `gplas`; **gplas2_external** takes a user-supplied classifier table.
- **geNomad** (`end-to-end`), **PLASMe** (probability threshold 0.5), **RFPlasmid** (species model, default Enterobacteriaceae), **PlasmidHunter**, **Plasmer**, **PlaScope** (E. coli and Klebsiella databases only), **plASgraph2** (CPU).
- **Long-read and hybrid:** Flye then MOB-recon; Plassembler; Hybracter (long or hybrid); Trycycler (subsample, Flye, cluster, reconcile, consensus, then MOB-recon; Medaka optional).

**Databases and leakage.** Many tools score contigs against a database of public plasmids or a model trained on one. Those sources overlap the public complete genomes PlasBench uses as truth. `config/tool_database_releases.tsv` records, per tool, which database it uses and (when you fill it in) its release date. Plassembler, Hybracter and PLASMe use PLSDB-derived data. PlasmidSPAdes uses no reference database.

**The adapter contract** keeps tools comparable:

- Every adapter writes `pred_<tool>.plasmid.fasta`, the standardised hard call (an empty file is a valid "predicted nothing").
- Binning-capable tools also write `pred_<tool>.bins.tsv` (`bin_id`, `sequence_id`; each record exactly once) ([adapters/BINS.md](../adapters/BINS.md)).
- Tools that give a per-record probability may write `pred_<tool>.candidates.fasta` and `pred_<tool>.scores.tsv` so a threshold-free PR-AUC can be computed ([adapters/SCORES.md](../adapters/SCORES.md)). Only geNomad, PLASMe, plASgraph2, RFPlasmid, PlasmidHunter and Plasmer provide this.
- The metagenomic track has its own contracts ([adapters/METAGENOMICS.md](../adapters/METAGENOMICS.md)).

To add a tool, register it in `config/tool_capabilities.tsv`, add an adapter that meets the contract, and add its database entry. See the contributing section of the README.

---

## 7. Scoring: what is measured, how, and why

### 7.1 Projection onto the reference

Each prediction FASTA is mapped to the truth with `minimap2 --secondary=no -c -x asm5` (same isolate, so at most about 5% divergence). Alignments are kept only if they pass four filters:

| Filter | Default | Why |
|---|---|---|
| Alignment length | 200 bp | Ignore short spurious hits. |
| Identity (matches / block length) | 0.90 | Ignore poor matches. |
| MAPQ | 20 | Repeats that map equally well to several places have MAPQ near 0; excluding them stops an arbitrary choice of "primary" placement from deciding TP or FP. |
| Query coverage per alignment | 0.20 | Ignore small local placements of a long contig. |

Filters apply to each alignment, not to the whole record. A record that is half plasmid and half chromosome contributes both of its primary pieces, so it is charged for its chromosome half. Any secondary alignment row (`tp:A:S`) in a supplied PAF is ignored with a warning. Overlapping alignments are merged, so each reference base counts once.

### 7.2 The confusion matrix (positive class = plasmid)

- **TP**: reference **plasmid** bases covered by a prediction.
- **FP**: reference **chromosome** bases covered by a prediction.
- **FN**: reference plasmid bases not covered.

| Metric | Definition | Why |
|---|---|---|
| **Precision** | TP / (TP + FP) | The complement of chromosomal contamination. Matters when plasmid-borne resistance is being reported. |
| **Recall** | TP / (TP + FN) | Completeness: how much true plasmid was recovered. |
| **F1** | 2PR / (P + R) | A tool cannot score well by maximising one at the expense of the other. |

**Undefined values.** A tool that predicts nothing on an isolate that has plasmids scores recall 0 and **F1 = 0** (precision left blank). On an isolate with no true plasmid, recall and F1 are blank, never `0`; use the negative-control metrics instead. This rule exists so that abstaining on hard isolates cannot raise a tool's average.

### 7.3 What the base-level metric hides, and the diagnostics that expose it

Predicted bases with **no retained alignment** (unmapped, or removed by the filters) are neither TP nor FP. Precision is therefore conservative about what it can attribute and **optimistic about noise**: a tool that emits chimeric or repeat-rich contigs that fail the MAPQ filter pays no precision penalty. Read these diagnostics beside precision and F1:

| Diagnostic | Meaning |
|---|---|
| `strict_precision` | TP / (TP + FP + unmapped predicted bases). Charges unmapped output. Mixes reference and query bases, so it is an approximation. |
| `unmapped_pred_bp`, `off_truth_pred_bp` | Predicted bases with no retained alignment, and bases that align only to a sequence absent from the truth table. |
| `ambiguously_mapped_pred_bp` | Predicted bases with retained placements on both plasmid and chromosome. A repeat flag, never a change to F1. |
| `redundant_pred_bp` | Reference bases claimed more than once. A multimer or duplicated record earns no extra TP and no penalty; this shows it. |
| `recall_ceiling`, `ceiling_adjusted_recall` | Truth plasmids are tiled into 1,000 bp windows (step 250) and mapped back with the scorer's filters; a window is *scorable* only if it maps to its own origin. The ceiling is the largest recall any tool could reach once repeats shared with the chromosome are discounted. A conservative approximation. |
| `isolate_specificity`, `chromosome_fp_bp`, `fp_predicted_record_count` | Negative-control metrics: how much chromosome was wrongly claimed. Most informative on isolates with no plasmid. |

`test/test_scoring_adversarial.py` pins this behaviour with hand-computed cases (chimeric contig, repeat at MAPQ 0 versus 20, multimer, truncated plasmid, secondary rows).

### 7.4 Plasmid-level recovery

Base-level recall pools all plasmids, so it cannot tell one large plasmid recovered and three small ones missed from four partly recovered.

| Metric | Definition |
|---|---|
| `plasmid_recall` | Fraction of true plasmids covered to at least 90% (`PLASMID_RECOVERY_THRESHOLD`). |
| `plasmid_recall_ge50`, `_ge90` | Fixed 50% and 90% bands. |
| `complete_circular_plasmid_recall` | Circular truth plasmids covered to at least 0.99995. Only defined when a curated circular list is supplied. It shows the *reference* plasmid was covered, not that the tool closed the circle. |
| `amr_gene_recall` | Fraction of curated AMR-gene intervals on true plasmids covered to at least 90%. Needs a curated `truth_amr.tsv`; blank otherwise. PlasBench never calls AMR genes on predictions. |

### 7.5 Bin-level metrics (binning-capable tools only)

Bins are matched to truth plasmids by a **Hungarian maximum-weight one-to-one assignment**, not a greedy rule.

| Metric | Definition |
|---|---|
| `lw_bin_f1` (**primary endpoint for reconstruction**) | Length-weighted binning F1 with an ungated match. Recall = bases placed in the correct matched bin over all truth-plasmid bases. Precision = those bases over all bases the bins align to (chromosome, other plasmids and unmatched bins count against it). |
| `bin_f1` | Count-based F1 over bins matched only if truth completeness ≥ 0.9 and bin purity ≥ 0.9. Supplementary. |
| `split_events`, `merge_events` | Plasmids spread across several bins, and bins holding several plasmids (≥ 10% each). |
| `contamination_fraction`, `contaminated_bins` | Chromosome-aligned bases in bins. |
| `nmi`, `variation_of_information` | Agreement between bins and truth plasmids over a base-weighted contingency table with virtual "unassigned" and "chromosome" categories. NMI cannot separate a merged bin from random assignment; VI can, so both are reported. Supplementary. |
| **CPRR** (correct plasmid reconstruction rate) | The share of truth plasmids reconstructed *correctly*: matched to a bin, coverage ≥ 0.95, that bin ≥ 95% from this plasmid, not split, and (where `base_level_metrics_valid` is yes) alignment identity ≥ 0.99. Pooled over plasmids with a cluster bootstrap interval. The thresholds are pre-specified and must not be tuned. |
| `perfect_reference_recovery`, `strict_reference_reconstruction` | Yes/no quality screens. They are not claims of nucleotide identity, closure or clinical fitness. |

*Why length-weighted:* a count-based metric lets a tool that recovers many small plasmids outrank one that recovers the large, AMR-carrying plasmid. Weighting by length reflects the sequence that matters.

### 7.6 Threshold-free ranking quality

For tools that give per-record probabilities, **PR-AUC** is the area under the precision-recall curve over every distinct probability, so a tool is not judged only at its own cut-off. It is supplementary and absent (never 0) for other tools.

### 7.7 Structural evidence

`python/call_structural_variants.py` reads each predicted record's alignment blocks and reports alignment-derived discordances (inter-replicon junction, inversion, relocation, reference deletion or insertion, tandem duplication) and a `collinear_fraction`. Every call is marked `validated: false`: these are candidate misassemblies, not confirmed ones. They never change scores. Replicon and MOB-type breakdowns of recovery (`stratify_recovery.py`) are descriptive only; groups under five plasmids are flagged underpowered.

---

## 8. Ranking and statistics

### 8.1 Tracks and tasks

A leaderboard is produced for each (track, task). A long-read tool is never ranked against a short-read tool, and a classifier-only tool is never ranked against a binning tool (it would be scored zero on a task it does not attempt).

| Task | Tools | Ranking metric |
|---|---|---|
| reconstruction | `binning_capable = yes` | length-weighted binning F1 (`lw_bin_f1`) |
| classification | others | base-level F1 |

### 8.2 The headline

1. **Reference standard.** Only samples with reference tier ≤ 2 enter the headline. If none qualifies, all samples are used and the report says so.
2. **Shared samples.** Each tool is ranked on the samples that every ranked tool has, so a tool cannot benefit from failing on hard isolates. If the tools share none, each uses its own samples and `ranking_basis` says so.
3. **Species balance.** The ranking score is the mean of per-species means over species with at least 20 independent clusters, so one over-represented species cannot dominate. Smaller species are described only. With no qualifying species the pooled mean is used and the basis column says so.
4. Ties rank by tool name, so the order never depends on row order.

### 8.3 Failures

A tool run that failed (`tool_status.tsv`) on a plasmid-bearing sample scores 0 for that tool. A tool that failed on **every** sample still gets a leaderboard row (score 0), in its own track, ranked last. A sample missing for any other reason (no status, skipped, scoring failure) is removed from every tool's ranking.

Exit codes 124 (timeout) and 137 (SIGKILL, the usual out-of-memory kill) are classed as **resource failures**: the machine ran out of time or memory, which says little about accuracy. By default they score 0 like any failure. `aggregate_results.py --resource-failures exclude` drops such samples from every tool's ranking instead. Either way `n_failed_resource` is reported.

### 8.4 Uncertainty

| Procedure | Detail |
|---|---|
| Interval | Percentile interval from a 1,000-resample bootstrap (fixed seed), resampling whole clusters within each species, then macro-averaging. Reported only with at least 5 values and 5 independent clusters. |
| Pairwise comparison | Two-sided sign-flip permutation test on paired per-sample differences (10,000 permutations, fixed seed), flipping whole clusters together; at least 5 paired clusters. |
| Multiplicity | Holm correction across all pairs within one (track, task). |
| `significant_vs_runner_up` | Whether the top tool's Holm-adjusted p-value against the runner-up is below 0.05. It describes the cohort, not the field. |
| Guard | Aggregation refuses to rank samples derived from the same genome (for example depth-ladder runs), because that would shrink the interval falsely. |

With few independent clusters the output is `not_assessed`, by design. Treat blank intervals as information, not as an omission.

### 8.5 How fragile is the ranking?

`python/rank_sensitivity.py` (stage 6; `RUN_RANK_SENSITIVITY=0` skips it) writes `benchmark.rank_robustness.tsv`. Per track it re-scores every PAF already on disk with one filter changed at a time (MAPQ 0 and 30, identity 0.80 and 0.95, query coverage 0) and re-ranks under strict F1, per-plasmid recovery and recovery at 90% completeness. For each variant it reports each tool's mean, rank, change from baseline, **Kendall's tau** against the baseline order, and whether the top tool is unchanged. A first place that does not survive a defensible change of filter is not a finding. It uses the samples that have a PAF, so failure-as-zero is not applied, and it warns if its recomputed baseline differs from `scores.tsv`.

---

## 9. Truth quality and leakage controls

| Risk | Control | Where |
|---|---|---|
| Truth labels wrong or uncertain (chromids, integrated plasmids, mislabels) | Evidence labels; ambiguous replicons set aside; `REVIEW` for unresolvable sequences. | Sections 4.3 to 4.5 |
| Truth not trustworthy because of how it was built | Reference tiers; tier 3 excluded from the headline and shown as a sensitivity analysis. | `benchmark.truth_provenance.tsv`, `benchmark.reference_tiers.tsv` |
| Tools may have seen the truth genomes (database or training overlap) | Date screen: each truth assembly's release date against each tool's database release date. | `flag_database_overlap.py`, `benchmark.database_overlap.tsv` |
| Non-independent isolates | Clusters by study and clone. | Section 4.6 |
| One species dominating | Species-balanced headline. | Section 8.2 |
| Sampling and repeats limit what any tool can score | Recall ceiling. | Section 7.3 |
| Reads used to polish the truth | `base_level_metrics_valid`; CPRR identity criterion applied only where valid. | Section 4.4 |
| Isolate difficulty confounds the comparison | Benchmark-only descriptors: assembly-graph dead ends, plasmid-to-chromosome depth ratio, plasmid-to-chromosome Mash distance (`RUN_DIFFICULTY_FEATURES`, off by default). | `compute_difficulty_features.py` |
| Cohort outliers | Robust z-score flags (advisory). | `benchmark.cohort_qc_flags.tsv` |

**The database-overlap screen is only as good as its inputs.** It needs `database_release_date` filled in for each tool in `config/tool_database_releases.tsv`; until then every database-using pair is `unknown`. When no pair can be judged, the leaderboard (stderr, Markdown and HTML) says explicitly that **leakage was not assessed**, instead of showing 0 / 0 / blank. It is a date-based screen, not proof that a genome is or is not in a database, and it does not measure sequence-level similarity to a tool's training data.

---

## 10. Long-read and hybrid tracks

Long reads play two distinct roles: as the **truth** (every run) and as a **reconstruction input** for the five long-read and hybrid tools. A tool given the reads its own truth was built from is scored against its own input, so PlasBench refuses by default.

**The circularity guard** (`long_read_truth_eligible` in `scripts/lib.sh`): a tool whose registry entry says `requires_independent_long_read_truth = yes` runs on a sample only if

- the sample sheet declares `truth_independent_of_long_reads` as yes/true/1, or
- the per-tool override `<TOOL>_ALLOW_CIRCULAR_TRUTH=1` is set (the override is recorded in `tool_status.tsv`).

A missing or blank value is treated as "assume circular", by design. Skips are logged with a `circular truth:` reason. Eligible long-read cohorts are those with truth independent of the reads, held-out long reads, or simulated data. `self_assembled_hybrid` truth can never qualify.

**Related experiments**

- **Depth ladder** (`plasbench depth-ladder`, `depth-report`): subsamples paired reads with `seqtk` (default 20, 40, 80, 160×; fixed seed) to separate a weak tool from too little data. Rungs are correlated, so they are refused as a headline leaderboard.
- **Read-quality ladder** (`read-quality-ladder`, `read-quality-report`): filters long reads by length and mean quality (Filtlong) for the long-read and hybrid tracks.
- **Simulated reads** (`truth_source=simulated`): a real reference with reads simulated at a declared depth, seed and error model. Short-read depth is uniform across all replicons, a documented simplification.

---

## 11. The metagenomic track

A separate workflow for mixed communities (wastewater, gut, environmental). It does not reuse isolate truth and its ranks are never compared with isolate results. Full detail is in [docs/METAGENOMICS.md](METAGENOMICS.md).

- **Manifest**: `community_id`, `sample_id`, `information_regime` (single sample, multisample, graph-aware, long-read supported), `truth_status` (synthetic, mock, verified, unavailable; `unavailable` is never ranked).
- **Truth**: per contig, `plasmid`, `chromosome`, `virus` or `unknown`. Three classes mean phage is not scored as chromosome error.
- **Scoring**: global one-to-one (Hungarian) bin matching, with precision, recall and F1 plus chromosome and virus contamination and ambiguous contigs. Classifiers get per-class precision, recall and F1 and are never pooled with bin reconstructors.
- **BMock12 control**: a real 12-strain mock community with released contig-level truth. It is labelled chromosome, so it measures **plasmid false positives, chromosome contamination and bin purity**. It cannot measure plasmid recall, closure, or rank tools for routine metagenomics.
- **Report**: `metagenomics.report.html`. Candidate bins are never interpreted as host linkage.
- **Status**: the real communities listed in `cohorts/metagenomics-real-v1.tsv` are a review panel, not a leaderboard, because their truth is unavailable or unvalidated.

---

## 12. Operational mode: using the evidence

Operational mode helps a laboratory apply benchmark evidence to a **sample that has no truth**.

- `plasbench reconstruct --sample ID --sra RUN` runs stage 1 (reads only), assembly, and exactly **one** tool, chosen as the evidence-gated recommendation for the sample's organism, then Gram group, then overall, or given with `--tool`. The output is always flagged `truth_available: false` and `confidence_tier: confirmation_required`.
- `plasbench select-candidates` creates the recommendation tables (`benchmark.recommendations.tsv`, `benchmark.stratified.tsv`) and copies the best **already-generated** prediction for each benchmark sample into `selected_candidates/<sample>/` with a `selection_report.json`. `plasbench select-unknown` applies those tables to a sample without truth. No consensus is fabricated and no tool is re-run.
- **Evidence gates**: a method is recommended for a stratum only with at least 5 samples and at least 80% coverage (`RECOMMENDATION_MIN_SAMPLES`, `RECOMMENDATION_MIN_COVERAGE`). A method tested on a small subset cannot become a recommendation.
- **Decision profiles** change only the ranking, never eligibility: `accuracy_first` (default), `amr_surveillance`, `rapid_screening`, `amr_context` (needs curated AMR truth, and falls back visibly otherwise).
- **Recommendation model** (`RUN_RECOMMENDATION_MODEL`, off by default): a small ridge regression of F1 and plasmid recall from isolate features. It runs only when leave-one-study-out validation shows at least 5% improvement over a per-tool baseline, with at least 3 studies and 20 samples; otherwise every script behaves as if it did not exist. Truth-derived features are barred from it. It is not meaningful on the shipped public cohorts.

**Nearest-reference screen (experimental, unvalidated; off by default).** `RUN_PLASMID_NOVELTY_CLASSIFICATION=1` reports how close each predicted record is, by Mash distance, to a 16-plasmid curated set. Calls are `close_reference_match`, `no_close_reference`, `insufficient_reference`. It is **not** a taxonomy, **not** a relatedness inference and **not** a test of novelty, and a Mash distance of 0.05 is not "95% similar" for plasmids: two equal-size sequences sharing about 35% of their k-mers reach it, and an exact piece under about 21% of a reference falls outside it. The result is shown in the report with its caveat. See [docs/OPERATIONAL_SELECTION.md](OPERATIONAL_SELECTION.md).

---

## 13. Outputs and how to read them

### 13.1 The files

| File | Contents |
|---|---|
| `results/scores.tsv` | One row per (sample, tool): the base-level, plasmid-level, bin-level and diagnostic columns (13.2). |
| `results/benchmark.leaderboard.tsv` / `.md`, `benchmark.<track>.leaderboard.*` | The ranked results, per (track, task). |
| `benchmark.paired_comparisons.tsv` | Pairwise differences, intervals and Holm-adjusted p-values. |
| `benchmark.species.tsv`, `benchmark.reference_tiers.tsv`, `benchmark.headline_design.tsv` | Per-species means, tier sensitivity, the ranking metric and basis. |
| `benchmark.rank_robustness.tsv` | How the ranking moves under changed scoring choices (8.5). |
| `benchmark.database_overlap.tsv` | Samples whose truth predates a tool's database. |
| `benchmark.truth_provenance.tsv`, `benchmark.clonal_groups.tsv` | How each truth was built, and the clusters. |
| `benchmark.recovery_by_replicon.tsv` | Descriptive recovery by replicon and MOB type. |
| `benchmark.cohort_qc_flags.tsv` | Outlier flags. |
| `benchmark.recommendations.tsv`, `benchmark.stratified.tsv`, `selected_candidates/` | Operational recommendations and selected predictions. |
| `benchmark.recommendation_validation.tsv` | Leave-one-study-out check of the recommendation. |
| `benchmark.report.html` | The interactive report (13.3). |
| `run_manifest.json` | Provenance (section 14). |
| `download_status.tsv`, `assembly_status.tsv`, `tool_status.tsv`, `score_failures.tsv` | What did not work, and why. |
| `results/<sample>/` | Predictions, PAFs, per-plasmid tables, bin matches, CPRR rows, PR curves, structural events and visualisation JSON. |
| `data/<sample>/` | Reference, truth tables, labels, features, reads, assembly. |

### 13.2 The `scores.tsv` columns

- **Identity**: `sample`, `tool`, `analysis_track`.
- **Confusion matrix**: `true_plasmid_bp`, `TP_bp`, `FP_bp`, `FN_bp`.
- **Predicted-sequence accounting**: `mapped_pred_bp`, `unambiguously_mapped_pred_bp`, `unmapped_pred_bp`, `off_truth_pred_bp`, `ambiguously_mapped_pred_bp`, `predicted_record_count`.
- **Plasmid-level and AMR**: `true_plasmid_count`, `recovered_plasmid_count`, `plasmid_recall`, `true_amr_gene_count`, `recovered_amr_gene_count`, `amr_gene_recall`, circular-plasmid counts and recalls.
- **Alignment accounting**: `alignment_total`, `alignment_retained`, `filtered_alignment_count`.
- **Headline base-level**: `precision`, `recall`, `f1`.
- **Negative controls**: `isolate_specificity`, `chromosome_fp_bp`, `fp_predicted_record_count`.
- **Graded recovery**: the `_ge50`, `_ge90` and complete-circular columns.
- **Diagnostics**: `redundant_pred_bp`, `strict_precision`, `scorable_plasmid_bp`, `recall_ceiling`, `ceiling_adjusted_recall`.
- **Binning**: `bin_precision`, `bin_recall`, `bin_f1`, `matched_bins`, `unmatched_bins`, `missed_plasmids`, `split_events`, `merge_events`, `contaminated_bins`, `chromosome_aligned_bp`, `repeat_ambiguity_bp`, `bin_total_mapped_bp`, `contamination_fraction`, `nmi`, `variation_of_information`, `perfect_reference_recovery`, `strict_reference_reconstruction`, `lw_bin_precision`, `lw_bin_recall`, `lw_bin_f1`, `cprr_plasmids`, `cprr_correct`, `cprr_correct_without_identity`.
- **Threshold-free**: `pr_auc`, `pr_n_thresholds`.

Blank always means "not defined or not assessed", never zero.

### 13.3 The HTML report

A single self-contained file. Its main sections are: Summary (report card and "start here" findings), Run metadata, Insights, Chart, **Leaderboard**, Robustness (ranked-on samples, independent clusters, strict precision, recall ceiling, database overlap), **Headline design** (reference standard, tier sensitivity, species balance), Recommendations, Validation, Selected reconstructions (with the experimental nearest-reference block when present), an interactive cohort dashboard and reconstruction-evidence explorer, All scores, Statistics, Bin diagnostics, Zero-plasmid controls, Graded recovery, Isolate difficulty, Cohort QC, Replicon recovery, QUAST diagnostics, Execution health, Tool and sample drill-downs, Legend, Artifact explorer and Method. It offers sortable tables, filters, CSV and BED export, a colour-blind-safe palette and a print view. Unmeasured values are shown as "not measured", never zero, and read coverage is never displayed because it is not measured.

### 13.4 How to read a leaderboard

1. Check the **basis** first: which track and task, how many samples (`n_ranking_samples`), how many independent clusters, whether the score is species-balanced or pooled, and which reference tiers.
2. Read the **interval**. If intervals overlap, the tools are not distinguishable on this cohort. A blank interval means too few independent units.
3. Read **precision beside recall**, and `strict_precision` beside precision. A high F1 with a large `unmapped_pred_bp` is not the same result as a high F1 with none.
4. Read **plasmid-level recovery** (`plasmid_recall`) and CPRR when your question is "did I get the whole resistance plasmid?". They are usually far lower than base-level recall.
5. Check the **robustness table** for rank changes under other scoring choices.
6. Check the **leakage line**. If it says leakage was not assessed, treat database-based tools' ranks as provisional.
7. Check **failures**: `n_failures_scored_zero` and `n_failed_resource`.

### 13.5 What you can and cannot conclude

| You may conclude | You may not conclude |
|---|---|
| Under this cohort, reference standard and scoring, tool A recovered more plasmid sequence than tool B, with this uncertainty. | That tool A is best for your taxon, unless your taxon is in the cohort with enough independent isolates. |
| A tool leaves a lot of unmapped or chromosomal output. | That its plasmid calls are wrong in a specific isolate. |
| A reconstruction matched a reference plasmid at the stated coverage, share and identity. | That the sequence is closed, circular or clinically validated. |
| A tool recovered a curated AMR-gene interval. | That the gene is plasmid-borne in your sample, or that it spread between hosts. |
| A predicted record is close, by Mash distance, to a reference plasmid. | That it is the same plasmid, belongs to a cluster, or is novel or not novel. |

---

## 14. Reproducibility and provenance

| Mechanism | What it gives you |
|---|---|
| **`run_manifest.json`** | Tool version, time, platform, container image and digest, database identity (path, file count, hash over names, sizes and times), model status, an allow-list of settings, SHA-256 of the sample sheet and every `truth.tsv`, tool versions for 23 binaries, runtime and memory per run, SHA-256 of every `benchmark*` output, and selected candidates. |
| **Cohort lock files** (schema 1.1) | `sample_sheet_sha256` plus NCBI assembly and SRA evidence per sample; `--verify-lock` fails on any change. A cross-cohort BioSample ledger prevents the same isolate entering twice. |
| **Environment lock** | `env/environment.lock.yml` (explicit, linux-64) built by `env/lock_environment.sh`. |
| **Container** | `Dockerfile` pins its base image by digest and builds from the lock. MOB-suite and gplas2 get separate environments. Databases are not baked in; `scripts/docker_run.sh` records the image digest. |
| **Release archives** | `make_release.sh` builds a checksummed archive; the release workflow verifies it; a Zenodo upload workflow and citation metadata are provided. |
| **Determinism** | The scorer uses only the Python standard library; bootstrap and permutation use fixed seeds. |

**Gaps to know about:** database release dates are blank until you fill them in, the manifest's database identity hashes names, sizes and times (not contents), the allow-list of settings omits some newer variables, and the MOB-suite database lives inside the conda environment (copy it with the environment).

---

## 15. Configuration reference

All settings are environment variables read by `config/config.sh` (override them on the command line or in `config/local.env`). `RUN_*` flags are 1 (on) or 0 (off).

**Compute**

| Variable | Default | Meaning |
|---|---|---|
| `THREADS` | CPU count | Threads per tool. A `<TOOL>_THREADS` variable exists per tool and defaults to this. |
| `MEMORY_GB` | 80% of available | Memory for assembly. |
| `MAX_PARALLEL_SAMPLES`, `MAX_PARALLEL_TOOLS` | 1, 1 | Fully sequential by default. |

**Tools**

| Variable | Default | Meaning |
|---|---|---|
| `RUN_MOB_RECON`, `RUN_PLATON`, `RUN_PLASMIDSPADES` | 1 | On by default. |
| `RUN_GPLAS2_MOB`, `RUN_GPLAS2_EXTERNAL`, `RUN_GENOMAD`, `RUN_PLASME`, `RUN_PLASGRAPH2`, `RUN_RFPLASMID`, `RUN_PLASMIDHUNTER`, `RUN_PLASMER`, `RUN_PLASCOPE` | 0 | Short-read tools, opt-in. |
| `RUN_FLYE_MOB_RECON`, `RUN_PLASSEMBLER`, `RUN_HYBRACTER_LONG`, `RUN_HYBRACTER_HYBRID`, `RUN_TRYCYCLER_MOB_RECON` | 0 | Long-read and hybrid tools, opt-in, behind the circularity guard. |
| `<TOOL>_ALLOW_CIRCULAR_TRUTH` | 0 | Override the circularity guard for one tool (recorded). |
| `FORCE_RERUN_TOOLS` | 0 | Ignore completed-result markers. |

**Reads and assembly**

| Variable | Default | Meaning |
|---|---|---|
| `ASSEMBLER` | spades | `spades` or `unicycler`. |
| `MIN_READ_LEN` | 50 | fastp length filter. |
| `FASTP_EXTRA` | empty | Extra fastp arguments. |

**Scoring**

| Variable | Default | Meaning |
|---|---|---|
| `MINIMAP2_PRESET` | asm5 | Alignment preset. |
| `MIN_ALIGNMENT_LENGTH`, `_IDENTITY`, `_MAPQ`, `_QUERY_COVERAGE` | 200, 0.90, 20, 0.20 | Alignment filters. |
| `PLASMID_RECOVERY_THRESHOLD`, `AMR_GENE_RECOVERY_THRESHOLD` | 0.90, 0.90 | Coverage to count as recovered. |
| `CPRR_MIN_COVERAGE`, `CPRR_MIN_SHARE`, `CPRR_MIN_IDENTITY` | 0.95, 0.95, 0.99 | Pre-specified; do not tune. |
| `RUN_SCORABLE_TRUTH`, `SCORABLE_WINDOW_BP`, `SCORABLE_STEP_BP` | 1, 1000, 250 | Recall-ceiling diagnostic. |
| `REPORT_MAPPING_AMBIGUITY` | 1 | Second, secondary-mapping PAF for the ambiguity diagnostic. |

**Truth and design**

| Variable | Default | Meaning |
|---|---|---|
| `RUN_REFERENCE_ANNOTATION` | 1 | Annotate the reference (replicon, MOB, AMR, rRNA, IS). |
| `RUN_TRUTH_LABEL_EVIDENCE` | 1 | Evidence labels; ambiguous replicons set aside. |
| `ALLOW_DEFAULTED_TRUTH` | 0 | Restore guess-chromosome for unresolved sequences. |
| `HEADLINE_MAX_REFERENCE_TIER` | 2 | Highest tier in the headline. |
| `MIN_SPECIES_CLUSTERS` | 20 | Clusters a species needs to enter the species-balanced headline. |
| `CLONAL_MASH_DISTANCE` | 0.0005 | Clonal-group threshold. |
| `EXCLUDE_DATABASE_OVERLAP` | 0 | 1 drops possible-overlap rows before ranking (default is report only). |
| `RUN_RANK_SENSITIVITY` | 1 | Write `benchmark.rank_robustness.tsv`. |
| `COHORT_QC_FLAGS_ENABLED` | 1 | Advisory outlier flags. |

**Operational mode and optional diagnostics**

| Variable | Default | Meaning |
|---|---|---|
| `RECOMMENDATION_MIN_SAMPLES`, `RECOMMENDATION_MIN_COVERAGE` | 5, 0.80 | Evidence gates. |
| `DECISION_PROFILE` | accuracy_first | Recommendation weighting. |
| `RUN_RECOMMENDATION_MODEL` | 0 | Ridge model, gated by validation. |
| `RUN_PLASMID_NOVELTY_CLASSIFICATION` | 0 | Experimental nearest-reference screen. |
| `RUN_DIFFICULTY_FEATURES`, `RUN_QUAST_DIAGNOSTICS`, `RUN_PROTEIN_ANNOTATION` | 0 | Optional diagnostics. |

**Command-line reference** (`plasbench --help` lists all):

| Group | Commands |
|---|---|
| Run | `run`, `report`, `reconstruct`, `select-candidates`, `select-unknown`, `open-report` |
| Set up and check | `check`, `install-conda`, `install-tools`, `upgrade`, `test`, `demo`, `docs`, `concept-note` |
| Cohorts | `init-local`, `validate-cohort`, `curate-cohort`, `discover-cohort`, `review-candidates`, `build-ledger`, `prepare-contribution` |
| Experiments | `depth-ladder`, `depth-report`, `read-quality-ladder`, `read-quality-report` |
| Evidence | `validate-orthogonal-evidence`, `import-external-benchmark`, `candidate-dataset` |
| Metagenomics | `metagenomics` (aliases `meta`, `beta`), `audit-meta-cohort`, `design-meta-synthetic`, `validate-meta-intake`, `materialize-meta-bmock12`, `normalize-meta-classifier`, `import-mobilome-evidence` |

---

## 16. A guide for domain experts: how to check it yourself

You do not need to take any statement here on trust. This section tells you how to verify each part, by the kind of expertise you bring.

### 16.1 For a microbiologist or AMR scientist: is the biology right?

| Check | How |
|---|---|
| Are the truth labels right for my isolates? | Open `data/<sample>/truth.tsv`, `truth_labels.tsv` and `truth_features.tsv`. Confirm each PLASMID has a replicon or relaxase marker and no rRNA, and each CHROMOSOME has rRNA. Read the `AMBIGUOUS` rows. Check the lengths against what you know. |
| Is the reference truly complete and from the same isolate? | The cohort lock records BioSample, BioProject and platforms. Check them against the source publication. For your own isolates, confirm long-read depth across each plasmid. |
| Is the plasmid count plausible? | Compare `true_plasmid_count` with your own knowledge of the isolate. A small cryptic plasmid missing from the reference will penalise a tool that finds it. |
| Does a "recovered" plasmid make sense? | Open `results/<sample>/<tool>.per_plasmid.tsv` and the structural events. Look at the alignment explorer in the report. |
| Are resistance genes handled the way I would? | `truth_amr.tsv` must be curated by you (gene, coordinates, database version). PlasBench does not call AMR genes on predictions, so the recall is of *your* curated intervals. |

### 16.2 For a bioinformatician: is the computation right?

| Check | How |
|---|---|
| Does the software behave? | `plasbench test` (offline regression suite), then `plasbench demo`. The scoring tests use hand-computed values: for example `test/test_scoring.py` and `test/test_scoring_adversarial.py`. |
| Is the score what I would compute? | Take one sample. Open `<tool>.pred_vs_ref.paf`, merge the retained alignments per reference sequence yourself, and count covered plasmid and chromosome bases. Compare with `TP_bp`, `FP_bp`, `FN_bp`. |
| Do the filters matter? | Run `rank_sensitivity.py`, or re-run `score_plasmids.py` with other `--min-alignment-*` values. Read `benchmark.rank_robustness.tsv`. |
| Does an independent scorer agree? | `python/compare_scoring_methods.py` compares PlasBench's scoring with a BLAST-based approximation for the same sample and tool (a labelled proxy, not an equivalence claim). Cross-checks with an external evaluator can be archived with `import-external-benchmark`. |
| Are the statistics right? | Read `python/headline_design.py` and `aggregate_results.py`. Check that the same seed gives the same interval, that whole clusters are resampled, and that `test/test_aggregate*.py` and `test_research_design.py` pass. |
| Can I reproduce a published run? | Verify the cohort lock (`validate-cohort --verify-lock`), use the environment lock or container digest, compare checksums in `run_manifest.json`. |

### 16.3 For a public-health or programme lead: is it usable and safe to rely on?

- Run the **small public cohort** first and confirm your installation reproduces the documented numbers' structure (the demo is synthetic and is not performance evidence).
- Read [section 13.5](#135-what-you-can-and-cannot-conclude) and [section 17](#17-validation-status-and-known-limitations) before using any ranking in a decision.
- Treat the operational recommendation as a **candidate choice that needs confirmation**, particularly for carbapenemase, outbreak or novel-plasmid claims.
- Note the platform requirements: Linux or WSL2, about 5.6 GB of databases, 30 to 90 minutes to install, and several hours for a ten-isolate cohort.

### 16.4 For a reviewer or funder: what would count as evidence?

See [section 17.3](#173-what-would-establish-the-claims). In short: real-data results on an independent, taxonomically broad cohort, with the robustness and leakage tables, and a truth-label audit.

---

## 17. Validation status and known limitations

This section records what has and has not been shown, so that a reader can judge the evidence. It separates *methodological limits* (inherent to the approach) from *work not yet done*.

### 17.1 What has been established

- The scoring arithmetic is covered by hand-computed unit tests, including adversarial cases (chimeric contigs, repeats at different MAPQ, multimers, truncated plasmids, secondary rows).
- The ranking rules guard against known benchmark-gaming routes: abstention and failure score zero, shared-sample ranking, cluster-aware resampling, a circularity guard for long-read truth, and an explicit refusal to rank correlated samples.
- Failure handling, tie-breaking, undefined-metric handling, study grouping and the leakage warning are covered by tests.
- The Continuous Integration job runs the full offline suite, the demo and a container build.

### 17.2 What has not been shown yet

| Not yet established | Consequence for you |
|---|---|
| **No benchmark result on real data ships with the repository.** The bundled leaderboards come from a synthetic demo and are explicitly not performance evidence. | You must run a cohort yourself (or wait for archived results) before drawing any conclusion about a tool. |
| Database release dates are blank in `config/tool_database_releases.tsv`. | Database leakage is reported as *not assessed* until you fill them in. |
| The shipped cohorts are small and taxonomically narrow: 17 of 32 `public-v2` isolates are *E. coli*, `public-v1` is mostly one study, and the added rows lack depth and plasmid counts. | A headline can rarely reach the 20-cluster species minimum, so the pooled fallback often applies, and intervals are often unavailable. Do not generalise to other taxa. |
| The nearest-reference Mash screen has not been validated against any independent plasmid partition and uses a 16-plasmid reference set. | Use it only as a distance report. |
| No laboratory (PCR, long-read confirmation) evidence is bundled. | Computational concordance is not biological confirmation. |

### 17.3 What would establish the claims

1. A full run of the working cohort for all default tools, with archived scores, manifest, robustness table and leakage table.
2. Filled database release dates, and ideally a sequence-level screen of truth plasmids against each tool's database.
3. An independent audit of truth labels and of the completeness of each reference.
4. Agreement with an independent scorer, and a simulation check that the intervals have their nominal coverage under clustered sampling.
5. External cohorts: other sequencing platforms, species, geographies, clinical and environmental isolates, with AMR-positive and AMR-negative isolates and some independent laboratory confirmation.

### 17.4 Methodological limits

| Limit | Why it matters | What to do |
|---|---|---|
| **Truth is an assembly.** Labels come from the submitter's record or from topology. Chromids, integrated plasmids, collapsed repeats and missed small plasmids can be wrong. | A correct tool can be penalised. | Use the evidence labels and tiers; audit the labels (16.1). |
| **Survivorship.** Only isolates with finished long-read or hybrid assemblies and matched public reads qualify, which favours less repeat-rich genomes. | Results may overstate performance on hard isolates. | Add difficult isolates; compare isolate difficulty descriptors with your own data. |
| **Precision is optimistic about unmapped output.** | Chimeric or repeat-rich output can go unpunished. | Read `strict_precision` and the robustness table. |
| **Base-level F1 is dominated by large plasmids.** | A recovered megaplasmid can mask missed small plasmids. | Read plasmid-level recovery, CPRR and per-plasmid tables. |
| **Repeats and IS elements** shared between plasmid and chromosome are filtered by MAPQ. | They cap recall and hide contamination. | Read the recall ceiling and ambiguity diagnostics. |
| **Fragmentation is invisible to base-level scoring.** A plasmid split into many contigs scores the same as one assembled whole. | A usable reconstruction is not the same as a high F1. | Read bin metrics, split and merge events. |
| **Long-read independence is scarce.** | Few samples qualify for the long-read track. | Use held-out reads or simulation. |
| **Database leakage is date-based.** | It cannot prove inclusion or absence. | Fill the dates; interpret as a screen. |
| **Short-read assembly parameters** use SPAdes defaults and a trimmed-read length filter; results depend on the assembler. | A different assembler changes what tools receive. | Compare `ASSEMBLER` settings. |

### 17.5 Behaviour in difficult cases

| Case | What PlasBench does |
|---|---|
| Several plasmids in one isolate | Scored per base, per plasmid and per bin; bins matched one-to-one. |
| Near-identical co-resident plasmids | Shared regions may fall below MAPQ 20 and cap recall; reported by the ceiling and ambiguity diagnostics. |
| Very large or very small plasmids | Large plasmids dominate pooled F1; small ones may be missed. Read per-plasmid recovery. |
| Divergent plasmids | A prediction that fails the identity or `asm5` filters is unmapped and not a false positive. |
| Fragmented or incomplete reconstruction | Recovery bands and split events show it; base F1 does not penalise splitting. |
| Plasmids rich in insertion sequences or transposons | Repeats are filtered by MAPQ; contamination can be hidden; structural calls flag discordances. |
| Plasmid-chromosome integration, chromids | Truth label may be ambiguous; such replicons are set aside when evidence conflicts. |
| Chromosome called plasmid | False positives are counted (unless the call falls in a filtered repeat). |
| Contaminated reads | Unmapped output is reported, not scored as false positive. |
| Different species, locations or times | Species-balanced where data allow; geography and date are metadata, and there is no temporal evaluation. |
| A tool needs a database that is missing | The tool is skipped with a recorded reason and does not score as zero. |
| The machine runs out of memory | Recorded as a resource failure and, by default, scored as 0; `--resource-failures exclude` changes this. |

---

## 18. Scope matrix

| Capability | Status |
|---|---|
| Benchmark short-read plasmid reconstruction and classification tools against a complete reference | **Implemented**; validated by unit tests, not yet by a published real-data run. |
| Per-track, per-task, species-balanced, cluster-aware ranking with intervals | **Implemented.** |
| Reference-tier, species, robustness and leakage analyses | **Implemented.** |
| Long-read and hybrid tool benchmarking behind a circularity guard | **Implemented**, opt-in; few eligible samples exist. |
| Separate metagenomic bin and classifier scoring | **Implemented**; limited to negative-control and review panels. |
| Operational method recommendation for a sample without truth | **Implemented**; evidence-gated and needs confirmation. |
| Learned recommendation model | **Implemented, off by default**, gated by validation. |
| Nearest-reference Mash screen | **Experimental, unvalidated, off by default.** |
| Plasmid identification for a user's sample | **Not a PlasBench function.** |
| Plasmid clustering, communities or subcommunities | **Not implemented.** |
| PLSDB comparison, most-similar reference, relatedness, backbone versus accessory analysis | **Not implemented.** |
| Transmission, outbreak or horizontal-gene-transfer inference | **Not implemented and not claimed.** |
| Clinical or diagnostic use | **Out of scope.** |

If you need plasmid relatedness, clustering or database comparison, use a method designed and validated for it (for example MOB-typer's cluster codes, COPLA, or PLSDB's own search) and cite that tool; do not infer these from PlasBench's output.

---

## 19. Further documentation

| Document | Covers |
|---|---|
| [README](../README.md) | Installation and step-by-step workflows for a laboratory. |
| [docs/USER_GUIDE.md](USER_GUIDE.md) | The full user guide, including the recommendation model and `reconstruct`. |
| [docs/METHODS.md](METHODS.md) | The scoring and research-design specification, written to be lifted into a methods section. |
| [docs/COHORTS.md](COHORTS.md) | Cohort format, validation, discovery, curation, tiers and public panels. |
| [docs/GOVERNANCE.md](GOVERNANCE.md) | Release, review and retirement policy. |
| [docs/METAGENOMICS.md](METAGENOMICS.md) | The separate metagenomic track. |
| [docs/OPERATIONAL_SELECTION.md](OPERATIONAL_SELECTION.md) | Recommendations, `reconstruct` and the nearest-reference screen. |
| [docs/FINDING_DATA.md](FINDING_DATA.md) | How to find matched reference and read pairs. |
| [docs/SCENARIOS.md](SCENARIOS.md) | Scenario-specific cohorts (outbreak, metagenomic). |
| [docs/EXTERNAL_EVIDENCE.md](EXTERNAL_EVIDENCE.md), [docs/ORTHOGONAL_VALIDATION.md](ORTHOGONAL_VALIDATION.md) | Keeping published or laboratory evidence separate from native scores. |
| [docs/VISUAL_QUALITY.md](VISUAL_QUALITY.md) | The visual explorer. |
| [docs/CONCEPT_NOTE.md](CONCEPT_NOTE.md) | A non-technical overview for partners and funders. |
| [CHANGELOG.md](../CHANGELOG.md), [docs/RELEASES.md](RELEASES.md) | What changed, and how to choose and verify a release. |

**Background reading** (check the original papers before citing): Ondov et al. 2016, *Genome Biology* (Mash); Arredondo-Alonso et al. 2017, *Microbial Genomics* (limits of plasmid reconstruction from short reads); Robertson and Nash 2018, *Microbial Genomics* (MOB-suite); Galata et al. 2019 and Schmartz et al. 2022, *Nucleic Acids Research* (PLSDB); Redondo-Salvo et al. 2020, *Nature Communications* (COPLA); Schwengers et al. 2020, *Microbial Genomics* (Platon); Camargo et al. 2023, *Nature Biotechnology* (geNomad); Teixeira et al. 2025, *Briefings in Bioinformatics* (benchmarking plasmid detection and reconstruction from short reads, cited in `docs/METHODS.md`).

To cite PlasBench, use the version and cohort you ran and the metadata in `CITATION.cff`.
