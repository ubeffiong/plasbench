#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: Workflow
label: PlasBench - align, score and aggregate predicted plasmids
doc: |
  Scores the predicted-plasmid FASTA of one or more plasmid-reconstruction tools for ONE isolate against its complete reference and ranks the tools
  (the PlasBench Galaxy tools as a CWL workflow): align each prediction to the reference with minimap2, score it against the labelled truth,
  stack the rows and aggregate them into a leaderboard.

  Inputs: the complete reference FASTA, its truth labels (TSV: sequence_id, molecule_type, length), and per tool one predicted-plasmid FASTA
  with a matching tool name. The stages that download isolates, assemble reads or run the reconstruction tools themselves are not part of this
  workflow (they run for hours and fetch data); use `plasbench run` for them. See https://github.com/ubeffiong/plasbench.
requirements:
  ScatterFeatureRequirement: {}
  StepInputExpressionRequirement: {}
inputs:
  reference:
    type: File
    doc: Complete reference assembly (FASTA) used as ground truth.
  truth:
    type: File
    doc: Truth labels of the reference sequences (TSV).
  predictions:
    type: File[]
    doc: One predicted-plasmid FASTA per tool.
  tool_names:
    type: string[]
    doc: The tool that produced each prediction, in the same order as predictions (letters, digits, dot, dash, underscore).
  sample:
    type: string
    default: sample
    doc: Isolate identifier (letters, digits, dot, dash, underscore).
  analysis_track:
    type:
      type: enum
      symbols: [short_read, long_read, hybrid]
    default: short_read
  plasmid_recovery_threshold:
    type: float
    default: 0.90
  preset:
    type: string
    default: asm5
steps:
  align:
    run: align.cwl
    scatter: prediction
    in:
      reference: reference
      prediction: predictions
      preset: preset
    out: [paf]
  score:
    run: score.cwl
    scatter: [paf, prediction, tool]
    scatterMethod: dotproduct
    in:
      truth: truth
      paf: align/paf
      prediction: predictions
      tool: tool_names
      sample: sample
      analysis_track: analysis_track
      plasmid_recovery_threshold: plasmid_recovery_threshold
    out: [scores]
  stack:
    run: concat_scores.cwl
    in:
      tables: score/scores
    out: [combined]
  aggregate:
    run: aggregate.cwl
    in:
      scores: stack/combined
    out: [leaderboard, leaderboard_markdown]
outputs:
  scores:
    type: File
    outputSource: stack/combined
    doc: Per-sample, per-tool scores.
  leaderboard:
    type: File
    outputSource: aggregate/leaderboard
    doc: Ranked tool leaderboard.
s:license: https://spdx.org/licenses/GPL-3.0-only
s:author:
  - class: s:Person
    s:name: Ubokobong Effiong
    s:url: https://github.com/ubeffiong
s:codeRepository: https://github.com/ubeffiong/plasbench
$namespaces:
  s: https://schema.org/
