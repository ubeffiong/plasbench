"""Console entry points for the individual pipeline steps.

`plasbench` drives whole stages and expects a project directory. Galaxy, CWL,
Nextflow and Snakemake instead call one step at a time, with explicit inputs and
outputs and no project layout at all -- and a Galaxy tool in particular may only
invoke a command that is on PATH, never an absolute path inside a container
image. These wrappers provide exactly that: a stable command per step that
resolves the pipeline scripts wherever they were installed.

Resolution order for the pipeline root, first hit wins:

1. ``$PLASBENCH_HOME`` -- set it explicitly to override everything else.
2. ``$CONDA_PREFIX/share/plasbench`` -- where the conda/bioconda package puts
   the pipeline (see recipes/bioconda/build.sh).
3. ``<sys.prefix>/share/plasbench`` -- the same location when the environment is
   active but ``CONDA_PREFIX`` is unset, e.g. under a Galaxy job runner.
4. The repository checkout containing this file -- the developer case.
5. The current working directory -- an unpacked release archive that has been
   pip-installed, where the package is in site-packages but the pipeline is not.

Each wrapper execs the underlying script with the current interpreter, so
arguments, exit codes and stderr pass straight through and nothing needs to be
kept in sync with the script's own option parser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = ["pipeline_root", "script_path", "score_main", "aggregate_main"]

# A directory is only accepted as the pipeline root if it actually holds the
# scripts, so a stale PLASBENCH_HOME fails loudly here instead of much later.
_MARKER = Path("python") / "score_plasmids.py"


def _candidates():
    override = os.environ.get("PLASBENCH_HOME")
    if override:
        yield Path(override), "PLASBENCH_HOME"

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        yield Path(conda_prefix) / "share" / "plasbench", "CONDA_PREFIX"

    yield Path(sys.prefix) / "share" / "plasbench", "sys.prefix"

    # plasbench/tools.py -> plasbench/ -> repository root. This is the case
    # where PlasBench is run straight from a checkout without installing.
    yield Path(__file__).resolve().parent.parent, "source checkout"

    # Finally the working directory: after `pip install .` inside an unpacked
    # release archive, the package lives in site-packages while the pipeline is
    # still in the directory the user is standing in.
    yield Path.cwd(), "current directory"


def pipeline_root() -> Path:
    """Return the directory holding scripts/, python/, adapters/ and config/."""
    tried = []
    for candidate, origin in _candidates():
        if (candidate / _MARKER).is_file():
            return candidate
        tried.append(f"  {candidate}  (from {origin})")
    raise SystemExit(
        "ERROR: cannot locate the PlasBench pipeline files.\n"
        "Looked for python/score_plasmids.py under:\n"
        + "\n".join(tried)
        + "\n\nSet PLASBENCH_HOME to the directory containing scripts/ and python/, "
        "or reinstall PlasBench."
    )


def script_path(relative: str) -> Path:
    """Absolute path to a pipeline script, e.g. 'python/score_plasmids.py'."""
    resolved = pipeline_root() / relative
    if not resolved.is_file():
        raise SystemExit(f"ERROR: {resolved} is missing from this PlasBench installation.")
    return resolved


def _exec(relative: str, argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    command = [sys.executable, str(script_path(relative)), *argv]
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 130


def score_main(argv=None) -> int:
    """`plasbench-score`: score one predicted-plasmid FASTA against truth."""
    return _exec("python/score_plasmids.py", argv)


def aggregate_main(argv=None) -> int:
    """`plasbench-aggregate`: build the leaderboard from per-sample scores."""
    return _exec("python/aggregate_results.py", argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(score_main())
