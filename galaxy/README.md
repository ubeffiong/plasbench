# PlasBench for Galaxy

`plasbench_score.xml` is the first Galaxy wrapper. It exposes the stable scoring
engine as a standalone tool with explicit FASTA, PAF, and truth-table inputs.

Before publishing to the Galaxy Tool Shed:

1. publish a versioned PlasBench container to Quay or GHCR and replace
   `YOUR_QUAY_NAMESPACE` in the wrapper;
2. add the complete assembly/prediction/alignment/aggregation/report wrappers;
3. create a Galaxy workflow accepting paired-read and reference collections;
4. run `planemo lint galaxy/plasbench_score.xml` and `planemo test galaxy/plasbench_score.xml`;
5. copy `.shed.yml.example` to `.shed.yml`, set the Tool Shed owner and GitHub org,
   then publish with a Tool Shed account.

The public workflow should use preloaded, versioned MOB-suite and Platon databases;
jobs must not download databases at runtime.
