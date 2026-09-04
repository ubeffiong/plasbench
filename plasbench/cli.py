"""Command-line entry point for the source checkout and container image."""

import argparse
import os
import shutil
import subprocess
import sys
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


def run(command, root, env=None):
    merged_env = os.environ.copy()
    # The Bash configuration derives PROJECT_ROOT from its script location. Do
    # not inject a Windows path here: Git Bash would interpret its backslashes.
    if env:
        merged_env.update(env)
    return subprocess.run(command, cwd=root, env=merged_env, check=False).returncode


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


def print_concept_note(root):
    """Print the non-technical project concept note from the source checkout."""
    note = root / "docs" / "CONCEPT_NOTE.md"
    if not note.is_file():
        raise SystemExit(f"ERROR: concept note not found: {note}")
    print(note.read_text(encoding="utf-8"), end="")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="plasbench",
        description="PlasBench: benchmark plasmid-reconstruction tools against complete references.",
        epilog="Examples:\n"
               "  plasbench install-tools core\n"
               "  plasbench install-tools all\n"
               "  plasbench demo\n"
               "  plasbench run --samples samples.tsv --threads 8\n"
               "  plasbench run 3 4 5 6 --platon off --assembler unicycler\n"
               "  plasbench select-candidates --scores results/scores.tsv --samples config/accessions.tsv --results-dir results --out-prefix results/benchmark\n"
               "  plasbench reconstruct --sample new_isolate_01 --sra SRR12345678\n"
               "  plasbench report --results-dir results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"plasbench {__version__}")
    parser.add_argument("--project-root", type=project_root, default=Path.cwd(),
                        help="PlasBench source checkout (default: current directory).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Run the offline synthetic scoring and report demo.")
    sub.add_parser("test", help="Run the complete offline regression suite.")
    sub.add_parser("check", help="Check configured runtime dependencies.")
    cohort_parser = sub.add_parser("validate-cohort", help="Validate a cohort schema or verify its NCBI-linked pairs.")
    cohort_parser.add_argument("--samples", type=Path, required=True, help="Cohort TSV to validate.")
    cohort_parser.add_argument("--online", action="store_true", help="Verify NCBI assembly/SRA linkage and library metadata.")
    cohort_parser.add_argument("--email", help="Contact email sent to NCBI E-utilities.")
    cohort_parser.add_argument("--api-key", help="NCBI API key; defaults to NCBI_API_KEY when omitted.")
    cohort_parser.add_argument("--write-lock", type=Path, help="Write NCBI verification evidence as JSON; requires --online.")
    cohort_parser.add_argument("--verify-lock", type=Path, help="Require a verification lock that matches the cohort TSV.")
    curate_parser = sub.add_parser("curate-cohort", help="Strictly screen candidate assembly/SRA pairs and write accepted/rejected tables.")
    curate_parser.add_argument("--candidates", type=Path, required=True)
    curate_parser.add_argument("--out-dir", type=Path, required=True)
    curate_parser.add_argument("--email")
    curate_parser.add_argument("--api-key")
    discover_parser = sub.add_parser("discover-cohort", help="Discover strict assembly/paired-Illumina candidate pairs from NCBI.")
    discover_parser.add_argument("--organism", action="append", required=True, help="Scientific name; repeat for each taxon.")
    discover_parser.add_argument("--out-dir", type=Path, required=True)
    discover_parser.add_argument("--country", action="append", default=[],
                                 help="Require deposited BioSample geo_loc_name to contain this country/place; repeat as needed.")
    discover_parser.add_argument("--max-assemblies", type=int, default=30)
    discover_parser.add_argument("--email")
    discover_parser.add_argument("--api-key")
    review_parser = sub.add_parser("review-candidates", help="Create an additive, non-release balanced shortlist from NCBI candidates.")
    review_parser.add_argument("--candidates", type=Path, required=True)
    review_parser.add_argument("--out-dir", type=Path, required=True)
    review_parser.add_argument("--max-per-bioproject", type=int, default=3)
    review_parser.add_argument("--max-per-organism", type=int, default=8)
    install_parser = sub.add_parser("install-tools", help="Install an optional bioinformatics dependency profile.")
    install_parser.add_argument("profile", nargs="?", default="core", help="locked, core, assembly, reconstruction, long-read, annotation, annotation-prokka, all, or a conda package name.")
    install_parser.add_argument("--env", default="plasbench", help="Conda/mamba environment name (default: plasbench).")
    docs_parser = sub.add_parser("docs", help="Print the comprehensive user guide or a topic.")
    docs_parser.add_argument("--topic", choices=("all", *DOC_TOPICS), default="all",
                             help="Guide topic to print (default: all).")
    sub.add_parser("concept-note", help="Print the non-technical researcher and donor concept note.")
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
    reconstruct_parser.add_argument("--tool", choices=("mob_recon", "platon", "plasmidspades", "gplas2_mob", "gplas2_external"),
                                    help="Run exactly this tool, skipping the benchmark recommendation lookup.")
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
    run_parser = sub.add_parser("run", help="Run the full benchmark or selected stages.")
    run_parser.add_argument("stages", nargs="*", choices=[str(i) for i in range(8)],
                            help=f"Optional {STAGE_HELP}")

    def add_run_options(command_parser):
        inputs = command_parser.add_argument_group("inputs and outputs")
        inputs.add_argument("--samples", type=Path, help="Sample-sheet TSV; defaults to config/accessions.tsv.")
        inputs.add_argument("--data-dir", type=Path, help="Directory for downloaded references, reads, and assemblies.")
        inputs.add_argument("--results-dir", type=Path, help="Directory for predictions, scores, and reports.")
        inputs.add_argument("--log-dir", type=Path, help="Directory for tool and mapping logs.")
        inputs.add_argument("--platon-db", type=Path, help="Path to the installed Platon database.")
        inputs.add_argument("--gplas2-external-predictions-dir", type=Path,
                            help="Directory containing <sample>.tsv external gplas2 classifier files.")
        inputs.add_argument("--local-inputs", action="store_true",
                            help="Use pre-staged data/<sample>/ inputs only; never download from NCBI or SRA.")
        inputs.add_argument("--long-reads-file", help="Long-read filename within each sample directory (default: long_reads.fastq.gz).")
        inputs.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"),
                            help="Label score and report rows for a separate read-technology track.")
        resources = command_parser.add_argument_group("resources and assembly")
        resources.add_argument("--threads", type=int, help="CPU threads per tool (default: config value, normally 4).")
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
        tools = command_parser.add_argument_group("tools")
        for option, destination, label in (
            ("--mob-recon", "mob_recon", "Enable or disable MOB-suite reconstruction."),
            ("--platon", "platon", "Enable or disable Platon classification."),
            ("--plasmidspades", "plasmidspades", "Enable or disable plasmidSPAdes."),
            ("--gplas2-mob", "gplas2_mob", "Enable or disable gplas seeded by MOB-recon membership."),
            ("--gplas2-external", "gplas2_external", "Enable or disable gplas with external classifier TSVs."),
            ("--flye-mob-recon", "flye_mob_recon", "Enable or disable optional Flye plus MOB-Recon long-read reconstruction."),
        ):
            tools.add_argument(option, dest=destination, choices=("on", "off"), help=label)
        tools.add_argument("--force-rerun-tools", action="store_true",
                           help="Discard completed tool results and execute them again.")

    add_run_options(run_parser)
    add_run_options(report_parser)

    args = parser.parse_args(argv)
    root = args.project_root
    if args.command == "demo":
        code = run([bash_command(), "test/run_demo.sh"], root)
    elif args.command == "test":
        code = run([bash_command(), "test/run_tests.sh"], root)
    elif args.command == "check":
        code = run([bash_command(), "scripts/run_all.sh", "0"], root)
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
        code = run(command, root)
    elif args.command == "curate-cohort":
        command = [sys.executable, "python/curate_cohort.py", "--candidates", str(args.candidates),
                   "--out-dir", str(args.out_dir)]
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
        if args.email:
            command.extend(["--email", args.email])
        if args.api_key:
            command.extend(["--api-key", args.api_key])
        code = run(command, root)
    elif args.command == "review-candidates":
        code = run([sys.executable, "python/review_candidate_cohort.py", "--candidates", str(args.candidates), "--out-dir", str(args.out_dir), "--max-per-bioproject", str(args.max_per_bioproject), "--max-per-organism", str(args.max_per_organism)], root)
    elif args.command == "install-tools":
        code = run([bash_command(), "env/install_tools.sh", "--env", args.env, args.profile], root)
    elif args.command == "depth-ladder":
        code = run([sys.executable, "python/make_depth_ladder.py", "--samples", str(args.samples),
                    "--data-dir", str(args.data_dir), "--out-dir", str(args.out_dir),
                    "--depths", args.depths, "--seed", str(args.seed)], root)
    elif args.command == "depth-report":
        code = run([sys.executable, "python/summarize_depth_ladder.py", "--scores", str(args.scores),
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
        env = {}
        for argument, variable in (("data_dir", "DATA_DIR"), ("results_dir", "RESULTS_DIR"), ("log_dir", "LOG_DIR")):
            value = getattr(args, argument)
            if value:
                env[variable] = str(value.resolve())
        code = run(command, root, env)
    elif args.command == "docs":
        print_docs(root, args.topic)
        code = 0
    elif args.command == "concept-note":
        print_concept_note(root)
        code = 0
    else:
        env = {}
        path_options = {
            "samples": "SAMPLE_SHEET", "data_dir": "DATA_DIR", "results_dir": "RESULTS_DIR",
            "log_dir": "LOG_DIR", "platon_db": "PLATON_DB",
            "gplas2_external_predictions_dir": "GPLAS2_EXTERNAL_PREDICTIONS_DIR",
        }
        for argument, variable in path_options.items():
            value = getattr(args, argument)
            if value:
                env[variable] = str(value.resolve())
        if args.local_inputs:
            env["LOCAL_INPUTS_ONLY"] = "1"
        if args.long_reads_file:
            env["LONG_READS_FILE"] = args.long_reads_file
        if args.analysis_track:
            env["ANALYSIS_TRACK"] = args.analysis_track
        positive_options = {"threads": "THREADS", "memory_gb": "MEMORY_GB", "min_read_len": "MIN_READ_LEN",
                            "parallel_samples": "MAX_PARALLEL_SAMPLES", "parallel_tools": "MAX_PARALLEL_TOOLS"}
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
                                   ("flye_mob_recon", "RUN_FLYE_MOB_RECON")):
            value = getattr(args, argument)
            if value:
                env[variable] = "1" if value == "on" else "0"
        if args.force_rerun_tools:
            env["FORCE_RERUN_TOOLS"] = "1"
        stages = ["6"] if args.command == "report" else args.stages
        code = run([bash_command(), "scripts/run_all.sh", *stages], root, env)
    raise SystemExit(code)
