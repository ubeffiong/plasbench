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

### Self-built hybrid truth (`truth_source=self_assembled_hybrid`)

Some cohort sources deposit long+short reads without ever formally submitting a
finished assembly (see `docs/FINDING_DATA.md`'s Route C). For these,
`python/build_hybrid_truth.py` builds the truth reference itself: a Unicycler
hybrid assembly (long + paired-short reads), labelled chromosome/plasmid from
Unicycler's own reported topology alone — a circular contig at or above a
configurable minimum length (`HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH`, default
1,500,000 bp) is chromosome, every other circular contig is plasmid. This is
deliberately the same kind of signal `make_truth.py` uses for an NCBI-deposited
assembly (a submitter's own topology declaration), never a gene-content
classifier: several of those (`mob_recon`, PlaScope, RFPlasmid, geNomad, ...)
are themselves benchmarked prediction tools here, and building "truth" from one
would make it trivially perfect against itself. A non-circular contig anywhere
in the assembly, or more than one contig clearing the chromosome-length bar,
means the result is not a trustworthy complete reference — the sample is
rejected outright, never scored against a partial or uncertain truth. Unicycler
is not itself a benchmarked plasmid caller in this project, only an assembler
(the same role `ASSEMBLER=unicycler` already gives it for short-read
assemblies).

A self-built truth is, by construction, never independent of the long reads
that built it. `validate_cohort.py` enforces this as a schema rule, not a
judgment call: a `self_assembled_hybrid` row may never declare
`truth_independent_of_long_reads=yes`. Left unset — the only allowed state —
`scripts/lib.sh`'s existing `long_read_truth_eligible()` guard applies
unchanged, so every long-read/hybrid tool is automatically excluded from
scoring on these samples; they contribute to the short-read track only.

### Simulated reads from a real reference (`truth_source=simulated`)

The mirror image of self-built hybrid truth above: `assembly_accession` is a REAL,
independently-deposited Complete Genome assembly (required, downloaded and used as truth
unchanged — checked online by `validate_cohort.py`'s `verify_simulated_row()` against the
exact same Complete-Genome/plasmid-replicon bar as an `ncbi_deposited` row), but the reads
are not real sequencing data: `python/simulate_reads.py` generates them locally with
InSilicoSeq (short reads) and Badread (long reads) at a depth, seed, and error model
declared in the cohort sheet (`simulation_seed`, `simulation_short_depth_x`,
`simulation_long_depth_x`, and two optional error-model columns). `sra_run` is reused as
the local read-file prefix for these rows, never a real SRA accession, so
`validate_cohort.py` does not apply its SRR/ERR/DRR pattern check to it.

Short-read depth is applied UNIFORMLY across every reference contig (chromosome and
plasmid(s) alike) via InSilicoSeq's `--coverage_file`, a documented simplification rather
than a per-replicon depth model. Badread's read-length distribution is deliberately left at
its own natural default rather than forced to a fixed length, unlike some published
simulation pipelines that fix every long read to exactly 10,000 bp — a real fidelity choice
worth flagging, not copying uncritically, since real long-read runs are not length-uniform.

Because the reference is real and independently deposited, a `simulated` row's truth is, by
construction, independent of whatever reads (real or simulated) exist for it — the opposite
relationship from `self_assembled_hybrid` above, where the truth is built FROM the reads. A
`simulated` row may therefore freely declare `truth_independent_of_long_reads=yes` with no
special restriction. The HTML report still marks every simulated sample with its own
distinct "simulated reads" badge (never the same badge as `self_assembled_hybrid`'s
"self-built truth"), so a simulated isolate can never be silently read as a real-world
result.

### Difficulty descriptors (benchmark-only, never a live recommendation input)

`python/compute_difficulty_features.py` (gated by `RUN_DIFFICULTY_FEATURES`, off by
default; run in stage 3, once this isolate's own assembly graph exists) computes three
signals for how intrinsically hard *this isolate* is to correctly separate into plasmid
vs. chromosome, independent of any tool's own performance on it:

- **`gfa_dead_end_count`** — the assembly graph's own dead-end count
  ([rrwick/GFA-dead-end-counter](https://github.com/rrwick/GFA-dead-end-counter), the
  same author as Filtlong and Trycycler), a direct fragmentation signal.
- **`plasmid_chromosome_depth_ratio`** — median plasmid-contig depth divided by median
  chromosome-contig depth, from aligning this isolate's own short reads back to its
  truth reference (`minimap2` + `samtools coverage`).
- **`plasmid_chromosome_mash_distance`** — the minimum Mash distance between this
  isolate's own truth plasmid sequence(s) and its own truth chromosome. A plasmid
  sharing many k-mers with its own chromosome (shared IS elements, integrated regions)
  is intrinsically harder to correctly separate for every tool, not just a weak one; the
  *minimum* across a multi-plasmid isolate's plasmids is reported, since the most
  chromosome-similar plasmid is the harder case to flag.

Each of the three fields is independently optional: a missing prerequisite (no assembly
graph, no reads, the external tool not installed) leaves that field empty, never a
guessed or zero value — the same convention every other optional per-isolate feature in
this project follows.

**These are truth-derived, exactly like `plasmid_count` and Inc-type stratification, and
follow the same rule: benchmark-only descriptors, never wired into
`recommendation_model.py`.** A genuinely unknown operational isolate has no truth
reference to compute a plasmid-vs-chromosome Mash distance or depth ratio from, so
feeding these to a live recommendation model would be leakage, not a real feature —
`recommendation_model.py`'s `ASSEMBLY_STAT_FIELDS` deliberately excludes them, with that
exclusion stated in code so it cannot be "fixed" accidentally later.

### QUAST supplementary diagnostics (`RUN_QUAST_DIAGNOSTICS`, off by default)

`python/run_quast_diagnostics.py` (stage 5) runs QUAST three ways per sample/tool,
against the SAME predicted-plasmid FASTA: a `combined` reference (every truth plasmid
in one multi-FASTA), one `individual` run per truth plasmid, and a `chromosome`-only
reference. This is C-Connor/PlasmidToolBenchMarking's own verified pattern (a sibling
plasmid-tool benchmarking pipeline), reused here for a genuinely different purpose:
explaining WHY a low F1 happened (a high chromosome-reference genome fraction means the
tool's "plasmid" call actually contains substantial chromosome sequence; an uneven
per-plasmid genome fraction means recall is concentrated in one plasmid, not spread
evenly), never replacing `score_plasmids.py`'s own base-level precision/recall/F1 as the
ranking metric. `--min-contig 0` is always passed explicitly — QUAST's own default
(500 bp) would otherwise silently drop short plasmid contigs from the analysis, exactly
the kind of hidden filtering this project avoids elsewhere. Report.tsv is parsed by ROW
LABEL ("Genome fraction (%)", "# misassemblies", "Duplication ratio"), never a fixed row
position, since QUAST only emits fields applicable to a given run. Real per-tool-per-
sample compute cost (up to `2 + n_truth_plasmids` QUAST invocations), so off by default
like every other optional diagnostic in this project.

### Equal CPU allocation across tools (fairness policy)

Every registered tool gets its own `<TOOL>_THREADS` config variable, defaulting to the
same shared `$THREADS` value — never a tool-specific hardcoded thread count, and never one
tool silently favored with more CPU than another by default. This is a deliberate fairness
policy, not an accident of how the config file grew: a tool given more threads than its
competitors runs faster (and, for a genuinely parallelizable step, sometimes also more
accurately, e.g. via better default heuristics tuned for multi-core execution) for reasons
that have nothing to do with the tool itself. C-Connor/PlasmidToolBenchMarking, a sibling
plasmid-tool benchmarking pipeline, states this concern explicitly and independently: its
own Nextflow configuration labels every tool process `process_8` (8 CPUs each), applied
uniformly "even if the tool does not support multi-threading" — external validation that
this is a real methodological concern in this space, not a PlasBench-specific scruple.

An audit of every `<TOOL>_THREADS` variable against its tool's real invocation (2026-09-08)
found the policy correctly wired for every tool that actually accepts a thread-count flag,
with three exceptions worth recording:

- **`flye_mob_recon` and `plassembler`** previously used the general `$THREADS` value
  directly in their Flye/MOB-Recon/Plassembler invocations, with no dedicated override
  variable of their own — inconsistent with every other tool's own `<TOOL>_THREADS`
  pattern (though not itself unfair, since the shared default was still identical for
  every tool). Fixed: both now have their own `FLYE_MOB_RECON_THREADS`/
  `PLASSEMBLER_THREADS` variables, defaulting to `$THREADS` like everywhere else.
- **`GPLAS_THREADS`** exists but is not actually wired into any invocation: the `gplas`
  binary itself takes no thread flag (confirmed single-threaded), and neither
  `python/mob_to_gplas_classifier.py` nor `python/validate_gplas_classifier.py`
  (gplas2_mob's/gplas2_external's own classifier-prep steps) accept one either — both are
  lightweight single-threaded table/graph transformations. The variable is kept for
  interface consistency with every other tool's own `<TOOL>_THREADS` var, with its
  `config/config.sh` comment corrected to say so plainly, rather than silently deleted or
  left with a misleading comment implying it does something it does not.
- **`plASgraph2`**'s adapter invocation passes no thread-count flag at all, and whether
  `plASgraph2_classify.py` even accepts one has not been verified this pass — recorded
  here as an open question for whoever next revisits this policy, not silently assumed
  either way.

#### Thread-scaling sweep (`scripts/thread_scaling_sweep.sh`, opt-in)

An empirical check for the fairness policy above, not just a documentation claim: reruns
ONE already-registered tool on a small, already-assembled sample subset at several
thread counts (default 1/4/8), reusing `scripts/04_run_tools.sh`'s own `ONLY_TOOL`
restriction and its existing `profile_exec`/RSS-capture instrumentation — the SAME
`tool_status.tsv` `runtime_seconds`/`peak_rss_kb` columns a normal run already writes,
never a second profiling mechanism. Writes
`results/thread_scaling_sweep.<tool>.tsv` (`tool, sample, threads, runtime_seconds,
peak_rss_kb`). Every sweep point is force-rerun (a cached "reused" result would report a
stale runtime from a different thread count), so this only ever touches stage 4, never
stages 1-3.

```bash
bash scripts/thread_scaling_sweep.sh --tool platon --samples s1,s2 --threads 1,4,8
```

Answers whether the leaderboard's own runtime numbers (and, for a genuinely
parallelizable step, sometimes its reported accuracy too) depend on the thread-count
choice a tool happens to be given — not run automatically, since it multiplies one
tool's own stage-4 runtime by the number of sweep points.

### Research and investigation scripts (one-off, never part of the pipeline)

Two scripts exist purely to investigate open questions raised by the sibling-repo
cross-pollination review, matching `python/parse_teixeira2025_supplement.py`'s own
"one-time migration/investigation script" precedent — neither is wired into any stage
script, gated behind a config toggle, or run automatically. Run them by hand; each
script's own module docstring is the full usage reference.

- **`python/audit_three_class_scoring.py`** — checks whether PlasBench's binary
  plasmid/chromosome truth model is missing something RasmussenLab/PlasMAAG models
  explicitly as a third class (`candidate_virus`): does any curated isolate's truth
  reference contain an INTEGRATED PROVIRUS region embedded inside a truth plasmid or
  chromosome sequence? Runs geNomad's own provirus-finding (on by default in
  `genomad end-to-end`, confirmed from geNomad's own source) against the truth
  reference itself, and cross-references its real `<prefix>_virus_summary.tsv` output
  (specifically its `coordinates`/`seq_name` columns — verified from geNomad's own
  documentation, not assumed) against truth.tsv's own sequence boundaries. A research
  script, not a fix: per the approved plan, a three-class scoring change is only worth
  designing if running this across a real cohort finds a genuine, non-trivial incidence
  — this script has not yet been run against real cohort data (it requires a geNomad
  database this project's own development environment does not have installed), so
  that finding is still outstanding for whoever runs it next.
- **`python/compare_scoring_methods.py`** — cross-checks PlasBench's own minimap2-based
  scoring (`score_plasmids.py`'s exact interval-merge) against
  C-Connor/PlasmidToolBenchMarking's own verified BLASTN command (confirmed by direct
  fetch of `modules/BlastContigs/main.nf`: `blastn -perc_identity 80 -evalue 1E-20
  -culling_limit 1 -max_target_seqs 10000 -dust no -outfmt '6 qseqid qlen sseqid slen
  length pident qcovhsp' -subject <reference> -query <prediction>`), for the SAME
  sample/tool. That repo's own chosen `-outfmt` has no alignment coordinates to
  interval-merge exactly, so this script computes a clearly-labeled, capped
  hit-length proxy F1 rather than claiming methodological equivalence, and reports it
  next to PlasBench's own real (never re-derived) F1 from an existing `scores.tsv` row.

## Predictions
Each tool emits a set of sequences it considers plasmid. A thin per-tool adapter
(`adapters/`) normalises these disparate outputs into a single **predicted-plasmid FASTA**:
- classification tools (Platon, mob_recon) → the contigs/bins they labelled plasmid;
- re-assembly tools (plasmidSPAdes, gplas) → their reconstructed plasmid contigs.

The default workflow consumes paired short-read FASTQs, usually Illumina, and
long reads establish the complete reference. Long reads are ALSO a native
prediction input for the tools that take them: `flye_mob_recon`,
`hybracter_long` and `trycycler_mob_recon` (long reads alone), and
`plassembler` and `hybracter_hybrid` (long + short). Each is off by default.
Where a tool sits is a declared registry property (`analysis_track` in
`config/tool_capabilities.tsv`), so every score is stamped with the track it
was earned on and leaderboards are written per track, never pooled -- see
"Recommendation validation and tracks" below and the circularity section.

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

### Zero-true-plasmid isolates: undefined ratios and negative-control metrics

An isolate with no true plasmid at all (`total_plasmid` = 0) makes recall and F1
mathematically undefined (0/0), and makes precision undefined too whenever nothing
was predicted (TP + FP = 0). PlasBench reports these as empty (`""`), never a
misleading `0.0` — a `0.0` would read as total failure for a tool that in fact
correctly abstained. Precision *is* still a real, defined number whenever something
*was* predicted on such an isolate (TP is always 0 there, so precision is exactly
0.0 — a genuine, meaningful "of what you predicted, none was correct").

Because such an isolate is the only kind that can directly measure a tool's
false-positive plasmid-calling behaviour (there is nothing true to recall, so
anything predicted is by construction a false positive), `score_plasmids.py` also
reports three fields specifically for this purpose, defined for every isolate but
most informative on a zero-true-plasmid one:
- **`isolate_specificity`** — the classic true-negative rate: the fraction of the
  isolate's chromosome correctly *not* claimed as plasmid (`1 − FP/total_chromosome_bp`).
- **`chromosome_fp_bp`** — raw false-positive base count (an explicit alias for FP,
  named for this negative-control context).
- **`fp_predicted_record_count`** — how many distinct predicted records contributed
  any false-positive coverage, a record-level complement to the base-level count.

These are never blended into the main precision/recall/F1 ranking; the leaderboard
carries them as a separate summary (`n_zero_plasmid_isolates`,
`mean_zero_plasmid_specificity`, `total_zero_plasmid_chromosome_fp_bp`) restricted to
isolates that actually have zero true plasmids.

## Plasmid-level recovery
In addition to base-level F1, PlasBench reports the number of true plasmid
replicons and the number recovered to at least the configured fraction of their
reference length (default 90%). `plasmid_recall` is the fraction of true
replicons meeting that threshold. `predicted_record_count` is intentionally a
sequence-record proxy, not a bin-level precision claim: tools differ in whether
they output one contig, multiple contigs, or one FASTA per plasmid bin.

### Graded plasmid-recovery completeness tiers (supplementary, never a ranking replacement)
`plasmid_recall` answers one question at one configured threshold: recovered, or not.
`score_plasmids.py` additionally computes each true plasmid's own per-plasmid
completeness fraction once (covered bp / reference length) and reports it against two
further FIXED bands, independent of `--plasmid-recovery-threshold`:

- **`plasmid_recall_ge50`** — fraction of true plasmids at least half covered.
- **`plasmid_recall_ge90`** — fraction of true plasmids at least 90% covered.
- **`complete_circular_plasmid_recall`** — fraction of the isolate's CIRCULAR true
  plasmids that are essentially fully covered (matching `merge_bin_metrics.py`'s own
  "essentially 1.0" convention for its perfect-recovery label) — the strictest
  per-plasmid claim this script makes. Only defined when circular-truth evidence was
  supplied at all (`--circular-plasmids`); reported as not-applicable, never a fabricated
  0, otherwise.

These fill a genuine gap between "any recall" and the whole-sample "Perfect reference
recovery"/"Strict reconstruction" labels (`merge_bin_metrics.py`'s `perfect_metrics()`,
which score every predicted base across the WHOLE sample at once, not one plasmid at a
time): a tool that gets every plasmid to 60% complete and one that gets half its plasmids
to 100% complete can land on the same `plasmid_recall` and the same `mean_f1`, yet
represent very different practical outcomes. None of these bands replace `mean_f1` as the
ranking metric or `mean_plasmid_recall` as the primary completeness figure; the HTML
report surfaces them in their own "Graded plasmid recovery" section, explicitly labeled as
supplementary.

For adapters that supply `pred_<tool>.bins.tsv`, PlasBench also performs
deterministic global one-to-one bin matching using a maximum-weight assignment,
not a greedy first-match rule. A bin is eligible for a truth plasmid only when
it reaches the configured completeness and purity thresholds. Bin
precision/recall/F1 use these assignments; split events count extra qualifying
bins for one truth plasmid, merge events count extra qualifying truth plasmids
for one bin, and chromosome-aligned bin bases are reported separately.
The same all-mapping diagnostic records repeat-associated ambiguity per bin.

### NMI and Variation of Information (supplementary, never a replacement)

Bin precision/recall/F1 above are computed only from the *matched* bin-plasmid
pairs the maximum-weight assignment picks — a tool that merges every plasmid into
one giant bin, or leaves plasmid sequence completely unassigned, is not
automatically penalised by that alone. `score_bins.py` additionally computes
**Normalized Mutual Information (NMI)** and **Variation of Information (VI)** over
a deliberately wider, bp-weighted contingency table: every predicted bin as a row,
every true plasmid as a column, plus two virtual categories — an
`"__unassigned__"` row for true-plasmid bp no bin covers at all, and a
`"CHROMOSOME"` column for chromosome bp a bin wrongly claims. Chromosome bp no bin
ever claims (the correct, desired outcome for most of a bacterial genome) is
deliberately excluded, so the metric is not swamped by an enormous, uninteresting
"true negative" mass.

NMI uses the arithmetic-mean normalization (`2·I(X,Y) / (H(X)+H(Y))`, natural log),
matching scikit-learn's `normalized_mutual_info_score` convention so it can be
cross-checked against a familiar reference. A single-point-mass distribution on
both sides scores NMI = 1.0 (perfect agreement by construction); a single-point-mass
on only one side scores NMI = 0.0 (no information could be shared with the other
side's real variability) — the same convention scikit-learn uses. This means NMI
alone cannot distinguish a genuinely independent (random) assignment from a single
giant merged bin, since both collapse to the same zero-entropy shortcut; **VI's
unnormalized scale is what actually orders them** (a merged bin is a smaller
information loss than true independence). Both are reported together for exactly
this reason, and both are strictly supplementary — the leaderboard's ranking stays
on mean F1, never NMI/VI, and they are absent (`""`, never `0`) whenever the
contingency table is empty or the tool is not `binning_capable`.

## Structural and AMR evidence

### External evaluator cross-checks

PlasBench's native base, bin, split/merge, contamination, AMR, and QUAST
diagnostics remain the source of its native results. An external evaluator such
as PlasEval can be useful as a supplementary structural cross-check, but its
metrics must be archived with its exact version, command, truth definition, and
source citation using `plasbench import-external-benchmark`; they are not mixed
into `scores.tsv`, the native leaderboard, or operational recommendations.
This prevents a superficially similar metric from silently changing a published
rank. PlasEval integration becomes a first-class adapter only after its
versioned input/output contract and a regression fixture are available.

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

**Significance vs. the runner-up.** The leaderboard's `significant_vs_runner_up`
column asks one specific, narrow question: on the samples the top-ranked and
second-ranked tool actually *share*, is the mean F1 difference between them
distinguishable from chance? This is derived from the same paired data as
`benchmark.paired_comparisons.tsv`, using a two-sided sign-flip permutation test on
the paired per-sample F1 differences (10,000 permutations, a deterministic seed),
with Holm's method controlling the family-wise error rate across every pairwise
tool comparison computed in the same run. `True` only when the Holm-adjusted
p-value is below 0.05 **and** there are at least 5 paired samples (the permutation
test's own minimum — fewer than that returns no p-value at all, never a fabricated
one); otherwise `not_assessed`. This is deliberately **not** based on whether the
two tools' bootstrap confidence intervals overlap — CI overlap is a weaker,
different, and more conservative test than a paired permutation test on the same
shared samples, and the two can disagree. Like every other number in this
benchmark, a `True` here describes this cohort, not a general claim that the tool
is better in the field.

## Known limitations / honest caveats
- **Base-level, not object-level, but not blind to it either.** The core metric
  rewards recovering plasmid *sequence*, not object-level correctness on its own —
  but PlasBench also reports bin-level precision/recall/F1, split/merge events, and
  (see above) NMI/Variation of Information specifically so a tool that splits one
  plasmid into two bins, or merges two into one, is not invisible to the benchmark.
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
- **Organism-dependent tool failure is a documented, published phenomenon, not
  over-engineering.** Teixeira et al., "Circling in on plasmids: benchmarking
  plasmid detection and reconstruction tools for short-read data from diverse
  species" (*Briefings in Bioinformatics*, 2025; DOI 10.1093/bib/bbaf589) report
  that PlasBin-Flow failed to detect any enterococcal plasmids in their benchmark,
  despite functioning on other taxa. PlasBench's `organism`/`gram_group`
  stratification throughout the leaderboard and recommendation logic exists
  precisely because tool performance is not taxon-independent — this is external,
  peer-reviewed confirmation of that design choice, not a hypothetical.

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

Optionally (`RUN_RECOMMENDATION_MODEL=1`, off by default), a hand-rolled
ridge regression replaces the recommendation formula's F1/plasmid-recall
terms with predictions from an isolate's own continuous features -- read
depth, plasmid size and count, plus GC content, N50, contig count and
assembly size computed from that isolate's reference during stage 2. At
sufficient cohort scale (default: 60 rows and 5 source studies), its ridge
penalty is selected in an inner study-level LOSO loop and evaluated only on an
outer held-out study. Below that scale, PlasBench records an **approximate
LOSO** result instead: the same folds choose lambda and estimate MAE, so its
apparent improvement can be optimistic. Every fit writes
`benchmark.recommendation_model.card.md` with input checksums, observed scope,
validation strategy/results, and limitations. The model is never used unless
it demonstrably beats the plain per-tool mean under its declared folds. This
is a descriptive recommendation, not a scoring change, and is not validated
beyond the cohorts it was fit on. See `docs/USER_GUIDE.md`'s "Decision-support
recommendation model" section.

## Long-read and hybrid tools and the circularity constraint

Five tools assemble plasmids from long reads: Flye+MOB-Recon, Hybracter
(long-only mode) and Trycycler+MOB-Recon on the long-read track, and
Plassembler and Hybracter (hybrid mode), which add short reads on top. That
creates a problem the short-read tools never had.

PlasBench's truth labels come from a complete long-read or hybrid assembly. If
a long-read or hybrid tool is given the same long reads that produced that
assembly, it is being scored against its own input: it would look near-perfect
for reasons that say nothing about the tool. A short-read tool has no such
exposure, because its input is genuinely independent of the truth.

The pipeline therefore refuses by default. This is a declared, per-tool
property in `config/tool_capabilities.tsv`
(`requires_independent_long_read_truth=yes`), not something hardcoded to one
tool -- every long-read/hybrid tool gets it automatically. A sample is
eligible for such a tool only when the cohort declares independence
explicitly, in a `truth_independent_of_long_reads` column set to `yes`.
Anything else -- absent column, empty value, `no` -- is recorded as
`circular truth: truth_technology=<X> derives from the supplied long reads`
and skipped. Each affected tool has its own override variable, named
`<TOOL>_ALLOW_CIRCULAR_TRUTH` after the tool's registry name
(`FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH=1`, `PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1`,
`HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH=1`,
`HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH=1`,
`TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH=1`). It overrides this globally and
stamps every affected row in `tool_status.tsv`, so a compromised result can
never be mistaken later for an independent one. A new long-read tool inherits
both the guard and its own override variable from its registry row alone; see
docs/COHORTS.md for the curator-facing version of this table.

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
