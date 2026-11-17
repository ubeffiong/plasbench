# Status of the 17 November 2026 audit findings

The audit (`audit-2026-11-17/AUDIT_REPORT.md`, `ISSUE_REGISTER.tsv`) raised 53 findings. Status after the fixes in this change: **34 fixed, 11 partial, 8 not fixed.** A finding is `FIXED` only when a test fails on the old code and passes on the new; the web window and CSP changes were checked by headers, static HTML and reasoning, not in a browser.

| ID | Severity | Status | Note |
|---|---|---|---|
| AU-001 | Critical | FIXED | Two runs that share TMP_DIR wipe each other's status shards and crash markers. The first run exits 0, prints '... |
| AU-002 | High | FIXED | Importing a study bundle can plant an HTML file that the window serves as a report without a Content-Security-... |
| AU-003 | High | FIXED | NMI, Variation of Information and ARI are perfect (1.0, 0.0, 1.0) when a whole plasmid is missed, because the... |
| AU-004 | High | FIXED | A gene on a contig the binner left out of its bins file is scored correct_plasmid: membership.get(query, query... |
| AU-005 | High | FIXED | The word-boundary regexes fail on OXFORD_NANOPORE, PACBIO_SMRT (underscore), run-together names (IlluminaMiSeq... |
| AU-006 | High | FIXED | Nine of the 1,099 'independent' (long-read-only, polish none) isolates are not independent: six name an Illumi... |
| AU-007 | High | FIXED | 'Runs completed' is completed/scored with no clamp: the shipped real-cohort report shows 1000% (10/1), which l... |
| AU-008 | High | FIXED | 12 of 16 adapters exit 0 with an empty prediction when the tool's output is missing; the guard accepts any fil... |
| AU-009 | High | PARTIAL | process-group cancel and orphan recovery added; SIGKILL cannot be trapped, pid reuse can cause a false refusal, WSL pids differ from Windows pids |
| AU-010 | High | PARTIAL | `stalled` and `completed_with_warnings` shown; no default tool timeout (the confirmed default is no limit, and a limit would change scores) |
| AU-011 | High | FIXED | Stage 4 exits 0 when every tool failed; the run continues to the report, and the job shows done at 100%.... |
| AU-012 | High | FIXED | A tool marked failed that still has score rows is not flagged; a blank metric is silently dropped (a tool's me... |
| AU-013 | High | FIXED | The shared-sample restriction is a cliff: a tool silently absent from samples shrinks everyone's ranking set (... |
| AU-014 | High | FIXED | Docs say all long-read-first rows are headline-eligible and four species reach 20 independent studies; under t... |
| AU-015 | Medium | FIXED | 'Chromosomal contamination' is FP_bp/(true_plasmid_bp+FP_bp), not 'fraction of all truth-mapped bases'; it sho... |
| AU-016 | Medium | FIXED | 'Methods compared' is len(leaderboard) over the first task (1 for 4 tools); 'Leading method MOB-recon' is the... |
| AU-017 | Medium | FIXED | Table says 'validated, 1 long-read-first isolate across 3 held-out studies' while the leaderboard says '< 5 in... |
| AU-018 | Medium | FIXED | Run metadata omits the PlasBench version, database versions and paths, settings and container; a local path le... |
| AU-019 | Medium | FIXED | circular_plasmid_recall is the share of circular truth plasmids reaching 90% coverage; recovered_complete_circ... |
| AU-020 | Medium | FIXED | AMBIGUOUS, CHIMERIC, UNPLACED and SHORT contigs are dropped from TP/FP/FN/TN, so false calls on unplaced conti... |
| AU-021 | Medium | NOT FIXED | duplicate FASTA/PAF/table readers not unified: a repository-wide refactor that needs its own change |
| AU-022 | Medium | PARTIAL | Holm numeric and CPRR boundary tests added (`test_guard_boundaries.py`); synthetic/real refusal, secret-commit and TP-clamp mutants not yet covered |
| AU-023 | Medium | FIXED | runner counts skipped checks; `REQUIRE_NO_SKIPS=1` fails on any (CI workflow not edited: needs workflow scope) |
| AU-024 | Medium | FIXED | Commands typed into the terminal are stored verbatim in sessions.jsonl and terminal_history.jsonl (including e... |
| AU-025 | Medium | FIXED | The commit scanner misses password: in .yml, ZENODO_TOKEN= in .cfg and NCBI_API_KEY= in a file named config.lo... |
| AU-026 | Medium | PARTIAL | download checksums verified or recorded for Platon, PlaScope and MOB-suite; release, Dockerfile and gplas2 pinning not done |
| AU-027 | Medium | FIXED | truth_technology and truth_assembly_strategy disagree on 101 rows (66 long_read vs long_read_first_hybrid, 32... |
| AU-028 | Medium | FIXED | All 7,227 rows are curation grade B, so Tier 1 and grade A are unreachable; the tier-1 population is empty and... |
| AU-029 | Low | FIXED | identity_valid returns True when a sample has no provenance record, applying identity criteria with unknown po... |
| AU-030 | Medium | FIXED | Stage 8 checks only that pred_<tool>.plasmid.fasta is non-empty; an uninstalled tool is 'skipped' and an older... |
| AU-031 | Medium | FIXED | Retries re-run the same command into the same output directory without cleanup (tools that refuse an existing... |
| AU-032 | Medium | FIXED | Uses one global THREADS for every tool, so thread-seconds and CPU utilisation are wrong when per-tool threads... |
| AU-033 | Medium | PARTIAL | stage timing and per-attempt resources recorded; blank-memory note untested |
| AU-034 | Low | NOT FIXED | needs a measured pilot, not code |
| AU-035 | Low | PARTIAL | failure reasons, database pre-flight for three tools and empty-cohort checks; malformed-FASTA check and other tools' pre-flight not done |
| AU-036 | Low | FIXED | The compression-ratio check runs only above 50 MB and the cap is 8 GiB, so a low-ratio bomb below 8 GiB is acc... |
| AU-037 | Low | FIXED | Windows reserved names (CON) and a trailing dot (foo. aliases foo) are accepted as study names.... |
| AU-038 | Low | FIXED | config/local.env (holding the NCBI key) is written with the default umask; some scripts send the NCBI key in U... |
| AU-039 | Low | PARTIAL | Forget, remote Remove, Create on GitHub, git sign-in wired; `git/show` deliberately unwired |
| AU-040 | Low | FIXED | Two validate calls have no catch (Start/Run keep their previous state on a network error); ~30 empty catch blo... |
| AU-041 | Medium | PARTIAL | one task vocabulary, task explanation and leaderboard download; rank help and exit-0 wording not done |
| AU-042 | Low | FIXED | Stale counts: '23 tools and three baselines' (20 real tools + 3 baselines + 5 demo stand-ins), 58 CLI subcomma... |
| AU-043 | Low | FIXED | seven dead functions removed; `GPLAS_THREADS` kept (documented as having no effect on gplas) |
| AU-044 | Low | PARTIAL | 21 subprocess sites bounded; five Popen pipelines and three analysis scripts left |
| AU-045 | Medium | PARTIAL | `classify_method` is now tested on real cohort tokens against an independent oracle and the cohort count is derived; the ledger and adversarial tests still pin line positions and known optimism |
| AU-046 | Medium | NOT FIXED | needs real binaries and a scheduled job; not possible here |
| AU-047 | Low | NOT FIXED | two definitions of gene recovery kept: choosing one changes scientific numbers and needs a decision |
| AU-048 | Low | NOT FIXED | undefined-handling difference kept: aligning it changes published numbers and needs a decision |
| AU-049 | Low | FIXED | scores.tsv is truncated in place then appended: a kill mid-merge leaves a partial file.... |
| AU-050 | Low | NOT FIXED | CI permissions and action pinning need workflow scope on the token |
| AU-051 | Medium | NOT FIXED | disclosed in METHODS; a with/without-exclusion report not built |
| AU-052 | Low | FIXED | intervals for proportions are clipped to [0, 1] (paired differences to [-1, 1]) via `resampling.clamp_interval`; the method itself and its coverage under-run are unchanged and documented in `docs/STATS_VALIDATION.md` |
| AU-053 | Low | PARTIAL | README states which code built the cohort-1 results; not rebuilt because the sample sheet is not in the folder |
