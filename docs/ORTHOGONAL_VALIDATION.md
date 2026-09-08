# Orthogonal Validation Evidence

Computational benchmark performance is not biological confirmation. PlasBench
can preserve optional independent evidence in a validated TSV. Supported types
are independent long-read confirmation, hybrid assembly, targeted PCR, plasmid
extraction, conjugation, Hi-C linkage, and optical mapping.

```text
sample_id  evidence_type  evidence_status  evidence_reference  notes
isolate_01 targeted_pcr supportive DOI:10.example/protocol  PCR supports blaCTX-M context; not a transfer assay.
```

`evidence_status` is `confirmed`, `supportive`, `inconclusive`, or
`contradicted`. A reference is required for every row. Use a public accession,
DOI, laboratory-record ID, or approved protocol ID; do not store sensitive
patient data in this file.

```bash
plasbench validate-orthogonal-evidence \
  --evidence orthogonal_evidence.tsv \
  --out results/orthogonal_validation.summary.json
```

The summary becomes downloadable in the normal report's Results explorer. It
does not alter F1, operational recommendations, host assignment, circularity,
or transmissibility claims. Those claims require their own suitable evidence.
