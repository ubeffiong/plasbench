# Methods — the scoring model

This document is written so you can lift it into a methods section.

## Ground truth
For each isolate, a complete (long-read or hybrid) assembly is treated as truth. Each
reference sequence is labelled **plasmid** or **chromosome** using the
`assigned_molecule_location_type` field of the NCBI sequence report
(`python/make_truth.py`). This avoids using any tool-under-test to define truth, which would
bias the benchmark.

## Predictions
Each tool emits a set of sequences it considers plasmid. A thin per-tool adapter
(`adapters/`) normalises these disparate outputs into a single **predicted-plasmid FASTA**:
- classification tools (Platon, mob_recon) → the contigs/bins they labelled plasmid;
- re-assembly tools (plasmidSPAdes, gplas) → their reconstructed plasmid contigs.

## Projection onto the reference
The predicted-plasmid FASTA is aligned to the reference with `minimap2 -x asm5` (same
isolate, so ≤5% divergence). Alignment target intervals are merged per reference sequence,
so a reference base covered by one or more predicted-plasmid alignments is counted once.

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

## Plasmid-level recovery
In addition to base-level F1, PlasBench reports the number of true plasmid
replicons and the number recovered to at least the configured fraction of their
reference length (default 90%). `plasmid_recall` is the fraction of true
replicons meeting that threshold. `predicted_record_count` is intentionally a
sequence-record proxy, not a bin-level precision claim: tools differ in whether
they output one contig, multiple contigs, or one FASTA per plasmid bin.

For adapters that supply `pred_<tool>.bins.tsv`, PlasBench also performs
deterministic one-to-one bin matching. Bin precision/recall/F1 use matched bins
and true plasmids; split events count extra qualifying bins for one true
plasmid, and merge events count extra qualifying true plasmids for one bin.

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
  subsampling experiment to separate tool quality from data quality.

## Reproducibility
All randomness-free. Regenerate the explicit lock with `bash env/lock_environment.sh` and record tool versions per run. The
scoring scripts depend only on the Python standard library, so they are stable across
environments.
