# Rebuilding the report figures: status of cohort 1 and of every results folder in the repository

Written 19 November 2026 with `plasbench check-results` and `plasbench regenerate-visuals` (see [REPORT_INPUTS.md](REPORT_INPUTS.md) for what every report section reads and how each file can be rebuilt, and the guide section "Rebuilding a report's figures from an old run").

## Cohort 1 (`results_real_cohort1`, PlasBench 0.2.3, 10 isolates, 4 tools)

### What the folder held

Only the run-level tables: `scores.tsv`, `tool_status.tsv`, `run_manifest.json`, the `benchmark.*` tables and the HTML report. No per-sample folder at all: no predictions, no alignments, no truth tables, no QC table. That is why the synteny ribbons, plasmid maps, presence/absence matrix, plasmid-level facets, fingerprints and the QC panel said "Not available in this run". The zip `benchmark.report_cohort1.zip` in the working copy holds the same 60 top-level files and nothing more.

### What was found and used

The original data and results folders of the run are not in the repository. The manifest says where they were: the data in `~/.local/share/plasbench/data/<sample>/` and the results in `~/plasbench-0.2.3/results/<sample>/` on the machine that made the run (WSL, user `ueffiong`). Neither could be reached from this checkout (WSL was not responding).

An earlier two-isolate run of the same pipeline was found at `F:\tmp\plasbench_run` (data folders of `upec_ecpf5` and `upec_ecpf7` with reads, reference FASTAs, `sequence_report.jsonl`, `truth.tsv`; results with the predictions and alignments of `mob_recon` and `plasmidspades`). It is not part of the published run, so none of it was used on trust. Each of its four predictions was checked against the published `scores.tsv` row (`regenerate-visuals` does this for anything supplied with `--predictions-dir`: record count and total length must equal the row):

| Isolate | Tool | Records (scores.tsv = file) | Predicted bp (scores.tsv = file) |
|---|---|---|---|
| upec_ecpf5 | mob_recon | 21 = 21 | 148,790 = 148,790 |
| upec_ecpf5 | plasmidspades | 5 = 5 | 15,158 = 15,158 |
| upec_ecpf7 | mob_recon | 15 = 15 | 125,569 = 125,569 |
| upec_ecpf7 | plasmidspades | 29 = 29 | 144,283 = 144,283 |

All four matched, so they were accepted. `platon` and `baseline_coverage` were not in that run, and the other eight isolates were not in it at all.

### What was regenerated (committed in `results_real_cohort1/`)

```
plasbench regenerate-visuals results_real_cohort1 --cohort cohorts/public-v1.tsv \
    --data-dir F:/tmp/plasbench_run/data --predictions-dir F:/tmp/plasbench_run/out/results --yes
```

For `upec_ecpf5` and `upec_ecpf7`: `truth.tsv` (copied from the data folder), `visualization/alignment_blocks.json` and `structural_metrics.tsv` and `structural_calls.json`, `structural_events.tsv`, `structural_summary.tsv` (built by the pipeline's own scripts with the current settings, for the two tools whose alignments exist), a `<tool>.prediction_summary.tsv` per tool, and, from the reads, `short_read_qc.tsv` and `short_read_qc_status.tsv` (both PASS). The prediction FASTAs and PAF files were copied in beside them but are left out of git by the repository's `.gitignore` (`*.fasta`, `*.paf`). Everything is recorded, with the SHA-256 of every input, in `results_real_cohort1/regenerated_inputs.json`.

Not touched: `scores.tsv`, every `benchmark.*` table, `run_manifest.json` and `benchmark.report.html` (verified by hash before and after). The committed HTML report is still the 0.2.3 one: it was not rebuilt, because that would also rewrite its scores-derived sections; rebuild it with `--report` once the full inputs are supplied.

The partial state is stated by the tool, not hidden: `plasbench check-results results_real_cohort1 --cohort cohorts/public-v1.tsv` reports each of these sections as PARTIAL, with "2 of 10" for the alignment blocks. In the report built from this folder the synteny section draws 5 plasmid views (3 plasmids of `upec_ecpf7`, 2 of `upec_ecpf5`) and the plasmid-map section draws 380 KB of maps; checked by calling the two section builders on the folder, not by rebuilding the whole report (stage 6 was tried on a scratch copy and stopped in `write_manifest.py` with `KeyError: 'sample_id'` on this Windows machine, so no whole report was built from the folder).

### Section by section

| Report section / figure | Needs | State now |
|---|---|---|
| Method ranking, All scores, outcome states | `scores.tsv`, `tool_status.tsv`, `benchmark.leaderboard.tsv` | Available (the published tables, unchanged) |
| Synteny ribbons (`learn-synteny`) | `<sample>/visualization/alignment_blocks.json` | Partial: regenerated for 2 of 10 isolates, 2 of 4 tools |
| Plasmid maps (`plasmid-maps`) | `alignment_blocks.json`; `truth_features.tsv`, `truth_amr.tsv`, `reference.fna` enrich it | Partial: 2 of 10 isolates; no feature or AMR tracks (see below) |
| Presence/absence matrix, plasmid-level facets, fingerprints (branches not yet merged) | `alignment_blocks.json` | Partial: 2 of 10 isolates |
| Sample drill-down sequence view (`samples`) | `truth.tsv`, predictions, alignments, `alignment_blocks.json` | Partial: `truth.tsv` for 2 of 10; predictions and alignments for 4 of 40 sample-tool pairs |
| Short-read QC panel (`learn-readqc`) | `short_read_qc.tsv` | Partial: 2 of 10 (the other eight isolates' reads are not on this machine) |
| `truth_features.tsv` (replicon table, map features) | reference FASTA and an annotation caller (abricate, amrfinder, isescan, mob_typer, barrnap) with databases | Not available: the earlier run's `truth_features.tsv` has no rows (no caller was installed then; its `annotation_provenance.json` says "not evaluated"), so nothing was copied |
| `truth_amr.tsv` (AMR placement tracks) | a curated table | Not available for any isolate: it is written by a person (`plasbench promote-amr-truth`), never generated |

### What the lead must supply, and the command

For the other eight isolates (`upec_ecpf14`, `upec_ecpf15`, `upec_ecpf16`, `upec_ecpf18`, `upec_ecpf40`, `arbank_0346`, `arbank_0349`, `tahini_salmonella`), and for `platon` and `baseline_coverage` on all ten, one of these folders from the machine that produced the run:

1. **The data folder** `~/.local/share/plasbench/data` (`<sample>/reference.fna`, `sequence_report.jsonl` or `truth.tsv`, the read pairs for the QC panel, and any `truth_*.tsv`).
2. **The original results folder** `~/plasbench-0.2.3/results` (`<sample>/pred_<tool>.plasmid.fasta` and `<tool>.pred_vs_ref.paf` for every tool), or the folder's `pred_*` files alone.

Then:

```
plasbench regenerate-visuals results_real_cohort1 --cohort cohorts/public-v1.tsv \
    --data-dir <path-to-data> --predictions-dir <path-to-original-results> --yes --report
```

Predictions are verified against `scores.tsv` before use; ones that do not match are refused and named. With no original results folder but the data folder and `minimap2` installed, predictions that were kept still need the tool re-run: `platon` needs its database, `plasmidspades` and `mob_recon` need the reads. If the data folder is gone, the references can be downloaded again (ENA/NCBI, needs internet access; the accessions are in `cohorts/public-v1.tsv`), which rebuilds `truth.tsv` and the reference but not the predictions. For the figures' feature and AMR tracks: run an annotation caller on the references (`--only truth-features`) and supply a curated `truth_amr.tsv`.

## Every results folder in the repository

`check-results` was run over each folder (cohort 1 with `--cohort cohorts/public-v1.tsv`). Sections not listed in a row are available.

| Folder | Written by | Per-sample folders | Sections that cannot draw | Can be regenerated | Needs |
|---|---|---|---|---|---|
| `results_real_cohort1` | PlasBench 0.2.3 | 2 of 10 isolates after regeneration (none before) | Partial: synteny ribbons, plasmid maps, presence/absence, facets, fingerprints, sample drill-down, QC panel | Nothing more from what is present | The data and results folders named above |
| `results_audit` | audit fixture, manifest not recorded | 2 samples | none (QC panel not applicable: synthetic) | Structural-call files and prediction summaries (optional) | `truth_features.tsv` needs a reference FASTA and a caller; `truth_amr.tsv` is curated |
| `results_demo` (made by `plasbench demo`; local, not committed) | PlasBench 0.1.5 | 6 samples | none (QC panel not applicable: synthetic) | Prediction summaries (optional) | `truth_amr.tsv` for 2 samples; `truth_features.tsv` for 1 needs a caller |

`results_demo_metagenomics` is the separate metagenomic track and is out of scope. `docs/sample_report/` is a built report, not a results folder.

## Cost of keeping the inputs (`KEEP_REPORT_INPUTS=1`)

Measured on a copy of the local `results_demo` (6 samples, 20.5 MB; written by 0.1.5, since a fresh `bash test/run_demo.sh` takes about 100 minutes on this machine and WSL was down): the files that stage 5 now keeps per sample (truth tables and prediction summaries) total 2.6 to 6.5 KB per sample, 29,682 bytes for the six, 0.14% of the folder. The budget `KEEP_REPORT_INPUTS_MAX_KB=2048` per sample is therefore far above the demo's need; a real isolate with a protein-annotation table (`truth_proteins.tsv`) will be larger, and anything over the budget is listed as skipped in `<sample>/report_inputs.json`.
