# Window inputs with a known set of values (audit of 27 November 2026)

Every input in the window was checked for whether its valid values are a finite known set. The list below was derived from the code that validates each value (argparse `choices`, python
constants, `config/prereg.tsv`, the keywords a parser understands, the scripts that compare the value), not from guesses. **One registry** holds the options: `config/setting_options.tsv`
(read by `python/setting_options.py`). The window's dropdowns, the server's save check and the validators that can read it all use it, and `test/test_setting_options.py` fails when the
registry differs from the code that really validates a value.

## What changed

* 33 settings are now dropdowns (30 exact lists, 3 keyword-plus-number or keyword-plus-folder combos) in **Settings**; the same options appear on the **workflow rows** (and so in the
  **New benchmark wizard**) for the 7 settings that have a workflow row, and on the **command forms** (`--read-depth-cap` of `run` and `report`). `SHORT_READ_QC_MODE` offers Off, Report and
  Enforce everywhere, with what each does and the default marked.
* Each option shows its plain label, its stored value and a one-sentence meaning beside the dropdown (not hover-only); the default is marked; the saved value is always the selected option;
  a saved value that is not in the list (a hand-edited config, an older version) is shown as **Custom: &lt;value&gt;**, kept, and never replaced by a save that does not change it.
* A combo (READ_DEPTH_CAP_X: `off` or a number of x coverage, minimum 1; WORK_DIR and DOWNLOAD_TMP_DIR: `auto`, `data` or a folder) is a dropdown of the keywords plus a "Number..." or
  "Folder..." choice that reveals a validated input with its unit and limit.
* Saving writes exactly the stored value (never the label, never a changed case). The server refuses a NEW value outside the list with a plain sentence; clearing, an unchanged value and a
  value already saved never block a save. Reset to default, "changed" markers, the search box and the per-setting help are unchanged.
* `config/ai_settable.tsv`: `MULTIQC_REPORT` now lists `auto|on|off` (it listed `auto|0|1`, which the parser accepts but the dropdown does not offer); a test checks that every value the
  assistant may set is one the registry lists. The assistant still cannot set `enforce` for the QC gate or assembly selection (a deliberate narrower list, listed in the test as a subset).

## The converted settings

| Setting | Kind | Options (stored values) | Where it appears | Source of truth |
|---|---|---|---|---|
| `SHORT_READ_QC_MODE` | enum | off, report, enforce | Settings, workflow rows / wizard | python/short_read_qc.py --mode choices |
| `ASSEMBLY_SELECTION_MODE` | enum | off, report, enforce | Settings, workflow rows / wizard | scripts/03_assemble.sh (off, report, enforce) |
| `ASSEMBLY_SELECTION_POLICY` | enum | fixed, quality | Settings | python/assembly_selection.py --policy choices |
| `READ_SOURCE` | enum | auto, sra, ena | Settings | scripts/01_download.sh (auto, sra, ena) |
| `UPDATE_CHECK` | enum | auto, off | Settings | plasbench/updatecheck.py (auto, off) |
| `ASSEMBLER` | enum | spades, unicycler | Settings, --assembler (run form) | plasbench/cli.py --assembler choices |
| `FLYE_READ_TYPE` | enum | nano-raw, nano-hq, pacbio-raw, pacbio-hifi | Settings, --flye-read-type (run form) | plasbench/cli.py --flye-read-type choices |
| `ANALYSIS_TRACK` | enum | short_read, long_read, hybrid | Settings, --analysis-track (run form) | python/tool_capabilities.py ANALYSIS_TRACKS |
| `ANALYSIS_TRACK_FILTER` | enum | (empty), short_read, long_read, hybrid | Settings | python/tool_capabilities.py ANALYSIS_TRACKS (empty = every enabled tool under its own track) |
| `DECISION_PROFILE` | enum | accuracy_first, amr_surveillance, rapid_screening | Settings, --decision-profile (run form) | plasbench/cli.py --decision-profile choices |
| `RUN_PROFILE` | enum | standard, fast, thorough | Settings, --profile (run form) | python/run_profiles.py PROFILES |
| `TRUTH_LABEL_SCHEME` | enum | ncbi, nonchromosomal, evidence | Settings | config/prereg.tsv choices (python/prereg_admin.py) |
| `HEADLINE_REFERENCE_INDEPENDENCE` | enum | independent, any | Settings | config/prereg.tsv choices (python/prereg_admin.py) |
| `HEADLINE_INDEPENDENCE` | enum | independent, partially_independent, dependent, unknown | Settings | config/prereg.tsv choices (python/prereg_admin.py) |
| `PLASBENCH_CI_METHOD` | enum | percentile, cluster_t, bootstrap_t | Settings | config/prereg.tsv choices (python/prereg_admin.py) |
| `PLASBENCH_CI_METHOD_STRATIFIED` | enum | percentile, cluster_t, bootstrap_t | Settings | config/prereg.tsv choices (python/prereg_admin.py) |
| `MULTIQC_REPORT` | enum | auto, on, off | Settings, workflow rows / wizard | python/run_multiqc.py (auto, on, off) |
| `ISESCAN_SCOPE` | enum | plasmids, all | Settings | python/annotate_reference.py ISESCAN_SCOPES |
| `STATS_VALIDATION_MODE` | enum | smoke, full | Settings | python/simulate_validation.py SETTINGS |
| `DISSIMILARITY_REPEATS` | enum | aware, drop | Settings | python/bin_agreement.py --repeats choices |
| `LEAKAGE_CUTOFF_POLICY` | enum | per_tool, fixed_date | Settings | python/flag_database_overlap.py --policy choices |
| `LEAKAGE_DATE_BASIS` | enum | earliest_public, assembly, read | Settings | python/flag_database_overlap.py LEAKAGE_DATE_BASES |
| `RUN_PUBLISHED_COMPARISON` | enum | auto, off | Settings, workflow rows / wizard | scripts/06_aggregate.sh (auto, off) |
| `RUN_PLSDB_NOVELTY` | enum | auto, off | Settings, workflow rows / wizard | scripts/06_aggregate.sh (auto, off) |
| `RUN_PLASEVAL_GATE` | enum | auto, on, off | Settings, workflow rows / wizard | scripts/06_aggregate.sh (auto, on, off) |
| `PROTEIN_ANNOTATION_ENGINE` | enum | bakta, prokka, none | Settings | python/annotate_proteins.py --engine choices |
| `PLASBENCH_RUNTIME` | enum | conda, docker | Settings, --runtime (run form) | plasbench/cli.py runtime choices |
| `PLASBENCH_DOCKER_PULL` | enum | missing, always, never | Settings | plasbench/docker_runtime.py PULL_POLICIES |
| `MINIMAP2_PRESET` | enum | asm5, asm10, asm20 | Settings | minimap2 -x assembly presets (scripts/05_score.sh passes it to -x) |
| `TRUTH_LONG_READ_PRESET` | enum | map-ont, map-hifi, map-pb | Settings | minimap2 -x read presets (scripts/02_truth.sh passes it to -x) |
| `READ_DEPTH_CAP_X` | combo | off, number | Settings, workflow rows / wizard, --read-depth-cap (run form) | python/depth_cap.py parse_cap (off, none, no, false, whole, 0, or a number) |
| `WORK_DIR` | combo | auto, data, folder | Settings | python/work_dir.py resolve (auto, data, or a folder) |
| `DOWNLOAD_TMP_DIR` | combo | auto, data, folder | Settings | python/download_scratch.py resolve (auto, data, or a folder) |

## Left as they were, and why

| Field | Widget | Why it is not a dropdown from this registry |
|---|---|---|
| 110 on/off settings (`RUN_*`, `ANNOTATE_WITH_*`, ...) | already a select: Default (x), `1 - on`, `0 - off` | already a dropdown with a finite set; the validator is "0 or 1" |
| 68 whole-number settings (30 with a range in `config/setting_ranges.tsv`) | number input with min, max and step | not a finite set; the range table is their source of truth |
| `RFPLASMID_SPECIES` | text | RFPlasmid's own species list lives in that tool, not in this repository, so it cannot be checked here |
| `SIMULATE_SHORT_MODEL`, `SIMULATE_LONG_MODEL` | text | the simulators' model names come from the installed simulator, not from PlasBench |
| `ANNOTATION_AMR_DB`, `ANNOTATION_REPLICON_DB`, `REPLICON_ABRICATE_DBS` | text | the names depend on the databases installed for Abricate on this computer (one may be a space-separated list) |
| `TRUTH_LONG_READ_PRESET`, `MINIMAP2_PRESET` | dropdown with the common minimap2 presets | listed (map-ont, map-hifi, map-pb; asm5, asm10, asm20) but the names are minimap2's: any other value stays as "Custom" and is passed through. This is the one registry entry that is not checked against code that rejects other values |
| `tools new --output-format` (command form) | text | a comma list of several of contig_bins, contig_labels, plasmid_fasta, fasta_dir, adapter: a multi-value, not a single choice |
| list options with choices (for example `run stages`) | space-separated text | several values at once |
| paths, accessions, names, tokens, `AI_PROVIDER` / `AI_MODEL` and the AI pane's pickers | text / the AI pane's own selects | not a fixed set (or in the AI pane, which another change is editing; its provider and model lists already come from `plasbench/ai_providers.py`) |

## Other surfaces

* **New benchmark wizard**: its fields come from the same command description, so every argparse `choices` option is already a select (70 of the 435 command options) and every switch a
  toggle; the only text option with a known set (`--read-depth-cap`) is now the combo; the workflow rows inside the wizard show the registry dropdown (wizard value = per-run, stored in the
  run's environment).
* **Workflow rows**: switches stay as they were; a row whose setting has more than two values (QC gate, assembly selection, MultiQC, read-depth cap, the published comparison, PLSDB
  novelty, the PlasEval gate) also shows the dropdown. The row's "changed" marker still follows the on/off state (the contract in `workflow_steps.py`); the dropdown shows the exact value.
* **Tool install / consent dialogs, add-your-own-tool form**: their choices (install method, how it runs, task, track) are already selects built from fixed lists; nothing was left as
  text except the multi-value output format above.
* **Run/job options**: see the wizard line above.

## How it is checked

* `test/test_setting_options.py`: every registry key is a setting in `config/config.sh`, the marked default is the one `config.sh` uses, every option has a label and meaning;
  **parity** with the validating code for each setting; the AI list is a subset; check() and validate_changes() behaviour (listed value, keyword, number, folder, custom kept, clearing);
  Settings rows and workflow items carry identical options; saving writes exactly the stored value; the page's option logic runs in node (selected option, `Custom: x`, combo number
  and folder, validation); the page script passes `node --check`.
* `test/test_setting_options_browser.py` (`PLASBENCH_BROWSER_TESTS=1`, Playwright + Chromium): real browser, real server: change enum dropdowns, a number combo, a folder combo, keep a
  custom value, save, reload and see the same options; the workflow row and the run form show the same list. Only the unit tests run in CI.
