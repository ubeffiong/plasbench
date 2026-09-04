# Methods — the scoring model

This document is written so you can lift it into a methods section.

## Ground truth
For each isolate, a complete (long-read or hybrid) assembly is treated as truth. Each
reference sequence is labelled **plasmid** or **chromosome** using the
`assigned_molecule_location_type` field of the NCBI sequence report
(`python/make_truth.py`). This avoids using any tool-under-test to define truth, which would
bias the benchmark.

For NCBI cohorts, PlasBench obtains `sequencing_tech` and `assembly_method`
from NCBI Datasets v2. An assembly without explicit ONT/PacBio/SMRT evidence is
rejected: “Complete Genome” alone is not sufficient evidence of independent
long-read/hybrid truth.

## Predictions
Each tool emits a set of sequences it considers plasmid. A thin per-tool adapter
(`adapters/`) normalises these disparate outputs into a single **predicted-plasmid FASTA**:
- classification tools (Platon, mob_recon) → the contigs/bins they labelled plasmid;
- re-assembly tools (plasmidSPAdes, gplas) → their reconstructed plasmid contigs.

The present workflow consumes paired short-read FASTQs, usually Illumina. Long
reads are used to establish the complete reference, not as a native prediction
input; long-read reconstruction modes are a future extension.

## Projection onto the reference
The predicted-plasmid FASTA is aligned to the reference with `minimap2 -x asm5` (same
isolate, so ≤5% divergence). Alignment target intervals are merged per reference sequence,
so a reference base covered by one or more predicted-plasmid alignments is counted once.
The primary-only PAF defines TP/FP/FN. When enabled, a separate all-mappings PAF
records `ambiguously_mapped_pred_bp`: query bases having retained placements on
both plasmid and chromosome. It is a mapping-ambiguity diagnostic and does not
alter F1.

Retained alignments must meet configured length, identity, MAPQ, and per-record
query-coverage thresholds. The score table separates mapped predicted bases
into unambiguous, plasmid/chromosome-ambiguous, and unmapped categories. These
categories support interpretation but do not silently change the TP/FP/FN
definition.

## Base-level confusion matrix (positive class = plasmid)
Let `C` be the set of reference bases covered by predicted-plasmid alignments.
- **TP** = |{plasmid reference bases} ∩ C|
- **FP** = |{chromosome reference bases} ∩ C|
- **FN** = |{plasmid reference bases}| − TP

Then:
- **precision** = TP / (TP + FP) — the complement of chromosomal contamination;
- **recall** (completeness) = TP / (TP + FN) — fraction of true plasmid sequence recovered;
- **F1** = 2·precision·recall / (precision + recall).

Predicted sequence that does not align to the reference at all is reported as
`unmapped_pred_bp` and is **not** counted as FP, because it cannot be attributed to a
chromosome or plasmid origin (it usually reflects mis-assembly or contamination). Reporting
it separately keeps the core precision metric conservative and interpretable.

Predicted sequence that *does* align, but only to a reference sequence absent from
`truth.tsv` (for example a contig the NCBI sequence report never classified), is a
different failure mode and is reported separately again as `off_truth_pred_bp`. It is
also excluded from FP for the same reason: it cannot be attributed to a chromosome or
plasmid origin, since truth has no label for that target at all.

## Plasmid-level recovery
In addition to base-level F1, PlasBench reports the number of true plasmid
replicons and the number recovered to at least the configured fraction of their
reference length (default 90%). `plasmid_recall` is the fraction of true
replicons meeting that threshold. `predicted_record_count` is intentionally a
sequence-record proxy, not a bin-level precision claim: tools differ in whether
they output one contig, multiple contigs, or one FASTA per plasmid bin.

For adapters that supply `pred_<tool>.bins.tsv`, PlasBench also performs
deterministic global one-to-one bin matching using a maximum-weight assignment,
not a greedy first-match rule. A bin is eligible for a truth plasmid only when
it reaches the configured completeness and purity thresholds. Bin
precision/recall/F1 use these assignments; split events count extra qualifying
bins for one truth plasmid, merge events count extra qualifying truth plasmids
for one bin, and chromosome-aligned bin bases are reported separately.
The same all-mapping diagnostic records repeat-associated ambiguity per bin.

## Structural and AMR evidence

`circular_truth_plasmid_recovery` only says a circular *reference* plasmid was
covered. PlasBench does not infer closure from that fact. A source may supply
`pred_<tool>.evidence.tsv` with `record_id`, `evidence_type`, and
`evidence_value` for replicon, MOB, or independently supported closure evidence;
it is copied and displayed as source-reported evidence, not upgraded to proof.

AMR recovery runs only after `truth_amr.tsv` passes
`python/validate_amr_truth.py`. Curators must supply plasmid coordinates,
normalized gene and database identifiers, unique gene-copy identifiers, and a
database version. This preserves AMR context as independent truth evidence.

## Aggregation and uncertainty
Per-sample (sample, tool) rows are averaged per tool (mean and median F1, mean precision,
mean recall) and ranked by mean F1 (`python/aggregate_results.py`). A
deterministic 1,000-resample bootstrap interval is emitted for each mean F1,
and `benchmark.paired_comparisons.tsv` reports paired per-sample F1
differences and win/tie/loss counts. These are descriptive uncertainty aids,
not formal claims of clinical or statistical superiority.

## Known limitations / honest caveats
- **Base-level, not object-level.** This metric rewards recovering plasmid *sequence*. It
  does not, on its own, tell you whether a tool split one plasmid into two bins or merged
  two into one. A bin-level metric (correct plasmid *count* and 1-to-1 bin matching) is a
  natural, high-value extension.
- **Reference completeness matters.** If the "complete" assembly actually missed a small
  plasmid, a tool that finds it is unfairly penalised. Curate references carefully
  (`docs/FINDING_DATA.md`).
- **minimap2 preset.** `asm5` assumes same-isolate identity. If you deliberately test
  cross-isolate generalisation, revisit the preset.
- **Depth confound.** Low-coverage runs depress every tool; consider a depth-controlled
  subsampling experiment to separate tool quality from data quality. PlasBench
  measures staged FASTQ bases divided by reference length and rejects a depth
  ladder whose declared source depth differs by more than 20%. Ladder-derived
  samples are correlated and are not valid for a headline leaderboard.

## Reproducibility
All randomness-free. Regenerate the explicit lock with `bash env/lock_environment.sh` and record tool versions per run. The
scoring scripts depend only on the Python standard library, so they are stable across
environments.

## Recommendation validation and tracks

Stage 6 writes `benchmark.recommendation_validation.tsv`, a leave-one-study-out
check that selects a simple training-only method ranking and evaluates it on
each held-out `source_study`. It withholds an assessment when cohort diversity
or training sample size is inadequate. It is descriptive release evidence, not
external clinical validation. Track-specific leaderboard files are emitted as
`benchmark.short_read.leaderboard.tsv`, `benchmark.long_read.leaderboard.tsv`,
and `benchmark.hybrid.leaderboard.tsv`; methods from different tracks must not
be pooled into one operational conclusion.

## Hybrid tools and the circularity constraint

Plassembler assembles plasmids from long reads plus short reads. That creates a
problem the short-read tools never had.

PlasBench's truth labels come from a complete long-read or hybrid assembly. If a
hybrid tool is given the same long reads that produced that assembly, it is being
scored against its own input: it would look near-perfect for reasons that say
nothing about the tool. A short-read tool has no such exposure, because its input
is genuinely independent of the truth.

The pipeline therefore refuses by default. A sample is eligible for Plassembler
only when the cohort declares independence explicitly, in a
`truth_independent_of_long_reads` column set to `yes`. Anything else -- absent
column, empty value, `no` -- is recorded as
`circular truth: truth_technology=<X> derives from the supplied long reads` and
skipped. `PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1` overrides this globally and stamps
every affected row in `tool_status.tsv`, so a compromised result can never be
mistaken later for an independent one.

Three ways to build an eligible cohort, in descending order of how well they
withstand review:

1. **Independent truth.** The reference comes from a source other than the long
   reads fed to the tool -- a closed reference from a different platform, or a
   curated complete genome. Cleanest, and hardest to source.
2. **Held-out long reads.** Split the long-read set: part builds the truth
   assembly, the remainder feeds the tool. Defensible, and the split must be
   stated.
3. **Simulated data**, where ground truth is known by construction. Needs its own
   quality tier, since it cannot be verified against NCBI the way tiers A and B
   are.

Hybrid results are never ranked against short-read results. Aggregation writes
one leaderboard per analysis track and does not mix track claims, so
`benchmark.hybrid.leaderboard.tsv` answers "what do long reads add?" while
`benchmark.short_read.leaderboard.tsv` answers "what can short reads alone
recover?" -- the same metric, on the same isolates, with the inputs kept
separate.
