# Why the window is fast, and what is cached

This note explains how `plasbench ui` keeps its pages quick, what it remembers and for how long, where everything is stored, and why it does **not** use a
database. The code is `plasbench/loadcache.py` (the caches), `plasbench/webui.py` (where they are used) and `plasbench/data/ui.html` (the Tools filter).
The checks are `test/test_window_load.py` and `test/tool_filter_perf.js`.

## What was slow (measured, not guessed)

The load path of each page was profiled with `cProfile` and timed over HTTP against a realistic workspace: this repository's `config/`, `cohorts/` (20 MB), `docs/`,
a `results_demo` folder, 200 studies with results, 200 jobs and a 5,000-row sample sheet. The causes were few:

| Cost | Where | Cause |
|---|---|---|
| PATH searches | `/api/tools`, `/api/env` | `shutil.which` once per tool (23 tools) and per core executable, each scanning every folder on PATH. In WSL the PATH holds the Windows folders on `/mnt/c`, so one search is hundreds of slow file-system calls. |
| `config/config.sh` parsed again and again | `/api/settings`, `/api/info`, `/api/tools`, `/api/prereg` | `Project.settings()` re-parsed the file for every setting looked up (12 times for one Settings page). |
| Re-reading every results folder | `/api/runs`, `/api/run-sessions`, `/api/workspace` | every call reopened each `benchmark.leaderboard.tsv`, `tool_status.tsv`, `study.json` and resolved every path, and three routes asked for the study list at the same moment. |
| Slow probes on the request path | `/api/platform` | `docker info`, `wsl -l` (about 4 s on Windows). |
| Counting cohort rows | `/api/cohorts` | each call read every cohort sheet in full. |
| Start-up job list | `Jobs()` | every job's `<id>.meta.json` was rewritten at start-up even when unchanged. |
| Size | page and `/api/schema` | 470 KB of HTML and 220 KB of JSON, sent uncompressed. |
| Client | Tools page | the whole table was rebuilt on every keystroke. |

## What is cached (all in memory, nothing on disk)

| What | Remembered until | If it goes stale |
|---|---|---|
| Registry rows (`config/tool_capabilities.tsv`, `tool_installers.tsv`, `tool_database_releases.tsv`) | one of those files, `config.sh` or `local.env` changes (mtime and size) | never stale |
| `config.sh` settings, `local.env` | the file changes | never stale |
| Cohort rows, Guides titles | their file (and its lock/selection/publication file) changes | never stale |
| One row per results folder and per study | its leaderboard, `tool_status.tsv`, report or `study.json` changes | never stale |
| Is a tool on PATH? conda, git, bash, databases (Set up) | 30 s, then **refreshed in the background**: the old answer is shown at once (stale-while-revalidate) | at most 30 s after an install; Check again forces it |
| Docker, WSL, conda environment (Set up > platform) | 120 s, same rule | Check again forces it |
| The study list, real paths | 1.5 s and 10 s; cleared by every change made in the window | an outside change shows within seconds |
| The command schema | for the life of the window (it only changes with the code) | restart |
| gzip of the page and schema | per distinct body | never stale |

`PLASBENCH_PROBE_TTL` (seconds, default 30) sets how long a PATH probe is fresh. The window also fills these caches in a background thread as it starts, so the
first page you open is served from memory.

**The Tools page** draws from the cached registry at once. A tool whose PATH probe has no answer yet shows `checking...`; the page asks again every 0.7 s
until none is left, then fills in `installed` / `not found`, the counts and the Install buttons. Typing in the filter is debounced (120 ms), each row's HTML and search
text are built once, the table is written with one DOM operation, and not at all when the result did not change.

**Clearing the memory.** Press *Check again* on Set up, or restart the window. There is no cache folder to delete. An install, a settings save or saving a user tool
marks the tools as stale and the page asks for a fresh probe.

## Measured before and after

Machine: Windows 11 laptop, 6 cores, Python 3.14 (native) and WSL2 Ubuntu (Python 3.12) with the project and workspace on a `/mnt/c` 9p drive, which is the slow
case this window usually runs in. Workspace: this repository, 200 studies with results, 200 jobs, 40 hand-added run folders, a 5,000-row sheet. Times are
milliseconds for one HTTP call to a local server. "Cold" is the first call in a fresh process (no start-up warm-up); "warm" is the median of later calls. The harness
is not in the repo (it was a throwaway script); `test/test_window_load.py` is the regression guard.

**WSL2, workspace on `/mnt/c` (the project's usual setup).** Before = origin/main, one cold and two warm calls each; after = this change, with the start-up warm-up
already done (it runs in a background thread, about 4 s, not on any request).

| Route (page) | Before cold | Before warm | After cold, no warm-up | After warm (with start-up warm-up) |
|---|---:|---:|---:|---:|
| `tools` (Tools filters) | 3,626 to 5,495 | 3,584 to 4,913 | 337 | 16 |
| `env` (Set up) | 1,810 to 2,478 | 1,800 to 1,918 | 1,904 | 6 |
| `settings` | 222 to 342 | 218 to 291 | 55 | 40 |
| `cohorts` | 841 to 1,466 | 699 to 806 | 1,295 | 31 |
| `docs` | 1,469 | 471 | n/a | 203 |
| `workspace` | 12,113 | 11,942 | 6,086 | 11 |
| `runs` | 31,550 to 75,063 | 35,193 to 54,865 | 16,425 | 14,874 |
| `run-sessions` | 67,209 to 80,318 | 55,947 to 122,871 | 31,618 | 32,370 |
| `platform` | not measured (docker/wsl probe, seconds) | | 12 (answers pending, then ready) | 7 |
| page `/` (bytes sent) | 309 ms, 470 KB | | 25 ms, about 90 KB gzipped | |
| `schema` bytes | 222,635 | | 29,909 | |
| `Jobs()` start-up | 5,111 to 9,812 | | 1,998 | |

Honest reading: on `/mnt/c` the Tools filters, Set up, Settings, Cohorts and Workspace now answer in tens of milliseconds once warm, and the first call is no longer a
blocking PATH search. **`runs` and `run-sessions` remain slow on `/mnt/c` with 240 results folders (about 15 s and 32 s)**: each folder still costs several stat calls
at about 5 ms each on that drive; the fingerprint pass was reduced afterwards (one stat pass per folder, see below) but WSL went down before this could be re-measured
there. With 240 folders that is the cost of walking a 9p drive; the remedy is to keep the workspace on WSL's own disk, or (if it matters) the rebuildable index
described under "When it would be reconsidered". The load-path target of "no handler over 200 ms warm" is therefore met for every route except those two on `/mnt`.

**Windows native (Python 3.14, drive C:), after the last change, with start-up warm-up; warm median of two calls.**

| Route | Before warm | After warm |
|---|---:|---:|
| `tools` | 89 to 526 | 3 |
| `env` | 57 to 467 | 1 |
| `settings` | 83 to 269 | 8 |
| `cohorts` | 59 to 78 | 3 |
| `runs` | 592 to 1,891 | 17 |
| `run-sessions` | 749 to 1,921 | 24 |
| `workspace` | 56 to 502 | 9 |
| `info` | 16 to 92 | 3 |
| `platform` | 681 to 3,919 | 8 |
| `Jobs()` start-up | 389 to 1,126 (1,856 under profile) | 361 |
| page `/` | 6 to 44 ms | 9 ms |

Not changed: `git/status` (about 1.7 to 2.7 s on Windows: several `git` and `gh` processes; it belongs to the Git page, not to the load path of the pages above).
No bootstrap endpoint was added: a localhost round trip costs 2 to 3 ms, so batching saves nothing once the handlers are cached.
Client-side timings could not be measured (no browser here); only the filter's DOM-operation count is tested, under node.


## Where things are stored

Everything the window keeps is plain files, by design, and none of it moved:

| Data | File | Written by |
|---|---|---|
| Settings for this computer | `config/local.env` (git-ignored) | window, by hand |
| Defaults, tool registry, cohorts, sample sheets, prereg | `config/*.tsv`, `config/config.sh`, `cohorts/*.tsv` | people, git |
| Studies, results, run history | `<study>/study.json`, `results/*.tsv`, `run_events.jsonl` | the pipeline |
| Window jobs | `~/.plasbench/ui/jobs/jobs.json`, `<id>.meta.json`, `jobs.lock`, `jobs.deleted` | window and the detached runner |
| Studies kept outside the workspace | `<workspace>/.external_studies.json` | window |

## Why not SQLite?

It was evaluated against the profile above and **not adopted**.

- **The delays were not storage.** Every cost in the table is repeated parsing, PATH and subprocess probes, directory walks and client rendering. They were removed
  by remembering the results with a file fingerprint. A database would have been a second copy to keep in step with the same files and would not have shortened a
  single `shutil.which`.
- **The data is small and is meant to be plain text.** The registry has 23 tools, the cohort sheets are TSVs people edit and diff, and results, `run_events.jsonl` and
  `study.json` are the scientific record that is committed to git. Putting any of that behind a database would hide it from `git diff` and from reviewers.
- **WAL databases are unsafe where studies often live.** SQLite's write-ahead log needs shared memory and working file locks; on `/mnt` (9p), OneDrive and other
  cloud or network folders it can corrupt. Falling back to journal modes there would remove the concurrency that was the reason to use a database.
- **Jobs already work.** `jobs.json` is written under a lock (`jobs.lock`, exclusive create, stale-lock recovery) with a per-job meta file, and the detached runner
  writes its own small files without opening the list, so it never needs a shared database connection.

**When it would be reconsidered:** thousands of runs or jobs in one window, where listing them from files is still slow after the fingerprint caches above. Even then
the answer would be a *rebuildable index* of runs and studies in the local app-data folder (never in a cloud or `/mnt` folder, never the only copy of anything,
dropped and rebuilt from the files if it is damaged), not a move of the data itself.

## Tips

- Keep the workspace on the computer's own disk (under `/home` in WSL) rather than `/mnt/c`, and keep PATH short: every PATH folder on a slow drive adds to the first probe.
- A slow first page after a long idle time is the background refresh of a probe that expired; the page itself does not wait for it.
