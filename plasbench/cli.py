"""Command-line entry point for the source checkout and container image."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__


STAGE_HELP = """stage numbers: 0=setup, 1=download, 2=truth, 3=assemble,
4=reconstruct, 5=score, 6=aggregate and HTML report."""

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
    cohort_parser.add_argument("--write-lock", type=Path, help="Write NCBI verification evidence as JSON; requires --online.")
    install_parser = sub.add_parser("install-tools", help="Install an optional bioinformatics dependency profile.")
    install_parser.add_argument("profile", nargs="?", default="core", help="core, assembly, reconstruction, all, or a conda package name.")
    install_parser.add_argument("--env", default="plasbench", help="Conda/mamba environment name (default: plasbench).")
    docs_parser = sub.add_parser("docs", help="Print the comprehensive user guide or a topic.")
    docs_parser.add_argument("--topic", choices=("all", *DOC_TOPICS), default="all",
                             help="Guide topic to print (default: all).")
    report_parser = sub.add_parser("report", help="Regenerate the leaderboard and HTML report from scores.")
    run_parser = sub.add_parser("run", help="Run the full benchmark or selected stages.")
    run_parser.add_argument("stages", nargs="*", choices=[str(i) for i in range(7)],
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
        resources = command_parser.add_argument_group("resources and assembly")
        resources.add_argument("--threads", type=int, help="CPU threads per tool (default: config value, normally 4).")
        resources.add_argument("--memory-gb", type=int, help="SPAdes memory limit in GB (default: config value, normally 16).")
        resources.add_argument("--assembler", choices=("spades", "unicycler"), help="Short-read assembler.")
        resources.add_argument("--min-read-len", type=int, help="Discard reads shorter than this after fastp.")
        resources.add_argument("--minimap2-preset", help="minimap2 assembly preset (default: asm5).")
        tools = command_parser.add_argument_group("tools")
        for option, destination, label in (
            ("--mob-recon", "mob_recon", "Enable or disable MOB-suite reconstruction."),
            ("--platon", "platon", "Enable or disable Platon classification."),
            ("--plasmidspades", "plasmidspades", "Enable or disable plasmidSPAdes."),
            ("--gplas2-mob", "gplas2_mob", "Enable or disable gplas seeded by MOB-recon membership."),
            ("--gplas2-external", "gplas2_external", "Enable or disable gplas with external classifier TSVs."),
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
        if args.write_lock:
            command.extend(["--write-lock", str(args.write_lock)])
        code = run(command, root)
    elif args.command == "install-tools":
        code = run([bash_command(), "env/install_tools.sh", "--env", args.env, args.profile], root)
    elif args.command == "docs":
        print_docs(root, args.topic)
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
        positive_options = {"threads": "THREADS", "memory_gb": "MEMORY_GB", "min_read_len": "MIN_READ_LEN"}
        for argument, variable in positive_options.items():
            value = getattr(args, argument)
            if value is not None:
                if value < 1:
                    parser.error(f"--{argument.replace('_', '-')} must be positive")
                env[variable] = str(value)
        for argument, variable in (("assembler", "ASSEMBLER"), ("minimap2_preset", "MINIMAP2_PRESET")):
            value = getattr(args, argument)
            if value:
                env[variable] = value
        for argument, variable in (("mob_recon", "RUN_MOB_RECON"), ("platon", "RUN_PLATON"),
                                   ("plasmidspades", "RUN_PLASMIDSPADES"),
                                   ("gplas2_mob", "RUN_GPLAS2_MOB"), ("gplas2_external", "RUN_GPLAS2_EXTERNAL")):
            value = getattr(args, argument)
            if value:
                env[variable] = "1" if value == "on" else "0"
        if args.force_rerun_tools:
            env["FORCE_RERUN_TOOLS"] = "1"
        stages = ["6"] if args.command == "report" else args.stages
        code = run([bash_command(), "scripts/run_all.sh", *stages], root, env)
    raise SystemExit(code)
