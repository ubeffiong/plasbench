# Visual Reconstruction Quality

PlasBench's visual-quality views are a linked, offline HTML dashboard for
understanding why two reconstructions differ. They are generated from the same
retained primary PAF alignments used in scoring, not from a screenshot or an
untracked browser calculation.

## Three Linked Views

1. **Sample-by-tool heatmap:** rows are samples and columns are methods. Select
   base F1, precision, recall, plasmid recall, bin F1, chromosome
   contamination, unmapped predicted bases, execution state, or the explicitly
   exploratory composite quality value. Filter sample/tool text or order rows
   by their best visible metric. Click a cell to open the corresponding
   sample/tool context below.
2. **Per-plasmid recovery tracks:** select a truth plasmid to compare all tools
   on the same reference coordinate system. The percent at each row is the
   displayed-block completeness for that plasmid.
3. **Zoomable alignment explorer:** use Fit, zoom buttons, mouse wheel, or
   exact start/end coordinates. Click a coloured block to inspect its retained
   PAF query/reference coordinates, strand, identity, and MAPQ. New stage-5
   runs retain CIGAR operations and offer a bounded local nucleotide view when
   the selected alignment is small enough to display safely.

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
aligned bases, and the number of blocks omitted by the display cap. The default
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
0.45 * base F1 + 0.25 * plasmid recall + 0.15 * (bin F1, or base F1 when N/A)
+ 0.15 * (1 - chromosome contamination)
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
