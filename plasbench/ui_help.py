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

ARGS = {"run": _RUN, "report": dict(_RUN), "demo": _DEMO, "reconstruct": _RECONSTRUCT, "intake": _INTAKE}

# Wizard controls that are not command-line options. Keys are the control names used by the page.
WIZARD = {
    "cohort": {"summary": "The bundled cohort to benchmark: its sample sheet in cohorts/. Locked cohorts are verified against their recorded accessions.", "flag": "--cohort",
               "when": "Only sample sheets of the benchmark kind are offered (the accession ledger is not one)."},
    "sample_sheet": {"summary": "A sample sheet you prepared, or one built on the Your own isolates page: columns sample_id, assembly_accession, sra_run.", "flag": "--samples", "setting": "SAMPLE_SHEET"},
    "local_inputs": ARGS["run"]["local_inputs"] | {"flag": "--local-inputs"},
    "stages": dict(_RUN["stages"], flag="positional stage numbers"),
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
# Settings shown together in the "Reliability and downloads" group (only those config.sh defines).
RELIABILITY_KEYS = ["READ_SOURCE", "MAX_RUN_DOWNLOAD_GB", "WARN_RUN_DOWNLOAD_GB", "PREFETCH_FAIL_LIMIT", "NETWORK_RETRIES", "NETWORK_RETRY_DELAY_SECONDS",
                    "ENA_DOWNLOAD_CONNECTIONS", "PLASBENCH_OFFLINE", "PLASBENCH_ONLINE_TIMEOUT", "PRESERVE_DOWNLOADS", "TOOL_RETRIES", "TOOL_TIMEOUT_SECONDS", "ALLOW_ALL_TOOLS_FAILED", "RUN_CONSOLE_LOG", "LOG_RETENTION_RUNS"]


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
