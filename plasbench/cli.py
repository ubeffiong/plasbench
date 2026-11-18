"""Command-line entry point for the source checkout and container image."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import __version__


STAGE_HELP = """stage numbers: 0=setup, 1=download, 2=truth, 3=assemble,
4=reconstruct, 5=score, 6=aggregate and HTML report, 7=optional long-read reconstruction."""

DOC_TOPICS = {
    "overview": "What PlasBench Is",
    "what-it-does": "What It Does",
    "how-it-works": "How It Works",
    "when-to-use": "When To Use It",
    "limits": "Requirements and Limits",
    "example": "Simulated End-to-End Research Example",
    "install": "Install",
    "inputs": "Inputs",
    "commands": "Commands",
    "options": "Run Options",
    "workflow": "Workflow",
    "outputs": "Outputs",
    "metrics": "Metric Definitions",
    "selection": "Operational Selection",
    "long-reads": "Long-Read Reconstruction",
    "metagenomics": "Metagenomic Plasmid Benchmarking",
    "orthogonal-validation": "Orthogonal Validation Evidence",
    "console": "Console Messages",
    "troubleshooting": "Troubleshooting",
    "reproducibility": "Reproducibility and Citation",
    "deployment": "Public Deployment",
}


def project_root(value):
    root = Path(value).resolve()
    if not (root / "scripts" / "run_all.sh").is_file():
        raise argparse.ArgumentTypeError(
            f"{root} is not a PlasBench source checkout (scripts/run_all.sh missing)"
        )
    return root


def is_project_root(root):
    """Whether *root* contains the runnable pipeline, not merely the CLI wheel."""
    return (root / "scripts" / "run_all.sh").is_file()


def configured_data_dir(root):
    """Return the persistent data location configured by install.sh.

    The Bash workflow reads config/local.env itself. This small equivalent keeps
    CLI commands that manage input FASTQs (notably init-local) in the same
    storage location without evaluating arbitrary shell content in Python.
    """
    configured = os.environ.get("DATA_DIR") or os.environ.get("PLASBENCH_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    settings = root / "config" / "local.env"
    if settings.is_file():
        for line in settings.read_text(encoding="utf-8").splitlines():
            if line.startswith("export PLASBENCH_DATA_DIR="):
                value = line.split("=", 1)[1].strip()
                try:
                    values = shlex.split(value)
                except ValueError:
                    break
                if len(values) == 1:
                    return Path(values[0]).expanduser()
    return root / "data"


def run(command, root, env=None):
    merged_env = os.environ.copy()
    # The Bash configuration derives PROJECT_ROOT from its script location. Do
    # not inject a Windows path here: Git Bash would interpret its backslashes.
    if env:
        merged_env.update(env)
    code = subprocess.run(command, cwd=root, env=merged_env, check=False).returncode
    if code < 0 or code in (137, 139, 134):
        # Killed from outside (out of memory, WSL or the system stopping it): the command itself could not say so.
        from .exitcodes import explain
        sys.stderr.write(f"\nERROR: PlasBench stopped: {explain(code)} (exit {code}). Finished work is kept; run the "
                         "same command again to continue. The logs folder has the last messages.\n")
    return code


def bash_command():
    """Find a Bash executable without accidentally preferring the broken WSL shim."""
    explicit = os.environ.get("PLASBENCH_BASH")
    if explicit:
        return explicit
    if os.name != "nt":
        return "bash"
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidate = Path(base) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    return shutil.which("bash") or "bash"


def open_report_in_browser(report):
    """Open a local report with the host's browser, including WSL hosts."""
    report = Path(report).resolve()
    if not report.is_file():
        raise SystemExit(f"ERROR: report not found: {report}")
    if os.name == "nt":
        os.startfile(str(report))  # type: ignore[attr-defined]
        return
    # wslview translates the Linux pathname to Windows before opening it.
    if os.environ.get("WSL_DISTRO_NAME") and shutil.which("wslview"):
        subprocess.Popen(["wslview", str(report)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return
    webbrowser.open(report.as_uri())


def announce_report(report, open_now=False, prompt=True):
    """Give every completed benchmark the same clear report handoff."""
    report = Path(report).resolve()
    if not report.is_file():
        return
    print("\n[plasbench] Benchmark report ready")
    print(f"[plasbench] Report file : {report}")
    print(f"[plasbench] Open command: plasbench open-report --report {shlex.quote(str(report))}")
    if open_now:
        open_report_in_browser(report)
        print("[plasbench] Opening the report in your default browser.")
    elif prompt and sys.stdin.isatty():
        try:
            answer = input("[plasbench] Open the report now? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer in {"y", "yes"}:
            open_report_in_browser(report)
            print("[plasbench] Opening the report in your default browser.")
        else:
            print("[plasbench] Report was not opened. Run the Open command above whenever you are ready.")


def print_docs(root, topic):
    guide = root / "docs" / "USER_GUIDE.md"
    if not guide.is_file():
        raise SystemExit(f"ERROR: user guide not found at {guide}")
    text = guide.read_text(encoding="utf-8")
    if topic == "all":
        print(text, end="" if text.endswith("\n") else "\n")
        return
    heading = "## " + DOC_TOPICS[topic]
    start = text.find(heading)
    if start < 0:
        raise SystemExit(f"ERROR: documentation section not found: {topic}")
    end = text.find("\n## ", start + len(heading))
    print(text[start:] if end < 0 else text[start:end])


def write_run_script(path, root, command_args, env):
    """Write the exact resolved invocation as a standalone, editable, runnable
    bash script instead of executing it -- so the underlying commands PlasBench
    would run are visible and changeable, not hidden behind the CLI wrapper.
    """
    lines = [
        "#!/usr/bin/env bash",
        f"# Generated by 'plasbench ... --write-script {path.name}'.",
        "# This is a plain, editable batch script, not a hidden CLI internal: change",
        "# any exported value below, add or remove stages, or add your own commands,",
        f"# then run it directly: bash {path.name}",
        "set -euo pipefail",
        f"cd {shlex.quote(root.as_posix())}",
        "",
    ]
    for key, value in env.items():
        lines.append(f"export {key}={shlex.quote(str(value))}")
    if env:
        lines.append("")
    lines.append(" ".join(shlex.quote(str(a)) for a in command_args))
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass  # best-effort; harmless on platforms/filesystems without exec bits
    print(f"Wrote {path}\n")
    print(text, end="")
    print(f"\nReview or edit it, then run: bash {path}")


def print_concept_note(root):
    """Print the non-technical project concept note from the source checkout."""
    note = root / "docs" / "CONCEPT_NOTE.md"
    if not note.is_file():
        raise SystemExit(f"ERROR: concept note not found: {note}")
    print(note.read_text(encoding="utf-8"), end="")


VALID_STAGES = frozenset(str(i) for i in range(8))


# Standalone analysis scripts reachable through `plasbench analysis <name>`. Each keeps its own
# argument parser, so there is one place that defines its options. Stage scripts call the same files.
ANALYSES = {
    "stratify-recovery": ("stratify_recovery.py", "Per-plasmid recovery by replicon, MOB, size band and AMR carriage"),
    "rank-sensitivity": ("rank_sensitivity.py", "How much the ranking depends on scoring choices"),
    "bin-agreement": ("bin_agreement.py", "PlasEval-style best-match scores and split/join dissimilarity between bin sets"),
    "plaseval-replication": ("plaseval_replication.py", "Score the PlasEval paper's published bins (53 E. coli isolates) with PlasBench and draw the error profile; optionally compare with the original program"),
    "build-published-outcomes": ("build_published_outcomes.py", "Rebuild the published-outcome tables (cohorts/published/) from the plsMD and Teixeira supplementary workbooks"),
    "performance-drivers": ("performance_drivers.py", "A multivariable, study-clustered regression of per-plasmid recovery on size, repeats, replicon family, resistance genes, species, depth and arm"),
    "plsdb-novelty": ("plsdb_novelty.py", "Classify each truth plasmid as known, related or novel against PLSDB and compare recovery across the classes"),
    "discover-plasmid-free": ("discover_plasmid_free.py", "Find plasmid-free negative controls (single-replicon complete genomes with long-read truth and a paired Illumina run) at NCBI"),
    "assembly-adequacy": ("assembly_adequacy.py", "Whether each short-read assembly contains the plasmids it is judged against"),
    "copy-number": ("copy_number.py", "Tool versus truth plasmid copy number per matched bin"),
    "repeat-content": ("repeat_content.py", "K-mer repeat content of the truth replicons"),
    "truth-depth-anomalies": ("truth_depth_anomalies.py", "Windows of unusual read depth on the truth reference"),
    "prereg": ("prereg_admin.py", "List, confirm and change the pre-registered scoring decisions, with a record of who decided what and when"),
    "freeze-prereg": ("freeze_prereg.py", "Freeze (--write) or verify (--verify) the pre-registered scoring parameters"),
    "label-schemes": ("label_schemes.py", "Truth labels under the three labelling schemes (NCBI primary)"),
    "detect-dimers": ("detect_dimers.py", "Find (and optionally collapse) tandem-dimer truth plasmids"),
    "recommender-eval": ("evaluate_recommender.py", "Leave-one-study-out regret, gap closed and oracle-gap verdict"),
    "warning-eval": ("evaluate_warnings.py", "PPV, sensitivity and firing rate of each operational warning"),
    "contig-crosscheck": ("contig_crosscheck.py", "Independent alignment-free second scorer for the contig layer"),
    "amr-placement": ("score_amr_placement.py", "AMR gene copies placed on the right plasmid, by gene class"),
    "leave-taxon-out": ("leave_taxon_out.py", "Leave-one-genus/phylum-out regret; --confirm-holdout evaluates the holdout once"),
    "assembly-qc": ("assembly_qc_gate.py", "Flag mixed or contaminated assemblies before ranking (advisory)"),
    "flag-database-overlap": ("flag_database_overlap.py", "Screen truth genomes that may already be in a tool's database"),
    "flag-cohort-outliers": ("flag_cohort_outliers.py", "Advisory outlier flags for cohort assembly statistics"),
    "validate-truth-table": ("validate_truth_table.py", "Check a truth table against its reference before scoring"),
    "call-structural-variants": ("call_structural_variants.py", "Alignment-derived structural discordance calls"),
    "run-quast-diagnostics": ("run_quast_diagnostics.py", "Optional QUAST structural diagnostics"),
    "compare-scoring": ("compare_scoring_methods.py", "One-off BLASTN versus minimap2 scoring cross-check"),
    "audit-three-class-scoring": ("audit_three_class_scoring.py", "Check whether binary scoring hides a third class"),
    "alignment-accuracy": ("alignment_accuracy.py", "Identity, mismatch and indel rates and missing regions for one sample and tool"),
    "feature-preservation": ("feature_preservation.py", "Gene, replicon, mobility and AMR preservation and NGOC for one sample and tool"),
    "bin-quality": ("bin_quality.py", "High and medium quality bin yield, homogeneity and completeness for one sample and tool"),
    "mask-accuracy": ("mask_accuracy.py", "Blank accuracy rates where truth was polished with the benchmark's reads"),
    "merge-tables": ("merge_tables.py", "Merge per-run shard tables into one"),
    "performance-summary": ("performance_summary.py", "Runtime, memory, reliability, cost per plasmid and scaling per tool"),
    "power-analysis": ("power_analysis.py", "Minimum detectable difference and clusters needed per tool pair"),
    "scenario-tags": ("scenario_tags.py", "Tag isolates by scenario and report performance per scenario"),
    "composite-score": ("composite_score.py", "Optional five-dimension composite with gates and weight sensitivity"),
    "compare-runs": ("compare_runs.py", "Compare repeated runs for reproducibility"),
    "simulate-validation": ("simulate_validation.py", "Check by simulation that the intervals and tests are calibrated (smoke or full)"),
    "characterise-dataset": ("characterise_dataset.py", "One table of every isolate's characteristics, each marked knowable without a reference or not"),
    "truth-marker-overlap": ("truth_marker_overlap.py", "Which tools share a database with the truth's marker evidence"),
    "truth-exclusion-sensitivity": ("truth_exclusion_sensitivity.py", "The headline F1 with and without the evidence-based truth exclusion"),
    "database-provenance": ("database_provenance.py", "Tool and database provenance table (collect), or the checksum of a database (checksum PATH)"),
}


def build_parser():
    """The complete command-line interface. `plasbench ui` renders a form for every command from this parser,
    so the window and the command line can never disagree about what a command accepts."""
    parser = argparse.ArgumentParser(
        prog="plasbench",
        description="PlasBench: benchmark plasmid-reconstruction tools against complete references.",
        epilog="Examples:\n"
               "  plasbench install-conda\n"
               "  plasbench upgrade                 (latest release; also: Setup > Check for updates in the window)\n"
               "  plasbench ui --tab                (open the window in a normal browser tab)\n"
               "  plasbench desktop-icon            (put the PlasBench icon on the desktop; --remove undoes it)\n"
               "  bash install_latest.sh --archive plasbench-<version>.tar.gz   (install a downloaded release with no network)\n"
               "  plasbench check --yes\n"
               "  plasbench install-tools core\n"
               "  plasbench install-tools all\n"
               "  plasbench ui                      (the same, in a window)\n"
               "  plasbench demo\n"
               "  plasbench run --cohort public-v1 --threads 8\n"
               "  plasbench run --samples samples.tsv --threads 8\n"
               "  plasbench run --mode metagenomics --samples meta_samples.tsv --predictions-dir predictions_meta --results-dir results_meta\n"
               "  plasbench run --mode meta --cohort bmock12 --predictions-dir predictions_meta --results-dir results_meta\n"
               "  plasbench metagenomics validate --manifest meta_samples.tsv\n"
               "  plasbench materialize-meta-bmock12 --out-dir data/metagenomics\n"
               "  plasbench validate-orthogonal-evidence --evidence evidence.tsv --out results/orthogonal_validation.summary.json\n"
               "  plasbench run --cohort public-v1 --write-script run_public_v1.sh\n"
               "  plasbench run 3 4 5 6 --platon off --assembler unicycler\n"
               "  plasbench select-candidates --scores results/scores.tsv --samples config/accessions.tsv --results-dir results --out-prefix results/benchmark\n"
               "  plasbench reconstruct --sample new_isolate_01 --sra SRR12345678\n"
               "  plasbench metagenomics validate --manifest meta_samples.tsv\n"
               "  plasbench report --results-dir results\n"
               "\n"
               "Run 'plasbench docs' for the full guide, or 'plasbench docs --topic TOPIC'\n"
               "for one section (see --topic choices on 'plasbench docs --help').",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"plasbench {__version__}")
    parser.add_argument("--project-root", type=project_root, default=Path.cwd(),
                        help="PlasBench source checkout (default: current directory).")
    sub = parser.add_subparsers(dest="command", required=True)
    ui_parser = sub.add_parser(
        "ui", help="Open the PlasBench window: set up, add tools, run benchmarks and read results without the command line.")
    ui_parser.add_argument("--port", type=int, default=8770, help="Local port (default 8770; the next free one is used).")
    ui_parser.add_argument("--no-browser", action="store_true", help="Print the address instead of opening a window.")
    ui_parser.add_argument("--tab", action="store_true",
                           help="Open the page in a normal browser tab instead of an app-style window.")
    ui_parser.add_argument("--new-instance", action="store_true",
                           help="Start another server even if a PlasBench window is already running for this folder.")
    git_parser = sub.add_parser(
        "install-git",
        help="Install Git (optional): Git for Windows with Git Bash on Windows, conda-forge git elsewhere.")
    git_parser.add_argument("--force", action="store_true", help="Install even if git is already found.")
    git_parser.add_argument("--dry-run", action="store_true", help="Only say what would be done.")
    icon_parser = sub.add_parser(
        "desktop-icon",
        help="Put a PlasBench icon on the desktop and in the applications/Start menu; clicking it starts PlasBench.")
    icon_parser.add_argument("--remove", action="store_true", help="Remove the PlasBench icons instead.")
    icon_parser.add_argument("--no-desktop", action="store_true",
                             help="Only the applications/Start menu entry, not an icon on the desktop.")
    demo_parser = sub.add_parser("demo", help="Run the offline synthetic scoring and report demo.")
    demo_parser.add_argument("--open-report", action="store_true",
                             help="Open the completed demo report in your browser without asking.")
    demo_parser.add_argument("--no-report-prompt", action="store_true",
                             help="Do not ask whether to open the demo report when it finishes; just print its path.")
    open_report_parser = sub.add_parser("open-report", help="Open a completed HTML report in the default browser.")
    open_report_group = open_report_parser.add_mutually_exclusive_group(required=True)
    open_report_group.add_argument("--report", type=Path, help="Path to benchmark.report.html.")
    open_report_group.add_argument("--results-dir", type=Path,
                                   help="Results directory containing benchmark.report.html.")
    report_pdf_parser = sub.add_parser("report-pdf", help="Export a completed HTML report to a PDF with headless Edge or Chrome.")
    report_pdf_group = report_pdf_parser.add_mutually_exclusive_group(required=True)
    report_pdf_group.add_argument("--report", type=Path, help="Path to benchmark.report.html.")
    report_pdf_group.add_argument("--results-dir", type=Path, help="Results directory containing benchmark.report.html.")
    report_pdf_parser.add_argument("--out", type=Path, help="PDF to write (default: next to the report, same name with .pdf).")
    for status_name, status_help in (
            ("status", "Show what a run is doing now: stage, isolate and step, for how long, CPU and memory, progress so far, and plain hints when it looks stuck."),
            ("diagnose", "Like status, plus the busiest processes of the run: use it when a run seems stuck.")):
        status_parser = sub.add_parser(status_name, help=status_help)
        status_group = status_parser.add_mutually_exclusive_group()
        status_group.add_argument("--study", help="The study whose run to inspect (default: the most recently updated study).")
        status_group.add_argument("--results-dir", type=Path, help="A results folder to inspect (its run_events.jsonl and .run.lock are read).")
        status_parser.add_argument("--json", action="store_true", help="Print the summary as JSON, for scripts and the window.")
        status_parser.add_argument("--watch", type=int, metavar="SECONDS", help="Repeat every SECONDS until you press Ctrl+C.")
    sub.add_parser("test", help="Run the complete offline regression suite.")
    net_parser = sub.add_parser(
        "net", help="Check which online services this computer can reach (NCBI, ENA, GitHub, conda, ...) and what to do when one is not.")
    net_parser.add_argument("--service", action="append", default=[], metavar="NAME",
                            help="Check only this service (repeatable; names are in config/network_services.tsv). Default: all.")
    net_parser.add_argument("--json", action="store_true", help="Print the answer as JSON, for scripts and the window.")
    upgrade_parser = sub.add_parser(
        "upgrade",
        help="Download the latest release and reuse this install's shared reads and databases.",
    )
    upgrade_parser.add_argument("--yes", action="store_true", help="Pass --yes to the new release installer.")
    upgrade_parser.add_argument("--refresh-tools", action="store_true",
                                help="Also refresh Conda packages/tools; normally unnecessary and may download channel indexes.")
    check_parser = sub.add_parser(
        "check",
        help="Check configured runtime dependencies (tools and databases); offers to install what's missing.",
    )
    check_parser.add_argument("--yes", action="store_true",
                              help="Install missing tools/databases without an interactive confirmation prompt.")
    local_parser = sub.add_parser("init-local",
                                  help="Set up one of your own isolates: file layout, truth-table template, sheet row.")
    local_parser.add_argument("--sample", required=True, help="Sample id; becomes the directory name.")
    local_parser.add_argument("--reads-1", required=True, help="Forward reads (gzipped FASTQ).")
    local_parser.add_argument("--reads-2", required=True, help="Reverse reads (gzipped FASTQ).")
    local_parser.add_argument("--reference", help="Complete assembly FASTA for this isolate (the ground truth).")
    local_parser.add_argument("--sequence-report", help="NCBI sequence_report.jsonl, if you have one.")
    local_parser.add_argument("--data-dir", type=Path,
                              help="Where sample directories live (default: the configured shared data directory).")
    local_parser.add_argument("--samples", default="config/local.tsv", help="Sample sheet to create or append to.")
    local_parser.add_argument("--prefix", help="Read filename prefix (default: the sample id).")
    local_parser.add_argument("--accession", default="LOCAL", help="assembly_accession column value.")
    local_parser.add_argument("--link", choices=("copy", "symlink", "hardlink"), default="copy",
                              help="How to place the input files (default: copy).")
    local_parser.add_argument("--force", action="store_true", help="Overwrite an existing truth.tsv.")

    intake_parser = sub.add_parser(
        "intake",
        help="Your own isolates: write a sheet template, find isolates in a folder, place them, and quick-test that PlasBench can use them.",
        description="template: write a sheet to fill in.  scan FOLDER...: find isolates (changes nothing).  stage FOLDER...: place them and write the sheet.  "
                    "check [--fix]: open every file the way a run will. Guide: docs/INPUT_GUIDE.md",
    )
    intake_parser.add_argument("action", choices=("template", "scan", "stage", "check"), help="What to do.")
    intake_parser.add_argument("intake_args", nargs=argparse.REMAINDER, help="Arguments of that action (try: plasbench intake scan --help).")

    cohort_parser = sub.add_parser("validate-cohort", help="Validate a cohort schema or verify its NCBI-linked pairs.")
    cohort_parser.add_argument("--samples", type=Path, required=True, help="Cohort TSV to validate.")
    cohort_parser.add_argument("--online", action="store_true", help="Verify NCBI assembly/SRA linkage and library metadata.")
    cohort_parser.add_argument("--email", help="Contact email sent to NCBI E-utilities.")
    cohort_parser.add_argument("--api-key", help="NCBI API key; defaults to NCBI_API_KEY when omitted.")
    cohort_parser.add_argument("--write-lock", type=Path, help="Write NCBI verification evidence as JSON; requires --online.")
    cohort_parser.add_argument("--verify-lock", type=Path, help="Require a verification lock that matches the cohort TSV.")
    cohort_parser.add_argument("--ledger", type=Path, help="cohorts/accepted_accessions.tsv (build-ledger); "
                                                            "rejects a row whose BioSample is already in a prior released cohort.")
    orthogonal_parser = sub.add_parser("validate-orthogonal-evidence", help="Validate optional laboratory or independent-technology evidence without changing computational scores.")
    orthogonal_parser.add_argument("--evidence", type=Path, required=True, help="TSV described in docs/ORTHOGONAL_VALIDATION.md.")
    orthogonal_parser.add_argument("--out", type=Path, help="Optional summary JSON, normally results/orthogonal_validation.summary.json.")
    analysis_parser = sub.add_parser(
        "analysis",
        help="Run one standalone analysis script on a completed run (see 'plasbench analysis --list').",
        description="Run a standalone analysis script with its own options, e.g. "
                    "'plasbench analysis stratify-recovery --results-dir results --data-dir data --out out.tsv'. "
                    "Use 'plasbench analysis <name> --help' for that script's options.")
    analysis_parser.add_argument("name", nargs="?", choices=sorted(ANALYSES), help="Analysis to run.")
    analysis_parser.add_argument("--list", action="store_true", help="List the available analyses and exit.")
    analysis_parser.add_argument("analysis_args", nargs=argparse.REMAINDER, help="Arguments passed to the script.")
    amr_draft_parser = sub.add_parser("derive-amr-truth", help="Draft AMR truth from reference annotation (never writes truth_amr.tsv).")
    amr_draft_parser.add_argument("--features", type=Path, required=True, help="truth_features.tsv from annotate_reference.py.")
    amr_draft_parser.add_argument("--truth", type=Path, required=True, help="truth.tsv for the same reference.")
    amr_draft_parser.add_argument("--out", type=Path, required=True, help="Draft TSV, e.g. data/<sample>/truth_amr.draft.tsv.")
    promote_parser = sub.add_parser("promote-amr-truth", help="Promote a reviewed AMR truth draft to truth_amr.tsv (a deliberate human step).")
    promote_parser.add_argument("--draft", type=Path, required=True, help="truth_amr.draft.tsv from derive-amr-truth, after you have reviewed it.")
    promote_parser.add_argument("--truth", type=Path, required=True, help="truth.tsv for the same reference.")
    promote_parser.add_argument("--out", type=Path, help="Default: truth_amr.tsv beside the draft.")
    promote_parser.add_argument("--reviewed-by", required=True, help="Who reviewed the draft.")
    promote_parser.add_argument("--database-version", required=True, help="The real AMR database version (the draft holds only the caller's version).")
    promote_parser.add_argument("--confirm-reviewed", action="store_true", help="Required: states that the draft was reviewed gene by gene.")
    promote_parser.add_argument("--force", action="store_true", help="Overwrite an existing truth_amr.tsv.")
    audit_labels_parser = sub.add_parser("audit-truth-labels", help="Screen PLASMID/CHROMOSOME truth labels against replicon/MOB evidence (advisory).")
    audit_labels_parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Directory of per-sample truth folders.")
    audit_labels_parser.add_argument("--out", type=Path, default=Path("results/benchmark.truth_label_audit.tsv"))
    curate_parser = sub.add_parser(
        "curate-cohort",
        help="Strictly screen candidate assembly/SRA pairs and write accepted/rejected tables.",
        epilog="Candidates need assembly_accession AND sra_run populated. If a source only "
               "gives a BioSample (no assembly at all was ever deposited), first run "
               "'python3 python/resolve_ncbi_accessions.py --candidates ... --out-dir ...' -- "
               "its resolved.tsv is curate-cohort-ready, and its self_build_candidates.tsv "
               "identifies isolates PlasBench can build its own truth for instead (see "
               "docs/COHORTS.md's truth_source=self_assembled_hybrid section).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    curate_parser.add_argument("--candidates", type=Path, required=True)
    curate_parser.add_argument("--out-dir", type=Path, required=True)
    curate_parser.add_argument("--email")
    curate_parser.add_argument("--api-key")
    curate_parser.add_argument("--ledger", type=Path, help="cohorts/accepted_accessions.tsv (build-ledger); "
                                                           "rejects a candidate whose BioSample is already in a prior released cohort.")
    ledger_parser = sub.add_parser("build-ledger", help="Regenerate the cross-cohort accession ledger from cohorts/*.lock.json.")
    ledger_parser.add_argument("--cohorts-dir", type=Path, default=Path("cohorts"), help="Directory containing *.lock.json files (default: cohorts).")
    ledger_parser.add_argument("--out", type=Path, default=Path("cohorts/accepted_accessions.tsv"))
    contrib_parser = sub.add_parser(
        "prepare-contribution",
        help="Validate a new-isolate contribution and stage it on a local git branch for manual PR "
             "(schema, NCBI-linked evidence, cross-cohort dedup, privacy screen, metric bounds; "
             "nothing is pushed automatically).",
    )
    contrib_parser.add_argument("--cohort", required=True, help="Target cohort name, e.g. public-v2 (must already exist as cohorts/<NAME>.tsv).")
    contrib_parser.add_argument("--new-rows", type=Path, required=True, help="TSV of new cohort rows; columns must be a subset of cohorts/<NAME>.tsv's own header.")
    contrib_parser.add_argument("--scores", type=Path, required=True, help="Your own locally-produced scores.tsv containing row(s) for the new sample_id(s), and nothing else.")
    contrib_parser.add_argument("--tool-status", type=Path, help="Optional locally-produced tool_status.tsv for the new sample_id(s).")
    contrib_parser.add_argument("--cohorts-dir", type=Path, default=Path("cohorts"))
    contrib_parser.add_argument("--branch-label", help="contrib/<label> branch name; required when contributing more than one sample.")
    contrib_parser.add_argument("--email", help="Contact email sent to NCBI E-utilities.")
    contrib_parser.add_argument("--api-key", help="NCBI API key; defaults to NCBI_API_KEY when omitted.")
    discover_parser = sub.add_parser("discover-cohort", help="Discover strict assembly/paired-Illumina candidate pairs from NCBI.")
    discover_parser.add_argument("--organism", action="append", required=True, help="Scientific name; repeat for each taxon.")
    discover_parser.add_argument("--out-dir", type=Path, required=True)
    discover_parser.add_argument("--country", action="append", default=[],
                                 help="Require deposited BioSample geo_loc_name to contain this country/place; repeat as needed.")
    discover_parser.add_argument("--max-assemblies", type=int, default=30)
    discover_parser.add_argument("--negative-controls", action="store_true",
                                 help="Look for plasmid-free isolates (complete genomes whose record declares no plasmid, with a paired Illumina run) to use as negative controls.")
    discover_parser.add_argument("--email")
    discover_parser.add_argument("--api-key")
    provenance_parser = sub.add_parser(
        "collect-truth-provenance",
        help="Record each truth assembly's construction (long-read-first/short-read-first) and polishing reads from NCBI evidence.")
    provenance_parser.add_argument("--samples", type=Path, required=True, help="Cohort TSV.")
    provenance_parser.add_argument("--evidence-out", type=Path, required=True)
    provenance_parser.add_argument("--sheet-out", type=Path, help="Copy of --samples with the provenance columns filled.")
    provenance_parser.add_argument("--api-key")
    design_parser = sub.add_parser(
        "discover-design-cohort",
        help="Find long-read-first, one-per-BioProject NCBI isolates until each species reaches a cluster target.")
    design_parser.add_argument("--species", action="append", required=True, help="Taxon name; repeat per species.")
    design_parser.add_argument("--existing", type=Path, help="Current cohort TSV with provenance columns.")
    design_parser.add_argument("--ledger", type=Path, default=Path("cohorts/accepted_accessions.tsv"))
    design_parser.add_argument("--target-clusters", type=int, default=22)
    design_parser.add_argument("--max-reports", type=int, default=4000)
    design_parser.add_argument("--max-checks", type=int, default=300)
    design_parser.add_argument("--out", type=Path, required=True)
    design_parser.add_argument("--evidence-out", type=Path, required=True)
    design_parser.add_argument("--api-key")
    review_parser = sub.add_parser("review-candidates", help="Create an additive, non-release balanced shortlist from NCBI candidates.")
    review_parser.add_argument("--candidates", type=Path, required=True)
    review_parser.add_argument("--out-dir", type=Path, required=True)
    review_parser.add_argument("--max-per-bioproject", type=int, default=3)
    review_parser.add_argument("--max-per-organism", type=int, default=8)
    import_parser = sub.add_parser("import-contributed-cohort", help="Select a seeded, cluster-aware candidate cohort from the contributed RefSeq/SRA pool (unverified until validate-cohort --online).")
    import_parser.add_argument("--out-dir", type=Path, required=True)
    import_parser.add_argument("--pool", type=Path, help="Candidate pool TSV or .gz (default: the copy shipped in cohorts/candidates/contributed-refseq-sra).")
    import_parser.add_argument("--released-after", default="", help="YYYY-MM-DD; keep genomes public on or after this date (on --date-basis).")
    import_parser.add_argument("--released-before", default="", help="YYYY-MM-DD; build the older comparison arm.")
    import_parser.add_argument("--date-basis", choices=("earliest_public", "assembly", "read"), help="Default: LEAKAGE_DATE_BASIS, else earliest_public.")
    import_parser.add_argument("--species", action="append", default=[])
    import_parser.add_argument("--country", action="append", default=[])
    import_parser.add_argument("--region", action="append", default=[])
    import_parser.add_argument("--allow-short-read-first", action="store_true")
    import_parser.add_argument("--max-clusters-per-species", type=int, default=0)
    import_parser.add_argument("--min-clusters", type=int, default=20)
    import_parser.add_argument("--seed", type=int, default=20260916)
    import_parser.add_argument("--arm", default="", help="Label for selection_arm (for example recent or older) so two runs can be combined by resolve-contributed-cohort.")
    report_parser = sub.add_parser("selection-report", help="Write cohorts/<name>.selection.json: how a cohort was selected (shown as the Selection report pop-up in the window).")
    report_parser.add_argument("--name", required=True)
    report_parser.add_argument("--sheet", type=Path, required=True)
    report_parser.add_argument("--importer-dir", type=Path, required=True)
    report_parser.add_argument("--resolver-dir", type=Path, required=True)
    report_parser.add_argument("--out", type=Path, required=True)
    report_parser.add_argument("--importer-command", default="")
    report_parser.add_argument("--resolver-command", default="")
    report_parser.add_argument("--validate-command", default="")
    compare_parser = sub.add_parser("compare-published", help="Put PlasBench's results on a publication's isolates beside the publication's own outcomes (tables, JSON and an optional page).")
    compare_parser.add_argument("--results-dir", type=Path, required=True, help="The finished run's results directory.")
    compare_parser.add_argument("--samples", type=Path, required=True, help="The cohort sheet that was run (matched to the publication by BioSample).")
    compare_parser.add_argument("--scores", type=Path, help="Defaults to <results-dir>/scores.tsv.")
    compare_parser.add_argument("--out-prefix", type=Path, help="Defaults to <results-dir>/benchmark.published_comparison.")
    compare_parser.add_argument("--html", type=Path, help="Also write a stand-alone page.")
    pubcohort_parser = sub.add_parser("build-publication-cohorts", help="Build the publication cohorts (pub-*.tsv and publication-v1.tsv) from the candidate ledgers, public-v4 and NCBI resolution.")
    pubcohort_parser.add_argument("--resolved", type=Path, action="append", default=[], metavar="STUDY=resolved.tsv", help="Resolver output per study, for example mobsuite=work/mobsuite/resolved.tsv (repeatable).")
    pubcohort_parser.add_argument("--out-dir", type=Path, default=Path("cohorts"))
    pubcohort_parser.add_argument("--audit", type=Path, help="Write the per-candidate outcome table here.")
    resolve_parser = sub.add_parser("resolve-contributed-cohort", help="Verify importer candidates at NCBI, run the pre-download read-QC check, and choose the final per-species rows.")
    resolve_parser.add_argument("--candidates", type=Path, action="append", required=True, help="Importer candidates.tsv; repeat for the recent and older arms.")
    resolve_parser.add_argument("--out-dir", type=Path, required=True)
    resolve_parser.add_argument("--target-per-species", type=int, default=20)
    resolve_parser.add_argument("--min-recent", type=int, default=10)
    resolve_parser.add_argument("--cache", type=Path, help="JSON cache of earlier per-candidate results.")
    conda_parser = sub.add_parser(
        "install-conda",
        help="Check for conda/mamba/micromamba; offer to install Miniforge if none is found.",
    )
    conda_parser.add_argument("--yes", action="store_true", help="Install without an interactive confirmation prompt.")
    conda_parser.add_argument("--prefix", type=Path, help="Install location (default: $HOME/miniforge3).")
    install_parser = sub.add_parser("install-tools", help="Install, inspect, or verify registered bioinformatics tool profiles.")
    install_parser.add_argument("profile", nargs="?", default="core", help="list, plan, validate, locked, core, assembly, metagenomics, reconstruction, simulate, quast, long-read, annotation, annotation-prokka, ppr-meta, plsmd, mobilome-map, gplas, gplas2, plassembler, hybracter, trycycler, genomad, plasme, plasgraph2, rfplasmid, plasmidhunter, plasmer, plascope, all, or a conda package name.")
    install_parser.add_argument("--env", default="plasbench", help="Conda/mamba environment name (default: plasbench).")
    install_parser.add_argument("--yes", action="store_true", help="Use non-interactive mode for supported installer profiles; database setup remains explicit in 'plasbench check --yes'.")
    tools_parser = sub.add_parser(
        "tools", help="Add your own plasmid tool: create, validate, list and install user tool manifests (docs/ADDING_TOOLS.md).")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list", help="Every user tool PlasBench can see, with its task, track, run mode and output format.")
    tools_validate = tools_sub.add_parser("validate", help="Check every manifest (or one); exit 1 with each problem listed.")
    tools_validate.add_argument("name", nargs="?")
    tools_show = tools_sub.add_parser("show", help="Print one tool's manifest as PlasBench reads it.")
    tools_show.add_argument("name")
    tools_new = tools_sub.add_parser("new", help="Write a commented manifest template to fill in.")
    tools_new.add_argument("name", help="Tool name: lower-case letters, digits and _.")
    tools_new.add_argument("--dir", type=Path, help="Where to create it (default: ~/.plasbench/tools).")
    tools_add = tools_sub.add_parser("add", help="Validate a tool folder (or manifest) and copy it to ~/.plasbench/tools.")
    tools_add.add_argument("path", type=Path)
    tools_install = tools_sub.add_parser("install", help="Install a user tool from its [install] section (same as install-tools NAME).")
    tools_install.add_argument("name")
    tools_install.add_argument("--env", default="plasbench", help="Conda environment holding PlasBench itself (default: plasbench).")
    candidate_dataset_parser = sub.add_parser("candidate-dataset", help="Build an auditable, label-safe candidate-quality dataset from a completed run.")
    candidate_dataset_parser.add_argument("--scores", type=Path, required=True)
    candidate_dataset_parser.add_argument("--samples", type=Path, required=True)
    candidate_dataset_parser.add_argument("--results-dir", type=Path, required=True)
    candidate_dataset_parser.add_argument("--out-prefix", type=Path, required=True)
    candidate_dataset_parser.add_argument("--tool-status", type=Path)
    import_external_parser = sub.add_parser("import-external-benchmark", help="Archive source-labelled external benchmark evidence without altering native ranks.")
    import_external_parser.add_argument("--predictions", type=Path, required=True)
    import_external_parser.add_argument("--ani", type=Path)
    import_external_parser.add_argument("--out-dir", type=Path, required=True)
    import_external_parser.add_argument("--source-repository", required=True)
    import_external_parser.add_argument("--source-revision", required=True)
    import_external_parser.add_argument("--citation", required=True)
    docs_parser = sub.add_parser("docs", help="Print the comprehensive user guide or a topic.")
    docs_parser.add_argument("--topic", choices=("all", *DOC_TOPICS), default="all",
                             help="Guide topic to print (default: all).")
    sub.add_parser("concept-note", help="Print the non-technical researcher and donor concept note.")
    meta_parser = sub.add_parser("metagenomics", aliases=("meta", "beta"),
                                 help="Validate, score, or report the separate graph-aware metagenomic track.")
    meta_parser.add_argument("action", choices=("validate", "score", "report"))
    meta_parser.add_argument("-s", "--manifest", "--samples", type=Path, required=True, help="Community manifest TSV; see docs/METAGENOMICS.md.")
    meta_parser.add_argument("-p", "--predictions-dir", type=Path, help="Normalized <tool>/<community>.bins.tsv directory; required for score.")
    meta_parser.add_argument("-o", "--results-dir", type=Path, help="Metagenomic result directory; required for score/report.")
    meta_parser.add_argument("--open-report", action="store_true", help="Open metagenomics.report.html after scoring.")
    meta_parser.add_argument("--no-report-prompt", action="store_true", help="Do not offer to open the metagenomic report.")
    meta_parser.add_argument("--release-ready", action="store_true", help="For validate only: require public-release provenance fields for scored communities.")
    meta_audit = sub.add_parser("audit-meta-cohort", help="Audit a community manifest for regime coverage and duplicate-reference leakage.")
    meta_audit.add_argument("--manifest", type=Path, required=True)
    meta_audit.add_argument("--out", type=Path, required=True)
    meta_audit.add_argument("--release-ready", action="store_true")
    meta_design = sub.add_parser("design-meta-synthetic", help="Write a deterministic, provenance-pinned synthetic-community design; it does not fabricate reads.")
    meta_design.add_argument("--members", type=Path, required=True, help="TSV following cohorts/metagenomics.synthetic-members.example.tsv.")
    meta_design.add_argument("--out-dir", type=Path, required=True)
    meta_design.add_argument("--seed", type=int, required=True)
    meta_design.add_argument("--simulator", default="CAMISIM")
    meta_design.add_argument("--simulator-version", required=True)
    meta_design.add_argument("--container-image", required=True)
    meta_design.add_argument("--container-digest", required=True)
    meta_intake = sub.add_parser("validate-meta-intake", help="Validate an external metagenomic tool/dataset intake decision before implementation.")
    meta_intake.add_argument("--intake", type=Path, default=Path("config/metagenomic_ecosystem_intake.tsv"))
    bmock_parser = sub.add_parser("materialize-meta-bmock12", help="Download, checksum-verify, and convert BMock12's real physical-community gold standard.")
    bmock_parser.add_argument("--out-dir", type=Path, required=True, help="Directory for BMock12 assembly, graph, truth TSV, and executable manifest.")
    bmock_parser.add_argument("--source-manifest", type=Path, default=Path("config/metagenomic_truth_sources.tsv"), help="Checksum-pinned artifact registry.")
    bmock_parser.add_argument("--retries", type=int, default=3, help="Download attempts per artifact (default: 3).")
    meta_normalize = sub.add_parser("normalize-meta-classifier", help="Normalize PPR-Meta or PlasmidHunter probability output for the meta track.")
    meta_normalize.add_argument("--tool", choices=("ppr_meta", "plasmidhunter"), required=True)
    meta_normalize.add_argument("--input", type=Path, required=True)
    meta_normalize.add_argument("--out", type=Path, required=True)
    meta_normalize.add_argument("--threshold", type=float, default=0.5)
    mobilome_parser = sub.add_parser("import-mobilome-evidence", help="Import MAP-compatible GFF3 as non-scoring metagenomic evidence.")
    mobilome_parser.add_argument("--gff", type=Path, required=True)
    mobilome_parser.add_argument("--community", required=True)
    mobilome_parser.add_argument("--sample", required=True)
    mobilome_parser.add_argument("--out", type=Path, required=True)
    report_parser = sub.add_parser("report", help="Regenerate the leaderboard and HTML report from scores.")
    select_parser = sub.add_parser("select-candidates", help="Create conservative recommendations and copy existing selected candidates.")
    select_parser.add_argument("--scores", type=Path, required=True)
    select_parser.add_argument("--samples", type=Path, required=True)
    select_parser.add_argument("--results-dir", type=Path, required=True)
    select_parser.add_argument("--out-prefix", type=Path, required=True)
    select_parser.add_argument("--tool-status", type=Path)
    select_parser.add_argument("--min-samples", type=int, default=5)
    select_parser.add_argument("--min-coverage", type=float, default=0.80)
    select_parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    unknown_parser = sub.add_parser("select-unknown", help="Choose an evidence-gated benchmark method for an unlabelled operational sample.")
    unknown_parser.add_argument("--recommendations", type=Path, required=True, help="benchmark.recommendations.tsv from a validated benchmark.")
    unknown_parser.add_argument("--sample-id", required=True)
    unknown_parser.add_argument("--results-dir", type=Path, required=True)
    unknown_parser.add_argument("--out", type=Path, help="Selection JSON path; defaults to results/<sample>/selection_report.json.")
    unknown_parser.add_argument("--organism", default="", help="Scientific name, used to select an organism-specific recommendation.")
    unknown_parser.add_argument("--gram-group", default="", help="Gram group, used if no organism-specific recommendation exists.")
    unknown_parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    reconstruct_parser = sub.add_parser(
        "reconstruct",
        help="Reconstruct plasmids for ONE new operational sample using only the selected method, "
             "not every benchmarked tool.",
    )
    reconstruct_parser.add_argument("--sample", required=True, help="New sample id (letters, digits, dot, dash, underscore only).")
    reconstruct_parser.add_argument("--sra", required=True, help="SRA run accession for this sample's Illumina reads.")
    reconstruct_parser.add_argument("--tool", choices=("mob_recon", "platon", "plasmidspades", "gplas2_mob", "gplas2_external",
                                                       "genomad", "plasme", "plasgraph2", "rfplasmid", "plasmidhunter",
                                                       "plasmer", "plascope", "plasmidec"),
                                    help="Run exactly this tool, skipping the benchmark recommendation lookup.")
    reconstruct_parser.add_argument("--recommendation-model", type=Path,
                                    help="Optional fitted recommendation-model JSON (default: <results-dir>/benchmark.recommendation_model.json "
                                         "when RUN_RECOMMENDATION_MODEL=1). Used only if model_ready is true.")
    reconstruct_parser.add_argument("--read-depth-x", type=float,
                                    help="This isolate's own read depth, if known, for live model prediction (see --recommendation-model).")
    reconstruct_parser.add_argument("--recommendations", type=Path,
                                    help="benchmark.recommendations.tsv to consult when --tool is omitted "
                                         "(default: <results-dir>/benchmark.recommendations.tsv).")
    reconstruct_parser.add_argument("--organism", default="", help="Scientific name, used to match an organism-specific recommendation.")
    reconstruct_parser.add_argument("--gram-group", default="", help="Gram group, used if no organism-specific recommendation exists.")
    reconstruct_parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    reconstruct_parser.add_argument("--data-dir", type=Path, help="Directory for downloaded reads and assembly (default: config value).")
    reconstruct_parser.add_argument("--results-dir", type=Path, help="Directory for predictions and the selection report (default: config value).")
    reconstruct_parser.add_argument("--log-dir", type=Path, help="Directory for tool logs (default: config value).")
    ladder_parser = sub.add_parser("depth-ladder", help="Create deterministic local-input depth-ladder cohorts using seqtk.")
    ladder_parser.add_argument("--samples", type=Path, required=True)
    ladder_parser.add_argument("--data-dir", type=Path, required=True)
    ladder_parser.add_argument("--out-dir", type=Path, required=True)
    ladder_parser.add_argument("--depths", default="20,40,80,160")
    ladder_parser.add_argument("--seed", type=int, default=20260901)
    depth_report_parser = sub.add_parser("depth-report", help="Summarize a completed depth-ladder benchmark and create an SVG plot.")
    depth_report_parser.add_argument("--scores", type=Path, required=True)
    depth_report_parser.add_argument("--manifest", type=Path, required=True)
    depth_report_parser.add_argument("--out-prefix", type=Path, required=True)
    depth_report_parser.add_argument("--metric", choices=("precision", "recall", "f1", "plasmid_recall"), default="f1")
    rq_ladder_parser = sub.add_parser("read-quality-ladder", help="Create deterministic local-input read-quality-ladder cohorts using filtlong.")
    rq_ladder_parser.add_argument("--samples", type=Path, required=True)
    rq_ladder_parser.add_argument("--data-dir", type=Path, required=True)
    rq_ladder_parser.add_argument("--out-dir", type=Path, required=True)
    rq_ladder_parser.add_argument("--rungs", default="1000:8,5000:10,20000:15",
                                  help="Comma-separated MIN_LENGTH:MIN_MEAN_Q pairs.")
    rq_report_parser = sub.add_parser("read-quality-report", help="Summarize a completed read-quality-ladder benchmark and create an SVG plot.")
    rq_report_parser.add_argument("--scores", type=Path, required=True)
    rq_report_parser.add_argument("--manifest", type=Path, required=True)
    rq_report_parser.add_argument("--out-prefix", type=Path, required=True)
    rq_report_parser.add_argument("--metric", choices=("precision", "recall", "f1", "plasmid_recall"), default="f1")
    run_parser = sub.add_parser(
        "run",
        help="Run the full benchmark or selected stages.",
        epilog="Examples:\n"
               "  plasbench run --cohort public-v1 --threads 8\n"
               "  plasbench run --samples my_samples.tsv --threads 8\n"
               "  plasbench run --cohort public-v4 --max-isolates 40   (a balanced 40 of its isolates; any N)\n"
               "  plasbench run --cohort public-v1 --write-script run_public_v1.sh\n"
               "  plasbench run 3 4 5 6 --platon off --assembler unicycler\n"
               "  plasbench run --parallel-samples 3 --parallel-tools 2\n"
               "\n"
               "--cohort NAME picks a curated panel from cohorts/NAME.tsv (see cohorts/README.md\n"
               "for what ships, e.g. public-v1 and public-v2); --write-script writes the exact\n"
               "commands this invocation would run to a file you can read, edit, and run yourself\n"
               "with bash, instead of running them now.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # `choices` is deliberately NOT used here. With nargs="*", argparse on
    # Python <= 3.12 validates the empty default against choices and rejects a
    # bare `plasbench run` with "invalid choice: []". Python 3.13+ fixed that,
    # so the bug only appears for users whose environment is older -- including
    # the Python 3.11 that env/environment.yml currently solves to. Validate
    # the values ourselves instead, which behaves the same on every version.
    run_parser.add_argument("stages", nargs="*", metavar="{0,1,2,3,4,5,6,7}",
                            help=f"Optional {STAGE_HELP}")

    def add_run_options(command_parser):
        inputs = command_parser.add_argument_group("inputs and outputs")
        samples_or_cohort = inputs.add_mutually_exclusive_group()
        samples_or_cohort.add_argument("-s", "--samples", type=Path, help="Sample-sheet TSV; defaults to config/accessions.tsv.")
        samples_or_cohort.add_argument("-c", "--cohort", help="Isolate: shorthand for --samples cohorts/<NAME>.tsv (e.g. public-v1). Meta: --cohort bmock12 materializes the bundled physical truth control.")
        inputs.add_argument("--max-isolates", type=int, metavar="N",
                            help="Run only N isolates of the cohort or sample sheet (N is any number you choose). By default they are "
                                 "a balanced selection, spread across species, studies and recent / older genomes, so a small run is a "
                                 "fair miniature of the cohort; --isolate-order file takes the first N rows instead. The sheet itself is "
                                 "not changed: a copy with those rows is written next to the results and used for this run.")
        inputs.add_argument("--independent-truth-only", action="store_true",
                            help="Run only the isolates whose truth is independent of the benchmark's reads (long-read-only or long-read-first, polished with no reads "
                                 "or independent reads). With public-v4 that is about 15%% of the cohort. Combine with --max-isolates for a balanced N of them. "
                                 "The cohort file is not changed; a copy is written next to the results.")
        inputs.add_argument("--isolate-order", choices=("balanced", "file"), default="balanced",
                            help="With --max-isolates: balanced (default) spreads the N isolates across species, studies and "
                                 "recent / older genomes; file takes the first N rows exactly as they appear in the sheet.")
        inputs.add_argument("--write-script", type=Path,
                            help="Write the exact resolved commands to this file instead of running them, "
                                 "so you can review or edit them before running it yourself with bash.")
        inputs.add_argument("-d", "--data-dir", type=Path,
                            help="Folder for downloaded references, reads and assemblies. By default every study uses ONE shared folder (DATA_DIR in config/config.sh, "
                                 "~/.local/share/plasbench/data when installed by install.sh): it is reused by every study, so nothing is downloaded twice, and it is kept "
                                 "when a study is deleted. Give a folder here to use another one for this run; the study remembers it for its later runs.")
        inputs.add_argument("--keep-data-in-study", action="store_true",
                            help="Keep this run's downloaded reads and assemblies inside the study folder, in <study>/data, instead of the shared folder. That folder is "
                                 "git-ignored and is deleted together with the study. The study remembers the choice, so Resume and later runs find the reads. "
                                 "Cannot be combined with --data-dir.")
        inputs.add_argument("-o", "--results-dir", type=Path,
                            help="Directory for predictions, scores, and reports (instead of a study folder).")
        inputs.add_argument("--study", metavar="NAME",
                            help="Keep this run in its own study folder, <workspace>/NAME/ (results, logs, tmp and a "
                                 "study.json record). A run names its study after the cohort or sample sheet when this "
                                 "is not given; `report --study NAME` rebuilds that study's report. The workspace is "
                                 "PLASBENCH_WORKSPACE, default <PlasBench folder>/studies.")
        inputs.add_argument("--study-location", type=Path, metavar="PARENT_DIR",
                            help="Create the study folder as PARENT_DIR/NAME instead of in the workspace: on another drive, or anywhere you choose. PlasBench remembers where "
                                 "it is (a hidden list in the workspace), so `--study NAME` finds it again. The folder must already exist; it is never created for you, "
                                 "so a disconnected drive is not silently replaced by a folder on this computer's disk.")
        inputs.add_argument("--open-report", action="store_true",
                            help="Open benchmark.report.html in your browser when the run finishes, without asking. Only for runs that write a report (not the metagenomics track).")
        inputs.add_argument("--no-report-prompt", action="store_true",
                            help="Never stop at the end of the run to ask whether to open the report: it prints the report path and exits, so the run can go unattended. "
                                 "It changes nothing about what is run or written (the window always sets it).")
        inputs.add_argument("--log-dir", type=Path, help="Directory for tool and mapping logs.")
        inputs.add_argument("--platon-db", type=Path, help="Path to the installed Platon database.")
        inputs.add_argument("--genomad-db", type=Path, help="Path to the installed geNomad database directory (containing genomad_db/).")
        inputs.add_argument("--plasme-db", type=Path, help="Path to the installed PLASMe database directory.")
        inputs.add_argument("--plasgraph2-model-dir", type=Path, help="Path to plASgraph2's pretrained model directory (e.g. its cloned repo's model/ESKAPEE_model/).")
        inputs.add_argument("--gplas2-external-predictions-dir", type=Path,
                            help="Directory containing <sample>.tsv external gplas2 classifier files.")
        inputs.add_argument("--local-inputs", action="store_true",
                            help="Use pre-staged data/<sample>/ inputs only; never download from NCBI or SRA.")
        inputs.add_argument("--long-reads-file", help="Long-read filename within each sample directory (default: long_reads.fastq.gz).")
        inputs.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"),
                            help="Score only tools declared under this track this run (each tool's own "
                                 "track is still stamped correctly regardless); leave unset to score "
                                 "every enabled tool under its own correct track in one run.")
        inputs.add_argument("--decision-profile", choices=("accuracy_first", "amr_surveillance", "rapid_screening"),
                            help="Named decision_score weight set for operational recommendations (default: "
                                 "accuracy_first, today's original formula). A different profile only changes "
                                 "which tool ranks highest; it never changes which tools are eligible.")
        resources = command_parser.add_argument_group("resources and assembly")
        resources.add_argument("-t", "--threads", type=int, help="CPU threads per tool (default: config value, normally 4).")
        resources.add_argument("--memory-gb", type=int, help="SPAdes memory limit in GB (default: config value, normally 16).")
        resources.add_argument("--parallel-samples", type=int,
                               help="Samples to download/assemble/reconstruct/score concurrently "
                                    "(default: config value, normally 1 = sequential).")
        resources.add_argument("--parallel-tools", type=int,
                               help="Independent reconstruction tools to run concurrently per sample in "
                                    "stage 4 -- mob_recon, platon, plasmidspades, gplas2_external; "
                                    "gplas2_mob still always waits for mob_recon (default: config value, "
                                    "normally 1 = sequential).")
        resources.add_argument("--assembler", choices=("spades", "unicycler"), help="Short-read assembler.")
        resources.add_argument("--min-read-len", type=int, help="Discard reads shorter than this after fastp.")
        resources.add_argument("--minimap2-preset", help="minimap2 assembly preset (default: asm5).")
        resources.add_argument("--flye-read-type", choices=("nano-raw", "nano-hq", "pacbio-raw", "pacbio-hifi"), help="Flye technology for optional stage 7.")
        resources.add_argument("--trycycler-assembly-count", type=int,
                               help="Independent Flye assemblies Trycycler reconciles per sample "
                                    "(default: config value, normally 4). Higher is more robust but "
                                    "multiplies stage-7 runtime for trycycler_mob_recon proportionally.")
        tools = command_parser.add_argument_group("tools")
        for option, destination, label in (
            ("--mob-recon", "mob_recon", "Enable or disable MOB-suite reconstruction."),
            ("--platon", "platon", "Enable or disable Platon classification."),
            ("--plasmidspades", "plasmidspades", "Enable or disable plasmidSPAdes."),
            ("--gplas2-mob", "gplas2_mob", "Enable or disable gplas seeded by MOB-recon membership."),
            ("--gplas2-external", "gplas2_external", "Enable or disable gplas with external classifier TSVs."),
            ("--flye-mob-recon", "flye_mob_recon", "Enable or disable optional Flye plus MOB-Recon long-read reconstruction."),
            ("--plassembler", "plassembler", "Enable or disable optional Plassembler hybrid (long+short) plasmid assembly."),
            ("--hybracter-long", "hybracter_long", "Enable or disable optional Hybracter long-read-only assembly with plasmid recovery."),
            ("--hybracter-hybrid", "hybracter_hybrid", "Enable or disable optional Hybracter hybrid (long+short) assembly with plasmid recovery."),
            ("--trycycler-mob-recon", "trycycler_mob_recon", "Enable or disable optional Trycycler consensus long-read assembly plus MOB-Recon."),
            ("--genomad", "genomad", "Enable or disable optional geNomad ML classification."),
            ("--plasme", "plasme", "Enable or disable optional PLASMe alignment+transformer classification."),
            ("--plasgraph2", "plasgraph2", "Enable or disable optional plASgraph2 GNN classification (assembly graph)."),
            ("--rfplasmid", "rfplasmid", "Enable or disable optional RFPlasmid random-forest classification (assembly contigs)."),
            ("--plasmidhunter", "plasmidhunter", "Enable or disable optional PlasmidHunter gene-content Naive Bayes classification (assembly contigs)."),
            ("--plasmer", "plasmer", "Enable or disable optional Plasmer ensemble classification (assembly contigs; requires ~32GB RAM)."),
            ("--plascope", "plascope", "Enable or disable optional PlaScope Centrifuge classification (E. coli/Klebsiella only)."),
            ("--plasmidec", "plasmidec", "Enable or disable optional PlasmidEC majority-vote ensemble classification (eight species only)."),
        ):
            tools.add_argument(option, dest=destination, choices=("on", "off"), help=label)
        tools.add_argument("--tool", dest="user_tools", action="append", metavar="NAME",
                           help="Also benchmark a user-added tool (see `plasbench tools list`); repeat for several, "
                                "or give 'all'. Sets USER_TOOLS.")
        tools.add_argument("--force-rerun-tools", action="store_true",
                           help="Discard completed tool results and execute them again.")

    add_run_options(run_parser)
    add_run_options(report_parser)
    run_parser.add_argument("-m", "--mode", choices=("isolate", "metagenomics", "meta", "beta"), default="isolate",
                            help="Workflow mode (default: isolate). With --cohort bmock12, meta materializes/reuses the bundled physical control before scoring normalized community outputs.")
    run_parser.add_argument("-p", "--predictions-dir", type=Path,
                            help="Metagenomics only: directory holding <tool>/<community>.bins.tsv normalized outputs.")

    return parser


def network_commands(root):
    """{(command, sub): {"flag": str, "services": set}} from the `used_by` column of config/network_services.tsv.

    A used_by entry that starts with "plasbench " names a command: "plasbench upgrade", "plasbench tools add" (a sub-command),
    "plasbench validate-cohort --online" (only with that flag). Entries that are file paths are for test/test_network_declared.py."""
    from . import netcheck
    table = {}
    for row in netcheck.load_catalogue(Path(root) / "config" / netcheck.CATALOGUE_NAME):
        for token in (row.get("used_by") or "").split(";"):
            words = token.split()
            if len(words) < 2 or words[0] != "plasbench":
                continue
            flag = next((w for w in words[2:] if w.startswith("-")), "")
            sub_name = next((w for w in words[2:] if not w.startswith("-")), "")
            entry = table.setdefault((words[1], sub_name), {"flag": flag, "services": set()})
            entry["services"].add(row["service"])
    return table


def network_preflight(args, root):
    """Refuse an online-only command before it does anything when the services it needs are unreachable. Returns the message, or None.

    Only the cases that certainly go online are checked: an action that can be done from files on disk must not demand the internet
    (`run` and `check` decide that themselves, in stage 1 and scripts/00_setup.sh)."""
    command = args.command
    table = network_commands(root)
    sub_name = ""
    if command == "tools":
        sub_name = getattr(args, "tools_command", "") or ""
        source = str(getattr(args, "path", "") or "").replace("\\", "/")
        if sub_name == "add" and not re.match(r"^(https?|git|ssh):/|^git@", source):
            return None                      # a folder or manifest on disk
    elif command == "analysis":
        sub_name = getattr(args, "name", "") or ""
    elif command == "install-tools" and getattr(args, "profile", "") in ("list", "plan", "validate"):
        return None                          # registry inspection only
    entry = table.get((command, sub_name))
    if entry is None:
        return None
    if entry["flag"] and not getattr(args, entry["flag"].lstrip("-").replace("-", "_"), False):
        return None
    from . import netcheck
    try:
        netcheck.require(sorted(entry["services"]), action=f"plasbench {command}" + (f" {sub_name}" if sub_name else ""))
    except netcheck.NoInternet as exc:
        return exc.message
    return None


def net_command(args):
    from . import netcheck
    answer = netcheck.check(args.service or None)
    if args.json:
        print(json.dumps(answer, indent=2))
    else:
        print(netcheck.status_table(answer))
    return 0 if answer["state"] in ("online", "assumed_online") else 3


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Keep accepted shorthand spellings out of downstream control flow and
    # manifests. The stored mode is always the scientifically explicit name.
    if getattr(args, "mode", "") in {"meta", "beta"}:
        args.mode = "metagenomics"

    # See the note on the "stages" argument above: validated here rather than
    # via argparse's own `choices`.
    invalid_stages = [s for s in getattr(args, "stages", []) or [] if s not in VALID_STAGES]
    if invalid_stages:
        parser.error("argument stages: invalid choice: {} (choose from {})".format(
            ", ".join(repr(s) for s in invalid_stages),
            ", ".join(repr(s) for s in sorted(VALID_STAGES))))
    root = args.project_root
    # argparse does not apply ``type=project_root`` to a Path-valued default.
    # Without this explicit check, invoking the CLI from a random directory
    # failed later with a shell "file not found" message. The report opener is
    # deliberately standalone; every other command needs the release tree.
    if args.command == "net":
        raise SystemExit(net_command(args))
    if args.command != "open-report" and not is_project_root(root):
        parser.error(
            f"{root} is not a PlasBench release/source directory (scripts/run_all.sh missing). "
            "Run 'cd \"$PB\"' using the installation directory from the README, "
            "or pass --project-root /path/to/plasbench before the command."
        )
    problem = network_preflight(args, root)
    if problem:
        print(f"[plasbench] ERROR: {problem}", file=sys.stderr)
        raise SystemExit(3)
    if args.command == "ui":
        from .webui import serve
        serve(root, port=args.port, open_browser=not args.no_browser, tab=args.tab, new_instance=args.new_instance)
        return 0
    if args.command == "install-git":
        from . import install_git
        return install_git.main((["--force"] if args.force else []) + (["--dry-run"] if args.dry_run else []))
    if args.command == "desktop-icon":
        from . import desktop
        return desktop.main(["--project-root", str(root)] + (["--remove"] if args.remove else [])
                            + (["--no-desktop"] if args.no_desktop else []))
    if args.command == "demo":
        code = run([bash_command(), "test/run_demo.sh"], root)
    elif args.command == "open-report":
        report = args.report or (args.results_dir / "benchmark.report.html")
        open_report_in_browser(report)
        print(f"[plasbench] Opening report: {Path(report).resolve()}")
        code = 0
    elif args.command == "report-pdf":
        report = args.report or (args.results_dir / "benchmark.report.html")
        command = [sys.executable, str(root / "python" / "export_report_pdf.py"), "--report", str(report)]
        if args.out:
            command += ["--out", str(args.out)]
        code = run(command, root)
    elif args.command in ("status", "diagnose"):
        from . import studies
        if args.results_dir:
            results_dir = Path(args.results_dir)
        elif args.study:
            try:
                results_dir = studies.study_path(root, args.study) / "results"
            except ValueError as exc:
                parser.error(str(exc))
        else:
            listed = studies.list_studies(root)
            results_dir = (Path(listed[0]["path"]) / "results") if listed else (root / "results")
        command = [sys.executable, str(root / "python" / "run_status.py"), "--results-dir", str(results_dir)]
        record = {}
        try:
            record = json.loads((results_dir.parent / "study.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if record.get("data_dir"):
            command += ["--data-dir", str(record["data_dir"])]
        if args.command == "diagnose":
            command.append("--diagnose")
        if args.json:
            command.append("--json")
        if args.watch:
            command += ["--watch", str(args.watch)]
        code = run(command, root)
    elif args.command == "test":
        code = run([bash_command(), "test/run_tests.sh"], root)
    elif args.command == "upgrade":
        update_script = root / "update.sh"
        if not update_script.is_file():
            parser.error(f"upgrade script not found at {update_script}")
        command = [bash_command(), "update.sh"]
        if args.yes:
            command.append("--yes")
        if args.refresh_tools:
            command.append("--refresh-tools")
        code = run(command, root)
    elif args.command == "check":
        command = [bash_command(), "scripts/00_setup.sh"]
        if args.yes:
            command.append("--yes")
        code = run(command, root)
    elif args.command == "init-local":
        data_dir = args.data_dir or configured_data_dir(root)
        command = [sys.executable, "python/init_local_sample.py",
                   "--sample", args.sample, "--reads-1", args.reads_1, "--reads-2", args.reads_2,
                   "--data-dir", str(data_dir), "--samples", args.samples,
                   "--accession", args.accession, "--link", args.link]
        if args.reference:
            command.extend(["--reference", args.reference])
        if args.sequence_report:
            command.extend(["--sequence-report", args.sequence_report])
        if args.prefix:
            command.extend(["--prefix", args.prefix])
        if args.force:
            command.append("--force")
        code = run(command, root)

    elif args.command == "intake":
        extra = list(args.intake_args)
        if args.action in ("stage", "check") and "--data-dir" not in extra and "-h" not in extra and "--help" not in extra:
            extra += ["--data-dir", str(configured_data_dir(root))]
        code = run([sys.executable, "python/intake.py", args.action, *extra], root)
    elif args.command == "validate-cohort":
        command = [sys.executable, "python/validate_cohort.py", "--samples", str(args.samples)]
        if args.online:
            command.append("--online")
        if args.email:
            command.extend(["--email", args.email])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        if args.write_lock:
            command.extend(["--write-lock", str(args.write_lock)])
        if args.verify_lock:
            command.extend(["--verify-lock", str(args.verify_lock)])
        if args.ledger:
            command.extend(["--ledger", str(args.ledger)])
        code = run(command, root)
    elif args.command == "validate-orthogonal-evidence":
        command = [sys.executable, "python/validate_orthogonal_evidence.py", "--evidence", str(args.evidence)]
        if args.out:
            command.extend(["--out", str(args.out)])
        code = run(command, root)
    elif args.command == "analysis":
        if args.list or not args.name:
            for name, (script, summary) in sorted(ANALYSES.items()):
                print(f"{name:26s} {summary}  [{script}]")
            code = 0
        else:
            code = run([sys.executable, f"python/{ANALYSES[args.name][0]}", *args.analysis_args], root)
    elif args.command == "derive-amr-truth":
        code = run([sys.executable, "python/derive_amr_truth.py", "--features", str(args.features),
                    "--truth", str(args.truth), "--out", str(args.out)], root)
    elif args.command == "promote-amr-truth":
        command = [sys.executable, "python/promote_amr_truth.py", "--draft", str(args.draft), "--truth", str(args.truth), "--reviewed-by", args.reviewed_by,
                   "--database-version", args.database_version]
        if args.out:
            command.extend(["--out", str(args.out)])
        if args.confirm_reviewed:
            command.append("--confirm-reviewed")
        if args.force:
            command.append("--force")
        code = run(command, root)
    elif args.command == "audit-truth-labels":
        code = run([sys.executable, "python/audit_truth_labels.py", "--data-dir", str(args.data_dir),
                    "--out", str(args.out)], root)
    elif args.command == "curate-cohort":
        command = [sys.executable, "python/curate_cohort.py", "--candidates", str(args.candidates),
                   "--out-dir", str(args.out_dir)]
        if args.email:
            command.extend(["--email", args.email])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        if args.ledger:
            command.extend(["--ledger", str(args.ledger)])
        code = run(command, root)
    elif args.command == "build-ledger":
        command = [sys.executable, "python/build_accession_ledger.py",
                   "--cohorts-dir", str(args.cohorts_dir), "--out", str(args.out)]
        code = run(command, root)
    elif args.command == "prepare-contribution":
        command = [sys.executable, "python/prepare_contribution.py", "--cohort", args.cohort,
                   "--new-rows", str(args.new_rows), "--scores", str(args.scores),
                   "--cohorts-dir", str(args.cohorts_dir)]
        if args.tool_status:
            command.extend(["--tool-status", str(args.tool_status)])
        if args.branch_label:
            command.extend(["--branch-label", args.branch_label])
        if args.email:
            command.extend(["--email", args.email])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        code = run(command, root)
    elif args.command == "discover-cohort":
        command = [sys.executable, "python/discover_ncbi_cohort.py", "--out-dir", str(args.out_dir),
                   "--max-assemblies", str(args.max_assemblies)]
        for organism in args.organism:
            command.extend(["--organism", organism])
        for country in args.country:
            command.extend(["--country", country])
        if args.negative_controls:
            command.append("--negative-controls")
        if args.email:
            command.extend(["--email", args.email])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        code = run(command, root)
    elif args.command == "collect-truth-provenance":
        command = [sys.executable, "python/collect_truth_provenance.py", "--samples", str(args.samples),
                   "--evidence-out", str(args.evidence_out)]
        if args.sheet_out:
            command.extend(["--sheet-out", str(args.sheet_out)])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        code = run(command, root)
    elif args.command == "discover-design-cohort":
        command = [sys.executable, "python/discover_design_cohort.py", "--out", str(args.out),
                   "--evidence-out", str(args.evidence_out), "--ledger", str(args.ledger),
                   "--target-clusters", str(args.target_clusters), "--max-reports", str(args.max_reports),
                   "--max-checks", str(args.max_checks)]
        for species in args.species:
            command.extend(["--species", species])
        if args.existing:
            command.extend(["--existing", str(args.existing)])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        code = run(command, root)
    elif args.command == "review-candidates":
        code = run([sys.executable, "python/review_candidate_cohort.py", "--candidates", str(args.candidates), "--out-dir", str(args.out_dir), "--max-per-bioproject", str(args.max_per_bioproject), "--max-per-organism", str(args.max_per_organism)], root)
    elif args.command == "import-contributed-cohort":
        command = [sys.executable, "python/import_contributed_cohort.py", "--out-dir", str(args.out_dir),
                   "--released-after", args.released_after, "--released-before", args.released_before,
                   "--min-clusters", str(args.min_clusters), "--max-clusters-per-species", str(args.max_clusters_per_species),
                   "--seed", str(args.seed)]
        if args.pool:
            command.extend(["--pool", str(args.pool)])
        if args.date_basis:
            command.extend(["--date-basis", args.date_basis])
        for flag, values in (("--species", args.species), ("--country", args.country), ("--region", args.region)):
            for value in values:
                command.extend([flag, value])
        if args.allow_short_read_first:
            command.append("--allow-short-read-first")
        if args.arm:
            command.extend(["--arm", args.arm])
        code = run(command, root)
    elif args.command == "compare-published":
        command = [sys.executable, "python/compare_published.py", "--results-dir", str(args.results_dir), "--samples", str(args.samples)]
        for flag, value in (("--scores", args.scores), ("--out-prefix", args.out_prefix), ("--html", args.html)):
            if value:
                command.extend([flag, str(value)])
        code = run(command, root)
    elif args.command == "build-publication-cohorts":
        command = [sys.executable, "python/build_publication_cohorts.py", "--out-dir", str(args.out_dir)]
        for item in args.resolved:
            command.extend(["--resolved", str(item)])
        if args.audit:
            command.extend(["--audit", str(args.audit)])
        code = run(command, root)
    elif args.command == "selection-report":
        command = [sys.executable, "python/build_selection_report.py", "--name", args.name, "--sheet", str(args.sheet),
                   "--importer-dir", str(args.importer_dir), "--resolver-dir", str(args.resolver_dir), "--out", str(args.out)]
        for flag, value in (("--importer-command", args.importer_command), ("--resolver-command", args.resolver_command), ("--validate-command", args.validate_command)):
            if value:
                command.extend([flag, value])
        code = run(command, root)
    elif args.command == "resolve-contributed-cohort":
        command = [sys.executable, "python/resolve_contributed_cohort.py", "--out-dir", str(args.out_dir),
                   "--target-per-species", str(args.target_per_species), "--min-recent", str(args.min_recent)]
        for path in args.candidates:
            command.extend(["--candidates", str(path)])
        if args.cache:
            command.extend(["--cache", str(args.cache)])
        code = run(command, root)
    elif args.command == "install-conda":
        command = [bash_command(), "env/bootstrap_conda.sh"]
        if args.yes:
            command.append("--yes")
        if args.prefix:
            command.extend(["--prefix", str(args.prefix)])
        code = run(command, root)
    elif args.command == "install-tools":
        command = [bash_command(), "env/install_tools.sh", "--env", args.env]
        if args.yes:
            command.append("--yes")
        command.append(args.profile)
        code = run(command, root)
    elif args.command == "tools":
        if args.tools_command == "install":
            code = run([bash_command(), "env/install_tools.sh", "--env", args.env, args.name], root)
        else:
            command = [sys.executable, "python/user_tools.py", args.tools_command]
            if args.tools_command in ("validate", "show", "new") and getattr(args, "name", None):
                command.append(args.name)
            if args.tools_command == "new" and args.dir:
                command.extend(["--dir", str(args.dir)])
            if args.tools_command == "add":
                command.append(str(args.path.resolve()))
            code = run(command, root)
    elif args.command == "candidate-dataset":
        command = [sys.executable, "python/build_candidate_quality_dataset.py", "--scores", str(args.scores),
                   "--sample-sheet", str(args.samples), "--results-dir", str(args.results_dir),
                   "--out-prefix", str(args.out_prefix)]
        if args.tool_status:
            command.extend(["--tool-status", str(args.tool_status)])
        code = run(command, root)
    elif args.command == "import-external-benchmark":
        command = [sys.executable, "python/import_external_benchmark.py", "--predictions", str(args.predictions),
                   "--out-dir", str(args.out_dir), "--source-repository", args.source_repository,
                   "--source-revision", args.source_revision, "--citation", args.citation]
        if args.ani:
            command.extend(["--ani", str(args.ani)])
        code = run(command, root)
    elif args.command == "depth-ladder":
        code = run([sys.executable, "python/make_depth_ladder.py", "--samples", str(args.samples),
                    "--data-dir", str(args.data_dir), "--out-dir", str(args.out_dir),
                    "--depths", args.depths, "--seed", str(args.seed)], root)
    elif args.command == "depth-report":
        code = run([sys.executable, "python/summarize_depth_ladder.py", "--scores", str(args.scores),
                    "--manifest", str(args.manifest), "--out-prefix", str(args.out_prefix),
                    "--metric", args.metric], root)
    elif args.command == "read-quality-ladder":
        code = run([sys.executable, "python/make_read_quality_ladder.py", "--samples", str(args.samples),
                    "--data-dir", str(args.data_dir), "--out-dir", str(args.out_dir),
                    "--rungs", args.rungs], root)
    elif args.command == "read-quality-report":
        code = run([sys.executable, "python/summarize_read_quality_ladder.py", "--scores", str(args.scores),
                    "--manifest", str(args.manifest), "--out-prefix", str(args.out_prefix),
                    "--metric", args.metric], root)
    elif args.command == "select-candidates":
        command = [sys.executable, "python/select_operational_method.py", "--scores", str(args.scores),
                   "--sample-sheet", str(args.samples), "--results-dir", str(args.results_dir),
                   "--out-prefix", str(args.out_prefix), "--min-samples", str(args.min_samples),
                   "--min-coverage", str(args.min_coverage), "--analysis-track", args.analysis_track]
        if args.tool_status:
            command.extend(["--tool-status", str(args.tool_status)])
        code = run(command, root)
    elif args.command == "select-unknown":
        command = [sys.executable, "python/select_unknown_sample.py", "--recommendations", str(args.recommendations),
                   "--sample-id", args.sample_id, "--results-dir", str(args.results_dir),
                   "--organism", args.organism, "--gram-group", args.gram_group,
                   "--analysis-track", args.analysis_track]
        if args.out:
            command.extend(["--out", str(args.out)])
        code = run(command, root)
    elif args.command == "reconstruct":
        command = [bash_command(), "scripts/08_operational_reconstruct.sh",
                   "--sample", args.sample, "--sra", args.sra,
                   "--organism", args.organism, "--gram-group", args.gram_group,
                   "--analysis-track", args.analysis_track]
        if args.tool:
            command.extend(["--tool", args.tool])
        if args.recommendations:
            command.extend(["--recommendations", str(args.recommendations)])
        if args.recommendation_model:
            command.extend(["--recommendation-model", str(args.recommendation_model)])
        if args.read_depth_x is not None:
            command.extend(["--read-depth-x", str(args.read_depth_x)])
        env = {}
        for argument, variable in (("data_dir", "DATA_DIR"), ("results_dir", "RESULTS_DIR"), ("log_dir", "LOG_DIR")):
            value = getattr(args, argument)
            if value:
                env[variable] = value.resolve().as_posix()
        code = run(command, root, env)
    elif args.command == "docs":
        print_docs(root, args.topic)
        code = 0
    elif args.command == "concept-note":
        print_concept_note(root)
        code = 0
    elif args.command in {"metagenomics", "meta", "beta"}:
        command = [sys.executable, "python/metagenomics.py", args.action, "--manifest", str(args.manifest)]
        if args.action == "validate" and args.release_ready:
            command.append("--release-ready")
        if args.action == "score":
            if not args.predictions_dir or not args.results_dir:
                parser.error("metagenomics score requires --predictions-dir and --results-dir")
            command.extend(["--predictions-dir", str(args.predictions_dir), "--out-dir", str(args.results_dir)])
        elif args.action == "report":
            if not args.results_dir:
                parser.error("metagenomics report requires --results-dir")
            command.extend(["--results-dir", str(args.results_dir)])
        code = run(command, root)
        if code == 0 and args.action in {"score", "report"}:
            announce_report(args.results_dir / "metagenomics.report.html", args.open_report, not args.no_report_prompt)
    elif args.command == "audit-meta-cohort":
        command = [sys.executable, "python/audit_metagenomic_cohort.py", "--manifest", str(args.manifest), "--out", str(args.out)]
        if args.release_ready:
            command.append("--release-ready")
        code = run(command, root)
    elif args.command == "design-meta-synthetic":
        code = run([sys.executable, "python/design_synthetic_communities.py", "--members", str(args.members),
                    "--out-dir", str(args.out_dir), "--seed", str(args.seed), "--simulator", args.simulator,
                    "--simulator-version", args.simulator_version, "--container-image", args.container_image,
                    "--container-digest", args.container_digest], root)
    elif args.command == "validate-meta-intake":
        code = run([sys.executable, "python/validate_metagenomic_intake.py", "--intake", str(args.intake)], root)
    elif args.command == "materialize-meta-bmock12":
        code = run([sys.executable, "python/materialize_bmock12_truth.py", "--out-dir", str(args.out_dir),
                    "--source-manifest", str(args.source_manifest), "--retries", str(args.retries)], root)
    elif args.command == "normalize-meta-classifier":
        command = [sys.executable, "python/normalize_metagenomic_classifier.py", "--tool", args.tool,
                   "--input", str(args.input), "--out", str(args.out), "--threshold", str(args.threshold)]
        code = run(command, root)
    elif args.command == "import-mobilome-evidence":
        command = [sys.executable, "python/import_mobilome_evidence.py", "--gff", str(args.gff),
                   "--community", args.community, "--sample", args.sample, "--out", str(args.out)]
        code = run(command, root)
    elif args.command == "run" and args.mode == "metagenomics":
        if not args.predictions_dir:
            parser.error("plasbench run --mode meta requires --predictions-dir containing normalized community outputs")
        if args.cohort:
            if args.cohort == "bmock12":
                if args.write_script:
                    parser.error("--write-script with --mode meta --cohort bmock12 is not supported yet; run the command directly so the verified control can be materialized first")
                control_dir = configured_data_dir(root) / "metagenomics" / "controls"
                source_manifest = root / "config" / "metagenomic_truth_sources.tsv"
                print(f"[plasbench] Preparing the BMock12 physical truth control in {control_dir}")
                code = run([sys.executable, "python/materialize_bmock12_truth.py", "--out-dir", str(control_dir),
                            "--source-manifest", str(source_manifest)], root)
                if code != 0:
                    raise SystemExit(code)
                args.samples = control_dir / "bmock12" / "metagenomics-bmock12-verified.tsv"
                print(f"[plasbench] Using verified community manifest: {args.samples}")
            else:
                cohort_path = root / "cohorts" / f"metagenomics-{args.cohort}.tsv"
                if not cohort_path.is_file():
                    available = sorted(path.stem.removeprefix("metagenomics-") for path in (root / "cohorts").glob("metagenomics-*.tsv"))
                    parser.error(f"no such metagenomic cohort '{args.cohort}'; available: {', '.join(available) if available else 'none'}")
                args.samples = cohort_path
        if not args.samples:
            parser.error("plasbench run --mode meta requires --samples or --cohort bmock12")
        if args.study and args.results_dir:
            parser.error("give --study or --results-dir, not both")
        if getattr(args, "study_location", None) and args.results_dir:
            parser.error("--study-location needs a study folder: give it without --results-dir")
        if args.results_dir:
            meta_results = args.results_dir
        else:
            from . import studies
            try:
                study_name = args.study or studies.default_name(args.cohort, args.samples, meta=True)
                folder = studies.prepare(root, study_name, args.samples, args.cohort, argv or sys.argv[1:], location=getattr(args, "study_location", None))
            except ValueError as exc:
                parser.error(str(exc))
            meta_results = folder / "results"
            print(f"[plasbench] Study folder: {folder}")
        command = [sys.executable, "python/metagenomics.py", "score", "--manifest", str(args.samples),
                   "--predictions-dir", str(args.predictions_dir), "--out-dir", str(meta_results)]
        if args.write_script:
            write_run_script(args.write_script, root, command, {})
            code = 0
        else:
            code = run(command, root)
        if code == 0 and not args.write_script:
            announce_report(meta_results / "metagenomics.report.html", args.open_report, not args.no_report_prompt)
    else:
        if args.cohort:
            from . import sheetcheck
            cohort_path = root / "cohorts" / f"{args.cohort}.tsv"
            # Only real benchmark sheets are offered: the accession ledger and the metagenomic tables sit in cohorts/ too.
            available = sheetcheck.cohort_sheets(root / "cohorts") if (root / "cohorts").is_dir() else []
            if not cohort_path.is_file():
                parser.error(
                    f"no such cohort '{args.cohort}' ({cohort_path} not found); "
                    f"available: {', '.join(available) if available else 'none'}"
                )
            # A file that is not a benchmark sheet (the accession ledger, for one) is refused here, once, before a study folder is made,
            # instead of failing stage 0 with one error per row. Only what is certainly not a cohort is refused (the ledger, a table with no sample_id);
            # whether a sheet has the curated columns stays stage 0's decision, because REQUIRE_CURATED_METADATA can be switched off in config/local.env.
            problem = sheetcheck.refusal(cohort_path, available)
            if problem:
                parser.error(problem)
            args.samples = cohort_path
        elif args.samples and Path(args.samples).is_file():
            from . import sheetcheck
            if sheetcheck.is_ledger(sheetcheck.header(args.samples)):
                parser.error(sheetcheck.refusal(args.samples, sheetcheck.cohort_sheets(root / "cohorts") if (root / "cohorts").is_dir() else []))
        if args.study and args.results_dir:
            parser.error("give --study or --results-dir, not both")
        if getattr(args, "keep_data_in_study", False) and args.data_dir:
            parser.error("give --keep-data-in-study or --data-dir, not both")
        if getattr(args, "keep_data_in_study", False) and args.results_dir:
            parser.error("--keep-data-in-study needs a study folder: give it without --results-dir")
        if getattr(args, "study_location", None) and args.results_dir:
            parser.error("--study-location needs a study folder: give it without --results-dir")
        # Every run keeps what it produces in its own study folder (plasbench/studies.py); downloads stay shared.
        # `report` uses a study only when named, so `report --results-dir DIR` and the old layout keep working.
        study_tmp = None
        # An explicit RESULTS_DIR in the environment (a script, a container) is honoured like --results-dir.
        explicit_results = bool(os.environ.get("RESULTS_DIR")) and not args.study
        if not args.results_dir and not explicit_results and (args.study or args.command == "run"):
            from . import studies
            try:
                study_name = args.study or studies.default_name(args.cohort, args.samples)
                folder = studies.prepare(root, study_name, args.samples if args.command == "run" else None,
                                         args.cohort, argv or sys.argv[1:], location=getattr(args, "study_location", None))
                if args.command == "run":
                    data_folder, data_note = studies.resolve_data(root, folder, getattr(args, "keep_data_in_study", False), args.data_dir, configured_data_dir(root))
                    if data_folder is not None:
                        args.data_dir = data_folder
            except ValueError as exc:
                parser.error(str(exc))
            if args.command == "run" and data_note:
                print(f"[plasbench] {data_note}")
            args.results_dir = folder / "results"
            if not args.log_dir:
                args.log_dir = folder / "logs"
            study_tmp = (folder / "tmp").resolve().as_posix()
            print(f"[plasbench] Study folder: {folder}")
        if getattr(args, "independent_truth_only", False):
            from . import sheet_limit
            source_sheet = args.samples or Path(os.environ.get("SAMPLE_SHEET") or root / "config" / "accessions.tsv")
            try:
                only = sheet_limit.independent_truth_only(source_sheet, args.results_dir or Path(os.environ.get("RESULTS_DIR") or root / "results"))
            except ValueError as exc:
                parser.error(str(exc))
            args.samples = only.path
            print(f"[plasbench] --independent-truth-only: running {only.kept} of {only.total} isolates of {Path(source_sheet).name} (copy: {only.path})")
        if getattr(args, "max_isolates", None) is not None:
            from . import sheet_limit
            source_sheet = args.samples or Path(os.environ.get("SAMPLE_SHEET") or root / "config" / "accessions.tsv")
            limit_dir = args.results_dir or Path(os.environ.get("RESULTS_DIR") or root / "results")
            try:
                limited = sheet_limit.limit_sheet(source_sheet, args.max_isolates, limit_dir, args.isolate_order)
            except ValueError as exc:
                parser.error(str(exc))
            if limited.path:
                args.samples = limited.path
                how = "a balanced selection" if ".balanced_" in limited.path.name else "the first rows, in file order"
                print(f"[plasbench] --max-isolates {args.max_isolates}: running {limited.kept} of {limited.total} "
                      f"isolates of {Path(source_sheet).name}, {how} (copy: {limited.path})")
            else:
                print(f"[plasbench] --max-isolates {args.max_isolates}: {Path(source_sheet).name} has only {limited.total}; running all of them")
        env = {}
        path_options = {
            "samples": "SAMPLE_SHEET", "data_dir": "DATA_DIR", "results_dir": "RESULTS_DIR",
            "log_dir": "LOG_DIR", "platon_db": "PLATON_DB", "genomad_db": "GENOMAD_DB", "plasme_db": "PLASME_DB",
            "plasgraph2_model_dir": "PLASGRAPH2_MODEL_DIR",
            "gplas2_external_predictions_dir": "GPLAS2_EXTERNAL_PREDICTIONS_DIR",
        }
        for argument, variable in path_options.items():
            value = getattr(args, argument)
            if value:
                # .as_posix() (not str()) so a Windows drive-letter path like
                # F:\foo becomes F:/foo: bash interprets backslashes as escape
                # characters, so an env var carrying raw Windows separators
                # breaks the moment scripts/*.sh use it as a path. A no-op on
                # POSIX hosts, where paths already use forward slashes.
                env[variable] = value.resolve().as_posix()
        if study_tmp:
            env["TMP_DIR"] = study_tmp
        if args.local_inputs:
            env["LOCAL_INPUTS_ONLY"] = "1"
        if args.long_reads_file:
            env["LONG_READS_FILE"] = args.long_reads_file
        if args.analysis_track:
            env["ANALYSIS_TRACK_FILTER"] = args.analysis_track
        if args.decision_profile:
            env["DECISION_PROFILE"] = args.decision_profile
        positive_options = {"threads": "THREADS", "memory_gb": "MEMORY_GB", "min_read_len": "MIN_READ_LEN",
                            "parallel_samples": "MAX_PARALLEL_SAMPLES", "parallel_tools": "MAX_PARALLEL_TOOLS",
                            "trycycler_assembly_count": "TRYCYCLER_ASSEMBLY_COUNT"}
        for argument, variable in positive_options.items():
            value = getattr(args, argument)
            if value is not None:
                if value < 1:
                    parser.error(f"--{argument.replace('_', '-')} must be positive")
                env[variable] = str(value)
        for argument, variable in (("assembler", "ASSEMBLER"), ("minimap2_preset", "MINIMAP2_PRESET"), ("flye_read_type", "FLYE_READ_TYPE")):
            value = getattr(args, argument)
            if value:
                env[variable] = value
        for argument, variable in (("mob_recon", "RUN_MOB_RECON"), ("platon", "RUN_PLATON"),
                                   ("plasmidspades", "RUN_PLASMIDSPADES"),
                                   ("gplas2_mob", "RUN_GPLAS2_MOB"), ("gplas2_external", "RUN_GPLAS2_EXTERNAL"),
                                   ("flye_mob_recon", "RUN_FLYE_MOB_RECON"),
                                   ("plassembler", "RUN_PLASSEMBLER"),
                                   ("hybracter_long", "RUN_HYBRACTER_LONG"),
                                   ("hybracter_hybrid", "RUN_HYBRACTER_HYBRID"),
                                   ("trycycler_mob_recon", "RUN_TRYCYCLER_MOB_RECON"),
                                   ("genomad", "RUN_GENOMAD"),
                                   ("plasme", "RUN_PLASME"),
                                   ("plasgraph2", "RUN_PLASGRAPH2"),
                                   ("rfplasmid", "RUN_RFPLASMID"),
                                   ("plasmidhunter", "RUN_PLASMIDHUNTER"),
                                   ("plasmer", "RUN_PLASMER"),
                                   ("plascope", "RUN_PLASCOPE"),
                                   ("plasmidec", "RUN_PLASMIDEC")):
            value = getattr(args, argument)
            if value:
                env[variable] = "1" if value == "on" else "0"
        if getattr(args, "user_tools", None):
            env["USER_TOOLS"] = ",".join(name.strip() for value in args.user_tools for name in value.split(",") if name.strip())
        if args.force_rerun_tools:
            env["FORCE_RERUN_TOOLS"] = "1"
        stages = ["6"] if args.command == "report" else args.stages
        if args.write_script:
            # A generic "bash", not bash_command()'s Windows-bash.exe-path
            # lookup: that lookup exists only to invoke bash reliably FROM
            # Python's subprocess, which does not apply once the generated
            # file is already itself a bash script.
            write_run_script(args.write_script, root, ["bash", "scripts/run_all.sh", *stages], env)
            code = 0
        else:
            code = run([bash_command(), "scripts/run_all.sh", *stages], root, env)
    # A report is an end product, not an unadvertised file. Keep this handoff
    # in the Python CLI so demo, local-isolate, and cohort benchmark workflows
    # behave identically even though they use different Bash entry points.
    if code == 0 and args.command == "demo":
        announce_report(root / "results_demo" / "benchmark.report.html", args.open_report,
                        not args.no_report_prompt)
    elif code == 0 and args.command in {"run", "report"} and not args.write_script and getattr(args, "mode", "isolate") == "isolate":
        stages = ["6"] if args.command == "report" else (args.stages or ["0", "1", "2", "3", "4", "7", "5", "6"])
        if "6" in stages:
            results_dir = args.results_dir or (root / "results")
            announce_report(results_dir / "benchmark.report.html", args.open_report,
                            not args.no_report_prompt)
    raise SystemExit(code)
