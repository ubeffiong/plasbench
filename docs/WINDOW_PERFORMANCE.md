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

TIMING_TABLE

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
