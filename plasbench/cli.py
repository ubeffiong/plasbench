"""Command-line entry point for the source checkout and container image."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__


def project_root(value):
    root = Path(value).resolve()
    if not (root / "scripts" / "run_all.sh").is_file():
        raise argparse.ArgumentTypeError(
            f"{root} is not a PlasBench source checkout (scripts/run_all.sh missing)"
        )
    return root


def run(command, root, env=None):
    merged_env = os.environ.copy()
    merged_env["PROJECT_ROOT"] = str(root)
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="plasbench",
        description="PlasBench: benchmark plasmid-reconstruction tools against complete references.",
    )
    parser.add_argument("--version", action="version", version=f"plasbench {__version__}")
    parser.add_argument("--project-root", type=project_root, default=Path.cwd(),
                        help="PlasBench source checkout (default: current directory).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Run the offline synthetic scoring and report demo.")
    sub.add_parser("test", help="Run the scoring unit tests.")
    sub.add_parser("check", help="Check configured runtime dependencies.")
    run_parser = sub.add_parser("run", help="Run the full benchmark or selected stages.")
    run_parser.add_argument("stages", nargs="*", choices=[str(i) for i in range(7)],
                            help="Optional stage numbers: 0 setup through 6 report.")
    run_parser.add_argument("--samples", type=Path, help="Override config/accessions.tsv for this run.")
    run_parser.add_argument("--threads", type=int, help="Override THREADS for this run.")

    args = parser.parse_args(argv)
    root = args.project_root
    if args.command == "demo":
        code = run([bash_command(), "test/run_demo.sh"], root)
    elif args.command == "test":
        code = run([sys.executable, "test/test_scoring.py"], root)
    elif args.command == "check":
        code = run([bash_command(), "scripts/run_all.sh", "0"], root)
    else:
        env = {}
        if args.samples:
            env["SAMPLE_SHEET"] = str(args.samples.resolve())
        if args.threads:
            if args.threads < 1:
                parser.error("--threads must be positive")
            env["THREADS"] = str(args.threads)
        code = run([bash_command(), "scripts/run_all.sh", *args.stages], root, env)
    raise SystemExit(code)
