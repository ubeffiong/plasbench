# PlasBench independent audit of `main` (commit 5c041ec)

Date: 2026-11-17. Branch: `audit/reaudit-from-main`, created from `origin/main`. This replaces the earlier audit of `perf-audit-fixes`, which was done on a stale base (118 commits behind `main`, no web UI). That audit is kept in `baseline_perf-audit-fixes/` for comparison only.

**How to read the evidence.** Every row of `ISSUE_REGISTER.tsv` (53 rows) carries an evidence level:
- **EXECUTED**: I ran it and saw the result. 16 rows. Commands and outputs are in `TEST_LOG.md`.
- **Read by me**: I read the code on `main` but did not run it. 2 rows.
- **Agent-read**: a read-only exploration agent reported it and I did not re-check it. 35 rows. Treat these as credible risks, not proven defects.

Severity: 9 High, 29 Medium, 15 Low.

## 1. Scope and what was not done
- Audited: the whole repository at `origin/main` (CLI, stage scripts, adapters, scoring, statistics, report generator, and the web UI, `webui.py` + `ui.html`).
- Executed: scorer fixtures (real scripts, hand-calculated cases), the per-file test suite on Linux (Ubuntu WSL, real `minimap2`), failure injection on stage 4 with fake binaries (Linux), the web UI in real Chrome 157 against an isolated server and state folder, and the shipped real-cohort report in Chrome.
- **Not done:** no real bioinformatics tool or database was run; no full or real cohort benchmark; no 98-isolate report; no peak-memory or CPU profile beyond per-test wall time; no run on a HPC scheduler; no test of the web UI's Git, intake, update-check or desktop-icon features; the 35 agent-read rows are not re-checked; the new `intake.py`, `plaseval_*`, `simulate_validation.py` and most `report_fig_*` modules were read only at signature level.
- My Linux test copy was a `git archive` export without `.github/` and without the package installed, so 5 test failures there are probably artefacts of the copy (see `TEST_LOG.md`).

## 2. Overall assessment
`main` is a considerably more mature system than the stale branch suggested. It now has a three-task evaluation design (binning, reassembly, classification, each with its own headline metric), a pre-assembly short-read QC gate, truth-free assembly selection, a candidate-multiplicity report, run-table consistency checks, a pre-registration lock, an exact permutation test with a six-cluster floor, a banner for "primary analysis unavailable", and a web UI with a detached job runner, heartbeat, token and Origin checks, and loopback-only binding.

The weaknesses that matter for a publication are:
1. **The headline binning and reassembly endpoints can still be inflated.** Executed: a bin padded with 100 bp that aligns nowhere keeps `lw_bin_f1` = 1.0 and CPRR "correct". The strict columns drop (0.5 precision, 0.667 F1) but do not affect rank (MA-003). On the classification track, F1 stays 1.0 with 5,000 bp of junk (MA-004).
2. **Zero-plasmid isolates score 0.0, not undefined, for binners** (MA-001, executed).
3. **Failures and silent failures are not reliably distinguished from "nothing found"** (MA-005, 006, 007, 008; all executed on Linux). The stage reports completion when a sample's job died, records a tool that wrote nothing as `completed`, has no stall detection, and leaves the tool running after SIGINT.
4. **The web UI has a script-injection path** from crafted folder or cohort names (MA-043, executed in Chrome), and the terminal route runs any command with the token (MA-046, executed). Together they are code execution as the user from a name in a shared folder. Apostrophes in names also break buttons without any attack.
5. **Sleep or hibernate makes a live run show "interrupted", and Resume then starts a duplicate** (MA-039, executed).
6. **The only real-data result in the repository predates the independence rule** and rests on 1 of 10 isolates (MA-019).
7. **Defaults leave leakage and QC non-binding:** `EXCLUDE_DATABASE_OVERLAP=0` with 14 tools lacking release dates (MA-013), and QC mode `report` (MA-011). These are documented choices, but the manuscript run must set them deliberately.

| Dimension | Assessment |
|---|---|
| Architecture | Coherent. Duplicated helpers remain (MA-017, plus the metric-helper duplication listed in the baseline). Report generator is still very large. |
| Scientific validity | Strong design intent; endpoint loopholes above; several statistical consistency gaps (MA-025 to MA-028). |
| Computational reliability | Weak on failure states, stall detection, cancel and re-run. |
| Frontend (web UI) | Feature-rich and loopback-safe, with injection and state-handling defects. |
| Reporting | Good self-containment and no fabricated values found; denominator, missing-vs-zero and accessibility issues. |
| Publication readiness | **Not ready.** See section 8. |

## 3. What `main` fixed since the stale branch (verified by agents, selected items checked by me)
PB-011 (QC gate exists), PB-014 (three tasks), PB-021 (contradictory failure text gone), PB-031 (recommender truth leakage removed), PB-032 (rank sensitivity includes `lw_bin_f1`), PB-002 (candidate multiplicity module), PB-033 (minimum six clusters, exact test, minimum attainable p reported), silent headline fallback (now `unavailable`/`provisional` with a banner), run-table checks, synthetic-data guard, `equivalent` no longer "yes" without an interval. I did not re-verify each by execution.

## 4. The three reviewer questions on `main`
**Assembly selection.** `python/assembly_selection.py` (new). Candidates are written to `assembly_candidates.tsv`; policy `fixed` (default) or `quality` (N50 then contig count, truth-free); mode `off`/`report` (default)/`enforce`. By default the primary assembly is used and the choice is only recorded. Gaps: reused contigs are accepted without checking which assembler made them and are labelled with the current assembler name (MA-009); size window 1-10 Mb (MA-035). Status: **implemented, optional, not the default behaviour**. (Agent-read.)

**Short-read QC and rejection.** `python/short_read_qc.py` (new): PASS/WARN/REJECT before assembly, thresholds in `config/short_read_qc_thresholds.tsv`, rejects recorded as `rejected` rather than tool failures. Default mode `report` flags but proceeds; only integrity failures always exclude; thresholds are marked provisional; depth assumes a 5 Mb genome; no contamination screen (MA-011). Status: **implemented, non-binding by default**. (Agent-read; I did not run it.)

**Multiple candidates per plasmid.** `python/candidate_multiplicity.py` (new): per plasmid `n_candidates`, `best_candidate_coverage`, `combined_coverage`, `redundant_bp`, `n_fragments`, `n_chimeric_touching`; per candidate a role (primary, complementary fragment, redundant, chimeric, off-target, unmapped). It is descriptive only and never changes scores or ranks, so inflation is still not penalised in the headline (MA-003, MA-004, MA-036). Status: **diagnostic implemented, scoring unchanged**.

## 5. Duplication and consolidation
Carried from the baseline and partly re-confirmed: several matching rules and contamination definitions across `score_bins`, `bin_quality`, `bin_agreement`, `score_amr_placement`; two `number()` helpers with opposite blank semantics (MA-017); two "strict" precision definitions that disagree (MA-003); two env variables for one independence setting (MA-025); dashboard, explorer and Visual Quality views overlapping. `main` consolidated `read_truth_table` and `iter_fasta` into `plasbench_common`. No deletion is recommended without a dependency trace.

## 6. Integration map
Static report path: `plasbench` CLI → `scripts/00..08` → `adapters/` → `python/` → TSVs → `build_html_report.py` + `report_*` → static HTML with lazy iframes.
Web UI path: `ui.html` control → `fetch /api/<route>` with token → `webui.py` route → `Jobs`/`Terminal`/Git/intake services → detached `jobrunner` → `python -m plasbench` → bash stages → `.log/.pid/.alive/.exit` + `jobs.json` → polling (1 s console, 4 s job list) → UI. Agent-mapped: no UI call to a missing route, no control without a handler; unwired server routes: `runs/forget`, `git/show`, some git ops. I confirmed in Chrome that all 15 sidebar pages open with no console errors.

## 7. Answers to the 15 final questions
1. **Architecturally coherent?** Largely yes. The web UI, CLI and stages share a clean job model. Remaining issues are duplication and the monolithic report generator.
2. **Major workflows correctly implemented?** The happy path runs: the Linux suite passes 321 of 326 test files and the UI opens and runs a job. Failure, interruption, sleep and re-run paths are not reliable (MA-005 to MA-010, MA-039).
3. **Primary endpoints calculated correctly?** The calculations match their definitions in my fixtures, but two give misleading values: zero-plasmid binners (MA-001) and multi-chromosome contamination (MA-002). The padded-bin result (MA-003) is a design gap, not a coding error. Statistical intervals can exceed 1 (MA-028, executed).
4. **Tools compared fairly?** Better than before (three tasks), but the shared-sample rule, leakage defaults and track-unaware independence remain (MA-013, 014, 031).
5. **Every UI feature traceable to a backend operation?** For what I tested, yes: job start, cancel, resume, terminal, the 15 pages and the cohort controls reach real routes. Not tested: Git, intake, update check, settings writes, desktop icon.
6. **Backend outputs correctly represented?** Mostly; the shipped real report is stale relative to the rules (MA-019); skipped counted as failed (MA-018); missing shown as zero (MA-017); the UI shows 100% and "done" for exit 0 regardless of tool failures (MA-040).
7. **Disconnected, duplicated or abandoned implementations?** Duplicated yes (section 5); the unwired routes are few. `ranking_stability.py` silently omits one task (MA-026).
8. **Detect and recover from stalled runs?** No. Executed: a hung tool blocks the stage (MA-007); the UI shows "Running" indefinitely with `last_activity` unused (MA-040); sleep gives a false "interrupted" (MA-039); SIGINT leaves an orphan (MA-008).
9. **Resource use appropriate?** Not profiled at scale. Report size is a concern (18.4 MB for 10 isolates; MA-020). No global parallelism cap (agent-read).
10. **Can users trust results without reading source?** Not yet for the headline binning endpoints (MA-003) or for run completion state (MA-005, 040). Provenance banners help.
11. **Reproducible?** Good intent (fingerprints, preregistration lock, run-table checks). Weakened by reuse without stamping (MA-009), the stale shipped report (MA-019), and a test runner that stops at the first failure (MA-023, agent-read).
12. **What could invalidate the conclusions?** Padding inflation on the primary endpoints; zero-plasmid zeros; database lookup tools in the headline; a restricted tool shrinking the shared set; silent tool failures scored as empty results; selection of complete, long-read-supported, plasmid-bearing genomes only (MA-024).
13. **Fix before the next benchmark run:** MA-005, 006, 007, 008, 009, 010, 001, and set QC `enforce`, leakage exclusion and the assembler policy deliberately.
14. **Fix before a manuscript:** all of the above plus MA-003, 004 (endpoint inflation), 013, 014, 019, 024, 025 to 028, 031, and a real-data run under the current rules.
15. **To make it a robust platform:** section 9.

## 8. Remediation roadmap (nothing applied)
**P0 (scientifically wrong or invalid results, or unsafe):**
- MA-043: remove inline handlers and unescaped `data-run`; use event listeners and a JSON data island. Complexity S-M. Test: browser case with `a');window.__pwn=1;('` and `O'Neil`.
- MA-003/004: add an inflation-resistant co-primary or gate and a strict sensitivity row; unify the strict definitions. M. Test: the padded-bin fixture.
- MA-001: blank metrics on zero-plasmid truth; add a false-positive-bp measure. S. Test: zero-plasmid fixture.
- MA-005/006/008: per-PID waits, output-validating adapters, signal forwarding to process groups, status row for every unit. M. Test: the fake-binary cases in `TEST_LOG.md` as regression tests.
- MA-039: re-adopt a job whose heartbeat resumes; refuse Resume while the original pid is alive. S. Test: suspend/resume case.
**P1:** MA-044/045/046/047/048/049/050 (UI isolation, token handling, path validation, data-dir resolver, gitignore kind, hidden-answer storage); MA-007 stall detection; MA-009/010; MA-013/014/015; MA-019 regenerate the real report; MA-025 to 028; MA-031.
**P2:** MA-011/012 freeze QC thresholds and use enforce; MA-017/018/020/024/029/030/032 to 038; UI progress and states (MA-040/042).
**P3:** MA-021/022/052/053 and documentation drift.
**Quick wins (under a day):** MA-001, MA-016 (`is not None`), MA-018, MA-025, MA-028 clamp, MA-048, MA-049, the `.gitignore` kind, apostrophe fix.

## 9. Target architecture (incremental, preserving what works)
Keep the three-task scoring design, preregistration lock, run-table checks and detached job runner. Add: (1) a per-run `run.json` and a `units.tsv` with explicit states `queued → running → validating → completed | failed | skipped | cancelled | stalled`, written by the stage scripts and read by the UI (replacing exit-code-only completion); (2) adapters that must produce a sentinel to count as completed; (3) a supervisor in `lib.sh` with per-PID waits, signal forwarding and stall detection from log/output activity; (4) enforce-mode QC and assembly selection for the primary analysis, with thresholds frozen in the preregistration lock; (5) one metrics module and one `number()`; (6) the UI served with no inline handlers, a stricter CSP, a sandboxed or separate-origin report viewer, and the token exchanged without appearing in `argv`; (7) tests: the fake-binary failure cases, a browser smoke test of the page and injection cases, a report DOM-ID and link test, and a runner that tallies failures.

## 10. Open questions and disagreements
- Whether the primary headline should gate on unaligned sequence is an authors' design decision; the audit shows what the current definition does not penalise.
- Whether `TOOL_TIMEOUT_SECONDS` should stay unset (an owner decision recorded 2026-11-16) is a policy choice; the finding is the missing stall detection, not the default.
- The 35 agent-read rows need re-checking before any is quoted in a manuscript response.
