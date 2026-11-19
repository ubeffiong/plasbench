"""What an exit code means, in words: the plasbench command and the window say why a run stopped."""
from __future__ import annotations

import signal

_MEANING = {
    1: "a command reported an error",
    2: "a command was given a wrong option or a missing file",
    4: "every tool run of stage 4 failed (nothing was produced to score)",
    20: "a manual installation step is needed (nothing failed; the notice above lists the steps)",
    21: "your consent is needed to install (nothing was changed; read the plan above, then run the same command with --yes)",
    124: "a time limit was reached",
    126: "a program could not be run (permissions)",
    127: "a program was not found (not installed, or not on PATH)",
    129: "stopped (SIGHUP): the terminal was closed",
    130: "stopped with Ctrl+C",
    134: "aborted (SIGABRT): the program crashed",
    137: "killed (SIGKILL): usually out of memory, or WSL or the system ended it",
    139: "crashed (segmentation fault)",
    143: "stopped (SIGTERM): cancelled, or the system asked it to stop",
}


# `plasbench install-tools` uses the same numbers for different reasons: 2 there is an unknown profile name or a wrong option, never a missing file.
_INSTALL_MEANING = {
    1: "the installation did not complete (the messages above say which step failed)",
    2: "the profile name is not known, or an option was wrong (the line above lists the nearest names)",
}


# Exit codes that are information, not failure: 20 a tool cannot be installed automatically (a verified limit, the notice lists the steps), 21 a first install
# of a source-built tool is waiting for consent. Every wrapper (the window's console, the terminal page, scripts/lib.sh) must say so without "ERROR" and without red.
INFORMATIONAL = (20, 21)


def is_informational(code) -> bool:
    try:
        return int(code) in INFORMATIONAL
    except (TypeError, ValueError):
        return False


def explain(code, command=None) -> str:
    """Python reports a death by signal N as -N; the shell reports it as 128+N. Both read the same. `command` is the plasbench command name when it
    changes what a code means (install-tools)."""
    if code is None:
        return "still running"
    code = int(code)
    if code == 0:
        return "finished"
    if command == "install-tools" and code in _INSTALL_MEANING:
        return _INSTALL_MEANING[code]
    if code < 0:
        code = 128 - code
    if code in _MEANING:
        return _MEANING[code]
    if code > 128:
        try:
            return f"stopped by signal {signal.Signals(code - 128).name}"
        except ValueError:
            return f"stopped by signal {code - 128}"
    return f"failed with exit code {code}"
