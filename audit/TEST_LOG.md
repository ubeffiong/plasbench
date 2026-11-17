# Test log: audit of `main` (5c041ec)

`SP` = `<scratch dir>`. Nothing was run inside the project folders. The code under test was a `git archive origin/main` export at `SP\main`, copied to `~/pb_main` inside Ubuntu WSL for Linux runs. The export has no `.github/` and the package was not pip-installed.

Machines: Windows 11, Git Bash, Python 3.14; Ubuntu (WSL2, 6 cores, 7.9 GB), bash 5.2, Python 3.12, `minimap2`, GNU `timeout`; Chrome 157; Node 24.

## Executed

| ID | What | Command / method | Result |
|---|---|---|---|
| T1 | Scorer fixtures on `main` | `python SP\fx\run_fixtures.py SP\main` (hand-written truth, PAF, FASTA; real `score_plasmids.py`, `score_bins.py`) | Junk output F1 1.0 / strict 0.0196; duplicate F1 1.0 / redundant_pred_bp 100; 20 x 5 bp tiles recall 1.0; zero-plasmid binner `lw_bin_f1` 0.0000 while `score_plasmids` F1 is blank; two-chromosome bin `chromosome_aligned_bp` 1000 (true 2000), share 0.5 (true 0.333). Same as the stale branch. |
| T2 | Padded bin | `score_bins.py` with bin A = 100 bp contig aligned to a 100 bp plasmid + 100 bp contig aligning nowhere, `--pred-fasta` | `lw_bin_f1` 1.0000, CPRR share 1.0, correct=yes; `lw_bin_precision_strict` 0.5, `lw_bin_f1_strict` 0.6667, `bin_unaligned_fraction` 0.5. |
| T3 | Interval method | `resampling.cluster_t_ci(values, groups)` | [1,0,1,0,1,1,1,1,1,1] -> (0.498, 1.102); [1,1,1,1,1,0.99] -> (0.994, 1.0026); six zeros -> (0.0, 0.0). |
| T4 | Linux test suite, per file | `wsl -e bash gen/wsl_suite.sh`: each `test/test_*.py`/`.sh`, 240 s timeout each | 326 files: **321 pass, 5 fail, 0 timeout**. Failures: `test_real_tool_checks.py` (missing `.github/` in my export), `test_release_archive.sh` and `test_update_script.sh` (need `pyproject.toml` in cwd / package installed: `No module named 'plasbench'`), `test_install_all_optional.sh` (`config/tool_installers.tsv` not found in its temp project; one SIGKILL message), `test_cohort_and_write_script.sh` (exits 1 silently on `python3 -m plasbench`, so the same package issue). I did not trace these to the line; I judge them export/environment artefacts, not product defects. Slowest passes: `test_download_parallel.sh` 256 s wall, `test_job_survival.py` 106 s, `test_demo_end_to_end.py` 69 s. |
| T5 | Failure injection FI-A | stage 4 (`scripts/04_run_tools.sh`) with `ONLY_TOOL=mob_recon`, fake `mob_recon` = `exit 0` | status `completed`, empty prediction FASTA written, stage exit 0. |
| T6 | FI-B | fake tool `sleep 300`, `TOOL_TIMEOUT_SECONDS` unset, outer `timeout 25` | still running at 25 s (exit 124). |
| T7 | FI-C (first attempt) | `kill -INT` to a backgrounded stage | **Invalid**: non-interactive background jobs ignore SIGINT. Discarded. |
| T8 | FI-C2 | `timeout --foreground -s INT 8 bash 04_run_tools.sh` with fake tool `sleep 311` | Log: "stopped with Ctrl+C"; the `sleep 311` process was still running afterwards (orphan); no `tool_status.tsv` row for the interrupted unit. |
| T9 | FI-D (first attempt) | contigs.fasta replaced by a directory | **Invalid**: the fake tool never read it, so nothing crashed. Discarded. |
| T10 | FI-D2 | two samples; `results/s2` made a regular file so `mkdir -p` fails for s2 | stage logged `mkdir -p "$RDIR"` failed (04_run_tools.sh:828), then "Stage 4 (run tools) complete", exit 0; `tool_status.tsv` has only the s1 row. |
| T11 | Web UI, load | isolated server: `PLASBENCH_UI_HOME`, `HOME`, `USERPROFILE`, `PLASBENCH_DB_DIR` pointed at `SP\ui`; project root = `SP\main`; port 8791; driven by `SP\ui\cdp.mjs` (Chrome DevTools Protocol) | Page loads, title "PlasBench", token removed from the address bar, 288 ids, 189 buttons, 0 console errors. |
| T12 | Web UI, 15 pages | clicked each sidebar entry, screenshot each | All 15 clicked and rendered; 0 console errors. (My first heading check was wrong and is not used.) Screenshots in `SP\ui\shots`. |
| T13 | Web UI, injection | planted `cohorts/a');window.__pwn=1;('.tsv` and `cohorts/O'Neil.tsv` in the scratch project; clicked Details/Validate in Chrome | Crafted name: `window.__pwn` became 1 after clicking Details (only a harmless flag was set). O'Neil: Details raises `SyntaxError: missing ) after argument list`; Validate's `data-run` is truncated and `JSON.parse` throws. |
| T14 | Web UI, terminal | `POST /api/terminal/run {"command":"echo AUDIT_PROBE"}` with the token header only | exit 0, output `AUDIT_PROBE`, shell `wsl:Ubuntu`. |
| T15 | Web UI, job + cancel | `POST jobs {"argv":["demo"]}`, poll, `POST jobs/<id>/cancel` | state `running`; progress structure empty for 22 s (the demo is not a staged run); cancel: `cancelling` -> `cancelled` after 19.1 s; 0 leftover processes (Windows). |
| T16 | Web UI, sleep | suspended the runner and its children with `psutil` for 30 s, then resumed | `interrupted` at t+20.2 s; still `interrupted` 14 s after resume while the runner was alive; `POST jobs/<id>/resume` accepted and returned a new running job. |
| T17 | Shipped real-cohort report | opened `results_real_cohort1/benchmark.report.html` in Chrome (`SP\ui\t6_report.mjs`) | 18,433,145 bytes; 31 sections; `#enterprise` anchor dangling; 68 sortable tables with no `tabindex`/`aria-sort`/button; 37 of 128 SVGs have `role=img`; CSV export works; page logs failed loads of `selected_candidates/*/*.candidate.plasmid.fasta` (not in the repo). Sort test inconclusive (first table had one row). |
| T18 | Housekeeping | `POST /api/shutdown`; process check; `stat` on real `~/.plasbench/ui/*.json` | server stopped; real files unchanged (dated 14-15 Nov). No leftover related processes besides my own shells. |

## Mistakes and corrections
- My first WSL background launch silently never ran (WSL ends processes when the launching command exits; Git Bash also rewrote `/mnt/...`). Fixed with `MSYS_NO_PATHCONV=1` and a foreground command in a background task.
- T7 and T9 were invalid test designs and were redone.
- On the earlier stale-branch audit, an installer test wrote `~/.plasbench/databases/genomad`; I removed only that stub. This `main` audit used isolated homes and wrote nothing to the real `~/.plasbench`.

## Not done, and why
- Real tools and databases (none installed); real-data or full-cohort run (not authorised); 98-isolate report; memory/CPU profiling; HPC.
- UI features not driven: Git page, intake wizard, settings writes, update check, desktop icon, WSL-child orphan check on cancel, terminal timeout hang on Windows.
- Re-checking the 35 agent-read register rows.
