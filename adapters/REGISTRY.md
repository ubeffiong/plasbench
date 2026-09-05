# Adapter Registry

Every PlasBench tool adapter must produce `pred_<tool>.plasmid.fasta`. An empty
FASTA is a valid completed prediction; an adapter must exit non-zero only when
its output cannot be interpreted safely. The pipeline then records a failure
rather than assigning an artificial zero score.

| Tool | Method class | Bin diagnostics | Input | Adapter | Status |
|---|---|---|---|---|---|
| MOB-suite | binning | applicable | short-read assembly | `adapt_mob_recon.sh` | supported |
| Platon | classification | not applicable | short-read assembly | `adapt_platon.sh` | supported |
| plasmidSPAdes | reassembly | not applicable | paired reads | `adapt_plasmidspades.sh` | supported |
| gplas2_mob | binning | applicable | GFA graph plus MOB-recon hard-label seed TSV | native mode | optional |
| gplas2_external | binning | applicable | GFA graph plus user classifier TSV | native mode | optional |
| flye_mob_recon | binning | applicable | long reads | `adapt_mob_recon.sh` | optional |
| plassembler | reassembly | applicable | long + short reads (hybrid) | `adapt_plassembler.sh` | optional |
| hybracter_long | reassembly | applicable | long reads | `adapt_hybracter.sh` | optional |
| hybracter_hybrid | reassembly | applicable | long + short reads (hybrid) | `adapt_hybracter.sh` | optional |
| trycycler_mob_recon | binning | applicable | long reads | `adapt_mob_recon.sh` | optional |
| geNomad | ml_classification | not applicable | short-read assembly | `adapt_genomad.sh` | optional |
| PLASMe | ml_classification | not applicable | short-read assembly | `adapt_plasme.sh` | optional |

The machine-readable source is `config/tool_capabilities.tsv`. Stage 5 only
computes bin metrics for declared binning methods; the report labels all other
tools as not applicable rather than assigning a misleading low bin score.

## gplas2 contract

`gplas2` is graph based and requires both an assembly graph and a binary
classifier prediction table. `gplas2_mob` generates this table only when the
successful MOB-recon output and graph use the same contig identifiers. MOB
plasmid membership becomes deterministic 1/0 seed labels; these values are not
calibrated probabilities. The generated provenance JSON records input checksums,
eligible graph-node counts, and label counts. A mismatch fails safely rather
than relabelling an incompatible graph.

`gplas2_external` still requires a classifier table generated from the same
graph's extracted nodes, with documented classifier/database versions.

This contract supports current and future external methods without coupling
the core benchmark to unstable third-party command-line interfaces. Enable
`RUN_GPLAS2_MOB=1` or `RUN_GPLAS2_EXTERNAL=1`. The MOB mode requires gplas,
an assembly graph, and successful `mob_recon`; it writes its evidence under
`results/<sample>/gplas2_mob/`. External mode reads
`$GPLAS2_EXTERNAL_PREDICTIONS_DIR/<sample>.tsv`.

## adapt_plassembler.sh

`plassembler run` writes `<prefix>_plasmids.fasta`, one contig per assembled
plasmid. Unlike a contig classifier the output is already plasmid-level, so each
record becomes its own bin. Headers carry copy-number fields
(`>1 len=2000 copy_number_short_read=2.5`); the first whitespace-delimited token
is taken as the sequence id.

Plassembler deliberately writes an EMPTY `_plasmids.fasta` when it finds no
plasmids, so that workflow managers see a file either way. That is a real
prediction -- "this isolate has no plasmids" -- and the adapter succeeds on it,
emitting an empty prediction to be scored as such. Treating it as a failure would
drop the isolate from the denominator and flatter the tool.

    adapt_plassembler.sh <plassembler_out_dir> <unused_base_asm> <out_fasta>

## adapt_hybracter.sh

`hybracter long-single`/`hybracter hybrid-single` write a `<prefix>_plasmid.fasta`
(singular) per sample, one contig per assembled plasmid -- Hybracter uses
Plassembler internally for plasmid recovery, so the output shape and header
convention (copy-number fields, first whitespace token as id) match
`adapt_plassembler.sh`'s. Unlike Plassembler's fixed output directory, the exact
path under Hybracter's `FINAL_OUTPUT/` varies (`complete/` vs `incomplete/`
depending on assembly completeness), so this adapter searches recursively for
`*_plasmid.fasta` rather than assuming one fixed location. An empty result is a
valid "no plasmids" prediction, scored as such, same as Plassembler.

    adapt_hybracter.sh <hybracter_out_dir> <unused_base_asm> <out_fasta>

## adapt_genomad.sh (ML classifier, see adapters/SCORES.md)

`genomad end-to-end` writes `<prefix>_summary/<prefix>_plasmid.fna` (the
tool's own hard call, taken unchanged) and
`<prefix>_aggregated_classification/<prefix>_aggregated_classification.tsv`
(one row per INPUT contig -- not just the hard call -- with a `plasmid_score`
column). The adapter takes the hard call as-is, and additionally emits
`pred_genomad.candidates.fasta` + `pred_genomad.scores.tsv` (the wider
candidates universe, extracted from the base assembly FASTA by matching
`seq_name` in the aggregated classification table) so stage 5 can sweep a
PR-curve alongside the point estimate. geNomad is a per-contig classifier
with no grouping output, so `bins.tsv` is always header-only (matching
`adapt_platon.sh`'s convention) -- `binning_capable=no` in
`config/tool_capabilities.tsv` is what actually decides "not applicable",
not the adapter.

    adapt_genomad.sh <genomad_out_dir> <base_assembly_fasta> <out_fasta>

## adapt_plasme.sh (ML classifier, see adapters/SCORES.md)

`PLASMe.py INPUT_CONTIG OUTPUT_PLASMIDS` writes an explicit output FASTA
(the tool's own hard call, per its `-p/--probability` threshold) and a
sibling `OUTPUT_PLASMIDS_report.csv` (`contig, length, reference, order,
evidence, score, amb_region`) covering every contig PLASMe's alignment+
transformer pipeline scored, not just the ones passing the threshold --
PLASMe's own docs describe this `score` column as meant for exactly this
kind of PR-curve sweep. `scripts/04_run_tools.sh`'s `run_plasme()` invokes
PLASMe with a fixed, adapter-known output filename
(`plasme_output.fasta`) inside its own per-tool directory so this adapter
can find both files reliably. Like Platon and geNomad, PLASMe is a
per-contig classifier with no grouping output, so `bins.tsv` is always
header-only.

PLASMe itself is distributed as a git checkout with its own conda
environment, not a bioconda package -- `PLASMe.py` is expected on PATH
after manual setup, the same convention this project already documents for
gplas2 (see INSTALL.md).

    adapt_plasme.sh <plasme_out_dir> <base_assembly_fasta> <out_fasta>

## trycycler_mob_recon (no new adapter)

Trycycler is a reconciler, not an assembler: `scripts/07_long_read_reconstruct.sh`
runs several independent Flye assemblies, reconciles them into one consensus
FASTA per replicon, concatenates the surviving clusters' consensus sequences
into one assembly FASTA, then runs `mob_recon` on that assembly exactly as
`flye_mob_recon` does on Flye's own single assembly -- so it reuses
`adapt_mob_recon.sh` completely unchanged. A cluster that fails to reconcile
is dropped rather than failing the whole sample; see `docs/USER_GUIDE.md`'s
Long-Read Reconstruction section for the exact policy.
