"""What an exit code means, in words: the plasbench command and the window say why a run stopped."""
from __future__ import annotations

import signal

_MEANING = {
    1: "a command reported an error",
    2: "a command was given a wrong option or a missing file",
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


def explain(code) -> str:
    """Python reports a death by signal N as -N; the shell reports it as 128+N. Both read the same."""
    if code is None:
        return "still running"
    code = int(code)
    if code == 0:
        return "finished"
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
