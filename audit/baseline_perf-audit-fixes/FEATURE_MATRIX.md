# Feature integration matrix

The audited branch (`perf-audit-fixes`) has no web server or REST API; a web UI exists on other branches and was not audited. The "UI" column is the static HTML report; the "API" column is the CLI (`plasbench <subcommand>`) plus environment variables. "Verified" means I executed it; everything else is by reading code or the exploration pass.

Status vocabulary: **Verified** (implemented and executed), **Implemented, not verified**, **Partial**, **Unwired**, **Broken**, **Duplicated**, **Missing**, **n/a**.

| Feature | UI (report) | CLI/API | Backend | Workflow | Analysis | Report | Status |
|---|---|---|---|---|---|---|---|
| Synthetic demo end to end | yes | `plasbench demo` | yes | scoring + report only | yes | yes | **Verified** (ran in scratch copy, exit 0) |
| Offline regression suite | n/a | `plasbench test` | yes | n/a | n/a | n/a | **Partial**: stops at the first failing file, so a config edit that breaks the line-pinned ledger test hides ~200 tests (PB-029). Run per file: 209/216 pass on Windows |
| Web UI (live, jobs, server) | not on audited branch | `webui.py` on origin/feat/ui-* | **not audited** | n/a | n/a | n/a | **Not audited** (see AUDIT_REPORT section 0) |
| Base-level scoring (P/R/F1, recall tiers) | leaderboard, tables | stage 5 | score_plasmids.py | stage 5 | yes | yes | **Verified** (fixtures); loopholes PB-001/002 |
| Bin scoring (lw_bin_f1, CPRR, outcomes) | tables, bin flow | stage 5 | score_bins.py | stage 5 | yes | yes | **Verified** (fixtures); PB-003, PB-004 |
| Ranking, bootstrap, permutation, Holm | leaderboard CIs, p | stage 6 | aggregate_results.py, resampling.py | stage 6 | yes | yes | Implemented, not verified at runtime |
| Failure-as-zero | health table | stage 4/6 | yes | stage 4 | headline only | contradictory text | **Partial** (PB-017, PB-021) |
| Tool execution with retry/timeout | health table | stage 4 | 04_run_tools.sh, adapters | stage 4 | n/a | yes | **Partial**: no default timeout (PB-007); silent failures (PB-005/006) |
| Short-read QC gate | flags in report | none before assembly | assembly_qc_gate.py (post-scoring) | stage 6 only | advisory | flags | **Partial / Missing** as a gate (PB-011) |
| Input validation | n/a | `--local-inputs` | validate_local_inputs.py | stage 1 | n/a | n/a | **Partial**: truncated gzip passes (PB-012) |
| Assembly selection among candidates | none | `ASSEMBLER` env | 03_assemble.sh | stage 3 | none | none | **Missing** |
| Multi-candidate per-plasmid accounting | partial | stage 5 | score_plasmids.py `--per-plasmid-out`, redundant_pred_bp | stage 5 | partial | partial | **Partial** (PB-002) |
| Truth construction (NCBI, hybrid, local) | provenance tab | stage 2, `init-local` | make_truth.py, build_hybrid_truth.py | stage 2 | n/a | provenance | Implemented, not verified; hybrid-truth scripts not wired into CLI (README:2345) |
| Database-overlap flagging | flag columns | config | flag_database_overlap.py | stage 6 | report-only by default | yes | **Partial** (PB-015) |
| Recommender / select-unknown | recommendation section | `select-unknown`, `reconstruct` | recommendation_model.py | stage 8 | LOSO | yes | Implemented, not verified; train/serve skew (PB-031) |
| Depth and read-quality ladders | ladder figures | `depth-ladder`, `read-quality-ladder` | yes | local | yes | yes | Implemented, not verified |
| Metagenomics track (beta) | dashboard | `metagenomics` and 7 others | metagenomics.py | separate | yes | yes | Implemented, not verified |
| HTML score table: sort, filter, CSV export | yes | n/a | JS in build_html_report.py | n/a | n/a | n/a | Implemented, not verified interactively; a11y gaps (PB-027) |
| Visual Quality viewer | yes (`vq-*`) | n/a | JS + embedded JSON | stage 6 | n/a | yes | **Duplicated** with explorer/dashboard (Reported) |
| Evidence explorer / enterprise dashboard iframes | yes | n/a | templates in assets/ | stage 6 | n/a | yes | **Duplicated**; size (PB-025) |
| Report from the real cohort | yes | `open-report` | generator not in repo | n/a | n/a | n/a | **Unwired**: cannot be regenerated (PB-024) |
| Run state: queued / running / stalled / cancelled | none | none | none | per-unit status only | n/a | n/a | **Missing** (PB-005, PB-008) |
| Progress / time-to-completion | none | log lines | heartbeat to /dev/tty | n/a | n/a | n/a | **Missing** (docs admit it) |
| Galaxy tools | n/a | galaxy/*.xml | align, score, aggregate | n/a | n/a | n/a | Implemented, not verified |
| Docker / conda installation | n/a | install.sh, Dockerfile | yes | n/a | n/a | n/a | Implemented, not verified; `.dockerignore` copies real results (Reported) |

CLI-only features (no report counterpart): `validate-cohort`, `derive-amr-truth`, `audit-truth-labels`, `curate`, `build-ledger`, `discover-cohort`, `review-candidates`, `install-tools`. Report-only features (no CLI): none found. Features reachable only through stage scripts, not as CLI commands: `long_read_support`, `validate_structural_evidence`, `write_operational_override_report`.
