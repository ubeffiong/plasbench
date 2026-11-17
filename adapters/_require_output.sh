#!/usr/bin/env bash
# Sourced by the adapters (not run). require_tool_output TOOL DIR GLOB... succeeds when at least one GLOB (relative to DIR) matches a file,
# and otherwise explains "no output from TOOL" and returns 1. Every GLOB names a file the tool writes even when it finds no plasmid, so a
# tool that ran and found nothing is still a completed run with an empty prediction, while a tool that crashed, wrote somewhere else or
# left only a log is a FAILED run (audit AU-008: it used to be scored as a genuine zero).
require_tool_output() {
    local tool="$1" dir="$2" pattern; shift 2
    for pattern in "$@"; do
        # cd first: a Windows-style DIR (drive letter and backslashes) would otherwise have its backslashes read as glob escapes
        ( cd "$dir" 2>/dev/null && compgen -G "$pattern" > /dev/null ) && return 0
    done
    echo "[adapt_${tool}] no output from ${tool}: none of its result files ($*) exists under $dir. This is a failed run, not 'no plasmids found' (a log file alone does not count)." >&2
    return 1
}
