# Adapter Registry

Every PlasBench tool adapter must produce `pred_<tool>.plasmid.fasta`. An empty
FASTA is a valid completed prediction; an adapter must exit non-zero only when
its output cannot be interpreted safely. The pipeline then records a failure
rather than assigning an artificial zero score.

| Tool | Input | Adapter | Status |
|---|---|---|---|
| MOB-suite | short-read assembly | `adapt_mob_recon.sh` | supported |
| Platon | short-read assembly | `adapt_platon.sh` | supported |
| plasmidSPAdes | paired reads | `adapt_plasmidspades.sh` | supported |
| gplas | GFA graph | `adapt_gplas.sh` | experimental |
| gplas2_mob | GFA graph plus MOB-recon hard-label seed TSV | native mode | optional |
| gplas2_external | GFA graph plus user classifier TSV | native mode | optional |

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
