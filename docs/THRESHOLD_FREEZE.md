# Threshold freeze (17 November 2026)

*Written for: anyone who needs to know which PlasBench limits are fixed, what they were fixed from, and what is still open.*

PlasBench uses limits in two places before any tool is scored: **eligibility** (is this read set or assembly fit to benchmark on?) and **scoring decisions** (what counts as a correct plasmid, how wide an interval is, which references count). The scoring decisions were pre-registered and locked on 16 November (70 decisions, `config/prereg.tsv`, `docs/PREREGISTRATION.md`). The eligibility limits were provisional starting points. This document records freezing them, from real data, and says which are *not* yet frozen and why.

## What was frozen

| Limits | File | Status | Evidence |
|---|---|---|---|
| Short-read QC: 10 metrics, each with a warn and a reject limit | `config/short_read_qc_thresholds.tsv` | **Frozen.** Every row `frozen`; file hash `0727af448900` (written to every QC row as `thresholds_sha`) | The pilot below, and the ENA read counts of 7,129 public-v4 runs |
| Assembly QC gate: size limit 8.5 Mb | `ASSEMBLY_QC_MAX_SIZE_MB` in `config/config.sh` | **Frozen at 8.5, unchanged.** Advisory only | 0 of 3,428 genomes of the 11 clinical species in public-v4 exceed it (the largest, *P. aeruginosa*, is 7.30 Mb); 361 of 3,799 genomes of other taxa do, almost all *Streptomyces*. For those taxa set `ASSEMBLY_QC_MAX_SIZE_MB` higher: a flag there is advice, not proof of a mixed culture |
| Assembly QC gate: GC spread 0.12 | `ASSEMBLY_QC_MAX_GC_SPREAD` | **Frozen at 0.12, unchanged.** Advisory only. *Weakly* backed | 10 real assemblies (`results_real_cohort1`): the largest spread is 0.037, about a third of the limit. That is consistent with the limit, but ten assemblies cannot show it catches mixed cultures |

## The short-read QC pilot

`python/qc_pilot.py` takes the first read pairs of each run of the first rows of public-v4 in its balanced order (species take turns; chosen by position, never by any tool's result), fetches only a small prefix of each mate from the ENA with HTTP range requests, and measures it with `short_read_qc.py`. The committed table is `docs/validation/short_read_qc_pilot.tsv`.

- **60 runs attempted, 40 measured.** 20 could not be fetched (7 are not a plain two-file paired run at the ENA, 5 answered 403, the rest were dropped connections or a timeout); the reason is in the table. One isolate per species, 40 species.
- **Per-read measures are valid on a prefix; read pairs and depth are not,** so those two (and read length) are checked against the ENA counts of the 7,129 public-v4 runs that resolved (`cohorts/candidates/contributed-refseq-sra/public-v4.precheck.tsv`).

| Metric | Real data | Limits (warn, reject) | What fired |
|---|---|---|---|
| `read_pairs` | median 2.0 million; 7,129 runs | 100,000, 10,000 | 4 under warn (0.06%); none under reject |
| `estimated_depth_x` | median 139x; 7,129 runs | 30x, 10x | 136 under warn (1.9%); 9 of 7,867 candidates (0.1%) under reject |
| `mean_quality` | 30 to 39.5, median 35; 40 runs | 28, 20 | none |
| `q30_fraction` | 0.72 to 1.0, median 0.89; 40 runs | 0.75, 0.50 | 1 of 40 under warn; none under reject |
| `median_read_length` | 100 to 301, median 151; 40 runs (and 7,129) | 70, 35 | 7 of 7,129 (0.1%) under warn; none under reject |
| `adapter_fraction` | median 0.1%; 40 runs, 4 above 10% (12%, 21%, 47%, 66%) | 0.10, **none** | 4 warned; the old reject limit of 0.50 would have excluded the 66% run |
| `duplication_fraction` | 0.0001 to 0.28, median 0.01; 40 runs | 0.50, 0.90 | none |
| `n_fraction` | 0 to 0.0028; 40 runs | 0.01, 0.10 | none |
| `pair_mismatch_fraction` | none in 40 runs | 0, 0.001 | none |
| `gc_deviation` | not evaluated (see below) | 0.10, 0.20 | never fires |

**One value changed, before freezing:** `adapter_fraction` lost its reject limit. Stage 3 trims adapters, so a high share is a signal to trim, not a reason to discard a sample; the four runs with more than 10% adapter reads all had good quality (Q30 0.84 to 1.0), and the old limit would have excluded the 66% one. The change was made from the pilot and not from any tool's score, and the test (`test_short_read_qc.py`) now says an adapter-heavy run is WARN, never REJECT.

**What the pilot does not back.** `gc_deviation` is frozen as written but is **not backed** by the pilot: the pipeline never passes an expected GC, so the row never fires, and one isolate per species gives no within-species spread to calibrate it. The limits for Q30, quality and duplication are consistent with every real run seen but come from 40 runs: they are reasonable minimums, not an optimum, and the 20 runs that could not be fetched are not represented. The `qc_precheck` sample (`public-v4`) was already filtered by these limits, which is why "none under reject" for pairs and read length is partly by construction; the depth figure (9 of 7,867) is the only exclusion rate that was measured on the unfiltered candidates.

## What is not frozen, and why

| Setting | Value | Why it is still open |
|---|---|---|
| `MIN_ASSEMBLY_ADEQUACY` | 0.90 | Flags a truth plasmid the short-read assembly mostly lacks. It is a design choice about what counts as "contained", not something read QC can calibrate; it needs a real multi-tool run to see how many references it flags |
| `MULTIPLICITY_NEW_FRACTION`, `MULTIPLICITY_CHIMERA_MIN_BP`, `MULTIPLICITY_CHIMERA_FRACTION` | 0.10, 1000, 0.10 | Define when a second predicted record is redundant, complementary or chimeric. Only a real run with several tools shows how often each applies |
| Alignment, binning and CPRR limits (`MIN_ALIGNMENT_*`, `CPRR_*`, `PLASMID_RECOVERY_THRESHOLD`) | see `config/prereg.tsv` | Already pre-registered and locked (16 November); a sensitivity analysis runs beside them (`benchmark.cprr_threshold_sweep.tsv`) |
| Interval method for a stratified mean | `bootstrap_t` | Decided and pre-registered on 17 November (`interval_method_stratified`) |

The next step for the open rows is a real-data run of several tools on the independent-truth subset (`plasbench run --independent-truth-only`), then recording what fraction of references and records each limit flags before freezing it.

## Rule going forward

A frozen row is changed only with a new decision on record. The file hash is stored in every QC row (`thresholds_sha`), so results made before and after a change are visibly not comparable, and `test_threshold_freeze.py` fails if this document's hash no longer matches the file.
