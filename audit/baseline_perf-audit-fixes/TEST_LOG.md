# Test log

Platform: Windows 11, Git Bash (bash), Python 3.14 (`/c/Python314`). The project documents Linux/WSL2 as the supported platform, so some failures below may be Windows artefacts rather than product defects; I say so where I cannot tell. `minimap2` is not installed here. `node` is installed but was not used on the report.

Scratch locations (`SP` = `<scratch dir>`):
- `SP\copy`: copy of the project without `results*`, `tmp`, `dist`, `data`, `logs`, zips. All test runs used this copy.
- `SP\fx\run_fixtures.py`: scorer fixtures. `SP\fx\out_<test>.txt`: per-test output. `SP\each.tsv`: per-test exit code and seconds.

## Executed

| ID | Command | Result |
|---|---|---|
| T1 | `bash test/run_demo.sh` (in `SP\copy`; it writes to `SP\copy\results_demo`) | exit 0. Ran twice; the first background run printed only the cohort line to its log, the traced rerun (`bash -x`) completed through "interactive HTML report". Cohort: 6 samples x 5 methods, 11 truth plasmids, synthetic. |
| T2 | `bash test/run_tests.sh` (scratch copy, which includes the uncommitted working-tree `config/config.sh`) | exit 1 after about 28 s. 11 files had printed PASSED; test 13 `test_independent_review_ledger.py` printed `REVIEW LEDGER TESTS FAILED` (E9, E10, E11, E18, E19, E42) and `set -e` stopped the script. Re-running that one file in the original working tree gave the same failures. |
| T2c | `git show HEAD:config/config.sh > SP\copy\config\config.sh`, then `python test/test_independent_review_ledger.py` | `ALL REVIEW LEDGER TESTS PASSED` (49 rows). So the failure comes from the uncommitted `config.sh` edits (git diff: +35/-11 lines) shifting line numbers, not from the committed tree. |
| T2b | Each of the 216 `test/test_*.py` and `test_*.sh` files run separately, 180 s timeout each | 209 passed, 6 failed, 1 timed out. See below. |
| T3 | `python SP\fx\run_fixtures.py SP\copy` (hand-written truth, PAF and FASTA; real `score_plasmids.py` and `score_bins.py`) | Results in `SCIENCE_VALIDATION.md` V1-V5. |
| T4 | Same script, junk / duplicate / fragmentation / zero-plasmid / two-chromosome cases | V1 precision 1.0000, F1 1.0000, strict 0.0196. V2 F1 1.0, redundant_pred_bp 100. V3 recall 1.0. V4 lw_bin_f1 0.0000 and blank score_plasmids F1. V5 chromosome_aligned_bp 1000, bin_share 0.5000. |
| T5 | Reading the cited lines of `build_html_report.py` (466-470, 482-486, 511-514, 672-679), `04_run_tools.sh` (788-795) and `config.sh` (112-117) | Lines match what the exploration reported. |
| T6 | Built a 20,000-read gz FASTQ pair, truncated R2 to half its bytes, ran `python python/validate_local_inputs.py --samples ... --data-dir ...` | **exit 0, "local inputs verified: 1 sample(s) ready".** The truncation was not detected (PB-012). |
| T7 | Python reproduction of `(optional_number(x) or 1) < 0.9` | `"0.0000"` -> False, `""` -> False, `"0.5"` -> True. Recall 0 does not trigger the warning (PB-019). |
| T8 | `python test/test_independent_review_ledger.py` in the original tree | Same failure as T2, which shows it is not caused by my copy. |

## Failures in T2b (cause not always established)

| Test | Result | What the output shows | Product defect or environment? |
|---|---|---|---|
| test_independent_review_ledger.py | exit 1 | Ledger line references into config.sh are stale | Caused by the uncommitted config.sh edits; passes on committed config.sh (T2c). Brittle design, PB-029 |
| test_outcome_states.sh | exit 1 | Its first checks passed (retry, timeout 124); the last step failed with `ModuleNotFoundError: No module named 'aggregate_results'` from an inline `python -c` | Unknown. Probably a path/`sys.path` issue under Windows Git Bash or Python 3.14; not diagnosed. Because this is the failure-state test, the aggregation half of it is **unverified** |
| test_build_hybrid_truth_stage.sh | exit 1 | `expected contig 2 labeled PLASMID` | Unknown; not diagnosed |
| test_database_installers.sh | exit 1 | `expected a populated genomad_db directory` | Likely environment; see side effect below |
| test_release_archive.sh | exit 1 | `FileNotFoundError: 'pyproject.toml'` (relative path) | Likely a working-directory assumption; not diagnosed |
| test_update_script.sh | exit 1 | `old data directory was not linked to shared storage` | Likely symlinks on Windows; not diagnosed |
| test_download_parallel.sh | timeout (180 s) | Passed its first case then did not finish | Unknown (Windows process handling or a hang); a hang would itself be relevant to PB-007 but I did not establish that |

Slowest passing tests: `test_demo_end_to_end.py` 151 s, `test_tool_result_fingerprint.sh` 142 s, `test_capability_cache.sh` 139 s.

All T2b results used the working-tree `config.sh`, which changes where tool databases live (`PLASBENCH_DB_DIR`, default `$HOME/.plasbench/databases`). That is why an installer test touched the home directory.

## Side effect to disclose
`test_database_installers.sh` wrote outside the scratch copy: it created `~\.plasbench\databases\genomad\genomad_db\version.txt` (6 bytes, "marker"), birth time 2026-11-17 07:53:18, during my run. Because a stub like this could make `plasbench check` believe a geNomad database is installed, I deleted that `genomad` directory (only that one; `databases\mob_suite` predates my run and was left alone). `~/.plasbench/ui/` also exists, dated 9-14 November, and I did not touch it.

## Not done, and why
- **Fake-binary failure injection** (crashing tool, exit-0-without-output tool, hung tool, SIGINT mid-stage, re-run of stage 7, duplicate sample IDs, stale `.complete` marker): not run. The stage scripts need Linux tooling (`/proc`, GNU `stat`, `timeout`, `wait -n`) and I judged results from Git Bash on Windows would not be trustworthy. PB-005 to PB-010 are therefore **Static**.
- **Real tools and databases**: none installed; no real-tool integration test.
- **minimap2-based alignment tests**: not installed.
- **Browser or headless UI test, screenshots**: not done. The report JS was not executed.
- **98-isolate report size and runtime**: not generated.
- **Performance profile** (peak memory, CPU, subprocess counts): not measured beyond per-test wall time above.
- **Disk-full, missing executable per tool, corrupt FASTQ into stage 1**: only the validator case (T6) was run.
- **Full-cohort benchmark**: not run, as instructed.
