# PlasBench independent audit: executive report

Audit date: 2026-11-17. Mode: read-only on project code, config, references and results. Everything written for the audit is in this `audit/` directory; test runs used a scratch copy of the tree.

**Evidence labels used throughout**
- **Executed**: I ran it and saw the result (commands in `TEST_LOG.md`).
- **Static**: I read the code; I did not run it. Treat as a credible risk, not a proven defect.
- **Reported**: an exploration pass read it and I did not re-check it.

Counts: 36 registered issues in `ISSUE_REGISTER.tsv` (14 High, 18 Medium, 4 Low). Eight are marked Reproducible: PB-001, 002, 003, 004, 012 and 029 by running real scripts on fixtures or the suite, PB-019 by reading the line and reproducing the expression in Python, and PB-021 by reading the contradicting lines. The other 28 are Static or Reported; the register's Reproducibility column says which.

## 0. Scope limit you need to know first

**The live web UI was not audited.** I audited the checked-out branch, `perf-audit-fixes` (HEAD `5b4f74c`), plus its uncommitted working-tree changes (`config/config.sh`). That branch has no web server, API routes or interactive front end: its only "frontend" is the static HTML report. The repository's git history shows a separate web UI on other branches. For example, `origin/feat/ui-existing-databases` contains `plasbench/webui.py` (1,277 lines), `plasbench/ui_schema.py` and `plasbench/data/ui.html` (3,069 lines), and is 48 commits ahead of the audited branch. `~/.plasbench/ui/` on this machine holds job logs and a `server.json` from 13-14 November. I only listed those files; I read none of that code and tested none of it.

Consequences: the mandate items on UI-to-API tracing, forms, polling, job state, cancellation from a UI and state management are **not covered** for the web UI. Where this report says "no API" or "no live dashboard" it means on the audited branch only. A second pass on the UI branch is needed before the audit can claim full coverage.

## 1. Overall assessment

PlasBench is not a loose collection of scripts. It has a consistent spine: one CLI, numbered stage scripts, a tool-capability registry, per-unit status files, fingerprinted reuse in stage 4, and a large and fairly honest body of documentation (including an internal independent review). The statistics layer is better than most: resampling is at cluster level, Holm correction is applied, and pre-registration and provenance are taken seriously.

The weaknesses are concentrated in four places, and they matter for a publication:

1. **Scoring rewards output the benchmark cannot see.** Executed fixtures show base-level precision and F1 stay at 1.0 when a tool adds 5,000 bp of non-aligning sequence, emits duplicates, or shatters a plasmid into 20 pieces. Zero-plasmid isolates score 0.0 rather than undefined for binners.
2. **Failure and absence are not reliably distinguished from "nothing found".** Adapters turn missing output into an empty prediction; stage 4 and 5 end in a bare `wait`; there is no default timeout. Static evidence only, but the pattern is consistent across files.
3. **There is no QC gate that can reject.** The only gate is advisory, runs after scoring, and checks two assembly properties. A truncated FASTQ passed input validation in an executed test.
4. **The report can say two incompatible things.** The Summary says failed runs are excluded from means; three other places say they count as zero. The real-cohort leaderboard rests on 1 of 10 isolates while the Summary shows the whole cohort.

Also: the regression runner is fragile. With the uncommitted `config.sh` edits in the working tree, `plasbench test` stops at test 13 and never runs the other ~200 files, because a line-number-pinned ledger test fails and `set -e` aborts (PB-029). That test passes against the committed `config.sh`, so this is not a committed-tree defect. Run one file at a time, 209 of 216 passed on Windows/Git Bash (`TEST_LOG.md`).

| Dimension | Assessment | Basis |
|---|---|---|
| Architectural maturity | Moderate. Coherent spine, but duplicated metric definitions and a 2,600-line report generator | Static |
| Scientific validity | Mixed. Cluster-level statistics are sound; endpoints have loopholes (PB-001/002/003/013/014/015/016) | Executed + Static |
| Computational reliability | Weak on failure handling, timeouts, cancellation and re-runs | Static |
| Workflow integrity | Moderate. Per-unit status exists; run-level state and prerequisite checks do not | Static |
| Frontend/report quality | Good on self-containment and no fabricated values; weak on denominators, missing-vs-zero and accessibility | Reported + Executed (2 items) |
| Usability | Good documentation and error messages in the input validator; heavy for non-developers; Windows is second-class | Static |
| Publication readiness | **Not ready.** See section 5 | |

## 2. The three reviewer questions

### 2.1 Assembly selection
| Question | Answer | Status |
|---|---|---|
| Can PlasBench select between candidate assemblies? | No. One assembler is chosen globally by `ASSEMBLER` (config.sh:498; 03_assemble.sh:123-153) | Missing |
| What decides the choice? | The configuration value only | Existing |
| Are assembly QC metrics available? | Partial. `assembly_qc_gate.py` (size, GC spread) runs post-scoring; `compute_assembly_stats.py` runs on the truth reference, not the short-read assembly; `assembly_adequacy.py` needs truth | Partial |
| Are alternatives retained? | No (except the separate Trycycler track in stage 7) | Missing |
| Can users specify an assembly? | Yes by placing `data/<sample>/contigs.fasta`, but it is silently reused with no provenance check (PB-009) | Partial |
| Is the choice reproducible? | Yes, deterministic given config | Existing |
| Does it avoid selecting on downstream benchmark performance? | Yes, trivially, because it never selects | Existing |
| Proposal | Per-sample candidate assemblies with pre-registered, truth-free selection criteria (length, N50, contig count, depth uniformity, GC outliers); retain all; record choice and criteria | Proposed |

### 2.2 Short-read QC and rejection policy
| Question | Answer | Status |
|---|---|---|
| Formal QC gate before assembly? | No. fastp runs with a length filter only (03_assemble.sh:92-95); fastp.json is never read | Missing |
| Raw reads assessed? | Only in `--local-inputs` mode (`validate_local_inputs.py`): file existence, gzip magic, first 1000 mate names, capped count | Partial |
| Integrity, pairing, quality, depth, adapters, contamination evaluated? | Pairing partly. Integrity not fully (Executed: truncated R2 passed, PB-012). Quality, adapters, contamination: no. Depth: computed vs truth in stage 2 as a stratifier only | Mostly missing |
| PASS/WARN/REJECT? | No. Gate states are pass / flagged / not_evaluable | Missing |
| Does rejection prevent downstream execution? | No. The gate is advisory and runs in stage 6; stage 8 warns and continues | Missing |
| Thresholds configurable and documented? | Two thresholds (`ASSEMBLY_QC_MAX_SIZE_MB`, `ASSEMBLY_QC_MAX_GC_SPREAD`) are; min contig length 10,000 is hard-coded; thresholds are not written to the output | Partial |
| Exclusions recorded in the report? | Flags appear in the report, but nothing is excluded, so there is nothing to record | Missing |
| Proposal | Stage 2.5 `qc`: PASS/WARN/REJECT manifest per sample; REJECT blocks stage 3; thresholds in config and echoed in the manifest and report | Proposed |

### 2.3 Multiple reconstruction candidates per plasmid
| Question | Answer | Status |
|---|---|---|
| Accounts for all candidate outputs? | Yes at the base level (union over all records) | Existing |
| Identifies several candidates on one reference plasmid? | Partial: bin outcomes (`fragmented`, `merged`), CPRR split rule (0.1), `--per-plasmid-out` | Partial |
| Fragments vs duplicates? | Partial: `redundant_pred_bp` exists but is diagnostic only (Executed: 100 for a duplicated plasmid) | Partial |
| Best-candidate coverage? | Not a reported column | Missing |
| Combined non-redundant coverage? | Yes, this is what recall uses (union of intervals) | Existing |
| Off-target and chimeric sequence? | Contig-level classes CHIMERIC/UNPLACED exist in `contig_classification.py`; base precision ignores unmapped output (Executed, PB-001) | Partial |
| Collective recovery when no single candidate is complete? | Counted as recovered by base recall; CPRR requires one bin | Partial |
| Avoids rewarding output inflation? | No for base-level endpoints (Executed, PB-001/002). CPRR and lw precision partly do | Missing for base level |
| Proposal | Per-plasmid table: n_candidates, best-candidate coverage, combined coverage, redundant bp, off-target bp, chimeric flag; report beside F1 and rank on an inflation-resistant measure | Proposed |

## 3. Duplication register

| Item | Where | Authoritative | Note |
|---|---|---|---|
| Matching rules (5): gated Hungarian, ungated Hungarian, per-bin best, record-level Hungarian, contig best | score_bins, bin_quality, bin_agreement, score_amr_placement, contig_classification | `score_bins` ungated for the headline | Different tables will disagree by design; label each |
| Contamination definitions (2) | score_bins.py:433 (reference bp); bin_quality.py:126-173 (query bp) | Pick one and rename the other | Reported |
| Interval union helpers (6) | plasbench_common, score_bins, bin_quality, contig_classification, feature_preservation | plasbench_common | Merge semantics differ for touching intervals |
| Cluster definitions (3) | aggregate_results, headline_design, power_analysis | headline_design | Reported |
| PAF quality-gate defaults | score_bins/score_amr_placement 1/0/0/0 vs bin_quality/feature_preservation/alignment_accuracy env 200/0.9/20/0.2 | One shared config | Reported |
| Report views | dashboard, explorer, Visual Quality section | Decide one | Reported |
| Unreferenced functions | `scorable_truth.open_text`, `aggregate_results.format_rate` | Safe-to-remove candidates after a final grep | Reported |

I did not recommend deleting anything. Each needs a dependency trace first.

## 4. Integration map (audited branch: no web server or REST API; see section 0)

`plasbench/cli.py` (42 subcommands) → `scripts/00..08_*.sh` + `lib.sh` → `adapters/adapt_*.sh` → `python/*.py` → TSVs in `results*/` → `python/build_html_report.py` and helpers → static HTML (+ two `srcdoc` iframes). The "API" layer is the CLI and environment variables. Details of what is wired and what is not are in `FEATURE_MATRIX.md`.

## 5. Answers to the 15 final questions

1. **Architecturally coherent?** Largely yes in structure; duplicated metric definitions and a monolithic report generator are the weak points. (Static)
2. **Major workflows correctly implemented?** The happy path works: the synthetic demo ran to completion (exit 0 in the scratch copy). Failure, re-run and cancellation paths are not reliable. (Executed + Static)
3. **Primary endpoints correct?** The calculations I tested match their documented definitions, but several are wrong for the question being asked: zero-plasmid isolates (PB-003), multi-chromosome contamination (PB-004), and loopholes in base-level F1 (PB-001/002). (Executed)
4. **Tools compared fairly?** Not yet. Classifiers and reassemblers share a task (PB-014); one taxon-restricted tool can shrink everyone's sample set (PB-016); database leakage is off by default (PB-015). (Static)
5. **Every UI feature traceable to a backend operation?** Unknown for the web UI, which I did not audit (section 0). For the static report I did not trace every control interactively: it has no inline handlers, handlers resolve in the demo report, and there is one dangling anchor in the real-cohort report. (Reported)
6. **Outputs represented correctly in dashboard and report?** Spot-checked headline values match; denominators and missing-vs-zero do not (PB-019 to PB-023). (Reported + Executed)
7. **Disconnected, duplicated or abandoned implementations?** Duplicated yes (section 3). No orphan Python modules; one config variable (`GPLAS_THREADS`) is unwired; the real-cohort report cannot be regenerated (PB-024). (Static)
8. **Detect and recover from stalled runs?** No. There is no default timeout, no stalled state, no cancellation handling (PB-007, PB-008). (Static)
9. **Resource use appropriate?** Not measured at scale. Report size is a concern (PB-025). Parallelism has no global cap. (Static)
10. **Can users trust results without reading source?** Not yet. The report contradicts itself on failure handling and hides n. (Executed for PB-021)
11. **Reproducible?** Good intent (fingerprints, provenance, pre-registration); undermined by silent reuse (PB-009), an unregenerable real-cohort report (PB-024), and a test runner that a routine config edit can silently truncate (PB-029).
12. **What could invalidate the conclusions?** Output inflation under base-level F1, zero-plasmid scoring, database leakage into headline ranks, shared-sample collapse, silent tool failures scored as valid empty predictions, truth built from labels correlated with tool databases.
13. **Fix before the next benchmark run:** PB-005, 006, 007, 009, 010, 011, 012, 029 (reliability and QC); PB-003 and PB-021 (cheap and high value).
14. **Fix before a manuscript:** all of the above plus PB-001/002/014 (endpoint design), PB-015/016 (fairness and leakage), PB-017, PB-023, PB-024, PB-032, plus an executed end-to-end run on a real cohort with at least one real tool in CI.
15. **To make it a robust platform:** see `TARGET_ARCHITECTURE.md`: a run manifest with explicit states, output-validating adapters, a pre-assembly QC gate, one metrics module, and a report built from a single results JSON.

## 6. Disagreements and open questions
- Whether base-level F1 should remain the classifier headline is a design decision for the authors. The audit shows what it does not penalise; it does not decide the endpoint.
- Whether `plsmd` and `plassembler` belong in the same task as contig binners is a scientific scoping decision (PB-014).
- I did not verify the Static items by execution. Resolving them needs fake-binary failure injection (listed in `TEST_LOG.md` as not done).
