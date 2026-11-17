# Prioritised remediation roadmap

Nothing here has been applied. Each item waits for authorisation. Complexity: S (hours), M (days), L (weeks). Regression risk is for existing results. Endpoint changes (PB-001, 002, 003, 014) alter published numbers, so they should be additive columns first and versioned, never silent redefinitions.

## P0: scientifically incorrect results, invalid scoring, or major workflow failure

| Item | Issue | Change | Files | Depends on | Cx | Risk | Acceptance | Tests |
|---|---|---|---|---|---|---|---|---|
| P0-1 | PB-003 | Blank (undefined) `lw_bin_f1`/`bin_f1` when truth plasmid bp = 0; add a negative-control false-positive-bp measure | score_bins.py, aggregate_results.py, headline_design.py | none | S | Low-Med: changes binner means where negative controls exist | Fixture returns blank; sample excluded from F1 means; FP bp reported | Extend test_zero_plasmid_isolate_scoring.py to bins |
| P0-2 | PB-005, 006, 007 | Per-PID waits, output-validating adapters, default timeouts with `-k`; stage exits non-zero on missing units | 04_run_tools.sh, 05_score.sh, lib.sh, adapters/*.sh, config.sh | none | M | Med: runs that "passed" will now fail | Fake binaries: crash, no-output, hang each produce `failed` and non-zero exit | New `test_stage4_failure_injection.sh` |
| P0-3 | PB-011, 012 | Pre-assembly QC gate with PASS/WARN/REJECT; full gzip integrity check; REJECT blocks stage 3; thresholds echoed to a manifest | new `python/qc_reads.py`, 01/03 scripts, report | PB-012 first | M-L | Med: some samples now excluded | Corrupt, truncated and low-Q fixtures REJECT; report lists exclusions | Corrupt/truncated FASTQ tests |
| P0-4 | PB-001, 002 | Add strict (unmapped-aware) precision, n_candidates, best-candidate and combined coverage, off-target bp as leaderboard columns; keep F1 unchanged and labelled | score_plasmids.py, report | none | M | Low if additive | Junk and duplicate fixtures visible in leaderboard | Extend test_scoring_adversarial.py |
| P0-5 | PB-029 | `run_tests.sh` runs every file and prints a tally; ledger test matches symbols, not line numbers (passes on committed config.sh, fails with the current uncommitted edits) | test/run_tests.sh, test/test_independent_review_ledger.py | none | S | Low | Adding a line to config.sh does not hide other tests | self |
| P0-6 | PB-021, 023 | Single failure-policy statement; show n beside every ranking value | build_html_report.py | PB-017 | S | Low | Grep shows one policy; n visible | Report text test |
| P0-7 | PB-015, 016 | Populate DB release dates; report headline with and without overlapping samples; taxon-support column; rank restricted tools on their own subset | config/*.tsv, aggregate_results.py, headline_design.py | none | M | Med | Headline shown both ways; n retained for general tools | Synthetic skip-pattern test |

## P1: broken core features, unreliable execution, misleading reporting

| Item | Issue | Change | Cx | Acceptance |
|---|---|---|---|---|
| P1-1 | PB-009, 010 | Atomic writes, fingerprints on reuse in stage 3, idempotent status rows, score only current-run tools | M | Re-run produces identical row counts; truncated reuse regenerates |
| P1-2 | PB-008 | Signal traps and cancelled state | M | No orphans after SIGINT |
| P1-3 | PB-004 | Key chromosome intervals by (bin, target) | S | Fixture gives 2000 / 0.333 |
| P1-4 | PB-017, 032 | One sample-set policy per row; rank robustness on the headline endpoint | M | n per column; ranks reproduce |
| P1-5 | PB-014 | Separate classifier, binner, reassembler endpoints | M | Task blocks in the leaderboard |
| P1-6 | PB-019, 020, 022 | `is not None` checks; missing vs zero vs failed vs skipped everywhere | S | Unit tests with recall 0.0 and blank |
| P1-7 | PB-025, 026 | Budget the iframes; lazy-load alignments; correct README | M | 98-sample synthetic report within a size target |
| P1-8 | PB-024 | Commit or regenerate the generator for the real-cohort report | S-M | Regeneration diff is empty |

## P2: inefficiency, duplication, incomplete diagnostics

PB-013 (contigs-per-plasmid diagnostic), PB-018 (consolidate metric helpers, one contamination definition), PB-031 (recommender features), PB-033 (suppress p-values at fewer than 6 clusters), PB-034 (truth-label fixtures), PB-030 (missing tests: six modules, real-tool CI job, corrupt FASTQ, report DOM IDs), assembly candidate selection with truth-free criteria, run lock and preflight.

## P3: cosmetic and documentation

PB-027 (accessibility), PB-028 (anchor), PB-035 (docs drift), PB-036 (platform notes), double rounding, `.dockerignore`.

## Quick wins (under a day each)
PB-005 exit codes, PB-019, PB-021, PB-022, PB-028, PB-029, PB-003, the timeout default, README wording.

## Architectural changes
Run manifest and state machine; pre-assembly QC stage; single metrics module; report generated from one results JSON; per-task endpoint blocks.

## Before the next benchmark run
PB-005, 006, 007, 009, 010, 011, 012, 029, 003, 021.

## Before a manuscript
All P0, plus PB-014, 017, 023, 024, 032; an executed real-data end-to-end run; at least one real tool in CI; an independent re-derivation of the headline endpoints on a simulated cohort with known answers.
