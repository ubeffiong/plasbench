# PlasBench and the reviewer question bank

A 108-question reviewer bank was written for an expert panel examining PlasBench. Every
question is answered here, briefly, with the evidence behind the answer. This file
complements [`FAQ.md`](../FAQ.md), which answers the questions a PlasBench user asks
most often in more depth. Where this file says "see FAQ", the fuller answer is there.

## Read this first: what PlasBench is

Much of the bank assumes PlasBench is a plasmid relatedness or clustering tool. It is not:
plasmid clustering, communities, database search, relatedness, backbone/accessory analysis
and phylogeny are outside this benchmark.

**PlasBench benchmarks plasmid reconstruction tools.** For each isolate it runs tools
such as MOB-recon, Platon, plasmidSPAdes or geNomad on a short-read assembly. It then
maps each tool's predicted-plasmid sequence onto a complete reference genome *of the same
isolate*, and scores how much true plasmid sequence was recovered, how much chromosome was
wrongly included, and how well contigs were grouped into plasmids. The output ranks the
tools. It never compares one isolate's plasmids with another's.

So a question about those topics is answered in one line, "outside this benchmark". Where a question exposed a real gap in
what PlasBench does claim, the gap was closed in software and tested; the status says so.

**Status labels** (same meanings as `FAQ.md`)

| Label | Meaning |
|---|---|
| **Verified** | Implemented, and a test in `test/` exercises it. |
| **Fixed here** | The question exposed a gap; the fix and its test were added alongside this file. |
| **Documented** | Stated in the docs, not enforced by code. |
| **Open** | Not done; the reason is given (usually: it needs real data, not code). |
| **Not applicable** | The question assumes a capability PlasBench does not claim. |

Code changes made for this file (all tested in `test/test_question_bank_gaps.py`):
probability calibration (Q66); two trivial baselines scored like tools (Q62, Q78, Q108);
an "Interpretation limits" report section (Q41-43, Q68-73); metadata-completeness
reporting (Q85); and run-manifest recording of every setting that changes a ranking (Q36, Q38).

---

## Part I. Fundamental questions (level 1)

**Q1. What decision does PlasBench enable that MOB-suite, geNomad, Pling and PLSDB cannot?**
Which reconstruction tool to trust for a given kind of isolate and read data. The evidence
is how well each tool recovered *known* plasmids, on isolates with complete reference
genomes, scored on one common metric. Each of those tools makes its own predictions; none
measures how often the predictions are right on independent truth. The user is a
laboratory or pipeline maintainer choosing a method. *Documented.* Whether the choice
changes in practice depends on a real-cohort result (Q22 in FAQ). *Open.*

**Q2. What would be lost if PlasBench were deleted?**
A reproducible, shared scoring of reconstruction tools on the same truth and metric, with
failure handling, cluster-aware uncertainty and leakage screening. Reproducing that by hand
is possible but error-prone, as this project's own audit history shows (FAQ). It is
benchmark infrastructure, not a new biological capability. *Documented.*

**Q3. What is the central claim: methods, biological or surveillance?**
A **methods claim**: on stated cohorts and truth, tool A recovers plasmids more completely,
more cleanly and with better grouping than tool B. No biological or surveillance claim is
made. *Documented.* The report's "Interpretation limits" section says so (*Fixed here*).

**Q4. What does PlasBench mean by "plasmid relatedness"?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids. It measures agreement between a prediction and the truth of the same isolate.

**Q5. What is the minimum viable contribution?**
A benchmark, meaning a scoring method, curated truth with provenance tiers, and a
reproducible pipeline. It is not a new algorithm. *Documented.*

**Q6. What evidence assigns plasmids to the same community?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q7. Can a mosaic plasmid have a single evolutionary history?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q8. Two plasmids share a carbapenemase gene but have unrelated backbones: related?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids. Within one isolate, AMR placement (Q-P10) checks the gene lands on its own plasmid.

**Q9. Identical replicon, different backbones: same lineage?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q10. What does "novel plasmid" mean?**
Benchmark scoring never calls novelty. A separate, off-by-default operational screen
(`classify_operational_plasmid.py`, stage 8) reports Mash distance from an unknown
isolate's candidate plasmid to a small curated reference set (16 accessions). It
measures distance to that set, **not novelty**; the open audit PR #8 renames its outputs
to `close_reference_match` / `no_close_reference` to stop that misreading. *Documented;
the rename is pending PR #8.*

**Q11. What published limitation does PlasBench overcome?**
Existing reconstruction tools are evaluated mostly in their own papers, on their own data,
with incompatible metrics. Independent comparisons such as Teixeira et al. 2025 ("Circling
in on plasmids", Briefings in Bioinformatics, doi:10.1093/bib/bbaf589) are one-off
studies, not reusable pipelines. *Documented.* Verify the exact claims of cited
benchmarks before publishing.

**Q12. What result would falsify the central claim?**
The claim is that rankings are stable, measurable properties of tools. It is falsified if
rankings change when:
- the alignment filters change (rank robustness, PR #8);
- the cohort is resampled (cluster bootstrap intervals);
- truth moves from tier 1/2 to tier 3 (`benchmark.reference_tiers.tsv`); or
- the species changes (`benchmark.species.tsv`).

A tool that fails to beat a trivial baseline falsifies any claim that it adds value
(*Fixed here*: `beats_best_baseline`). *Verified.*

## Part II. Methodological questions (level 2)

**Q13. What similarity measure is used?**
For scoring, base-level alignment of the prediction to the same-isolate truth:
`minimap2 -x asm5 -c --secondary=no`, primary alignments only. A reference base counts as
covered when a retained alignment spans it, so precision, recall and F1 are fractions of
reference bases (`python/score_plasmids.py`). Not ANI or Mash: the question is "was this
truth base recovered", not "how similar are two plasmids". *Verified.*

**Q14. Global or local comparison?**
Local alignments, merged per reference base, so rearrangements and indels cannot double
count. Structural discordance is reported separately as typed events
(`python/call_structural_variants.py`). *Verified.*

**Q15. How are IS elements, transposons and integrons handled?**
Repeats shared by plasmid and chromosome map with low MAPQ and are dropped by the MAPQ ≥ 20
filter. That makes them unscorable, never wrongly credited. The **recall ceiling**
(`python/scorable_truth.py`) measures how much truth is lost this way;
`ambiguously_mapped_pred_bp` reports predictions with both plasmid and chromosome
placements. *Verified.*

**Q16. What alignment coverage threshold declares similarity?**
The scoring filters are minimum alignment length 200 bp, identity 0.90, MAPQ 20 and
per-record query coverage 0.20. Plasmid "recovery" means ≥ 90% coverage
(`PLASMID_RECOVERY_THRESHOLD`). CPRR additionally needs ≥ 95% coverage, ≥ 95% bin share and
≥ 99% identity where valid. All are pre-specified in `config/config.sh` and recorded in the
run manifest (*Fixed here*). Their effect on rankings is sensitivity-tested by rank
robustness (PR #8). *Verified.*

**Q17. Why pairwise rather than a graph?**
Scoring compares each prediction with its own truth, so there is no plasmid graph to
build. *Not applicable.* Assembly graphs are inputs to graph-aware tools such as gplas2
and plASgraph2.

**Q18. How are repeats that align to multiple plasmids handled?**
Primary-only mapping plus the MAPQ filter, the ambiguity diagnostic and the recall ceiling
(Q15). Binning uses one-to-one matching, so one repeat cannot match two plasmids.
*Verified.*

**Q19. What clustering algorithm assigns communities?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q20. Are cluster boundaries statistically justified and stable?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids. Ranking stability is covered by cluster-bootstrap intervals, rank robustness and the tier tables. *Verified.*

**Q21. Can a plasmid belong to two communities?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q22. How are spurious groupings from one shared gene avoided?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q23. What happens to plasmids that fit no cluster?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q24. Which reference database and version?**
Scoring uses the isolate's own complete genome (NCBI Complete Genome, accession pinned in
the cohort sheet and verified online), not a reference database. The tools' own
databases and dates are in `config/tool_database_releases.tsv`. *Verified.*

**Q25. How is a novel plasmid distinguished from one missing from the database?**
It can't be, and PlasBench doesn't try (Q10). For benchmark truth, marker-free plasmids
are AMBIGUOUS and counted (`marker_free_plasmids`), so this bias is reported, not hidden.
*Documented.*

**Q26. Is database versioning recorded, and can results be reproduced?**
Tool versions go into `run_manifest.json`. Database release dates go into
`tool_database_releases.tsv`, filled from verified sources for every installed database.
Cohort sheets are versioned (`public-v1`, `public-v2`) with SHA-256 locks of the NCBI
evidence. *Verified.*

**Q27. What if the closest match is misleading because of a shared mobile element?**
Not applicable to scoring (Q13). For the operational screen, see Q10.

## Part III. Workflow and architecture (level 3)

**Q28. What input does PlasBench accept?**
For isolates: paired-end Illumina reads (assembled by PlasBench) plus a complete reference
assembly as truth. Long reads are accepted for the long-read and hybrid tracks. Tools'
own outputs are normalised by adapters into a predicted-plasmid FASTA, plus bins and
probabilities where available. *Verified.*

**Q29. How are plasmids spread over several contigs handled?**
That is exactly what binning tools are scored on. Length-weighted binning F1 rewards
grouping a plasmid's contigs into one bin; split events report when a tool divides one
plasmid. *Verified.*

**Q30. How is assembly quality and coverage assessed?**
`python/compute_assembly_stats.py` (N50, contig count), `measure_depth.py`, and
read-quality bands. Cohort QC flags outliers. Low coverage lowers the recall ceiling, and
the depth-ladder mode measures performance against depth. *Verified.*

**Q31. How are plasmid and chromosome contigs told apart, and what is the false-positive
rate?**
That is what the benchmarked *tools* do. PlasBench measures their false-positive rate:
`chromosome_fp_bp`, precision, and isolate specificity on zero-plasmid negative controls.
*Verified.*

**Q32. Multiple similar plasmids in one isolate?**
Each truth plasmid is matched to at most one bin. Two similar plasmids co-assembled into
one contig show up as a merge, with lower bin share, so neither passes CPRR. Duplicate
identical plasmids lose recall to MAPQ 0, which the recall ceiling shows. *Verified.*

**Q33. Circular versus linear plasmids?**
Truth topology is used where known. `complete_circular_plasmid_recall` reports whether
circular truth plasmids were fully recovered. Prediction circularity is not scored,
because most tools do not report topology. *Verified.*

**Q34. Plasmid-chromosome integration?**
An integrated plasmid is part of the chromosome in the truth and is scored as chromosome.
The evidence labeller flags chromosome-labelled replicons carrying plasmid markers as
AMBIGUOUS when they are secondary replicons. Integration *within* the chromosome is not
detected. *Open:* it needs a dedicated integration caller.

**Q35. Runtime and scale?**
Per-tool runtime and peak memory are recorded (`tool_status.tsv`). Scoring is one minimap2
call plus linear-time interval merging per tool and sample. The recall ceiling adds one
call per plasmid set. Bin matching is Hungarian, O(n³) in bins, which is small per
isolate. *Verified.*

**Q36. Is the pipeline deterministic?**
Bootstrap and permutation seeds are fixed (20260831, 20260901, 20260902). Results are
deterministic given identical tool outputs. Some benchmarked tools (assemblers using
several threads) are not deterministic themselves. Every setting that changes a ranking
is now recorded in the run manifest (*Fixed here*: CPRR, headline-tier, species,
clonal, recall-ceiling, truth-evidence, leakage and baseline settings were missing).
*Verified.*

**Q37. Are intermediate files kept, and can stages rerun or resume?**
Yes. Stages 1–8 run independently; each tool result carries a `.complete` marker and is
reused on rerun. PAFs, bins and per-plasmid tables stay under `results/<sample>/`.
*Verified.*

**Q38. Can an analysis be reproduced from configuration alone?**
`run_manifest.json` records tool versions, the sample sheet, truth checksums and the
settings allow-list, completed for this file (Q36). The configuration lives in
`config/config.sh`, with every default commented. *Verified.*

**Q39. What happens when a stage fails?**
Failures are explicit:
- a failed tool run is `failed` in `tool_status.tsv` and counts as F1 = 0 on
  plasmid-bearing samples;
- scoring failures go to `score_failures.tsv`;
- missing references or truth skip that sample with a warning;
- a baseline that cannot apply is `skipped`, not failed.

*Verified.*

**Q40. What does the output look like, and can a non-bioinformatician follow it?**
TSV leaderboards per input track and task, a Markdown leaderboard, and an offline HTML
report with plain-language sections and a glossary of every term. *Verified.*

**Q41. How is uncertainty represented?**
- 95% cluster-bootstrap intervals and Holm-adjusted paired permutation tests.
- "< 5 independent units" when an interval cannot be supported.
- AMBIGUOUS truth.
- Recall ceilings.
- Rank robustness (PR #8).

The "Interpretation limits" section defines the words used (*Fixed here*). *Verified.*

**Q42. Is strong evidence distinguished from weak?**
Yes, at plasmid level:
- **CPRR** needs full coverage, purity, no split, and identity where valid.
- **Graded recovery** bands report ≥ 50%, ≥ 90%, and complete-and-circular.
- Coverage below the scoring filters is not counted at all.

*Verified.*

**Q43. Does the output show which AMR genes are shared and where?**
For curated AMR truth: which genes were recovered inside predicted plasmids
(`amr_gene_recall`), and their positions in the explorer view. Comparison *between*
isolates is not done (Q8). *Verified* for recovery; *Not applicable* for between-isolate
sharing.

## Part IV. Edge cases (levels 2–3)

**Q44–Q47 (backbone versus accessory sharing, shared carbapenemase, identical replicons,
mosaic plasmids).** *Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q48. A plasmid on five contigs, one chimeric with chromosome.**
The chimeric contig's chromosome bases count as false positives (precision drop, bin share
below 95%, so CPRR fails). The plasmid part counts as true positive. The structural
caller reports the chimera as a typed event. *Verified* (`test_scoring_adversarial.py`,
PR #8; structural tests on main).

**Q49. Two related plasmids co-assembled into one contig.**
One bin aligns to two truth plasmids: a merge event, and neither plasmid passes CPRR's
bin-share criterion. *Verified.*

**Q50. A small cryptic plasmid (< 2 kb) with no replicon.**
In truth, a plasmid without any marker is AMBIGUOUS, excluded from scoring and counted as
marker-free. If its long-read support is low, it is short-read-only evidence. Size-stratified
recovery is on the companion branch (FAQ). *Verified* for labelling.

**Q51. A very large plasmid (> 200 kb) with many repeats.**
Scored like any plasmid. Repeats lower its recall ceiling, which is reported, and
length-weighted binning gives it weight in proportion to its size. *Verified.*

**Q52. Integrated or excised plasmids.**
See Q34. *Open* for integration calling.

**Q53–Q56 (partial PLSDB matches, redundant records, misannotated references, genuinely
novel plasmids).** *Outside this benchmark:* no database search is performed; scoring uses
each isolate's own truth, whose labels are checked (Q-P1).

**Q57. 10,000 plasmids: runtime and memory?**
Scoring is per isolate, with no all-against-all step, so cost grows linearly with
isolates. *Verified.*

**Q58. A database update with 5,000 new plasmids?**
Truth does not depend on a plasmid database, so nothing is reprocessed. A tool's own
database update changes its version and date in the registry and the manifest, and needs
that tool rerun. *Documented.*

**Q59. A cluster assignment changes between database versions?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

## Part V. Validation and benchmarking (levels 2–3)

**Q60. What ground truth, and is it independent of development?**
NCBI Complete Genome assemblies of the same isolates, verified online and locked. As of
this release:
- **Tiers.** Truth is graded 1–3 by provenance. Short-read-first or unknown truth is tier
  3, outside the headline.
- **Recorded provenance.** Assembly strategy and polishing reads are recorded from NCBI
  evidence (`python/collect_truth_provenance.py`). In `public-v2`, 13 of 32 truths are
  long-read-first or long-read-only (11 and 2).
- **Same-read polishing.** Truth polished with the benchmark's own reads is never used
  for identity criteria.

*Verified.*

**Q61. Which metrics, with intervals?**
- **Primary:** length-weighted binning F1.
- **Secondary:** CPRR and base-level precision, recall and F1.
- **Supplementary:** NMI, VI, PR-AUC, and now Brier score and ECE (*Fixed here*).

All rankings carry cluster-bootstrap 95% intervals. A base-pair-weighted Adjusted Rand
Index is reported beside NMI (#12). *Verified.*

**Q62. Compared with MOB-suite, geNomad, Pling and a PLSDB BLAST/Mash baseline?**
MOB-suite, geNomad and others are benchmarked *as tools*. Pling is not a reconstruction
tool. Two trivial baselines are now scored with every run:
- **`baseline_coverage`:** contigs with depth well above the median.
- **`baseline_reference`:** contigs that align to the local plasmid reference set, a
  PLSDB-search stand-in.

Each tool's leaderboard row says whether it beats the best baseline. *Fixed here.* The
local reference set is small (16 accessions); point `PLASMID_REFERENCE_FASTA` at a PLSDB
export for a full-strength baseline.

**Q63. How is data leakage avoided?**
Tools' databases are screened by date. A truth genome released before a tool's database
is `possible_overlap`; leaderboards report F1 on post-database samples, with optional
exclusion. Release dates are filled for every installed database. *Verified.*

**Q64. Negative controls?**
Zero-plasmid isolates measure false-positive plasmid calling (isolate specificity,
chromosome false-positive bp). The trivial baselines act as performance floors. A
"shares only an AMR gene" control is outside this benchmark.

**Q65. Stable across size, ARG status, species and geography?**
- **Species:** `benchmark.species.tsv`.
- **Reference tier:** `benchmark.reference_tiers.tsv`.
- **Replicon and MOB type:** recovery by type (#6).
- **Size and ARG status:** stratification on the companion branch (FAQ).
- **Geography:** not stratified. The completeness table flags isolates without
  `collection_country`.

*Partly verified; geography Open.*

**Q66. Is the confidence score calibrated?**
Now measured. For tools that expose a per-contig plasmid probability, each contig's
probability is compared with the share of its truth-aligned bases that lie on plasmid.
The outputs are:
- **Brier score:** lower is better; 0 is perfect.
- **Expected calibration error:** over 10 bins.
- **Reliability diagram:** in the report.

*Fixed here.* PlasBench itself outputs no confidence score.

**Q67. External validation?**
Cohorts span several species, platforms and studies, and the leave-one-study-out
validation exists. No external group has yet run PlasBench. *Open:* needs collaborators.

## Part VI. Interpretation and public health (levels 1–3)

**Q68. Two "related" plasmids from different hospitals: what can be concluded?**
PlasBench never reports this. The report's "Interpretation limits" section states that
results say nothing about transmission, common source or lineage. *Fixed here.*

**Q69. Is genomic relatedness distinguished from epidemiological association and
transmission?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids. The report's vocabulary avoids these claims (*Fixed here*).

**Q70. Can collection date, location, host or metadata be used?**
Yes, as stratifiers and for completeness checks:
- species, country and isolation source are read from the sample sheet;
- missing fields, and what each absence changes, are reported (*Fixed here*);
- metadata never enters scoring.

**Q71. Plasmid spread versus resistance-gene spread?**
Not addressed. Q8 and the report's limits section state this. *Not applicable.*

**Q72. What is the actionable output for a public-health authority?**
A method recommendation (which tool to use, coverage-gated and validated
leave-one-study-out) and a selected reconstruction per isolate. Neither is an outbreak
alert. *Documented.*

**Q73. What conclusions does PlasBench warn against?**
The "Interpretation limits" report section, *Fixed here*, warns against:
- inferring relatedness, transmission, gene-versus-plasmid spread or novelty;
- assuming clinical validity;
- treating a score as experimental confirmation.

## Part VII. Comparison and novelty (levels 1–2)

**Q74. Strongest defensible novelty claim, in one sentence?**
"A reproducible benchmark that scores plasmid reconstruction tools on a common metric
against provenance-graded truth, with failure-aware, species-balanced, cluster-aware
statistics and trivial baselines." That is an operational and methods contribution;
evidence that it matters needs a real-cohort run. *Documented.*

**Q75. How does it differ from Pling?**
Pling compares plasmids with each other, which is outside this benchmark. PlasBench scores
predictions against truth. *Documented.*

**Q76. How does it differ from MOB-suite?**
MOB-suite is one of the tools PlasBench scores. PlasBench adds the measurement, not
another reconstruction. *Documented.*

**Q77. Is the integrated workflow validated as a whole?**
The scoring path is tested end to end: the demo pipeline, about 90 Python and 48 shell
tests, and a Linux CI run of the whole suite and the demo. No independent real-cohort
validation of the whole workflow exists yet. *Verified; real-data run Open.*

**Q78. Could a shell script chaining MOB-suite, geNomad and a PLSDB search replace it?**
That script would *produce* predictions; it would not tell you whether they are right.
PlasBench now scores such a search as a baseline (Q62). *Fixed here.*

## Part VIII. Software and usability (levels 3–4)

**Q79. Is the code modular and tested?**
Single-responsibility scripts under `python/` and staged shell drivers. About 90 Python
regression tests and 48 shell tests run in CI, along with shellcheck at warning level.
Coverage percentage is not measured. *Verified.*

**Q80. Are dependencies pinned and reproducible?**
- **Conda:** `env/environment.lock.yml`, an explicit lock.
- **Docker:** the image is built from that lock.
- **Platforms:** CI tests on Ubuntu; Windows runs through WSL.

*Verified.*

**Q81. Open source and auditable?**
GPL-3.0. Every scoring rule is in readable standard-library Python. *Verified.*

**Q82. How are errors and malformed input handled?**
Validators reject bad truth tables, cohort sheets, AMR truth and PAFs with clear errors
(`validate_*.py`). Undefined metrics are blank, never 0. *Verified.*

**Q83. What does a laboratory need, and is programming required?**
- **Inputs:** a sample sheet and NCBI accessions, or local files (`plasbench init-local`).
- **Commands:** one `plasbench run` command, plus a guided installer and Docker image.
- **Galaxy:** wrappers exist for scoring and aggregation (`galaxy/`).

A Linux or WSL command line is still needed. *Documented.*

**Q84. Are outputs understandable to non-bioinformaticians?**
The HTML report has plain-language sections, a glossary of every term, tooltips, and the
interpretation-limits section. *Verified.*

**Q85. What happens with incomplete metadata?**
The run continues. Each scored sample's missing consequential fields, and what each
absence changes, go to `benchmark.metadata_completeness.tsv` and the report. For example,
no species means the sample leaves the species-balanced headline. *Fixed here.*

**Q86. Do visualisations aid interpretation?**
Each visual answers a question:
- **Explorer view:** the genomic regions behind each call, as alignment blocks on the
  truth.
- **Charts:** recall versus ceiling, precision versus strict precision, tier sensitivity,
  and reliability diagrams.

*Verified.*

**Q87. Local, HPC, cloud, low-resource deployment?**
Runs locally, in Docker, and under WSL. Thread and parallelism settings scale down for
small machines. No HPC scheduler integration exists. *Partly verified; HPC Open.*

**Q88. Maintenance and database updates?**
Database dates are a registry that the user fills and the code checks. Cohort releases
are versioned with locks and Zenodo DOIs. A sustainability plan beyond the developer is
not documented. *Open.*

**Q89. What would cause a funder to reject the project?**
No real-cohort results yet; a small cohort (32 isolates, E. coli-heavy, being expanded in
`public-v3`); and no external users. *Documented.*

## Part IX. Statistics (levels 2–3)

**Q90. Statistical assumptions?**
Isolates within a cluster (shared BioProject or clonal group) are not independent.
Bootstrap and permutation tests resample whole clusters within species. Plasmids within
an isolate are pooled for CPRR, with isolate-level cluster intervals. *Verified.*

**Q91. Are thresholds calibrated or conventional?**
They are conventional: 90% recovery and the CPRR 95/95/99 cut-offs. They are pre-specified
and recorded, and rank robustness tests how much rankings depend on them (PR #8). No
"95% ANI" species threshold is used for scoring. *Documented.*

**Q92. Does sequence length bias the scores?**
- **Base-level scores:** weight large plasmids more.
- **Plasmid recall and CPRR:** weight each plasmid equally.
- **Length-weighted binning F1:** chosen on purpose, so a tiny correct bin cannot outweigh
  a large plasmid.

Size-stratified recovery is on the companion branch. *Verified.*

**Q93. Are results stable under resampling?**
Cluster bootstrap intervals on every ranking score; rank robustness (PR #8). *Verified.*

**Q94. Null model and false-discovery rate?**
Sign-flip permutation on paired per-isolate differences, flipping whole clusters, with
Holm correction across all tool pairs. *Verified.*

**Q95. Missing values?**
Undefined metrics are blank, never 0, and excluded from means with their counts reported.
Failed runs on plasmid-bearing samples are 0, deliberately. Missing metadata is reported
(Q85). *Verified.*

## Part X. Research, publication and funding (levels 3–5)

**Q96. What kind of paper is this?**
A methods or software paper describing a benchmark. *Documented.*

**Q97. What would a reviewer challenge first?**
Truth independence and leakage, now tiered and screened; cohort size and species bias,
being expanded; and the lack of real-cohort results. *Documented.*

**Q98. What is the minimum pilot?**
One locked cohort (`public-v3`) run end to end, with every tool scored, the headline on
tier 1–2 truth and baselines beaten. *Open.*

**Q99–Q100 (users consulted; one-sentence advantage).**
*Open*: no user study is recorded. The advantage is measurement, not prediction (Q74).

**Q101–Q102 (phages, metagenomes, One Health).**
A separate, documented metagenomic track already scores community bins
(`docs/METAGENOMICS.md`). It is kept apart from isolate results. *Documented.*

## Part XI. Adversarial questions (levels 1–2)

**Q103. Which single result would most damage credibility, and was it tested?**
Rankings flipping under a reasonable change of filters, or a top tool not beating a
trivial baseline. Both are now measured on every run: rank robustness (PR #8) and
`beats_best_baseline` (*Fixed here*).

**Q104. An independent group gets a different result: then what?**
Compare the two run manifests (tool and database versions, every setting), the cohort
lock checksums, and the per-plasmid tables. These are designed to localise a
discrepancy. *Verified.*

**Q105. Is clustering driven by shared AMR genes?**
*Outside this benchmark:* PlasBench does not cluster, group, relate or phylogenetically place plasmids.

**Q106. Does performance on novel plasmids get reported honestly?**
Novel or marker-free truth plasmids are AMBIGUOUS and counted, not hidden. Tools are not
forced to call anything. The known-plasmid bias of marker-based labelling is stated.
*Documented.*

**Q107. Is the reference bias toward high-income-country plasmids inherited?**
Partly. Truth comes from deposited genomes, which skew the same way. Geography is
recorded where available, but not yet stratified (Q65). *Open.*

**Q108. What would convince an independent scientist that PlasBench is superior?**
That framing doesn't fit: PlasBench ranks tools; it doesn't compete with them. What
should convince is:
1. On a locked, provenance-graded cohort, the top tools beat trivial baselines with
   non-overlapping cluster-bootstrap intervals.
2. That ranking survives filter changes and tier restriction.
3. An independent group reproduces it from the manifest.

Items 1 and 2 are measured on every run. *Real-data result Open.*

## Parts XII–XIV. Viva sequence, review record, prioritisation

The five opening viva questions map to Q1, Q4, Q8, Q60 and Q10/Q25 above. In short:
- **Q1:** PlasBench's decision is method choice.
- **Q4:** relatedness is outside this benchmark.
- **Q8:** outside this benchmark; AMR placement is measured within an isolate.
- **Q60:** truth is provenance-tiered.
- **Q10/Q25:** novelty is not claimed; the screen is renamed.

To track answers, use the review-record template with these status labels. The level-1
blocking questions are all answered above, except those marked *Open* that need a
real-cohort run (Q1, Q22 in FAQ, Q98, Q108).

## Panel examination: rounds 1-5 and edge-case lab

The panel's questions, with what PlasBench now does. Decisions the developer recorded are
marked **Decision**. The implementation plan and the items not implemented are in
[PANEL_ALIGNMENT.md](PANEL_ALIGNMENT.md); the frozen parameters in
[PREREGISTRATION.md](PREREGISTRATION.md).

**Q-P0. What is PlasBench's input, core operation and output (1.1)?**
Reads (and optionally long reads) plus a complete reference of the same isolate in; each
tool's plasmid prediction scored against that reference; ranked leaderboards per track and
task, and an HTML report, out. Clustering-style questions are outside this benchmark.
*Documented.*

**Q-P1. Which labels count as truth (E.15)?**
**Decision:** Scheme 3, NCBI labels (`assigned_molecule_location_type`), pre-registered as
primary (`TRUTH_LABEL_SCHEME=ncbi`). The sequence report's SHA-256 and retrieval date are
written beside every label. Scheme 1 (every non-chromosomal replicon is a plasmid) and the
evidence scheme are re-ranked as sensitivity analyses, with Kendall's tau against the primary.
Every replicon's three labels are in `benchmark.label_schemes.tsv` and the report. Isolates
without an NCBI record are marked `not_applicable:<truth_source>`. In-database versus
not-in-database recovery is reported per tool (#12). *Fixed here.*

**Q-P2. A tool crashes or writes nothing (D6)?**
**Decision:** F1 = 0, counted in the ranking. An infrastructure failure (container or
command never started, full disk) is not the tool's fault: it is recorded as
`infrastructure_failure`, never scored, and rerun. Failed runs get `TOOL_RETRIES` retries and
every tool the same `TOOL_TIMEOUT_SECONDS`. *Fixed here.*

**Q-P3. A truth plasmid is assembled as a tandem dimer (D2)?**
`detect_dimers.py` compares the two halves; with `COLLAPSE_DIMERS=1` the monomer is scored and
the change listed in `truth.corrections.tsv`. *Fixed here.*

**Q-P4. A plasmid seen only in short reads is absent from the truth (D1)?**
Predicted sequence that does not map to the truth is never a false positive
(`unmapped_pred_bp`); plasmids without long-read support are flagged by depth. Laboratory
confirmation needs a wet-lab step. *Verified; wet lab Open.*

**Q-P5. NCBI labels conflict within an assembly (D3)?**
Contradictory sequence-report entries become `REVIEW` and stop stage 2 (#8). *Verified.*

**Q-P6. An integrated plasmid (D5)?**
The truth-label audit flags chromosome-labelled replicons that carry plasmid markers;
integration inside a chromosome is not called. The integrated-element stratum's thresholds
are `TO_FIX` in the pre-registration. *Partly; Open.*

**Q-P7. A region shared by two plasmids (D8)?**
Contigs aligning equally well to both are AMBIGUOUS (excluded, counted as shared length),
not multi-assigned. *Verified.*

**Q-P8. A multi-copy AMR gene (D9)?**
Curated AMR truth has one row per copy; placement matches copies by position. *Verified.*

**Q-P9. A tool's output format changes between versions (D10)?**
Every adapter has a fixture test and tool versions are recorded; run-time schema checks per
version are not done. *Partly.*

**Q-P10. Is an AMR gene placed on the right plasmid?**
`score_amr_placement.py`: per gene copy, correct or wrong plasmid (one-to-one bin matching),
shared or unassigned contig, or not recovered; replicon-type agreement as level 1; reported
per gene class (carbapenemase, ESBL, colistin, ...). *Fixed here.*

**Q-P11. No tool works on an isolate type (D11)?**
When the best expected F1 is below `RECOMMENDATION_MIN_EXPECTED_SCORE` (0.40) no tool is
recommended and the reason says so. *Fixed here.*

**Q-P12. A mixed or contaminated assembly (D13)?**
The advisory assembly QC gate (size, GC spread across long contigs) warns before
recommending and is scored like every other warning. *Fixed here.*

**Q-P13. Which tools were compared, and why did some not run (D15)?**
The report's "How every run ended" section counts every outcome per tool and lists the most
common reason for each skip or failure. *Fixed here.*

**Q-P14. What are the limits of the warnings (D16)?**
Each warning is scored by PPV, sensitivity and firing rate against failed recommendations;
where its validity limit applies (for example a cohort too small for outlier detection) the
report says "could not be applied". *Fixed here.*

**Q-P15. A query too short, or equally close to two references (3.3, 2.4)?**
The operational screen returns `insufficient_sequence` (under 1 kb, not compared) or
`ambiguous_between_references`. *Fixed here.*

**Q-P16. Were the scoring rules fixed before the results?**
`config/prereg.tsv` holds every decision; `freeze-prereg --write` locks it; the manifest and
report show the hash, the lock state, open `TO_FIX` items and any setting that departs from
the plan; `REQUIRE_PREREG=1` refuses to run otherwise. *Fixed here; freeze Open.*

**Q-P17. Does recommending per isolate beat using the single best tool?**
`evaluate_recommender.py`: leave-one-study-out regret, near-optimal and top-1 rates, gap
closed, and a `benchmark_only` verdict when the oracle gap is below 0.02. *Fixed here;
real-data result Open.*

**Q-P18. Is the permutation test robust to the choice of test?**
A Wilcoxon signed-rank p-value (exact for n ≤ 25) and an equivalence flag sit beside it. *Fixed here.*

**Q-P19. Does it transfer to an unseen genus, and is there a holdout?**
Leave-one-genus/phylum-out regret; `split=holdout` isolates are evaluated once only. *Fixed here.*

**Q-P20. Is a contig-level score reported?**
Yes, as a parallel layer: contig F1 and MCC by count and length, contig-level binning F1,
shared and unassigned lengths. Never the headline; not validated against a second scorer.
*Fixed here.*

**Q-P21. What was not adopted, and why?**
Plasmid-free isolates scored 0 in F1 (undefined there); summed contig length as the
headline recall denominator (contig layer only); a context model beyond the QC gate (needs
data); more than 100 in-house isolates (data collection). *Documented.*

**Q-P22. Pilot, orthogonal validation, temporal holdout, pre-registration publication
(E.9-E.13)?**
They need data collection and a study protocol. The database-date screen and in-database
split support a temporal analysis; the pre-registration file is ready to freeze. *Open.*
