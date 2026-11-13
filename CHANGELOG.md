# Changelog

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

The v0.1.x series was renumbered on 2026-09-09 from an earlier, denser
v0.1.0-v0.2.8 sequence (19 tags) down to 5 milestone releases. Each entry
below folds in every change from the tags it supersedes -- nothing from that
history is lost, only the numbering is cleaner. See
[docs/releases/](docs/releases/) for the full per-version notes.

## [Unreleased]

### Changed -- the sample report link is at the top of the README
- A link to open the sample HTML report (online preview; a relative path for a clone) now sits directly under the README title, not only in the report section. GitHub removes `target="_blank"` from README links, so the link says to Ctrl/Cmd-click or middle-click to open it in a new tab. `test/test_sample_report.py` keeps it there.

## [0.2.0] - 2026-11-10

A minor release: rankings, the recommendation output and some column names differ from v0.1.5, and the HTML report is rebuilt. Read **Upgrading from v0.1.5** in the [release notes](docs/releases/v0.2.0.md) first; everything below is the detail behind them. Compare: [v0.1.5...v0.2.0](https://github.com/ubeffiong/plasbench/compare/v0.1.5...v0.2.0).

### Changed -- the sample report is replaced by every demo run
- `test/run_demo.sh` (so `plasbench demo` and the demo tests too) ends by running `python/refresh_sample_report.py`, which replaces `docs/sample_report/benchmark.report.html` with the demo report just built. It is skipped, with a printed reason, when `docs/sample_report/` is absent, `PLASBENCH_SAMPLE_REPORT=0`, or the report is incomplete or holds a local path, and it never fails the demo. `test/test_refresh_sample_report.py` covers it.


### Added -- a download button per isolate in the plasmid matrix
- In *Which tool recovered which plasmid* (one table per analysis track) every isolate has a small **FASTA** button that downloads that isolate's best reconstructed
  plasmid(s): the selected candidate, `selected_candidates/<isolate>/<isolate>.candidate.plasmid.fasta`. The button works when the report is open from its results
  folder. When the report has been copied away, so the file cannot be reached, the button is **greyed out** and says why; an isolate with no selected reconstruction is
  grey from the start. Over http(s) the check is a HEAD request; from a local file the browser forbids reading files, so the file is requested as a script (it loads when
  the file exists and fails when it does not; the browser may log one harmless parse error per file in its developer console).
- The notes under the Summary's sub-headings (the plasmid matrix, the report card) are now hover tooltips like every other section note; only the Summary's own lead
  stays visible.

### Added -- a sample report in the repository
- `docs/sample_report/benchmark.report.html` is the report built from the offline demo (synthetic data, about 11 MB), with a README that says what it is, how to regenerate it and what differs from a real run. The project README links to it, with an online preview link. `test/test_sample_report.py` keeps the link, the file and its contents honest.

### Added -- a "?" help button on every section and tab
- Every section and every tab of the report has a green **?** button beside its title. A click opens one help dialog that explains the analysis for a reader who is
  not a specialist, in the same six parts everywhere: *In plain words*, *Data used*, *How it was made*, *How to read it*, *Why it matters* and *Keep in mind*. Esc, the
  Close button or a click outside closes it; focus returns to the button; the button is hidden in print. The texts are in `python/report_help_text.py` (84 entries on
  the demo), injected by `python/report_help.py` as one JSON block, so the page grows by about 45 KB, not once per button.
- `test/test_report_help.py` fails when a section or tab has no entry or an entry leaves one of the six parts empty, so a new analysis cannot ship without its help.
  It sits beside the small "i" popovers, which still carry each section's own lead note on hover.

### Fixed -- 3D charts drawn flat
- Pruning a Not-run tab also removed the shared 3D engine script that was emitted after it, so the 3D landscape fell back to its flat static picture. Pruning now keeps
  script and style blocks, and a test checks the demo page carries the engine.

### Fixed -- out-of-memory failures counted as the tool's fault
- A run whose log shows "Cannot allocate memory", `std::bad_alloc`, `MemoryError` or "out of memory"
  is a **resource** failure, like exit 124/137: by default it still scores 0, but it is reported as
  `failed_resource`, and `--resource-failures exclude` drops it. Found on cohort 1, where plasmidSPAdes
  ran out of memory on one isolate (exit 250) and was counted as an ordinary tool failure.
- **PDF export from WSL**: a Windows Edge/Chrome found under `/mnt/c` is given Windows paths (`wslpath -w`)
  for the report, the PDF and its profile; it could not open Linux paths and wrote no PDF.

### Changed -- section review: duplicates, mixed tasks and not-run sections
- **Recommendations are made for one task.** `select_operational_method.py` now recommends among the reconstruction tools only (`binning_capable=yes` in
  `config/tool_capabilities.tsv`); classifiers are ranked separately and are no longer compared with reconstruction tools in one "recommended overall" line.
  `benchmark.recommendations.tsv` has a last column `task`; `--task all` keeps the old behaviour and warns. The report says "One task" above the recommendation.
- **One place for each result**: the Automated interpretation section (it repeated *Start here*) is gone; per-plasmid results live in Plasmid maps ("All per-plasmid
  results" is its tab); run outcomes are one table with a reason column; Assembly adequacy is a tab of Assembly quality; both database-leakage screens are one tab;
  the two truth-quality groups are one *Reference standard* group beside the Headline design (with the pre-registration); the contig layer no longer prints the
  independent second scorer twice.
- **Fewer views of the same data**: the scorecard and its by-scenario views and the five-dimension composite are one *Scorecard (exploratory)* view with tabs; the
  Overview keeps the result, its confidence and the findings, the rest moved to Detailed results and Methods; the per-isolate recommender evaluation is one
  *Recommender validation* card under Recommendation, closed by default.
- **Artifact explorer replaces the "Data in this report" table**: each of its files has a description (what it is, which step wrote it, where it is shown); empty
  Logs and Data folds are hidden.
- **Glossary**: the 40 key headings are one searchable table.
- **Not-run sections are listed once**: a section or tab that holds only a "Not run" notice is not shown; *Run metadata* lists it with its reason ("Not run in this
  run"), and the old section id still lands there. *Extended analyses and next steps* is one line in Run metadata unless results exist.
- **The interactive cohort dashboard is optional** (`--embed-dashboard` or `REPORT_EMBED_DASHBOARD=1`, default off): it repeats the heatmap and metric tables and
  adds about 1 MB (the 6.5 MB of evidence-explorer data is separate and stays, lazy-loaded). The evidence explorer is unaffected.
- Panels of the explorers no longer show two headings; "Selected reconstructions" says why a selection needs review. The feature manifest keeps an explicit
  `REMOVED_BY_DECISION` list (six rows, each with its reason and where the information went) so nothing is lost silently.

### Changed -- order and wording for readers who are deciding
- **View order**: Overview, Recommendation, Figures, Plasmid maps, Detailed results (was "Statistical diagnostics"), Data quality, Methods and limits, Scorecard
  (exploratory), Appendix. Menu labels equal view titles; section labels in the menu are two to four words. Figures run CPRR differences, CPRR distributions, heatmap,
  precision-recall, ladder, 3D landscape, then the interactive cohort dashboard; the dashboard (Figures) and the reconstruction evidence explorer (Plasmid maps, new
  section `evidence-explorer`) are no longer in the Appendix.
- **Banner**: the title only. The duplicate numbers (samples, tools, leader, execution issues) are gone; the Summary has them once, then *Start here*, the plasmid matrix,
  the report card and the scorecard overall. The eyebrow is no longer all capitals.
- **Phone top bar**: the isolate filter, palette, collapse all and print / save PDF sit behind one menu button; the search keeps the room.
- **Display names at build time** (`python/report_names.py`): tool ids in the page text become display names when the report is built (link text only when it is exactly
  one id; file names, attributes, options and code are left alone), so print, PDF and no-JavaScript readers see them too.

### Changed -- the two explorers load when first shown
- The interactive cohort dashboard and the reconstruction evidence explorer (7 to 8 MB each) were written into their iframes at page load even though they sit in the
  Appendix, which opens hidden. They are now written only when the frame first becomes visible (with a 400 px margin), when the reader presses *Load now*, or at once
  when printing or exporting a PDF (`?print=1`, `beforeprint`) or where `IntersectionObserver` is missing. The documents stay in the page (it is still one offline file).
  On the demo report the page finishes loading in about 1.5 s instead of 4.5 s. `test/test_lazy_frames.py` runs the loader in node against a stub DOM.

### Changed -- report layout, condensed analytics, full PDF
- **Page shell** (`python/report_layout.py`): fixed top bar and left rail, one view at a time (Overview, Scorecard, Figures, Plasmid maps, Diagnostics, Data quality,
  Recommendation, Methods, Appendix) in story order, compact title band, status-chip accordion for data quality, hash routing for every old id, no-JavaScript fallback
  (the full linear page). 73 top-level sections become 34.
- **Merged analyses** (`python/report_merge.py`): related sections become tabs of one container and keep their old id as the panel id (`python/report_aliases.py`
  resolves old links): Ranking confidence, Method ranking (chart, metric framework, MCC and F-beta, graded recovery, negative control, baselines), Cohort and truth
  quality, Run outcomes and cost, Bin diagnostics, Scorecard (composite as *Weights and sensitivity*), Recommendations, Recommender, All scores (by tool, by sample) and
  a Reference tables appendix. The duplicate paired-comparison table in the unseen-taxa section is gone (it was a second copy of the Paired tests table).
- **Isolate filter and plasmid matrix** (`python/report_isolates.py`): the Summary and the Scorecard used to show cohort-wide numbers only. The Summary now has a
  *Which tool recovered which plasmid* matrix (one row per truth plasmid, one column per tool, coverage with a tick, half circle or cross, the best tool starred, and
  per-tool counts of plasmids recovered and plasmids on which the tool was best; one table per analysis track). An **Isolate** filter in the top bar (default *All
  isolates*) swaps the report card, the scorecard overall, the whole Scorecard (every metric re-scored on that isolate alone) and the matrix to one isolate's own
  numbers; a scope label next to each heading says which isolate is shown, and the no-JavaScript and print views show all isolates. The run line under the title is
  removed (the run folder is in the top bar and the full run details are in *Run metadata*).
- **Content uses the full width; folds start open**: the right-hand "On this page" strip is gone and the list now sits at the bottom of the left rail (it follows the
  view on show and highlights the current section). Every fold (cards, folded tables, drill-downs) starts expanded and can be collapsed; the top-bar button reads
  *Collapse all* / *Expand all* according to the state of the view. Summaries written as "Show the X" read "The X".
- **Condensed tables** (`python/report_condense.py`): tables over 15 rows show 12 rows with a filter and *Show all*; consistent table typography.
- **Full PDF export** (the browser sandbox stays on; where it cannot start, e.g. a container, set `PLASBENCH_BROWSER_FLAGS=--no-sandbox` for that run): print stylesheet with cover and contents, one view per page, every fold open; `python/export_report_pdf.py` and `plasbench report-pdf`.
- **No feature lost**: `test/fixtures/report_feature_manifest.tsv` (254 features of the earlier report) is checked by `test/test_report_feature_manifest.py`.
- **Corrected statements**: the ranking metric is named where the ranking score is quoted; the claim that failed runs are excluded from means is replaced by the real rule
  (F1 = 0 for a failed run on a plasmid-bearing isolate); robustness column renamed; power table names its metric (`power_analysis.py --leaderboard`); scenario views share
  one definition; scorecard overall beside the report card; glossary covers CPRR, MCC, F2, scorecard terms and NGOC; `--scores` folder is the results directory.

### Added -- figure gallery
- **Reconstruction ladder** (`fig-ladder`, `docs/images/reconstruction_ladder.svg`): the five steps from contigs to a verified plasmid, the score layer that judges
  each, live values from the run, and three explicit distinctions (binning is not reconstruction, circular is not correct, 3D is illustrative), two of them quantified.
- **3D landscape** of accuracy, completeness and structural fidelity (`fig-landscape`), **tool-by-metric heatmap** with clustering (`fig-heatmap`), **CPRR distributions**
  and **forest plot** (`fig-distributions`, `fig-forest`), and an interactive **precision-recall** plot (`fig-pr`). Each has a side setup panel, tooltips, drilldown,
  a no-JavaScript fallback and SVG / PNG / CSV export. The shared 3D engine no longer uses `Math.random`.
- Plasmid viewer: linear **Reference versus reconstruction** pane and Alignment tab, linked to the circular map; per-tool alignment blocks in the payload.
- `python/report_collapse.py` folds the scorecard, accuracy, performance, stratified, replicon-recovery and graded-tier tables that a figure now draws into closed details
  (nothing is removed). `python/report_figures.py` wires the figure modules; a module that raises fails the build instead of leaving a silent gap.

### Added -- databases kept once per machine
- **`PLASBENCH_DB_DIR`** (default `~/.plasbench/databases`): every tool database default points
  there instead of `DATA_DIR/db`, so new checkouts, new `DATA_DIR`s and rebuilt environments reuse
  what is downloaded. A database still at the old `DATA_DIR/db` path is used until the store has it.
- **`env/preserve_databases.sh`** moves existing databases into the store and leaves a link at the
  old path; never deletes; reports duplicates.
- **MOB-suite's database** moves to the store and its environment folder becomes a link; setup and
  the MOB-suite installer link a rebuilt environment to the stored copy instead of downloading again.

### Fixed -- MOB-suite pandas incompatibility in local installs
- MOB-suite needs `pandas<=1.5.3`; in the main environment (pandas 3) `mob_recon` crashed at start
  and every run scored 0. `env/environment.yml` and its lock no longer include `mob_suite`;
  `env/install_tools.sh` installs it into its own environment, `<env>-mobsuite` (MOB-suite 3.1.9,
  the Dockerfile's pins), and writes `mob_recon`/`mob_typer`/`mob_cluster`/`mob_init` wrappers into
  the main environment. `setup_conda.sh` runs this step; `plasbench install-tools mobsuite` repairs
  an existing install. The MOB-suite database checks follow the wrapper (`scripts/lib.sh`
  `mobsuite_db_dir`), as does stage 6's database-containment step.

### Added -- downloads kept for future runs; broken tools caught early
- **Preserved downloads** (`PRESERVE_DOWNLOADS=1`): stage 1 writes `<sample>/downloads.sha256` for the
  reads and NCBI records and makes the reads read-only; a later run with the same `DATA_DIR` verifies
  them and downloads nothing, and re-fetches only a file that fails its checksum.
- **Tool smoke test at setup**: an enabled tool that is installed but cannot start (for example
  MOB-suite importing a name newer pandas removed) is reported as `[BROKEN]`, not `[ok]`.
- **Import failures are infrastructure failures**: a run whose log shows `ImportError`,
  `ModuleNotFoundError` or similar is never scored as the tool's F1 = 0; it is rerun after the fix.
- Download tests force `READ_SOURCE=sra`, so they never reach ENA over the network.

### Added -- interactive report views
- **Info popovers for explanatory notes** (`python/report_info.py`, `assets/report/info_script.html`): one post-processing step on the finished
  page moves section leads, "how to read" notes and figure captions into a circled "i" beside the heading that opens on hover, keyboard focus
  or tap (click pins, Esc closes, links inside stay usable, works inside collapsed sections). The plasmid viewer, the 3D views and the colour
  palette bar use the same icon for their hint lines. "Not run" notices, caution boxes, notes that carry a status or a value, and the Summary
  section stay on the page; the print view shows every note inline. Notes keep their original HTML and the page is shorter to read.
- **Interactive plasmid map viewer** (`assets/report/plasmid_viewer_*.html`, `python/report_maps.py`): one viewer with a side panel replaces the
  stack of static maps. Hover tooltips, click drilldown into a Detail tab, wheel zoom and drag rotate with labels re-laid out, region inputs,
  search, layer, class and tool filters, Tools / Features / Events tables as tabs, SVG, PNG and TSV export, shareable URL-hash state, keyboard
  and touch support. The static SVG maps stay as the no-JavaScript and print fallback.
- **3D views** (`python/report_3d.py`, `assets/report/viz3d_*.html`): rotatable SVG scenes (no libraries, offline) for the contig layer beside
  the reference layer (bars per tool and layer with the independent-scorer cross-check), the per-isolate recommender against the single best
  tool and the oracle (regret gaps and a verdict banner), and AMR genes on the right plasmid (a tower of rings, one per tool). A static server-
  rendered view is the no-JavaScript and print fallback; a test checks the JS and Python projections agree.
- Large tables are collapsed until opened: scorecard definitions, headline design and reference standard, classification and reconstruction
  metrics, interpretation limits, the per-plasmid table and the regret table (their rows are also in the viewer and 3D panels; nothing is removed).

### Added -- report overhaul: scorecard, maps, workflow, inventory
- **Workflow figure moved to the README**: it describes how the pipeline is built, not what one run produced, so the report no longer has a
  Workflow section. `python/report_workflow.py` now draws a static `docs/images/workflow.svg` (embedded in the README's "Benchmark workflow"
  section); a test fails if the committed file drifts from the generator.
- **Weighted scorecard** (`python/report_scorecard.py`, `config/scorecard.tsv`): 17 metrics A1-E3, piecewise-linear score (100/85/60/0), metric bands, overall
  bands (90/75/55), weights renormalised over scored metrics with the scored weight share, and non-exclusive scenarios (simple, complex, annotated,
  challenging) with an underpowered flag below `SCORECARD_MIN_SAMPLES` (5). Only the identity bands are `fixed`; the rest are `proposed` and registered in
  `config/prereg.tsv`. A4 and C2 are `undefined` (no truth variant set): no thresholds, excluded from the overall.
- **Circular plasmid maps** (`python/report_maps.py`): per truth plasmid, with truth genes, tool coverage rings, GC content and GC skew
  (`MAP_MAX_TOOLS` 8, `MAP_MAX_BP` 600000).
- **Data inventory** ("Data in this report", `python/report_surfaces.py`), per-plasmid detail, assembly-quality section, depth strip,
  grouped collapsible navigation, a column-group switch for the scores table, and links to `leaderboard.md` and `scoring_spec.md`.
- Corrected the paired-comparison table and the overlap wording.
- Docs: SCIENTIFIC_GUIDE 7.10, 13.3, 15, 17.4; METHODS; README. New variable `SCORECARD_MIN_SAMPLES`.

### Changed -- performance audit fixes ([docs/PERFORMANCE_AUDIT.md](docs/PERFORMANCE_AUDIT.md))
- **Bin matching is rectangular** (`python/matching.py`, shared by `score_bins.py`, `score_amr_placement.py` and
  `metagenomics.py`): O(r²c) instead of a padded O(max(B,P)³) square. Same optimal total weight; the same pairs
  wherever the optimum is unique (`test/test_matching.py`); 400 bins × 20 plasmids in 0.02 s.
- **Exact statistics without `Fraction` objects** (`python/resampling.py`): every mean, bootstrap interval and
  permutation p-value is bit-identical to before (`test/test_resampling_equivalence.py`), and resampling adds
  precomputed per-cluster integer sums. `headline_design` and `aggregate_results` no longer import each other.
- **Stage 4 reuses a tool result only when its fingerprint matches**: installed executable, adapter, database row,
  `<TOOL>_*` settings (thread counts excluded) and inputs are written into `.<tool>.complete`. An upgrade, a
  changed setting or a new assembly re-runs that tool. Markers from earlier releases re-run once
  (`REUSE_UNFINGERPRINTED=1` reuses them unchecked).
- **Capability registry read once per stage** (`tool_capabilities.py --dump`, `lib.sh load_capabilities`) instead
  of one `python3` launch per lookup (12.5% of the demo's wall time).
- **One minimap2 index per sample** in stage 5 (`.reference.<preset>.mmi`, deleted afterwards); byte-identical
  PAF across all 105 call shapes checked on the demo.
- **Stage 6 advisory analyses run as a bounded parallel group** (`STAGE6_PARALLEL_JOBS`, default 4; 1 restores
  the serial order).
- **`plasbench-score` applies the pre-registered alignment filters** the caller omits (`MIN_ALIGNMENT_*` when
  exported); a direct `score_plasmids.py` run without filters prints a note.
- **Shared, validated readers** in `plasbench_common.py` (`read_truth_table`, `read_bin_membership`, `iter_fasta`,
  `open_maybe_gz`, `union_length`) replace 20 local copies. `bin_quality.py` now applies the bin scorer's rules
  (a non-`PLASMID`/`CHROMOSOME` truth row, or a contig in two bins, is an error) instead of reading them differently.
- The leaderboard writer refuses a column/value count mismatch; `test/bench/` holds the timing harnesses.
- **Data-structure upgrades, results unchanged** (every output hash identical before and after,
  `test/bench/bench_dsa.py`): hash-map indexing in `bin_agreement.per_bin_rows` (64×) and hash-set dedup in
  `read_bins` (86×); hash sets for the matcher's live rows (6.8×); a bounded heap for the visualization top-k;
  a sliding window between N positions with bytes encoded once in `contig_crosscheck.sampled_kmers`; binary
  search in calibration bucketing; a `Counter` for duplicate checks; the permutation tests' fair-bit draw
  inlined (a bulk bit-decoding variant was measured slower and not kept).
- **Streaming reads**: `iter_fasta(path, wanted)` skips unwanted records without joining them; the database
  containment check no longer holds the chromosome (peak 12.7 → 0.4 MiB on a 5 Mb reference).
- **Parallel ENA downloads**: both mates at once and `ENA_DOWNLOAD_CONNECTIONS` (default 4) byte ranges per
  file of at least `ENA_SEGMENT_MIN_BYTES` (aria2c when installed; `ENA_USE_ARIA2=0` disables it), falling back
  to the resumable single stream and always MD5-verified (`test/test_fetch_ena_parallel.py`). 8.6 → 1.6 s for
  2 × 16 MiB at 4 MiB/s per connection.
- **Thread budget**: with `THREADS` unset, the cores are divided across `MAX_PARALLEL_SAMPLES × MAX_PARALLEL_TOOLS`
  instead of every job requesting every core (`test/test_thread_budget.sh`).
- Stage-4 fingerprints identify a tool's executable by path, size and modification time and never run it to ask
  its version (a tool that does not parse `--version` could otherwise start a real run).

### Fixed
- Leftover merge-conflict markers in this changelog.

### Changed -- track-specific endpoints and CPRR robustness
- **Long-read and hybrid reconstruction are now ranked on isolate-level CPRR** (`sample_cprr`); short-read reconstruction stays on
  length-weighted binning F1 with CPRR as the key secondary endpoint (`headline_design.ranking_metric()`; `config/prereg.tsv`
  `primary_endpoint`, `primary_endpoint_long_read`).
- **CPRR threshold sweep**: `score_bins.py` writes correct counts with coverage and bin share at 0.80-0.99; new
  `benchmark.cprr_threshold_sweep.tsv` and leaderboard `cprr_auc` (normalised area under the pooled curve).
- **Isolate-weighted CPRR** (`cprr_isolate_mean`, `cprr_isolates`) beside the pooled rate.
- **Stratified CPRR**: `cprr` and `n_cprr_assessed` per size band, replicon, MOB and AMR carriage in
  `benchmark.recovery_by_replicon.tsv` (identity rule via `--truth-provenance`), and pooled CPRR per reference tier.
- README evaluation framework and workflow sections; METHODS, PREREGISTRATION and the HTML report updated to match;
  `test/test_cprr_robustness.py` added.

### Added -- completing the plsMD, PlasEval and GAEMR follow-ups
- **PlasBin-flow output adapter** (`RUN_PLASBIN_FLOW`, `PLASBIN_FLOW_OUTPUTS_DIR`, `adapters/adapt_plasbin_flow.sh`): adapts the tool's own output
  (it needs a Gurobi licence, so PlasBench does not run it); a contig listed in several bins stays in the first and the rest are recorded.
- **Cross-check against the original PlasEval** (`test/test_plaseval_crosscheck.py`, optional, `PLASEVAL_SRC`): best-match precision, recall and F1
  agree on every case, and the normalised dissimilarity agrees on every case without repeated contigs.
- **Optional label evidence**: several Abricate replicon databases (`ANNOTATION_REPLICON_DB`) and BLAST-based ISFinder annotation (`ISFINDER_FASTA`).
- `env/download_plsdb.sh` now has an offline test and refuses a download that is not FASTA: the PLSDB address in plsMD's Dockerfile redirects to an HTML page.

### Fixed
- The `repeat_rich` scenario tag never fired on real annotation: it counted feature types `is` and `isescan`, while `annotate_reference.py` writes
  `insertion_sequence`.

### Added -- lessons from plsMD, PlasEval and GAEMR
- **plsMD wrapper** (`RUN_PLSMD`, `adapters/adapt_plsmd.sh`): an optional benchmarked reassembly tool, skipped with a recorded reason when
  its command, PLSDB index or Unicycler assembly is missing; PLSDB listed as its database for the leakage screens.
- **`baseline_replicon`**: a third trivial baseline (a replicon marker, with plsMD's Col-versus-Inc rule).
- **Bin agreement** (`python/bin_agreement.py`, PlasEval's published definitions reimplemented): best-match (non-one-to-one) precision, recall
  and F1, a split/join dissimilarity, a tool-vs-tool agreement matrix and a PlasEval-format export.
- **`CHIMERIC` contig label** and a `plasmids` column in the contig labels (GAEMR's misjoin idea).
- **Assembly adequacy**, **plasmid copy-number concordance**, **truth repeat content** and opt-in **truth depth anomalies**.
- **Origin-wrap fix**: a rotated circular plasmid is no longer reported as a tandem duplication by `call_structural_variants.py`.
- Local read pairing for `init-local --reads-dir` (`_1`, `_R1`, `_R1_001`), `env/download_plsdb.sh`, report sections for all of the above, and a README
  section on what PlasBench offers over the three projects, with where each is better.

### Added -- cross-check, ENA fallback, demo coverage
- **Independent second scorer for the contig layer** (`contig_crosscheck.py`): alignment-free k-mer
  labels and separately written metrics; per-run agreement table, report and validity statement.
- **ENA fallback for short reads** (`fetch_ena_reads.py`, `READ_SOURCE`): when `prefetch` fails (for
  example an old SRA Toolkit failing TLS), the same run is fetched from ENA and MD5-verified.
- The demo now has a synthetic assembly, so the contig layer, the cross-check, assembly statistics and
  the QC-gate warnings render with real values.

### Added -- scoring specification and panel examination
- **Pre-registration** (`config/prereg.tsv`, `freeze_prereg.py`): freeze/verify a SHA-256 lock; the
  manifest and report show the hash, lock state, `TO_FIX` items and departing settings;
  `REQUIRE_PREREG=1` gates stage 4.
- **Labelling schemes** (`label_schemes.py`, `TRUTH_LABEL_SCHEME`, default `ncbi`): the headline is
  now scored on NCBI labels (Scheme 3, decision E.15) instead of the evidence-checked truth; Scheme 1
  and the evidence scheme are rank-sensitivity variants. **Behaviour change:** set
  `TRUTH_LABEL_SCHEME=evidence` for the previous scoring.
- **Dimer collapse** (`detect_dimers.py`, `COLLAPSE_DIMERS`), **truth grades** A/B/C, optional cohort
  columns `same_extraction`, `split`, `genus`, `phylum`, `grade_source`, `collection_date`.
- **Scoring**: `TN_bp`, `mcc`, `f2`, `f0_5`, `abstention_rate`, `--min-contig-length`; per-plasmid
  outcome states (`score_bins.py --outcomes-out`); contig-level binning F1 and shared/unassigned
  lengths; AMR placement by gene class (`score_amr_placement.py`, `config/amr_gene_classes.tsv`).
- **Outcome states**: `infrastructure_failure` (never scored), `TOOL_RETRIES`, `TOOL_TIMEOUT_SECONDS`,
  `tool_outcomes.tsv`, `benchmark.outcome_states.tsv`; `tool_status.tsv` schema unchanged.
- **Statistics**: Wilcoxon signed-rank (exact n ≤ 25) with Holm, equivalence flag
  (`SMALLEST_DIFFERENCE`); new rank-sensitivity axes (schemes, min contig 500, micro, public/in-house,
  grade C excluded, MCC/F-beta/contig metrics).
- **Recommender evaluation** (`evaluate_recommender.py`, `evaluate_warnings.py`, `leave_taxon_out.py`):
  regret, near-optimal, gap closed, `benchmark_only` verdict, warning PPV/sensitivity, leave-taxon-out
  and a once-only holdout.
- **Panel items**: recommendation floor (`RECOMMENDATION_MIN_EXPECTED_SCORE`, D11); operational states
  `insufficient_sequence` and `ambiguous_between_references`; advisory assembly QC gate (D13); a
  "tools compared" reason table (D15).
- Ten new HTML report sections and `benchmark.scoring_spec.md`; the demo exercises all of them.
- Docs: `docs/PREREGISTRATION.md`, `docs/PANEL_ALIGNMENT.md`, the scientific guide, METHODS, and
  the question bank (clustering/relatedness answers cut to "outside this benchmark").

### Added -- metric rubric
- **Contig-level classification** (`contig_classification.py`): contigs labelled against truth
  (>= 95% identity over >= 80% of the contig; short, ambiguous and unplaced contigs excluded and
  counted); count-based and length-weighted precision, recall, F1 and **MCC** per tool.
- **ARI** (base-pair weighted) and **assembly-aware binning recall/F1** in `score_bins.py`.
- **Micro** (pooled-base) precision/recall/F1 beside the macro means.
- **Sequence-level database membership** (`database_containment.py`): truth plasmids checked against
  each tool's own database; recovery reported inside vs outside it.
- HTML sections "Classification and reconstruction metrics" and "Truth plasmids in tool databases";
  README metric tables updated, with a headline metric set.

### Added -- reviewer question bank
- **Trivial baselines** `baseline_coverage` and `baseline_reference`, scored like tools;
  leaderboard columns `is_baseline` and `beats_best_baseline`.
- **Probability calibration** for probability-exposing tools: Brier score, expected
  calibration error and a reliability table/diagram.
- HTML report sections **Baselines and calibration**, **Interpretation limits** and
  **Metadata completeness**; `benchmark.metadata_completeness.tsv`.
- `docs/FAQ_QUESTION_BANK.md` answers the 108-question reviewer bank.

### Fixed
- The run manifest now records every ranking-relevant setting added by recent releases.
- A duplicate `PLASMID_REFERENCE_SKETCH` default ignored `DATA_DIR`.
### Cohort and database data
- **`public-v3` panel** (98 isolates, locked): `public-v2` plus recorded truth provenance
  and 66 new long-read-first isolates, one per BioProject, across six species. All rows
  verified online; `accepted_accessions.tsv` regenerated; CI checks the v3 lock.
- `config/tool_database_releases.tsv`: release dates verified from each installed or pinned
  database's own record (MOB-suite DB v2.0.0 2020-05-04, Platon DB v1.5.0 2020-10-05,
  geNomad DB v1.9 2025-02-18, PlaScope 2018-07-13, RFPlasmid 0.0.18 models 2021-07-28);
  uninstalled databases left blank with the reason.
- New `python/collect_truth_provenance.py` and `python/discover_design_cohort.py`; the
  assembler pattern now tolerates NCBI's "Trycyler" misspelling.
### Added -- further benchmark dimensions (advisory; none changes the leaderboard)
- `python/alignment_accuracy.py`: nucleotide identity, mismatch, insertion and deletion rates decoded from the alignment CIGAR,
  and missing-region counts; `python/mask_accuracy.py` blanks the rates where the truth was polished with the benchmark's own
  reads (the same rule as the CPRR identity criterion). SNP concordance is not computed (no variant truth exists).
- `python/feature_preservation.py`: full-length, truncated and missed recovery per feature kind, and NGOC (gene or
  landmark-order conservation, strand and circularity aware), by projecting truth features through the alignments.
- `python/bin_quality.py`: high and medium quality-bin yield, homogeneity, completeness and V-measure, as secondary diagnostics.
- `python/performance_summary.py`: success rate, resource failures, runtime, memory, thread-seconds per recovered plasmid,
  CPU utilisation and scaling exponents. Stage 4 now records user and system CPU seconds beside peak memory.
- `python/power_analysis.py`, `python/scenario_tags.py`, `python/compare_runs.py`, and an optional gated composite with weight
  sensitivity (`python/composite_score.py`, `config/composite_weights.tsv`). The composite never changes the leaderboard.
- `python/stratify_recovery.py` also stratifies by size band and resistance-gene carriage and reports median and IQR;
  `python/audit_truth_labels.py` screens truth labels against replicon and MOB evidence; `plasbench derive-amr-truth`,
  `plasbench audit-truth-labels` and `plasbench analysis <name>` expose the standalone scripts.
- The HTML report gains sections for each of the above, with explicit empty states. `RUN_DIMENSION_ANALYSES=0` skips them.
- Tests: `test_alignment_accuracy.py`, `test_mask_accuracy.py`, `test_feature_preservation.py`, `test_bin_quality.py`,
  `test_performance_summary.py`, `test_power_analysis.py`, `test_scenario_tags.py`, `test_composite_score.py`,
  `test_compare_runs.py`, `test_audit_truth_labels.py`, `test_scoring_controls.py`, `test_scoring_real_minimap2.py`,
  `test_stratify_multilabel.py`, `test_script_wiring.py`, `test_demo_end_to_end.py`, `test_stage_dimensions.sh`.
- Docs: `FAQ.md` (evidence-backed answers, and the reviewer question bank answered section by section),
  `docs/REVIEW_TRACKER.tsv`, a METHODS section for the new dimensions, and the README metric-framework and roadmap section.
- CI installs minimap2 so the real-aligner golden test runs.

### Changed (breaking, experimental output only)
- **The Mash nearest-reference screen no longer claims novelty.** Its calls were renamed
  because they promised more than a Mash distance to 16 plasmids can show:
  `known_cluster` is now `close_reference_match`, `novel` is now `no_close_reference`, and
  the `confidence_score` column is now `distance_margin` (a linear margin to an uncalibrated
  threshold, not a probability). `plasmid_similarity.tsv` gains `mash_p_value` and
  `shared_hashes`. The default threshold is unchanged, but its documentation no longer calls
  it "roughly ANI >= 95%": for plasmids, two equal-size sequences sharing about 35% of their
  k-mers already reach it, and an exact piece under about 21% of a reference falls outside it.
  Anything that read the old labels or column must be updated. The feature remains off by
  default and unvalidated.
- **`make_truth.py` no longer guesses CHROMOSOME for a sequence it cannot label.** Such
  sequences are written as `REVIEW`, which `validate_truth_table.py` rejects, so stage 2 stops
  instead of silently biasing precision and recall. This now also covers location types other
  than Plasmid/Chromosome and reports that contradict themselves. `ALLOW_DEFAULTED_TRUTH=1`
  (or `--allow-default`) restores the old behaviour.
- A skipped tool run (command not installed, database missing, no assembly graph) no longer
  counts as a failure in the operational recommendation's `failure_rate`; it already lowers
  coverage, which gates eligibility.

### Added
- **`docs/SCIENTIFIC_GUIDE.md`**, a guide for domain experts: what PlasBench does, how and why,
  its scope, every metric and statistical procedure, the shipped cohorts, outputs and how to read
  them, reproducibility, how each kind of expert can check the claims, what has and has not been
  validated, and a scope matrix. It has a table of contents, a README section with its own
  contents list, and `python/build_guide_toc.py` keeps both in step with the headings.
  `test/test_guide_docs.py` checks the contents, every link, and that every configuration
  variable, command and `scores.tsv` column the guide names still exists in the code.
- `run_manifest.json` now lists selected candidates for a benchmark run. It looked only for the
  operational layout (`<sample>/selected_candidate/`), so an ordinary benchmark run listed none.
- `n_failed_resource` and `n_unknown_overlap` leaderboard columns; `--resource-failures
  {score-zero,exclude}` and `--tool-capabilities` on `aggregate_results.py`.
- A failed tool run's exit code is recorded in `tool_status.tsv`'s reason column
  (`exit_code=<n>`; the file's header is unchanged). Exit 124/137 is classed as a resource
  failure.
- The HTML report now shows the nearest-reference screen result in each sample's selection card,
  with its experimental caveat and support (p-value, shared hashes); reports from before the
  rename still display.
- `python/rank_sensitivity.py` and `benchmark.rank_robustness.tsv`: per-track sensitivity of the
  ranking to alignment filters (re-scored from the PAFs on disk) and to the metric (strict F1,
  per-plasmid recovery), with Kendall's tau and whether the top tool changes. Run from stage 6;
  `RUN_RANK_SENSITIVITY=0` skips it. It does not change the leaderboard.
- A leaderboard warning (stderr and the Markdown leaderboard) and a clearer HTML cell when the
  database-overlap screen could not judge any pair because `database_release_date` is blank.
- Tests: `test_scoring_adversarial.py`, `test_aggregate_failures.py`,
  `test_selection_undefined_metrics.py`, `test_study_groups.py`, `test_leakage_visibility.py`,
  `test_classifier_semantics.py`, `test_report_classifier_section.py`, `test_rank_sensitivity.py`, `test_failed_tool_exit_code.sh`.
### Changed -- research design (headline endpoints and reference standard)
- **Primary endpoint is now length-weighted binning F1** for binning-capable tools
  (`lw_bin_f1`, ungated Hungarian match; the count-based `bin_f1` is kept but not
  ranked). **CPRR** (Correct Plasmid Reconstruction Rate) is the secondary endpoint,
  with pre-specified `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE`/`CPRR_MIN_IDENTITY`.
  Classifier-only tools are ranked on a separate classification track by
  base-level F1. Leaderboards add `task`, `ranking_metric`, `ranking_score` (+ CI),
  `ranking_species_basis`, `cprr` (+ CI) and `mean_lw_bin_f1`.
- **Reference standard.** `truth_provenance.py` classifies how each truth was built
  (long-read-first vs short-read-first; polished with the benchmark's own reads or
  not) and assigns reference tiers 1-3. Short-read-first and unknown-provenance truth
  (tier 3) leave the headline and become a sensitivity analysis; the CPRR identity
  criterion is dropped for truth polished with the benchmark's reads.
- **Evidence-based truth labels.** `label_truth_evidence.py` confirms each replicon
  with plasmid markers, rRNA genes (new barrnap caller) and long-read support;
  conflicting replicons (chromids, marker-free or short-read-only plasmids) are
  AMBIGUOUS and excluded from scoring via `truth.scored.tsv`. Self-built truth is no
  longer labelled by size alone.
- **Species balance.** The ranking score averages per-species means over species with
  >= `MIN_SPECIES_CLUSTERS` independent clusters; clusters join shared BioProjects and
  clonal groups (`clonal_groups.py`), and CIs/permutation tests resample whole
  clusters within species. New `benchmark.species.tsv`,
  `benchmark.reference_tiers.tsv`, `benchmark.headline_design.tsv`.
- `validate_cohort.py` prints advisory composition warnings (species count, dominant
  species, species below the minimum) and validates the new optional sheet columns
  `truth_assembly_strategy`, `truth_polish_reads` and `clonal_group`.
- HTML report: leaderboards per task with ranking score, CI and CPRR; new "Headline
  design and reference standard" section with provenance, tiers, species balance and
  a tier-sensitivity chart.

### Fixed
- `benchmark.species.tsv` now lists a tool that failed on every sample (mean 0 over the plasmid-bearing
  samples), as the leaderboard already did. `species_table` called `shared_values` without the failed-only tool,
  so the two outputs disagreed. The tool list passed in comes from the same (track, task) group, so failures of
  other groups' tools are not counted.
- **A tool that failed on every sample no longer vanishes from the leaderboard.** It now ranks
  last with F1 = 0 on every plasmid-bearing sample, in its own track.
- Equal mean F1 now ranks by tool name instead of by row order in `scores.tsv`, which made the
  "runner-up" in the significance test arbitrary.
- The operational recommendation no longer averages an undefined F1, precision or recall (an
  isolate with no true plasmid) as 0.0.
- Leave-one-study-out validation no longer silently drops samples with a blank `source_study`:
  they join the study of any sample sharing their bioproject, else use the bioproject, and
  samples with neither are reported.
- The mash query sketch now uses the same sketch size as the reference (it used Mash's default
  of 1000 against a 10000-hash reference), and mash's p-value and shared-hash count are no
  longer discarded; a close but statistically unsupported hit is no longer a match.
- `make_truth.py`: the version-less accession fallback is no longer order-dependent, and a
  `chr_name` shared by several records no longer silently resolves to the last one.
- The scorer ignores secondary alignment rows (`tp:A:S`) in a supplied PAF and warns.
- `scorable_truth.py` reads truth with the scorer's own validation.
- Removed `write_track_leaderboards`, which nothing called.
- **Empty predictions no longer inflate mean F1.** On an isolate with true
  plasmid, a tool that predicts nothing now scores F1 = 0 (precision stays
  empty). Previously F1 was left empty and the sample was dropped from the
  tool's mean, so a tool that abstained on hard isolates could tie a perfect one.
- **Tools are ranked on the same samples.** `mean_f1`, its CI and median now use
  only samples shared by every ranked tool in the track; a failed tool run
  (`tool_status.tsv`) on a plasmid-bearing sample counts as F1 = 0 for that tool,
  in both the ranking and the paired comparisons. New leaderboard columns:
  `analysis_track`, `n_ranking_samples`, `ranking_basis`, `mean_f1_all_scored`,
  `n_f1_scored`, `n_failures_scored_zero`.
- **The combined leaderboard no longer ranks across input tracks.**
  `benchmark.leaderboard.tsv/.md` now hold each track's table ranked within that
  track, and `benchmark.paired_comparisons.tsv` only compares tools within a
  track (new `analysis_track` column). Previously the combined file ranked
  short-read, long-read and hybrid tools against each other.
- `make_truth.py` no longer claims that defaulting an unclassified sequence to
  CHROMOSOME "only ever creates false negatives": if it is really a plasmid, correct
  plasmid calls on it are scored as false positives. Its warnings now say so, and
  the plasmid-free note no longer suggests excluding negative-control isolates.
- The HTML report no longer says failed tool runs are excluded from F1 aggregation
  or never become zero scores; it now describes the failure-as-zero ranking rule.
- METHODS.md now states that `unmapped_pred_bp` includes predicted sequence whose
  alignments were all removed by the alignment filters, so it lowers neither
  precision nor F1.

### Added
- **Cluster-aware statistics.** Bootstrap CIs and paired permutation tests resample
  whole BioProject clusters (sample-sheet `bioproject`, else `source_study`), so
  same-study isolates are not counted as independent. New columns
  `n_independent_clusters` (leaderboard) and `paired_clusters` (comparisons).
  Unchanged results when no cluster column is present.
- **Recall-ceiling diagnostic** (`python/scorable_truth.py`, stage 5, on by default):
  `scorable_plasmid_bp`, `recall_ceiling` and `ceiling_adjusted_recall` show how much
  plasmid sequence (shared repeats, duplicate plasmids) no prediction can be credited
  for under the alignment filters. Config: `RUN_SCORABLE_TRUTH`,
  `SCORABLE_WINDOW_BP`, `SCORABLE_STEP_BP`.
- **Strict precision** (`strict_precision`, `mean_strict_precision`): also charges
  unmapped and filter-rejected predicted bases. Supplementary, never ranking.
- **Reference-database overlap screen** (`python/flag_database_overlap.py`, stage 6,
  `config/tool_database_releases.tsv`): flags truth genomes public before a tool's
  database; leaderboard adds `n_possible_db_overlap`, `n_after_database`,
  `mean_f1_after_database`; `EXCLUDE_DATABASE_OVERLAP=1` drops flagged rows before
  ranking. Stage 1 now keeps `assembly_data_report.jsonl` for the release date.
- **HTML report "Robustness diagnostics" section** with a table and three charts
  (recall vs ceiling, precision vs strict precision, F1 vs F1 after database);
  the leaderboard shows the shared-sample basis and the comparisons table shows
  cluster counts.
- `redundant_pred_bp` score column: reference bases claimed more than once by
  retained alignments (e.g. duplicate predicted records). Diagnostic only; it never
  changes TP, FP or F1.

## [0.1.5] - 2026-09-10

### Added

- Optional operational-mode novel-vs-known plasmid classification
  (`RUN_PLASMID_NOVELTY_CLASSIFICATION`, `python/classify_operational_plasmid.py`,
  `python/build_plasmid_reference_set.py`): Mash distance from a truth-unknown
  isolate's own reconstructed candidate to a small, curated reference plasmid
  set, independently reimplementing santirdnd/COPLA's own known-cluster-or-
  novel pattern with PlasBench's existing Mash dependency rather than COPLA's
  code or its `graph-tool`/nested-SBM machinery. Off by default -- a purely
  supplementary, operational-only signal never wired into
  `recommendation_model.py`'s training features, since a genuinely unknown
  isolate has no truth reference, the entire reason this signal exists.
  - `python/build_plasmid_reference_set.py` builds the reference Mash sketch
    and metadata once from a committed, curated accession list
    (`cohorts/reference_plasmids/curated_accessions.tsv`, 16 real NCBI
    plasmids spanning *E. coli*, *Salmonella enterica*, *Klebsiella
    pneumoniae*, *Acinetobacter baumannii*, and *Staphylococcus aureus*, each
    with a one-line provenance justification). The built sketch/metadata are
    real downloaded data, not tracked metadata, so -- the same convention as
    `PLATON_DB`/`GENOMAD_DB`/`PLASME_DB` -- they live under `DATA_DIR/db`,
    gitignored.
  - `python/classify_operational_plasmid.py` calls the built-in `mash dist`
    against that sketch and calls `known_cluster` when the nearest reference
    is within `PLASMID_NOVELTY_SIMILARITY_THRESHOLD` (default Mash distance
    0.05, roughly ANI >= 95%) AND that reference's cluster has at least
    `PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS` members (default 2); otherwise
    `novel`. A missing `mash` binary or reference set gives
    `insufficient_reference`, never a guess.
  - Wired into `scripts/08_operational_reconstruct.sh` (`plasbench
    reconstruct`); results land in `results/<sample>/plasmid_similarity.tsv`
    and under `plasmid_novelty` in `selection_report.json`. A failed or
    skipped classification never blocks reconstruction or the rest of the
    report -- it is supplementary, not a gate.
  - See `docs/OPERATIONAL_SELECTION.md`'s new "Novel-vs-known plasmid
    classification" section for the full usage walkthrough.

### Changed

- **Relicensed from MIT to the GNU General Public License, version 3
  (GPL-3.0-only)**, effective from this point forward. Releases v0.1.0
  through v0.1.4 remain published under the MIT License as distributed;
  this change is not retroactive. See `LICENSE`, `NOTICE`, and
  `CITATION.cff`.

### Documentation

- Recorded the two real, permanent Zenodo dataset DOIs minted by the
  existing `zenodo-upload.yml` workflow when the v0.1.3/v0.1.4 GitHub
  Releases were created during the v0.1.x renumbering
  ([10.5281/zenodo.22671309](https://doi.org/10.5281/zenodo.22671309),
  [10.5281/zenodo.22671314](https://doi.org/10.5281/zenodo.22671314)), in
  both release notes and `cohorts/README.md`, per `docs/RELEASING.md`'s own
  instruction. These are dataset-only DOIs (the archived `cohorts/*.tsv`),
  not a software citation.

### Removed

- **PyPI publishing.** `.github/workflows/release.yml`'s `pypa/gh-action-pypi-publish`
  step (and the now-unused `python -m build` step that only fed it) failed on
  every real attempt with `invalid-publisher` -- the trusted-publisher
  registration on PyPI's side never actually matched this workflow, and
  `plasbench` was never reachable at pypi.org/project/plasbench despite
  `continue-on-error` making every release job show green. A step that
  always fails silently is worse than no step: it lets a broken channel look
  configured. The GitHub Release archive remains the Python-package
  distribution; see `RELEASING.md` for how to re-add PyPI later with a
  verified trusted publisher.

## [0.1.4] - 2026-09-08

Supersedes the removed v0.2.5-v0.2.8 tags.

### Added

- A separately executable metagenomic community/bin scoring route:
  `plasbench metagenomics`, or `plasbench run --mode metagenomics`.
- Strict community manifests, three-class plasmid/chromosome/virus truth,
  normalized graph/bin tables, global one-to-one bin matching, split/merge
  and contamination diagnostics, a run manifest, and
  `metagenomics.report.html`.
- A metagenomics installer profile for the tested baseline runtime
  dependencies (`metaSPAdes` through SPAdes and geNomad).
- An auditable optional orthogonal-validation evidence validator for
  long-read, hybrid, PCR, plasmid-extraction, conjugation, Hi-C, and
  optical-mapping records. Evidence is preserved separately and cannot
  inflate a score.
- Public cohort release and governance standards, including two-reviewer,
  conflict-of-interest, versioning, representation, and annual-refresh
  rules.
- An `amr_context` decision profile that treats curated AMR-gene recovery,
  plasmid recovery, bin quality, and structural penalties as co-primary;
  it safely falls back when an AMR truth table is unavailable.
- A deterministic, offline metagenomic demonstration fixture covering bin
  recovery, merge and contamination trade-offs, three-class classifier
  calls, uncertainty, and non-scoring mobilome evidence.
- An auditable tool-installer registry covering every supported, non-demo
  adapter, with `plasbench install-tools list`, `plan`, and `validate`
  modes.
- An external-benchmark importer that preserves source data, checksums, and
  truth-definition boundaries instead of mixing external scores into native
  PlasBench results.
- A candidate-quality dataset builder for downstream research only.
  Aggregate tool scores are explicitly not converted into fabricated bin
  labels.
- Strict reference-recovery-rate metrics and nested-validation model cards.
- A complete user-facing release guide (`docs/RELEASES.md`), a reusable
  GitHub Release template, and version-specific release notes under
  `docs/releases/`.

### Changed

- Refreshed public project identity to **PlasBench: A Reproducible,
  Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction
  Tools** with the tagline *Benchmarking plasmid reconstruction from
  sequence to biological function.* The stable `plasbench` command is
  unchanged.
- The isolate and metagenomic HTML reports now carry the updated project
  identity, plus auto-sized reconstruction dashboard frames, balanced
  evidence panels, run labels, and a clearer heatmap/report handoff.
- Installation guidance defaults to the verified latest-release installer
  and separates normal laboratory use from recovery and troubleshooting.
- The CLI reports a clear recovery command when launched outside a
  PlasBench project directory.

### Fixed

- Reject duplicate or malformed BMock12 gold-standard memberships, fail
  clearly when truth-backed metagenomic scoring receives no normalized
  predictions, and safely escape cohort metadata embedded in a
  self-contained HTML dashboard.

### Safeguards

- Metagenomic and isolate reports/rankings are structurally separated.
  Candidate bins are never represented as host assignments, circular
  closure, or clinical confirmation without independent evidence.
- `gplas2` remains source-runtime-only until its upstream runtime and
  classifier provenance can be installed reproducibly. It is deliberately
  not misrepresented as a one-command package installation.

## [0.1.3] - 2026-09-07

Supersedes the removed v0.2.0-v0.2.4 tags. Nothing here is on by default --
an existing cohort run behaves exactly as before unless a new flag is
switched on.

### Added

- Three long-read/hybrid tools: `hybracter_long`, `hybracter_hybrid`, and
  `trycycler_mob_recon`, a second independent long-read assembly path
  alongside Flye+MOB-Recon and Plassembler (assembler choice materially
  affects plasmid completeness on ONT data). Hybracter reuses the
  Plassembler database.
- Three opt-in ML classifiers, all short-read-track contig classifiers, not
  binners: `genomad` (gene-based neural classifier), `plasme` (alignment +
  transformer hybrid), `plasgraph2` (GNN over assembly-graph nodes).
- A new `pr_auc` metric: where an adapter publishes a candidates universe
  plus per-record probabilities, scoring sweeps every distinct probability
  as a threshold and reports the area under the precision-recall curve.
  Ranking stays on `mean_f1`; PR-AUC is supplementary.
- A read-quality ladder, the long-read analog of the depth ladder, with
  combined length+quality `--rungs` cutoffs.
- A leave-one-study-out decision-support model and multi-track
  recommendation support.
- `./update.sh` / `plasbench upgrade` for one-command version upgrades that
  reuse shared data across releases, plus a latest-release bootstrap
  installer.

### Changed

- Each tool is now scored under its own declared `analysis_track`
  (`config/tool_capabilities.tsv`), so one run correctly scores short-read,
  long-read, and hybrid tools together instead of applying one global track
  to every tool. Stage 7 (long-read reconstruction) is now part of the
  default stage list, before scoring.
- **The circularity guard (truth independence from long reads) now applies
  to all five long-read/hybrid tools**, including retroactively to
  `flye_mob_recon`, which had no guard before. This is a real behavior
  change for existing cohorts: a sample lacking
  `truth_independent_of_long_reads=yes` is now correctly **skipped** where
  it previously ran; each tool has a `<TOOL>_ALLOW_CIRCULAR_TRUTH=1`
  override.
- `docs/COHORTS.md`/`docs/METHODS.md` now name all five guarded tools with
  their override variables, instead of the two they listed before.

### Fixed

- CI no longer lets a failed PyPI publish block the GHCR image/GitHub
  Release.
- An upgrade no longer re-fetches shared data it should reuse.

## [0.1.2] - 2026-09-05

Supersedes the removed v0.1.6-v0.1.9 tags.

### Added

- `plasbench init-local`, staging a user's own FASTQ reads and reference
  into the pipeline, writing the truth table and sample-sheet row.
  Unlabelled sequences are written as `REVIEW`, never guessed.
- Two input validators that run before any tool starts: staged reads
  (missing/empty/not actually gzipped, mates out of order) and the truth
  table (unmatched ids, unlabelled sequences, bad `molecule_type`, tabs vs.
  spaces, length mismatches).
- Cohort download-size estimation and confirmation before fetching.
- Plassembler support on the long-read/hybrid track, with a circularity
  guard.

### Changed

- `THREADS`/`MEMORY_GB` now default to 80% of the detected machine's
  cores/RAM (floor 2 GB) instead of a fixed value.
- Databases are checked for presence before being re-downloaded; a partial
  download is reported as **incomplete**, never mistaken for a working
  install. Re-downloading is opt-in via `--force`.

### Fixed

- A failed download no longer aborts the whole cohort: failures are
  recorded per sample in `results/download_status.tsv` with automatic
  linear-backoff retry (`NETWORK_RETRIES`, default 3); the stage aborts
  only when every sample fails.
- Two parallelism tests now assert that work genuinely overlaps, measured
  from the stubbed tools' own process logs, rather than comparing elapsed
  time.

## [0.1.1] - 2026-09-04

Supersedes the removed v0.1.1-v0.1.5 tags.

### Added

- The packaged install-archive distribution
  (`plasbench-<version>.tar.gz` + `.tar.gz.sha256`, installed with
  `./install.sh --tools`).
- Three Galaxy tool wrappers (align/score/aggregate) with a real bioconda
  recipe and `plasbench-score`/`plasbench-aggregate` PATH entry points.

### Fixed

- Release archives no longer ship CRLF line endings, which previously made
  `plasbench test` die with `set: pipefail: invalid option name`.
- The `public-v2` cohort lock was regenerated against LF content and
  re-verified online against NCBI (32/32 pairs).
- `plasbench run` with no stage numbers no longer exits 2 on Python <=
  3.12. `install.sh` now bootstraps Miniforge itself when no conda is
  present.
- A micromamba prefix-resolution bug that aborted `plasbench install-tools`
  with "No prefix found" against a working install. `install-tools all` no
  longer pulls the incompatible bioconda `gplas` package; the explicit
  `gplas` profile now warns and points at gplas2 instead.
- **Install-critical**: `env/setup_conda.sh` no longer destroys an existing
  environment (including MOB-suite's 450 MB database) when re-run against a
  working install -- an existing environment is detected and updated in
  place, non-destructively.

## [0.1.0] - 2026-09-01

Initial public release: the verified `public-v1` cohort, a reproducible
environment lock, capability-aware scoring metrics, and the depth-ladder
workflow.

## Release Reading Guide

- **GitHub Release assets** are the checksum-verified source distribution for
  terminal installations. There is no PyPI package (removed; see "Unreleased"
  above) -- external bioinformatics tools and databases are installed
  separately through the documented installer routes regardless.
- **GHCR** supplies the container image. Use an immutable version tag such as
  `ghcr.io/ubeffiong/plasbench:v0.1.5` for reproducible work, not `latest`.
- **Run manifests and cohort locks** are required companions when reporting or
  comparing scientific results; a software version alone is insufficient.
