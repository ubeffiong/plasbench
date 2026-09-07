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
| plASgraph2 | ml_classification | not applicable | assembly graph | `adapt_plasgraph2.sh` | optional |
| RFPlasmid | ml_classification | not applicable | short-read assembly | `adapt_rfplasmid.sh` | optional |
| PlaScope | classification | not applicable | short-read assembly (E. coli/Klebsiella only) | `adapt_plascope.sh` | optional |

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

## adapt_plasgraph2.sh (ML classifier, see adapters/SCORES.md)

`plASgraph2_classify.py gfa <graph.gfa.gz> <model_dir> <output.csv>` writes a
single CSV, one row per contig above the tool's own 100bp length cutoff:
`sample,contig,length,plasmid_score,chrom_score,label` (label in {plasmid,
chromosome, ambiguous, unlabeled}). Unlike geNomad/PLASMe, plASgraph2 writes
no separate hard-call FASTA of its own -- the CSV is the only output -- so
this adapter derives the hard call itself (`label == "plasmid"` rows,
sequences extracted from the base assembly FASTA by contig id) rather than
taking a tool-written FASTA unchanged. Every scored row is the candidates
universe the PR-curve sweep needs. plASgraph2 needs the same
`assembly_graph.gfa` gplas2 uses (gzipped first, since plASgraph2's own
examples only ever show a `.gfa.gz` input); `scripts/04_run_tools.sh`'s
`run_plasgraph2()` handles that gzip step before invoking the classifier.

plASgraph2 is a per-node classifier: it emits no bins/clusters/connected-
components output of its own, so -- like Platon/geNomad/PLASMe -- bins.tsv is
written header-only; `binning_capable=no` is what actually decides "not
applicable", not this adapter.

plASgraph2 itself is distributed as a git checkout (not a bioconda package)
with its own dependency set (TensorFlow, Spektral) and its pretrained model
shipped inside the checkout -- `PLASGRAPH2_MODEL_DIR` must point at it (e.g.
the checkout's `model/ESKAPEE_model/`) after manual setup; see INSTALL.md.

    adapt_plasgraph2.sh <plasgraph2_output_csv> <base_assembly_fasta> <out_fasta>

## adapt_rfplasmid.sh (ML classifier, see adapters/SCORES.md)

`rfplasmid --species SPECIES --input <dir-of-fasta> --out OUT_DIR` requires a
DIRECTORY of `*.fasta` files as input, not a single file, unlike
geNomad/PLASMe -- `scripts/04_run_tools.sh`'s `run_rfplasmid()` therefore
stages this sample's own `contigs.fasta` alone into a per-sample temp
directory before invoking it. RFPlasmid also auto-appends a timestamp to
`--out` if that path already exists, so `run_rfplasmid()` removes `OUT`
first and lets RFPlasmid create it fresh, rather than pre-creating it.

RFPlasmid writes one file, `prediction.csv` (an R `write.csv` table: header
names and string-typed cells double-quoted, numeric cells not), with a
`prediction` column (`"p"`/`"c"` hard call), a `votes plasmid` column (the
underlying random forest's plasmid vote fraction, in [0,1] -- the
continuous score the PR-curve sweep needs), and a `contigID` column (the
original input FASTA record's own description, confirmed directly from
RFPlasmid's own source since its docs do not spell out these column names
precisely). RFPlasmid writes no separate hard-call FASTA of its own, so this
adapter reconstructs `pred_rfplasmid.plasmid.fasta` itself from the `"p"`
rows, rather than taking a tool-written FASTA unchanged (unlike
`adapt_genomad.sh`/`adapt_plasme.sh`). Like Platon/geNomad/PLASMe, RFPlasmid
is a per-contig classifier with no grouping output, so `bins.tsv` is always
header-only.

RFPlasmid's species/genus model is chosen via `RFPLASMID_SPECIES`
(`config/config.sh`); an unsupported species is RFPlasmid's own error, not
something this adapter or `run_rfplasmid()` pre-validates. RFPlasmid is a
real bioconda package, but bundles CheckM as a transitive dependency, and
CheckM always needs its own reference data directory configured once
post-install (`checkm data setRoot`) regardless of how it was installed --
see `env/install_tools.sh`'s `rfplasmid` case and INSTALL.md.

    adapt_rfplasmid.sh <rfplasmid_out_dir> <base_assembly_fasta> <out_fasta>

## adapt_plascope.sh

`plaScope.sh --fasta <assembly> -a <spades|unicycler> -o <out> --sample
<prefix> --db_dir ... --db_name ...` writes, under
`<out>/<prefix>_PlaScope/`, a `PlaScope_predictions/` directory containing
up to three FASTA files -- `<prefix>_plasmid.fasta`, `<prefix>_chromosome.fasta`,
`<prefix>_unclassified.fasta` -- from its own Centrifuge-based hard call, and
a `Centrifuge_results/` directory with the underlying classification table.
Each predictions file is written lazily and simply does not exist when zero
contigs landed in that class -- a missing `*_plasmid.fasta` is scored as
"predicted none", same policy as `adapt_platon.sh`/`adapt_plassembler.sh`.
`run_plascope()` passes `<out>/<prefix>_PlaScope` (not the raw `-o` value) as
this adapter's out_dir, so the sample prefix does not need to be known here
-- the plasmid FASTA is found by glob.

PlaScope produces no continuous per-contig score, only a hard
chromosome/plasmid/unclassified call, so `method_class=classification` (the
Platon/MOB-suite shape) -- no `candidates.fasta`/`scores.tsv`, and `bins.tsv`
is always header-only.

**Species gate (the tool's defining constraint):** PlaScope needs a
species-specific Centrifuge database, and only *E. coli* and *Klebsiella*
pre-built databases exist (Zenodo). `run_plascope()` looks up each sample's
`organism` column (`config/accessions.tsv` via `scripts/lib.sh`'s
`sample_column()`) and skips every other organism with a distinct
`"no PlaScope database for organism <X>"` reason in `tool_status.tsv` --
visibly different from a generic `"command unavailable"` skip, so a reader
understands it is a structural limitation of the tool, not a broken install.
See `env/download_plascope_db.sh` and `config/config.sh`'s
`PLASCOPE_ECOLI_DB`/`PLASCOPE_KLEBSIELLA_DB`.

    adapt_plascope.sh <plascope_prefix_dir> <unused_base_asm> <out_fasta>

## trycycler_mob_recon (no new adapter)

Trycycler is a reconciler, not an assembler: `scripts/07_long_read_reconstruct.sh`
runs several independent Flye assemblies, reconciles them into one consensus
FASTA per replicon, concatenates the surviving clusters' consensus sequences
into one assembly FASTA, then runs `mob_recon` on that assembly exactly as
`flye_mob_recon` does on Flye's own single assembly -- so it reuses
`adapt_mob_recon.sh` completely unchanged. A cluster that fails to reconcile
is dropped rather than failing the whole sample; see `docs/USER_GUIDE.md`'s
Long-Read Reconstruction section for the exact policy.
