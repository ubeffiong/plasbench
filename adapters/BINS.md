# Bin Membership Contract

Write `pred_<tool>.bins.tsv` beside the standardized prediction FASTA:

```tsv
bin_id	sequence_id
plasmid_bin_1	contig_001
plasmid_bin_1	contig_002
```

Each FASTA record must occur once. `bin_id` denotes a biologically intended
plasmid reconstruction; it is not merely a FASTA filename. Stage 5 emits a
one-to-one `*.bin_matches.tsv` when this file exists. Legacy tools without a
membership table remain base-level only and are labelled accordingly.
