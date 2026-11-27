#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
label: PlasBench aggregate
doc: |
  Combine per-sample score rows into a ranked tool leaderboard (galaxy/plasbench_aggregate.xml).
baseCommand: plasbench-aggregate
hints:
  EnvVarRequirement:
    envDef:
      PLASBENCH_HOME: /opt/plasbench   # where the v0.5.6 image keeps the pipeline; a path that does not exist is ignored outside the container
  DockerRequirement:
    dockerPull: ghcr.io/ubeffiong/plasbench:v0.5.8
  SoftwareRequirement:
    packages:
      - package: plasbench
        version: ["0.5.8"]
inputs:
  scores:
    type: File
    doc: Rows from PlasBench score, one header row then one row per sample and tool.
    inputBinding: {prefix: --scores}
  tool_status:
    type: File?
    doc: Optional table of which tool runs completed, were reused, skipped or failed.
    inputBinding: {prefix: --tool-status}
arguments:
  - {prefix: --out-prefix, valueFrom: benchmark}
outputs:
  leaderboard:
    type: File
    outputBinding: {glob: benchmark.leaderboard.tsv}
  leaderboard_markdown:
    type: File?
    outputBinding: {glob: benchmark.leaderboard.md}
s:license: https://spdx.org/licenses/GPL-3.0-only
$namespaces:
  s: https://schema.org/
