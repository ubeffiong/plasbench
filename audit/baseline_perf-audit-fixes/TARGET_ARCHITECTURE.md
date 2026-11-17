# Recommended target architecture

Principle: keep what works (CLI, numbered stages, adapter contract, capability registry, scorers, statistics, pre-registration). Add the missing control layer. No rewrite.

```
plasbench CLI
   │  writes run.json (run_id, config hash, samples, tools, expected outputs)
   ▼
stage 0 setup → 1 download → 1.5 QC (NEW: PASS/WARN/REJECT) → 2 truth → 3 assemble
   → 4 run tools (supervisor) → 5 score → 6 aggregate → report
   each unit: queued → running → validating → completed | failed | skipped | cancelled | stalled
   │
   ▼
results/<run_id>/ { run.json, units.tsv, qc.tsv, scores.tsv, ... , results.json }
   ▼
report builder reads results.json only (no recomputation, no TSV re-parsing in JS)
```

| Layer | Target | Reuse |
|---|---|---|
| Frontend | One static report; one of dashboard / explorer / Visual Quality; data loaded lazily; every number carries its n and links to its definition | Existing templates, `assets/` |
| API / services | CLI and env vars stay the contract; `plasbench status --run <id>` reads `units.tsv`; `plasbench cancel` | cli.py |
| Orchestration | Bash stages stay; add a supervisor with per-PID waits, stall detection, signal traps, lock file, preflight | lib.sh, 04/05 |
| Data model | `run.json`, `units.tsv` (run_id, sample, tool, state, exit, failure_class, output_valid), `qc.tsv`, one `results.json` | tool_status.tsv, tool_outcomes.tsv |
| Execution monitoring | Heartbeat to a log file; stalled state; progress from units.tsv | run_with_heartbeat |
| Analytics | One `plasbench_common` for interval union, matching, contamination and clusters; endpoints grouped by task type (classifier, binner, reassembler); inflation-resistant co-endpoints | score_*.py, headline_design.py |
| Reporting | Generated from `results.json`; failure policy and denominators printed from the same constants the scorer uses | build_html_report.py split into modules |
| Logging / audit | Per-unit log paths in units.tsv; QC and exclusion decisions recorded; config hash and tool/DB versions in run.json | tool_database_releases.tsv |
| Configuration | One validated config with documented defaults; thresholds echoed into run.json | config.sh |
| Testing | Fake-binary failure injection; corrupt-FASTQ fixtures; one real-tool CI job; report DOM-ID/link test; `run_tests.sh` that runs everything and prints a tally; simulated cohort with known answers for endpoint validation | test/ |

Migration order: (1) manifest and state files written alongside current outputs, (2) supervisor and adapter validation, (3) QC stage, (4) results.json and report switch, (5) metric consolidation. Each step leaves the current outputs readable.
