# UI and HTML report audit

**Scope.** This covers only the static HTML report on the audited branch (`perf-audit-fixes`). The live web UI (`plasbench/webui.py`, `ui_schema.py`, `data/ui.html` on `origin/feat/ui-*` branches) was not read or tested. Its forms, job control, polling, cancellation and state handling are unaudited.

**What was and was not done.** The report is a static HTML file with embedded JS and two iframes. Findings below come from an exploration pass that read `python/build_html_report.py`, the templates and the three sample reports (`results_demo`, `results_real_cohort1`, `results_audit`), and from my own checks of the cited lines (marked *checked*). **I did not drive the report in a browser. No screenshots were taken.** No headless browser was used; `node` exists on this machine, but I did not run the report JS. So no control was verified by clicking it.

## Structure
No inline `onclick`; handlers are assigned in JS. Interactive elements: score-table filters, status filter, click-to-sort on every `table.sortable th`, CSV export, Visual Quality controls (`#vq-*`), protein filters, plasmid viewer, 3D views, enterprise dashboard iframe, evidence explorer iframe. No external CDN or image dependencies were found; fonts are inlined.

## Confirmed or checked findings

| ID | Finding | Evidence |
|---|---|---|
| PB-021 *checked* | Summary says failed runs are excluded from means; other sections say a failure counts as F1 = 0 | build_html_report.py:484-486 vs 509, 1040, 2554 |
| PB-019 *checked, expression reproduced* | recall 0.0 treated as 1.0 in the "High F1, missed plasmids" warning | build_html_report.py:468 |
| PB-020 *line 674 checked* | Missing renders as zero | number() returns 0.0 for blank |

## Reported by the exploration pass (not re-verified)

| ID | Finding |
|---|---|
| PB-023 | `results_real_cohort1`: leaderboard has n_samples=1 (tier filter) with mean_plasmid_recall 0.0000 for all tools; Summary shows 10 isolates and 22 plasmids |
| PB-022 | "Runs not completed" counts skipped runs |
| PB-025 | iframes bypass the 6 MB budget; 18.4 MB for 10 isolates |
| PB-026 | README claims one self-contained file; downloads and external mode need siblings |
| PB-024 | real-cohort report not regenerable from the repo |
| PB-028 | dangling `#enterprise` anchor in the real-cohort report |
| PB-027 | mouse-only sort headers; non-total sort comparator; 7 of 32 SVGs lack `role=img`; no `<noscript>` or dark mode in the demo report; CSV formula injection |
| — | Dashboard uses `truth_quality_tier` from the cohort file, which INDEPENDENT_REVIEW.md says disagrees with provenance tier for 8 of 15 short-read-first isolates |
| — | Output is not byte-reproducible (timestamp, `Math.random` uid) |
| — | Dashboard, explorer and Visual Quality duplicate content and sync through `postMessage` and `setTimeout` |

## Spot-checks of values (reported)
Demo `mob_like` ranking 0.9875 ↔ "0.988" OK; demo `weak_like` precision 0.9285 ↔ 0.929 OK; real cohort `mob_recon` 0.8381 ↔ "0.8381 on 1 shared" OK; demo failed runs OK; demo `gplas_like` 0.8195 shown as 0.819 and 0.820 (double rounding). No fabricated or placeholder values found; the random-data generators of the vendored templates were removed.

## Suggested interface improvements
1. Every ranking value carries its n and denominator; warn below n = 5.
2. One statement of the failure policy, generated from the same constant the scorer uses.
3. Distinguish failed, skipped and not-measured everywhere (including charts).
4. A short "how this was calculated" popover per metric, linked to METHODS.
5. Make sort headers buttons with `aria-sort`; add `role=img` and text alternatives to SVGs.
6. Pick one of dashboard / explorer / Visual Quality and lazy-load alignment data.
7. A link-check and DOM-ID test in CI (currently only `node --check`).
8. Show QC status and exclusion reasons per sample once a QC gate exists.
