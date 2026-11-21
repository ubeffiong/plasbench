#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
label: Concatenate score tables
doc: Stack the one-row score tables of PlasBench score into one table with a single header row, the input PlasBench aggregate expects.
requirements:
  ShellCommandRequirement: {}
hints:
  DockerRequirement:
    dockerPull: ghcr.io/ubeffiong/plasbench:v0.5.6
baseCommand: awk
arguments:
  - 'FNR==1 && NR!=1 {next} {print}'
inputs:
  tables:
    type: File[]
    inputBinding: {position: 1}
stdout: scores.combined.tsv
outputs:
  combined:
    type: stdout
s:license: https://spdx.org/licenses/GPL-3.0-only
$namespaces:
  s: https://schema.org/
