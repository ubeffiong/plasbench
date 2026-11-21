#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
label: PlasBench align
doc: |
  Align one predicted-plasmid FASTA onto the complete reference with minimap2, as the Galaxy wrapper does (galaxy/plasbench_align.xml):
  a primary-only PAF for scoring.
baseCommand: [minimap2, --secondary=no, -c]
hints:
  SoftwareRequirement:
    packages:
      - package: minimap2
        version: ["2.28"]
        specs: ["https://anaconda.org/bioconda/minimap2"]
  DockerRequirement:
    dockerPull: quay.io/biocontainers/minimap2:2.28--he4a0461_3
inputs:
  preset:
    type: string
    default: asm5
    doc: minimap2 preset for assembly-to-reference alignment (asm5, asm10 or asm20).
    inputBinding: {prefix: -x, position: 1}
  threads:
    type: int
    default: 1
    inputBinding: {prefix: -t, position: 2}
  reference:
    type: File
    doc: The complete long-read or hybrid assembly used as ground truth (FASTA).
    inputBinding: {position: 3}
  prediction:
    type: File
    doc: The sequence one reconstruction tool considers plasmid (FASTA).
    inputBinding: {position: 4}
stdout: prediction.paf
outputs:
  paf:
    type: stdout
    doc: Primary-alignment PAF of the prediction on the reference.
s:license: https://spdx.org/licenses/GPL-3.0-only
$namespaces:
  s: https://schema.org/
