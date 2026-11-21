"""Hover / focus help for every field of the setup window, kept out of the page so the window has no hard-coded option text.

Plain dicts: ARGS[command][dest] -> {"summary", "choices": {choice: meaning}, "when", "setting"}; SETTINGS[KEY] -> same keys;
WIZARD[control] -> same keys for the wizard controls that are not command-line options. Everything below is taken from the code it
describes (plasbench/cli.py help and env mapping, config/config.sh comments, scripts/01_download.sh, python/fetch_ena_reads.py,
python/recommendation_model.py). Where the code shows no more than a name, only that is said.

`tooltip(entry, arg)` merges an entry with the argparse facts (flag, default) into what the window shows; ui_schema.schema() adds it
to every argument as `tooltip` (and the choice meanings as `choice_help`), so a command without an entry still gets its CLI help.
"""
from __future__ import annotations

TOOLS = {
    "mob_recon": ("RUN_MOB_RECON", "MOB-suite reconstruction"),
    "platon": ("RUN_PLATON", "Platon classification"),
    "plasmidspades": ("RUN_PLASMIDSPADES", "plasmidSPAdes"),
    "gplas2_mob": ("RUN_GPLAS2_MOB", "gplas seeded by MOB-recon membership"),
    "gplas2_external": ("RUN_GPLAS2_EXTERNAL", "gplas with external classifier TSVs"),
    "flye_mob_recon": ("RUN_FLYE_MOB_RECON", "optional Flye plus MOB-Recon long-read reconstruction"),
    "plassembler": ("RUN_PLASSEMBLER", "optional Plassembler hybrid (long+short) plasmid assembly"),
    "hybracter_long": ("RUN_HYBRACTER_LONG", "optional Hybracter long-read-only assembly with plasmid recovery"),
    "hybracter_hybrid": ("RUN_HYBRACTER_HYBRID", "optional Hybracter hybrid (long+short) assembly with plasmid recovery"),
    "trycycler_mob_recon": ("RUN_TRYCYCLER_MOB_RECON", "optional Trycycler consensus long-read assembly plus MOB-Recon"),
    "genomad": ("RUN_GENOMAD", "optional geNomad ML classification"),
    "plasme": ("RUN_PLASME", "optional PLASMe alignment+transformer classification"),
    "plasgraph2": ("RUN_PLASGRAPH2", "optional plASgraph2 GNN classification (assembly graph)"),
    "rfplasmid": ("RUN_RFPLASMID", "optional RFPlasmid random-forest classification (assembly contigs)"),
    "plasmidhunter": ("RUN_PLASMIDHUNTER", "optional PlasmidHunter gene-content Naive Bayes classification (assembly contigs)"),
    "plasmer": ("RUN_PLASMER", "optional Plasmer ensemble classification (assembly contigs; requires ~32GB RAM)"),
    "plascope": ("RUN_PLASCOPE", "optional PlaScope Centrifuge classification (E. coli/Klebsiella only)"),
    "plasmidec": ("RUN_PLASMIDEC", "optional PlasmidEC majority-vote ensemble classification (eight species only)"),
}

TRACKS = {
    "short_read": "Score only tools whose declared analysis_track (config/tool_capabilities.tsv) is short_read.",
    "long_read": "Score only tools whose declared analysis_track is long_read.",
    "hybrid": "Score only tools whose declared analysis_track is hybrid (long plus short reads).",
}

_TOOL_ENTRIES = {
    dest: {"summary": f"Turn {label} on or off for this run only.",
           "choices": {"on": f"Run it this time (the command sets {var}=1).",
                       "off": f"Skip it this time (the command sets {var}=0).",
                       "": f"Leave it as the {var} setting saved for this computer says (Tools page or Settings)."},
           "when": f"Leave on 'default' unless you want a different choice than your saved {var} setting for this one run.",
           "setting": var}
    for dest, (var, label) in TOOLS.items()
}

_RUN = {
    "stages": {"summary": "Run only some stages of the pipeline instead of all of them.",
               "choices": {"0": "setup", "1": "download", "2": "truth", "3": "assemble", "4": "reconstruct",
                           "5": "score", "6": "aggregate and HTML report", "7": "optional long-read reconstruction"},
               "when": "Leave empty to run the whole pipeline. Choose stages to resume or redo part of a benchmark, e.g. 5 and 6 to re-score and rebuild the report."},
    "mode": {"summary": "Which workflow to run.",
             "choices": {"isolate": "Benchmark isolates that have a reference (truth) genome. The default.",
                         "metagenomics": "The separate metagenomics track: scores normalized community outputs (see predictions dir).",
                         "meta": "Shorthand for metagenomics; the command converts it to metagenomics.",
                         "beta": "Shorthand for metagenomics; the command converts it to metagenomics."},
             "when": "Leave on isolate unless you are scoring metagenomic community outputs."},
    "predictions_dir": {"summary": "Metagenomics only: the folder holding <tool>/<community>.bins.tsv normalized outputs.",
                        "when": "Leave empty for isolate runs."},
    "samples": {"summary": "The sample-sheet TSV to benchmark (columns such as sample_id, assembly_accession, sra_run).",
                "when": "Leave empty to use config/accessions.tsv, or use cohort for a bundled cohort.", "setting": "SAMPLE_SHEET"},
    "cohort": {"summary": "A bundled cohort by name: shorthand for --samples cohorts/<NAME>.tsv. With meta, --cohort bmock12 materializes the bundled physical truth control.",
               "when": "Leave empty when you give a sample sheet."},
    "max_isolates": {"summary": "Run only N isolates of the cohort or sheet (any number you choose). The sheet itself is not changed: a copy with those rows is written next to the results.",
                     "choices": {"balanced": "The isolates are a balanced selection: spread across species and studies, and across recent and older genomes, so a small run is a fair miniature of the cohort."},
                     "when": "Leave empty to run all isolates."},
    "independent_truth_only": {"summary": "Run only isolates whose truth is independent of the benchmark's reads (long-read-only or long-read-first, polished with no reads or independent reads). The cohort file is not changed; a copy is written next to the results.",
                               "when": "Switch on to avoid truth that shares reads with the benchmark; combine with max isolates for a balanced N of them."},
    "isolate_order": {"summary": "With max isolates: which N isolates are chosen.",
                      "choices": {"balanced": "Spread the N isolates across species, studies and recent / older genomes (the default).",
                                  "file": "Take the first N rows exactly as they appear in the sheet."},
                      "when": "Only matters when you set max isolates."},
    "write_script": {"summary": "Write the exact resolved commands to this file instead of running them, so you can review or edit them and run them yourself with bash.",
                     "when": "Leave empty to run now. Settings given as environment values by the window (Downloads and reliability) are not part of the script."},
    "data_dir": {"summary": "Folder for downloaded references, reads and assemblies for this run; the study remembers it for its later runs. The default shared folder is reused by every study and kept when a study is deleted.",
                 "when": "Leave empty to use the shared data folder (or the folder this study recorded earlier).", "setting": "DATA_DIR"},
    "keep_data_in_study": {"summary": "Keep this run's downloaded reads and assemblies inside the study folder, in <study>/data. That folder is git-ignored and is deleted together with the study; the study remembers the choice so Resume and later runs find the reads.",
                           "when": "Cannot be combined with data dir. Leave off to use the shared folder."},
    "study_location": {"summary": "Create the study folder as PARENT_DIR/NAME instead of in the workspace: on another drive, or anywhere you choose. PlasBench remembers where it is. The folder must already exist; it is never created for you.",
                       "when": "Leave empty to use the workspace."},
    "results_dir": {"summary": "Folder for predictions, scores and reports, instead of a study folder.",
                    "when": "Leave empty: the run gets its own study folder in the workspace.", "setting": "RESULTS_DIR"},
    "study": {"summary": "Keep this run in its own study folder <workspace>/NAME/ (results, logs, tmp and a study.json record). Without a name the study is named after the cohort or sample sheet.",
              "when": "Leave empty to use the automatic name; type a name to keep runs apart."},
    "open_report": {"summary": "Open benchmark.report.html in your browser after a successful report-producing run; never prompts.",
                    "when": "Switch on if you want the report to appear when the run finishes."},
    "no_report_prompt": {"summary": "Do not offer to open benchmark.report.html when an interactive run finishes. The window always sets this so the run never stops to ask a question.",
                         "when": "Only useful when you run the command in a terminal."},
    "log_dir": {"summary": "Folder for tool and mapping logs.", "when": "Leave empty to use the run's own logs folder.", "setting": "LOG_DIR"},
    "platon_db": {"summary": "Path to the installed Platon database.", "when": "Leave empty to use the installed copy.", "setting": "PLATON_DB"},
    "genomad_db": {"summary": "Path to the installed geNomad database directory (containing genomad_db/).", "when": "Leave empty to use the installed copy.", "setting": "GENOMAD_DB"},
    "plasme_db": {"summary": "Path to the installed PLASMe database directory.", "when": "Leave empty to use the installed copy.", "setting": "PLASME_DB"},
    "plasgraph2_model_dir": {"summary": "Path to plASgraph2's pretrained model directory (e.g. its cloned repo's model/ESKAPEE_model/).", "when": "Needed only if plASgraph2 is switched on.", "setting": "PLASGRAPH2_MODEL_DIR"},
    "gplas2_external_predictions_dir": {"summary": "Directory containing <sample>.tsv external gplas2 classifier files.", "when": "Needed only if gplas2_external is switched on.", "setting": "GPLAS2_EXTERNAL_PREDICTIONS_DIR"},
    "local_inputs": {"summary": "Use pre-staged data/<sample>/ inputs only; never download from NCBI or SRA.",
                     "when": "Switch on when your reads and references are already on disk.", "setting": "LOCAL_INPUTS_ONLY"},
    "long_reads_file": {"summary": "Long-read filename within each sample directory.", "when": "Leave empty for long_reads.fastq.gz.", "setting": "LONG_READS_FILE"},
    "analysis_track": {"summary": "Score only tools declared under this track this run (each tool's own track is still stamped correctly regardless).",
                       "choices": dict(TRACKS),
                       "when": "Leave unset to score every enabled tool under its own track in one run.", "setting": "ANALYSIS_TRACK_FILTER"},
    "decision_profile": {"summary": "Named weight set for operational recommendations. A profile only changes which tool ranks highest; it never changes which tools are eligible.",
                         "choices": {"accuracy_first": "The original formula (the default): F1 weighs most (0.45), then plasmid recovery (0.18).",
                                     "amr_surveillance": "Weighs plasmid recovery most (0.35) and penalises failed runs more (-0.08); an approximation of surveillance priorities from what is measured.",
                                     "rapid_screening": "Lower F1 weight (0.35) and a resource penalty five times larger (scale 5.0), so cheaper tools rank higher."},
                         "when": "Leave unset for accuracy_first.", "setting": "DECISION_PROFILE"},
    "threads": {"summary": "CPU threads per tool.", "when": "Leave empty to use the setting worked out from this computer's cores. Threads apply per tool: parallel samples x parallel tools x threads should not exceed your CPU count.", "setting": "THREADS"},
    "memory_gb": {"summary": "SPAdes memory limit in GB.", "when": "Leave empty to use the setting, worked out from the memory available on this computer.", "setting": "MEMORY_GB"},
    "parallel_samples": {"summary": "Samples to download, assemble, reconstruct and score concurrently.", "when": "Leave empty for 1 (one sample at a time).", "setting": "MAX_PARALLEL_SAMPLES"},
    "parallel_tools": {"summary": "Independent reconstruction tools to run concurrently per sample in stage 4; gplas2_mob always waits for mob_recon.", "when": "Leave empty for 1 (one tool at a time).", "setting": "MAX_PARALLEL_TOOLS"},
    "assembler": {"summary": "Short-read assembler.",
                  "choices": {"spades": "SPAdes (the default).", "unicycler": "Unicycler: cleaner graphs but slower (config.sh); also needed by some tools that use the assembly graph."},
                  "when": "Leave empty for the saved ASSEMBLER setting (spades unless you changed it).", "setting": "ASSEMBLER"},
    "min_read_len": {"summary": "Discard reads shorter than this after fastp.", "when": "Leave empty for the saved setting.", "setting": "MIN_READ_LEN"},
    "minimap2_preset": {"summary": "minimap2 assembly preset used when mapping for scoring.", "when": "Leave empty for the saved setting (asm5).", "setting": "MINIMAP2_PRESET"},
    "flye_read_type": {"summary": "Flye read-type option for optional stage 7, naming the long-read technology.",
                       "choices": {"nano-raw": "Flye's nano-raw option (Oxford Nanopore, raw reads).", "nano-hq": "Flye's nano-hq option (Oxford Nanopore, high-quality reads); the default in config.sh.",
                                   "pacbio-raw": "Flye's pacbio-raw option (PacBio, raw reads).", "pacbio-hifi": "Flye's pacbio-hifi option (PacBio HiFi reads)."},
                       "when": "Only matters when a long-read tool is switched on.", "setting": "FLYE_READ_TYPE"},
    "trycycler_assembly_count": {"summary": "Independent Flye assemblies Trycycler reconciles per sample. Higher is more robust but multiplies stage-7 runtime for trycycler_mob_recon proportionally.", "when": "Only matters when trycycler_mob_recon is on.", "setting": "TRYCYCLER_ASSEMBLY_COUNT"},
    "user_tools": {"summary": "Also benchmark a tool you added (see `plasbench tools list`); repeat for several, or give 'all'.", "when": "Leave empty unless you added your own tools.", "setting": "USER_TOOLS"},
    "force_rerun_tools": {"summary": "Discard completed tool results and execute them again.", "when": "Leave off to keep finished tool results.", "setting": "FORCE_RERUN_TOOLS"},
    "install_missing_tools": {"summary": "Install any enabled tool that is missing before the run starts, each from its pinned release or commit in its own environment (needs the internet).", "when": "Leave off to have the run stop at its first check and name what is missing; the window asks before installing.", "setting": "INSTALL_MISSING_TOOLS"},
}
_RUN.update(_TOOL_ENTRIES)

_RECONSTRUCT = {
    "sample": {"summary": "New sample id (letters, digits, dot, dash, underscore only)."},
    "sra": {"summary": "SRA run accession for this sample's Illumina reads."},
    "tool": {"summary": "Run exactly this tool, skipping the benchmark recommendation lookup.",
             "choices": {t: label[0].upper() + label[1:] + "." for t, (_, label) in TOOLS.items() if t in (
                 "mob_recon", "platon", "plasmidspades", "gplas2_mob", "gplas2_external", "genomad", "plasme", "plasgraph2",
                 "rfplasmid", "plasmidhunter", "plasmer", "plascope", "plasmidec")},
             "when": "Leave empty to let the benchmark's recommendation choose the tool for your organism or Gram group."},
    "recommendation_model": {"summary": "Optional fitted recommendation-model JSON. Used only if model_ready is true.", "when": "Leave empty for the default file in the results folder."},
    "read_depth_x": {"summary": "This isolate's own read depth, if known, for live model prediction."},
    "recommendations": {"summary": "benchmark.recommendations.tsv to consult when no tool is given.", "when": "Leave empty for <results-dir>/benchmark.recommendations.tsv."},
    "organism": {"summary": "Scientific name, used to match an organism-specific recommendation."},
    "gram_group": {"summary": "Gram group, used if no organism-specific recommendation exists."},
    "analysis_track": {"summary": "The analysis track passed to the recommendation lookup and the tool run (default short_read).", "choices": dict(TRACKS)},
    "data_dir": {"summary": "Directory for downloaded reads and assembly.", "when": "Leave empty for the configured data folder."},
    "results_dir": {"summary": "Directory for predictions and the selection report.", "when": "Leave empty for the configured results folder."},
    "log_dir": {"summary": "Directory for tool logs.", "when": "Leave empty for the configured logs folder."},
}

_SCAN = {
    "folder": {"summary": "The folder to look through; sub-folders are searched. Nothing in it is changed."},
    "json": {"summary": "Print the full result as JSON (for scripts) instead of a table."},
    "max_depth": {"summary": "How many folder levels below FOLDER to look into.", "when": "Raise it only if your files are nested deeper than 6 levels."},
    "max_files": {"summary": "Stop after looking at this many files, so a huge folder cannot hang the scan."},
    "write_sheet": {"summary": "After the scan, place each complete isolate and write or append this sample sheet, using the same code as init-local.", "when": "Leave empty to only look."},
    "data_dir": {"summary": "Where each isolate gets its own folder when placing.", "when": "Leave empty for the configured data folder."},
    "link": {"summary": "How the input files are placed when writing the sheet.", "choices": {"copy": "Copy the files (uses disk space, original untouched).", "symlink": "Make symbolic links to the originals.", "hardlink": "Make hard links (no extra space, same disk only)."}},
    "yes": {"summary": "Also place isolates that only need review (for example lanes to be joined). Isolates with an error are never placed."},
}

_INTAKE = {
    "action": {"summary": "What to do with your own isolates.",
               "choices": {"template": "Write a sample sheet (or truth table) to fill in, with the rules as comments.",
                           "scan": "Look through the folder(s) you name and work out what is there; nothing is copied or changed.",
                           "stage": "Place what the scan found where the pipeline expects it and write the sample sheet.",
                           "check": "The quick test: open every file the way a run will and say pass / warn / fail."}},
    "intake_args": {"summary": "Arguments of that action, such as the folder to scan (try: plasbench intake scan --help).", "when": "Leave empty for template."},
}

_DEMO = {
    "open_report": dict(_RUN["open_report"], summary="Open the completed demo report without prompting."),
    "no_report_prompt": dict(_RUN["no_report_prompt"], summary="Do not offer to open the completed demo report. The window always sets this so the run never stops to ask a question."),
}

_UI_STATE = {"json": {"summary": "Print the evidence as JSON instead of a short report.", "when": "Only when you want to process it with a script; to ask for help, paste the plain report."}}

_RUNTIME = {
    "action": {"summary": "What to do: status shows the choice and Docker's state, use saves the choice, check tests Docker step by step, pull gets the published image, build makes the image on this computer from the Dockerfile.",
               "choices": {"status": "Show where the tools run and what Docker looks like.", "use": "Save conda or docker as the place the tools run (PLASBENCH_RUNTIME).",
                           "check": "Test Docker: the image, the version inside it, a file written in a mounted folder and read here, and the path mapping. PASS or FAIL per step.",
                           "pull": "Download the published image of this version.", "build": "Build the image from this folder's Dockerfile (long, needs the internet, asks first)."}},
    "choice": {"summary": "With use: conda (the plasbench environment on this computer) or docker (a container of the PlasBench image)."},
    "yes": {"summary": "Agree to the download or build without asking.", "when": "Only after reading what it will do; a build takes a long time and several GB."},
    "rebuild": {"summary": "With build: build the image again even if one for this version exists on this computer."},
    "json": {"summary": "Print status or check as JSON instead of text."},
}

ENVIRONMENT = {
    "environment": {"summary": "Where PlasBench's tools run. Conda: the plasbench environment on this computer. Docker: a container of the PlasBench image, started for each run, with your study, data and database folders mounted at the same paths. The window itself always stays on this computer."},
    "conda": {"summary": "Tools run from the plasbench conda environment on this computer: fastest file access, no image to download, each tool installed with conda."},
    "docker": {"summary": "Tools run inside a container of the PlasBench image: every tool at the pinned version without installing conda; needs Docker, an image download (size not measured) and slower file access on /mnt drives."},
    "use_docker": {"summary": "Switch runs to Docker. Conda stays installed and you can switch back at any time; runs already going keep the runtime they started with."},
    "use_conda": {"summary": "Switch runs back to the conda environment on this computer."},
    "pull_image": {"summary": "Download the published image of this PlasBench version, or update it. Needs the internet."},
    "build_image": {"summary": "Build the image on this computer from the Dockerfile in the PlasBench folder, used when the image cannot be pulled. Slow (not measured; from half an hour to hours), several GB, needs the internet; asks first."},
    "test_docker": {"summary": "A small real test of Docker: the image runs plasbench --version, a container writes a file in a mounted folder and this computer reads it, and a path survives the round trip. PASS or FAIL per step with the exact error."},
    "install_docker": {"summary": "Docker is not ready: open the Tools page to install it (needs your OK)."},
    "restart_window": {"summary": "You are in the docker group now, but this window started before that, so it cannot use Docker yet. Restarts the window so the group applies; runs keep going."},
    "start_docker": {"summary": "Starts Docker Desktop (it is installed but not running) after asking, then checks the engine with visible progress. PlasBench only runs the program: it never accepts the Docker licence and never changes Docker Desktop settings."},
    "open_integration": {"summary": "Opens Docker Desktop at Settings > Resources > WSL integration, where you switch on this Linux distro. PlasBench does not change Docker Desktop settings itself; it checks every 5 seconds afterwards."},
    "run_in": {"summary": "Where this study's tools run: Conda or Docker. The default is the setting above; the choice is recorded in the study and in the run manifest."},
    "make_ready": {"summary": "Install every enabled tool and its database into the persistent storage of Docker mode (the image is never changed). Asks first and says what will be downloaded."},
    "extras": {"summary": "Tools and databases added in Docker mode live in this folder on your computer and are mounted into every container, so they stay between runs."},
}

ARGS = {"ui-state": _UI_STATE, "run": _RUN, "report": dict(_RUN), "demo": _DEMO, "reconstruct": _RECONSTRUCT, "intake": _INTAKE, "scan-isolates": _SCAN, "runtime": _RUNTIME}
_RUNTIME_ARG = {"summary": "Where this run's tools run: conda (the plasbench environment on this computer) or docker (a container of the PlasBench image, started for this run with your folders mounted). Empty uses the setting from Set up this computer. The choice is recorded in the study and the run manifest.",
                "choices": {"conda": "Tools from the plasbench conda environment on this computer.", "docker": "Tools from a container of the PlasBench image; needs Docker (Set up this computer, Environment)."},
                "when": "Leave empty unless this study should differ from the setting."}
ARGS["run"]["runtime"] = _RUNTIME_ARG
ARGS["report"]["runtime"] = _RUNTIME_ARG

# Wizard controls that are not command-line options. Keys are the control names used by the page.
WIZARD = {
    "git_page": {"summary": "Git without the command line, for your runs: one repository in the working directory, holding every study's record, sample sheets, settings, result tables, reports, figures and logs, with one history and one remote. The PlasBench program itself is not tracked here, because updates replace it. A managed .gitignore keeps raw sequence data (reads, assemblies, FASTA, alignments), tmp folders and credentials out. Every commit is checked for data, secrets and files too large for GitHub before it is made, and nothing is ever force-pushed."},
    "cohort": {"summary": "The bundled cohort to benchmark: its sample sheet in cohorts/. Locked cohorts are verified against their recorded accessions.", "flag": "--cohort",
               "when": "Only sample sheets of the benchmark kind are offered (the accession ledger is not one)."},
    "sample_sheet": {"summary": "A sample sheet you prepared, or one built on the Your own isolates page: columns sample_id, assembly_accession, sra_run.", "flag": "--samples", "setting": "SAMPLE_SHEET"},
    "local_inputs": ARGS["run"]["local_inputs"] | {"flag": "--local-inputs"},
    "stages": dict(_RUN["stages"], flag="positional stage numbers"),
    "workflow_view": {"summary": "The chain of steps a run goes through, in order, with the tools and optional steps you can switch in each. Workflow shows the chain; List shows the plain list. Both change the same settings, so they always agree.",
                      "when": "Use Workflow to see what each extra adds before you switch it on."},
    "workflow_estimate": {"summary": "What the items that are on add, per isolate or per 10 isolates. Time and disk add up; memory is the largest single tool. Every figure is an estimate and says where it comes from: measured on real isolates in this repository, documented by the tool or the README, or not measured. A tool with no figure is named, never counted as zero, so a total that includes one is a lower bound.",
                          "choices": {"measured": "Taken from a real run in results_real_cohort1 (10 isolates).", "documented": "A stated requirement or size (README, config.sh), not re-measured.", "not measured": "No figure exists yet; the total leaves it out and says so."},
                          "when": "Treat the total as a guide to plan time and disk, not a promise."},
    "workflow_colours": {"summary": "On is green with a tick. Off is plum with a cross and a dashed outline. The word is always written too, so colour is never the only cue. An item at its default shows its default state in that state's colour: a default-off tool shows Off until you switch it on. An item you changed from its default also carries a 'changed' tag. Green help marks, amber warnings and red errors keep their own meaning.",
                         "when": "Look for the 'changed' tag to see what you altered."},
    "tool_state": {"summary": "Per tool: default, on or off for this run only.",
                   "choices": {"default": "Use the RUN_<TOOL> setting saved for this computer (Tools page).", "on": "Run it this time.", "off": "Skip it this time."},
                   "when": "Leave on default unless this run should differ from your saved choice."},
    "study": {"summary": "Name of the study folder in the workspace where everything this benchmark produces goes (results, report, logs and study.json).", "flag": "--study",
              "when": "Leave empty: the study is named after the isolates."},
    "data_location": {"summary": "Where this run keeps downloaded reads and assemblies.", "flag": "--keep-data-in-study / --data-dir", "setting": "DATA_DIR", "default": "shared folder",
                      "choices": {"Shared folder": "The default folder in config.sh (DATA_DIR); reused by every study so nothing is downloaded twice, and kept if a study is deleted.",
                                  "Inside this study folder": "<study>/data: git-ignored and deleted together with the study (--keep-data-in-study).",
                                  "Another folder": "Any folder on this computer or a connected drive (--data-dir PATH); the study remembers it."},
                      "when": "Keep the shared folder unless you want a study's data kept with it, or on another drive."},
    "study_location": {"summary": "Where the study folder (results, logs, record) is created.", "flag": "--study-location", "default": "the workspace",
                       "choices": {"Workspace": "The workspace folder shown (PLASBENCH_WORKSPACE or the PlasBench studies folder).",
                                   "Another folder": "PARENT/NAME in a folder you choose, on this computer or a connected drive; PlasBench remembers where it is."},
                       "when": "A drive seen from Ubuntu (/mnt/c) is slower for many small files and for git; cloud-sync folders can lock files mid-run."},
    "open_report_run": {"summary": "Open the finished report in your browser when the run ends.", "flag": "--open-report",
                        "when": "The window always also passes --no-report-prompt, so the run never stops to ask a question."},
    "no_report_prompt": {"summary": "Always on in this window: the run never stops to ask whether to open the report.", "flag": "--no-report-prompt"},
    "read_source": {"default": "auto", "summary": "Where stage 1 gets short reads.", "setting": "READ_SOURCE",
                    "choices": {"auto": "SRA Toolkit first, then ENA if prefetch fails.", "sra": "SRA Toolkit only.", "ena": "ENA only (python/fetch_ena_reads.py, MD5-verified)."},
                    "when": "Leave on auto unless the SRA Toolkit keeps failing (use ena) or you want no ENA fallback (use sra)."},
    "max_run_download_gb": {"summary": "The largest read download allowed for one isolate, in GB.", "setting": "MAX_RUN_DOWNLOAD_GB", "when": "Leave empty for no limit."},
    "warn_run_download_gb": {"default": "5", "summary": "Warn when one isolate's read download is above this many GB.", "setting": "WARN_RUN_DOWNLOAD_GB", "when": "Leave empty for the default (5)."},
    "prefetch_fail_limit": {"default": "2", "summary": "Stop using the SRA Toolkit after this many failures.", "setting": "PREFETCH_FAIL_LIMIT", "when": "Leave empty for the default (2)."},
    "tool_timeout_hours": {"summary": "Wall-time budget per tool per isolate, in hours (sent as TOOL_TIMEOUT_SECONDS = hours x 3600). A tool that exceeds it fails with exit 124 (resource failure).",
                           "setting": "TOOL_TIMEOUT_SECONDS", "when": "Leave empty for no limit, the default: a limit scores a slow tool zero. Set one only to stop a truly stuck run, and make it generous."},
    "allow_all_tools_failed": {"summary": "Stage 4 normally exits with code 4 when every tool run failed (nothing to score). Switched on, the run continues with a warning.",
                               "setting": "ALLOW_ALL_TOOLS_FAILED", "when": "Leave off unless you want the run to go on after every tool failed."},
    "skip_disk_check": {"default": "off", "summary": "PlasBench estimates the disk space the isolates still to do need. It stops (exit 6) only when the first isolates cannot fit at once; a whole cohort that will not fit is a warning, and a guard before each isolate stops the run cleanly when space runs out. Switched on, the disk figures and the guard are skipped.",
                        "setting": "PLASBENCH_SKIP_DISK_CHECK", "when": "Leave off. Use it only when the estimate is wrong for your data and you know the space is there."},
    "cap_threads_to_cpus": {"default": "on", "summary": "Lower THREADS to the CPUs this process can really use (affinity, container quota, WSL processors=) and print the decision.",
                            "setting": "CAP_THREADS_TO_CPUS", "when": "Leave on. Off keeps exactly the number you set, even above your CPUs."},
    "assembler_auto_retry": {"default": "on", "summary": "When SPAdes fails for lack of memory (or from a stale output folder of that isolate), retry that isolate once with fewer threads and a budget that fits the free memory. Never more than one retry.",
                             "setting": "ASSEMBLER_AUTO_RETRY", "when": "Leave on. Off never retries; the failure is still diagnosed."},
    "console_log": {"default": "on", "summary": "Keep a console log of the run in the study folder (logs/run_*.log, and logs/run.latest.log for the newest): everything the run prints, kept after the window is closed.",
                    "setting": "RUN_CONSOLE_LOG", "when": "Leave on. Unchecked, the window sends RUN_CONSOLE_LOG=0 and no console log file is written."},
    "log_retention_runs": {"default": "20", "summary": "How many console logs of earlier runs are kept in the study's logs folder; older ones are removed.",
                           "setting": "LOG_RETENTION_RUNS", "when": "Leave empty for the default (20)."},
    "network_retries": {"default": "3", "summary": "Stage 1 retries each fetch this many times before recording the sample as failed.", "setting": "NETWORK_RETRIES", "when": "Leave empty for the default (3)."},
    "ena_download_connections": {"default": "4", "summary": "A large ENA read file is split into this many byte ranges fetched in parallel (aria2c is used when installed).",
                                 "setting": "ENA_DOWNLOAD_CONNECTIONS", "when": "Leave empty for the default (4). Only affects ENA downloads."},
}

# The Version control page's GitHub controls and the Online / Offline indicator (shown as tooltips by the page).
GITHUB = {
    "signin": {"summary": "Sign in to GitHub in a pop-up window: PlasBench shows a one-time code, you approve it on GitHub, and git push and pull then use the sign-in. The page never sees a token.", "when": "Needs the GitHub CLI (gh); without it, use a personal access token."},
    "token": {"summary": "Sign in with a personal access token instead of the pop-up: the token is sent once, over standard input, to the GitHub CLI and is never stored or shown.", "when": "Give the token the repo scope (and workflow if you push workflow files)."},
    "signout": {"summary": "Sign out of GitHub on this computer (gh auth logout). Nothing on GitHub changes.", "when": "Use Switch account to sign in as someone else."},
    "create_repo": {"summary": "Create the repository on GitHub (your account or an organisation, public or private), add it as origin and push the first branch.", "when": "Keep it private unless you are sure: run folders can hold sample data."},
    "clone": {"summary": "List or search your GitHub repositories and clone one into a folder."},
    "branches": {"summary": "Switch, push (setting the upstream) and delete branches. Delete only removes a fully merged local branch; deleting on GitHub removes the remote branch. Nothing is force-pushed."},
    "new_pr": {"summary": "Ask GitHub to merge one branch into another: title, description, base, head, draft, reviewers, labels. The branch is pushed first if needed."},
    "prs": {"summary": "Open, closed and merged pull requests: view (checks, reviews, mergeability, changed files, comments), check out, mark ready, close, reopen and merge."},
    "merge": {"summary": "Merge a pull request. Choose merge, squash or rebase, whether to delete the branch, or to wait for checks and merge automatically (only if the repository allows it).",
              "choices": {"merge": "A merge commit keeps every commit.", "squash": "One commit for the whole pull request.", "rebase": "Replays the commits on top of the base branch."},
              "when": "With failing checks, conflicts or a requested change PlasBench names the risk and asks you to confirm."},
    "checks": {"summary": "Checks (CI) of a pull request or branch, with the failing names and addresses; re-run only the failed ones."},
    "issues": {"summary": "List, create, comment on and close issues."},
    "releases": {"summary": "List releases, create a tag (and push it), create a release from a tag with notes."},
    "net_indicator": {"summary": "Whether the internet and each service PlasBench needs are reachable. Controls that need an unreachable service are switched off with the reason; local work is never blocked. Click for details and to check again.",
                      "choices": {"Online": "Everything checked is reachable.", "Limited": "Some services are unreachable.", "DNS problem": "Names cannot be looked up: the connection may be up but names fail.", "Offline": "No connection.", "Offline (forced)": "PLASBENCH_OFFLINE=1 is set."}},
}

# Settings page: per setting, what the section comment in config.sh does not already say.
SETTINGS = {
    "READ_SOURCE": WIZARD["read_source"],
    "UPDATE_CHECK": {"choices": {"auto": "Look for a newer release when the window starts, then at most once a day (one request to GitHub's public release list, nothing about you is sent).",
                                 "off": "Never look by itself; only the Check for updates button asks GitHub."}},
    "ANALYSIS_TRACK_FILTER": {"choices": TRACKS, "when": "Leave empty to score every enabled tool under its own track."},
    "ASSEMBLER": {"choices": ARGS["run"]["assembler"]["choices"]},
    "FLYE_READ_TYPE": {"choices": ARGS["run"]["flye_read_type"]["choices"]},
    "DECISION_PROFILE": {"choices": ARGS["run"]["decision_profile"]["choices"]},
    "TRUTH_LABEL_SCHEME": {"choices": {"ncbi": "Scheme 3, NCBI sequence-report labels (truth.tsv): the pre-registered primary.",
                                       "nonchromosomal": "Scheme 1: every replicon but the main chromosome is a plasmid (sensitivity scheme).",
                                       "evidence": "Scheme 2: evidence-confirmed labels with AMBIGUOUS replicons excluded (truth.scored.tsv; sensitivity scheme)."}},
    "TOOL_TIMEOUT_SECONDS": {"when": "Blank = no limit. Set a limit only to stop a truly stuck run, and make it generous (172800 = two days); a run that exceeds it fails with exit 124."},
    "MAX_RUN_DOWNLOAD_GB": WIZARD["max_run_download_gb"], "WARN_RUN_DOWNLOAD_GB": WIZARD["warn_run_download_gb"],
    "PREFETCH_FAIL_LIMIT": WIZARD["prefetch_fail_limit"], "ALLOW_ALL_TOOLS_FAILED": WIZARD["allow_all_tools_failed"],
    "ENA_DOWNLOAD_CONNECTIONS": WIZARD["ena_download_connections"], "NETWORK_RETRIES": WIZARD["network_retries"],
    "RUN_CONSOLE_LOG": WIZARD["console_log"], "LOG_RETENTION_RUNS": WIZARD["log_retention_runs"],
}
# MultiQC versus the built-in QC panel: ONE text (python/multiqc_note.py), shown in the report's QC panel and PDF, here as the help of the MULTIQC_REPORT setting and
# as REPORT_NOTES["qc"] for the window's Report-view / QC area.
def _multiqc_text():
    import sys
    from pathlib import Path
    folder = str(Path(__file__).resolve().parent.parent / "python")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        import multiqc_note
        return multiqc_note.TITLE, multiqc_note.text()
    except ImportError:          # a trimmed install without python/: say so rather than show nothing
        return "MultiQC or the built-in panel?", "The report's QC panel is PlasBench's own; MultiQC is an optional companion (plasbench install-tools multiqc)."


_MQ_TITLE, _MQ_TEXT = _multiqc_text()
SETTINGS["MULTIQC_REPORT"] = {"summary": "Whether to also run the optional MultiQC over the fastp (and QUAST) outputs and link its report from the QC panel. " + _MQ_TEXT,
                              "choices": {"auto": "Run MultiQC only when it is installed (plasbench install-tools multiqc). The default.",
                                          "on": "Always try, and warn when MultiQC is missing. A failure never stops the run.",
                                          "off": "Never run MultiQC."},
                              "when": "Leave on auto. MultiQC adds plots (per-base quality, adapter content, duplication); it does not change any decision or score.",
                              "setting": "MULTIQC_REPORT"}
SETTINGS["MULTIQC_TIMEOUT_SECONDS"] = {"summary": "The limit, in seconds, for the optional MultiQC command (default 600). A timeout is a warning, not a failure."}
REPORT_NOTES = {"qc": {"title": _MQ_TITLE, "text": _MQ_TEXT, "setting": "MULTIQC_REPORT"}}
# Settings shown together in the "Reliability and downloads" group (only those config.sh defines).
RELIABILITY_KEYS = ["READ_SOURCE", "MAX_RUN_DOWNLOAD_GB", "WARN_RUN_DOWNLOAD_GB", "PREFETCH_FAIL_LIMIT", "NETWORK_RETRIES", "NETWORK_RETRY_DELAY_SECONDS",
                    "ENA_DOWNLOAD_CONNECTIONS", "PLASBENCH_OFFLINE", "PLASBENCH_ONLINE_TIMEOUT", "PRESERVE_DOWNLOADS", "TOOL_RETRIES", "TOOL_TIMEOUT_SECONDS", "ALLOW_ALL_TOOLS_FAILED", "PLASBENCH_DISK_RESERVE_GB", "PLASBENCH_VDISK_MIN_GB", "RUN_CONSOLE_LOG", "LOG_RETENTION_RUNS"]


def _default_text(default, kind=None):
    if default in (None, ""):
        return "none"
    return str(default)


def tooltip(entry, arg=None, flag="", default=None, setting=""):
    """What the window shows for one field: summary, one line per choice, default, flag, setting name, when."""
    entry = entry or {}
    summary = entry.get("summary") or (arg or {}).get("help") or ""
    flag = flag or entry.get("flag") or ""
    if arg and not flag:
        flag = next((f for f in arg.get("flags", []) if f.startswith("--")), (arg.get("flags") or [""])[0])
    default = entry["default"] if "default" in entry else default if default is not None else (arg or {}).get("default")
    out = {"summary": summary, "choices": [[c, m] for c, m in (entry.get("choices") or {}).items()],
           "default": _default_text(default), "flag": flag, "setting": entry.get("setting") or setting, "when": entry.get("when", "")}
    if not out["summary"]:
        out["summary"] = f"{(arg or {}).get('dest', 'This field')}: no description is recorded for it."
    return out


def page_tip(entry):
    """What a page-level (?) shows: a title line, the summary, a short bullet list and a closing line. No default/flag footer: these explain a page, not an option."""
    return {"title": entry.get("title", ""), "summary": entry.get("summary", ""), "bullets": list(entry.get("bullets", [])), "when": entry.get("when", ""), "plain": True}


def setting_tooltip(row, carried=""):
    """Tooltip for one Settings-page row (a dict from Project.settings())."""
    entry = SETTINGS.get(row["key"], {})
    comment = row.get("comment") or ""
    summary = entry.get("summary") or comment
    if not summary and carried:
        summary = f"Listed with the settings above it in config.sh: {carried}"
    if not summary:
        summary = f"The {row['key']} setting."
    out = tooltip(dict(entry, summary=summary), default=row.get("default"), setting=row["key"])
    out["flag"] = ""
    return out


# ---- Add your own tool: what the page's new controls mean (the manifest keys are documented in docs/ADDING_TOOLS.md) ----------------------------------
# The sentences are python/user_tools.py's own (TASK_HELP, FORMAT_HELP, SOURCE_HELP: the window sends those to the page); test_ui_help checks these copies are identical,
# so the tooltips and the page cannot drift apart.
TASK_HELP = {
    "binning_reconstruction": "Groups assembly contigs into plasmids (bins); scored with bin-level metrics such as completeness, purity and CPRR.",
    "sequence_reassembly": "Writes predicted plasmid sequence (a FASTA); scored on how well the sequence matches the true plasmids.",
    "classification": "Labels each contig plasmid or chromosome, optionally with a probability; scored per base with F1 and PR-AUC.",
}
FORMAT_HELP = {
    "contig_bins": "A table with one row per contig and the bin (plasmid) it belongs to; serves binning, and classification (a contig in any bin is plasmid).",
    "contig_labels": "A table with one row per contig and a plasmid/chromosome label and/or a probability; serves classification, and binning only as one flagged bin per plasmid contig.",
    "plasmid_fasta": "One FASTA of predicted plasmid sequence, each record its own plasmid; serves sequence reassembly only.",
    "fasta_dir": "A folder with one FASTA file per predicted plasmid; serves sequence reassembly only.",
    "adapter": "Your own script converts the tool's output into PlasBench's native files for the tasks named in adapter_tasks.",
    "auto": "PlasBench looks at the files listed in candidates and recognises each by its content; an ambiguous or unrecognisable output is an error, never a guess.",
}
SOURCE_HELP = {
    "conda": "Installs the named conda packages into the tool's own environment.",
    "pip": "Installs the named pip packages into the tool's own environment.",
    "script": "Runs an install script that ships beside the manifest.",
    "url": "Downloads the tool from an https URL (archive, git repository or single file) into the manifest's src/ folder, checking its sha256 when you give one.",
    "local": "Uses a tool already on this computer: a copy (recorded with a checksum, reproducible) or a link (used in place, can change under the benchmark).",
    "none": "Nothing to install: the command is already on PATH.",
}

USERTOOL = {
    "task": {"summary": "What the tool does. A tool may do more than one task; it is then scored on each, using the same output where PlasBench can derive one result from another. The first task chosen is the primary one.",
             "choices": dict(TASK_HELP), "setting": "[tool] task", "default": "none",
             "when": "Beside each task the page shows, from the Check panel, whether it is native (the output already is that result), derived from another output, or not possible (and why)."},
    "task_primary": {"summary": "The first task in the list is the primary task: it names the tool's row in the tables and is the one the tool is ranked on first. Move a task left or right to change it.",
                     "setting": "[tool] task (first item)"},
    "source": {"summary": "Where the tool comes from. Nothing is downloaded or run until you press Save & install.",
               "choices": {"Already installed": SOURCE_HELP["none"], "Package manager": "conda or pip: " + SOURCE_HELP["conda"],
                           "Download from a URL": SOURCE_HELP["url"], "A file or folder on this computer": SOURCE_HELP["local"], "My own install script": SOURCE_HELP["script"]},
               "setting": "[install] method", "default": "conda",
               "when": "PlasBench will run code you download or point to. Only use sources you trust."},
    "src_url": {"summary": "The https address to download the tool from. Only https is accepted; http and other schemes are refused.", "setting": "[install] url", "when": "Required for a download."},
    "src_sha256": {"summary": "The expected SHA-256 checksum of the download (64 hexadecimal characters). When given, PlasBench refuses a download that does not match, so the tool cannot change under you.",
                   "setting": "[install] sha256", "default": "not pinned", "when": "Recommended. Without it PlasBench cannot tell if the file changed since you checked it."},
    "src_kind": {"summary": "What the URL points to.", "setting": "[install] kind", "default": "auto",
                 "choices": {"auto": "Decide from the address and the file name.", "archive": "A .zip, .tar.gz or similar archive that is unpacked.", "git": "A git repository that is cloned (see ref).",
                             "file": "A single file, kept as it is."}},
    "src_ref": {"summary": "For a git repository: the tag, branch or commit to check out. A tag or commit keeps the result reproducible.", "setting": "[install] ref", "when": "Only for kind = git."},
    "src_build": {"summary": "An optional command run after the download or copy to build the tool (for example make). It runs in the tool's folder.", "setting": "[install] build_command", "when": "Leave empty when the tool needs no build."},
    "src_path": {"summary": "A file or folder already on this computer. Use {src} in the run command to refer to it. Choose... opens the folder browser, which lists every drive.", "setting": "[install] path"},
    "src_mode": {"summary": "How PlasBench uses the local path.", "setting": "[install] mode", "default": "link",
                 "choices": {"link": "Follow the file where it is. It always uses the current contents, but the result changes if the file changes.",
                             "copy": "Copy it into the tool's folder and record a checksum. Reproducible: the copy does not change when the original does."}},
    "src_script": {"summary": "Your own install script, saved beside the manifest and run as script <environment name>. Upload it here if it is small.", "setting": "[install] script"},
    "upload": {"summary": "Upload a small file (a script or an adapter, up to 5 MB) from this computer. It is stored in the tool's own folder, under the tool's name, and the manifest then refers to it. Large tool programs are located on this computer or downloaded, not uploaded.",
               "when": "Give the tool a name first: the name is its folder."},
    "outputs": {"summary": "What the tool writes. A tool can write more than one kind of output: add one row per output. PlasBench reads each, and uses the one that fits each task you chose (for example contig bins can be turned into plasmid/chromosome labels).",
                "setting": "[output] format and [output.<format>]", "when": "Detect automatically lists file patterns instead and PlasBench works out the shape."},
    "out_format": {"summary": "The shape of this output.", "choices": dict(FORMAT_HELP), "setting": "[output] format"},
    "out_path": {"summary": "Where the tool writes this output, relative to {outdir}.", "setting": "[output] path"},
    "out_candidates": {"summary": "File name patterns (globs) to try under {outdir}, separated by commas, for example bins.tsv, *.labels.tsv. PlasBench reads whichever one exists and recognises its shape.", "setting": "[output] candidates",
                       "when": "If two patterns match files of different shapes PlasBench says it is ambiguous instead of guessing."},
    "out_delimiter": {"summary": "What separates the columns of the table.", "choices": {"tab": "Tab-separated.", "comma": "Comma-separated.", "semicolon": "Semicolon-separated.", "whitespace": "Any run of spaces."}, "setting": "delimiter", "default": "tab"},
    "out_header": {"summary": "Whether the first row of the table holds column names.", "choices": {"yes": "Columns are given by name or number.", "no": "Columns must be given by number, starting at 1."}, "setting": "header", "default": "yes"},
    "out_contig_column": {"summary": "The column holding the contig name: its header name, or its number starting at 1.", "setting": "contig_column"},
    "out_bin_column": {"summary": "The column holding the bin (plasmid) each contig belongs to.", "setting": "bin_column"},
    "out_label_column": {"summary": "The column holding the plasmid or chromosome label.", "setting": "label_column"},
    "out_plasmid_values": {"summary": "The label values that mean plasmid, separated by commas, for example plasmid, Plasmid, 1. Any other value means chromosome.", "setting": "plasmid_values"},
    "out_score_column": {"summary": "A column of probabilities between 0 and 1. It adds a precision-recall curve to the results.", "setting": "score_column"},
    "out_threshold": {"summary": "Without a label column, a contig whose score is at least this value is a plasmid.", "setting": "threshold", "default": "0.5"},
    "out_fasta_glob": {"summary": "Which files in the folder are plasmid FASTA files, for example plasmid_*.fasta.", "setting": "fasta_glob", "default": "*.fa, *.fasta, *.fna"},
    "out_adapter": {"summary": "A script beside the manifest that is run as adapter <output> <contigs> <predictions fasta>.", "setting": "adapter"},
    "out_contig_id_from": {"summary": "How to turn the tool's contig ids into PlasBench's.", "choices": {"": "Use them as written.", "first_token": "Keep the first word of each id."}, "setting": "contig_id_from"},
    "out_contig_id_strip": {"summary": "A regular expression removed from each contig id, for example _length_.*$.", "setting": "contig_id_strip_regex"},
}


# The folder window (plasbench/native_picker.py) and the built-in browser; the page shows these next to every Browse button.
NATIVE_PICKER = {
    "browse": {"summary": "Opens this computer's own folder window (Explorer on Windows) with every drive, USB stick and network location, and puts the folder you choose in the box. "
                          "If the window is hidden behind this one, use Bring it to front."},
    "inline": {"summary": "Browse inside this window with PlasBench's built-in browser. It is used automatically when this computer has no folder window to open."},
    "open_explorer": {"summary": "Shows the folder in the box in Explorer (the file manager of this computer). It only opens a view: use Browse to choose a folder."},
    "drive_capacity": {"summary": "Size and free space come from Windows itself (as Explorer shows them). GB here is 2^30 bytes, the unit Explorer calls GB."},
    "drive_unmounted": {"summary": "This drive is plugged in but Ubuntu has not mounted it yet. Copy the command and run it in the Terminal tab; PlasBench never runs it for you."},
    "paste_path": {"summary": "Paste a path from Explorer: Copy as path (with quotes), the address bar, a wsl.localhost network path or a file:/// link all work."},
    "why": {"summary": "Why Browse is using the built-in browser instead of the computer's own folder window: the exact reason PlasBench found, and what it tried."},
    "diagnostics": {"summary": "Copies what PlasBench found out about the folder window (the computer, what it looked for, what happened last) so you can paste it into a bug report. `plasbench picker-check` gives the full step-by-step version."},
    "test": {"summary": "Opens a test folder window that closes itself after two seconds and reports every step (the computer, WSL interop, PowerShell, compiling the window, opening it, bringing it to the front). Nothing is changed."},
    "docker_add": {"summary": "This window runs inside Docker and sees only the folders mounted into the container. Type a folder of your computer and PlasBench makes the docker run command that mounts it. The command is only shown and copied, never run."},
    "docker_switch": {"summary": "Shows the command that runs the PlasBench pipeline in Docker with your folders mounted, when Docker is installed and running. The tools run inside the image and results are written to your folders. The command is only shown and copied, never run."},
    "in_docker": {"summary": "Inside Docker there is no desktop, so no folder window can open. The built-in browser starts at the folders mounted into the container."},
    "docker_state": {"summary": "The state of Docker on this computer, from a background check that never changes anything: not installed, installed on Windows but not started, Docker Desktop starting (its engine does not answer yet, often the licence window is waiting for you), running but WSL integration off for this Linux distro, daemon stopped, permission needed, or ready. On Windows and WSL it looks at Docker Desktop on the Windows side (its files, whether it is running, docker.exe info and its settings file) as well as at `docker` itself."},
    "docker_install": {"summary": "Starts the Docker setup. Where an installer can run without PlasBench holding admin rights (winget on Windows, Homebrew on macOS) it asks you first and lists exactly what will run; Windows or macOS then show their own approval prompt. Elsewhere it shows the exact steps and a script you run yourself with your own sudo. PlasBench never runs sudo and cannot accept the Docker Desktop licence for you."},
    "docker_recheck": {"summary": "Looks at Docker again right now: the same checks as the state label. Use it after you finished the steps PlasBench handed to you (starting Docker Desktop, turning on WSL integration, adding yourself to the docker group)."},
    "docker_guide": {"summary": "Opens Docker's own installation guide in your browser."},
    "docker_install_first": {"summary": "Run in Docker needs Docker to be installed and running. This opens the Docker setup: its state, what to do next and the install button."},
    "docker_restart": {"summary": "You are in the docker group now, but this window started before that and a running program keeps the groups it started with, so it still cannot use Docker. This starts PlasBench again so the group applies (through `sg docker` when that is available; otherwise it tells you to run newgrp docker and plasbench ui, or wsl --shutdown). Your runs keep going: they are detached from the window."},
    "docker_start": {"summary": "Starts Docker Desktop for you (Windows, WSL 2 and macOS) after asking: PlasBench only runs the program, then checks the engine every few seconds with visible progress. It never accepts the Docker licence, never changes Docker Desktop settings and never clicks in its window. If Docker Desktop shows the licence, you accept it there."},
    "docker_integration": {"summary": "Opens Docker Desktop at its WSL integration settings (Settings > Resources > WSL integration), where you switch on this Linux distro and press Apply & restart. PlasBench does not edit Docker Desktop settings itself. If the settings page does not open directly, Docker Desktop opens and you click that path."},
    "docker_integration_done": {"summary": "Press this after you switched WSL integration on: PlasBench checks every 5 seconds, for up to 3 minutes, by reading Docker Desktop settings and running docker inside this distro, and reports as soon as it works."},
    "docker_stages": {"summary": "The four things Docker needs, in order: Docker Desktop installed, running, its engine answering (the licence accepted), and, in WSL, integration turned on for this distro. A tick is done, a dot is the step to do now, a dash is waiting for an earlier step. Hover a step to see what PlasBench found."},
}


# ---- Front-facing page notes -------------------------------------------------------------------------------------------------------------------------
# Every page shows one short line; what the page or a control MEANS lives here and opens from the green (?) next to it (hover, keyboard focus, or a tap).
# Rule: text that explains what a control means or how it works is a tooltip (this dict); text that reports a state, a problem or a decision the person must
# make stays visible. Entries: title (bold first line), summary, bullets (a short list), when (a closing line). test_ui_cleanup keeps the pages inside a word budget.
PAGE = {
    "term_shell": {"title": "Which shells appear", "summary": "The list depends on where this window runs. A greyed entry says why it is off when you hover it.",
                   "bullets": ["Windows: each Ubuntu (WSL), Git Bash, PowerShell, Command Prompt (cmd).", "Ubuntu (WSL): your Ubuntu shell, plus Windows PowerShell, Command Prompt (cmd) and Git Bash (Windows) through WSL interop.", "Linux and Mac: your login shell, and PowerShell if pwsh is installed.", "plasbench works in every shell and runs this PlasBench folder."],
                   "when": "Windows shells started from Ubuntu cannot see the Ubuntu tools; Command Prompt cannot start in an Ubuntu folder, so it uses a temporary drive letter."},
    "p_setup": {"title": "Set up this computer", "summary": "What PlasBench needs, what is already here, and a one-click fix for anything missing.",
                "bullets": ["Each fix runs the same plasbench command you would type.", "Its output appears in the console below."]},
    "pc_help": {"title": "This computer", "summary": "The desktop icon starts PlasBench (or brings this window back). Quit, top right, stops it.", "when": "Every page also works from the command line, and from the Terminal tab of the console below."},
    "ncbi": {"title": "NCBI access", "summary": "Cohort downloads use NCBI.", "bullets": ["An email is courtesy.", "An API key raises the request allowance from 3 to 10 per second.", "Both are saved in config/local.env on this computer only."]},
    "profile": {"title": "Tool profiles", "summary": "Profiles group related tools.", "bullets": ["core is needed for everything.", "The rest add assemblers, binning-reconstruction tools and optional analyses."]},
    "docker_card": {"title": "Docker (optional)", "summary": "Docker is optional. It runs PlasBench in a container (scripts/docker_run.sh) and is the runtime tools such as mobilome-map and plsmd need when they run in a container.",
                    "bullets": ["PlasBench never runs sudo.", "PlasBench never accepts the Docker Desktop licence for you."]},
    "m_conda": {"title": "Install conda", "summary": "Installs Miniforge. Only if no conda, mamba or micromamba is present."},
    "install_toast": {"title": "Installation in progress", "summary": "Shows while any install, pull, build or update is running, on every page, even after a reload.",
                      "bullets": ["View log opens the live log.", "Hide collapses it to a chip in the top bar; the chip brings it back.", "Cancel stops that install; what is already installed is kept.",
                                  "A failure or a step waiting for you stays until you dismiss it; Done goes away by itself."]},
    "install_chip": {"title": "Installing", "summary": "Installations are still running. Click the chip to show the details again."},
    "upd_card": {"title": "Updates", "summary": "Check GitHub for a newer release, download and install it, or install a release file you already downloaded. It runs plasbench upgrade, the same command as in a terminal.",
                 "bullets": ["Only GitHub's public release list is asked (nothing about you or this computer is sent). The setting UPDATE_CHECK=off stops the daily background check.",
                             "The download is verified against the release's .sha256 file before anything is replaced.",
                             "Studies, settings, databases and tools are kept. The previous version is saved so Roll back can return to it.",
                             "A running benchmark blocks the update unless you choose Update anyway: an update replaces the program files it uses.",
                             "Afterwards restart the window (a button appears) to use the new version."],
                 "when": "No internet? Download plasbench-<version>.tar.gz on another computer and use Install from a file."},
    "upd_file_help": {"title": "Install from a file", "summary": "For a release file you downloaded yourself, for example on another computer. Needs no internet.",
                      "bullets": ["The file must be named plasbench-<version>.tar.gz exactly as downloaded from the release page.", "Keep plasbench-<version>.tar.gz.sha256 beside it: the checksum is verified before anything is replaced.",
                                  "An older release than the installed one is a downgrade and asks you to confirm."]},
    "m_test": {"title": "Run the test suite", "summary": "Offline regression checks of this installation."},
    "p_tools": {"title": "Tools", "summary": "Every tool PlasBench can benchmark, built-in and your own.",
                "bullets": ["The switch, and the on / off beside it, set whether a tool runs by default (saved for this computer).", "on: it runs unless you turn it off for a run.", "off: it is skipped unless you turn it on.", "The New benchmark page can still change it for one run."]},
    "tool_tasks": {"title": "Three kinds of task, each ranked on its own", "summary": "Tools are never ranked against tools of another task or another input track.",
                   "bullets": ["Classification: the tool labels every contig plasmid or chromosome (ranked by base-level F1).", "Binning reconstruction: the tool groups contigs into separate plasmids (ranked by length-weighted binning F1).",
                               "Sequence reassembly: the tool produces the plasmid sequences themselves (ranked by CPRR, the share of true plasmids recovered correctly)."]},
    "p_addtool": {"title": "Add your own tool", "summary": "Describe a plasmid reconstruction or classification tool once.",
                  "bullets": ["PlasBench installs it into its own environment.", "It runs it on every sample (or reads outputs you already have) and converts its output.", "It scores, ranks and reports it beside the built-in tools.", "No code changes."]},
    "ut_text": {"title": "Manifest text", "summary": "You can also edit the text directly; the form follows."},
    "p_prereg": {"title": "Scoring decisions", "summary": "Before any result is looked at, PlasBench fixes how tools are scored and ranked. These are those rules, each in plain words.",
                 "bullets": ["They are confirmed and recorded so that nobody, including you, can quietly change a rule after seeing which tool wins.", "You can still change one: PlasBench asks why, records it, and warns that results from before and after the change cannot be compared."]},
    "p_settings": {"title": "Settings", "summary": "Every setting PlasBench reads (from config/config.sh), its default, and your value for this computer.",
                   "bullets": ["Changes are saved to config/local.env, which upgrades keep.", "Clear a value to return to the default."]},
    "folder_window": {"title": "Folder window", "summary": "Browse opens this computer's own folder window. If it does not, test it here: PlasBench opens a window, closes it again after two seconds and says which step fails."},
    "p_wizard": {"title": "New benchmark", "summary": "Choose the isolates, the tools and the resources, review the exact command, and start.", "bullets": ["Every option of plasbench run is available.", "Anything you leave alone keeps its default."]},
    "p_workspace": {"title": "Workspace and studies", "summary": "Every benchmark is a study with its own folder: its results, report, logs and a record of how it was run. The workspace is the folder that holds all studies.",
                    "when": "Downloads, tool environments and databases are shared between studies, so a new study never downloads the same reads again."},
    "ws_change": {"title": "Change the workspace", "summary": "Choose a folder with plenty of free space: a public cohort needs hundreds of GB.", "bullets": ["A local disk is fastest; an external drive works if it stays connected.", "Existing studies stay where they are."]},
    "st_new": {"title": "New study", "summary": "Optional: a run creates its study automatically, named after the cohort or sample sheet. Create one here to name it yourself, then choose it on New benchmark."},
    "st_name": {"title": "Study name", "summary": "Letters, digits, '.', '_' or '-'."},
    "st_loc": {"title": "Study location", "summary": "The study folder is created as location/name. Leave empty to use the workspace, or choose a folder on this computer or a connected drive."},
    "st_import": {"title": "Import a study", "summary": "Bring in a study bundle (a .zip made by Manage > Export) from another computer or an earlier time. It becomes a new study; nothing is overwritten."},
    "p_isolates": {"title": "Your own isolates", "summary": "Tell PlasBench which folder(s) hold your reads and reference genomes.",
                   "bullets": ["It finds each isolate and places the files where the run expects them.", "It tests that it can read and use them, before any run spends hours."], "when": "Not sure what you need? Read the guide: Help > INPUT_GUIDE."},
    "in_sheet": {"title": "A sheet to fill in (optional)", "summary": "You do not have to write a sheet: step 2 writes it for you from your folders. If you prefer to fill one in yourself, download a template.", "when": "Each has the rules written at the top, and a worked example."},
    "in_need": {"title": "What you need for each isolate", "summary": "Its paired Illumina reads (two files); for a scored benchmark also the complete genome of the same isolate (chromosome and each plasmid as separate sequences).", "when": "With reads only, PlasBench reconstructs the plasmids but cannot score them."},
    "in_find": {"title": "Find my files", "summary": "Add the folder(s) where your files are. Sub-folders are searched.", "when": "Nothing is changed until you press Place the selected isolates."},
    "in_test": {"title": "Quick test", "summary": "Opens each file the way a run will: are the reads real FASTQ and paired, is the reference a complete genome, do the labels match it, and do the reads actually come from that reference's isolate.", "when": "Takes seconds per isolate and changes nothing unless you press Fix."},
    "in_data": {"title": "Data folder", "summary": "Where each isolate's own folder lives. The default is PlasBench's data folder."},
    "in_scan": {"title": "Scan a folder", "summary": "Point at ONE folder, even a messy one with sub-folders and unrelated files. PlasBench looks for each isolate's paired reads and its complete reference, shows what it would use and why, and flags anything it is not sure of.",
                "bullets": ["Scanning never changes your folder.", "Nothing is added until you press Add selected isolates.",
                            "Reads: FASTQ pairs named _R1/_R2, _1/_2, .1/.2 or _R1_001/_R2_001 (.fastq or .fq, gzipped). Illumina lanes (_L001, _L002) of one isolate are listed and flagged: you confirm before they are joined.",
                            "Reference: a plain FASTA of the complete genome. Assembler output (contigs.fasta, scaffolds.fasta, assembly.fasta in SPAdes, Unicycler or Flye folders, NODE_ headers) is never taken as a reference.",
                            "Also used: sequence_report.jsonl and truth tables (truth.tsv) that sit with an isolate.",
                            "Ignored and counted: alignments (BAM), documents, spreadsheets, logs, hidden folders, .git, results and logs folders, long reads (not used here).",
                            "Limits: matching uses folder and file names; check the reference of every isolate marked 'check' before you rely on it."]},
    "p_cohorts": {"title": "Cohorts", "summary": "Study sets that ship with PlasBench, each a sample sheet of NCBI-linked isolates. Validate one, or benchmark it directly.", "when": "Building your own cohort (discover, curate, validate, lock) is under All commands > Cohorts and truth."},
    "coh_meta": {"title": "Where the details come from", "summary": "From the sheet and its verification lock: country, host, isolation source, collection date, how the reference was sequenced and assembled, and the Illumina run's size come from NCBI as recorded when the cohort was locked.", "when": "The download estimate uses the same factors as plasbench run's pre-download check."},
    "coh_published": {"title": "Comparison with published outcomes", "summary": "Stage 6 does this automatically (setting RUN_PUBLISHED_COMPARISON) and the report gets a 'Comparison with published outcomes' section.", "when": "It is a comparison for your judgement, not a ranking: assemblies, tool versions, databases and metric definitions differ from the paper's."},
    "p_runs": {"title": "Runs and reports", "summary": "Your benchmark runs: the ones going now, the ones that failed or were interrupted (resume them: finished work is kept), and the completed ones with their reports.", "when": "Below, every results folder found in this installation."},
    "rank_help": {"title": "How to read a rank", "summary": "A rank is a tool's position within one task and one input track (short-read, long-read or hybrid), ordered by that task's headline metric (F1 for classification, length-weighted binning F1 for binning, CPRR for reassembly).",
                  "bullets": ["Rank 1 is the best score, but a tied or overlapping confidence interval means two tools cannot be told apart.", "A tool is only ranked on the isolates it ran on.", "\"Leading\" names the rank-1 tool of each task; the full table is in the report and the Leaderboard download.", "\"Completed with warnings\" means the run finished normally but had failed tool runs."]},
    "p_jobs": {"title": "Jobs", "summary": "Every command started from this window, with its exact command line, how it ended, and its full log.",
               "bullets": ["Jobs keep running if you switch pages.", "Quit asks before stopping one that is still running.", "Runs you start in the Terminal appear under Runs and reports, marked 'started outside the window'."]},
    "p_commands": {"title": "All commands", "summary": "Every plasbench command and every option, generated from the command line itself, so nothing is missing or out of date.", "when": "Fill in what you need, check the command line, and run it."},
    "w_predictions": {"title": "Predictions folder", "summary": "<tool>/<community>.bins.tsv normalized outputs."},
    "w_db": {"title": "Use a different database copy", "summary": "Leave these empty: each run uses the database where PlasBench installed it. Fill one in only to use another copy."},
    "w_env": {"title": "Downloads and reliability", "summary": "These are environment settings for this run. Leave a box empty to keep the setting saved for this computer (Settings page, group Reliability and downloads)."},
    "w_reuse": {"title": "Reusing what you have", "summary": "Installed tools, tool databases and downloaded reads are shared by every benchmark on this computer.",
                "bullets": ["Reads and assemblies live in the shared data folder; databases where PlasBench installed them.", "You do not need to know where that is: a run finds them itself."]},
    "git_safe": {"title": "Safety", "summary": "Nothing is force-pushed. Deleting, closing and merging ask first, and say exactly what will happen."},
}
