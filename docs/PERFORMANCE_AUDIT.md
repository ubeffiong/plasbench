# PlasBench performance and architecture audit

Date: 2026-11-09. Scope: the whole repository (`python/`, `scripts/`, `adapters/`, `plasbench/`, `galaxy/`, `test/`).
Sections A–N are the audit as performed, before any change. The roadmap was then implemented; the next
section records what changed and how each change was validated. The timing harnesses are in `test/bench/`.

## Implementation status

| Roadmap item | Status | Where | Validation |
|---|---|---|---|
| Rectangular bin matching (both copies) | **Done** | `python/matching.py`; `score_bins.maximum_weight`, `metagenomics.hungarian_max` are adapters | `test/test_matching.py`: equal total weight on 1,530 random instances; identical pairs on all 1,373 with a unique optimum; 8 tied instances choose a different, equal-weight pairing (deterministic). End to end, `score_bins.py` on 2,000 one-contig bins: **2,495.8 s on `main` → 0.4 s** (200 bins: 2.1 → 0.3 s). |
| Exact statistics without `Fraction` | **Done** | `python/resampling.py` (exact mean, cluster bootstrap, sign-flip tests, stratified variants) | `test/test_resampling_equivalence.py`: 20,000 means and 16 resampling designs bit-identical to verbatim copies of the earlier code; `test_robustness_diagnostics.py` still passes. `aggregate_results.py`, identical inputs, `main` → branch: 20 × 8 tools on 1 worker 18.5 → 4.3 s (4.3×); 100 × 8 on 1 worker 25.5 → 9.9 s; 100 × 8 on 12 workers 8.5 → 3.8 s; 300 × 8 on 12 workers 11.6 → 7.1 s; 100 × 15 tools on 12 workers 18.4 → 8.1 s. |
| Break the `headline_design` ↔ `aggregate_results` cycle | **Done** | Both import from `resampling.py` and re-export the old names | Existing tests import the old names unchanged |
| Fingerprint stage-4 result reuse | **Done** | `scripts/04_run_tools.sh` (`tool_fingerprint`, `is_complete`, `mark_complete`) | `test/test_tool_result_fingerprint.sh`: reuse on no change; re-run on an upgraded executable (never run to ask its version), a changed `<TOOL>_*` setting or new contigs; thread counts ignored; legacy markers re-run unless `REUSE_UNFINGERPRINTED=1` |
| Capability registry read once | **Done** | `tool_capabilities.py --dump`; `lib.sh load_capabilities` | `test/test_capability_cache.sh`: identical answers to the per-call lookups for all 27 tools, an unknown tool and an invalid registry. It caught a `\r` bug on Windows during development. |
| One minimap2 index per sample | **Done** | `scripts/05_score.sh` (`MM2_TARGET`) | WSL, minimap2 2.26, demo sequences: byte-identical PAF in 105 of 105 call shapes |
| Merge the two minimap2 passes per tool | **Not adopted** | – | The combined pass reproduced the primaries (35 of 35) but changed the ambiguity diagnostic in 6 of 35 (that pass runs without `-c`), so the change would alter a reported result |
| Core scorer defaults vs pre-registration | **Done (entry point)** | `plasbench/tools.py` (`plasbench-score`); a note on direct `score_plasmids.py` runs | `test/test_score_entry_filters.py`. The script defaults stay unfiltered: about 25 tests use the scorers as pure functions |
| Consolidate duplicated readers | **Done** | `plasbench_common.py`: `read_truth_table`, `read_truth_split`, `read_bin_membership`, `iter_fasta`, `open_maybe_gz`, `union_length`; 20 local copies replaced | Full test suite and the demo. `bin_quality.py` now follows the bin scorer's rules (intended). `number()` copies with different semantics, the three-class truth reader and the multi-membership bin readers were left alone on purpose. |
| Parallel stage-6 advisory group | **Done** | `scripts/06_aggregate.sh` (`STAGE6_PARALLEL_JOBS`, default 4) | Bash syntax check; each job keeps its warn-only failure handling; the stage waits before anything downstream reads the tables |
| Leaderboard writer guard | **Done** | `aggregate_results.write_tsv` refuses a column/value count mismatch | Every aggregation test |
| Performance regression harness | **Done** | `test/bench/` (run by hand; not timed in CI) | – |
| Split `build_html_report.py` and the README | **Not done** | – | Editorial work with no runtime effect; still listed as open item 9 in the README |

### End-to-end check: the bundled demo, before and after (WSL Ubuntu, same machine)

| | `main` (before any change) | After the changes |
|---|---:|---:|
| `test/run_demo.sh` wall time | 645.9 s | 179.7 s (3.6× faster) |
| Output files | 528 | 528 |
| Byte-identical outputs | – | 527 of 528 |

The one differing file is `benchmark.report.html`, and only in timestamps (generation time and the file
times it lists) plus one listed size of `benchmark.bin_quality.tsv`, which another process rewrote after the
baseline's report was generated. That data file itself is byte-identical in both runs.

### Data-structure and algorithm techniques applied (second round)

Each change was benchmarked on fixed synthetic inputs before and after (`test/bench/bench_dsa.py`,
`test/bench/bench_downloads.py`), and each prints a hash of its output. Timings below are from back-to-back runs of
the two code versions on the same machine minutes apart (an earlier pair, taken under other load, gave smaller
ratios in the same direction). **Every output hash is identical
before and after**: these changes alter cost, never results.

| Technique | Where | Before → after | Complexity |
|---|---|---:|---|
| Hash map index instead of a scan per bin | `bin_agreement.per_bin_rows` (best match per bin, 3,000 single-contig bins) | 1.215 s → 0.019 s (64×) | O(bins × overlaps) → O(overlaps) |
| Hash set instead of list membership | `bin_agreement.read_bins` (60,000 rows, large bins) | 13.66 s → 0.16 s (86×) | O(k²) per bin → O(k) |
| Linear `min()` instead of sort-then-first | `bin_agreement.per_bin_rows` best match | (included above) | O(c log c) → O(c) |
| Hash sets instead of probing every row × column | `matching.max_weight_matching` live rows/columns (5,000 bins, 30 plasmids) | 0.027 s → 0.004 s (6.8×) | O(rows × cols) → O(edges) |
| Bounded heap (top-k) instead of a full sort | `build_visualization_data.top_blocks` (500 of 200,000 blocks) | 0.54 s → 0.26 s (2.1×); O(k) instead of O(n) extra space | O(n log n) → O(n log k) |
| Sliding window between precomputed N positions (two pointers), bytes encoded once | `contig_crosscheck.sampled_kmers` (1 Mb) | 2.66 s → 1.05 s (2.5×); the blake2b hash per k-mer, which defines the sample, now dominates | same O(n), smaller constant |
| Bit manipulation: bulk 32-bit Mersenne Twister words decoded into flip bits and bootstrap indices, sums via `itertools.compress` | `resampling.py` | **Tried and reverted.** Identical p-values, but 10% slower for the permutation test and 2× slower for the bootstrap: cProfile had inflated the per-call cost of the one-bit draw, and decoding words in Python costs as much as the C-level `getrandbits` calls it replaced. Kept instead: the bit draw inlined (no function call per draw) | – |
| Counting pass (`Counter`) instead of `list.count` per item | `freeze_prereg.read_rows` duplicate check | not measurable (dozens of rows) | O(n²) → O(n) |
| Binary search per record instead of a scan per bin | `score_plasmids.calibration` | 0.171 s → 0.102 s (1.7×) | O(n × bins) → O(n log bins) |
| Streaming with a filter instead of loading whole files | `iter_fasta(path, wanted)`; `database_containment` (truth plasmids out of the reference), `build_visualization_data` (only displayed records) | peak memory 12.7 MiB → 0.4 MiB (5 Mb chromosome + 3 plasmids) | O(genome) → O(largest wanted record) |
| Parallel downloads: both mates at once, plus N byte ranges per large file (HTTP Range; aria2c when installed) | `fetch_ena_reads.py` | 8.6 s → 1.6 s for 2 × 16 MiB at 4 MiB/s per connection (5.4×); 1.2 s with `ENA_DOWNLOAD_CONNECTIONS=8` | wall time ÷ connections while the link is not saturated |

### Pipeline-level techniques (third round)

| Technique | Decision | Evidence |
|---|---|---|
| Thread budget against oversubscription | **Done.** With `THREADS` unset, `config.sh` divides the cores across `MAX_PARALLEL_SAMPLES × MAX_PARALLEL_TOOLS`; the per-tool `*_THREADS` follow | 2 samples × 3 tools on 12 cores: 72 threads requested on `main` (a warning only), 12 now (`test/test_thread_budget.sh`). One slot still gets every core; an explicit `THREADS` wins |
| Shared read-only index instead of rebuilding per call | **Done** (round one): one `minimap2 -d` index per sample | Byte-identical PAF in 105 / 105 call shapes |
| Generators / lazy streaming | **Done.** Every reader already streams (no `readlines()` anywhere); `iter_fasta(wanted=…)` now also skips unwanted records without joining them | Peak 12.7 → 0.4 MiB on a reference read |
| Pre-compiled regular expressions | **Done** where one ran per record (`build_visualization_data` CIGAR parsing); `alignment_accuracy` was already compiled | The other 10 inline patterns run once per file or per label, and Python caches compiled patterns anyway |
| Caching of finished steps | **Done** (round one): fingerprinted stage-4 reuse; downloads, assemblies and the recall ceiling were already reused | `test/test_tool_result_fingerprint.sh` |
| Named pipes (FIFOs) between tools | **Recommended, not shipped.** The one large write-then-read is stage 1: `fasterq-dump` writes uncompressed FASTQ that `pigz` re-reads (0.5–3 GB per mate). The fix is `fasterq-dump` writing into FIFOs that `pigz` drains. `fastp` → SPAdes cannot use pipes (SPAdes reads its inputs several times) | `fasterq-dump`, `fastp`, `pigz` and the assemblers are not installed on the audit machine or its WSL, so the change could not be verified against the tools' real output behaviour, and an unverified change to the read-extraction step would put every downstream result at risk. Stage 5's only temporary file (recall-ceiling windows) is a few MB, too small to matter |
| Workflow engine (Snakemake / Nextflow) | **Not adopted here** | The fingerprinted reuse and bounded job slots cover the caching and core-mapping benefits; a migration is a separate project and the Galaxy wrappers already serve hosted runs |
| Binary columnar formats (Arrow / Parquet, Polars) | **Not adopted** | PlasBench is standard-library only by design, and its tables are small (a 98-isolate × 15-tool run has about 1,500 score rows); parsing is not a measured cost anywhere in the profiles |
| Read subsampling to a coverage cap before assembly | **Not adopted as a default** | It changes the input every tool is benchmarked on, so it would change results. Controlled subsampling already exists as a sensitivity analysis (`make_depth_ladder.py`, `make_read_quality_ladder.py`) |
| Memory-mapped classifier databases (Kraken2 `--memory-mapping`) | **Not applicable** | PlasBench runs no read-level taxonomic classifier; the benchmarked tools load their own databases |

**Considered and not changed.** `interval_overlap_bp` already uses a two-pointer sweep; the PR-curve sweep
is already incremental with binary search; `UnionFind.find` is already iterative with path halving;
`repeat_content` already packs k-mers into 2-bit integers on a rolling window. The only recursion,
`build_html_report`'s file-tree `render`, recurses as deep as the results directory nests (a few levels),
so converting it to an explicit stack would add risk for no measurable gain. `prefetch` / `fasterq-dump` / `datasets download` manage their own transfers; stage 1
already runs samples in parallel (`MAX_PARALLEL_SAMPLES`).

## How to read the numbers

| Label | Meaning |
|---|---|
| **Measured** | Timed on this machine: Windows 11, Python 3.14.3, 12 logical CPUs, repository on a OneDrive-synced drive. |
| **Estimated** | Derived from measured unit costs times counted operations. Not run end to end. |
| **Theoretical** | Read from the code (complexity class). Not timed. |

Two caveats apply to every measured number:

1. PlasBench targets Ubuntu. On this Windows machine a bare `python -c pass` takes **0.65–0.93 s**, and loading a
   scorer script takes about 1.4 s even for `--help`. On Linux, interpreter start-up is normally tens of
   milliseconds. Absolute times for short scripts are therefore pessimistic here, while the *ratios* between
   algorithms are not affected.
2. The external tools (SPAdes, fastp, minimap2, MOB-suite, Platon and the others) are **not installed here**,
   so stages 1, 3 and 4 and the minimap2 calls in stage 5 were not measured. On real runs they almost certainly
   dominate wall time. `tool_status.tsv` already records `runtime_seconds` and `peak_rss_kb` for every tool run.
   That is the right source for those numbers once a real cohort run exists.

---

## A. Executive assessment

PlasBench is a **pipeline of standalone, standard-library-only Python scripts driven by numbered bash
stages**, exchanging TSV files. There is no database, no service layer and no third-party Python dependency.
For a benchmark of about 100 isolates this is an appropriate architecture: easy to audit, reproducible and
portable. **No rewrite is recommended.**

There is visible earlier optimisation work: an exact mean that avoids `statistics.mean`, a cheaper sign-flip
random stream, an incremental O(E log E) precision-recall sweep, a process pool for paired statistics, and
parallel sample and tool slots. Most hot paths are already linear or near-linear.

The measured problems are concentrated in a few places:

| # | Finding | Evidence | Impact |
|---|---|---|---|
| 1 | **Dense Hungarian matching** in `score_bins.maximum_weight` pads to a max(B, P) square: O(max(B,P)³) time | 200 bins × 20 plasmids: **2.07 s**, against **0.004 s** for a rectangular solver (498×), same total weight | Seconds to hours per sample once a tool emits hundreds of bins (the trivial baselines emit one bin per contig). The same algorithm is duplicated in `metagenomics.hungarian_max`. |
| 2 | **Aggregation is dominated by exact `Fraction` arithmetic** inside the stratified permutation test | 20 samples × 8 tools: **80 s** serial. Profile: 87% in `stratified_permutation`, 78% in `exact_mean` (1.27 M calls) | Stage 6 cost grows with tools² × 10,000 permutations × samples. Two bit-identical prototypes give 2.5× and 2.8×. |
| 3 | **Per-call process overhead.** The demo makes 300 Python launches in 481 s; a static registry lookup is launched up to 5 times per (sample, tool) | `tool_capabilities.py`: 44 launches = **60.1 s (12.5%)** of the demo | About 7,000 avoidable launches on a 98 × 15 run (estimated) |
| 4 | **Stale-result risk.** Stage 4 reuses a tool result whenever a `.complete` marker exists, whatever the tool version, database release, parameters or input contigs | `scripts/04_run_tools.sh:138` `is_complete()` | Reproducibility, not speed: an upgraded tool can silently reuse old predictions. |
| 5 | **Duplicated scientific helpers**, some with diverging behaviour | `read_truth` ×11, `read_fasta` ×6, Hungarian ×2, interval merge ×5 | Maintenance risk. One divergence is latent today (see E). |

---

## B. Architecture and dependency map

```mermaid
flowchart LR
    CLI[plasbench CLI<br/>plasbench/cli.py, tools.py] --> RUN[scripts/run_all.sh]
    GAL[galaxy/*.xml] --> TOOLS[plasbench-score / plasbench-aggregate]
    RUN --> S0[00 setup] --> S1[01 download] --> S2[02 truth] --> S3[03 assemble] --> S4[04 run tools]
    S4 --> AD[adapters/*.sh<br/>14 tool adapters]
    S4 --> S5[05 score] --> S6[06 aggregate]
    S1 -.-> S7[07 long-read] --> S5
    S5 -->|per sample x tool| SP[score_plasmids.py]
    S5 --> SB[score_bins.py]
    S5 --> CC[contig_classification.py<br/>contig_crosscheck.py]
    S5 --> AMR[score_amr_placement.py]
    S6 --> AGG[aggregate_results.py]
    AGG <-->|circular, deferred import| HD[headline_design.py]
    S6 --> RS[rank_sensitivity.py] --> SP
    S6 --> HTML[build_html_report.py 2,578 lines]
    AMR --> SB
    SP & SB & HD --> PC[plasbench_common.py]
    TOOLS --> SP & AGG
```

* 113 Python modules (25,658 lines), 15 stage scripts (3,951 lines), 14 adapters, 198 test scripts (20,475 lines).
* Only 45 of the 113 modules import a shared helper. The rest are self-contained, which is why helpers are
  re-implemented (section E).
* The hubs are `plasbench_common.py`, `headline_design.py` and `validate_cohort.py`. Scripts are also imported
  as libraries: `rank_sensitivity → score_plasmids`, `score_amr_placement → score_bins`,
  `validate_recommendations → aggregate_results`.
* **Circular dependency:** `aggregate_results.py:34` imports `headline_design`, and `headline_design.py:218, 243, 302`
  import `bootstrap_ci`, `paired_permutation_pvalue` and `resampling_units` back from `aggregate_results` inside
  functions. It works, but the resampling primitives have no single home.
* **Silos:** the isolate track (`score_bins.py`) and the metagenomic track (`metagenomics.py`) each carry their
  own Hungarian solver and their own bin readers.
* **Database:** none. Section H is not applicable.

---

## C. Runtime analysis

### C1. End-to-end demo (`test/run_demo.sh`, mock tool outputs, every Python stage) — measured

Six demo isolates, mock tools, precomputed alignments, traced with `bash -x` timestamps.

**Total: 481 s wall, 300 Python process launches, about 1,080 shell commands.** Every launch averages 1.6 s.
A bare script start (`--help`) costs about 1.4 s here, so roughly 300 × 1.4 s ≈ 7 of the 8 minutes is
probably interpreter start-up and imports rather than computation (estimated from that floor).

| Script | Wall time | Share | Launches | Note |
|---|---:|---:|---:|---|
| `contig_crosscheck.py` | 61.1 s | 12.7% | 7 | Alignment-free k-mer labels, about 9 s per sample: real work |
| `tool_capabilities.py` | 60.1 s | 12.5% | 44 | **Static registry lookup**, about 1.4 s per launch: pure overhead |
| `score_plasmids.py` | 49.4 s | 10.3% | 29 | About 1.7 s per call, close to the start-up floor |
| `contig_classification.py` | 49.3 s | 10.3% | 36 | Mostly start-up |
| `bin_agreement.py` | 37.2 s | 7.7% | 26 | |
| `score_amr_placement.py` | 33.6 s | 7.0% | 21 | |
| `alignment_accuracy.py` | 26.9 s | 5.6% | 29 | |
| `score_bins.py` | 22.9 s | 4.8% | 12 | Few bins in the demo, so the matcher is not stressed |
| `feature_preservation.py` | 21.6 s | 4.5% | 25 | |
| Shell commands (non-Python) | 18.2 s | 3.8% | 1,079 | |
| `build_html_report.py` | 7.6 s | 1.6% | 1 | |

On this workload, wall time is set by **how many processes are started, not by algorithms**. With six demo
isolates, `aggregate_results.py` does not reach the cost shown in C2.

### C2. Component timings — measured

| Workflow | Stage / component | Input | Wall time | Memory | Bottleneck |
|---|---|---|---:|---:|---|
| Scoring | `score_plasmids.py` (one sample × tool) | 200 / 2,000 / 20,000 alignments | 2.85 / 2.82 / 2.17 s | not measured | Flat across a 100× input range, so this is fixed start-up cost, not the algorithm |
| Scoring | `score_bins.py`, one bin per contig | 200 bins, 6 plasmids | **15.6 s** | not measured | Dense Hungarian, called twice per run |
| Scoring | `maximum_weight` alone | 50 / 100 / 200 / 300 bins | 0.021 / 0.229 / 2.07 / 7.32 s | 0.5 MB traced at 200 | O(n³) on a padded square |
| Aggregation | `aggregate_results.py`, 8 tools, 1 worker | 20 / 100 / 300 samples | 80 / 148 / 224 s | not measured | Stratified permutation test |
| Aggregation | same, 12 workers | 100 / 300 samples | 47.5 / 49.9 s | not measured | Process pool helps 3–4.5× |
| Aggregation | 15 tools (105 pairs), 12 workers | 100 samples | 87.9 s | not measured | Pairs grow with tools² |
| Truth diagnostics | `repeat_content.canonical_kmers` + `Counter`, k = 29 | 1 Mb / 5 Mb random genome | 2.1 s (untraced) / about 10 s (estimated) | 86 / 346 MB traced peak | Pure-Python k-mer table; once per sample |
| Start-up | `python -c pass` | – | 0.65–0.93 s | – | Machine-specific (see caveat 1) |

### C3. Profile of aggregation (20 samples × 8 tools, 1 worker, cProfile) — measured

| Function | Cumulative share | Calls |
|---|---:|---:|
| `headline_design.stratified_permutation` | 87% | 28 (one per tool pair) |
| `headline_design.exact_mean` | 78% | 1,272,256 |
| `headline_design.macro_mean` | 76% | 280,064 |
| `fractions.Fraction.__new__` / add / div | about 55% combined | 4.3 M |
| `headline_design.stratified_bootstrap` | 12% | 36 |

The stratified path is taken whenever at least one species reaches `MIN_SPECIES_CLUSTERS`. On `public-v3`,
22 *E. coli* clusters qualify, so it applies to the real headline.

---

## D. Algorithmic complexity

Notation: B = predicted bins, P = truth plasmids, E = alignments, T = tools, n = samples, u = independent
clusters, I = 10,000 permutations, R = 1,000 bootstrap draws, L = genome length.

| Method (file) | Current complexity | Space | Basis | Concern | Recommended |
|---|---|---|---|---|---|
| `score_bins.maximum_weight` (`python/score_bins.py:297`) | O(max(B,P)³) | O(max(B,P)²) dense cost matrix | Code + measured | Cubic in the larger side; most cells are zero | Rectangular Hungarian, O(min² · max) time and O(B·P) space; 498× measured at 200 × 20 |
| `metagenomics.hungarian_max` (`python/metagenomics.py:226`) | O(max(B,P)³) | O(max(B,P)²) | Code (theoretical) | Same as above, on communities with more bins | Share one rectangular solver |
| `headline_design.stratified_permutation` (`:241`) | O(I · n) per pair, O(T² · I · n) per track | O(n) | Code + profile | Large constant: rebuilds lists and exact Fractions every iteration | Precompute exact integer sums per cluster: O(I · u) integer adds per pair; 2.8× measured, identical p-values |
| `headline_design.exact_mean` (`:175`) | O(k) fsum passes + Fraction | O(k) | Code + profile | `Fraction` object overhead | Integer numerator over a power-of-two denominator, one int/int division: 2.5× measured, bit-identical |
| `headline_design.stratified_bootstrap` (`:212`) | O(R · n) per call | O(R) | Code | 12% of aggregation | Same integer trick |
| `aggregate_results.paired_permutation_pvalue` (`:687`) | O(I · n) | O(n) | Code | Already uses `fast_mean` | Keep |
| `score_plasmids.sweep_thresholds` (`:428`) | O(E log E) | O(E) | Code (already incremental) | None | Keep |
| `score_plasmids.parse_paf_intervals` / `merge_intervals` | O(E log E) | O(E) | Code | None; streams the PAF | Keep |
| `repeat_content.canonical_kmers` + `Counter` | O(L) time | O(L) distinct k-mers | Code + measured | Python-object memory: about 70 B per k-mer | Acceptable for ≤ 12 Mb references; revisit only for metagenomes |
| `bin_agreement` overlaps and dissimilarity | O(T² · contigs) per sample | O(contigs) | Code | Hash-based, linear per pair | Keep |
| `rank_sensitivity` / `composite_score` reweighting | O(draws · T) | O(T) | Code | 500 draws, small T | Keep |

**Pairwise explosion check.** The only quadratic growth is tool pairs in stage 6. It is bounded by about 15
tools per track (105 pairs) and already parallelised. Nothing in PlasBench builds an all-against-all plasmid
distance matrix: it benchmarks tools and does not cluster plasmids. Mash and MinHash are only used for cohort
de-duplication.

---

## E. Duplicate implementations

| Implementation 1 | Implementation 2+ | Type | Overlap | Risk | Recommendation |
|---|---|---|---|---|---|
| `score_bins.maximum_weight` | `metagenomics.hungarian_max` | C (algorithmic) | Same dense Hungarian, different input shapes (edge dict vs matrix) | A fix to one misses the other | One rectangular solver in `plasbench_common`, with thin adapters |
| `score_plasmids.read_truth` (validates types, lengths, duplicates) | `score_bins`, `bin_quality`, `contig_classification`, `audit_three_class_scoring`, `compute_difficulty_features`, `derive_amr_truth`, `label_truth_evidence`, `repeat_content`, `truth_depth_anomalies` `.read_truth` | D (scientific logic) | 11 readers of the same `truth.tsv` | `bin_quality.read_truth` files every non-`PLASMID` row as chromosome. `compute_difficulty_features` does not upper-case. **Latent only**, because the scorer already refuses any other label. `scorable_truth.py` was already fixed the same way (its docstring says so). | Make each one delegate to the validating reader, as `scorable_truth` does |
| `plasbench_common.merge_intervals` | `score_bins.merge`, `contig_classification.merge`, `score_plasmids.merge_intervals`, `select_operational_method.merge_intervals` | B / C | Interval union length | Low: same result, different tuple shape | Keep one in `plasbench_common`. `score_bins` already imports it and still defines its own `merge()`. |
| `baseline_predictors.read_fasta` | `build_visualization_data`, `database_containment`, `detect_dimers`, `repeat_content`, `scorable_truth` `.read_fasta`; plus 3× `read_fasta_lengths`, 4× `fasta_ids`, 3× `open_maybe_gz` | G (data processing) | FASTA parsing | Header handling differs (`split()[0]` vs whole header) | One streaming reader with an option to keep the header |
| `score_bins.read_bins` | `bin_agreement`, `bin_quality`, `copy_number` `.read_bins` | B | Bin table | Validation differs (only `score_bins` rejects duplicates) | Shared reader with the strict validation |
| `plasbench_common.sha256` | `design_synthetic_communities`, `freeze_prereg`, `write_manifest` | A | Same | Low | Import the shared one |
| `plasbench_common.number` | 9 other `number()` helpers | A / B | Number parsing | Low | Import the shared one |
| Alignment thresholds in `config/prereg.tsv` and `config.sh` (0.90 / 20 / 0.20) | argparse defaults 0.0 / 0 / 0.0 in `score_plasmids`, `score_bins`, `score_amr_placement`, `scorable_truth`; 0.90 / 20 / 0.20 in `alignment_accuracy`, `bin_quality`, `feature_preservation`, `rank_sensitivity` | F (configuration) | Same parameter, two defaults | The pipeline and the Galaxy wrapper pass values explicitly, so results are consistent today. A bare manual `plasbench-score` call silently uses no filter. | Default the core scorers from the same environment variables, or make the flags required |

---

## F. Architectural silos

* **Appropriate modularity.** Each script does one job and is testable on its own (198 test scripts). This
  is a strength, not a silo.
* **Unnecessary isolation.** About 68 modules re-implement small readers instead of importing
  `plasbench_common`. This is the source of the type D risk above.
* **Shell-to-Python boundary used for lookups.** Bash calls Python for static registry facts
  (`05_score.sh:43-54`, `lib.sh:257`): a process per question.
* **Two bin-scoring stacks** (isolate and metagenomic) share no code.
* **Recommended shape:** keep the modular-monolith pipeline. Grow `plasbench_common` into the single home
  for readers, interval and matching primitives, and move the resampling primitives into `headline_design`
  (or a small `stats` module) to break the cycle. A workflow engine (Snakemake or Nextflow) would add value
  for cluster scheduling and caching, but it is a separate decision, and the Galaxy wrappers already cover
  hosted use. Microservices are not appropriate.

---

## G. Memory and resources

* Isolate-scale data are small: about 5 Mb references, thousands of contigs. Every scorer streams its PAF.
  No memory risk was found for the isolate track.
* Measured peaks: the dense Hungarian matrix is 0.5 MB at 200 × 20 but grows with max(B,P)². At 5,000 bins
  it would hold 25 M Python ints (about 0.7 GB; estimated). The k-mer `Counter` for a 5 Mb genome peaks at
  about 346 MB traced.
* FASTA readers load whole files into memory, which is fine for isolate references. A metagenome-scale
  reference (`--max-chromosome-bp` is 12 Mb) is the upper bound in use.
* File handles are opened with `with` throughout. No leak pattern was found.

## H. Database

Not applicable: the project has no database, ORM or connection management. Data access is file-based TSV.

## I. Bioinformatics-specific

| Area | Current | Finding |
|---|---|---|
| FASTA / FASTQ ingestion | Streaming line readers; FASTQ handled by fastp and the tools | Fine; duplicated readers (E) |
| Sequence comparison | minimap2 per (sample, tool) with the FASTA reference | The reference index is rebuilt on every call: up to 4 calls per tool per sample (`05_score.sh:121, 185, 239, 243, 283`), and no `.mmi` is ever written. Unmeasured here. Building one index per sample with the same preset should give identical alignments, which must be verified. |
| Two alignment passes per tool | `--secondary=no`, then `--secondary=yes -N 20` for ambiguity | A single pass with primaries filtered by `tp:A:P` could replace both. Adopt only after showing identical primary PAFs. |
| Plasmid / chromosome discrimination | Base-level projection; contig labels with a k-mer cross-check | Linear |
| Clustering | Not performed (by design) | N/A |
| AMR | `score_amr_placement` reuses the bin matcher | Inherits finding 1 |
| Structural analysis | `call_structural_variants`, NGOC | Linear per alignment set |

**Scientific restriction.** Every change proposed below either keeps results bit-identical (findings 2 and 3)
or keeps the optimum identical with a defined tie-break (finding 1). None removes a coverage, identity or
MAPQ requirement.

## J. Parallelisation and caching

* **Present:** `MAX_PARALLEL_SAMPLES` (stages 1, 3, 4, 5) and `MAX_PARALLEL_TOOLS` (stage 4) with `job_slot_wait`,
  per-tool `*_THREADS`, an oversubscription warning, and a process pool for tool-pair statistics above 2,000
  paired samples. The measured pool gain is 3–4.5× on 12 CPUs.
* **Defaults are serial** (`MAX_PARALLEL_SAMPLES=1`, `MAX_PARALLEL_TOOLS=1`). That is reasonable for memory-heavy
  assemblers, but scoring is light and could default higher for stage 5 only.
* **Stage 6 is serial across its 35 Python calls.** Most are independent diagnostics after `aggregate_results`,
  and could run as a bounded parallel group.
* **Caching:** download, assembly and tool outputs are reused, and the recall-ceiling windows carry a parameter
  fingerprint (`05_score.sh:178-194`). The **tool-output cache has no fingerprint** (finding 4). Fingerprint it
  with tool version, database release, parameters and the input-contig SHA-256, following the existing
  `SCORABLE_PARAMS` pattern.

## K. Scalability

| Dimension | Growth | Measured | Practical limit (estimated) |
|---|---|---|---|
| Samples, stages 1–5 | Linear; parallel slots | External tools not measured | Tool runtime and memory |
| Bins per sample (`score_bins`) | Cubic in max(B,P) | 0.02 s at 50 → 7.3 s at 300 | Minutes at 500 bins; hours at 2,000 (about 8 × 10⁹ inner steps) |
| Tools per track (stage 6) | Quadratic in T (pairs) × I × n | 28 pairs → 105 pairs: 47.5 → 87.9 s at 100 samples, 12 workers | Fine for ≤ 15 tools |
| Samples, stage 6 | Close to linear in clusters, with a large constant | 20 → 300 samples: 80 → 224 s serial | Fine for the planned ≤ 100–300 isolates |
| 10,000–100,000 plasmids | Not applicable to the isolate benchmark | Not tested | The metagenomic track is the only place large B and P occur; finding 1 is the blocker there |

## L. Technical debt

* `build_html_report.py` is 2,578 lines and `aggregate_results.py` is 1,431 lines. `write_tsv` in
  `aggregate_results` writes about 90 columns positionally, so each new column must be added in two aligned places.
* `README.md` is 3,379 lines (already listed as open item 9 in the README).
* A circular import is masked by in-function imports (B).
* Thresholds are defined in three places (`prereg.tsv`, `config.sh`, argparse defaults) and can drift (E).
* There are no performance-regression tests. Equivalence tests exist for the statistics
  (`test_robustness_diagnostics.py` re-derives results with `statistics.mean`) and for the incremental PR
  sweep, which is the safety net for findings 1–2.

## M. Optimisation roadmap

| Priority | Problem | Current | Proposed change | Expected benefit | Risk | Validation |
|---|---|---|---|---|---|---|
| **High** | Cubic dense matching (`score_bins.maximum_weight`, `metagenomics.hungarian_max`) | Square n = max(B,P) Hungarian | One rectangular solver (rows = smaller side), dropping zero-edge rows, in `plasbench_common` | **Measured** 44–498× on the matcher at 50–300 bins; removes the hours-scale case | Equal-weight optimal matchings could pick a different pair, changing which bin is "matched" | Property test against the current solver on random instances: identical total weight always, identical pairs where the optimum is unique; a deterministic tie-break; all demo and test outputs byte-identical |
| **High** | Exact mean via `Fraction` (78% of stage 6) | `sum(map(Fraction, terms)) / n` | Integer numerator over a power-of-two denominator; precomputed per-cluster exact sums in the permutation and bootstrap loops | **Measured** 2.5× (mean) and 2.8× (permutation); 0 / 200,000 and 12 / 12 identical | Very low: same single correctly rounded division | `test_robustness_diagnostics.py`, `test_research_design.py`, a new old-vs-new equivalence test, and before/after timings at 20 / 100 / 300 samples |
| **High** (reproducibility) | Tool-output reuse ignores versions and parameters | `.complete` marker | Write a fingerprint (tool version, database release, parameters, input SHA-256) beside the marker; mismatch → re-run | Prevents silently stale results | Forces re-runs after upgrades (intended) | Stage-4 shell tests: version change → re-run; same inputs → reused |
| Medium | Python launched per registry lookup | Up to 5 launches per (sample, tool) | Read `tool_capabilities.tsv` once per stage into a bash associative array (or one Python call that prints the table) | **Measured** 12.5% of the demo; about 7,000 launches saved on 98 × 15 (estimated) | Low | Identical `scores.tsv` on the demo; `test_script_wiring.py` |
| Medium | Reference index rebuilt per minimap2 call | FASTA reference each time | One `minimap2 -x $PRESET -d ref.mmi` per sample | Unmeasured; scales with tools × calls | Index must match the preset | Byte-identical PAFs on a real sample |
| Medium | Diverging duplicate readers | 11 `read_truth`, 6 `read_fasta`, 4 `read_bins` | Delegate to validated shared readers, one module at a time | Removes type D drift | Low with output-equality tests | Each module's existing test plus a golden output |
| Medium | Core scorer defaults differ from the pre-registration | 0.0 / 0 / 0.0 defaults | Default from `MIN_ALIGNMENT_*` like the diagnostics, or require the flags | Prevents unfiltered manual runs | Changes the result of bare manual calls (intended) | Galaxy test data, `test_scoring.py` |
| Low | Serial stage 6 diagnostics | 35 sequential calls | Bounded parallel group after `aggregate_results` | Wall-time reduction proportional to cores (estimated) | Ordering of warnings in logs | Identical `benchmark.*.tsv` set |
| Low | Circular import | In-function imports | Move resampling helpers into `headline_design` or `stats.py` | Clarity | None | Existing tests |
| Low | No performance regression guard | – | Commit the scratch harnesses as `test/bench/` with generous time ceilings | Catches regressions | Flaky if ceilings are tight | Run in CI on Linux |
| Not recommended | Rewrite with a database, microservices or numpy | – | – | – | Adds dependencies to a deliberately stdlib-only, auditable tool | – |

## N. Scorecard (0–10)

| Area | Score | Evidence |
|---|---:|---|
| Algorithmic efficiency | 7 | Most paths linear or O(n log n), with an incremental PR sweep; one cubic matcher in two places |
| Runtime efficiency | 6 | Stage 6 is dominated by `Fraction` overhead; heavy fixed start-up cost per script |
| Memory efficiency | 8 | Streams alignments; only the dense matrix and k-mer `Counter` grow notably |
| Database efficiency | N/A | No database |
| Sequence-processing efficiency | 7 | Delegated to minimap2 and the tools; index not reused (unmeasured) |
| Clustering efficiency | N/A | No plasmid clustering by design |
| Parallelisation | 7 | Sample and tool slots plus a statistics process pool; serial defaults; stage 6 serial |
| Caching | 5 | Broad reuse, but the tool cache is unfingerprinted |
| Code reuse | 4 | 11 truth readers, 6 FASTA readers, 2 Hungarian solvers; only 45 of 113 modules use the shared module |
| Architectural cohesion | 7 | Clear stages and TSV contracts; one circular import; two bin-scoring stacks |
| Modularity | 8 | Single-purpose scripts, independently testable |
| Maintainability | 6 | Very large report and aggregate modules; positional 90-column writer; 3,379-line README |
| Scalability | 6 | Fine for about 100–300 isolates; the matcher blocks bin-heavy and metagenomic inputs |
| Test coverage | 8 | 198 test scripts including statistics equivalence tests; no performance tests |
| Reproducibility | 7 | Pinned seeds, pre-registration, manifests; stale tool-cache risk |

## Reproducing the measurements

The harnesses are outside the repository, in this session's scratchpad: `bench_matching2.py`,
`bench_aggregate.py`, `bench_score.py`, `bench_kmers.py`, `proto_exact_mean.py`, `proto_permutation.py` and
`parse_trace.py`. Each takes the project's `python/` directory as its first argument and changes nothing in
the project. If the roadmap is approved, they become the before/after benchmarks.

## Stage 2 reference annotation (about 6.5 minutes per isolate in a production run)

What was measured and what was not. **Observed:** a WSL run of `public-v4` took about 6.5 minutes of stage 2 per isolate for three isolates (the user's log). **Read from the code, not timed:**
`python/annotate_reference.py` already runs its callers (MOB-typer, abricate for AMR and replicons, AMRFinderPlus, ISEScan, ISFinder BLAST, barrnap) at the same time, gives ISEScan the whole
thread allowance and AMRFinderPlus half; the isolates themselves run one after another unless `MAX_PARALLEL_SAMPLES` is raised. Which caller dominates on that machine was **not measured**;
the code's own comment names ISEScan as the slowest (a de novo scan of a whole genome), which is an assumption here. Each caller's time is now printed as it finishes, and
`data/<isolate>/stage2_timing.tsv` already records the annotation step, so the next run shows the split.
**Changed, safely:** the annotation of an isolate does not depend on the study, so a finished annotation is cached in the data folder by the reference's SHA-256 and the callers' versions and databases
(`ANNOTATION_CACHE_DIR`); a second study of the same isolate spends no annotation time. The cached table is byte-identical to a fresh one (`test/test_annotation_cache.py`). A caller is never
skipped and no caller's output is dropped.

## Stage 3 disk and memory (the figures the resource check uses)

The disk need per isolate is an **estimate**, and there are two figures. Peak per isolate (the working set) is the trimmed reads (1x the raw compressed reads) plus SPAdes working files at 8 times them (an assumption in the 5 to 10 times range; it was not measured on this project's data) plus 0.33 GB (reference, raw reads, results); the isolates in flight at once (`MAX_PARALLEL_SAMPLES`) must fit, or the run cannot start (exit 6). What stays per isolate is the raw and trimmed reads and the assembler folder (assumed 3 times the reads, because nothing is deleted after an isolate) plus 0.33 GB; the whole cohort not fitting is only a warning with the number of isolates that will fit, and a guard before each isolate's download and assembly stops the run cleanly when the next isolate no longer fits plus `PLASBENCH_DISK_RESERVE_GB`. Reads sizes come from the reads on disk, the verification lock's base counts, a sample of up to 20 ENA sizes, or last a typical 0.3 GB read set (a low-confidence figure, printed as not measured). `PLASBENCH_SKIP_DISK_CHECK=1` overrides all of it.

## Run stalls: what a long quiet run was made of (21 November 2026)

Evidence is from one real WSL2 run (6 CPUs, 7.8 GB, data on a 9p Windows drive); **measured** unless marked **assumed**.

| Step | Finding | Fix |
|---|---|---|
| Stage 1, 134-row sheet | planned 134 downloads, handled 3: a command in the loop read the loop's stdin (the sample list) | every stage loop reads the list on its own descriptor (`read -u 3`); helpers get `stdin=/dev/null`; stage 3 records any isolate it did not reach |
| Stage 3 SPAdes hammer | `You need approx. 5.24277GB of free RAM` under a 4 GB budget; failed after 2 to 22 min; classified `unknown`, evidence the citation line | rule `spades_needs_memory`, single retry with `-m` from the number, footer lines never evidence |
| Default budget | 6.9 GB available gave 4 GB (integer GB floored before 80%) | computed from MB: 6.9 GB gives 5 GB |
| ISEScan | 663 s then `failed`: `ValueError: NoneType copy mode not allowed` (fastcluster 1.3.0 for NumPy 2 with NumPy 1.26.4); the HMM search is wasted | readiness probe (1 s), pin `fastcluster<1.3`, skipped with the fix when not ready |
| AMRFinderPlus | 0 s failure: database absent; `[ok] amrfinder` only tested the binary | `amrfinder --database_version` probe, `amrfinder -u` in the reference-annotation install |
| mob_typer 108 s, barrnap 31 s, abricate 13 s, ISEScan 663 s | per-caller times for a 4 Mbp genome, 6 CPUs, **one run**; ISEScan's figure is a failed run | `TYPICAL_SECONDS` in `annotate_reference.py`, 'still running, typical N min' once past twice the typical |
| Many small files on 9p | 2000 tiny files: create 16.4 s on /mnt/f (9p) against 0.059 s on ext4 (about 280x), read 10.3 s against 0.024 s, delete 3.6 s against 0.026 s. This is the file-system cost, **not** a measured SPAdes speed-up | `WORK_DIR=auto` runs assemblies on local disk when the data folder is slow |
| `plasbench status` | said stage 1 during stage 2: stages 2 and 3 wrote no stage events | `stage_timing_begin` in every stage, `sample_start/sample_end` with step names, status reads the latest event |
| Slow steps | no per-command typical time | `config/step_typical.tsv`, `STEP_SLOW_FACTOR` (default 3), one note and a `slow_step` event; nothing is stopped |
| Warning flood | 131 'missing reference' lines | one aggregated warning per stage |

Audit of the other long steps (assumed unless a figure is given): ENA/SRA downloads print percentages and resume; prefetch and fasterq-dump have heartbeat labels and typical times in the table; fastp and SPAdes are labelled, SPAdes also names its phase;
tool runs (stage 4) have no limit unless `TOOL_TIMEOUT_SECONDS` or `PLASBENCH_TOOL_TIMEOUT_PRESET` is set (a limit can score a slow tool zero, so it stays opt-in, announced at the start of stage 4); minimap2 alignment, scoring and the report build run under the stage heartbeat. Not measured: stage 4 to 8 durations on this machine.

## Where the time goes: a measured 5-isolate laptop run (22 November 2026)

Measured on the owner's laptop (WSL2, 6 CPUs, 6.9 GB free memory, data folder on a Windows drive seen through 9p), `public-v4 --max-isolates 5`, read from `results/run_events.jsonl`, the
annotation logs and each isolate's `stage2_timing.tsv` with `plasbench profile-run`. Clock figures are measured; anything marked "estimated" is not.

| Stage | Clock | Awake | Note |
|---|---|---|---|
| 1 download | 4 h 28 min | 4 h 28 min | one 9.5 GB isolate was 4 h 20 min of it (measured); the download code is being rewritten elsewhere |
| 2 truth and reference annotation | 2 h 39 min | 2 h 39 min | 74% of the stage is reference annotation; per isolate 21 to 38 min |
| 3 assemble (so far) | 3 h 12 min | 25 min | fastp showed 10,096 s: the computer slept for 2 h 47 min inside it (Windows Kernel-Power 42 at 00:46:12, resume 03:33:19); awake it was about 1 min |

Reference annotation, the callers (they run at the same time, so the step takes as long as the slowest): ISEScan 38, 20, 22 (stopped at its limit) and 35 min on four isolates, 99% of the
annotation time (1 h 56 min of 1 h 57 min). The "quick" callers took 5 to 22 min instead of 1 to 3 (abricate 46 to 444 s against a typical 13 s, barrnap about 300 s against 31 s): the callers were given
13 threads on 6 CPUs (ISEScan all 6, AMRFinderPlus 3, the others 1 each) and read and wrote on the 9p drive. Three of them hit their time limit (mob_typer on three isolates, AMRFinderPlus and barrnap on one) and
their results are missing (recorded as `timed_out`, never as zero); the limits were wall-clock, so a sleep inside the wait also counts against them. The `repeat_content` step of the 8.8 Mbp isolate took 32 min against
5 to 43 s on the others, and started when Windows logged its connected-standby transitions (506/507 at 00:12): a possible pause that left no event (profile-run flags it as "possible", not as measured).

What changed because of this (all in this change):

| Change | Why, and what is measured |
|---|---|
| `KEEP_AWAKE=1` (default): the run asks the OS not to sleep (`python/keep_awake.py`, `run_sentinel.py`) | 2 h 47 min lost to one sleep. Verified on this laptop through WSL: powershell.exe holds `SetThreadExecutionState(ES_CONTINUOUS and ES_SYSTEM_REQUIRED)`, not the display, with no administrator rights (the shell was not elevated); the helper was gone within 8 s of a `kill -9` of the sentinel. Not verified: native Windows, macOS, systemd, Modern Standby under lid close or battery saver. |
| Suspend detection, `system_suspend` event, `awake_seconds` | Every elapsed time, slow-step note, "no output for N min" figure and annotation time limit leaves the sleep out. WSL2's CLOCK_MONOTONIC was not tested across a real sleep (the owner's run was active, and sleeping the machine would have disturbed it); the detector uses the wall clock and works with either behaviour of the monotonic clock (tested with simulated clocks). |
| `ISESCAN_SCOPE=plasmids` (default) | ISEScan searches only the replicons the truth labels plasmid; the chromosome is 90% or more of the bases. One measurement, noisy (measured under load: the owner's run was using the CPUs; nice 19, 2 threads): the 57 kb plasmid of the 3 Mbp S. aureus isolate took 211 s, so ISEScan has a start-up cost of minutes and the saving is less than proportional on isolates with large plasmids. A whole-genome time under the same load was not taken (it would have slowed the real run), so a before/after on one isolate under equal conditions is NOT measured; the real-run figure for that isolate is 1329 s (stopped at its limit) with 6 threads. |
| Thread plan: ISEScan gets threads minus 2, AMRFinderPlus a third, the quick callers 1 each | 13 threads on 6 CPUs became 10 (estimated; not re-measured end to end). |
| `plasbench profile-run`, end-of-run "Time spent", status "where the time went" | this table. |
| Run profiles `fast`, `standard`, `thorough` | fast drops ISEScan and the advisory sweeps; thorough adds extras. Only ISEScan has a measured time; the rest is "not measured" in `config/run_profiles.tsv`. |
| `config/step_typical.tsv` and the annotation callers' typical times re-based | measured on this laptop 2026-11-22 (upper figures: taken while oversubscribed). |

What stayed the same: `MAX_PARALLEL_SAMPLES` and `MAX_PARALLEL_TOOLS` still default to 1, the scratch folder is still SPAdes-only (`python/work_dir.py`), and stages
still run one after another. These are NOT done in this change; the measured case and design for each:

* **Local working copy for stages 3 and 4 (and annotation).** The quick callers' 10x slowdown points at the 9p drive (or the oversubscription; the two are not separated), but no ext4-versus-9p timing of fastp, SPAdes or mob_recon
  was taken: the real run was using every CPU, and a benchmark would have slowed it. Next step: extend `WORK_DIR` to fastp output and every tool's output folder with copy-in once and an atomic copy back, then measure on an idle machine.
* **Adaptive parallelism.** CPU use in the real run: 260 to 430% of 600% during annotation (about 3 to 4 cores busy), 470 to 505% in SPAdes. Stages 5 and 6 were not reached, so no figure exists for scoring or the report.
  Design: AUTO_PARALLEL=1 would size MAX_PARALLEL_SAMPLES from CPUs and free memory with the budget of `python/resource_adapt.py`, start with stage 2 (annotation across isolates, which is I/O-bound) and stage 5 scoring, keep assembly at 1 unless memory allows
  (SPAdes used 2.1 GB RSS on a 273 MB read set here), divide threads by slots as `config.sh` does, and keep output order deterministic. Not implemented.
* **Stage overlap.** Today `run_all.sh` runs each stage for all isolates. A per-isolate pipeline would run stage 2 for an isolate as soon as its stage-1 outputs exist, behind `PIPELINE_OVERLAP=1` (default off), with a bounded
  producer and consumer, so annotation (CPU) overlaps the long download (network). On this run the 4 h 20 min download of the 9.5 GB isolate would have hidden about 1 h 20 min of the other four isolates' stage 2 (estimated from their measured stage-2 time). Risks: interleaved logs and events, the status panel assuming one stage at a time, resume
  logic, disk use. Not implemented: the download code is changing concurrently and a half-tested overlap in `run_all.sh` is worse than none.

Tests: `test_run_profile.py`, `test_suspend_awake.py`, `test_keep_awake.py`, `test_suspend_heartbeat.sh`, `test_isescan_scope.py`, `test_run_profiles.py`.

## Annotation limits, retries after a sleep, and the calmer window (follow-up, 24 November 2026)

* **Annotation callers (measured case: mob_typer stopped on 3 of 4 isolates).** The time limits now grow with how far the callers' thread plan oversubscribes the CPUs, never count the time the computer slept, and a caller that still hits its limit is run ONCE more, alone, with twice the time. If it then finishes its evidence is kept (the record says `retried` and keeps the first reason); if it times out again it stays `timed_out` with both attempts in the reason and nothing from it is used or cached. Tested with fake callers (`test_annotation_retry.py`); not re-measured on the real laptop.
* **Review of the retry wrappers after a resume from sleep.** `retry_network` (stage 1 fetches, `scripts/lib.sh`) retried any failure 3 times with 15 s and 30 s waits (45 s in all): after a wake a dead connection fails at once and Wi-Fi often needs longer than that, so a sleep could use up all three attempts. A failure that happened while the computer was asleep (a recorded sleep inside the attempt) now does not use an attempt (up to `NETWORK_RESUME_RETRIES`, 3), with a short wait for the network. A hung connection that never resets is not covered: the fetch tools have no time limit of their own here. Stage 4's `TOOL_TIMEOUT_SECONDS` used the wall-clock `timeout`, so a sleep killed a tool with exit 124 and scored it failed; it now uses `awake_timeout` (awake time only). `retry_exec` (TOOL_RETRIES) does not retry 124/137, unchanged. The download code of the other agent (`python/fetch_ena_reads.py`, stage 1's loop) was not read or changed. Tested with `test_resume_retry.sh`.
* **Window.** One vocabulary everywhere (Working / Working, console quiet / Needs attention / Done / Failed, in the run card, Jobs rows, toasts and the console chip), the script's stage number and name ("Stage 3: Assemble"), a Done card no longer restates "All 6 stages done", the card's action is "Run info" so it is not confused with the status panel's Details, and the run-profile selector is in the New benchmark wizard ("How thorough") and in Settings (RUN_PROFILE). The live download bar keeps its place.
