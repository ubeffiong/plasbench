# Independent Scientific, Technical and Innovation Review — PlasBench

**Reviewed object:** PlasBench (repository snapshot, git HEAD `7ccaddd`, 185 commits, CHANGELOG "Unreleased" after v0.1.5)
**Review scope (agreed with the project lead):** PlasBench *as built*, plus an explicit gap analysis against the plasmid identity / PLSDB comparison / clustering / subcommunity / relatedness ambitions in the review brief.
**Stance:** sceptical and constructive. No advocacy. Every criticism carries a reason, a consequence and a recommendation.

---

## 0. Evidence basis and limits (read this first)

**Read in full or in the relevant part:** `README.md` (lines 1–1193 of 3037), `docs/METHODS.md` (to line 590), `docs/OPERATIONAL_SELECTION.md`, `docs/CONCEPT_NOTE.md` (to line 200), `docs/EXTERNAL_EVIDENCE.md`, `docs/SCENARIOS.md` (head), `python/classify_operational_plasmid.py`, `python/build_plasmid_reference_set.py`, `python/flag_database_overlap.py` (head), `test/test_classify_operational_plasmid.py`, `cohorts/public-v1.tsv`, `cohorts/public-v2.tsv` (summary), `cohorts/reference_plasmids/curated_accessions.tsv`, `config/tool_database_releases.tsv`, `config/config.sh` (scoring defaults), `scripts/05_score.sh` (minimap2 calls), `results_audit/`, `results_demo/`, candidate-discovery TSVs under `tmp/`.

**Executed:** `python -I test/test_classify_operational_plasmid.py` → all pass (note: uses a *faked* `mash`). `pytest` is not installed in this environment, so `test/test_aggregate.py` and the other ~130 test files were **not** run.

**Not audited line-by-line (reported as documented, not as verified):** `score_plasmids.py` (798 lines; only defaults and PAF handling inspected), `aggregate_results.py` (813 lines; bootstrap/permutation claims taken from METHODS.md), `make_truth.py`, all shell stages other than the minimap2 calls, the HTML report, the adapters, `recommendation_model.py`, README lines 1194–3037.

**No real-data benchmark results exist in the supplied folder.** `results/` and `data/` are empty; `results_audit/` (2 samples) and `results_demo/` are produced by *synthetic* tools named `good`, `leaky`, `shy`. If real runs exist elsewhere, every validation-dependent score below should be re-assessed against them.

**Citations** below are from memory of the established literature and the repo's own references. Verify each before publication; the Teixeira 2025 DOI is quoted from the repo and was not independently checked.

**Corrections to my own interim notes:** the curated reference set has **16** plasmids (not 17; I counted a header line). `public-v2` **does** contain African-origin isolates (22 of 32 rows); only `public-v1` lacks them.

---

## Part 1. Executive assessment

**What the tool is.** PlasBench is an open-source (GPL-3.0, single-author copyright) Ubuntu/WSL benchmarking framework. For each isolate it takes paired short reads and a complete long-read/hybrid reference, runs plasmid-reconstruction or -classification tools (mob_recon, Platon, plasmidSPAdes, gplas, geNomad, Plassembler, Hybracter, …), maps each tool's predicted-plasmid FASTA onto the reference with minimap2, and scores **per reference base** (TP = plasmid bases covered, FP = chromosome bases covered, FN = plasmid bases missed). Tools are ranked by mean F1 within input tracks (short / long / hybrid), with bootstrap CIs and paired permutation tests. A separate metagenomic bin-scoring track exists. An optional "operational" mode picks a tool for an unknown isolate and can run a Mash nearest-neighbour "known cluster / novel" call against a 16-plasmid reference set.

**What it is not.** It is not a plasmid identification, PLSDB-comparison, clustering, subcommunity, or relatedness-inference tool. Those are the brief's central objectives. The repo contains no PLSDB search, no community or subcommunity detection, no whole-plasmid alignment or synteny output, no backbone/accessory decomposition, and no relatedness grading.

**Overall assessment.**
1. The *benchmark core* is a careful, honest piece of engineering. Its design shows unusual awareness of how benchmarks mislead (abstention scored as F1 = 0, shared-sample ranking, bioproject-aware resampling, circularity guard for long-read truth, recall ceiling, database-overlap screen, explicit "never pooled across tracks"). That is its real strength.
2. It is **not yet scientifically demonstrated**: no real-data result is present, the headline metric has a structural optimism (filtered/unmapped predicted bases are never false positives), the leakage screen is inert until database dates are filled in, and the cohorts are small and taxonomically narrow.
3. The *Mash "known/novel" classifier* is the weakest component and the one closest to the brief's ambitions. It is unvalidated (tests use a faked `mash`), its reference set is 16 plasmids, and its threshold is mis-described as "≈ANI 95%". Under its own formula, **two equal-sized plasmids sharing only ~35% of their k-mers exactly would be called the same known cluster** (derivation in Part 5). It must not be presented as a relatedness or novelty method.
4. The concept note's framing (trustworthy plasmid research and AMR surveillance; African relevance) is ahead of the evidence in the folder.

**Most important findings (ranked).**
1. Scope mismatch between the review brief and the product; the product claims are narrower and mostly appropriate, the brief's are mostly unimplemented.
2. No real-data results; "implemented" ≠ "validated".
3. Mash classifier threshold semantics are wrong for mosaic and fragmented plasmids; "novel" is a statement about a 16-plasmid database, not about biology.
4. Precision is optimistic by design; ranking can be gamed by predicting repeat-rich or chimeric contigs that never retain an alignment.
5. Database-overlap leakage cannot be assessed until `database_release_date` is filled for every tool (all currently blank), and even then it is a date heuristic.
6. Selection bias: only isolates that *have* complete hybrid assemblies and matched reads can be truth; this under-represents exactly the hard, repeat-rich, low-resource isolates the project wants to serve.
7. A secret file (`.ncbi.env`, NCBI API key) sits in a OneDrive-synced folder; it is gitignored and untracked (good) but is still cloud-synced.

---

## Part 2. Understanding of the project

### 2.1 Workflow (as documented)

| Stage | Script | Action | Key choices |
|---|---|---|---|
| 0 | `00_setup.sh` | tool check | — |
| 1 | `01_download.sh` | NCBI reference + SRA reads | download estimate/confirm; checksums |
| 2 | `02_truth.sh` / `make_truth.py` | label each reference sequence PLASMID/CHROMOSOME | NCBI `assigned_molecule_location_type`; unclassified defaults to CHROMOSOME (counted and warned) |
| 3 | `03_assemble.sh` | fastp QC + SPAdes/Unicycler short-read assembly | optional difficulty descriptors |
| 4 | `04_run_tools.sh` | run each tool, adapters → standard FASTA (+bins/probabilities) | equal per-tool thread policy |
| 5 | `05_score.sh` / `score_plasmids.py` | `minimap2 --secondary=no -x asm5`, filters, interval merge, confusion matrix | pipeline defaults: length ≥ 200, identity ≥ 0.90, MAPQ ≥ 20, query coverage ≥ 0.20 |
| 6 | `06_aggregate.sh` / `aggregate_results.py` | per-track leaderboard, bootstrap CI, Holm-corrected permutation tests, recommendations, selection, database-overlap flags | ranking on mean F1 over shared samples |

### 2.2 Feature status ledger

| Feature | Proposed | Designed | Implemented | Unit-tested | Validated on real data | Evidence in folder |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Base-level P/R/F1 projection scoring | ✔ | ✔ | ✔ | ✔ (documented) | ✘ | demo/synthetic only |
| Per-track leaderboards, shared-sample rule, failure-as-zero | ✔ | ✔ | ✔ | ✔ (documented) | ✘ | CHANGELOG, METHODS |
| Cluster-aware bootstrap / permutation / Holm | ✔ | ✔ | ✔ | not run | ✘ | METHODS only |
| Per-plasmid recovery, bin matching, NMI/VI | ✔ | ✔ | ✔ | not run | ✘ | METHODS |
| AMR gene recall (needs curated truth) | ✔ | ✔ | ✔ | not run | ✘ | no curated `truth_amr.tsv` seen |
| Recall ceiling (scorable truth) | ✔ | ✔ | ✔ | not run | ✘ | METHODS |
| Database-overlap screen | ✔ | ✔ | ✔ | not run | **inert** (dates blank) | `tool_database_releases.tsv` |
| Long-read / hybrid tracks + circularity guard | ✔ | ✔ | ✔ | not run | ✘ | README §4.9 |
| Metagenomic bin scoring (BMock12 control) | ✔ | ✔ | ✔ | not run | partial negative control only | README, METAGENOMICS.md |
| Operational tool recommendation | ✔ | ✔ | ✔ | not run | ✘ (gates: ≥5 samples, ≥0.80 coverage) | OPERATIONAL_SELECTION.md |
| Mash known/novel classifier | ✔ | ✔ | ✔ | ✔ **with faked mash** | ✘ never run on real plasmids | test file |
| PLSDB search / comparison | brief only | ✘ | ✘ | ✘ | ✘ | PLSDB appears only as Plassembler/PLASMe DB provenance |
| Community / subcommunity assignment | brief only | ✘ | ✘ | ✘ | ✘ | absent |
| Relatedness grading with evidence | brief only | ✘ | ✘ | ✘ | ✘ | absent |
| Whole-plasmid alignment, shared/unique regions, backbone | brief only | ✘ | ✘ | ✘ | ✘ | absent |

### 2.3 Cohorts

- `public-v1`: 10 isolates; 9 *E. coli* + 1 *Salmonella*; 7 from one BioProject (PRJNA636382, UPEC); all tier A, hybrid truth; depth 50–315×.
- `public-v2`: 32 isolates; 17 *E. coli*, 6 *Salmonella*, 5 *Klebsiella*, 3 *Acinetobacter*, 1 *S. aureus*; 15 BioProjects; 22 tier-B rows with **blank** read depth, plasmid count and source study; origin labels include Egypt 9, South Africa 4, Nigeria 4, Tanzania 3, Kenya 2.
- Nigeria discovery run (`tmp/nigeria-discovery-20260901`): **0 accepted, 3 rejected** (assemblies declare no plasmid replicons). Real finding: the truth requirement itself excludes most Nigerian public genomes.

---

## Part 3. Scientific problem assessment

**The problem PlasBench actually addresses:** *Which plasmid-reconstruction method should a laboratory trust for short-read data of a given taxon?* This is real: published benchmarks disagree, tools are organism-dependent (the repo cites Teixeira et al. 2025, *Brief Bioinform*), and plasmid reconstruction from short reads is intrinsically limited (Arredondo-Alonso et al. 2017, *Microb Genom*).

**Challenges to the problem framing.**

1. **The question is narrowing in value.** As long-read sequencing becomes routine, short-read reconstruction matters mainly where long reads are unaffordable, which is precisely the resource-constrained setting the concept note targets, so the framing is defensible. But the long-read track has a structural problem: truth derived from long reads cannot independently score tools that consume the same reads (PlasBench recognises and blocks this). The remaining long-read cohort needs separate read sets or orthogonal truth, which are scarce. The scientifically interesting future problem (long-read plasmid *structure*) is the one the benchmark is least able to evaluate.
2. **The unit of evaluation may be wrong for the decisions users make.** Users ask "is this resistance gene on a plasmid, and which one?" That is an object-level question. The ranking metric is pooled base-level F1, which is dominated by large plasmids and by chromosome-contamination bases. PlasBench reports plasmid-level and AMR recall, but *ranks* on base F1. The consequence is a leaderboard whose order may not match the order a user would pick for their question. Test this empirically (Part 8).
3. **Too many problems at once.** The README covers isolate benchmarking, metagenomic bin scoring, operational recommendation, a candidate-quality ML dataset, a Mash novelty classifier, Galaxy/bioconda packaging, release governance and a 3,000-line manual. For a single-author project this is a scope risk: breadth is outpacing demonstrated evidence.
4. **The brief's problem (relatedness) is a different and harder problem** (homology among mosaic, recombining replicons; no ground truth; definitional disputes about plasmid taxonomic units). It should not be reached by growing the Mash bolt-on.

**Recommended precise problem statement.**
*"Quantify, with calibrated uncertainty and leakage controls, how accurately current tools recover plasmid sequence and individual plasmids from short-read isolate data, stratified by taxon and plasmid properties, using independently deposited hybrid/long-read references including African isolates."*
Everything else (metagenomics, operational selection, novelty) should be labelled exploratory until it has its own evidence.

---

## Part 4. Novelty assessment

| Level | Verdict | Reasoning |
|---|---|---|
| Conceptual | **None claimed, none present** | Benchmarking against a complete reference is standard. |
| Methodological | **Incremental** | Unifying classifiers and assemblers under one base-level projection metric; failure-as-zero + shared-sample ranking; bioproject-clustered resampling; recall ceiling from self-mapping windows; date-based DB-overlap flag. Each is sound; none is a new algorithm. Their *combination in a reproducible harness* is the contribution. |
| Computational | **None** | Interval merging and minimap2 are standard; no new complexity result. |
| Biological | **None demonstrated** | No biological finding is reported. |
| Operational | **Strongest claim** | One-command, containerised, provenance-locked benchmark with cohort locks, per-track reports and explicit refusal to score a tool on its own truth reads. |
| Public health | **Potential, not demonstrated** | Method selection for AMR labs is an enabling, indirect contribution; no surveillance intelligence is generated. |

**Compared with existing work.** PlasBench's *Mash known/novel call* copies the pattern of COPLA (Redondo-Salvo et al. 2020, *Nat Commun*) with a far smaller reference and none of its calibration, and overlaps functionally with MOB-typer/MOB-cluster (Robertson & Nash 2018, *Microb Genom*), PLSDB search (Galata et al. 2019; Schmartz et al. 2022, *NAR*) and mash-based screening. It adds no capability; it adds an uncalibrated duplicate. Published reconstruction benchmarks (Teixeira 2025 and earlier work) already compare many of the same tools; PlasBench differs in being a reusable harness rather than a one-off analysis.

**Strongest defensible novelty claim.** *"An open, provenance-locked, leakage-aware benchmarking harness that scores heterogeneous plasmid tools on a common per-base and per-plasmid basis, separates input tracks, and reports uncertainty that respects study dependence."* It becomes publishable as a *resource* only once real results exist (Part 13). It does not, today, support a claim of a new method or a biological discovery.

**Do not claim:** novelty of the known/novel classifier, any plasmid taxonomy, any relatedness inference, or "evidence-calibrated" in the sense of calibrated probabilities (the confidence score is a linear margin to a threshold).

---

## Part 5. Methodological assessment

### 5.1 Truth definition
- **Strength:** truth is independent of any benchmarked tool for NCBI-deposited and `simulated` rows; `self_assembled_hybrid` truth (Unicycler topology) is correctly barred from long-read scoring.
- **Weakness A — label source.** Plasmid vs chromosome comes from the submitter's `assigned_molecule_location_type`. Chromids, secondary chromosomes, integrated plasmids/ICEs and mislabelled records are not examined. *Consequence:* a tool that correctly flags a megaplasmid-like chromid is penalised as FP. *Recommendation:* run an independent audit of truth labels (replicon markers, size, gene content) and report disagreements per sample; exclude or flag ambiguous replicons.
- **Weakness B — "complete" is not "correct".** The reference is itself an assembly (hybrid or long-read) that may have collapsed repeats, missed small plasmids, or merged replicons. METHODS.md acknowledges missed small plasmids. *Recommendation:* require independent read-support of every truth replicon (long-read depth/uniformity) and tier truth quality in outputs.
- **Weakness C — survivorship bias.** Only isolates with finished hybrid assemblies and matched public short reads enter. Repeat-rich, IS-dense, multi-copy-similar-plasmid isolates are the ones least likely to be closed, so the benchmark is biased towards easier genomes and will overstate performance in real surveillance data. This is not fixable in software; it must be *stated* and bounded (compare assembly-graph difficulty descriptors against surveillance isolates).

### 5.2 Scoring metric
- **Optimism by construction.** Predicted bases with no *retained* alignment (unmapped, or removed by the length/identity/MAPQ/query-coverage filters) are neither TP nor FP. METHODS.md states this explicitly. A tool that emits large chimeric or repeat-rich contigs that fail the MAPQ ≥ 20 filter pays no precision penalty. `strict_precision` exists but is supplementary and approximate (query bp divided with reference bp). *Consequence:* ranking can be moved by exactly the output a user would distrust. *Recommendation:* make a sensitivity analysis mandatory in every release: re-rank under strict precision and under MAPQ ∈ {0, 20, 30}, identity ∈ {0.80, 0.90, 0.95}; publish the rank stability (e.g. Kendall τ).
- **Repeats and primary-only mapping.** With `--secondary=no`, a segment shared by plasmid and chromosome (IS, transposon) is assigned to one placement arbitrarily. At MAPQ 20 these segments are discarded, which both caps recall (the `recall_ceiling` diagnostic measures this) and hides contamination. The window-based ceiling is "conservative for repeats longer than the window and blind to much shorter ones" (METHODS.md). Honest, but the diagnostic is not wired into ranking.
- **Pooled base-level F1 favours large replicons.** A 150 kb plasmid outweighs five 5 kb cryptic plasmids 30:1 in F1. *Recommendation:* report macro-averaged (per-plasmid) and size-stratified recovery alongside, and show whether rank order is stable.
- **`asm5` preset.** Appropriate for same-isolate comparison; the scoring identity filter of 0.90 is lenient relative to `asm5`'s intent. Document why 0.90.
- **Multi-copy and multimeric plasmids.** Interval merging means duplicate or multimer predictions earn no extra TP and no penalty (`redundant_pred_bp` is diagnostic only). A multimer-collapsing tool and a multimer-emitting tool tie.

### 5.3 Statistics
- Bootstrap over clusters and sign-flip permutation with Holm correction are the right family of tools for correlated samples. **But** the pipeline minimum is 5 independent clusters; `public-v1` has few (≈4 BioProjects for 10 isolates, 7 in one), so intervals are either unavailable or extremely wide. *Consequence:* the headline statement "tool A beats tool B" is likely unsupported at v1 scale. `public-v2` (15 BioProjects) is the minimum credible panel; with 17/32 *E. coli* it still cannot support species-generalised claims.
- Ranking on a "shared-sample" subset can shrink to the weakest tool's coverage; the `own_samples_no_overlap` fallback silently changes the comparison basis (it is flagged in a column, which is good).
- Leave-one-study-out recommendation validation "withholds an assessment when cohort diversity is inadequate". That is the correct behaviour, and with current cohorts it will often withhold.

### 5.4 Leakage and circularity
- Most evaluated tools use databases built from RefSeq/PLSDB plasmids, i.e. often the same genomes used as truth. `flag_database_overlap.py` compares truth release date with tool database release date. **Every `database_release_date` cell is blank** (16 of the 17 tool rows use a database; plasmidSPAdes does not), so every database-using sample × tool pair is `unknown` and `mean_f1_after_database` is empty. A date screen is also coarse: absence of the exact genome from a database does not mean absence of near-identical plasmids (plasmid sequences are highly redundant). *Recommendation:* fill the dates, then add a *sequence-level* screen (Mash/containment of truth plasmids against each tool's database where available) and report F1 stratified by maximum similarity to the tool's reference database. That is the leakage question that matters.
- Long-read track circularity is correctly handled by design; its practical effect is that few samples qualify.

### 5.5 The Mash known/novel classifier (`classify_operational_plasmid.py`)

What the code does: for each predicted FASTA *record*, take the minimum Mash distance to 16 reference sketches; if D ≤ 0.05 **and** the reference's single-linkage cluster has ≥ 2 members → `known_cluster`, else `novel`; confidence is `1 − D/0.05` or `min(1,(D−0.05)/0.05)`.

Defects, in order of seriousness:

1. **Threshold semantics are wrong for plasmids.** Mash distance is `D = −(1/k)·ln(2j/(1+j))` (Ondov et al. 2016, *Genome Biol*), with k = 21 by default. For two equal-length sequences that share a fraction *s* of their k-mers exactly, `2j/(1+j) = s`, so `D = −ln(s)/21`.
   - s = 0.80 (80% shared, 20% different accessory) → D ≈ **0.011** → "known cluster".
   - s = 0.50 → D ≈ **0.033** → "known cluster".
   - s ≈ **0.35** → D ≈ 0.050 → the threshold.
   So the "roughly ANI ≥ 95%" gloss is incorrect: D is an *evolutionary distance under a point-mutation model* and loses that meaning with insertions, deletions, rearrangements and horizontally acquired blocks, which are the defining features of plasmid evolution. This is exactly the brief's "80% shared backbone, different accessory" case, and the classifier would call them the same cluster with confidence ≈ 0.78.
2. **Fragmentation is penalised as novelty.** A contig that is 100% identical to a *fraction f* of a reference plasmid has j = f, so D = −ln(2f/(1+f))/21. D ≤ 0.05 requires f ≳ **0.21**; f = 0.15 gives D ≈ 0.064 → "novel". A short-read assembly splits plasmids into many contigs, each classified independently, so fragments of a perfectly known plasmid can be called *novel*. The output is per record, not per plasmid, and nothing aggregates records into plasmid-level calls.
3. **"Novel" = "not within 0.05 of one of 16 references".** The reference set is 16 plasmids (*E. coli* 4, *Salmonella* 3, *Klebsiella* 3, *A. baumannii* 3, *S. aureus* 3), chosen as canonical models. No *Enterococcus*, *Pseudomonas*, *Vibrio*, *Shigella*, *Proteus*, Gram-positive diversity, and no plasmid chosen to represent African isolates. Absence from this set says almost nothing about biological novelty (brief principle 8). With so few references, many are likely singletons at 0.05 single-linkage, and `--min-cluster-members 2` then converts even a very close hit into "novel". This is a testable hypothesis: build the set and count singleton clusters.
4. **Single-linkage chaining** merges families through shared transposon/IS blocks; fine at 16 references, a design flaw if the set scales to thousands. There is no cluster-stability analysis.
5. **Sketch-size mismatch (confirmed by code audit).** References are sketched with `-s 10000` (`build_plasmid_reference_set.py:163,200`); queries are sketched with no `-s` (`classify_operational_plasmid.py:110`), so Mash's default of 1000 applies. Mash compares sketches of different sizes using the smaller, so effective resolution is set by the query sketch. The behaviour of the installed Mash version has not been tested here, but the code-level mismatch is certain.
6. **Ignored Mash outputs.** The code parses only the first three columns; the p-value and shared-hash fraction are discarded, so a distance supported by few shared hashes is treated like one supported by many.
7. **Confidence is not a probability.** It is a linear margin to an uncalibrated threshold; two outputs of 0.9 are not comparable across plasmid sizes.
8. **No validation.** The test file monkeypatches `subprocess.run` and `shutil.which`; the end-to-end "known_cluster" test feeds a fabricated `0.0100` distance line. These tests verify control flow, not biology. I executed them: they pass.

**Verdict on the component:** scientifically unsupported as a novelty/relatedness method. Either (a) remove it from claims and docs, (b) replace it by calling an established tool (MOB-typer/MOB-cluster, COPLA, PLSDB search) and recording its output with versions, or (c) invest in a real, validated method (Part 12).

---

## Part 6. Workflow and architecture assessment

**Strengths.** Numbered idempotent stages with reuse; run manifests and image digests; cohort lock files with SHA-256; download estimates and confirmations; per-tool thread equality policy; per-tool `skipped/failed/completed` status that feeds the scoring rules; adapters isolate tool-specific formats; truth-derived descriptors are barred from the live recommendation model (explicitly in code). The scorer is stdlib-only, which helps reproducibility.

**Weaknesses.**
1. **Bash-orchestrated, Linux-only.** Windows users need WSL2. For the stated African laboratory audience this is a real adoption barrier (admin rights, 5.6 GB of databases, 30–90 min install, ≥ 8 GB RAM; README reports SPAdes needing 7.8 GB for k-mer counting on a 250× isolate). The Docker route mitigates but does not remove it.
2. **Heavy surface area.** 133 files in `test/`, 295+ Python/shell/Markdown files, a 3,037-line README. Maintainability for a single maintainer is a risk, and the README's "copy and paste every command" guarantee is hard to keep true.
3. **Hidden coupling between stages.** Stage 2 defaulting unclassified sequences to CHROMOSOME silently inflates scores if wrong (the README tells users to watch the "(0 defaulted)" counter manually). That should be a hard failure by default, not a human check.
4. **Early errors propagate.** A wrong truth label (Part 5.1) flows unchanged into every tool's TP/FP, the recommendation gates and the candidate-quality dataset. There is no per-sample "truth confidence" carried downstream.
5. **Recommendation machinery outpaces its evidence.** Stratified recommendations by organism, truth technology, origin, plasmid size band and depth band need ≥ 5 samples and ≥ 0.80 coverage per stratum. With 10–32 isolates, most strata will be empty; the code withholds, which is right, but the existence of an optional ridge-regression recommender (`RUN_RECOMMENDATION_MODEL`) on such data is an overfitting hazard.
6. **Reproducibility gaps.** Database release dates blank; MOB-suite DB lives inside the conda environment; Platon DB URL "periodically changes"; an `environment.yml` lock is regenerable but not shown pinned in the artefacts reviewed.
7. **Scalability.** Scoring is near-linear; the bottleneck is per-isolate assembly and tools (30–60 min/isolate per README, an *unmeasured* claim). The classifier recomputes against a static sketch so it is cheap, but the reference clustering is all-vs-all Mash (quadratic) and single-link.

**Logical order.** Stages are in a defensible order. One missing step: a truth-quality gate between stage 2 and stage 5 (replicon audit, read-support check).

---

## Part 7. Edge-case and failure-mode assessment

**Columns.** *PlasBench scoring* = what the benchmark does with a tool's output for that scenario. *Mash classifier* = what the novelty classifier would do. *Basis*: **D** documented, **I** inferred from code/design, **U** untested. Cause: B biological, C computational, A algorithmic, D data.

| # | Scenario | PlasBench scoring | Mash classifier | Cause | Needs |
|---|---|---|---|---|---|
| 1 | Multiple plasmids per isolate | Scored per base; per-plasmid recovery and bin matching (D) | Per record; no per-plasmid aggregation (I) | A | validation |
| 2 | Highly similar co-resident plasmids | Interval merge: duplicates not penalised, ambiguous placement possible (D); MAPQ 20 may drop shared regions | Records may hit the same reference; cannot split (I) | A/B | method for multi-copy truth |
| 3 | Very large plasmids | Dominate pooled F1 (I) | Long refs vs fragment → D inflated (I) | A | macro-metrics |
| 4 | Small cryptic plasmids | Tiny weight in F1; may fail query-length/depth; not highlighted (I) | Query shorter than k-mer window may be dropped by Mash → `insufficient_reference` (D) | A/D | per-plasmid stratified reporting |
| 5 | Highly divergent plasmids | Fails `asm5`/identity 0.90 → unmapped, not FP (D) | → "novel" (correct, but see 6) | A | sensitivity analysis |
| 6 | Novel plasmid absent from databases | Tool-dependent; leakage flag inert (D) | "novel" for almost anything with 16 refs; not evidence of novelty (I) | D | larger/validated reference or drop |
| 7 | Incomplete assemblies | Scored by recall bands; cannot tell novel from incomplete (I) | Fragment looks novel (I) | A | per-plasmid aggregation, completeness evidence |
| 8 | Fragmented plasmid | Base score unaffected by splitting (D, stated); bin split metrics exist | Each fragment classified independently (I) | A | record-to-plasmid grouping |
| 9 | Circular vs linear | Circular truth recall exists; closure **not** inferred (D) | Ignored | A | closure evidence from graph/read support |
| 10 | Extensive IS elements | MAPQ 20 discards repeated IS → hidden contamination and recall ceiling (D) | IS-rich records pulled to arbitrary references (I) | B/A | repeat-aware metric |
| 11 | Transposons / integrons | Same as 10 | Shared Tn blocks can link unrelated plasmids (I) | B | backbone/accessory decomposition |
| 12 | Many AMR genes | AMR recall only with curated truth; none present in folder (D) | Gene content unused (D) | D | curated AMR truth |
| 13 | Same AMR gene, different backbones | Not assessed | Gene unused → not called related by gene; may be linked via shared Tn (I) | B | relatedness module if desired |
| 14 | Mosaic plasmids | Base score ok | One nearest reference only; s ≥ 0.35 shared → "known" (I) | A | multi-assignment method |
| 15 | Recombination / rearrangement | Not detected by scoring (a structural-variant script exists, not validated) | D loses meaning (I) | A | alignment-based synteny |
| 16 | Plasmid–chromosome integration | Truth label ambiguous; either FP or FN (I) | n/a | B/D | truth audit |
| 17 | Chromosome called plasmid | FP counted, unless repeat → MAPQ-filtered, uncounted (D) | May receive a "known" hit (I) | A | strict precision in ranking |
| 18 | Contaminated reads | Unmapped bp not FP (D); `off_truth_pred_bp` separate (D) | May be called novel (I) | D | contamination screen before scoring |
| 19 | Low-depth long reads | Depth ladder exists for short reads; long-read analogue unseen | n/a | D | extend ladder |
| 20 | Hybrid assemblies | Hybrid track separated (D) | n/a | — | validation |
| 21 | Structural rearrangements | Invisible to base-level F1 (D caveat) | Invisible | A | structural concordance metric |
| 22 | Different replicons, high similarity | Not assessed | Clusters by k-mers, ignores replicons (D) | B | replicon-aware layer |
| 23 | Same replicon, different backbones | Not assessed | Ignored (D) | B | same |
| 24 | Incomplete reference matches | Truth incomplete → penalises correct tools (D caveat) | Size asymmetry (I) | D | containment measure |
| 25 | DB duplication / inconsistent annotation | Leakage unscreened at sequence level (I) | Curated list, no dedup check (U) | D | redundancy audit |
| 26 | Different species | Organism stratification, underpowered (D) | 5 species only | D | broader reference |
| 27 | Geographically distant | Origin column; cannot test geography effects at n=32 (I) | none | D | larger cohort |
| 28 | Different time points | No temporal evaluation; release-date screen only | none | D | temporal hold-out |
| 29 | Shared conserved backbone only | Not assessed | Could be "known" at s ≥ 0.35 (I) | A | backbone-aware method |
| 30 | Shared accessory resistance region only | Not assessed | Could cause false links for small plasmids/islands (I) | A | local-vs-global alignment evidence |

**Additional failure modes discovered in the implementation.**
- **A31.** Stage 2 default-to-CHROMOSOME: unclassified truth plasmids become *FN for tools that find them and FP for correct calls*. Mitigation exists only as a printed counter.
- **A32.** `--min-cluster-members 2` with a mostly singleton reference set turns near-exact matches into "novel" (hypothesis, testable).
- **A33.** Sketch-size mismatch between reference and query (verify).
- **A34.** Mixed `alternate_paired_runs` columns and 22 `public-v2` rows with blank depth/plasmid count: ranking/stratification code must tolerate blanks; unverified.
- **A35.** Failure-as-zero treats a *crash caused by the environment* (e.g. 7 GB RAM cap) as tool inaccuracy. The README documents a 250× isolate failing SPAdes under a 7 GB cap; that is infrastructure, not method quality. Distinguish `failed:resource` from `failed:tool`.

---

## Part 8. Validation and benchmarking assessment

**What must be shown before any claim is trusted** (computational validity first, biological validity second).

### 8.1 Analytical validation of the benchmark itself (the benchmark is also a measurement instrument)
| Question | Experiment | Metric |
|---|---|---|
| Does the scorer reproduce known answers? | Synthetic ground-truth cases with analytically computable TP/FP/FN (several exist in the demo) plus adversarial cases: chimeric contigs, repeats, multimers, truncated plasmids | exact match |
| Is the ranking robust to scoring choices? | Re-rank under MAPQ/identity/qcov grids, strict precision, per-plasmid macro-F1 | Kendall τ, top-k stability |
| Does an independent scorer agree? | Cross-check against PlasEval or the BLAST-based pipeline (a comparison script exists; METHODS says it uses a *proxy* F1) | agreement of ranks, not of absolute F1 |
| Are truth labels right? | Independent audit: replicon markers, size, gene content, read support | label disagreement rate per sample |
| Is the CI honest? | Simulation: resample from a known generating process with clustered samples; check coverage of the 95% CI | empirical coverage |

### 8.2 Real-data performance
- Run `public-v2` (not v1) for every default tool; publish per-sample tables, CIs with `n_independent_clusters`, and the ranking-stability results above.
- Add **negative controls**: plasmid-free isolates (metrics `isolate_specificity`, `chromosome_fp_bp`) — the framework supports them, but no plasmid-free isolates are in the cohorts reviewed.
- Add **positive controls with known hard structure**: IS-rich multi-plasmid *Klebsiella*/*Acinetobacter*, co-resident near-identical plasmids.

### 8.3 Leakage-controlled comparison
1. Fill all database release dates.
2. Compute max similarity of each truth plasmid to each tool's reference database; stratify F1 by similarity band (≥99%, 95–99%, <95%).
3. Report F1 on "after-database" and "low-similarity" subsets as the *primary* generalisation claim.
4. Include held-out BioProjects and, ideally, newly sequenced isolates (African) that cannot be in any database.

### 8.4 Validation of the Mash classifier (only if retained)
- Positive/negative sets from PLSDB/RefSeq with known family membership (e.g. incompatibility group, PTU-like assignments from COPLA); evaluate with **ARI, NMI, purity, completeness** against an independent reference partition, *and* with pairwise precision/recall on same-family/different-family pairs.
- Stress sets: fragmented plasmids at fractions 10–100%; mosaics built by block exchange; equal-size pairs at controlled shared fractions (0.2…1.0) to show the s ≥ 0.35 effect empirically.
- Calibration: reliability curves for the confidence score; otherwise rename it.
- Compare to MOB-typer cluster codes and COPLA on the same queries.

### 8.5 External validation
Independent isolates from different sequencing platforms, species and countries; AMR-positive and AMR-negative; at least one laboratory-confirmed plasmid structure (PCR/long-read closure) to separate *computational* concordance from *biological* correctness. The repo's `ORTHOGONAL_VALIDATION.md` and evidence-import features create the right place to record that, but no laboratory evidence is present.

---

## Part 9. Results and interpretation assessment

**What outputs exist and whether they answer the question.**
- *Leaderboard + per-sample + per-plasmid recovery + diagnostics* answer "which tool recovers more reference sequence." They do **not** answer "is this particular candidate a real, complete, closed plasmid?", and the docs say so (`requires_confirmation`). Positive, honest design.
- *Interpretability:* plain-language metric explanations, graded bands (≥50%, ≥90%, complete circular), and negative-control metrics are good. Risk: too many metrics may obscure the one decision; the README itself warns that `mean_f1` and `mean_plasmid_recall` "are very different numbers".
- *Uncertainty:* CIs, permutation tests, "n < 5" suppression are good. But at current cohort sizes the output will mostly say `not_assessed`, and users may misread blanks.
- *Absence vs evidence of absence:* handled explicitly for undefined metrics (blank, never 0), and for `insufficient_reference`. Not handled for "novel".
- *Calibration:* none of the confidence-like values (classifier confidence, recommendation scores, candidate quality function) is calibrated; the candidate-quality function is described as "a reproducible prioritisation, not a biological truth oracle", which is accurate.
- *For the brief's relatedness questions:* the outputs cannot answer *why two plasmids are related*. There is no pairwise matrix, whole-plasmid alignment, shared/unique region map, backbone, or gene-content comparison.

**Recommended interpretable outputs, only if relatedness is pursued** (each answers a specific decision): pairwise containment *and* Jaccard (so size asymmetry is visible); alignment coverage of the shorter plasmid; shared-vs-unique region map; replicon/relaxase profile; AMR-gene context windows; explicit relationship class with evidence and "unresolved" as a legitimate output.

---

## Part 10. Practical usefulness and use cases

| Persona | Verdict |
|---|---|
| Bioinformatician (method choice) | **Best use case.** Reproducible harness and honest limitations; adopt once real results exist. |
| Microbiologist / lab scientist | Moderate. Can pick a tool and see failure modes, but WSL/Linux, 5.6 GB databases and hours per isolate are demanding; the 11-step manual is thorough but long. |
| AMR researcher | Moderate-low today. AMR-gene recovery needs curated truth, none present; plasmid-level recovery is the relevant output. |
| Epidemiologist | **Low.** No cross-isolate comparison, no relatedness, no temporal analysis. Study-dependence handling helps cohort statistics, not epidemiology. |
| Public health institution | **Low-moderate, indirect.** Can inform which pipeline to adopt; yields no surveillance intelligence and is explicitly not diagnostic. |
| Non-computational researcher | Moderate if the HTML report works as described (not inspected); the command-line install is a barrier. |
| Programme implementer | Moderate. Docker/Galaxy/bioconda packaging helps; single-maintainer sustainability and regular DB/tool refresh are unresolved. |
| Funder | Moderate-low for science today; moderate for infrastructure and capacity-building (Part 14). |

**Strongest use case:** choosing a short-read plasmid reconstruction workflow for a given taxon with explicit uncertainty. **Weakest:** anything involving relatedness, transmission or surveillance. **Demonstrated vs potential:** nothing has been demonstrated on real data in the folder; all applications are potential.

**Distinguish relatedness, association and transmission.** PlasBench produces none of these. Any future relatedness module must state that sequence similarity ≠ common ancestry, shared AMR gene ≠ plasmid transmission, and shared replicon ≠ same plasmid; transmission needs epidemiological and temporal data in addition to genomic evidence.

---

## Part 11. Risk assessment

| Domain | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Scientific | Rankings reflect scoring artefacts (unmapped = no FP; repeats filtered) | High | High | Mandatory sensitivity analysis; strict precision in ranking |
| Scientific | Leakage inflates database-based tools | High | High | Fill dates; sequence-level similarity strata |
| Scientific | Survivorship bias in cohorts | High | Medium | State; add difficulty descriptors; add hard isolates |
| Scientific | Truth mislabels (chromids/integrated plasmids) | Medium | High | Independent audit |
| Scientific | Classifier misread as relatedness/novelty | Medium | High | Remove or relabel; validate |
| Biological | Over-interpretation of "known cluster" as transmission | Medium | High | Evidence-bound language, disclaimers |
| Computational | Mash sketch-size mismatch; chaining; small-reference artefacts | Medium | Medium | Fix, test, document |
| Computational | Environment failures scored as tool failures | Medium | Medium | Separate failure classes |
| Operational | Linux/WSL, large downloads, RAM needs | High | Medium | Pre-built container, cloud/Galaxy path, lighter minimal config |
| Operational | Single-maintainer bus factor; large doc/test surface | High | High | Co-maintainers, scope freeze, CI |
| Implementation | Secret (`.ncbi.env`) in OneDrive-synced folder | Medium | Medium | Move out of synced path; confirm the key is rotatable; keep gitignored |
| Governance | GPL-3 with personal copyright and an IHVN acknowledgement that "does not imply institutional ownership" may complicate institutional adoption and funding | Medium | Medium | Clarify IP/affiliation with IHVN and funders before applying |
| Reputational | Concept note presents African relevance while the first pilot shows 0 accepted Nigerian candidates | Medium | Medium | Report the finding as a result; fund truth generation (long-read sequencing of local isolates) |

---

## Part 12. Recommendations

### Critical (before scientific claims can be trusted)
1. **State the scope plainly in README/concept note:** PlasBench benchmarks reconstruction tools; it does not identify, cluster or relate plasmids. Move the "novel-vs-known" feature to an "experimental, unvalidated" section.
   *Reason:* brief and product diverge. *Consequence:* funders/users will assume capabilities that do not exist. *Fix:* documentation change only.
2. **Produce and publish real-data results** (`public-v2`, all default tools) with CIs, `n_independent_clusters`, per-sample tables and the run manifest.
   *Reason:* nothing is demonstrated. *Consequence:* any claim is unsupported. *Fix:* run and archive (Zenodo, as GOVERNANCE.md already intends).
3. **Make the ranking robust to scoring choices:** include strict precision/ceiling-adjusted recall/macro-per-plasmid recovery and a stability analysis in every release.
   *Reason:* filtered/unmapped bases are not FP. *Consequence:* rank manipulable by chimeric/repeat output. *Fix:* script the sensitivity grid in stage 6.
4. **Fill `database_release_date` for every tool and add a sequence-similarity leakage stratification;** until then label database-based tool scores "leakage unassessed" in the report.
   *Reason:* inert screen. *Consequence:* inflated generalisation claims.
5. **Fix, validate or remove the Mash classifier.** Minimum: correct the ANI gloss (it is wrong for mosaics and fragments), sketch query and reference identically, parse p-value/shared hashes, aggregate by plasmid not by record, rename `novel` to `no_close_match_in_reference` and the confidence field to `distance_margin`. Preferably replace with an established tool's output.
   *Reason:* Part 5.5. *Consequence:* spurious "known cluster" and "novel" calls.

### High priority (research-grade maturity)
6. Independent audit of truth labels and truth-replicon read support; add per-sample truth-confidence carried to scoring.
7. Hard-fail (not warn) on stage-2 defaulted sequences unless explicitly overridden.
8. Distinguish resource failures from tool failures in failure-as-zero.
9. Broaden and balance the cohort: cap *E. coli* share, add *Enterococcus*, *Pseudomonas*, *Vibrio*, Gram-positive and African clinical/veterinary/environmental isolates; fill the blank depth/plasmid-count/study fields in the 22 tier-B rows; report the Nigerian finding (0 accepted) as a data-gap result.
10. Add plasmid-free negative controls and hard-structure positive controls to the released cohort.
11. Validate scorer against an independent evaluator (PlasEval or equivalent) and with simulation-based CI coverage checks.
12. Move `.ncbi.env` out of the OneDrive path; confirm it is rotated if it has ever synced or been shared.
13. CI already exists (`.github/workflows/ci.yml`: shellcheck, `plasbench test`, demo, build, container). Extend it so a job installs real minimap2 and mash and runs golden tests; today the `--no-deps` install means no real aligner or sketcher ever runs in CI.

### Medium priority (usability, scalability, optimisation)
14. Measure runtime and peak memory per tool/sample and publish them (the stage already records them); replace "30–60 min per isolate" with measured percentiles.
15. Incremental re-scoring when databases or tool versions change (scoring is cheap; cache keys should include tool and database versions).
16. Reduce documentation and feature surface: freeze new features; split README into a short quick-start plus reference docs.
17. Provide a minimal pre-built container/cloud notebook route for laboratories without Linux administration.
18. Long-read track: add a long-read depth ladder and document which samples qualify and why.

### Future development (optional, outside current scope)
19. If relatedness is desired: build on existing methods rather than a new heuristic, e.g. containment + alignment-coverage similarity, backbone/accessory decomposition from replicon/relaxase/core genes, community detection on the similarity network with stability analysis, multi-assignment for mosaics, explicit "unresolved" class, validated against curated plasmid taxonomic units. Treat as a separate project with its own validation.
20. Temporal and geographic comparison modules only after relatedness is validated.

---

## Part 13. Research and publication potential

**Credible paper type:** a *resource/benchmark* paper (e.g. *Briefings in Bioinformatics*, *NAR Genomics and Bioinformatics*, *Microbial Genomics*, *GigaScience*; confirm fit with each journal's scope). **Not credible today:** a method paper on plasmid relatedness/novelty.

**Research questions it could answer.**
1. How much do plasmid-reconstruction rankings change with scoring conventions (unmapped handling, MAPQ, per-plasmid vs per-base)?
2. How much of reported tool accuracy is attributable to database overlap?
3. Do tool rankings generalise across taxa and across African versus non-African isolates?
4. What fraction of truth plasmid sequence is intrinsically unscorable (repeat ceiling) per taxon?
5. How does survivorship (complete-assembly-only) bias distort benchmarks?

**Proposed manuscript structure.** (1) Background and benchmark pitfalls; (2) Framework design, truth definition and tracks; (3) Scoring and uncertainty with sensitivity analysis; (4) Cohorts and curation incl. the Nigerian data-gap result; (5) Results: per-tool performance, rank robustness, leakage-stratified performance; (6) Failure modes and recommendations; (7) Limitations; (8) Availability/reproducibility (manifests, Zenodo DOIs).

**Publication readiness: low** (infrastructure ready; results, validation and independent comparison absent). The sibling published benchmark (Teixeira 2025) raises the bar: a new paper must add something it does not, most plausibly leakage stratification, rank-robustness analysis, and African cohort data.

---

## Part 14. Funding and implementation readiness

| Criterion | Assessment |
|---|---|
| Scientific significance | Moderate (method choice for AMR labs); not transformative |
| Innovation | Low-moderate; engineering and rigour, not new science |
| Feasibility | High (software exists and is extensive) |
| Technical maturity | Mid: broad implementation, little demonstrated evidence |
| Implementation readiness | Pilot-ready for software; not ready for operational reliance |
| Scalability | Limited by assembly/tool runtime and per-isolate manual curation |
| Cost-effectiveness | Good if infrastructure is reused; risk of continued feature spend |
| Open science | Strong (open licence, locks, manifests) |
| Sustainability | Weak: single maintainer, large surface area, personal copyright |
| Partnerships/capacity | Good fit with IHVN/African AMR programmes; needs explicit institutional agreements |

**Funder questions.**
1. *Would I fund this?* Conditional on a funded pilot that produces the Part 12 critical items; not as currently evidenced.
2. *What would make me reject it?* A proposal that markets relatedness/surveillance capabilities, or that presents the Mash call as novelty detection.
3. *Strongest competitive advantage?* Reproducible, leakage-aware, extensible harness with African-isolate focus.
4. *Greatest scientific weakness?* No demonstrated real-data results plus metric optimism (Part 5.2).
5. *Missing evidence?* Real runs; rank-robustness; leakage stratification; truth audit; independent scorer agreement; laboratory-confirmed structures.
6. *First pilot should demonstrate:* a full `public-v2` run for ≥ 6 tools, with sensitivity and leakage analyses, plus a small set of newly sequenced Nigerian isolates with long-read truth.
7. *Minimum viable research-grade product:* the benchmark core (stages 0–6) + short-read track + cohort lock + sensitivity/leakage reports + CI-tested scorer; everything else off by default and labelled experimental.
8. *Defer:* metagenomics beyond the negative control, recommendation model/ridge regression, candidate-quality ML dataset, novelty classifier, Galaxy expansion, any relatedness work.

**Funding-readiness: low-to-moderate.** Suitable for a small, tightly scoped pilot or capacity-building grant, not for a major investment in a scientific tool.

---

## Part 15. Expert examination questions (for the developer)

Answers will change the scores; unsupported assertions will not be accepted.

**Scope and claims**
1. The concept note says PlasBench helps "AMR surveillance". Which surveillance decision does a base-level F1 leaderboard change, and what evidence shows it would?
2. Why is the Mash known/novel classifier in the repository at all, given MOB-typer, COPLA and PLSDB search? What does it do that they do not?

**Metric and truth**
3. Predicted bases that fail the MAPQ ≥ 20 filter are not counted as false positives. Have you re-ranked the tools with strict precision? How many ranks change?
4. How many truth plasmids in `public-v1/v2` contain IS or transposon content that makes them unscorable? What is the per-sample `recall_ceiling` distribution?
5. How do you know the `assigned_molecule_location_type` labels are right for all 32 distinct truth isolates (`public-v2` already contains the 10 `public-v1` isolates)? Has anyone audited chromids/integrated plasmids?
6. Pooled F1 weights a 150 kb plasmid thirty times a 5 kb plasmid. Does the rank order survive macro per-plasmid scoring?
7. Isolates with finished hybrid assemblies are not representative of surveillance isolates. How do you bound the resulting optimism?

**Leakage and generalisation**
8. Every `database_release_date` is blank. What fraction of truth plasmids are within 99% similarity of each tool's reference database?
9. What is each tool's F1 on isolates sequenced after its database was built?
10. The Nigerian discovery found 0 acceptable candidates. What is the plan for truth generation, and who will fund long-read sequencing?

**Statistics**
11. With ≈4 BioProjects in `public-v1` and a minimum of 5 clusters, what does the report say? Which statement in the concept note is supported at v1 scale?
12. Has CI coverage been checked by simulation with clustered data?

**Classifier**
13. Under your formula two equal-size plasmids sharing 50% of their sequence give D ≈ 0.033. Why is that "known cluster"?
14. A 15% fragment of a reference plasmid gives D ≈ 0.064 → "novel". How do you separate fragmentation from novelty?
15. How many of the 16 references are singleton clusters at 0.05? What fraction of PLSDB would be "known"?
16. Are query and reference sketched at the same size? Why are p-value and shared-hash fraction discarded?
17. What evidence supports 0.05 specifically? What is the false-known and false-novel rate against an independent partition?

**Reproducibility and operations**
18. Can another group reproduce a published leaderboard from the lock files alone, given Platon's changing database URL and MOB-suite's database living inside the conda environment?
19. Who maintains this beyond you, and what is the plan for a 3,000-line README and 133 test files?
20. Has `.ncbi.env` ever left your machine or been shared through OneDrive? Can the key be rotated?

**Unresolved-question log (implications if unanswered).** Q3, Q8, Q9 → rankings and generalisation claims remain unsupported; Q13–Q17 → classifier cannot be used for any claim; Q5 → truth-validity risk persists; Q11, Q12 → statistical statements limited to descriptive; Q19 → sustainability risk for funders.

**Where the expert perspectives disagree.**
- *Funder vs bioinformatician:* the funder wants fewer, finished things; the bioinformatician sees value in the breadth (metagenomics, operational mode). Resolution here: freeze breadth.
- *Laboratory scientist vs critical reviewer:* the former wants fewer metrics and simpler installation; the latter wants more diagnostics and sensitivity analyses. Resolution: one headline plus a mandatory robustness table.
- *Public health vs computational biologist:* public health wants actionable output; the computational view is that base-level F1 is not actionable for any single isolate. Both are right; the operational selection output should carry the `requires_confirmation` flag prominently, as it already does.

---

## Part 16. Final verdict

**PlasBench as a reconstruction benchmark:** **Promising but requires methodological refinement.**
Evidence: careful, self-critical metric design with explicit anti-gaming rules, strong provenance and reproducibility architecture, honest limitations. Against it: no real-data evidence in the folder, optimistic precision, inert leakage screen, small and taxonomically narrow cohorts, unaudited truth labels.

**Mash novelty/cluster classifier:** **Scientifically unsupported in its current form** (threshold mis-specified for mosaic and fragmented plasmids, unvalidated, 16-plasmid reference).

**Plasmid identity / relatedness / subcommunity tool described in the brief:** **Not implemented**; no score is warranted beyond N/A. The brief's scientific direction is legitimate and valuable but is a different project requiring its own validation.

**Does the project deserve scientific confidence?** For the *design* of the benchmark, yes, provisionally. For any *result, ranking, novelty call or surveillance claim*, not yet.

---

## Scoring framework (0–10; N/A where not assessable)

Scores are for PlasBench as built unless noted. Proposed or documented-but-unrun functionality is not credited.

| Domain | Score | Evidence | Weaknesses | Missing evidence | What would improve it |
|---|:-:|---|---|---|---|
| Problem significance | 6 | Real need for comparable, organism-aware tool evaluation | Narrowing as long-read grows; scope sprawl | Demonstrated decisions changed | Precise problem statement; pilot with a partner lab |
| Scientific rationale | 7 | Truth independent of tools; explicit anti-circularity and anti-gaming rules | Truth label source unaudited | Truth audit | Audit + read-support evidence |
| Conceptual novelty | 2 | None claimed | Standard benchmarking concept | — | Not required for a resource paper |
| Methodological novelty | 4 | Unified projection metric, clustered resampling, recall ceiling, DB-overlap flag | Incremental; each part standard | Comparison showing added value | Rank-robustness and leakage analyses as the contribution |
| Biological validity | 4 | Per-plasmid, circular and AMR-aware diagnostics | Chromid/integration ambiguity; no lab confirmation; survivorship bias | Orthogonal lab evidence | Audit; PCR/long-read confirmed structures |
| Computational validity | 6 | Careful metric definitions; stdlib scorer; classifier test passes | Optimistic precision; stats code not audited; most tests not run | Independent scorer agreement; CI coverage simulation | Sensitivity grid; PlasEval cross-check |
| Plasmid identification | N/A | PlasBench evaluates other tools; does not identify plasmids | — | — | n/a unless scope changes |
| Similarity assessment | 2 | Mash NN exists | Wrong ANI gloss; fragments; 16 refs; faked-mash tests | Any real validation | Part 8.4 |
| Clustering and subcommunity assignment | 1 | Static single-linkage over 16 plasmids | No subcommunities; chaining; no stability | Validation vs curated taxonomy | Replace/validate; keep out of claims |
| Relatedness inference | N/A | Not implemented | — | — | Separate project |
| Edge-case robustness | 4 | Many documented diagnostics (ambiguity, redundancy, ceiling, negative controls) | Repeats/IS hidden by MAPQ filter; fragmented classifier calls; stage-2 default | Adversarial test suite on real structure | Part 7 safeguards |
| Validation and benchmarking | 3 | Framework supports rigorous validation; cohort locks | **No real results present**; cohorts small, *E. coli* heavy | Real runs; external cohorts | Part 8; public-v2 pilot |
| Interpretability | 6 | Rich, plain-language diagnostics; confirmation flags | Metric overload; report not inspected; no relatedness evidence outputs | Usability testing with non-bioinformaticians | One headline plus robustness table |
| Computational efficiency | 4 | Scoring linear; threads policy; RSS/time recorded | No published runtime/memory; SPAdes memory failures noted | Measured benchmarks | Publish per-tool metrics |
| Practical usefulness | 5 | Real use for method choice; packaged in Docker/Galaxy/bioconda | WSL/Linux barrier; heavy install; no epidemiological use | User studies | Lighter route; pilot with partner labs |
| Public health relevance | 3 | Indirect via method choice; explicit "not diagnostic" | No surveillance outputs | Demonstrated surveillance use | Partner-lab pilot; AMR truth |
| Reproducibility | 7 | Cohort locks, manifests, image digests, tool-version capture | DB dates blank; Platon URL instability; DB inside conda env | Third-party re-run | External reproduction; pinned DB snapshots |
| Scalability | 4 | Idempotent stages; parallelism flags | Assembly bound; manual curation; all-vs-all Mash | Scaling test at 100+ isolates | Measure; incremental caching |
| Implementation readiness | 5 | Extensive code, tests, packaging | Single maintainer; 3,000-line README; scope sprawl | CI, full test run | Freeze scope; CI |
| Funding readiness | 4 | Open, reproducible, African-relevant | No results; governance/IP clarity; sustainability | Pilot evidence | Pilot with Part 14 items |

**Do not read the average as a quality indicator:** the mean of the numeric scores is ~4.3, but a single critical gap (no real-data evidence) caps the trust that any other score should earn.

---

## Addendum: follow-up code audit (scorer, truth, aggregation, tests/CI)

Three read-only audits followed this review. They **confirmed** the claims in Parts 5.2 and 5.5 (unmapped/filtered bases never FP; pipeline vs CLI defaults; default-to-CHROMOSOME with warning only; `strict_precision` mixes reference and query bp) and found these additional defects. Scores in this report are unchanged because none alters the main conclusions, but D1, D5 and D8 weaken the "Reproducibility" and "Computational validity" evidence.

| ID | Finding | Location |
|---|---|---|
| D1 | A tool that fails on every sample vanishes from the leaderboard instead of scoring F1 = 0 | `aggregate_results.py:299` |
| D2 | `tool_status.tsv` has no track column; failure/completion counts leak across tracks | `scripts/04_run_tools.sh:501` |
| D3 | Blank F1/precision/recall averaged as 0.0 in recommendation quality, contradicting the "never 0" rule | `select_operational_method.py` `tool_quality` |
| D4 | Failed and skipped lumped into one failure rate; OOM/timeouts indistinguishable from tool failures (no exit code recorded) | `04_run_tools.sh`, `aggregate_results.py` |
| D5 | Ranking has no tie-break, so the "runner-up" in the significance test can be arbitrary | `aggregate_results.py:379` |
| D6 | 22 of 32 `public-v2` rows have blank `source_study` and are dropped silently from leave-one-study-out validation | `study_groups.py:18-20` |
| D7 | Holm correction is applied per track, not across every comparison in the run as METHODS.md states | `aggregate_results.py:718` |
| D8 | Non-chromosome, non-plasmid location types (Segment, Unlocalized, Unplaced) are silently scored as CHROMOSOME | `make_truth.py:129-137` |
| D9 | Version-stripped accession fallback is order-dependent; `chr_name` collisions are last-wins | `make_truth.py:72-76,103-111` |
| D10 | Scorer does not read the minimap2 `tp:A:` tag, so "primary only" is not enforced when scoring; filters are per alignment row | `score_plasmids.py:156-221` |
| D11 | Leakage screen is invisible when every date is blank (shows "0, 0, blank"; HTML says "n/a") | `aggregate_results.py:401-411`, `build_html_report.py:1344` |
| D12 | The HTML report never shows the `plasmid_novelty` result; only `selection_report.json` does | `build_html_report.py` |
| D13 | Stale `build/lib/plasbench` (version 0.2.7 vs source 0.1.5); scratch test runners; duplicate concept-note files; synthetic `results_audit/` tracked | repo hygiene |

### Remediation status

This report describes the code as audited. A follow-up pass changed the following; the findings above are left as written so the record of what was wrong is intact. Scores were **not** re-assessed, because nothing below adds real-data evidence.

| Finding | Status | Where |
|---|---|---|
| D1 all-fail tool vanishes | **Fixed**; ranks last, F1 = 0, in its own track | `aggregate_results.py` `summarise`, `ranked_tracks`; `test_aggregate_failures.py` |
| D2 status leaks across tracks | **Reassessed**: the capability registry maps each tool to exactly one track, so tool-wide counts did not mix tracks. The real gap (placing a tool that has no score rows) is fixed via the registry | `ranked_tracks(tool_tracks=...)` |
| D3 blank metric averaged as 0 | **Fixed** for F1, precision, recall, plasmid recall | `select_operational_method.py`; `test_selection_undefined_metrics.py` |
| D4 resource vs tool failures; skipped counted as failed | **Fixed**: exit code recorded in the reason column (no schema change), 124/137 classed as resource, `--resource-failures`, `n_failed_resource`; skipped no longer raises `failure_rate` | `04_run_tools.sh`, `aggregate_results.py`; `test_failed_tool_exit_code.sh` |
| D5 no tie-break | **Fixed**; one existing test had depended on it | `aggregate_results.py`; `test_leaderboard_significance.py` |
| D6 blank `source_study` dropped silently | **Fixed**: bioproject fallback that never splits a study; unassigned samples reported | `study_groups.py`; `test_study_groups.py` |
| D7 Holm scope | **Documentation corrected** (per track, which is also the more defensible family) | `METHODS.md` |
| D8, D9 truth defaulting and lookup | **Fixed**: unresolved sequences are `REVIEW`, stage 2 stops; conflicts detected; `--allow-default` opt-in | `make_truth.py`, `02_truth.sh`; `test_make_truth.py` |
| D10 primary-only not enforced | **Fixed** (`tp:A:S` rows ignored with a warning); per-row filter semantics documented | `score_plasmids.py`, `METHODS.md`; `test_scoring_adversarial.py` |
| D11 leakage invisible when dates blank | **Fixed**: stderr and Markdown warning, `n_unknown_overlap`, clearer HTML cell. The dates themselves still need filling in | `aggregate_results.py`, `build_html_report.py`; `test_leakage_visibility.py` |
| D12 HTML omits the novelty result | **Fixed**: shown in each selection card as an experimental, caveated block; legacy labels still display | `build_html_report.py` `nearest_reference_block`; `test_report_classifier_section.py` |
| D13 hygiene (`build/`, scratch runners, duplicate `.docx`, tracked `results_audit/`) | **Not done** | |
| Part 5.5 classifier defects 1, 2, 5, 6, 7 | **Fixed or relabelled**: sketch sizes equal, p-value and shared hashes kept and gated, labels renamed (`close_reference_match`, `no_close_reference`, `distance_margin`), docstring and docs now state what the threshold means. The arithmetic is pinned by `test_classifier_semantics.py` | `classify_operational_plasmid.py` |
| Part 5.5 defects 3, 4, 8 (16 references, chaining, no validation) | **Not fixed**: the screen remains unvalidated and experimental | |
| Part 5.2 precision optimism | **Documented and pinned by tests, not changed**: `strict_precision` is still supplementary and ranking is still mean F1 | `METHODS.md`; `test_scoring_adversarial.py` |
| Part 5.2 ranking depends on scoring choices | **Measured, not removed**: `rank_sensitivity.py` writes `benchmark.rank_robustness.tsv` each run (filters re-scored from the PAFs, plus strict F1 and per-plasmid recovery; Kendall tau; top-tool change) | `python/rank_sensitivity.py`, `06_aggregate.sh`; `test_rank_sensitivity.py` |
| `--rank-metric`, real-data run, truth-label audit, fill database dates, CI job with real minimap2/mash, public-v2 metadata | **Not done** | |

Verified correct by the audit: interval merging, PAF coordinates, identity definition, zero-division handling, the bootstrap, sign-flip permutation and Holm mathematics, and the 5-cluster minimum.

Still unaudited: `recommendation_model.py`, `merge_bin_metrics.py`, `validate_truth_table.py` (whether it catches defaulted sequences is unverified), the HTML report rendering.

---

## Appendix A. Key numerical derivations (for verification)

Mash distance (Ondov et al. 2016): `D = −(1/k) ln(2j/(1+j))`, k = 21 (default; not overridden in the scripts).
- Equal-sized sequences sharing fraction *s* of k-mers: `j = s/(2−s)` ⇒ `D = −ln(s)/k`.
  - s = 0.80 → 0.0106; s = 0.50 → 0.0330; s = 0.35 → 0.0500.
- Exact fragment of fraction *f* of a reference: `j = f` ⇒ `D = −ln(2f/(1+f))/k`.
  - f = 0.25 → 0.0436 (known); f = 0.212 → 0.0500; f = 0.15 → 0.0639 (novel).
These ignore sketch sampling error and assume exact k-mer identity; they show the *direction and magnitude* of the effect, not a simulation.

## Appendix B. What was checked and found sound (for balance)
- Abstention scored as F1 = 0 and ranking on shared samples (CHANGELOG, METHODS) correctly prevent a known benchmark-gaming route.
- Bioproject-clustered bootstrap and permutation tests, Holm correction, and refusal to report an interval with fewer than 5 clusters.
- Explicit refusal to score long-read tools against truth built from the same reads, enforced by schema, not by convention.
- Truth-derived descriptors barred from the live recommendation model, with the exclusion stated in code.
- Honest documentation of limitations (unmapped bp, redundant coverage, ambiguity, recall ceiling, depth confound).
- Pipeline scoring defaults (MAPQ 20, identity 0.90, length 200, query coverage 0.20) are consistent with the METHODS text, even though the scorer CLI defaults (0/0/1/0) are permissive.
