# What PlasBench can and cannot do, and what the assistant can do for you

This page is for the AI help and for people. Every statement below is taken from a guide or from the program; the source is named in a comment in the file.

## What PlasBench is for

<!-- source: README.md (opening paragraphs, "PlasBench does / does not" table), docs/SCIENTIFIC_GUIDE.md sections 1 and 17 -->
PlasBench benchmarks how well plasmid-reconstruction tools recover plasmids, using complete long-read or hybrid assemblies as ground truth. It compares tools on a common footing and shows how and where each fails. It does **not** identify, cluster or classify the plasmids in your own sample, annotate or interpret them, infer transmission, outbreaks or horizontal gene transfer, or prove that a plasmid is closed or clinically meaningful. The shipped cohorts are small and taxonomically narrow and there is no laboratory confirmation.

## The pipeline stages (0 to 9)

<!-- source: config/workflow_steps.tsv -->
`plasbench run` goes through these stages, each with switches on the Workflow page:

- **0 Check and install**: makes the folders, checks the tools and databases, offers to install what is missing. Always runs.
- **1 Download**: fetches each isolate's reference assembly and Illumina reads (about 630 MB per isolate). Needs the internet. Skipped for your own local files.
- **2 Reference truth**: labels each reference sequence plasmid or chromosome. Optional annotation tools (MOB-typer, abricate, AMRFinderPlus, ISEScan, barrnap) add evidence and never change F1.
- **3 QC, trim and assemble**: fastp trims, SPAdes (or Unicycler) assembles. The tools run on this assembly.
- **4 Run the tools**: each enabled plasmid tool runs on every assembly; your own tools run here too. Baselines (coverage, reference, replicon) give the tools something to beat.
- **5 Score**: compares every tool's plasmids with the truth and adds the extra analyses.
- **6 Aggregate and report**: combines the isolates into the leaderboard, the statistics and the report.
- **7 Long-read and hybrid tools**: optional tools that need long reads.
- **8 Operational reconstruction**: reconstructs plasmids for one new isolate with the best-ranked tool (a separate command).
- **9 Metagenomics track**: a separate track that scores normalised community outputs.

## Optional switches on the Workflow page

<!-- source: config/workflow_steps.tsv (setting_key, default, cli_flag), config/config.sh -->
Each stage has a core step that always runs and optional items, each tied to one setting you switch on or off on the Workflow page (saved in `config/local.env`):

- **Stage 2 truth evidence**: `RUN_REFERENCE_ANNOTATION` and one switch per annotation caller (`ANNOTATE_WITH_MOB_TYPER`, `ANNOTATE_WITH_ABRICATE`, `ANNOTATE_WITH_AMRFINDER`, `ANNOTATE_WITH_ISESCAN`, `ANNOTATE_WITH_BARRNAP`). They add evidence to the truth table and never change F1. `ISESCAN_SCOPE=plasmids` (default) makes ISEScan search only the truth plasmids; the chromosome is then reported as "not evaluated (chromosome not searched)", never as zero. `all` searches every sequence (slow: about 30 minutes per 5 Mbp genome).
- **Stage 3 assembly**: `ASSEMBLER` = `spades` (default) or `unicycler`; `RUN_ASSEMBLY_QC_GATE` keeps a poor assembly out of the ranking.
- **Stage 4 tools**: one `RUN_<TOOL>` switch per plasmid tool (for example `RUN_MOB_RECON`, `RUN_PLATON`, `RUN_PLASMIDSPADES`, `RUN_GENOMAD`, `RUN_PLASME`). A tool that is switched on but not installed is offered for installation, not silently skipped.
- **Stages 5 and 6 extra analyses**: `RUN_DIMENSION_ANALYSES`, `RUN_RANKING_STABILITY`, `RUN_RANK_SENSITIVITY`, `RUN_PERFORMANCE_DRIVERS`, `RUN_RECOMMENDER_EVAL`, `RUN_QUAST_DIAGNOSTICS`, `MULTIQC_REPORT`. They are advisory: none of them changes the leaderboard.
- **Stage 7**: the long-read and hybrid tools (`RUN_FLYE_MOB_RECON`, `RUN_PLASSEMBLER`, `RUN_HYBRACTER_LONG`, `RUN_HYBRACTER_HYBRID`, `RUN_TRYCYCLER_MOB_RECON`) need long reads.

## Run profiles: fast, standard, thorough

<!-- source: config/run_profiles.tsv, plasbench/cli.py (run --profile) -->
`plasbench run --profile fast|standard|thorough` (or `RUN_PROFILE`, or the New benchmark form) picks a set of the optional switches. **standard** is the default and changes nothing. **fast** switches off the optional analyses that never change the leaderboard: ISEScan (`ANNOTATE_WITH_ISESCAN=0`, measured at about 30 minutes per isolate), the ranking-stability and rank-sensitivity sweeps, performance drivers, the recommender evaluation, the per-dimension tables, bin agreement, candidate multiplicity and MultiQC. **thorough** turns optional extras on: `ISESCAN_SCOPE=all`, difficulty descriptors, QUAST diagnostics, truth-depth anomalies and the replicon baseline. A profile only sets a key you did not set yourself, and no profile touches the scoring, the truth labels or the leaderboard. The profile is recorded in the run manifest and the report. `plasbench profile-run` shows where the time of a finished run went.

## Settings that change how a run uses the computer

<!-- source: config/config.sh comments for each key -->
- `THREADS` (CPU threads per tool), `MAX_PARALLEL_SAMPLES` (isolates at once in stages 1 to 5) and `MAX_PARALLEL_TOOLS` (tools at once per isolate in stage 4): together they decide how many CPU cores are busy.
- `MEMORY_GB` and `ASSEMBLY_MEMORY_GB`: the assembler's memory budget. `AUTO_RESOURCES=1` (default) raises it to what SPAdes says it needs, halves threads after an out-of-memory kill (exit 137) and skips an isolate that cannot fit, saying so.
- `TOOL_TIMEOUT_SECONDS`: a time limit per tool run (exit 124 when reached).
- `MAX_RUN_DOWNLOAD_GB` (empty = no limit) skips an isolate whose reads are larger ("skipped by choice"); `WARN_RUN_DOWNLOAD_GB` (default 5) only warns.
- `KEEP_AWAKE=1` (default) asks the computer not to sleep while a run is active; a sleep that still happens is recorded and left out of every elapsed time ("The computer was asleep from ... ; the run was paused, not slow").
- `LOCAL_INPUTS_ONLY` / `--local-inputs`: use your own staged files and never download. `REQUIRE_CURATED_METADATA=0` lets stage 0 accept a sheet that has only `sample_id`, `assembly_accession` and `sra_run` (your own isolates).
- Scoring thresholds (`CPRR_*`, `HEADLINE_*`, `*_THRESHOLD`) are pre-registered decisions: the assistant never changes them.

## Evidence, independence and tracks

<!-- source: README.md "Read support", "Limits", docs/COHORTS.md (tiers), docs/SCIENTIFIC_GUIDE.md sections 9 and 10 -->
Truth has quality tiers: tier A is curator-reviewed, tier B means every NCBI evidence check passed but no publication was reviewed, tier C is the weakest. The primary analysis needs a reference whose quality is within the tier limit and whose evaluation independence is `independent` (long-read truth polished with no reads or with reads independent of the benchmark). A tool is never scored against the reads its own truth was built from. Results are never pooled across input tracks: short-read, long-read and hybrid each have their own leaderboard. The metagenomic track is separate, with its own manifest and report.

## How scoring works

<!-- source: README.md "Evaluation framework", docs/METHODS.md -->
The prediction is projected onto the complete reference and scored per reference base (true positives, false positives, false negatives, precision, recall, F1) using primary alignments only, so repeats cannot inflate a claim. A failed run on a plasmid-bearing isolate scores F1 = 0; resource kills (exit 124 or 137) can instead be excluded with `--resource-failures exclude`. The correct plasmid reconstruction rate (CPRR) is the share of truth plasmids reconstructed correctly. Tasks (classification, binning reconstruction, sequence reassembly) are ranked separately.

## What PlasBench needs and what it cannot do for you

<!-- source: INSTALL.md (Windows and WSL 2 section), README.md "What the machine needs", config/workflow_steps.tsv columns needs_internet, mem_gb, disk_gb -->
It is Ubuntu-first. On Windows it runs in WSL 2 (Ubuntu) or with Docker Desktop's WSL 2 backend. Some tools are heavy (Plasmer documents a 32 GB memory minimum; several need databases of 1 to 3 GB). Downloads and installs need the internet. Some steps are manual: PlasBench never runs `sudo` or asks for an administrator password, and a licence such as Gurobi for Plasbin-flow is yours to provide.

## The window

<!-- source: plasbench/data/ui.html (navigation: home, setup, workspace, cohorts, isolates, wizard, runs, jobs, tools, addtool, prereg, git, commands, settings, help) -->
Pages: Home, Setup, Workspace and studies, Cohorts, Your own isolates, New benchmark (a four-step wizard that ends in the exact command), Runs, Jobs, Tools, Add a tool, Pre-registration, Version control, Commands, Settings, Guides. The AI help is the last tab of the side panel (Alt+Shift+H). Settings are saved for this computer in `config/local.env`.

## What the assistant can do

<!-- source: docs/AI_HELP.md, plasbench/ai_ui.py, plasbench/ai_files.py, plasbench/ai_folder.py -->
- Answer questions from PlasBench's own guides, and from its model's general knowledge (marked "General knowledge:").
- Propose a command with where to run it. It runs only after you press a button and confirm.
- Take you somewhere: open a page, a tab, a Guides section. One click.
- Change a Setting (a card shows the old and new value, you confirm, it can be undone), fill in the New benchmark form (nothing starts), open the report, type a command in the Terminal tab (you press Enter), start the tool install (the usual consent dialog) or switch conda and Docker (confirmation).
- Guide you step by step, without needing the model: set up a run from a folder, fix a sample sheet, install the tools you need, add your own tool, find out why the last run failed.
- If you choose a folder, PlasBench itself (not the assistant) reads names, sizes and the first lines, and shows you what it found. A summary goes to the assistant only when you press Share. The assistant can then propose a file plan (create folders, copy, move or rename files, write or repair a sample sheet). You see exactly what would change, with a diff for sheets, and only Apply does it. Undo restores the earlier state.

## What the assistant cannot do

- It cannot see your files. It never opens FASTQ, FASTA, sheets, results or logs. Only the summary you chose to share reaches it.
- It cannot run anything by itself, and it cannot browse the web or read a web page.
- It cannot delete files, overwrite a file without keeping a backup, write outside the folder you chose, create links, change permissions or run programs. It cannot decompress or compress files.
- It cannot change its own settings, keys or sign-in, or any Setting that holds a key, an e-mail address or a path.
- It can be wrong. Facts about PlasBench come from the documentation; its general knowledge can be mistaken. Check anything important.
- A free model follows instructions less reliably than a large one. The guided flows therefore work without the model, and a command or plan is checked by PlasBench's own code however it was written.
- Providers set their own limits: OpenRouter free models are limited in requests per minute and per day; Hugging Face free accounts have no included credits; a local model on this computer has no account but may be slower and less accurate.

## Your own isolates, sample sheets and troubleshooting (assistant flows)

<!-- placeholder: filled with the description of the assistant's isolate set-up, sheet check and run-troubleshooting flows -->

## Action blocks the assistant can write

<!-- source: plasbench/ai_ui.py (ids and schemas), plasbench/ai_files.py (operations), plasbench/ai_actions.py (parse_reply). Delivered by retrieval, not in the permanent prompt. -->
Each block is one fenced block with one JSON object. It becomes a card; nothing runs without a click. PlasBench validates it again on the server.

Window action, fence `pb-ui`, one of:
`{"ui":"go","target":"settings"}` (targets: home, setup, tools, addtool, prereg, settings, workspace, git, wizard, isolates, cohorts, runs, jobs, commands, help; optional "sub": runs: ongoing, attention, completed, all; help: a guide name)
`{"ui":"setting","key":"RUN_PLATON","value":"1"}` (a Settings key from the Settings page; a switch is 0 or 1)
`{"ui":"prefill","fields":{"source":"sheet","study":"my_study","max_isolates":5,"local_inputs":true,"samples":"config/my_isolates.tsv"}}` (fills the New benchmark form; starts nothing)
`{"ui":"open","what":"report"}` or `{"ui":"open","what":"terminal","cmd":"plasbench status"}`
`{"ui":"install","profile":"core"}` and `{"ui":"runtime","use":"docker"}`
`{"ui":"flow","name":"setup_run"}` (names: setup_run, fix_sheet, install_tools, add_tool, diagnose)

File plan, fence `pb-files`, only after the person has shared a folder summary: `{"ops":[...],"why":"one sentence"}` with operations
`{"op":"mkdir","path":"data/S1"}`, `{"op":"copy","from":"raw/a.fastq.gz","to":"data/S1/S1_1.fastq.gz"}`, `{"op":"move","from":"a.tsv","to":"config/a.tsv"}`,
`{"op":"write_sheet","path":"config/my.tsv","columns":["sample_id","assembly_accession","sra_run"],"rows":[["S1","NA","S1"]]}` and
`{"op":"patch_sheet","path":"x.tsv","edits":[{"type":"fix_delimiter"},{"type":"rename_column","from":"id","to":"sample_id"},{"type":"normalise_ids"},{"type":"set_cell","row":3,"column":"organism","value":"Escherichia coli"},{"type":"fill","column":"gram_group","value":"Gram-negative"}]}`.
Paths are relative to the shared folder, written with `/`, no `..`. There is no delete.
