# Reconstruction evidence explorer (vendored design)

`template.html` is an adopted interface design, kept as close to the original as
the report allows. It is rendered inside an isolated iframe because it styles
bare `*` and `body`; inlining it would restyle the whole report.

## What was changed, and why

| Change | Reason |
|---|---|
| Dark palette replaced with the report's light ground | The report is a light document. A dark island inside it reads as a different application. Canvas colours are drawn in JS and cannot read CSS variables, so those literals were remapped too. |
| Remote font and icon CDNs replaced with `__PB_FONTS__` | The report must render identically offline and years from now, so it carries the vendored faces in `assets/vendor/` rather than requesting a CDN at view time. |
| Sample data block replaced with `__PB_EXPLORER__` | Every displayed value now comes from the run. See `python/build_explorer_view.py`. |
| Header logo mark removed; sample and plasmid selectors added | PlasBench is multi-sample; the design assumed one. |
| `state.toolOrder` renamed to `state.rowOrder` and driven from the methods present | The design hardcoded three method names from its sample data. |
| Segment vocabulary widened from six terms to nine | PlasBench classifies `good`, `missing`, `inverted`, `chromosomal`, `wrong_plasmid`, `ambiguous`, `duplicated`, `low_identity` and `unsupported_join`. |
| `jumpToEvent` zooms before centring | At 1x the whole plasmid is in view and panning is clamped to zero, so a jump moved nothing. |
| JSON export serialises measured fields only | `render()` annotates each segment with a back-reference to its tool, which made the object graph circular and the export throw. |
| TSV export writes `NA`, not `0` | The design wrote `0` for absent values. A zero is a measurement; an absent value is not one. |

## Data the explorer shows, and where it comes from

| Field | Source |
|---|---|
| Segment spans and types | `visualization/alignment_blocks.json`, classified by `build_enterprise_view.contig_rows` |
| Identity | `matches / block_length` per alignment block |
| Mapping quality | the `mapq` column of each block |
| Structural navigation | `visualization/structural_calls.json`, plus gaps and inversions from the merged track |
| Split / merge map | `bin_assignment_flows`, counted per method |
| Proteins and categories | `--protein-truth`, `--amr-truth` and `--feature-truth` inputs |
| Nucleotide view | `local_alignment` on blocks carrying a `cg:Z:` CIGAR |
| Recovery | `plasmid_recovery[...].completeness`, best across methods |

## Deliberately not shown as a number

**Read coverage** is null everywhere. Scoring projects predictions onto
reference bases and never builds a depth profile, so there is no per-segment
coverage to report. The interface prints "not measured" and the exports write
`NA`.

**Purity** is null at plasmid scope. It is measured per predicted bin, not per
truth plasmid, so a per-plasmid purity figure would mix scopes.

**Nucleotide bases** resolve only inside CIGAR-bounded local alignments.
Everywhere else the sequence is `.` — unresolved, rather than invented.

Every structural call carries `validated: false`. These are alignment-derived
discordances, not confirmed misassemblies.
