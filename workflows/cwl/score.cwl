#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
label: PlasBench score
doc: |
  Score one predicted-plasmid FASTA against a complete reference whose sequences are labelled plasmid or chromosome
  (galaxy/plasbench_score.xml). One row of per-sample, per-tool scores.
baseCommand: plasbench-score
hints:
  EnvVarRequirement:
    envDef:
      PLASBENCH_HOME: /opt/plasbench   # where the v0.5.6 image keeps the pipeline; a path that does not exist is ignored outside the container
  DockerRequirement:
    dockerPull: ghcr.io/ubeffiong/plasbench:v0.5.6
  SoftwareRequirement:
    packages:
      - package: plasbench
        version: ["0.5.6"]
inputs:
  truth:
    type: File
    doc: TSV of reference truth labels (sequence_id, molecule_type, length). Ground truth comes from the reference, never from a tool being scored.
    inputBinding: {prefix: --truth}
  paf:
    type: File
    doc: PAF of the prediction on the reference (the align step, or any minimap2 PAF against the same reference).
    inputBinding: {prefix: --paf}
  prediction:
    type: File
    doc: The predicted-plasmid FASTA.
    inputBinding: {prefix: --pred-fasta}
  sample:
    type: string
    default: sample
    inputBinding: {prefix: --sample}
  tool:
    type: string
    default: tool
    doc: Which reconstruction tool produced the prediction, e.g. mob_recon.
    inputBinding: {prefix: --tool}
  analysis_track:
    type:
      type: enum
      symbols: [short_read, long_read, hybrid]
    default: short_read
    inputBinding: {prefix: --analysis-track}
  plasmid_recovery_threshold:
    type: float
    default: 0.90
    doc: Fraction of a truth plasmid that must be recovered for it to count as recovered.
    inputBinding: {prefix: --plasmid-recovery-threshold}
  min_alignment_length:
    type: int
    default: 200
    inputBinding: {prefix: --min-alignment-length}
  min_alignment_identity:
    type: float
    default: 0.90
    inputBinding: {prefix: --min-alignment-identity}
  min_alignment_mapq:
    type: int
    default: 20
    inputBinding: {prefix: --min-alignment-mapq}
  min_alignment_query_coverage:
    type: float
    default: 0.20
    inputBinding: {prefix: --min-alignment-query-coverage}
arguments:
  - {prefix: --out, valueFrom: scores.tsv}
outputs:
  scores:
    type: File
    outputBinding: {glob: scores.tsv}
s:license: https://spdx.org/licenses/GPL-3.0-only
$namespaces:
  s: https://schema.org/
