# Visual Reconstruction Quality

PlasBench's visual-quality views are a linked, offline HTML dashboard for
understanding why two reconstructions differ. They are generated from the same
retained primary PAF alignments used in scoring, not from a screenshot or an
untracked browser calculation.

## Three Linked Views

1. **Sample-by-tool heatmap:** rows are samples and columns are methods. Select
   base F1, precision, recall, plasmid recall, bin F1, chromosome
   contamination, unmapped predicted bases, execution state, or the explicitly
   exploratory composite quality value. Use one consolidated control bar to
   filter cohort fields, search sample/tool names, and order rows by sample or
   the best visible metric. Click a cell to open the corresponding sample/tool
   context below.
2. **Per-plasmid recovery tracks:** select a truth plasmid to compare all tools
   on the same reference coordinate system. The percent at each row is computed
   from all primary scoring blocks for that tool/plasmid; the browser cap only
   limits the number of rectangles drawn.
3. **Zoomable alignment explorer:** use Fit, zoom buttons, mouse wheel, or
   exact start/end coordinates. Click a coloured block to inspect its retained
   PAF query/reference coordinates, strand, identity, and MAPQ. New stage-5
   runs retain CIGAR operations and offer a bounded local nucleotide view when
   the selected alignment is small enough to display safely. The linked dot
   plot deliberately selects one predicted record at a time, preventing
   unrelated query coordinate systems from being merged into one plot.

The selection is intentionally progressive: cohort comparison, then plasmid
recovery, then alignment evidence.

## Colours And States

| Display | Meaning |
|---|---|
| Dark/medium green heatmap | Better recovery metric, or lower error/cost metric |
| Amber heatmap | Intermediate value |
| Red heatmap | Lower recovery or higher error/cost value |
| Grey heatmap | Metric unavailable or tool not scored |
| Red/brown/blue status | Failed, skipped, or reused; never silently converted to zero |
| Green alignment block | Forward-strand primary alignment to the selected truth plasmid |
| Purple alignment block | Reverse-strand primary alignment to the selected truth plasmid |
| White track space | Not covered by displayed alignment blocks |
| Blue triangle | Curated truth AMR feature, when supplied |
| Blue/purple/orange/green top track | Curated replicon, MOB, insertion-sequence, or AMR-context feature; hover for source and version |

For error metrics, the scale is inverted so less contamination or fewer
unmapped bases is greener. The tooltip on every heatmap cell gives the sample,
tool, metric value, F1, and execution status.

## Generated Artifacts

Stage 5 writes:

```text
results/<sample>/visualization/alignment_blocks.json
```

It includes the truth plasmid inventory, AMR markers, retained primary PAF
blocks, per-tool per-plasmid covered intervals and completeness, chromosome
aligned bases, structural diagnostics, contextual feature tracks, and the
number of blocks omitted by the display cap. Coverage and structural values use
all scoring blocks before the cap is applied. The default
cap is `VISUALIZATION_MAX_BLOCKS_PER_TOOL=2000`; change it in
`config/config.sh` only when the browser/report size remains practical.

Download the exact artifact from the visual explorer for audit or use in a
separate plotting workflow.

`structural_metrics.tsv` sits beside the JSON and reports alignment breakpoint,
orientation, multi-target-record, and ordering diagnostics plus a conservative
structural-concordance proxy. It is a diagnostic, not a validated structural
correctness score.

## Optional Context And Circular Truth

Provide `data/<sample>/truth_features.tsv` to show curator-supplied replicon,
MOB, insertion-sequence, and AMR-context features. Its required fields are:

```text
sequence_id  start  end  feature_type  label  source  version
```

Features without a source and version are not accepted for display. When
`truth_circular.tsv` marks a reference plasmid as circular, the explorer shows
a circular **truth comparison** map of recovered intervals. It never states
that a prediction is circular or closed unless separate validated closure
evidence supports that claim.

## Composite Quality

The optional `Exploratory composite quality` heatmap metric is deliberately
secondary and does not change rankings or candidate selection. It is:

```text
weighted mean of the available components: base F1 (0.45), plasmid recall
(0.25), bin F1 (0.15), and 1 - chromosome contamination (0.15). Missing
components are omitted and the remaining weights are re-normalized; a missing
bin metric is never silently replaced by base F1.
```

It makes trade-offs visible but must be read beside its individual components.
Runtime, memory, closure, and AMR context are not silently folded into it.

## Interpretation Boundaries

The explorer makes sequence recovery and orientation visible, but it does not
on its own prove plasmid closure, circularity, correct biological ordering, or
clinical validity. A broken track can indicate fragmentation, missing sequence,
or a display cap; investigate the PAF, bin diagnostics, and original FASTA.
Whole-plasmid nucleotide letters are intentionally not shown. For a disputed
AMR locus, breakpoint, or junction, create a region-specific alignment with an
appropriate external alignment tool and retain its provenance.

Use the visual panels together with bin purity, split/merge diagnostics,
structural-evidence records, and confirmation requirements in each selection
report. No single visual or score is a universal definition of the best
biological reconstruction.

## Optional Protein Labels

When `RUN_PROTEIN_ANNOTATION=1`, PlasBench normalizes Bakta or Prokka CDS calls
for both the truth reference and every predicted plasmid FASTA. The explorer
then supplies a searchable protein table and directional feature arrows for
AMR, replication, mobility, maintenance, mobile-element, hypothetical, and
other CDS annotations. Labels use the gene symbol where available, otherwise
the product name; source, version, and confidence remain visible in the table.

Predicted CDS features are placed on truth coordinates through retained
nucleotide alignments. `coordinate-complete`, `coordinate-partial`, and `not
projected` describe that mapping evidence only. They must not be read as
amino-acid identity, orthology, intact reading frame, correct protein function,
or plasmid closure. Those claims require separately versioned protein-alignment
and structural evidence.
