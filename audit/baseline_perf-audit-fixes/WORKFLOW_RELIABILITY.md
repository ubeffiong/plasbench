# Workflow reliability report

Evidence level: **Static** unless marked. No stage script was run end to end with injected failures (see `TEST_LOG.md`, "Not done"). Existing tests do cover exit 127, retry, and timeout 124 in stage 4 (`test_outcome_states.sh`), so those paths have some assurance on Linux; whether they run in this tree was not established because the shipped suite aborts early (PB-029).

## Causes of each failure mode

| Failure mode | Cause | Where | Issue |
|---|---|---|---|
| Stalled / indefinite wait | `TOOL_TIMEOUT_SECONDS` blank by default; no timeout in stages 1, 3, 5, 7; `timeout` without `-k`; dropped silently if `timeout` is absent | config.sh:115; 04_run_tools.sh:95-101 | PB-007 |
| Incorrect completion | Adapters write an empty prediction when output is absent; marker `.complete` written on exit 0 | adapt_*.sh; 04_run_tools.sh:263 | PB-006 |
| Stage reports success after job crash | Bare `wait`; no PID tracking; shard merge omits missing | 04_run_tools.sh:788-795; 05_score.sh:473-478; lib.sh:179-193 | PB-005 |
| Partial outputs accepted | `-s` (non-empty) checks; non-atomic copies; side files not cleaned on failure | 03_assemble.sh:88,110,134-148; 01_download.sh:222,253-256 | PB-009 |
| Failed resumption / duplicates | Stage 7 appends; stage 4 rewrites status; stage 5 scores any `.complete` marker | 07:92-117; 04:806; 05:168 | PB-010 |
| Cancellation leaves orphans | No traps in stages 0-7; no signal forwarding in heartbeat wrapper | lib.sh:76-93; cli.py:81-87 | PB-008 |
| Retry masks the real error | Retry re-runs into a dirty output directory | 04_run_tools.sh:102-115 | (P3, Reported) |
| Concurrent runs collide | No lock; `reset_shard_dir` uses `rm -rf` on shared names | lib.sh:169-172 | (O8, Suspected) |
| Excess resource use | Parallelism = samples x tools with no global cap; oversubscription check is advisory and Linux-only | 04_run_tools.sh:779-781; lib.sh:132-152 | (P7, Reported) |
| Disk exhaustion | No preflight beyond download estimate; detected only by grepping logs | 01_download.sh:39; 04_run_tools.sh:86 | (P8, Reported) |
| Heartbeat noise under SLURM/nohup | `[[ -w /dev/tty ]]` true without a terminal; printf to /dev/tty fails | lib.sh:69 | (P10, Suspected, not tested) |

## Existing run-state model
Per-unit status only: `assembly_status.tsv` (completed, reused, failed, skipped), `tool_status.tsv` and `tool_outcomes.tsv` (completed, reused, skipped, failed, infrastructure_failure; exit code, failure class, attempts). There is no queued, running, stalled or cancelled state; no run-level manifest; no progress file; no resume record.

## Proposed run-state and recovery model (minimal, keeps the Bash stages)

1. **`run.json` at the start of every run** with `run_id`, config hash, tool list, sample list and per-stage expected outputs. Status rows carry `run_id`.
2. **Unit states:** `queued → running → validating → completed | failed | skipped | cancelled | stalled`.
3. **`validating`:** an adapter-specific check that the expected output exists, parses and has a header. Exit 0 without valid output ends in `failed (no_output)`, never `completed`. A legitimately empty prediction is a file with a header and a `zero_plasmids` marker.
4. **Stall detection:** a unit is `stalled` when no log or output byte changes for `STALL_SECONDS`; the supervisor kills the process group (`timeout -k`) and records exit 124 or 137.
5. **Supervisor:** replace bare `wait` with per-PID waits. The stage exits non-zero when any expected unit is missing or failed, with a one-line tally.
6. **Signals:** a trap on INT/TERM forwards to child process groups, marks running units `cancelled`, and removes shard directories.
7. **Resume:** reuse a unit only if its fingerprint (tool version, DB release, input checksums, parameters) matches; write outputs to a temp name then rename.
8. **Idempotent status writes** keyed on `(run_id, sample, tool)`.
9. **Lock file** per results directory.
10. **Preflight:** free disk against an estimate, `timeout`, `/usr/bin/time`, bash version, CRLF check on config files.

## Linux, WSL and HPC notes
- Run from native Linux or WSL ext4, not from OneDrive-synced folders (many small temp files and `rm -rf` on shard directories).
- On SLURM, set `TOOL_TIMEOUT_SECONDS` below the job limit, redirect heartbeat to a log file instead of `/dev/tty`, and set `MAX_PARALLEL_SAMPLES * MAX_PARALLEL_TOOLS * threads <= cpus-per-task`.
- Git Bash on Windows: the resource-oversubscription warning is disabled and memory falls back to 8 GB; treat it as unsupported for real runs (consistent with the docs).
