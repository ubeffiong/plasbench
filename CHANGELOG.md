# Changelog

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

The v0.1.x series was renumbered on 2026-09-09 from an earlier, denser
v0.1.0-v0.2.8 sequence (19 tags) down to 5 milestone releases. Each entry
below folds in every change from the tags it supersedes -- nothing from that
history is lost, only the numbering is cleaner. See
[docs/releases/](docs/releases/) for the full per-version notes.

## [Unreleased]

### Added -- AI help: hardening review, a folder you choose, file plans, window actions, guided flows (21 November 2026)
- **Review.** The reply parser had a quadratic pattern (60,000 spaces took 36 s and froze the window's thread): fixed, with fuzz and size tests. A stream that ended without a finish was shown as complete: it is now marked cut and the pane offers Continue. A service line is capped at 1 MB and an answer at 8 MB. The key file is written with a unique temporary name and retried on Windows (six concurrent writers used to fail). A command with a lookalike or invisible character is refused. A GET from another origin is refused on every AI route. See `docs/AI_HELP.md` (threat model) and `docs/qa/AI_UI_REVIEW.md`.
- **The assistant never opens your files.** If you choose a folder, PlasBench itself reads names, sizes and the first lines, shows you what it found and sends a summary only when you press Share. Folder content is treated as hostile data.
- **File plans.** `mkdir`, `copy`, `move`, `write_sheet`, `patch_sheet` only, inside the chosen folder, with a dry run, a diff for sheets, a sheet check before Apply, a journal, rollback, cancel and Undo.
- **Window actions** (`pb-ui`): go, setting (never the assistant's own, secret, path or scoring-decision settings), prefill, open, install, runtime, flow; each validated by the server and done through the window's existing functions.
- **Guided flows that work without a model**: set up a run from my folder, fix my sample sheet, install the tools I need, add my own tool, why did my last run fail?
- **Retrieval.** `docs/AI_CAPABILITIES.md` (what PlasBench and the assistant can and cannot do) is delivered by retrieval for navigation, setup and file questions, so the permanent prompt stays at about 540 tokens. Off-topic questions send no excerpt. The gold set is now 51 in-sample plus 78 held-out questions.
### Fixed -- finished tools were re-run because the memory budget changed (21 November 2026)
- **Stage 4 reuse.** The check that decides whether a tool's earlier result can be reused counted every `<TOOL>_*` setting except `_THREADS`, including `<TOOL>_MEMORY_GB`, whose default is computed from the memory that is free when the run starts. On a resume the budget could differ by a gigabyte, the tool was judged "changed" and run again, for no scientific reason (and `test_tool_result_fingerprint.sh` failed now and then on CI for the same reason). `_MEMORY_GB` is now left out like `_THREADS`; any other changed setting, a new tool version, new inputs or new reads still re-run the tool.

### Changed -- AI help: declaration, questions, general knowledge, no usage cap (21 November 2026)
- **Declaration.** The first-use notice, a line that stays under the chat, `plasbench ask` and the model's own instructions now say that the assistant cannot see your files (FASTQ, FASTA, sheets, results, logs, databases, settings), only the documentation and what you send.
- **It asks.** When a missing fact decides the answer it asks one short question with quick-reply buttons (a button only sends text; nothing runs). The question is kept in the chat history it is sent next.
- **General knowledge.** Closely related questions (plasmids, sequencing, resistance genes, conda, Docker, WSL) may be answered from the model's own knowledge, marked "General knowledge:"; PlasBench facts still come only from the documentation and it must not invent commands or options.
- **No usage cap.** `AI_DAILY_TOKEN_CAP` now defaults to 0 (none; it was 200,000) and answers may use 2,000 tokens (600 in Brief; it was 700 and 300); an answer cut by the model's length limit offers **Continue**. The system prompt grew from about 410 to about 480 tokens for the new behaviour. The providers' own limits still apply.

### Added -- AI help: ask about PlasBench in the side panel, with commands you can run (21 November 2026)
- **An assistant that answers from PlasBench's own material.** The new **AI help** tab of the side panel (top-bar button, Alt+Shift+H) and `plasbench ask` search a compact index of the guides, FAQ, workflow stages 0-8, tool table, Settings, metric and window help, the whole command line (built from the parser), failure signatures and exit codes (`plasbench/data/ai_kb.json.gz`, built by `python/build_ai_kb.py`, shipped as package data, kept current by a test) and answer with cited sources. Retrieval is BM25 with exact-command, error-string, synonym and misspelling handling: 51 of 51 gold questions find an acceptable source in the top three. About 1,570 tokens per question (410 fixed, about 1,400 of excerpts), answers capped at 700 tokens (300 in Brief).
- **Free models only, native sign-in.** Providers: OpenRouter (free models, sign-in in a small pop-up with OAuth PKCE; no key is pasted), Hugging Face (public PKCE app, client id from `AI_HF_CLIENT_ID`) and a model on your own computer (Ollama, LM Studio: nothing leaves the computer). A model is offered or called only when its price fields are all zero in the provider's live list, re-checked at request time; routers that can pick a paid model are never used; a limit falls back to the next free model only. The key is stored in `~/.plasbench/ai/` (mode 0600) and never appears in a response, log, job, manifest or issue report. A notice is shown before the first question (what is sent, to whom, the free-model logging caveat, how to sign out).
- **Commands you can run, safely.** A suggested command is a card with where to run it (PlasBench's Terminal tab, Windows PowerShell, Ubuntu (WSL) terminal) and buttons Run in PlasBench (only when it is one plain `plasbench` command that the real parser accepts; it goes through the usual confirmation and Jobs, with one more confirmation for install, upgrade and stop), Copy and Open Terminal tab. Nothing runs by itself; text in excerpts or command output is data; a model's format slips are shown as plain text and never become buttons. After a run, Send result sends the last 40 lines with folders, user name, e-mail addresses, keys and IP addresses removed, only when you press it.
- Settings `AI_HELP_ENABLED`, `AI_PROVIDER`, `AI_MODEL`, `AI_DAILY_TOKEN_CAP`, `AI_BRIEF`, `AI_FREE_FALLBACK`, `AI_HF_CLIENT_ID`, `AI_HF_USE_CREDITS`, `AI_LOCAL_BASE`; network table rows for OpenRouter and Hugging Face; `plasbench ask` and `plasbench ai status|signout`; `docs/AI_HELP.md` (including the providers considered and why the others were not built), a USER_GUIDE section, FAQ Q77, a SECURITY.md note; `.gitignore` keeps local credential files out.
- Tests (stub servers, no real service): `test_ai_kb.py`, `test_ai_prompt.py`, `test_ai_actions.py`, `test_ai_providers.py`, `test_ai_routes.py`, `test_ai_cli.py`, `test_ai_secrets_guard.py`, `test_ai_ui_browser.py` (real browser, `PLASBENCH_BROWSER_TESTS=1`). Not verified here: a real OpenRouter or Hugging Face sign-in, a real model's answer, real free-tier limits.

### Changed -- the report's metric tables open as a chart per question, and the multiplicity charts are compact (21 November 2026)
Presentation only: no number, rank, threshold or score changes, and every metric is still in the report.
- **Visual summary first.** Each leaderboard, graded-recovery, scoring-additions, contig-layer, outcome, sequence-accuracy, bin-quality, performance, composite, feature and gene-order table now opens as a compact chart grouped by plain-language question ("How accurate are the bases?", "How many plasmids come back whole?", "How well are contigs grouped?"): one numbered dot per tool on one axis per metric, a ring and a star on the best, a whisker for the interval, run-outcome counts and not-assessed metrics as plain values, and the alignment error shares as one stacked bar per tool. A *Chart* / *Heatmap* switch shows the same rows as rank-shaded cells. The full grid (sort, find tool, heatmap, collapse groups, CSV) is kept under **All N metrics**; it stays open when JavaScript is off and when printing.
- **Drill-down.** Click a mark, a metric or a tool chip to open a drawer under the chart: the exact value, interval, n, evidence tier, direction and definition, the isolates behind it (best to worst, outliers flagged, linked to their rows), the same metric for every tool, and a link into the full table row. Tool chips filter (tick or untick); keys: arrows move between marks, Enter opens, Escape closes. Hover or focus shows the value, interval, n and rank.
- **Honesty kept.** A metric that was not assessed is a hatched dash with the reason, never zero and never placed or shaded; a row with no direction, fewer than two assessed tools, or all tools tied is not ranked and says why with one information mark instead of a repeated sentence; one tool alone is drawn on a fixed scale with "only one tool assessed, so no ranking"; ties share a rank; the direction arrows and the best-in-row star stay visible. The chips show the rank the leaderboard gives, or a labelled mean rank where the table has none.
- **Shorter.** The table legend is one line and each row's "not shaded" note is an icon with a tooltip. The metric-by-tool tables take about half the height they did.
- **Reconstruction multiplicity.** The two 760-px charts are replaced by one fixed-height row per tool (where the predicted sequence went, best single candidate against all candidates combined, and what happened to each reference plasmid); a tool opens into its per-plasmid table and its tracks (each closed, height-limited). The earlier charts and the table are kept under *Full-size charts* and *All values*.
- Tests: `test/test_compare_summary.py` (node view-model tests, the honesty rules, the summary's numbers equal the grid's and the original table's cells on the demo report, compact multiplicity).

### Fixed -- the documents said no real-data run exists (21 November 2026)
- **FAQ Q22 and the statements that rest on it** (FAQ, Scientific Guide, implementation catalogue) said "No" to "Has any of this been run on real data?". A real run exists: `results_real_cohort1` (PlasBench 0.2.3, 10 public isolates, three real tools and a baseline, 40 score rows). The answer now says what it shows and what it cannot: it works on real reads, it cannot rank tools (one Tier-2 reference, run-level tables only), and a run large enough to rank is still the largest open item. Dated reviews and audits (`INDEPENDENT_REVIEW`, `EXTERNAL_REVIEW_LOG`, `QA_RESULT`, `audit/`) are left as the records they are.

### Added -- every annotation tool can be installed and switched on or off from the Workflow (21 November 2026)
- **One switch per caller.** `ANNOTATE_WITH_MOB_TYPER`, `ANNOTATE_WITH_ABRICATE`, `ANNOTATE_WITH_AMRFINDER`, `ANNOTATE_WITH_ISESCAN` and `ANNOTATE_WITH_BARRNAP` (default on; they only matter while `RUN_REFERENCE_ANNOTATION=1`). A caller switched off is not run and is recorded as not evaluated with the switch named, never as "no feature found"; an annotation made with fewer callers is never reused from the cache of one made with all of them.
- **Workflow.** Five new rows under *Annotate the reference* (switch, install state, Install button), and install state with an Install button on the cards of QUAST, MultiQC, protein annotation (Bakta) and difficulty features (samtools, deadends). The Install button opens the usual consent dialog. *Install all enabled tools* and the offer before a run now include these tools when their switch is on (an *auto* switch is left alone). Checked by `test/test_support_tools.py`, `test/test_annotation_parallel.py` and the existing UI tests; not looked at in a browser.

### Added -- publishing files for Galaxy, bio.tools, Bioconda / BioContainers, WorkflowHub and F1000Research (21 November 2026)
- **What each platform needs, checked.** `docs/publishing/README.md` says per platform what is ready, what was verified and what only the maintainer can do (an account, a token, a submission, a DOI); nothing was submitted. BioBuntu documents no way to add a third-party tool, so nothing was prepared for it.
- **bio.tools.** `docs/publishing/biotools.json`, validated against the official biotoolsSchema; its EDAM terms were looked up in the current EDAM release.
- **WorkflowHub.** A CWL workflow of the align, score and aggregate steps (`workflows/cwl/`) that ran end to end in containers on the synthetic isolate, and `python/make_workflow_crate.py`, which builds the Workflow RO-Crate (`dist/plasbench-score.crate.zip`).
- **Bioconda.** `recipes/bioconda/meta.yaml` is now v0.5.6 with the release archive's real SHA-256 (it was at 0.1.5 with a placeholder); the out-of-date template was removed.
- **F1000Research.** A draft Software Tool Article (`docs/publishing/f1000research-software-tool-article.md`) with every claim traced to the repository and the author-only items marked.
- **Fixed: the container's entry points could not find the pipeline** unless started in `/opt/plasbench` (found by running the CWL workflow in the v0.5.6 image): the `Dockerfile` now sets `PLASBENCH_HOME`. **Fixed: `.zenodo.json`** named the licence `GPL-3.0-only`, which Zenodo's vocabulary does not know (its id is `gpl-3.0-only`); the cohort deposit workflow's `CC-BY-4.0` became `cc-by-4.0` likewise.
- **Kept in step.** `test/test_publishing.py` and `python/sync_publishing_versions.py` keep the versions in these files in step with each release; `docs/RELEASING.md` lists the steps.

### Added -- the annotation tools in the tools setup (21 November 2026)
- **Tools page.** The window's Tools page listed only the core tools, so abricate, AMRFinderPlus, ISEScan, barrnap and MOB-typer (all called by the default reference-annotation stage) could not be installed from it. They now appear under *Annotation tools* with an Install button (`install-tools reference-annotation`, `utilities` or `mobsuite`); AMRFinderPlus shows "installed, but its database is missing" when `amrfinder` is on PATH without its database. samtools, and the optional QUAST, MultiQC, Bakta, Prokka and deadends (no package exists: the manual steps are in INSTALL.md) appear under *Optional tools*.

### Changed -- the page tabs stay in view (21 November 2026)
- **Window.** The strip of page tabs under the top bar (the open page and any documents opened from it) is now fixed while the page scrolls, instead of scrolling away; the other sticky panels (the run form's side column, the command list) start below it. Checked statically and by the existing UI tests; not looked at in a browser.

## [0.5.6] - 2026-11-21
Summary. Nothing in this release changes a score, a ranking or a threshold. Fixes and additions since 0.5.5, all described in the entries below:
- **Window stability.** The false "older than the page" banner (the page's own check was rewritten by the server), the pop-up that repeated every few seconds, and duplicate app windows are fixed; a stale window with an old key no longer gets 403 while the cookie holds the new one.
- **Docker and tools.** Docker engine health checks and error diagnosis; tool installs into the persistent extras with writable-prefix checks; the annotation callers (abricate, AMRFinderPlus and its database, ISEScan with `fastcluster<1.3`) are installed by the first-time setup.
- **Runs.** One failed isolate no longer stops the others, a lost sample list in the stage loops is fixed, SPAdes memory messages are read and retried once at the stated need, and a general resource-adaptation layer (`AUTO_RESOURCES`, on by default) handles memory, threads, scratch space and open files. `plasbench status` shows the real stage and step.
- **Stopping and reporting.** `plasbench stop` and a "Stop all PlasBench on this computer" choice in the Quit dialog (closing the window still changes nothing; `wsl --shutdown` is opt-in), issue reporting (`plasbench issue-report`, GitHub forms, SUPPORT.md) and a private security-reporting route.
- **One memory-retry policy.** Stage 3 memory retries are decided by one engine (`fit_memory` lowers a budget larger than the free memory; kills no longer raise it); the scratch folder is never memory-backed; a Python `MemoryError` rule no longer matches Java's `OutOfMemoryError`.

### Changed -- one memory-retry policy for stage 3 (21 November 2026)
- **One policy, not three.** Stage 3 had two memory-retry policies (an older generic one in `python/preflight_resources.py` that halved threads under an 80% cap, and the response engine) and a third unused copy of the same arithmetic in `python/assembler_diagnosis.py`. The older plan and the unused copy are removed; the response engine (`python/resource_adapt.py`) decides every stage 3 memory retry.
- **New response `fit_memory`.** When a tool was killed or refused memory (exit 137, `bad_alloc`, ENOMEM, Python `MemoryError`) and its budget is larger than the memory free now, the budget is lowered to 85% of what is free (min 2 GB). For those causes the budget is no longer RAISED (a bigger budget cannot help a kill); a tool that stops at its own limit (SPAdes `-m`, samtools sort, Java heap) still gets a raise. One change per attempt, each at most once, at most two adjustments per isolate: an isolate that keeps running out of memory gets two or three attempts (first run, a lower budget only when the budget is above the free memory, then halved threads), then is skipped with the reason and the others continue.
- **Scratch folder never on tmpfs.** `WORK_DIR=auto` no longer picks a memory-backed folder (a container's tmpfs home in Docker mode) as the scratch folder: it would take RAM from the assembler and count against the container's memory limit; the data folder is used and the reason is logged.
- **Fixed.** The Python `MemoryError` signature also matched Java's `OutOfMemoryError` (it now matches the Java heap rule). Removed the unused `memory_need_plan` and `--format need-plan`, the `preflight_resources.py retry-plan` command and `--min-fraction`.

### Fixed -- a long run that looked stuck for hours: lost isolates, an unread SPAdes message, a wasted ISEScan (21 November 2026)
- **Why only some isolates were handled.** In a real run stage 1 planned 134 downloads and handled 3, and stage 3 handled 1 of 3 isolates and then said `no sample produced an assembly`. A command inside each stage's `while read` loop (a helper that starts `powershell.exe`, a download or assembly tool) could read the loop's own standard input, which is the sample list, and the remaining isolates vanished without a trace. Every stage loop (1, 2, 3, 4, 5, 7) now reads the list on its own descriptor, the resource helpers get `stdin=/dev/null`, and stage 3 records any isolate no step reached as `not attempted`.
- **One isolate never stops the others.** A memory, read or tool failure is recorded for that isolate and the stage goes on ("complete WITH WARNINGS: 2 of 3 assembled"); only computer-level causes stop the stage, and each isolate not reached is recorded `not attempted (stopped early: <cause>)`. `no sample produced an assembly` is reached only after every isolate was attempted, and lists each with its cause.
- **SPAdes memory.** New rule `spades_needs_memory` reads `You need approx. X GB of free RAM`: ONE retry with `-m` = ceil(X x 1.15) when that fits in 85% of the memory available now (cgroup and WSL aware), else ceil(X) when that fits in 92%, else a stop for that isolate with the exact need and what is free; the budget is never lowered when SPAdes asks for more. Footer lines (citation, thanks, where to report) are never evidence; an unknown cause shows the `ERROR` lines.
- **Default budget.** Computed from MB: 85% of the memory available now minus 512 MB, rounded down, 2 to 64 GB, cgroup-aware, so 6.9 GB available gives 5 GB (it gave 4); an explicit `MEMORY_GB` still wins; setup prints the rule.
- **Intelligent resources (`AUTO_RESOURCES=1`, default; `0` restores fixed behaviour).** A general adaptation layer, with the failure signatures as data: `config/resource_signatures.tsv` (17 signatures, each labelled real or sample wording) and `python/resource_adapt.py`. A recognised failure (a stated need such as `You need approx. X GB of free RAM`, bad_alloc, Cannot allocate memory, MemoryError, exit 137/-9, Java heap, samtools sort, Too many open files, No space left on device in a temp folder, thread limit, exit 124) gets ONE safe response from an ordered ladder with preconditions checked against what is free now: raise the memory budget (need x 1.15 + 0.5 GB when it fits in 85% of the free memory, else the need rounded up when it fits in 92%), halve threads (only for tools flagged as scaling with threads), move the work folder to a roomier disk, raise `ulimit -n` to at most the hard limit, extend a timeout once and only when the tool shows progress, else skip that isolate with the exact need and what is free (`needs 5.2 GB, 3.8 GB are free; close programs or raise WSL memory in C:\Users\<you>\.wslconfig (memory=8GB) then wsl --shutdown`) while the other isolates continue. Each response is tried at most once per tool, isolate and cause, at most `RESOURCE_MAX_ATTEMPTS` (default 2) per tool and isolate, each as one plain log line and a `resource_adjust` event shown by `plasbench status` and the window. The need is remembered per isolate in `results/resource_profile.tsv` (reads checksum; a changed read set invalidates it), so a resume starts at the right budget with no failing attempt; an estimate from learned rows needs at least 5 and is labelled estimated. Scientific parameters are never changed; `--only-assembler` is only tried with `ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1` (default off) and recorded as mode `only-assembler`. `run_manifest.json` gets a `resources` section (final memory, threads, mode, attempts, every adjustment) shown in the report's run metadata; `assembly_status.tsv` gains `memory_gb_used`, `needed_gb`, `attempts`, `assembly_mode`. Wiring: stage 3 SPAdes (client of the engine), `run_adaptive TOOL ISOLATE -- COMMAND` in `scripts/lib.sh`, used by every stage 4 tool run (exit-code and log-based signatures; changes reach a command through THREADS, MEMORY_GB, PB_MEMORY_MB, TMPDIR, PB_ULIMIT_N, TOOL_TIMEOUT_SECONDS, JAVA_TOOL_OPTIONS, so a command whose arguments are already expanded benefits only from TMPDIR, ulimit, timeout and Java options). Not yet covered: stage 1 helpers (fasterq-dump --temp), stage 2 annotation callers (they have their own limits), stage 5/6 Python helpers (MemoryError), Unicycler and plasmidSPAdes as engine clients (they share the SPAdes message but only stage 3 SPAdes retries), thread halving in stage 4 (tool arguments carry the thread count). docs/RESOURCE_ADAPTATION.md is generated from the table.
- **Annotation callers.** `python/tool_readiness.py` probes AMRFinderPlus (`--database_version`), abricate (`--list`) and ISEScan (its clustering step) in `plasbench check` and before annotating; a not-ready caller is skipped in seconds with the fix. Root cause of the 663 s ISEScan failure: fastcluster 1.3.0 (built for NumPy 2) beside NumPy 1.26.4; the reference-annotation profile now pins `fastcluster<1.3` and runs `amrfinder -u`. Per-caller limits (`ANNOTATION_TIMEOUT_SECONDS`, default max(300 s, 150 s per Mbp), ISEScan three times; 0 or off disables) stop a hung caller's process group and record `timed_out`; every failure says why in one line (the end of stderr); failed or timed-out annotations are not cached; a caller past twice its typical time is flagged (typical times are labelled estimates).
- **`plasbench status` and the window panel.** Stages 2 and 3 now write `stage_start`/`stage_end`, every per-isolate step writes `sample_start`/`sample_end` with a step name, and the status takes the latest event of any kind (older logs: the stage after the last finished one), shows elapsed against typical, `slow_step` events and a partial-assembly line.
- **Slow-step watchdog.** `config/step_typical.tsv` and `STEP_SLOW_FACTOR` (default 3): one note and a `slow_step` event past that multiple of a command's typical time; nothing is stopped. SPAdes heartbeats name its phase.
- **Scratch work folder.** `WORK_DIR=auto` (default): when the data folder is on a slow mount (9p/drvfs, NTFS, exFAT, network, FUSE) SPAdes runs under `~/.plasbench/scratch/<study>` and only the results are moved back atomically; leftovers of a crash are removed; `WORK_DIR=data` turns it off. Measured file-system cost: 2000 tiny files, create 16.4 s on a 9p Windows drive against 0.059 s on ext4.
- **Warnings.** Stages 2 and 3 print one summary line for isolates not downloaded yet instead of one warning per row.
- **Tests changed on purpose.** `test_stage3_failure_diagnosis.sh` case 3 (out of memory twice) now expects each isolate to get two attempts and the stage to continue (it expected a stop with exit 5); `test_run_status.py` expects the step label of the running command ("SPAdes assembly") instead of the raw step name; `test_disk_guard.sh` expects `not attempted (stopped early: disk_space)`. New: `test_resource_adapt.py`, `test_stage3_continues.sh`, `test_stage3_scratch.sh`, `test_slow_step_and_aggregation.sh`, `test_run_status_stages.py`, `test_work_dir.py`, `test_annotation_timeouts_and_readiness.py`.

### Added -- Stop everything: `plasbench stop`, "Stop all PlasBench on this computer" in the Quit dialog and an opt-in `wsl --shutdown` (project lead request, 21 November 2026)
- **`plasbench stop [--all] [--runs] [--windows] [--dry-run] [--yes] [--json] [--wsl-shutdown]`** (`plasbench/stopall.py`): ends every PlasBench window server of this user on this computer that PlasBench itself recorded (`~/.plasbench/ui/server.json`, `servers/*.json`, other UI homes). Each target is verified before it is signalled (live pid, a `plasbench` + `ui` command line, a start time that agrees with the record: a reused pid is skipped and its record removed), asked politely first (the quit route, keeping runs going), then terminated (Windows: `taskkill` without `/F`), and killed only after the grace period (default 10 s) if the same verified process is still there. A program holding a PlasBench port (wslrelay, Docker, anything else) is reported and left alone; never a kill by port number or name pattern; no sudo, other users' processes are never touched, and the command never signals itself. Runs and jobs keep going and are listed unless `--runs` (detached jobs through their recorded groups, terminal-started runs through their run locks, each re-verified; `stopped_by_user` recorded; finished work is kept). `--windows` closes only browser windows carrying a PlasBench server address and the PlasBench app-window profile. `--dry-run` prints what would end and what is skipped and changes nothing; the real command prints the same list and asks (`--yes` skips). Exit 0 / 3 (something could not be ended) / 2 (usage); the `--json` shape is documented in `plasbench/stopall.py`. Every stop is logged to `~/.plasbench/ui/stop.log` and `sessions.jsonl`. Backends are injectable (Linux /proc, macOS ps, Windows PowerShell + taskkill, the Windows side from WSL through interop).
- **Window.** The Quit dialogs gain "Stop all PlasBench on this computer..." (the existing choices and defaults are unchanged). It shows what will end, what keeps going, what is left alone, a red switch "Also stop N running runs/jobs" (off by default, with the consequences) and a button that names the choice ("Stop 2 servers", "Stop 2 servers and 3 runs"). `POST /api/stop/plan` (token, loopback, read-only) returns the plan with a single-use plan id valid for two minutes; `POST /api/stop/run` needs that id, so a reload, a prefetch, a double submit or a stale tab can never stop anything. The server answers first, then stops the others and itself; other servers' windows show "PlasBench has stopped" (the server marks its answers `X-PlasBench-Stopping`). The stale-session bar gets a Stop all... button that shows `plasbench stop --all` with a Copy button.
- **Opt-in `wsl --shutdown`** (only inside WSL, with Windows interop; never the default): "Quit and restart WSL" in the dialog and `plasbench stop --wsl-shutdown --yes`. It lists what it ends (all WSL distributions from `wsl.exe -l -v`, the Docker Desktop engine, every WSL terminal, the runs, this window), is blocked while runs are active unless they are also stopped, needs a typed `SHUT DOWN WSL` and a second danger button, records `wsl_shutdown`, stops the servers and runs first and then launches `wsl --shutdown` from Windows, detached and delayed by 3 s. The real `wsl --shutdown` is never executed by the tests (a fake launcher records the argv).
- **Closing the window is unchanged.** No unload/pagehide handler or beacon exists; window pings stay informational; the server never exits or cancels jobs because no window is open. Guarded by tests.
- **Docs.** USER_GUIDE "Stopping PlasBench: closing the window, Quit, Quit everything, `plasbench stop`" and a troubleshooting entry "Too many windows or servers", FAQ Q66b, README commands row.
- **Tests.** `test/test_stop_all.py`: fake process table with an injected clock (escalation order and grace), pid reuse, ports held by other programs, stale records, runs and jobs, hostile `--windows` command lines, backends, the WSL option (hidden, disabled, blocked, order of operations, fake launcher), CLI flags and exit codes, the routes (token, loopback, read-only plan, plan id replay and expiry, answer before stop), simulated window close against a real in-process server with a fake job, static checks and node tests of the dialog's pure functions, and a real integration test with two real servers, a dummy listener and a fake job.

### Added -- How to report an issue, GitHub issue forms and `plasbench issue-report` (project lead request, 21 November 2026)
- **README "Reporting an issue"** (mirrored in INSTALL.md, the User Guide troubleshooting, the FAQ (Q73), CONTRIBUTING.md and the window's Guides page): where to report, search first, one problem per issue, a title formula, and a checklist of what to send with copy-paste commands for Linux, WSL, Windows PowerShell, macOS, Docker mode and the window: the exact command, the complete error text (how to copy it from each terminal, `2>&1 | tee plasbench-error.log` and its pitfalls, paste or attach), versions, the run's diagnostics commands, which study files to attach, what never to share and a redaction one-liner, a fillable template and three good-versus-poor examples.
- **Issue forms on GitHub** (`.github/ISSUE_TEMPLATE/`): `bug_report.yml` (required: what happened, expected, steps, command, complete error output, version, environment, install method, diagnostics, checklist), `feature_request.yml`, `question.yml`, and `config.yml` with `blank_issues_enabled: false` (every report arrives through a form; Question is the escape hatch) and contact links to the README section, `SUPPORT.md` and `SECURITY.md`. New `SUPPORT.md` and `.github/PULL_REQUEST_TEMPLATE.md`. The forms appear on GitHub once this is on the default branch.
- **`plasbench issue-report`**: one redacted Markdown block (version, install record, computer, WSL/Docker/conda/Python versions, window and installed copies, tools on PATH, free disk, settings changed in `config/local.env`, the latest study's run status, the last N lines (default 60) of the newest run log and of each failed assembler or tool log with the classifier verdict). Read-only, offline unless `--net`, allow-listed environment only, secrets/e-mail/IP/user name/host name removed, capped at 200 KB. Options `--study`, `--out`, `--include-logs`, `--net`, `--hostname`, `--open`, `--title`.
- **Window**: More > Report an issue (also on the Guides page): opens the issue chooser and shows the redacted diagnostics (`GET /api/issue-report`, token-protected, loopback only, one at a time) in a dialog with a Copy button.
- **SECURITY.md** now says what to do when GitHub's private vulnerability reporting is not switched on (it is off for this repository at the time of writing).
- **Tests.** `test/test_issue_report.py`: a redaction table of secret shapes, the environment allow-list, size cap, read-only guarantee, missing docker/conda/wsl, a failing-assembler study, `--out` and exit codes, `--open` URL length, the window route and page, README/forms field parity, YAML validity and link targets.

### Fixed -- the window is unstable: false "program files changed" banner and a "reopen this window" pop-up that keeps coming back (reported on WSL2 with the Edge app window, 0.5.5)
- **False banner (root cause).** `plasbench/data/ui.html` tested the server's api level with `/^__API_LEVEL__$/.test(...)`. `webui.page()` replaces `__API_LEVEL__` with a plain text replace over the WHOLE file, so on a correct server the served code was `/^2$/.test("2")`, which is true: "this server is older than the page" on every load. Restart window and `wsl --shutdown` could never help, and the banner invited more restarts. The check is now `!/^[0-9]+$/.test(...)`. The substitution moved to `windowlife.render_page()`, with an allow-list of where each placeholder may appear.
- **Why CI passed.** Every test of the helper ran on the unreplaced source (node on the pure block, string checks on the file); the served-page test only asserted that no placeholder was left. `test/test_window_stability.py` now renders the page through the real server, asserts the substituted values appear only on the lines that carry a placeholder, and executes the SERVED `serverTooOld` with node (false with the server's meta, true with the raw placeholder). An opt-in real-browser test (`test/test_window_stability_browser.py`, `PLASBENCH_BROWSER_TESTS=1`) loads the window from a real server and asserts no banner.
- **Repeating pop-up (root cause).** `token_ok()` used the header or `?t=` key first and the cookie only when neither was present. After a restart on the same port an older window still open kept sending its old key while the browser's cookie held the new one: refused (403) for ever, and "Trying automatically" reused the same old key. Now ANY presented credential that matches is accepted (header, `?t=` or the port's cookie, each compared in constant time). The cookie stays HttpOnly and SameSite=Strict, and the Host check and the same-origin check on every POST are unchanged, so this is no weaker than accepting the cookie when no header is sent, which the server always did.
- **The page.** A refused key is checked once with a cheap protected route, then without the key header: cookie valid means a silent reload of the bare address (the dead key is dropped, never reused); key and cookie both refused shows ONE persistent non-modal bar ("This window belongs to an older PlasBench session": Close this window / Open the current window / Check again) and stops polling. "PlasBench is not responding" is one dialog created once, with backoff 3 s to 60 s and automatic retries stopped after 10 minutes (Retry now restarts them). Unreachable, key refused and recovered are separate states, each tested under node with a fake fetch.
- **One window.** Each window pings `POST /api/window-ping` (random id) every 10 s; `plasbench ui` and the desktop icon bring the open window to the front ("PlasBench is already open: ...", PowerShell AppActivate from WSL, wmctrl/xdotool on Linux) instead of opening another, and open one only when none is alive. The token-free, rate-limited (once per 10 s), same-origin-only `POST /api/reopen` opens THIS server's own window for a window that lost its key. Restart window keeps the window and the same port: the replacement waits for the old server to release it (it used to hop 8770, 8771, 8770).
- **Diagnostics.** `plasbench ui-state` lists every PlasBench server on the computer (port, pid, version, start time, windows alive; keys never shown), anything else listening on those ports, and warns about extra servers or windows. The stale banner's Details now show what was compared (the page's api level and the server's `api_level`).
- **After upgrading.** Close every PlasBench window, run `plasbench upgrade`, then `plasbench ui` once and `plasbench ui-state`. Docs: USER_GUIDE troubleshooting, FAQ Q66c. Tests: `test/test_window_stability.py`, `test/test_window_stability_browser.py`; `test_ui_connection.py` and `test_stale_false_positive.py` were updated deliberately (probe delays 3 s to 60 s, the wording of the refused-key state, the placeholder now lives in windowlife.py).

### Fixed -- Docker engine failures: stop instead of building for hours (project lead request, 21 November 2026)
- **The failure.** On a production server `plasbench check --yes` in Docker mode pulled the image, got `failed to extract layer ... unpigz: skipping: <stdin>: corrupted -- incomplete deflate data`, classified it as *unknown* and started a local build that ran into `write .../meta.db: read-only file system`; Docker Desktop's own dialog said `dockerd configuration error ... daemon.json is invalid ... fork/exec /usr/local/bin/dockerd: no such file or directory`. The root cause on that machine could not be inspected: PlasBench now diagnoses from the messages.
- **No more wrong fallback.** A local build is offered only when the pull failed because the image is genuinely unavailable (`manifest unknown`/`not found`/`repository does not exist`, `denied`/`unauthorized` for a not-yet-public image with the login hint, a platform mismatch where building natively is the fix). After an engine, disk, storage, corruption, network or unknown error PlasBench stops with the diagnosis and builds nothing.
- **`python/docker_diagnosis.py`.** A table-driven classifier (stdlib, Python 3.9, modelled on `assembler_diagnosis.py`): `diagnose(text, context)` returns cause, confidence, evidence lines, advice, copyable commands, last-resort steps with their consequences, `retryable`, `engine_unhealthy`, `build_ok` and the environment (Docker Desktop on Windows/WSL 2 or macOS, Linux Engine, rootless). It covers corrupted layers, read-only file systems, no space or inodes, a damaged Docker Desktop (`dockerd` missing), the engine not running or not permitted, registry limits, access and manifest errors, TLS (proxy CA, clock), proxy/DNS/network, storage-driver/containerd errors, cgroups, BuildKit (exit 137, ResourceExhausted), platform/QEMU and WSL failures; an unrecognised message is `unknown`, confidence low, with the last 15 lines. Commands that delete or move data are never in the command list and are never run.
- **Engine health pre-flight** (`plasbench/docker_health.py`) before any pull, build or container start: `docker version`, `docker info` (root dir, storage driver, proxies), free space where Docker keeps its data (warn below 10 GB, stop below 2 GB; a build is estimated from the Dockerfile) and a write test (`docker volume create` / `rm`, no network). About 15 seconds, each step with its own timeout, cached 30 s; `PLASBENCH_DOCKER_HEALTH=off` skips it. An unhealthy engine stops the command before any pull or build (exit 20 when only you can fix it).
- **Pull retries.** Retryable failures (network, a layer cut short, TLS handshake) are retried `PLASBENCH_DOCKER_PULL_RETRIES` times (default 2) with growing pauses (`PLASBENCH_DOCKER_PULL_BACKOFF`); the diagnosis is recorded in `run_events.jsonl` and the job result.
- **`plasbench runtime doctor`** (`--json`; exit 0 healthy, 3 problems, 2 usage): PASS/FAIL/NOTE per check with evidence, the environment, versions, root directory, free space, storage driver, the proxies Docker uses and a numbered plan. The Environment card gains **Run health check** (a bounded, token-protected `POST /api/runtime/health`, remembered 30 s; `GET` returns the last result only; nothing runs on page load) with copy buttons for the commands. `runtime check` gains an engine-health step; `runtime use docker` prints a health note.
- **Docs.** INSTALL.md "Docker troubleshooting" (error text, meaning, safe steps per environment), USER_GUIDE "Docker health", FAQ Q72. Tests: `test/test_docker_diagnosis.py`, `test/test_docker_health.py` (a scripted fake `docker`, also as a real executable on PATH on Linux), and the real-Docker end-to-end test now runs `runtime doctor` and the volume write test against the CI runner's engine.

### Added -- Windows shells in the Terminal tab, from a WSL window (project lead request, 21 November 2026)
- **Terminal shell list.** On a window running inside WSL the Terminal now offers, besides the Ubuntu shell (labelled with the distribution, e.g. "Ubuntu-24.04 (Bash)", still the default): **Windows PowerShell** (`pwsh.exe` when installed), **Windows Command Prompt (cmd)** and **Git Bash (Windows)**; greyed with the reason when WSL interop is off. A native Windows window gains **Command Prompt (cmd)** (order: each Ubuntu, Git Bash, PowerShell, cmd). Linux and macOS are unchanged (login shell, `pwsh`). The list is probed once in the background (`loadcache`), never on page load.
- **Running them.** The folder is translated with `wslpath -w` (an Ubuntu folder is a `\wsl.localhost` path; Command Prompt enters it with `pushd`, with a one-time notice); `plasbench` is a shim in each shell that calls back into Ubuntu (`wsl.exe -e`; a temporary `plasbench.cmd` removed after each command); PowerShell commands travel as `-EncodedCommand`, Command Prompt gets a raw command line; output is read as UTF-8, UTF-16 or the old code page, with terminal escape codes removed; a timeout or cancel stops the Windows process tree with `taskkill.exe /T /F`; each shell has its own history and prompt.
- **Fixed.** PowerShell single-quote escaping now also doubles the typographic quotes PowerShell treats as quotes; a PowerShell command run from a WSL window returns the exit code of a failed program.
- **Tests and docs.** `test/test_terminal_shells.py` (table-driven lists, hostile quoting, shims, kill path, decoding, page); user guide "The Terminal tab: which shells, and why"; FAQ Q71.

### Fixed
- **Fixed: the window could terminate itself.** Cancelling a job record that names the window's own process id (or its own process group) signalled that process; `Jobs._kill` and `kill_group` now never signal their own process or group. This was the cause of `test_job_survival.py` being killed with exit 143 once in a while in CI (a test-only record naming the test's own pid reached the shared job index through a background save, and the final tidy-up cancelled it); the test now uses a helper process for that record and asserts that no signal is sent to its own process or group.

### Fixed -- tool installs in Docker mode (production failure, 21 November 2026)
- **Installs go to the extras folder, never into the image.** `plasbench check --yes` / `install-tools` in a container solved into `/opt/conda/envs/plasbench`, which the host user cannot write: `Could not open lockfile ... conda-meta.lock`, `Permission denied` while unlinking packages, and a failed `mv` of the MOB-suite database. Now one overlay environment is created fresh (own solve, no inherited pins) at `<extras>/envs/extras`, with `MAMBA_ROOT_PREFIX`, `CONDA_PKGS_DIRS` and `CONDA_ENVS_PATH` inside the extras folder; PATH in every container is `extras/bin`, the image's tools, then the extras environment. Source-pinned installs build under the extras folder too.
- **Fail fast on a read-only prefix.** Before any solver runs, a prefix or package cache that cannot be written stops the install within a second with one message (the path it tried to write, and the fix); `python/install_diagnosis.py` classifies the solver's permission errors in the style of `assembler_diagnosis.py`. A failed profile no longer cascades: the rest of a list (and `check --yes`) is not attempted against the same prefix, `check --yes` installs each profile at most once per invocation ("not retrying X"), prints a summary (OK / FAILED / MANUAL) and exits 1 when a requested install failed. The useless ERR-trap line about `return "$rc"` is replaced by a message naming the profile.
- **MOB-suite database.** It is never moved out of a read-only folder; inside a container it is used from the mounted database folder through `-d`, the check reports `[ok]` only when all four files exist, and a swallowed `mv` error can no longer be followed by `[ok]`.
- **Heartbeats never fail the command they watch.** `proc_stats` returned 127 when the image had no `ps`, which aborted `install_tools.sh` under `set -e`; it now falls back to `/proc`, says "process figures unavailable" when it has nothing, and the image installs `procps-ng`.
- **Container noise.** Inside a container the WSL notes and the "could not measure the Windows drive" warning are not printed; the container's cgroup limits are reported with where to change them (Docker Desktop Settings > Resources); the Docker line of `plasbench check` no longer suggests installing Docker inside a container. The pull/build heartbeat prints once a minute, not twice.
- **Tests.** `test/test_docker_extras.sh`, `test/test_docker_extras.py` and `test/test_docker_extras_e2e.py` (real Docker in CI: a root-owned environment, a non-root user, the real `install-tools jq`, a second container, the image's conda-meta unchanged; the pre-fix failure is demonstrated).

### Added -- an installing toast (project lead request, 20 November 2026)
- **Installation in progress, on every page.** While any install, pull, build or update runs (`install-tools`, `tools install`, `install-conda`, `runtime pull|build`, `check --yes` for tools and databases, `upgrade`) a card in the toast area shows what is installing, the elapsed time and the latest log line, with **View log**, **Cancel** (a designed confirm dialog) and **Hide** (a chip with a spinner and a count in the top bar). It appears the moment the button is clicked and is drawn from the job list, so it survives a reload, a second window and a server restart. It turns to *Waiting for you*, *Consent needed*, *Manual step needed*, *Stalled?*, *Failed* (stays until dismissed) or *Done* (about 8 s), combines concurrent installs into one card, and a *Finished while you were away* note appears once for installs that ended while the window was closed.
- **Server.** `plasbench/jobs_labels.py` is the one place that decides which jobs are installs; `/api/jobs` entries gain `is_install`, `install_label`, `install_tools`, `install_kind`, `last_line` and `installed_version` (additive). `test/test_install_toast.py` covers it; `test/test_install_toast_browser.py` runs it in a real browser (opt-in).

### Added -- update PlasBench from the window, and install from a downloaded release file (project lead request, 20 November 2026)
- **Updates card** (Set up this computer; a dot on the top bar's More button opens it). **Check for updates** shows the installed and latest version, the release date, the first lines of the release notes (plain text) and whether the release is an upgrade, the same or older (an older release is never offered silently); the answer is cached with the time it was checked. A background check runs when the window starts and at most once a day (a thread, never on the page-load path), only with the new setting `UPDATE_CHECK=auto` (default; `off` stops it) and never with `PLASBENCH_OFFLINE=1`; only GitHub's public release list is asked.
- **Download and install** (a consent dialog lists the version change, the file and its size, the source, the checksum check, the folder, what is kept and the restart) runs `plasbench upgrade` as a job with a live log and six announced phases, then offers **Restart window** (the stale-window machinery). It is refused while a run or job is active unless the person chooses **Update anyway**, and never while another update runs. Failures are classified (offline, checksum, disk, permission, conda, wrong file, lock) with the next step and whether anything was changed.
- **Install from a file I already downloaded** (native Browse or a pasted path; `plasbench-<version>.tar.gz`, `.sha256` beside it used when present) runs `plasbench upgrade --archive FILE`; no internet.
- **`plasbench upgrade` gains** `--check-only`, `--version X.Y.Z`, `--archive FILE` and `--rollback`. update.sh verifies the checksum, the archive's file names (nothing outside `plasbench-<version>/`) and that the content is the version in the file name before replacing anything; downloads use https only from github.com, with a size limit (`PLASBENCH_UPDATE_MAX_MB`, 1024); a lock allows one update at a time; it checks free disk space first; it saves the replaced release in `.plasbench-rollback/` so `--rollback` can go back.
- **Routes** (token-protected): `GET /api/updates`, `POST /api/updates/check`, `POST /api/updates/archive`, `POST /api/updates/install`. The old `GET /api/update-check` remains.
- **Docs.** README and INSTALL.md: "I already downloaded the release file" (where to get the file and its checksum, checking it on Linux, WSL and Windows PowerShell, `install_latest.sh --archive`, offline notes, upgrading later, errors); the user guide's "Updating PlasBench from the window"; FAQ Q70. `test/test_readme_install_paths.py` keeps the README command identical to the installer's usage text.
- **Tests.** `test/test_updates.py` (a fake GitHub: newer, same, older, malformed, rate-limited, offline; plans, refusals, phases, failure classes, routes, page) and `test/test_upgrade_e2e.sh` (update.sh with fake release tarballs: `--check-only`, `--archive`, `--rollback`, `--version`, and refusals that leave every installed file unchanged). Not verified: a real release download from the window, a real browser, a real WSL or conda upgrade.

### Fixed

- Docker "Permission needed" told the truth about the window's own process: after `sudo usermod -aG docker $USER` the already-running window still gets `permission denied` on `/var/run/docker.sock` (a process keeps the groups it started with). PlasBench now compares the account's groups (`/etc/group`) with this process's and reports a distinct state `permission_group_not_applied` ("You are in the docker group, but this window started before that, so it cannot use it yet. Restart the window from a terminal where the group applies (newgrp docker, then plasbench ui) or run wsl --shutdown in Windows PowerShell and reopen Ubuntu.") with a **Restart window** button; the restart relaunches through `sg docker -c "exec ..."` (each word shell-quoted) only when needed, and falls back to the manual instructions without `sg`. Users who are not yet members keep the plain "add yourself to the group" state.
- `plasbench install-tools docker` no longer reports *Docker state: Not installed* right after winget installed Docker Desktop, and no longer waits 90 seconds for an engine that cannot answer until Docker Desktop is started. New states told apart from the Windows side (also from WSL 2): `installed_windows_not_running`, `desktop_running_engine_down`, `engine_up_wsl_integration_off`; *Not installed* is left for when nothing is found. Right after the install it says *Docker Desktop was installed on Windows (version X). It is not running yet.* and exits 20 at once; it polls the engine (default 90 s, `--wait SECONDS`) only where Docker Desktop is running, with a progress line every 10 s.

### Added

- `plasbench install-tools docker --start` starts Docker Desktop (`powershell.exe -NoProfile -Command Start-Process -FilePath '<Docker Desktop.exe>'`, an argument list) and polls the engine; `--open-integration` opens Docker Desktop's WSL integration settings and checks every 5 s for up to 3 min. PlasBench never accepts the licence, never edits Docker Desktop's settings and never clicks in its window.
- Read-only Windows-side evidence: `Docker Desktop.exe` / `docker.exe` files, `tasklist.exe`, `winget list`, `docker.exe info` and `settings-store.json` (`IntegratedWslDistros`, licence record). `plasbench runtime check`, `plasbench check` and the window use the same detector.
- The Tools page Docker card shows the four stages as a checklist (hover for the evidence) and one primary button for the next action (Install Docker, Start Docker Desktop, Open WSL integration settings, I enabled it, Re-check); the Environment card offers the same Start and Open actions.

### CI
- **CI: layer cache, sharded tests, cancelled superseded runs.** The container job caches its Docker layers in the GitHub Actions cache (scope `ci-container`, `mode=max`), so the conda layers are rebuilt only when the lock files change. The test suite runs as four parallel shards per Python version (`PB_SHARD=i PB_SHARDS=4 bash test/run_tests.sh`; weights in `test/shard_weights.tsv`, proved to cover every test exactly once by `test/test_shard_selection.py`); shellcheck runs once, and install, demo, compileall, build and twine run in a `checks (3.x)` job. The check names `test (3.9)`, `test (3.11)`, `test (3.13)` and `container` are kept: each `test (3.x)` is an aggregate that passes only if all four shards and the checks job of that version passed. A new push to a pull request cancels that PR's older CI run; runs on main are never cancelled. `release.yml` is unchanged (its image build stays uncached so a release is built from scratch).
- **CI: faster suite.** Three download tests no longer wait out real retry backoffs (`NETWORK_RETRY_DELAY_SECONDS=0` in `test_download_parallel.sh` and `test_simulated_download_stage.sh`, `PLASBENCH_RETRY_SLEEP=0` and the new `ENA_RETRY_DELAY_SECONDS=0` in `test_download_gate_and_prefetch.sh`; the first two knobs already existed, `ENA_RETRY_DELAY_SECONDS` (default 15, the wait before ENA retry n is n times it) is new in `python/fetch_ena_reads.py` and changes nothing by default, and the retry counts the tests assert are unchanged), which cut about 420 s of the suite; the suite now runs as five shards per Python version.

## [0.5.5] - 2026-11-20
Summary. Nothing in this release changes a score, a ranking or a threshold. Three groups of changes:
- **Docker.** Install Docker from the tools setup (`plasbench install-tools docker`, and a Docker card in the window): it detects the computer and the Docker state and installs with `winget` (Windows, and WSL 2 through the Windows side) or `brew` (macOS) only after consent; everything else (the Docker Desktop licence, first launch, WSL integration, the sudo script for Linux) is handed to you with a copyable step, and PlasBench never runs sudo. Choose where the tools run on *Set up this computer*: Conda (default) or Docker (`plasbench runtime status|use|check|pull|build`, `plasbench run --runtime`). The image is pulled, or built locally from the Dockerfile after consent; missing tools and databases are installed into persistent storage mounted into every container; every folder is mounted at the same absolute path; the runtime, image and Docker version are recorded in the manifest and the report. Limits: the per-run wizard choice of runtime is not wired (use `--runtime` on the command line), a derived image for `--with-tools` is not implemented, and the time and size of building the image and of databases are not measured.
- **Runs.** The resource pre-flight no longer blocks a run that can start: an honest probe of Ubuntu's virtual disk under WSL with its evidence, a sampled read-size estimate, only the working set blocks a start, a whole cohort larger than the free space is a warning with a `--max-isolates` suggestion, and a rolling disk guard stops the run cleanly before each isolate that no longer fits so the same command resumes.
- **Window.** A quieter window: explanations moved from the pages to the green ? help (hover, keyboard focus or tap), while warnings, errors, states and required decisions stay visible; page heads follow one pattern; the left list follows the workflow order; the top bar is slimmer, with Help, Reload and the theme in a More menu; on a phone there is no sideways scrolling and touch targets are 40 px. A test checks that all controls are kept and keeps a word budget per page. The explanations are summarised in USER_GUIDE "The window at a glance" and FAQ Q20e.
- **Window: a cleaner, quieter UI before release.** Explanations moved off the pages into the green **?** tooltips (hover, keyboard focus or tap; Escape closes; kept on screen); the text lives in `plasbench/ui_help.py` (`PAGE`, sent as `page_help`). Pages show a title, one line of purpose and the controls; warnings, errors, states and required decisions stay visible. The left list follows the workflow (Set up, Benchmark, Results, Tools & rules, Advanced, Settings & help); the top bar keeps Panel, the internet indicator, Console and Quit, with Help, Reload and the theme in a More menu; the phone layout no longer scrolls sideways and touch targets are 40 px. `test/test_ui_cleanup.py` keeps a word budget per page, checks that every help id exists and that no control was lost; `test/test_ui_cleanup_browser.py` (opt-in) checks the tooltip on hover, focus and tap in a real browser. See docs/USER_GUIDE.md "The window at a glance" and FAQ Q20e.
- **Docker in the tools setup.** `plasbench install-tools docker [--yes] [--dry-run] [--hello-world]` and a *Docker* card in the window (Tools page, Workflow view under *Check and install*, and *Install Docker first* in the folder chooser and Settings when *Run in Docker instead* is not available). It detects the computer (native Windows, WSL 2, macOS, Linux by package manager, inside a container) and the Docker state (not installed, daemon stopped, permission needed, WSL integration off, Docker Desktop not running, ready) with a precise diagnosis and next step. Where a user-level process may, it installs: `winget install -e --id Docker.DockerDesktop` (Windows, and WSL 2 through the Windows side) or `brew install --cask docker-desktop` (macOS), only after consent, and the operating system shows its own approval prompt. Everything else is handed to the user: the Docker Desktop licence (PlasBench cannot accept it), first launch, WSL integration, and a copyable sudo script per distro family from docs.docker.com with a signing-key check for Linux and Docker Engine inside WSL. PlasBench never runs sudo, never takes an administrator password and never pipes a script to a shell. Exit codes: 0 verified working, 20 handed to you (shown as *Waiting for you to finish in ...* with a **Re-check** button), 21 consent needed, 1 failed. The verified version and context are recorded for `plasbench check` and the run manifest (`container_engine`); `scripts/docker_run.sh` prints the same diagnosis when Docker is not ready. New netcheck services `winget` and `brew`. Tests: `test/test_docker_setup.py`, `test/test_docker_install.sh`. See INSTALL.md, "Installing Docker".

### Added -- choose where the tools run: Conda or Docker (project lead request, 20 November 2026)
- **Environment card.** Set up this computer has an Environment card at the top: Conda or Docker, the state of each (conda environment and tool counts; Docker not installed, stopped, permission needed, WSL integration off or ready, the image, its size and version match), what each means, and the buttons Use Docker (a consent dialog that lists the image, the mounts and that conda stays), Use Conda, Pull / update the image, Build the image, Test Docker setup, Make everything ready and Install Docker first. Docker is disabled with the reason, never hidden; the run wizard has the per-run choice. Routes: GET /api/runtime, POST /api/runtime/use, test, pull, ready (the pull, build and ready actions are jobs, gated on the internet).
- **Settings and command.** PLASBENCH_RUNTIME (conda or docker), PLASBENCH_DOCKER_IMAGE (default: the published image of this version, never latest), PLASBENCH_DOCKER_PULL (missing, always, never), PLASBENCH_DOCKER_EXTRA; `plasbench run --runtime docker|conda`; `plasbench runtime status|use|check|pull|build`.
- **How it works.** The window stays on the computer. In Docker mode `run`, `report`, `check`, `install-tools` and `tools install` start `docker run --rm` (plasbench/docker_runtime.py; arguments only, no shell strings) with every needed folder mounted at the same absolute path (native Windows maps D:\x to /mnt/d/x; UNC shares are refused), `--user` so files are not root-owned, CPU and memory limits, a container named plasbench-<job id> that Cancel stops, and the container's exit code returned unchanged. Conda mode is unchanged.
- **Build the image when it is missing.** Present locally, else pulled, else built from the Dockerfile after consent (`plasbench runtime build [--yes] [--rebuild]`), with a log, a heartbeat, a classified failure (disk, name lookup, registry, platform, failing step) and a version check after the build. Building needs the internet, several GB and a long time (not measured).
- **Tools and databases in Docker mode.** Missing tools and databases are installed inside a container into a persistent folder mounted into every container (the image is never changed) and put on PATH; databases use the shared database folder. Manual steps stay exit 20.
- **Honest records.** The study record and run_manifest.json record the runtime, image, whether it was pulled or built here, the Docker version, the mounts and the extra tools; the report's Run metadata says where the tools ran.
- **Tests.** test/test_docker_runtime.py (fake Docker) and test/test_docker_runtime_e2e.py (real Docker in CI: a real build, identical-path mounts, ownership, persistent extras, exit codes, cancel; prints n/a where Docker cannot be used).
- **Limits.** Real bioconda installs inside the container are exercised only with a fake tool; the Windows and WSL2 paths are tested with fakes.

### Fixed -- the new resource check blocked a run that could start (project lead report, 20 November 2026)
- **What happened.** `plasbench run --cohort public-v4 ...` (7,227 isolates, no `--max-isolates`) under WSL stopped in stage 0 with exit 6: "only 1519.6 GB is free ... 21897.8 GB estimated" and "the drive holding Ubuntu's virtual disk (C:) has only 0.3 GB free", under a headline "NOT ENOUGH RESOURCES" that read as a memory verdict (memory was fine: 7.0 GB available, 5 GB budget). The whole-cohort figure came from a typical isolate (3 GB x 7,227) because no reads were on disk yet, and a figure that only a long run could ever reach was treated as a block.
- **Policy.** Only what cannot even START is a block: the working set (peak per isolate x isolates in flight) must fit. A whole cohort that will not fit is a warning: "this run will fill the drive after about N isolates", with a `--max-isolates` to use. A rolling guard before each isolate's download (stage 1) and assembly (stage 3) stops the run cleanly with exit 6 when the next isolate no longer fits plus a reserve (`PLASBENCH_DISK_RESERVE_GB`, default 5); finished isolates are kept and the same command resumes. `PLASBENCH_SKIP_DISK_CHECK=1` turns the check and the guard off.
- **Better estimate.** Reads sizes come, in order, from the reads on disk, the cohort lock's base counts, the mean of up to 20 isolates whose size ENA reports (cached in the study folder, stage 0 only), else a typical 0.3 GB read set, printed as "NOT measured" with low confidence. Peak and kept (reads, trimmed reads and the assembler folder stay on disk) are separate figures; the factors (8x working files, 3x assembler folder) are assumptions and are printed as such.
- **Ubuntu's virtual disk, with evidence.** The Windows drive under Ubuntu's disk is found for the distribution this process runs in (exact `WSL_DISTRO_NAME`, never docker-desktop) and its free BYTES are read; any lookup or parse problem gives "unknown", never a number. The message prints the distribution, the ext4.vhdx path, the volume and the bytes, and the command to check it yourself (`powershell.exe -NoProfile -Command "(Get-PSDrive C).Free/1GB"`); `plasbench picker-check` and `python3 python/preflight_resources.py vdisk` print the same. What blocks depends on where the folders are: on a mounted Windows drive only a 2 GB floor (`PLASBENCH_VDISK_MIN_GB`) blocks and under 10 GB warns; on Ubuntu's own disk that drive's free space is the limit. A `/mnt/<x>` folder that is not a real mount is named as Ubuntu's own disk, with the mount command (never run for you).
- **Honest message.** One block: headline (cannot start / can start), Measured, Needed (working set vs whole cohort, measured vs estimated, the assumption) and the three most useful next steps; the memory and thread rules that were applied are printed ("memory: 5 GB assembler budget <= 7.0 GB available: ok").
- **Changed on purpose from PR #128's tests.** The estimate adds 0.33 GB per isolate for the reference, raw reads and results; "under twice the estimate" is no longer a warning (replaced by the working-set and whole-run rules); a whole cohort over the free space is a warning, not FAIL; the Windows-drive message now reads "the Windows drive C: holding Ubuntu's virtual disk"; the memory warning now starts "memory:" and names MEMORY_GB.
- **Not verified here.** The WSL probes could not be run against a real WSL; the recorded outputs in `test/test_preflight_resources.py` are written from knowledge of the formats.

## [0.5.4] - 2026-11-20
Summary. Nothing in this release changes a score, a ranking or a threshold.
- **Window.** The folder window now opens under WSL: `powershell.exe` is found by absolute path when PATH does not have it, the dialog script travels as a short unpacker or a file instead of a very long command line, there are fallbacks when Windows PowerShell is restricted, the window is brought to the front, and the page is told when it opened. When it cannot open, the page says why and offers the built-in browser. `plasbench picker-check` and Settings > Test the folder window show each step. In Docker, Browse uses the built-in browser rooted at the mounted folders and *Add another folder* writes the `docker run -v` command; *Run in Docker instead* shows a copyable command only (it does not start anything).
- **Install and update.** The older-version banner appears only when the loaded code really differs (content hashes of the loaded modules); two installs of PlasBench are named, with the fix command; Details shows the evidence and the banner can be dismissed for a server run. `plasbench ui` replaces an older running window. `plasbench upgrade` verifies the installed copy, repairs it, and exits 4 with the command if it cannot. New `plasbench ui-state`. The PlasBench folder is found from outside it (`~/.plasbench/install.json` and others), and an optional `~/.local/bin/plasbench` launcher is written.

### Fixed -- Browse did not open the folder window under WSL, and nothing said why (project lead report, 19 November 2026)
- **Why it failed.** The dialog script was about 11,000 characters and went through `powershell.exe` as a 29,000-character `-EncodedCommand`, within a few percent of the Windows command-line limit (32,767) and
  far above the 8,191 that some launchers stop at; `powershell.exe` was found only on PATH (WSL with `appendWindowsPath=false`, a conda environment or `interop` switched off found nothing and gave a bare "not found");
  a PowerShell that could not run `Add-Type` (company policy, Constrained Language Mode) ended in a blank error; the owner window sat at -32000, and a window started from WSL could open behind the browser;
  the page waited with "Waiting for the folder window..." and could not tell a window that was starting from one that never would. Each of these is now handled and reported.
- **Command line.** The script travels as a short ASCII unpacker (about 5,400 characters), else a `.ps1` file in the Windows temp folder, else on standard input; a script file keeps unicode and spaces.
- **Finding PowerShell.** The override, PATH, `/mnt/c/Windows/System32/WindowsPowerShell/v1.0`, `pwsh.exe`, any `/mnt/<drive>/Windows`, and `%SystemRoot%` asked of `cmd.exe`; `/etc/wsl.conf` and
  `/proc/sys/fs/binfmt_misc/WSLInterop` are read, and the reason names exactly what was found.
- **Fallbacks.** Explorer-style dialog, then `FolderBrowserDialog`, then `Shell.Application`, then a clear error that makes the page offer the built-in browser; a locked-down PowerShell is named as such.
- **In front.** A top-most invisible owner centred on the screen, the Alt-key and thread-input trick, `SetForegroundWindow`, a flashing taskbar button as the last resort; the script says `PB_OPENED` when the window exists.
- **The page never does nothing.** No "opened" signal within 8 seconds, an error, a lost server or an unknown job opens a dialog with the reason, **Why?**, **Copy diagnostics**, **Keep waiting** and
  **Use the built-in browser**; the built-in browser shows the reason with Why? as well; an unavailable window is looked at again after 15 seconds so a fix needs no reload.
- **Loopback rule.** Loopback, and under WSL2 the Windows host a localhost-forwarded browser can be seen as (the VM's default gateway); a Docker bridge address is not accepted.

### Added -- `plasbench picker-check`, Test the folder window, and Docker (same report)
- **`plasbench picker-check`** (`--interactive`, `--seconds`, `--json`) and Settings > **Test the folder window**: PASS or FAIL per step with the exact error (environment, WSL interop, which `powershell.exe`, a
  minimal script, `Add-Type`, the route the script takes, the older windows, the real window opened and closed after two seconds, front or flashing, the Windows-to-Linux path), ending with what Browse will do.
- **Docker.** Detected from `PLASBENCH_IN_DOCKER`, `/.dockerenv`, cgroup v1 and v2: no desktop folder window by nature, so Browse is the built-in browser rooted at the mounts read from
  `/proc/self/mountinfo` with a banner that other folders are not visible, and **Add another folder** writes the `docker run -v` / compose snippet (Windows, WSL, spaces and unicode handled, a UNC share refused),
  never run. From a window on the computer, **Run in Docker instead** is offered only when `docker info` answers (background probe) and `scripts/docker_run.sh` exists; it shows and copies the command and
  starts nothing (the window listens on 127.0.0.1 only and the image's command is the command line). `scripts/docker_run.sh` takes `PLASBENCH_DATA_DIR`.
- **Tests.** `test/test_picker_diagnostics.py` (about 180 checks; WSL and Docker with fakes; on Windows the real PowerShell route, the temp-file and stdin routes, and a real folder window found with UI Automation,
  closed with WM_CLOSE and reported as cancelled) and `test/test_picker_ui_browser.py` (opt-in, real browser: unavailable, Docker, and on Windows the real window).
### Fixed -- the "older version than the page" banner no longer cries wolf
- **Stale means the loaded code really differs.** The window judged itself by the size and mtime of every `plasbench/*.py`; a touched file with the same content, a module it never imported, a cache or a copy made by a sync tool counted. It now records a SHA-256 of each module it has imported and compares content (cached by size and mtime), plus the version in the package it runs from. `ui.html` is no longer part of it; the page carries an api level (`meta plasbench-api-level`), and a server that leaves that placeholder unreplaced is certainly older than the page.
- **Two installs are told apart from a stale window.** A copy in the plasbench environment (`pip install --no-deps .`) next to a different version in the PlasBench folder is reported as `two_installs` with the install command: Restart window cannot fix it, so it is not offered. `GET /api/server-state` gains `kind`, `running_version/path`, `project_root_version/path`, `changed_modules`, `fix_command`, `server {pid, port, started_at}`, `api_level`.
- **A second `plasbench ui` (or the icon) replaces a window older than the command** instead of reusing it (which brought the same old window, and its banner, straight back); runs keep going. Restart now starts the package folder the old server ran from, not whatever `-m plasbench` finds in the current folder.
- **Banner.** Shown only when the server says stale; Details carries versions, paths, pid and port and the changed modules with truncated hashes; "Dismiss for this server run" is keyed by start time, pid and kind.
- **`plasbench upgrade` verifies the install** (the Python's `plasbench` against the folder's version), repairs an old installed copy with `pip install --no-deps`, and records the folder. Cause inferred from the code (not reproduced on the reporter's WSL machine): an older installed copy or window left running after an upgrade.

### Added -- `plasbench ui-state`, finding the PlasBench folder from anywhere, a launcher
- `plasbench ui-state [--json]` prints the evidence behind the banner (running version and folder, every copy of `plasbench` on `sys.path` and in the conda environments next to this Python, `pip` metadata, the PlasBench folder and how it was found, install record, the running window's state).
- The PlasBench folder is found from `--project-root`, `PLASBENCH_HOME`, the current folder or a parent, `~/.plasbench/install.json`, the folder the program was imported from, then `~/PlasBench`; the one used is named when it is not the current folder, and a missing folder gives a short error with three fixes instead of the command list.
- `install.sh` and `plasbench upgrade` write `~/.local/bin/plasbench` (marker comment, never over a foreign file, `PLASBENCH_NO_LAUNCHER=1` to skip) so `plasbench` works outside the conda environment.
- New `plasbench/roots.py`; tests: `test/test_stale_false_positive.py`.

## [0.5.3] - 2026-11-19
Summary. Nothing in this release changes a score, a ranking or a threshold.
- **Window.** Every Browse button opens the computer's own folder window (Explorer on Windows and WSL, Finder, zenity/kdialog/yad) with the built-in browser as fallback; a window that is older than the files on disk shows a banner with Restart window and Reload page (clear cache).
- **Tools.** Missing tools install automatically, with consent, from pinned commits in isolated environments; exit 20 (manual step) and 21 (consent needed) are information, never an error; every install profile is proved on a clean Linux runner in CI; add-your-tool is tested end to end, with a new `plasbench tools remove NAME` and fixes found on the way.
- **Runs.** Stage 3 says why an assembler failed and stops early when the cause belongs to the machine; a resource check runs before stages 0, 2 and 3; finished reference annotations are cached.
- **Stage 3 says why an assembly failed, and the run says it too.** A production run (`public-v4`, WSL) stopped with "SPAdes failed ... see logs/<sample>.spades.log" three seconds after each assembly began, and nothing said why. New `python/assembler_diagnosis.py` reads the assembler's log and names the cause (disk full, out of memory, SPAdes memory limit, too many threads, illegal instruction, segmentation fault, a broken Python or distutils, truncated or corrupt reads, mismatched mates, k-mer longer than the reads, empty reads, missing or read-only files, a stale output folder, a missing tool, a network failure, or "not recognised" with the last 15 lines: never guessed), with its evidence line, confidence and advice. Stage 3 prints one block per failed isolate, records `cause` and `advice` as two new columns at the end of `assembly_status.tsv` (old readers and old files still work), emits `assembly_failed` run events, and stops at the first isolate (exit code 5, the rest recorded as "not attempted") when the cause belongs to the computer and would repeat for every isolate. Out of memory is retried once with fewer threads and a budget that fits the free memory (`ASSEMBLER_AUTO_RETRY=0` turns it off); a stale output folder of that isolate is removed and retried once; damaged reads are re-verified and given the exact re-download command; never more than one retry. `plasbench status` / `diagnose` and the window's run panel show the cause and advice.
- **Resource check before stages 0, 2 and 3.** New `python/preflight_resources.py`: free disk on the study, data and temporary folders against an estimate (printed as one) of what the isolates still to do will write, and under WSL the Windows drive holding Ubuntu's virtual disk; memory against the assembler budget; `THREADS` above the CPUs the process may really use (affinity, container quota, WSL processors) is lowered to them with the decision printed (`CAP_THREADS_TO_CPUS=0` keeps it); writable folders; cloud-synced and `/mnt` folders flagged. One compact "Resources check: ok / warnings" block in stage 0; too little disk stops with exit code 6 (`PLASBENCH_SKIP_DISK_CHECK=1` overrides).
- **Stage 2 annotation.** Finished reference annotations are kept in `ANNOTATION_CACHE_DIR` (default `<data>/.annotation_cache`), keyed by the reference's SHA-256 and the callers' versions and databases, and reused by a later study of the same isolate; the table is byte-identical to a fresh one and the provenance file says it was reused. A line per annotation caller says when it finished and which are still running. Nothing that is computed changed.

### Added -- every tool install is proved on Linux, and the add-your-tool path is tested end to end (project lead request, 19 November 2026)
- **Tool installation proof.** `.github/workflows/tool-install-proof.yml` (weekly, and on request; never on a pull request) installs every profile of `env/install_tools.sh` on a clean Linux runner with the project's own commands (`env/bootstrap_conda.sh`, then `plasbench install-tools PROFILE --yes`), runs each profile's verification (`config/install_proof.json` plus the registry's `verify_command`), uploads a JSON result per profile and one table of all of them. A profile that cannot be installed automatically (plsmd, ppr-meta) must exit 20 with its reason and is shown as expected-manual. A second job runs the installed tools on a real plasmid through stages 3 to 6 (`test/real_run_smoke.sh`). `docs/TOOL_INSTALL_AUDIT.md` has a *CI proof* column with the run and date.
- **What the proof found and fixed.** gplas2 installed but `gplas` could not import its package (upstream ships no `__init__.py`; the wrapper now sets `PYTHONPATH`); PLASMe's PyTorch libraries need an executable stack that recent glibc refuses (the installer clears that flag, as `execstack -c` does); Nextflow used the runner's own `JAVA_HOME` instead of the environment's Java (the wrapper sets it); the registry verified `RFPlasmid` and `python plasbin_flow.py`, which are not the commands the tools install, and bioconda's old `gplas` installs `gplas.sh`.
- **Add your own tool, tested end to end.** `test/test_add_tool_e2e.sh` and `.py` run the whole user path against the real code with tiny fake tools: every task and format, `format = auto` (ambiguity is an error), several formats, local copy and link, https URLs served from a local server (right, wrong and missing sha256; http, file and credential URLs; zip-slip; symlink escape; size cap; a decompression bomb), a git source at a pinned commit, script, conda, pip and none installs with a fake conda, the command line, the window routes, and stages 4, 5 and 6 on a small cohort.
- **`plasbench tools remove NAME`**, the window's *Remove* button and `POST /api/usertools/remove` delete a tool you added (never a built-in or a shipped example).

### Fixed -- found by the new add-your-tool tests
- `plasbench tools add` of the folder that already is the installed copy deleted it and then failed; it is now a no-op, and a copy is staged and swapped in so a failed copy keeps the old tool.
- Stage 0 reported a url/local tool whose source was never fetched as `[ok]`; it is now `[MISS]` with the install command (`user_tools.py source-status`). Stage 4 now prints a warning when it skips such a tool, not only a status row.
- **Window updated while open.** The server records its version and program files when it starts; `GET /api/server-state` (key required, cached, starts nothing) says whether the files on disk are newer. The page shows a banner with **Restart window**, **Reload page (clear cache)** and Why?, turns any `no such API: X` into "This window is running an older version of PlasBench than the page" (the original under Details), and compares its own version (`plasbench-page-version`) with the server's at once. `POST /api/server/restart` starts a replacement server and then lets the old one exit like Quit and keep running; runs are detached and are not touched. Where a restart is refused the dialog gives the manual steps. The page is served `no-cache` with an ETag; `/api` stays `no-store`.

- **Browse opens the computer's own folder window.** Every Browse / Choose a folder button now opens the real Explorer-style dialog (Windows, and WSL through `powershell.exe`; Finder on macOS; zenity, kdialog or yad on Linux) with every drive, USB stick and network location, and the chosen folder is converted for Ubuntu (`D:\x` to `/mnt/d/x`) and checked. Routes `/api/native-picker/{capabilities,open,status,cancel,front}` (token and loopback only, one dialog at a time, a timeout or Cancel kills the process); `plasbench/native_picker.py`. Where no desktop window exists the page says why and uses the built-in browser. Open in Explorer sits next to every path field, and pasted Explorer paths (Copy as path, the address bar, `file:///`, `This PC\Data (D:)\x`) are cleaned.
- **Built-in folder browser.** Lists every Windows drive (USB, network, not mounted, no disk) with its real size and free space from Windows and a Copy button for the exact `mount -t drvfs` command; fixes the false capacity (an empty `/mnt/e` folder reported Ubuntu's own virtual disk); adds Desktop, Documents, Downloads, recent folders, Back, Forward, Refresh, filter, sort, hidden files and keyboard keys. The computer card and the chooser read one drive list.

### Fixed -- tools are installed when you run, exit 20 is not an error (project lead report, 19 November 2026)
- **Exit 20 and 21 are information everywhere.** `plasbench install-tools gplas2 --yes` ended with "ERROR: the command stopped: failed with exit code 20". Every wrapper (the window's job console and state, the terminal page, `scripts/lib.sh`'s error trap and `explain_exit`) now treats 20 (a manual step, nothing failed) and new 21 (consent needed, nothing changed) as information, whatever command returned them. `test/test_exit20_wrappers.py` runs a fake command returning each code through every wrapper.
- **Tools install automatically, with consent.** New `python/source_install.py` and `config/source_tools.json` install gplas2 (1.1.0), PLASMe (v1.1), plASgraph2 (v1.0.0), PlasmidEC (1.3.1, the last release with the options PlasBench passes), PlasBin-flow (v1.1) and the Mobilome Annotation Pipeline (v5.0.3 with Nextflow 25.04.8) from an exact commit (tag resolved to a SHA, both recorded; `git rev-parse` must match) into their own environment, run the tool's verification command (gplas2: `gplas --help` must list `-P`), and write a provenance record read by `plasbench check` and the run manifest. The first install shows repository, revision, size and licence and needs `--yes`; a failure leaves nothing half installed and a working install is kept; a second run says it is already installed at the pinned revision; a changed pin upgrades. plsMD and PPR-Meta stay manual with the verified reason, evidence and a recipe in the registry.
- **`plasbench check` and `run` install what is missing, then carry on.** Stage 0 installs missing enabled tools with `--yes`, `INSTALL_MISSING_TOOLS=1` (`plasbench run --install-missing-tools`) or a `y` at a terminal, puts the new environment on PATH and re-checks in the same process (it used to exit 1 and ask for a new shell). With no terminal and no consent it stops before any sample work, naming every missing tool and the exact command. A missing gplas2 now installs gplas2, not bioconda's gplas 0.6.1, which has no `-P`. Stage 4 records a missing tool as `skipped` with the reason and the install command, after one notice naming all of them.
- **Window.** Install and Update buttons per tool (Tools page and Workflow cards), **Install all enabled tools** with one consent dialog, a progress strip, an offer to install missing enabled tools before a run, the installed revision beside each tool, and *Manual step needed* / *Consent needed* shown as their own states, not Failed. `install-tools` accepts a comma list.
- `docs/TOOL_INSTALL_AUDIT.md` (generated) lists every tool with how it is installed, pin, source, size, time estimate, verification and status. New `gitlab` network service. New tests: `test_source_install.sh`, `test_tool_install_registry.py`, `test_exit20_wrappers.py`.

## [0.5.2] - 2026-11-19
Summary. Nothing in this release changes a score, a ranking or a threshold.
- **Install and computer.** `plasbench install-tools` exits 20 ("manual step needed", nothing failed) for profiles PlasBench never installs for you; settings carry ranges that the window checks; the This-computer card shows CPUs, memory, limits, the Windows host behind WSL and every drive; the Version control page's description is a tooltip. Built-in, manual, dry-run and inspection install profiles need no internet: the command-line pre-flight, the window's gating and `/api/net/status` (`offline_install`) agree.
- **Window load and storage.** The window is drawn from a cache (`plasbench/loadcache.py`): tools answer at once with `pending` while the PATH probe finishes, the schema and long lists are cached and gzipped (`docs/WINDOW_PERFORMANCE.md`). The connection check, the workflow chain and the Windows-host probe are off the load path too, and the tests count that.
- **Report figures.** Redesigned fingerprint (radar), synteny view and a smaller precision-recall plot.

### Fixed -- install-tools, the "This computer" card, scoring-setting ranges, version-control note (project lead report, 18 November 2026)
- **`plasbench install-tools gplas2 --yes` is not an error.** gplas2, PLASMe, plASgraph2, plsMD, PPR-Meta, the Mobilome Annotation Pipeline, PlasBin-flow and PlasmidEC are installed by hand; their profiles exited 2 (or 1), and the window then printed "a command was given a wrong option or a missing file". They now print the reason and the exact steps and exit **20** (`manual step needed; nothing failed`). `plasbin_flow`, `plasmidec` and `baseline` used to fall through to a conda package of that name; `baseline` (built in) now exits 0 with "nothing to install". A misspelt profile (`plasmidhuter`) exits 2 and names the nearest profiles. Manual profiles are recognised before conda is looked for, so they no longer report "install conda first". `exitcodes.explain` gives exit 2 of `install-tools` its own text (an unknown name or a wrong option), and `scripts/00_setup.sh` does not count 20 as a failure. New `--dry-run` reports what a profile is with no conda and no network. In the window a job ending in 20 reads **Manual step needed** (amber), with its steps in the console, not Failed. Tests: `test/test_install_outcomes.py`.
- **"This computer" resources and drives.** The card showed only `os.cpu_count()` and the installed memory of the Linux virtual machine under WSL. It now shows CPU model, physical and logical cores, memory total and available now, swap, the limits in force (cgroup memory and CPU, CPU affinity, `.wslconfig`), the Windows host behind WSL (through PowerShell, with a wmic fallback), and what a benchmark will use. A new **Drives** table lists every mounted drive with label, mount point, Windows letter, filesystem, used and free space, type, read-only, plugged-in state, the drive holding the data folder, workspace and current study, and the existing slow-drive and cloud-sync warnings; a Windows drive plugged in but not mounted in Ubuntu shows the `mount -t drvfs` hint (never run); **Refresh** marks newly plugged drives and lists removed ones. A failing probe reads "unknown". `plasbench/computer_info.py`, `GET /api/computer`; tests use sample Linux, WSL, macOS and Windows output (`test/test_computer_info.py`).
- **Range of every numeric scoring setting.** The Scoring decisions page and the Settings page show each numeric setting's type, minimum, maximum, unit and default as a small label and in the tooltip, with number inputs carrying min, max and step (and a slider where both bounds are enforced) and an inline red message outside the range. One table, `config/setting_ranges.tsv`, written from what the code refuses (the decision validator and the scorers' own checks; "no maximum enforced" where the code accepts anything). The settings save refuses an out-of-range value with a plain sentence and never rejects a value that is already saved. Tests: `test/test_setting_ranges.py`.
- **Version control page.** The descriptive paragraph is now the help tooltip beside the heading (`ui_help.WIZARD["git_page"]`).
### Changed -- the window loads fast: the Tools filters, Set up and the run lists no longer wait (project lead report, 18 November 2026)
- **Measured first.** On the project's WSL machine (data on a `/mnt` drive) the Tools page waited about 9 s for `/api/tools` (a PATH search per tool through every Windows folder on PATH), Set up about 4 s for `/api/env`, and every settings call re-parsed `config/config.sh` a dozen times. The before/after table is in `docs/WINDOW_PERFORMANCE.md`.
- **What changed (no behaviour change, no new files on disk).** New `plasbench/loadcache.py`: registry, settings, cohort, doc and per-run rows are remembered until the file they were built from changes (mtime and size); PATH, conda and docker probes are remembered for 30 s and refreshed in the background (stale-while-revalidate); the Tools page draws from the cache at once and shows `checking...` per tool until its probe answers; the schema is built once and the page and JSON are gzip-compressed; the caches are filled at start-up in a background thread; the Tools filter is debounced and writes its table once. Check again / an install / a settings save asks for a fresh probe.
- **No SQLite.** The data the window reads is small, plain text by design (git-tracked, hand-edited, diffable), the delays came from repeated parsing, subprocess and PATH probes, directory walks and client rendering (profile in the docs), a WAL database is unsafe on `/mnt`, OneDrive and cloud folders, and detached runners already share `jobs.json` through a working lock. The docs say when this would be reconsidered.
- **Tests.** `test/test_window_load.py` counts spawns, `shutil.which` calls and file opens on the second call of each load-path route (none), checks invalidation and gzip, and runs `test/tool_filter_perf.js` (150 tools, one DOM write, five keystrokes one render) when node is installed.
### Changed -- three report figures made compact and interactive (project lead request, 19 November 2026)
- **Tool fingerprint** (`python/report_fig_fingerprint.py`, `assets/report/fig_fingerprint_*.html`). One 150 px radar per tool in a grid on one shared 0-1 scale (was one 560 x 470 radar with every tool overlaid), with a code key for the seven axes. Hover or focus shows each dimension, the rank and n; click, Enter or Space opens the side panel with every dimension, its meaning and limits from the registry, the spread across isolates, the per-isolate table and a link to the leaderboard row; arrow keys move between tiles, Escape closes; Compare overlays up to three tools. The numbers table stays in a fold; print shows the tiles. Axes and the not-available rule are unchanged.
- **Precision-recall** (`fig_pr_*`). The figure was already interactive; it is now about half the height (viewBox 640 x 330, at most about 320 px tall, was 760 x 640) with a narrower panel (340 px, was 430). Scores and curves are unchanged.
- **Synteny ribbons** (`python/report_fig_synteny.py`, `assets/report/fig_synteny_*.html`). One comparison (sample, plasmid, tool) at a time, chosen with selectors, at most 200 px tall (was every tool stacked, about 700 px): truth plasmid on top with a kb ruler, scale bar and annotated features, the tool's records below on the same scale, smooth bands that twist only for a reverse block (blue and hatched). Tooltips, a side panel with the alignment table and the plasmid-map link, drag and Ctrl+wheel zoom with `+`, `-`, `0` and arrows, a static fold per comparison for print. The old stacked drawing is kept as `report_synteny.inject_legacy`. Nothing that is scored changed.
### Added -- rebuilding a report's figures from an old or published run: `plasbench check-results`, `plasbench regenerate-visuals`, and report inputs that stay in the results folder
- **Why.** The synteny ribbons, plasmid maps, presence/absence matrix, plasmid-level facets, fingerprints and QC panel read per-sample files (`<sample>/visualization/alignment_blocks.json`, the truth feature and AMR tables, `short_read_qc.tsv`). A results folder that kept only the top-level `benchmark.*` tables, such as `results_real_cohort1` (PlasBench 0.2.3), showed them all as "Not available in this run".
- **`docs/REPORT_INPUTS.md`, generated from `config/report_inputs.tsv`** (`python/report_inputs.py`): one row for every file the report reads, with the stage and script that write it, what a fresh run needs for it, the cheaper inputs it can be rebuilt from, the `--only` key that rebuilds it, and the report sections that read it. `test/test_report_inputs.py` fails when a file the report reads is not in the table or a writer named there does not exist.
- **`plasbench check-results RESULTS_DIR`** says which report sections can draw and, for those that cannot, which required files are absent and whether each can be regenerated from what is present. **`plasbench regenerate-visuals RESULTS_DIR`** (alias `rebuild-report`; `--data-dir`, `--samples`/`--cohort`, `--only truth,paf,alignments,truth-features,qc,keep`, `--predictions-dir`, `--dry-run`, `--yes`, `--force`, `--report`, `--json`; `python/regenerate_visuals.py`) rebuilds them in place by calling the scripts the stages call with the run's recorded settings, so the files are byte-identical to a fresh run on the same inputs (tested). It never overwrites an existing file without `--force`, never rewrites `scores.tsv` or a `benchmark.*` table (`--only scores` only explains how to score again), and verifies predictions supplied with `--predictions-dir` against the run's `scores.tsv` rows (record count and total length) or the kept prediction summary before using them. Exit 0: nothing is left missing; 3: something is; 2: bad arguments. Old layouts are read as found: a folder with no per-sample folders, a pre-0.2 manifest and legacy `<tool>.paf` names are each named in the output.
- **Honest provenance.** Everything it writes is recorded in `<results>/regenerated_inputs.json` (file, kind, time, PlasBench version, tool versions, SHA-256 of every input and of their combination), and the report's Run metadata then says "These files were regenerated after the run" (`python/report_regenerated.py`).
- **Report inputs now stay in the results folder** (`KEEP_REPORT_INPUTS=1` by default, `KEEP_REPORT_INPUTS_MAX_KB=2048` per sample; `python/keep_report_inputs.py`, called at the end of stage 5): the truth tables that lived only in the data folder (`truth.tsv`, `truth_features.tsv`, `truth_amr.tsv`, `truth_circular.tsv`, `truth_proteins.tsv`, repeat tables), a `<tool>.prediction_summary.tsv` (record, length, sequence hash; no sequences) per tool and a `report_inputs.json` manifest. Reads, assemblies and reference FASTAs are never copied. A results folder copied to another machine can rebuild its alignment blocks and report. The run manifest now also records `VISUALIZATION_MAX_BLOCKS_PER_TOOL`, `VISUALIZATION_MAX_NUCLEOTIDE_ALIGNMENT_BP`, `ANNOTATION_AMR_DB` and the two `KEEP_REPORT_INPUTS` settings, so a rebuild uses the run's own values.
- **Cohort 1.** `docs/COHORT1_REBUILD_STATUS.md` lists, for `results_real_cohort1` and every other `results_*` folder in the repository, what is available, what was regenerated and what is still needed.

## [0.5.1] - 2026-11-18
Summary. Nothing in this release changes a score, a ranking or a threshold.
- **GitHub sign-in and actions.** Sign in from the window (device flow through the GitHub CLI) and run GitHub actions from the Version control page.
- **Connectivity checks.** One internet check for everything online (`plasbench net`, `config/network_services.tsv`), used by the command line, the scripts and the window, so being offline is said plainly instead of timing out.
- **Add-your-tool (multi-task, sources, outputs).** One tool can do several tasks; tools can come from a URL, a local folder or a small uploaded script; a tool can describe several outputs, and the Check panel says which output serves which task.
- **Folder scan for isolates.** `plasbench scan-isolates FOLDER` and the window's Scan a folder find each isolate's reads and reference in one mixed folder (`plasbench intake scan/stage` stay).
- **Report visuals.** The short-read QC panel, QUAST-style comparison tables with a heatmap, facet heatmaps, and the presence matrix.
- **Optional MultiQC.** A companion report (`MULTIQC_REPORT`, `plasbench install-tools multiqc`) that never fails a run.
- **Also:** workflow steps (what each optional step adds), and a fix for the Guides page freezing on a `#####` heading.

### Fixed -- opening a guide froze the window
- **The Guides page hung on the README.** The window's Markdown converter knew headings only up to level 4. A `##### ...` line (README line 2168) matched no rule and the paragraph rule refused to take a line starting with `#`, so the loop never advanced and the page stopped responding. The converter now knows levels 1 to 6, every pass must consume a line, and a stuck pass takes the line as plain text, so no input can loop. `test/test_ui_markdown.py` runs the real converter in Node on the exact line that hung, on odd inputs, on 3000 random Markdown-looking documents and on all 36 guides in the repository (each converts in well under a second; the README now takes about 30 ms).
### Added -- one internet check for everything online, and `plasbench net` (no more silent timeouts when offline)
- **`plasbench/netcheck.py`** with `config/network_services.tsv` (service, label, probe address, `used_by`, advice) as the single source of truth: `check()` probes services in parallel (DNS, then TLS and a HEAD request; nothing is downloaded) and tells no network, broken DNS (with the WSL advice), one service down, and sign-in page or certificate problems apart; `require()` raises `NoInternet` with a one-sentence message. `PLASBENCH_OFFLINE=1` refuses every online-only action; `PLASBENCH_ASSUME_ONLINE=1` skips probing; `PLASBENCH_ONLINE_TIMEOUT` sets the wait.
- **`plasbench net [--service NAME] [--json]`**, and a pre-flight for `upgrade`, `install-tools`, `validate-cohort --online`, `discover-cohort`, `discover-design-cohort`, `resolve-contributed-cohort`, `collect-truth-provenance`, `curate-cohort`, `prepare-contribution`, `build-publication-cohorts` and `tools add URL`.
- **`require_internet`** in `scripts/lib.sh`, called before the work in stage 1 (only for what must be fetched: nothing is demanded when the files are on disk or with `--local-inputs`), `update.sh`, `install_latest.sh`, `env/` installers and database downloads, and `scripts/00_setup.sh`. The python/ network scripts check first and explain failures in a sentence. The ENA size lookup in the download estimate is skipped with a note when offline.
- **`test/test_network_declared.py`** fails when a file uses the network without being declared in the catalogue and guarded; new tests `test_netcheck.py` and `test_require_internet.sh`.
### Added -- one tool, several tasks; tools from a URL or a local folder; several output types and `format = auto`
- **Several tasks.** `[tool] task = classification, binning_reconstruction`: the command runs once per sample and each task is a registry row of its own (`<name>` for the first, `<name>__<task>` for the others), converted from the same output, `completed`/`reused` on its own, listed in each task's leaderboard as `<display name> (<task>)` and never ranked across tasks. A derivation table decides what each task can be made from (bins -> classification; labels -> binning only as a flagged one-bin-per-plasmid-contig; a plasmid FASTA -> sequence reassembly only; an adapter -> the tasks in `adapter_tasks`); a task that cannot be produced is a validation error naming the fix. One-task, one-format manifests keep validating and running unchanged.
- **Where the tool comes from.** `[install] method = url` (https only; `sha256` verified when given and loudly missing when not; archive, git or file; size cap, timeout, resumable; archives extracted with path-traversal, symlink, device-file and size guards; `build_command`) and `method = local` (a file or folder, copied with a recorded checksum or linked). `{src}` in `[run] command`. Every install is recorded in `download_provenance.jsonl` and `run_manifest.json` (`user_tools`), and the source is part of the result fingerprint.
- **Several output types and `format = auto`.** `[output] format = contig_bins, contig_labels` with one `[output.<format>]` section each, or `format = auto` with `candidates`: each file or folder is recognised by content (FASTA, folder of FASTA, bins table, labels/probability table; comma, tab or semicolon, `#` headers), the best output is chosen per task by a documented priority, and an ambiguous or unrecognisable output is an error listing what was seen. The choice is recorded per sample.
- `plasbench tools new --task --source --url --sha256 --local-path --output-format`; `tools validate` prints the per-task derivation and the source; new worked examples in `tools.d/examples/` (multi-task, url, local, auto-detect); `python/user_tools.py` exposes `parse_text`, `validate_text`, `TASKS`, `FORMATS`, `INSTALL_METHODS`, `TASK_HELP`, `FORMAT_HELP`, `SOURCE_HELP` for the window's form. Tests: `test_user_tool_detect.py`, `test_user_tool_source.py`, `test_user_tool_multitask.py`, `test_user_tool_multitask_stage.sh`.

### Added -- Add your own tool: several tasks, several sources, several outputs (window)
- **Task is a multi-select.** A reusable, accessible dropdown (button with chips, popup listbox with checkboxes, `aria-multiselectable`, arrows / Home / End / Space / Escape, type-ahead, closes on an outside click, theme and phone-width aware, no library). The first task is the primary one (tagged, reorderable); the form writes `task = a, b`. Beside each task the Check result shows `native`, `derived from <output>` or `not possible: <reason>` (selectable, so the reason can be read).
- **Source selector.** Already installed, package manager (conda or pip), download from a URL (https only, checked as you type; optional SHA-256 with a warning when empty; kind; git ref; build command), a file or folder on this computer (Choose file / Choose folder through the existing chooser, which lists every drive; link or copy; build command), or your own install script. A visible warning that PlasBench runs code you download or point to. Small scripts and adapters (up to 5 MB) can also be uploaded: new token-protected route `usertools/upload` stores them in the tool's own folder under the manifest folder name and refuses paths, names with separators or `..`, binary content and files over the cap.
- **Outputs are rows.** Add or remove outputs, each with its format, its path and only the keys that format needs; or Detect automatically with candidate patterns. Serialised as a plain `[output]`, `format = a, b` with `[output.<format>]` sections, or `format = auto` + `candidates`. The Check panel shows a per-task derivation table, a source summary, warnings, and which output serves which task; problems appear inline with the fix.
- **Tools page and wizard** show one chip per task and, for your own tools, the source (url, local, conda, pip, installed) and the pinned SHA-256 or `not pinned`. Tooltips for every new control (`ui_help.USERTOOL`), an updated *How it works* guide and two more worked examples (a binner that is also a classifier; a tool downloaded from a URL).
- Until the backend (`python/user_tools.py`: `validate_text`, `TASK_HELP`, `FORMAT_HELP`, `SOURCE_HELP`) is merged the window falls back to the single-task check and to built-in help sentences (marked `TODO(backend)`). Tests: `test/test_ut_multi_task_ui.py` (form model under node, rendered markup, upload route over HTTP) and additions to `test/test_ui_help.py`.
### Added -- `plasbench scan-isolates`: point at one folder and PlasBench finds each isolate's reads and reference (18 November 2026)
- **One folder is enough.** `plasbench scan-isolates FOLDER [--json] [--max-depth N] [--write-sheet SHEET] [--data-dir D] [--link ...] [--yes]` walks a folder tree (symbolic-link loops, hidden, `.git`, `results`, `logs`, cloud-only and unreadable files are skipped and counted, never raised), pairs FASTQ reads by many naming styles (`_R1`, `_1`, `.1`, `_R1_001`, SRA, Illumina lanes listed and flagged, never merged silently), tells reference genomes from reads and from assembler output (`contigs.fasta`, SPAdes/Unicycler folders are never a reference), ranks candidate references with stated reasons, and reports every ambiguity or missing piece as an issue. Exit 0 when every isolate is complete, 3 when some need attention. Scanning never modifies the folder. `--write-sheet` places the complete isolates in-process through the same function as `init-local`.
- **In the window**, *Your own isolates > Scan a folder*: folder chooser, progress with a Cancel button, a review table with a tick box per isolate, drop-downs to change the reference or read pair from the alternatives, issue badges, a *Why these files* tooltip and *Add selected isolates* (designed dialogs only). Routes `POST /api/isolates/scan`, `GET /api/isolates/scan/status`, `POST /api/isolates/scan/cancel`, `POST /api/isolates/add` need the token; only files the scan itself listed can be chosen.
- Tests: `test/test_isolate_scan.py`, `test/test_isolate_scan_ui.py`. Guide: docs/USER_GUIDE.md, 'Add isolates from a folder'; FAQ Q59.

### Added -- optional MultiQC companion and a note on MultiQC versus the built-in QC panel (18 November 2026)
- **Correction.** MultiQC was not used anywhere: QC is fastp plus `python/short_read_qc.py`. The report's QC panel is PlasBench's own, modelled on MultiQC's layout. Real MultiQC is now an optional companion.
- **Install.** `plasbench install-tools multiqc` (`env/install_tools.sh multiqc`): its own isolated, pinned environment (`multiqc=1.25.2`, conda-forge and bioconda), not in `environment.yml`, the lock or the `all` loop. `scripts/00_setup.sh` checks it as optional (warns, never fails). Declared in `test/test_install_wiring.py` with profile and check routes (not env or lock, on purpose: isolated and optional).
- **Step.** `python/run_multiqc.py`, called by stage 6 before the report is built: `MULTIQC_REPORT=auto|on|off` (default auto: only when `multiqc` is on PATH; on warns when it is missing) and `MULTIQC_TIMEOUT_SECONDS` (600), both in `config/config.sh` with an explanation so the window's Settings shows them. It runs `multiqc` over every sample's `fastp.json` and each QUAST folder into `results/multiqc/` (`multiqc_report.html`, data and `multiqc_run.json`). It always exits 0: a missing multiqc, no inputs, a timeout or a failure is a warning event in `run_events.jsonl` and a note in the panel.
- **Panel.** A collapsible "MultiQC or the built-in panel? What to know" box at the top of the QC panel (open in the PDF), and a "Full MultiQC report" link when the report exists (relative, or the name without a link when far from the page, as in the file tree; never embedded: size, offline, version drift), a failure note, or how to get it (`plasbench install-tools multiqc`). One shared text (`python/multiqc_note.py`) is also the help of the `MULTIQC_REPORT` setting and `ui_help.REPORT_NOTES["qc"]` for the window's report and QC area.
- Docs: USER_GUIDE section "MultiQC and the built-in QC panel: which to use", FAQ Q33a, INSTALL. Tests: `test/test_run_multiqc.py`. Not run against a real MultiQC install.
### Added -- the short-read QC panel: a MultiQC-style, interactive view of read quality and assembly selection (18 November 2026)
- **Why.** A reviewer asked how read quality was assessed and how reads and assemblies were selected. The report's Short-read QC and Assembly selection sections were plain tables, and for the offline demo and for `results_real_cohort1` they said "Not run", so the reviewer never saw them.
- **`python/report_readqc_panel.py`.** A left section list (General statistics, Sequence counts, Read quality, Read length, GC content, Duplication, Adapter content, Decisions and reasons, Thresholds and policy, Assembly selection). General statistics keeps the per-sample inline bars and adds the toolbar: Copy table, Configure columns (show, hide, reorder; kept in the page only), Scatter plot (any two columns, a point per sample shaped and coloured by decision, hover and click), Violin plot (any column split by decision) and Export as CSV. Distribution plots of every metric with the warn and reject limits drawn as lines. Clicking a sample (a row or a point) opens a side panel, as in the plasmid viewer, with its full QC record: each metric as a gauge against its threshold with the reason it passed, warned or was rejected, the integrity checks, whether it was excluded or flagged, and its assembly selection outcome. Keyboard and screen-reader support (real buttons, a toolbar and tab-like list with ARIA labels, Escape closes the panel, shapes as well as colours), dark theme and phone-width rules.
- **What the reviewer asked** box, with links to the evidence on the page: how read quality was assessed; the thresholds, their status (frozen or provisional, the file hash, and whether it matches the hash recorded in the QC table); what was excluded and why; whether flagged samples change the conclusion (mean F1 per tool with and without them when `scores.tsv` is beside the table, otherwise "Not computed" and why); and how the assembly was selected. Nothing is claimed without data behind it.
- **Assembly selection** is a QUAST-style comparison with a Show heatmap checkbox (Worst-Median-Best shading, off or on; print keeps it), the chosen assembly starred and outlined, and the policy and reason stated. The panel's Assembly selection entry summarises it and links to it.
- **Print and PDF.** Every sub-section is written out statically, so the PDF export (and a browser without JavaScript) shows all of them stacked, open, with the per-sample records; the toolbar, section list and side panel are hidden in print. The earlier table stays as a collapsed "All values" fold; nothing was removed.
- **Not measured in this run.** A run without `short_read_qc.tsv` or `assembly_candidates.tsv` (for example `results_real_cohort1`, made by PlasBench 0.2.3) shows what is missing and the exact command (`SHORT_READ_QC_MODE=report plasbench run --cohort <cohort file>`, or `python python/qc_pilot.py`), never an empty or invented panel.
- **The offline demo shows it, honestly.** `python/make_demo_readqc.py` (called by `test/run_demo.sh`) writes SYNTHETIC `short_read_qc.tsv`, `short_read_qc_status.tsv` and `assembly_candidates.tsv` for the six demo isolates from fixed figures (deterministic; 3 PASS, 2 WARN, 1 REJECT; the decisions follow from the figures by `short_read_qc.decide` and the shipped thresholds) with a `short_read_qc.provenance.json` marker; the panel says "Synthetic" twice. It refuses, writing nothing, unless every sample in the sheet is marked synthetic, and never replaces a QC table it did not write.
- Tests: `test/test_report_readqc_panel.py` (builders, gauges, absent and empty states, escaping, print markers, the demo and `results_real_cohort1` builds), `test/test_make_demo_readqc.py`, `test/test_readqc_panel_js.py` (pure helpers under node, and a syntax check of the page script). Help text, the data-inventory entry for the provenance file and FAQ Q33 updated. The page script's interactive behaviour was not exercised in a browser.
### Added -- the comparison table: metric-by-tool tables become interactive grids with a side panel (the project lead's request, 18 November 2026)
- **A reusable component** (`python/report_compare_table.py`, `python/report_compare_apply.py`, `assets/report/compare_table_{style,core,ui}.html`). Metrics are rows (grouped under the headings the report already uses), tools are columns. Each row is shaded Worst (red), Median (white), Best (blue) **by rank among the tools assessed in that row, never by raw value**, so one extreme value cannot hide the rest; tied tools share a rank. Direction (higher or lower is better) comes from the metric registry and the scorecard; a metric whose direction is not defined is not shaded and says "direction not defined". A row with fewer than two assessed tools, or in which every tool ties, is not shaded and says why. Missing and "not assessed" cells are hatched, never shaded and never zero.
- **Controls:** a "Show heatmap" checkbox, collapsible metric groups, a tool filter, sorting of tools by mean rank or by one metric, re-ordering by a drag handle or the arrow keys on it, a "best in row" star, a CSV download, and a definition tooltip on every metric name (definition, direction, unit, source table and column). Keyboard use follows the ARIA grid pattern (arrow keys, Home and End, Enter or Space to open, Escape to close); dark theme; at phone width the grid scrolls with the metric column fixed.
- **A side panel**, as in the plasmid viewer. Click a cell: the value, its rank in the row, n, the interval, the per-isolate values as a strip with quartile box (outliers marked), the isolates ranked best to worst with links to their rows in the score table, and the same metric for the other tools. Click a metric name: its definition and where it comes from (registry id, evidence, limits). Click a tool: its profile across every metric.
- **Applied to eleven tables, each kept in a closed "Table" fold** (nothing removed): the leaderboard (per track and task), graded plasmid recovery, MCC / F2 / F0.5 / abstention, per-plasmid outcomes, the contig layer, bin quality tiers, sequence accuracy, feature preservation, gene-order conservation (NGOC), computational performance and the five-dimension composite. The text in a comparison cell is the text of the table cell (the same strings are passed to both). One component per track and task: tools of different tracks are never ranked together.
- **Print and PDF.** The static grid is complete without JavaScript: shading is kept (and forced on while printing), the panel and toolbar are left out and the original table prints open.
- **Help.** A green ? on every comparison table (`compare-table` in `python/report_help_text.py`); the help step now also lists buttons a component places itself. The condense step leaves a comparison grid alone. `python/report_surfaces.py` rows for the converted tables say they are comparison tables.
- **Tests.** `test/test_report_compare_table.py`: ranking, direction, ties, missing and "not assessed", escaping, panel data against table text, print markers, empty states, the toolbar / checkbox / panel / ARIA, the JavaScript ranking and shading functions against the Python mirror (node), and builds of the demo report and of `results_real_cohort1`.
### Added -- two interactive figures that replace reading tables: facet heatmaps by stratum and a clustered feature matrix (18 November 2026)
- **`fig-facets` (Figures, `python/report_fig_facets.py`).** Small-multiple heatmaps after the profiler-benchmark layout: columns are tools (the same order in every panel, from the leaderboard), rows are conditions nested in blocks, one panel per metric, one shared 0 to 1 colour bar. You pick the block and row strata from what the data record (species, sequencing-depth band, reference tier, source study, sample origin, Gram group, plasmid content, plasmids in the truth; with per-sample folders also plasmid size, replicon type, MOB type, AMR carriage, circular truth), the metrics (precision, recall, F1, CPRR, plasmid recall; recovered, CPRR correct, completeness at plasmid level), the unit (isolates or plasmids) and the track. The cell shows its n. **A cell with fewer than 3 units (adjustable) is hatched and flagged "too few"**, never shaded as a result; a combination with no unit is a dashed blank, never zero. Click a cell (or Enter on it; arrow keys move) to open the side panel: n, value, interval, a strip plot and every isolate or plasmid in the cell with its values, linked to the plasmid map. Means carry their range (labelled as a range); CPRR and recovered share are pooled over plasmids with a Wilson interval (not cluster-aware, labelled). Download CSV; a complete static SVG is the no-JavaScript and print version; the table of every cell is a collapsed fold.
- **`fig-presence` (Figures, `python/report_fig_presence.py`).** A clustered presence/absence matrix of the truth plasmids: rows clustered on the feature profile by a deterministic pure-Python average-linkage (Jaccard) clustering with its dendrogram, annotation tracks (species, source study, reference tier, size band, replicon), feature blocks from the annotation tables (replicon, MOB, AMR gene class or gene, insertion sequences and any protein class the table holds; only blocks the data contain) and a prevalence bar with n above every feature. **Hatched means not annotated, which is not the same as absent**; nothing is inferred. A tool selector overlays the real outcome per plasmid (recovered = counted correct by CPRR, partly recovered, missed). Order rows by any annotation, switch AMR classes and genes. Click a plasmid row for its facts, features, per-tool outcomes and a link to its circular map; click a feature column for prevalence by group and the recovery of the plasmids that carry it, per tool, with a Wilson interval. Static SVG for print; the table of every plasmid is a collapsed fold.
- Both degrade to `Not available in this run: <what is missing>` (listed in Run metadata when the section would hold only that notice). Dark theme, phone width, keyboard operation and ARIA labels are built in; none of it has been checked in a browser yet.
- Registered in `report_figures.py`, `report_layout.py`, `report_wiring.py`, `report_help_text.py` (green ?) and `report_surfaces.py` (`truth_features.tsv` and `truth_amr.tsv` are now shown by the matrix). Tests: `test/test_report_fig_facets.py`, `test/test_report_fig_presence.py`, `test/test_report_fig_visuals_js.py` (node, with a fake DOM), `test/test_report_fig_visuals_build.py` (demo and cohort-1 builds).
### Added -- the workflow at a glance: steps, what each tool adds, and a clearer On / Off (19 November 2026)
- **A Workflow view on Tools and on New benchmark.** The run is drawn as one ordered chain (check, download, truth, assemble, run the tools, score, aggregate and report, long-read tools, operational reconstruction, and the metagenomics track). Each tool or optional step is a switch with a one-line description, badges for what it needs (a database, the internet, an earlier step, an input such as long reads), and its added time, memory and disk. *Workflow | List* toggles between it and the existing list; both change the same setting (the saved setting on Tools, the per-run choice on New benchmark), so they stay in sync. Under each step, *What can I add here?* lists the optional items that are off with their cost; an *Enabled extras* strip shows what you added.
- **A live estimate, honestly labelled.** The bar at the top totals the selection per isolate or per 10 isolates and says *estimated*. Time and disk add up, memory is the largest single tool, one-off database downloads are separate. Each figure is *measured* (the 10 real isolates in `results_real_cohort1`: assembly, MOB-recon, Platon, plasmidSPAdes, coverage baseline), *documented* (README or config.sh: 630 MB disk per isolate, the 2.9 GB and 2.7 GB databases, the 32 GB floor Plasmer documents) or *not measured*, which is listed and never counted as zero (the total then says *at least*).
- **Dependencies.** Turning on something that needs an earlier step that is off offers to turn it on as well (gplas2 needs MOB-recon, evidence-based truth labels need the reference annotation); turning off a step others need warns first. Designed dialogs, no browser prompts.
- **One chain, one test.** `config/workflow_steps.tsv` and `plasbench/workflow_steps.py` are the single source; `GET /api/workflow` serves the chain with the current settings, defaults and estimates. `test/test_workflow_steps.py` fails when a tool in the registry or a stage script is not in a step, when a setting key or command-line flag does not exist, or when a default disagrees with `config/config.sh`; `test/test_workflow_ui.py` runs the page's arithmetic under node against the Python one.
- **Off no longer looks like On.** On is green with a tick, Off is plum with a cross and a dashed outline (and the word), both with enough contrast in light and dark (at least 4.5:1). The same colours now show on the switches, the on/default/off buttons of New benchmark, the on/off text on the Tools page and flag selects on Settings. An item at its default shows its default state's colour; an item changed from its default carries a *changed* tag. Help marks, warnings and errors keep their colours.

### Added -- a logging pipeline across the workflow, and `plasbench status` / `diagnose` (a run that sat silent for hours, 18 November 2026)
- **Why it was silent.** Stage 3 ran fastp and SPAdes as plain commands writing to their own logs, and the "still working" heartbeat existed only for the stage-4 tools (and wrote to `/dev/tty` or into the tool's own log, so it never reached a run log). A 9.5 GB isolate could sit there for hours with no line in the run log.
- **Heartbeats everywhere.** `run_with_heartbeat` now covers fastp, SPAdes, Unicycler and the alternative assemblers, and its line carries elapsed time, CPU and memory of the command and what it started, the machine's memory/swap/disk, and how long ago its own log changed with that log's last line. It writes to the run's console (a saved descriptor) so it reaches the run log and the terminal, never the tool's log. It warns below 300 MB of free memory and when a command is idle (almost no CPU, no log output for ten minutes).
- **`results/run_events.jsonl`.** One JSON line per stage start and end, isolate step, command start and end (exit code, seconds), download and assembly and tool result, heartbeat and warning (`run_event` in `scripts/lib.sh`; valid JSON for any value; no environment or commands).
- **`logs/run_<time>.log`.** The run's whole console output is kept in the study (newest 20, `LOG_RETENTION_RUNS`; `logs/run.latest.log`; `RUN_CONSOLE_LOG=0` off), closed and waited for at exit so the last lines are never lost.
- **`plasbench status` and `plasbench diagnose`** (`python/run_status.py`; `--study`, `--results-dir`, `--json`, `--watch`): state (running, finished, stopped: cut off), stage/isolate/step and how long, progress, processes, machine, newest log, and hints that each show their evidence (huge read set, low memory, swap, low disk, a cut-off run).
### Added -- downloads you can follow, and sizes you can see first (field use, 18 November 2026)
- **Progress in the run log.** While reads download, stage 1 logs a line every `DOWNLOAD_PROGRESS_SECONDS` (60) such as `SRR123: mate 1 74.7%, mate 2 66.2% (7.1 of 9.5 GB)` (`python/download_progress.py`, reading aria2's control file: the `.part` file is preallocated at full size, so its size is not progress). A long download no longer looks stalled.
- **Read sizes before and during the download.** Stage 1 asks ENA for each run's exact size, logs it, warns above `WARN_RUN_DOWNLOAD_GB` (5), and skips an isolate above `MAX_RUN_DOWNLOAD_GB` (recorded as failed with the reason). The estimate printed first uses ENA sizes when there is no lock file and names the largest read set; it uses decimal GB like the download log.
- **The SRA Toolkit failing on every isolate no longer costs a minute each.** After `PREFETCH_FAIL_LIMIT` (2) isolates in a row where `prefetch` failed and ENA worked, stage 1 goes to ENA first for the rest of the run; the log shows the toolkit's own last line as the reason (it showed the retry wrapper's message before). `READ_SOURCE=sra` never skips it.
- Settings added to `config/config.sh`, so they appear in the window's Settings page with their explanations: `MAX_RUN_DOWNLOAD_GB`, `WARN_RUN_DOWNLOAD_GB`, `PREFETCH_FAIL_LIMIT`, `DOWNLOAD_PROGRESS_SECONDS`, `ENA_DOWNLOAD_CONNECTIONS`, `DOWNLOAD_CONFIRM`, `ENA_SIZE_LOOKUP`, and the 0.5.0 run-health settings (`ALLOW_ALL_TOOLS_FAILED`, `MIN_FREE_DISK_GB`, `PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS`, the lock heartbeat and stale limits, `PLASBENCH_REQUIRE_CHECKSUMS`, `ALLOW_INCONSISTENT_RUNS`, `ALLOW_INPUT_MISMATCH`, `SHARED_MIN_FRACTION`, `SHARED_MIN_SAMPLES`, `RUN_TRUTH_EXCLUSION_SENSITIVITY`). `ENA_PORTAL_URL` points the lookup at a mirror.
### Fixed -- a file that is not a cohort, and a help screen that crashed
- **The report's file explorer could write the machine's folder names into the page.** A file in a folder far from the report (a logs folder elsewhere) was linked through a chain of `../` ending in the builder's home path. Such files are now listed by name, without a link, and say why; a log one level up (the study layout) is still linked. It surfaced when a run's console log made the logs folder non-empty during the AU-018 test on CI.
- **Cancelling a run a moment after it started left it in `cancelling`** for the whole 60-second startup grace period, because a runner with no heartbeat yet was assumed to be starting even when its process was already gone. A runner whose process has exited is no longer "starting"; the cancel completes at once (found by the cancelled-job persistence test on Linux).
- **`plasbench run --cohort accepted_accessions` failed with one identical error per isolate.** The accession ledger is not a benchmark sheet. The command now stops once, before a study folder exists, says what the file is and names real cohorts; `--samples` with the ledger is refused the same way; unknown-cohort messages list only files a run can use (a minimal sheet is never refused: stage 0 owns the curation rule, which config/local.env can switch off); stage 0 prints the first three bad rows and a count (`plasbench/sheetcheck.py`).
- **`plasbench run --help` crashed** (`TypeError: %o format`): a help string said `15% of the cohort`, which argparse reads as a format code. A test now formats the help of all 59 parsers.
- The help of `--no-report-prompt` and `--open-report` now says what they do and that `--no-report-prompt` changes nothing about the run.

### Added
- **The window explains every setup field.** An (i) button next to each field of the New benchmark wizard, the All commands forms and the Settings page opens (on hover, keyboard focus or tap; Escape closes it) the field's meaning, one line per option, its default, its command-line flag and setting name, and when to leave it empty. The text is written once in `plasbench/ui_help.py` and sent by `/api/schema` and `/api/settings`, so the page has none of its own.
- **New benchmark, step Options:** a checkbox "Open the report in my browser when the run finishes" (`--open-report`; `--no-report-prompt` stays on, so the run never stops to ask), and a "Downloads and reliability" card that sends READ_SOURCE, MAX_RUN_DOWNLOAD_GB, WARN_RUN_DOWNLOAD_GB, PREFETCH_FAIL_LIMIT, TOOL_TIMEOUT_SECONDS, ALLOW_ALL_TOOLS_FAILED, NETWORK_RETRIES and ENA_DOWNLOAD_CONNECTIONS with the run. They show in the review command (`KEY=value plasbench run ...`) and in the Jobs list; a saved script cannot carry them. The Settings page gains a "Reliability and downloads" group.
- **A quiet run is explained.** The "stalled" state now reads "No new output for N minutes. This is often normal while reads download or a tool assembles. Closing this window does NOT stop the run.", with **Check activity** (`GET /api/jobs/<id>/activity`: the files written most recently in the results and data folders, walk capped at 2000 entries or 2 s, symlinks not followed) and **Cancel**; when files are being written the chip reads "Working (quiet log)".
- **Designed dialogs everywhere.** The browser's alert / confirm / prompt boxes are gone: one accessible dialog (role=dialog, focus trap, Escape cancels, Enter presses the default button, the safe button is the default for destructive questions, optional type-the-name confirmation) asks every question. Cancelling a run shows its label, command, start time and stage, and says finished work is kept.
- **Delete run folder.** The Runs page separates **Remove from list** (the files stay) from **Delete folder...**, which removes a study's results folder, or a listed folder that holds PlasBench results, after showing what goes and asking for the folder's name. It refuses the program folder, the workspace, studies, the home folder, roots, symlinks and any run that is going (`POST /api/runs/delete`).
- **Workspace folder tree.** The Workspace page shows the workspace as a lazy tree with a breadcrumb bar, a path box, keyboard navigation and a right-click menu (open folder, open report, open in terminal here, copy path, properties, manage study, delete run folder). `GET /api/fs/list` and `GET /api/fs/properties` are confined to the workspace and never follow symlinks.
- **Where downloaded data goes, per run.** `run --keep-data-in-study` keeps the reads in `<study>/data` (git-ignored, deleted with the study); `run --data-dir` is remembered per study; a later run of the same study reuses the recorded folder. Manage study gains "Delete downloaded data only". The wizard has a "Where to keep downloaded reads and assemblies" card.
- **A study anywhere.** `run --study-location PARENT_DIR`, the window's Location choices and "Add an existing study folder..." keep a study outside the workspace; a hidden registry (ignored by git) finds it by name, and a disconnected drive is listed as "not available" instead of failing.
- **Choose a folder shows the PC.** The chooser has Quick places and This PC (in Ubuntu also the Windows drives from /mnt), a breadcrumb, a path box that accepts Windows and `\\wsl.localhost` paths, New folder, and the folder check (free space, sync-folder and slow-drive warnings); an unmounted drive gets the exact mount command to run.

### Fixed
- **Open folder** no longer fails with "No such file or directory" where `xdg-open` is missing (WSL): it uses explorer / open / wslview / explorer.exe with `wslpath -w` / xdg-open / gio / kde-open / gnome-open, and when none exists the window shows the path with a Copy button.

- **A cancelled job stays in the Jobs list.** The saved job list is read-merged-written under an exclusive lock (a lock file with a stale-lock timeout; Windows, POSIX and WSL), deletions are written down so they stay deleted in every window, each job has a `<id>.meta.json` written at launch and at every change so the list is rebuilt from the job folder if the index is lost or behind, and failed / interrupted / cancelled jobs are kept until deleted or older than `PLASBENCH_JOB_RETENTION_DAYS` (default 180, 0 = for ever). Runs started in the Terminal or a shell appear under Runs and reports, read-only and marked "started outside the window".
- **The folder trees no longer refresh under your hands.** The Workspace folder tree is rendered once and patched by key (expansion, selection, scroll and focus are kept); a slow 25 s signature check updates only changed rows and is suspended while a dialog or menu is open, the pointer is over the tree or focus is in it. The side panel's study tree is patched instead of rebuilt every 15 s, and the Runs list, Jobs table, job selector and tables are redrawn only when their content changed.
- **Run status panel.** Ongoing runs on the Runs page and the stalled-run panel show what the run is doing now (stage, isolate, step, how long), CPU and memory of its processes, the computer's free memory, swap and disk, progress counts, the newest log with its age, and plain-words hints with their evidence, from `GET /api/runs/status` (same confinement as the other run routes, cached 3 s, never an error: a failure is `{"state": "no-run"}`). It refreshes every 5 s only while visible and not while a dialog or menu is open; the stalled chip shows the first hint. Buttons: Refresh, Copy diagnosis, Open the console log, Open run_events.jsonl.
- The wizard's Downloads and reliability card has "Keep a console log of the run in the study (logs/run_*.log)" (default on; `RUN_CONSOLE_LOG=0` when unchecked) and a field for `LOG_RETENTION_RUNS` (default 20).
- **Sign in to GitHub in a pop-up.** The Version control page signs in with GitHub's device flow through the GitHub CLI: a dialog shows the one-time code, the address opens in a pop-up window of the page (opened in the click itself, so blockers allow it, with a fallback Open button), the window polls every 2 s and closes the pop-up on success, and runs `gh auth setup-git`. Cancel and a 15-minute limit stop the process; without `gh` the window shows the install command and offers a personal-access-token sign-in over standard input. The page never sees a token. Routes: `POST /api/github/signin/start|cancel|token`, `GET /api/github/signin/status`, `POST /api/github/signout`, `GET /api/github/account`.
- **GitHub actions in the window.** Create a repository on GitHub, clone from GitHub, branches (switch, push, delete local and remote), pull requests (create, list, view with checks, reviews, mergeability, files and comments, check out, ready, close, reopen, comment, merge with method, delete branch or auto-merge), checks and re-run of failed runs, issues, releases and tags, through `gh` (`POST /api/github/op`); a merge with failing checks or conflicts needs a confirmed risk; no force-push; failures in plain sentences.
- **Internet awareness.** An Online / Limited / DNS problem / Offline indicator in the top bar, every control that needs the internet marked `data-needs` and switched off with the reason (re-checked at the click), and server routes that answer 503 `{error: offline, service, state, advice}` for jobs that need an unreachable service. Offline never blocks local work; a run whose reads are already on disk still starts. (`plasbench/netgate.py` codes against the connectivity layer `plasbench/netcheck.py` and works without it.)
### Changed
- `POST /api/jobs` accepts `env` only for UPPER_SNAKE names that are Settings keys of `config/config.sh` or the download names above (not PATH, LD_PRELOAD and the like), with one-line values under 200 characters; anything else is a 400.
- The accession ledger `cohorts/accepted_accessions.tsv` is marked `ledger` and no longer offered as a cohort; the Quit dialog says in one sentence what each choice does.

## [0.5.0] - 2026-11-18
Scores change in this release (NMI/VI/ARI, AMR placement and gene recovery, empty-bin precision, truth provenance labels, interval clipping): see [docs/releases/v0.5.0.md](docs/releases/v0.5.0.md) before comparing with a v0.4.1 result. It fixes the 53 findings of the independent audit of 17 November 2026 (42 fixed, 10 partial, 1 not fixed; per finding in [docs/AUDIT_2026_11_17_STATUS.md](docs/AUDIT_2026_11_17_STATUS.md)), adds public-v4, frozen QC thresholds, the interval decision, study management in the working directory and the truth-exclusion sensitivity, and ships a real-data evaluation (`results_real_cohort1/`, 10 isolates, three real tools). The full-suite QA result is in [docs/QA_RESULT_2026_11_18.md](docs/QA_RESULT_2026_11_18.md).

### Added -- audit follow-up (AU-021, AU-022, AU-045, AU-051)
- **Shared readers (AU-021).** `plasbench_common.read_fasta_records`, `iter_paf`, `read_table` and `paf_identity` are the one validated reader set: a duplicate FASTA id or an empty header is an error, a malformed PAF row is dropped, counted and warned about once, a zero-length block has identity 0.0 everywhere (`build_enterprise_view` used 1.0). `score_plasmids`, `contig_classification`, `make_truth`, `score_bins`, `score_amr_placement` and `build_enterprise_view` use them; scores on valid input are unchanged (`test/test_shared_readers.py`). Other readers in the repository are not yet moved.
- **Guard tests (AU-022).** `test/test_guard_mutants.py` covers the synthetic/real refusal, the commit secret scan and the TP clamp; each was checked by hand mutation.
- **Test honesty (AU-045).** The evidence-ledger test checks the enclosing definition and asserts the cited behaviour for 21 rows; `test_scoring_adversarial.py` labels known-optimism pins and asserts the corrected expectation beside them. Ledger line numbers for E1-E7 and E12 corrected.
- **Readers, bins and ledger (AU-021, AU-045, AU-048).** Twelve more modules read PAF or FASTA through the shared readers (`score_plasmids`, `score_bins`, `alignment_accuracy`, `bin_quality`, `feature_preservation`, `copy_number`, `long_read_support`, `call_structural_variants`, `scorable_truth`, `contig_crosscheck`, `validate_structural_evidence`, `compare_runs`) with unchanged scores; `score_bins` skips secondary alignments and refuses a target length that disagrees with the truth, as the base scorer does; the evidence-ledger test now asserts behaviour for 46 of 49 rows.
- **With and without the truth exclusion (AU-051).** `python/truth_exclusion_sensitivity.py` writes `benchmark.truth_exclusion_sensitivity.tsv` (stage 6, report Truth labels tab, `plasbench truth-exclusion-sensitivity`): base-level F1 under the NCBI labels and the evidence labels, rank and top-tool change, and the change for tools that share a database with the truth markers.
- **Run lock heartbeat (AU-009).** The lock holder touches `.run.lock.heartbeat` every 5 s; a lock whose heartbeat is older than `PLASBENCH_LOCK_STALE_SECONDS` (60) is stale even when its pid is alive, which covers pid reuse; the window's `lock_holder` applies the same rule (`test/test_run_lock_heartbeat.sh`).
- **Tool timeout preset (AU-010).** `PLASBENCH_TOOL_TIMEOUT_PRESET=generous` sets `TOOL_TIMEOUT_SECONDS=172800` (opt-in; the default stays no limit) and stage 4 says at the start when no limit is set (`test/test_tool_timeout_preset.sh`).
- **Download pin (AU-026).** The gplas2 source archive is pinned in `config/download_checksums.tsv` (fetched and hashed 2026-11-17); the databases over ~300 MB are not pinned.
- **Reconstruction headlines with and without the truth exclusion (AU-051).** `truth_exclusion_sensitivity.py --rescore-reconstruction` (stage 6) re-scores the binning F1 and CPRR under both truths from the stage-5 files (`test/test_truth_exclusion_reconstruction.py`).

### Fixed -- the 17 November 2026 independent audit (53 findings; see `audit-2026-11-17/` register)
- **Scores.** NMI, VI and ARI now penalise a plasmid no bin covers (unassigned bases are singleton clusters; AU-003). An AMR gene on a record in no bin is `unassigned_contig`, not `correct_plasmid` (AU-004). Contig F1 shows its excluded share and is marked not comparable with base F1 (AU-020). A sample with no provenance record is no longer assumed identity-valid (AU-029).
- **Truth provenance.** `classify_method` reads `OXFORD_NANOPORE`, `IlluminaMiSeq`, misspelt Unicycler, HGAP and the Illumina polishers (Polypolish, Pilon, ...); public-v4 and the negative controls are relabelled with `python/relabel_cohort_provenance.py` and their lock hashes updated (AU-005, AU-006, AU-014). `validate-cohort` warns where `truth_technology` and the assembly-method strategy contradict (AU-027).
- **Report.** Runs completed never exceeds 100%; contamination is FP/(TP+FP) as labelled; summary tiles count tools across tasks and show failed and skipped separately; the validity table and the leaderboard share one independent-unit count; run metadata shows version, databases, container and settings; input validation refuses a mismatched leaderboard and scores; small or empty shared-sample sets are flagged; a Tier 1-unreachable banner (AU-007, 012, 013, 015-019, 028).
- **Workflow.** Per-run temp folders and a run lock; adapters fail with "no output from <tool>" when only a log was written; process-group cancel and orphan recovery; `stalled` and `completed_with_warnings` job states; stage 4 exits 4 when every tool failed; stage 8 uses only current predictions; retries start clean; per-run thread counts and `stage_timing.tsv`; helper timeouts; atomic table writes (AU-001, 008-011, 030-033, 035, 044, 049).
- **Web window and security.** Run reports are served under a sandboxing CSP and bundle import refuses unlisted members; terminal commands are redacted before logging; the commit secret scan covers all text files up to 5 MB; database downloads record or verify a SHA-256; zip-bomb and reserved-name checks; `config/local.env` is owner-only and NCBI keys go in a POST body; new window controls and one task vocabulary (AU-002, 024-026, 036-041).
- **Housekeeping.** Seven unused functions removed (AU-043); documentation counts corrected (AU-042); review-ledger line pins updated.
- **Follow-up to the audit (partial items).** The five Popen pipelines (seqtk, filtlong, badread, the streamed decompressor, minimap2 | samtools) are bounded by `PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS` and kill the producer (AU-044). Stage 4 checks each prediction FASTA and marks a malformed one failed at once, and pre-flights the PlaScope, plsMD, Plasmer and MOB-suite databases as it already did for Platon, geNomad and PLASMe (AU-035). `PLASBENCH_TIME_BIN` points stage 4 at another GNU time, which is how the blank-memory note is now tested (AU-033). The stale-lock handling of the run lock is serialised by a mkdir guard (AU-009). `config/download_checksums.tsv` is a registry of download checksums that `verify_or_record_download` reads; `PLASBENCH_REQUIRE_CHECKSUMS=1` refuses an unpinned download; the Dockerfile takes an optional `GPLAS2_SHA256` (AU-026; no value is pinned yet because none could be verified offline). The window explains a rank, words an exit-0 run with failed tools as 'completed with warnings' in the toast, shows a `retrying` state, and the commit page has a Copy patch button that uses `git/show` (AU-041, AU-010, AU-039).
- **Not fixed or only partly fixed:** see `docs/AUDIT_2026_11_17_STATUS.md`.

### Added -- thresholds frozen from real data; studies managed in the working directory
- **Short-read QC thresholds are frozen** (`docs/THRESHOLD_FREEZE.md`, file hash `0727af448900`): all ten rows `frozen`, set from a real-read pilot (`python/qc_pilot.py`, the first read pairs of 40 real public-v4 runs, `docs/validation/short_read_qc_pilot.tsv`; 20 of 60 could not be fetched, with reasons) and the ENA read counts of 7,129 runs. One change before freezing: `adapter_fraction` has no reject limit (stage 3 trims adapters; a good run had 66%). `gc_deviation` is frozen but inert and not backed by the pilot. The assembly QC limits (8.5 Mb, GC spread 0.12) are frozen unchanged with their evidence (0 of 3,428 genomes of 11 clinical species exceed 8.5 Mb; 361 of 3,799 other-taxa genomes do). Not frozen, with reasons: `MIN_ASSEMBLY_ADEQUACY` and the candidate-multiplicity limits.
- **`git init` lives in the working directory.** One repository for all studies, with a managed ignore block that reaches into every study (sample data, reads and tmp at any depth); a study that already has its own repository keeps it and is left out. Initialising inside a study is refused with an explanation. The Git page and side panel offer "Working directory: all studies" first.
- **Study management** (`plasbench/study_manage.py`, Workspace page -> Manage): notes and tags, rename, copy, archive and restore, delete with the files and bytes shown and the study's name typed back (blocked while a run uses the study), export and import of zip bundles with a manifest, schema version and checksums (import refuses path traversal, oversized bundles, damaged files and bundles from a newer PlasBench). Adopts the ideas of GenoSuv's working folder; rename, copy, archive and bundles go beyond it.
- Stale issues #1 to #4 (test entries) closed; 96 merged remote branches deleted (four unmerged ones kept as `archive/*` tags).

### Added -- the interval decision, and the negative-control search tools
- **Interval decision (pre-registered): `interval_method_stratified` = `bootstrap_t`.** For a species-balanced (stratified) mean the studentised cluster bootstrap is now the default (`PLASBENCH_CI_METHOD_STRATIFIED`): in the full simulation it is at least as good as the cluster-robust t in every stratified design and about 6 points better with one dominant species (0.94 against 0.88, which turns that design from below nominal to consistent with 95%). The unstratified interval stays `cluster_t`, and the dominant-study percentile rule still applies first. Recorded in `config/prereg_decisions.tsv` (decided by Claude as an expert, delegated by the project owner), the lock refreshed (70 decisions), and the committed simulation results re-run (every other column reproduced).
- `discover_ncbi_cohort.py --negative-controls` gained a bulk single-sequence filter (a plasmid-bearing genome has at least two sequences) and `--refseq` / `--hybrid-sequencing` to narrow the search: 22 of 1,500 *E. coli* candidates survive it. The plasmid-free cohort itself is `negative-controls-v1` from the same day's `discover_plasmid_free.py` (#114); an independent live search here found the same kind of isolates (*S. aureus* 24, *E. coli* 6, *K. pneumoniae* 2 candidates) and was not merged as a second cohort.

### Fixed -- the P0 items from the independent audit (`audit/`)
- **Zero-plasmid isolates in the binning scores.** `bin_f1`, `bin_precision`, `bin_recall` and `lw_bin_precision/recall/f1` (and the strict F1) are now blank, not `0.0000`, on an isolate with no true plasmid, as `docs/METHODS.md` already said and `score_plasmids.py` already did. Precision is a real 0.0 when something was binned there. Isolates that DO have plasmid are unchanged (a tool that bins nothing there still scores 0). Effect: negative-control isolates no longer enter a binner's mean as a forced zero.
- **Padded bins are now visible in the robustness analysis.** `lw_bin_f1_strict` (which charges sequence a tool put in a bin that aligns nowhere) is a `metric:lw_bin_f1_strict` row of the rank-robustness table. The pre-registered headline (`lw_bin_f1`, CPRR) is unchanged.
- **A stage no longer looks successful when a sample's job crashed.** Stages 4 and 5 now detect a per-sample job that died (previously a bare `wait` hid it and no row was written), finish and keep the other samples, then fail naming the crashed samples. `ALLOW_CRASHED_SAMPLE_JOBS=1` continues with a warning instead.
- **A tool that exits 0 and writes nothing is `failed`, not `completed`.** For mob_recon, Platon, plasmidSPAdes, geNomad, PLASMe, RFPlasmid, PlasmidHunter and Plasmer, the adapter now runs only if the tool left a file in its output directory; before, a silent crash was recorded as "no plasmids found".
- **Ctrl+C, TERM and HUP stop the tool.** The stage scripts now stop their child processes (TERM, then KILL after 5 s) instead of leaving the tool running with nothing watching it.
- **A laptop that sleeps no longer duplicates a run.** The window's job watcher keeps watching an `interrupted` run and puts it back to `running` when the runner's heartbeat returns, and Resume is refused while the original runner is alive.
- **Window: names containing an apostrophe, quote or backslash no longer break buttons.** Values placed in inline handlers and `data-run` attributes are now escaped for the context they are used in (`jsq`/`dattr` in `plasbench/data/ui.html`). Tests: `test_webui_inline_handlers.py`, `test_zero_plasmid_bin_scoring.py`, `test_job_sleep_resume.py`, `test_stage_failure_visibility.sh`.

### Added -- the remaining gaps from the literature review
- **PLSDB novelty** (`python/plsdb_novelty.py`, `plasbench analysis plsdb-novelty`; stage 6 when `PLSDB_FASTA` exists, `RUN_PLSDB_NOVELTY`): each truth plasmid is classed known, related or novel by the best PLSDB record (minimap2 asm20; thresholds `NOVELTY_*` in the settings), recovery is compared across the classes per tool with the gap to known and a study-clustered interval, and the class is a driver in the regression below. New report section "Novelty against PLSDB". Novel means no substantial relative in the PLSDB release used; the release provenance is shown. `database_containment.containment` gained an alignment preset argument.
- **Performance drivers** (`python/performance_drivers.py`, `plasbench analysis performance-drivers`; stage 6, `RUN_PERFORMANCE_DRIVERS`): one model per tool of per-plasmid recovery on plasmid size, repeat content, replicon family, resistance genes, species, read depth, recent/older arm and PLSDB novelty, with cluster-robust intervals (studies as clusters, t on studies - 1 degrees of freedom), a status that survives a correction for the number of terms, each driver's share of the explained variance, and "not estimable" with the reason for a tool with fewer than 30 plasmids or 5 studies. New report section "Performance drivers". Associations, not causes.
- **Plasmid-free negative controls** (`cohorts/negative-controls-v1.tsv` + lock, `python/discover_plasmid_free.py`): 136 RefSeq complete genomes with a single replicon, a long-read truth and a paired Illumina run, 12 species, 88 BioProjects, verified online. `validate-cohort` accepts a row marked `control_type=plasmid_free` only when its assembly declares no plasmid replicon. A single-replicon assembly shows the submitter deposited no plasmid, not that the strain has none; stated on every row.

### Added -- PlasmidEC as a benchmarked tool
- `plasmidec` (opt-in: `RUN_PLASMIDEC=1`, `plasbench run --plasmidec on`): the majority-vote ensemble of RFPlasmid, PlaScope and Platon (Paganini et al.; Teixeira et al. 2025 found it among the strongest detectors). `adapters/adapt_plasmidec.sh` takes its own `plasmid_contigs.fasta` as the hard call and fails, instead of reporting an empty prediction, when `ensemble_output.csv` is missing; `run_plasmidec()` maps each organism to its eight supported species and skips any other with a recorded reason. Registered in the capability, installer and database-release tables; tested on stand-in output and a stand-in launcher (the real tool was not run). Its published Teixeira outcomes now have a PlasBench counterpart in `compare-published`.
### Changed -- production readiness
- Fixed the scheduled **Real tools** workflow, whose Platon and plasmidSPAdes jobs failed on the fixture, not on the tools: Platon cannot train its gene finder on a 4 kb plasmid (`ORF prediction failed!`), so the check passes `--meta`; wgsim writes one constant quality character, from which SPAdes cannot infer the PHRED offset (`Failed to determine offset!`), so the workflow gives the simulated reads varied qualities. The production commands in `scripts/04_run_tools.sh` are unchanged. Whether the two now pass is confirmed by a manual run of the workflow (see the pull request).
- CI now runs the whole test suite on Python 3.9, 3.11 and 3.13 (`requires-python` is `>=3.9`; only 3.11 was tested). The first 3.9 run found a real bug: `Path.write_text(..., newline=)` exists only from Python 3.10, so saving settings or a tool from the window, writing a sample sheet, and the pre-registration editor all failed on 3.9; 13 calls now use `open(..., newline=)`. The test job is pinned to `ubuntu-24.04` because `ubuntu-latest` (26.04) has no Python 3.9 build.
- Added `SECURITY.md` (private reporting, supported versions, what is in scope) and `.github/dependabot.yml` (weekly GitHub Actions and monthly Docker base-image updates, each as a CI-tested pull request).
### Added -- fixes from the independent verification
- **The real-data run is in the repository**: `benchmark.report_cohort1` is renamed `results_real_cohort1` (10 isolates, PlasBench 0.2.3, three real tools) with a README saying what it supports and what it does not. The verification document had wrongly said no real-data result existed.
- **Binning: unaligned sequence is now counted beside the headline.** `score_bins.py --pred-fasta` writes `bin_unaligned_bp`, `bin_unaligned_fraction`, `lw_bin_precision_strict` and `lw_bin_f1_strict`; the leaderboard gains `mean_lw_bin_f1_strict` and `mean_bin_unaligned_fraction`. A bin padded with contigs that align nowhere scored a perfect headline; it now shows a low strict score. The headline definition is unchanged.
- **The run tables are checked before ranking** (`python/run_consistency.py`): duplicate runs, completed runs with no score and no recorded failure, scores with no status (errors); samples outside the sheet (a warning). Aggregation stops with a message unless `ALLOW_INCONSISTENT_RUNS=1`, and then the report carries a banner. A malformed or truncated `scores.tsv` stops with the file, line and value instead of a traceback.
- **Synthetic data stays out of real reports** (`python/data_nature.py`): a run that mixes `sample_origin = synthetic` samples with real ones is refused by aggregation and by the report builder; an all-synthetic report carries a "Demonstration data" banner.
- The weekly real-tool check now fails a tool that calls nothing as plasmid; `test_reference_groups.py` is registered; six optional demo analyses no longer end in `|| true`; the Galaxy wrapper pin follows `pyproject.toml` with a drift test.

### Added -- independent verification of the earlier audits
- `docs/INDEPENDENT_VERIFICATION.md` challenges the first audit, the second-review response and the performance audit on `main` at `17c9936`, classifying each finding and recording what was run versus read. New findings: bins padded with sequence that aligns nowhere keep a perfect binning score (verified with seven constructed cases); the report accepts missing, stale or duplicate runs without an error; the weekly real-tool check has a pass floor of 0; one test is registered nowhere. Intervals under-cover a nominal 95% (81-94% in simulation). Verdict: ready for a pilot and external review, not yet citable as evidence that one tool beats another.
- Fixed: the documented command `plasbench plaseval-replication` does not exist; it is `plasbench analysis plaseval-replication` (README-level docs, FAQ, replication guide).


### Changed -- the real-tool check uses real reads for plasmidSPAdes and measures recovery
- plasmidSPAdes is now checked on **real reads** of a known isolate (SRR11905452, *E. coli* EcPF14, first 600,000 pairs; the plasmid is NZ_CP054231.1, 7,154 bp; `cohorts/public-v1.tsv` `upec_ecpf14`), because it picks plasmids by copy number against a chromosome and called nothing on synthetic or lone-plasmid reads. MOB-suite and Platon keep the pBR322 fixture.
- New measure **`plasmid_recovered`**: the fraction of the plasmid's 31-mers (either strand) found in what the tool called plasmid. The existing share compares sizes only. It exposed that plasmidSPAdes, which called 50 kb (share 7.0), returned **0.099** of the real plasmid; MOB-suite and Platon return 1.0. A tool recovering none of the plasmid fails; `expected.tsv` has a `min_recovered` column (mob_recon 0.9, platon 0.9, plasmidspades 0.05, set from the 2026-11-17 run as a regression guard, not as a standard of performance).
- The summary table gains `plasmid_recovered` and `expected_min_recovered` (appended).
### Added -- the verification items that were left open
- **Independent-truth runs:** `plasbench run --independent-truth-only` runs only the isolates whose truth is independent of the benchmark's reads (1,099 of the 7,227 in `public-v4`); with `--max-isolates N` the N is a balanced selection of those. The cohort file and its lock are unchanged.
- **Negative controls:** `plasbench discover-cohort --negative-controls` (and `discover_ncbi_cohort.py --negative-controls`) looks for complete genomes whose record declares no plasmid, paired with an Illumina run, as candidates for plasmid-free isolates. None has been added to a cohort yet: the live discovery and a curator's check are still to do.
- **Intervals:** `resampling.stratified_bootstrap_t_ci` gives the studentised cluster bootstrap a species-stratified form (it used to fall back to `cluster_t` whenever the ranking was species-balanced), and the full simulation now measures it. The default method is unchanged (see `docs/STATS_VALIDATION.md`).
- **Curation grade:** the report's cohort filter is now labelled *Curation grade* (with an explanation), and the README says what `truth_quality_tier` means and what it does and does not do.


### Added -- publication cohorts and comparison with a paper's outcomes
- `cohorts/pub-plsmd-novel.tsv` (68), `pub-plsmd-filtered.tsv` (63), `pub-mobsuite.tsv` (95), `pub-teixeira2025.tsv` (5) and the mixed `publication-v1.tsv` (168 isolates, each once): the isolates of the published benchmarks (plsMD 2026, MOB-suite 2018, Teixeira 2025), each verified by `validate-cohort --online` and locked, tier B, with `truth_match` (the assembly's plasmids against the plasmids the paper used: 291 of 294 rows exact), `paper_run_used` and `published_studies`. Every one of the 531 candidates is accounted for in `cohorts/candidates/publication_cohort_audit.tsv`; 245 of Teixeira's 250 need a rebuilt hybrid truth (list shipped), the others lack a deposited complete assembly or a recorded long-read platform.
- `plasbench build-publication-cohorts` (`python/build_publication_cohorts.py`): builds them from the candidate ledgers, `public-v4` and NCBI resolution, checking the truth plasmids by accession and taking the nucleotide records, assembly method and sequencing platform from NCBI.
- `cohorts/published/`: the papers' own outcomes in long format with a metadata file each (source URL, SHA-256, definitions, metric map, caveats): plsMD's per-plasmid recall for plsMD, MOB-suite and gplas (copied; the filtered set's mean plsMD recall is 93.07 percent, as the paper reports) and Teixeira's published contig calls for 13 tools, from which per-isolate precision, recall and F1 are computed and labelled as computed. `plasbench analysis build-published-outcomes` rebuilds them.
- `plasbench compare-published` (`python/compare_published.py`; stage 6 runs it when the sample sheet holds published isolates, `RUN_PUBLISHED_COMPARISON`): PlasBench's results beside the paper's, matched by BioSample (accessions compared without version or RefSeq prefix), studies never pooled, a published value PlasBench could not match counted as "published only", never zero. Per tool: pairs, published and PlasBench means, difference, correlation, share within tolerance and a verdict; per study, the agreement of the tool order. The report gets a "Comparison with published outcomes" section and the window's cohort details show how each publication cohort was built and the command to compare. See `docs/PUBLICATION_COMPARISON.md`.

### Fixed
- `validate-cohort --online` rejected a run whose SRA experiment holds several runs ("could not retrieve run-info row"); it now takes the requested run's row. Some candidates left out of `public-v4` as failed lookups may be affected: re-run `resolve-contributed-cohort`.

### Added -- run only the first N isolates, and the cohort Selection report
- `plasbench run --max-isolates N` (any N; *How many isolates* in New benchmark) runs a balanced N isolates of a cohort or sample sheet: species take turns, recent and older alternate, long-read-first truths first, one isolate per study before a second (`plasbench_common.balanced_order`); `--isolate-order file` takes the first N rows instead. The cohort file is untouched and a copy with the chosen rows is used (`plasbench/sheet_limit.py`). `public-v4` is written in this order (`balance_rank`).
- The window's **Cohorts** page has a **Selection report** pop-up for a cohort built from the candidate pool: where the genomes came from, the criteria, available / passed / selected, why the others failed, a per-species table and the sequence information of the selected genomes. It reads `cohorts/<name>.selection.json`, written by `plasbench selection-report` (`python/build_selection_report.py`) from the importer's and resolver's output.

### Added -- public-v4 and the read-QC pre-check (contributed pool, verified at NCBI)
- `cohorts/public-v4.tsv` (+ lock, selection report, per-candidate audit): every genome of the contributed pool that verified at NCBI, 7,227 isolates of 943 species from 1,818 BioProjects, all tier B, all re-verified by `validate-cohort --online`. 1,539 recent (public from 2025-01-01) and 5,688 older; 3,552 long-read-first, 2,522 short-read-first, 1,153 unclassified truths; 98 are the first balanced selection (`panel_subset=core`). Written in balanced order, so `plasbench run --max-isolates N` runs a fair miniature. About 5 TB of reads for the whole panel; no tool has been run on it. The design is recorded in `docs/COHORTS.md` and `cohorts/README.md`. The accession ledger now covers it.
- `plasbench resolve-contributed-cohort` (`python/resolve_contributed_cohort.py`): verifies candidates at NCBI, replaces the pool's umbrella BioProject with the real one, picks the best SRA run, and runs the pre-download read-QC check (depth, read pairs, read length from SRA run-info, graded against `config/short_read_qc_thresholds.tsv`). It cannot see base quality or pair integrity: stage 3's `short_read_qc.py` still decides on the downloaded reads.
- `plasbench import-contributed-cohort --arm` labels a selection so two runs can be combined; `validate_cohort.run_metadata` also returns `spots` and `avg_length`.

### Added -- literature and public-data review: AMR regions, synteny ribbons, publication cohorts (16 November 2026)
- `python/report_amr_regions.py`: interactive AMR regions view (truth resistance regions with mobile context, a lane per tool with per-gene placement and flank coverage, a verdict per region, a funnel of where resistance information is lost); report section *AMR regions*.
- `python/report_synteny.py`: interactive synteny ribbons (order and orientation of each tool's records on a truth plasmid, identity shading, strand and identity filters, details panel); report section *Synteny ribbons*.
- Candidate cohorts adopted from publications: plsMD filtered (80 isolates, 244 plasmids), plsMD novel (68, 269), MOB-suite benchmark (133, 377), with supplement tables, ENA run metadata and a Teixeira ground-truth summary (`cohorts/candidates/PUBLICATION_COHORTS.md`, `python/build_publication_cohort_candidates.py`). Candidates only: assemblies are not resolved.
- FAQ Q43, external review log entry R10. Phylogeny, clustering and relatedness figures were not adopted (outside the benchmark).

### Added -- your own isolates: a template, a folder scan, a quick test, and a plain way out of every error
- **`plasbench intake`** (`python/intake.py`) and a rebuilt **Your own isolates** page. `template local|cohort|truth` writes a sheet to fill in with the rules written at the top (downloadable in the window); `scan FOLDER...` finds isolates under the folders you name (read pairs by `_1/_2`, `_R1/_R2`, Illumina lane names; lanes joined; the isolate named from the file or the folder), matches each reference FASTA to its isolate by name or folder **with a stated confidence**, and gives one FASTA to several isolates to none; `stage` places the files with the same code as `init-local` (now one shared function), compresses uncompressed reads, joins lanes, writes the sheet with a guessed organism and `NA` for reads-only isolates; `check` is the quick test.
- **The quick test** opens every file the way a run will: FASTQ validity, mates in step, short-read length, reference readable / DNA / unique names / not a draft, truth table against the reference, and **reads versus reference by 21-mer containment**, which catches a reference from a different strain or species that no file name or format check can see (80% or more passes, 30-80% warns, less fails).
- **Every error has a code, plain steps and a guide section** (`docs/INPUT_GUIDE.md`, one section per code; a test keeps the codes and the guide in step). **`check --fix`** (the window's *Fix what can be fixed*) repairs what has one right answer: a `.gz` that is plain text, differently named read files (copies; originals kept), a missing truth table (drafted), wrong capitals / stray spaces / Windows line endings in a truth table, missing reference sequences (added as `REVIEW`), the template's example row. It never decides plasmid or chromosome. **Label sequences** in the window is the one decision left to the person.
- Fixed: an empty `assembly_accession` (the documented reads-only row) shifted the read prefix into the accession column in every stage, because bash `read` collapses empty tab fields; `read_samples` now yields `NA`, which the stages already treat as "no reference", and the README example uses `NA`.
- Tests: `test/test_intake.py` (templates, scan layouts, staging, the wrong-organism reference, every repair, guide coverage) and `test/test_intake_ui_browser.py` (a real Chrome through the whole page; `PLASBENCH_BROWSER_TESTS=1`).

### Added -- 215-question reviewer assessment: ranking stability, assembler sensitivity, reference evidence audit (16 November 2026)
- `python/ranking_stability.py` (stage 6, `RUN_RANKING_STABILITY`): leave-one-study-out, leave-one-species-out and equal-study-weighted rankings, the largest study's share, Kendall tau and a verdict; `benchmark.study_sensitivity.tsv`, `.species_sensitivity.tsv`, `.ranking_stability.tsv`; report section *Ranking stability*.
- `python/assembler_sensitivity.py`: re-ranks the tools across runs that differ only in the assembly and says whether the leader depends on it; optional standalone HTML.
- `python/reference_evidence_audit.py` (stage 6, `RUN_REFERENCE_EVIDENCE_AUDIT`): one row per isolate with tier, independence, evidence recorded, flags and a strong / usable with caveats / weak status with reasons; report section *Reference evidence*.
- `docs/REVIEWER_ASSESSMENT_MATRIX.md` and `.tsv`: all 215 questions with component, status, evidence and what is still needed (a self-assessment, not independent review); FAQ section K (Q36 to Q42); external review log entry R9.
- Descriptive only: none of these change a score or a ranking.
- `docs/IMPLEMENTATION_CATALOGUE.md`: one document listing everything PlasBench implements (22 capabilities with what, why, files, settings, outputs, report sections, tests and limits; the pipeline stages; every tool, module, registered output, run switch and merged change; what is not implemented). Sections 5 to 9 are generated by `python/build_implementation_catalogue.py` and checked by `test/test_implementation_catalogue.py`.

### Changed -- the pre-registered scoring decisions are confirmed, recorded, and changeable in a controlled way
- The project owner confirmed all 29 `proposed` pre-registered decisions as proposed (16 November 2026): the task endpoints, `headline_independence`, `headline_min_clusters`, `interval_method`, `dominant_study_share`, `tool_timeout_seconds`, the truth-audit sizes, the scorecard weights and bands, `map_max_bp` and `amr_flank_bp`. None is `proposed` or `TO_FIX` now; the plan is no longer a draft.
- **The tool time limit is no limit, by decision.** `tool_timeout_seconds = 7200` (two hours) was proposed and confirmed with the rest, and the check that compares every decision with the program's default showed the program still ran with no limit. The project owner then decided that two hours is not realistic: the limit applies per tool per isolate, slow tools and large isolates take many hours, a pipeline with many tools and inputs can run for days, and a timeout scores the tool zero, which biases the ranking. The decision was changed to no limit through the new change flow (`unset` in `prereg.tsv`, blank in `TOOL_TIMEOUT_SECONDS`; both are in `config/prereg_decisions.tsv`). Set a generous limit only to stop a truly stuck run. A new test compares every decision that is a setting with its program default so a decision and the program cannot drift apart.
- **A decision record**: `config/prereg_decisions.tsv` (date, parameter, confirmed or changed, old and new value, who, why), seeded with the 29 confirmations. **Plain-language text** for every decision: `config/prereg_plain.tsv` (what it decides, what changes if it is changed, what kind of value it takes).
- **A way to change a decision**: `plasbench analysis prereg list | show | history | confirm | set | lock | check | doc` (`python/prereg_admin.py`), and a **Scoring decisions** page in the window (search, topics, status, every decision in plain words, **Change** with a required reason and name, the decision record, **Lock the decisions**, and a flag when a setting on this computer departs from the decision). A change edits exactly one row of `prereg.tsv`, records itself, sets this computer's setting, warns that earlier and later results are not comparable, and makes the lock stale. A decision built into the scoring code, or a scorecard table, cannot be changed from here: the page says why.
- `docs/PREREGISTRATION.md` is rewritten as a plain-language guide (what it is, what was decided, how to look, how to change, the lock, questions); its table of all decisions is generated from the data and tested. Tests: `test_prereg_admin.py`.

### Added -- a configurable leakage screen
- `LEAKAGE_CUTOFF_POLICY` (`per_tool` default, or `fixed_date` with `LEAKAGE_CUTOFF_DATE`) and `LEAKAGE_DATE_BASIS` (`earliest_public` default, `assembly`, `read`) in `config/config.sh`, so they appear in `plasbench ui` Settings; `python/flag_database_overlap.py` and stage 6 use them, `benchmark.database_overlap.tsv` gains `date_basis` and `cutoff_policy` columns, the manifest records them, and the report states the policy above the overlap counts. Defaults reproduce the earlier behaviour for sheets without `first_read_year`.


### Fixed -- the window disconnecting at random, and the icon that did nothing
- **Random "PlasBench disconnected".** The window's server listened with the standard backlog of 5, and the page opens many connections at once; on Windows a connection that finds the backlog full is refused outright, which the page took for a dead server (measured: 39 of 1,800 concurrent requests refused). The server now listens with a backlog of 256, speaks HTTP/1.1 keep-alive (one connection carries many requests), ignores clients that vanish mid-request, closes a refused POST's connection so an unread body cannot corrupt the next request, survives an error in its accept loop, and answers a repeated POST with the first run's response (`X-PlasBench-Req`), so a retried "start the benchmark" can never start it twice. The page retries a network failure quietly with backoff before it says anything, stands its pollers down while the connection is down, and reconnects by itself (probes grow from 2 s to 10 s, and run at once on wake, network return and tab focus).
- **The Retry button works.** It used to reload the page, which does nothing useful when the server is down. It now runs a real check (is the server answering? is this window's key still valid?), says honestly what it found ("Still not reachable, attempt 3, trying again in 5 s"), reconnects without a reload when PlasBench is back, and when PlasBench was restarted (new key) says the window must be reopened instead of pretending a retry can help.
- **The icon that did nothing, however often it was clicked.** The window is a Chrome or Edge window with a PlasBench-only profile; a stale lock in that profile (a browser that crashed, or a process id that was reused) makes the browser hand the URL to a browser that is not there and exit silently, and PlasBench never checked that a window appeared. Now stale profile locks are cleared first; the launch is verified (the server records when a window last loaded the page, shown in `/healthz`); a launch that produced no window is retried with a fresh profile and then in the default browser, without a second click, and if nothing works the message says so and gives the address. A server record left by a crash is recognised as stale (nothing answers, or a different server answers), two quick clicks start one server, and the launcher script reports a failed start with a notification and the log path instead of vanishing.
- **"This address needs the session key".** Three causes, three fixes. (1) The key cookie was shared by every PlasBench port on 127.0.0.1, so two PlasBench servers (or a stale one) overwrote each other's key and a reload of the other failed: the cookie is now named for the port and kept for 30 days, so a restarted browser keeps its key while the server runs. (2) A reload of the same tab lost the key even though the tab still held it in its own session storage: the explanation page now uses that once and reopens the window (the key is never in the page itself, and a stale key cannot loop). (3) The page was a dead end: it now says plainly what happened and the three ways back in (click the icon again, `plasbench ui`, the printed link). The key rule is unchanged: another program or user on the machine still cannot open PlasBench from the bare address.
- **Closing the terminal no longer stops PlasBench.** `plasbench ui` ignores SIGHUP (Quit in the window and Ctrl+C still stop it), so a closed terminal can no longer take the server, and with it the window, away.
- Tests: `test_ui_connection.py` (real server: burst, keep-alive, request replay, aborted clients), `test_app_launch.py` (stale locks, the verified ladder, stale records, the launch lock), and `test_ui_connection_browser.py` (a real browser with the network cut; `PLASBENCH_BROWSER_TESTS=1`).

### Added -- the contributed RefSeq/SRA candidate pool and a seeded, cluster-aware importer
- `cohorts/candidates/contributed-refseq-sra/`: 8,812 RefSeq Complete Genome / SRA pairs (and their 24,606 plasmids) from a collaborator, stored gzipped with SHA-256 pins and a `SOURCE.md` that lists what it does and does not establish.
- `plasbench import-contributed-cohort` (`python/import_contributed_cohort.py`): long-read-first, one isolate per read-BioProject cluster (the pool's `bioproject` column is the RefSeq umbrella on every row), seeded and order-independent, with a reason for every rejected row, `--released-after/--released-before` and a `--date-basis` (`assembly`, `read`, `earliest_public`). Output is unverified until `validate-cohort --online`.
- `plasbench_common.leakage_release_date` / `parse_iso_date`: the one definition of "when did this genome become public", for the importer and, next, the leakage screen.

### Added -- PlasEval cohort result, confirmable by any user (16 November 2026)
- The 53-isolate comparison with the original PlasEval program finished: 211 of 212 pairs compared, 210 agree within 0.001, 0 disagree, 1 capped-search upper bound (0.003), 1 original timeout. The original's answers are kept in `cohorts/plaseval_ecoli53/original_reference.tsv`; `python/plaseval_replication.py` compares with them when no PlasEval checkout is installed and says so on the page, so any user who re-runs the cohort can confirm the result in the HTML. Finished page: `cohorts/plaseval_ecoli53/replication_report.html`.

### Added -- reviewer questions: short-read QC gate, assembly selection policy, candidate multiplicity (16 November 2026)
- **Short-read QC gate** (`python/short_read_qc.py`, stage 3, `config/short_read_qc_thresholds.tsv`): measures each raw read pair before assembly (integrity, read pairs, depth, quality, read length, GC, N, adapters, duplicates, pair synchrony) and decides PASS, WARN or REJECT with the reason. `SHORT_READ_QC_MODE`: `report` (default) flags and excludes only an integrity failure, `enforce` also excludes a threshold REJECT (status `rejected`, not assembled, tools skipped as "short-read QC rejected", never scored as a tool failure), `off`. Thresholds are provisional until frozen on pilot data; their hash is written to every QC row. Outputs `short_read_qc.tsv` and `short_read_qc_status.tsv`.
- **Assembly selection** (`python/assembly_selection.py`, stage 3): every candidate assembly is measured (contigs, N50, L50, length, GC, optional read support via minimap2) and kept in `assembly_candidates.tsv`; a declared policy (`ASSEMBLY_SELECTION_POLICY`: `fixed` or `quality`) chooses from assembly-side evidence only, never the truth or a score; nothing is substituted silently when no candidate is eligible. `ASSEMBLY_SELECTION_MODE` `report` (default) / `enforce` / `off`; `ASSEMBLY_ALSO` runs alternative assemblers.
- **Candidate multiplicity** (`python/candidate_multiplicity.py`, stages 5 and 6): every predicted record is accounted for; per truth plasmid the best-candidate coverage, the combined (union) coverage and the redundancy; per candidate primary, complementary fragment, redundant, chimeric, off-target or unmapped. Descriptive: it never changes a score. Tables `benchmark.candidate_multiplicity.tsv`, `benchmark.candidates.tsv`, `benchmark.candidate_intervals.tsv`.
- **Three report dashboards** (`python/report_reviewers.py`): a MultiQC-style read-QC table with a cohort summary, a QUAST-style assembly comparison (worst to best per row, selected assembly marked) and Alvis-style candidate tracks with a coverage strip.
- `docs/EXTERNAL_REVIEW_LOG.md`: every review received, what was asked, how it was answered and what validated it, with human reviewers, AI-assisted reviews and automated validation kept apart; `test/test_external_review_log.py` keeps its references real. FAQ section J (Q32 to Q35).
- Provisional and open: the QC, size, read-support and candidate limits must be frozen before the main benchmark; running every tool on every alternative assembly, taxonomic contamination screening and a real-cohort run of the multiplicity analysis are not done.

### Added -- the PlasEval-paper cohort, binning error-profile charts, and a comparison gate against the original program
- `cohorts/plaseval-ecoli53.tsv`: the 53 *E. coli* isolates of the PlasEval paper (accessions from its `Ecoli_samples.csv`), with the paper's published ground truth and tool bins (MOB-recon, HyAsP, gplas2, PlasBin-flow) in `cohorts/plaseval_ecoli53/bins` (CC BY 4.0, credited). Schema-validated; the online NCBI check has not been run. Reference tier 3 (Unicycler hybrid on the same reads): a replication panel, not a headline one.
- `plasbench analysis plaseval-replication` scores the paper's bins with PlasBench and writes tables and an HTML page; with the original program found it runs it on the same pairs. PlasBench alone, on the real bins: mean dissimilarity 0.253 (MOB-recon), 0.316 (gplas2), 0.370 (PlasBin-flow), 0.479 (HyAsP) at alpha 0.5. Not yet compared with the original on these bins.
- `python/report_fig_binerrors.py`, in the report's Bin agreement section: error profile by tool (extra, missing, over-merged, fragmented), tool-by-part grid, precision against recall per tool, F1 against agreement with the truth, error composition per isolate, isolate-by-tool grid, tool-agreement matrix, a length-exponent stability table, and a reading list computed from the data (which error dominates, tools with the same F1 but different errors, whether the order depends on the exponent, capped searches). Pure SVG, colour-blind-safe, descriptive only.
- `python/plaseval_gate.py` and `RUN_PLASEVAL_GATE` (`auto` by default, `on`, `off`): stage 6 runs the original PlasEval program on the bins stage 5 exported and compares dissimilarity and best-match precision, recall and F1. Verdicts PASS, FAIL, PARTIAL, NOT_RUN, NO_DATA in `benchmark.plaseval_gate.json` and the report; `on` stops the run when the original is missing or disagrees; a capped PlasBench search is an upper bound, never below the original. The original is found through `PLASEVAL_SRC` or `~/.local/share/plasbench/tools/PlasEval`; it is never bundled (no licence).
- The repeat-aware search is faster: costs are kept incrementally and the cheapest pairing is tried first. On the paper's real bins the search time fell from about 97 s to 35 s and the capped searches from four to two, with the 59-case agreement with the original unchanged.
- `docs/PLASEVAL_REPLICATION.md`: what ships, what has been measured, and the commands to run the comparison on a computer that can.

### Changed -- third review (registry, intervals, documentation)
- `tool_capabilities.derived_task()` is strict: a reassembler is never derived to be a classifier (the old fallback did that for a reassembler with `binning_capable=no`), contradictory rows are errors, and a derived task is reported on stderr. The shipped registry declares `evaluation_task` for every tool; `test_registry_tasks.py` pins it (plasmidSPAdes is `sequence_reassembly`).
- Percentile fallback for dominated cohorts: when one study holds more than 30% of the observations (`PLASBENCH_DOMINANT_SHARE`, `PLASBENCH_DOMINANT_FALLBACK`), the leaderboard and paired intervals use the percentile cluster bootstrap instead of cluster t. New leaderboard columns `max_cluster_share`, `dominant_study` (appended after `ci_method`; `ci_method` now records the method actually used); a Headline design table of study structure. A new full simulation (committed in `docs/stats_validation/`) measures the rule: dominant-study coverage rises from 64-79% to 87-91%; the statistics stay provisional.
- `PLASBENCH_CI_METHOD`, `PLASBENCH_DOMINANT_SHARE`, `PLASBENCH_DOMINANT_FALLBACK` and `HEADLINE_REFERENCE_INDEPENDENCE` are now recorded in the run manifest (the first and last were missing).
- Documentation: the Methods document no longer describes the retired track-specific CPRR endpoint or the three-class independence names; the guide lists `public-v3`; `test_docs_consistency.py` checks tasks, endpoints, independence classes, cohorts, the interval defaults and the proposed pre-registration rows against the code.
- AMR placement: a regression fixture shows that agreement of the replicon type does not make a placement correct.

### Added -- repeat-aware PlasEval dissimilarity, checked against the original program
- `bin_agreement.py` now pairs the copies of a contig that sits in several bins, as PlasEval does (a maximal matching per repeat family, the lowest total dissimilarity found by branch and bound; every copy counts in the normaliser). `--repeats drop` keeps the earlier first-copy behaviour; `DISSIMILARITY_REPEATS` and `DISSIMILARITY_MAX_CALLS` configure it. A search that reaches the cap keeps the best pairing found and is marked `capped` in the new `dissim_repeat_search` column; `dissim_repeat_families` counts the repeat families.
- `scores.tsv` also records the dissimilarity at length exponent 0 and 1 (`bin_dissimilarity_alpha0`, `bin_dissimilarity_alpha1`) beside the configured alpha (default 0.5), so a reader can see whether a verdict depends on how contig length is weighted.
- `test/test_plaseval_crosscheck.py` now compares the dissimilarity in every case, including hand-built and seeded random cases with repeated contigs. Run on Linux against `github.com/acme92/PlasEval` (commit 8238356) it agreed on all 59 cases, 44 with repeated contigs. It still only runs when `PLASEVAL_SRC` points at a PlasEval checkout.

### Added
- **Run sessions: a run is never lost, and you can see, resume and open every one.** Runs started from `plasbench ui` now run under a detached runner (`plasbench/jobrunner.py`) that keeps the run's pid, a heartbeat and its exit code beside its log, so a run survives the window closing, a lost connection, the terminal being closed or **Quit and keep running**, and a new window finds it again (before, every "running" job was relabelled "interrupted" on restart and could not be followed). *Runs & reports* gains **Run sessions**: Ongoing (stage, isolate and percentage progress parsed from the log, Follow progress, Cancel), Needs attention (failed, interrupted, cancelled: **Resume** re-runs the same command and reuses finished work), Completed (Open report, Run again), with details, a badge and a one-time notice for runs that stopped unseen, and `#runs/attention` deep links. A lost connection now shows a retrying banner instead of a dead end; the full-screen notice appears after 45 s and says runs are not lost. Quit asks whether to keep runs going or stop them. Answers to a run's question reach it from a new window. New API routes `run-sessions` and `jobs/<id>/resume`; `shutdown` takes `keep`. Tests: `test_job_survival.py`, `test_webui.py`.
- **A persistent "benchmarking is running" toast in the window.** Starting a benchmark (or the demo) from `plasbench ui` shows an animated toast (spinner, sweeping bar, live elapsed time) the moment the button is clicked. It lives in the page shell, so it stays while you move between pages, is restored when the window is reloaded, says "Cancelling…" during a cancel, goes away when the run ends (the done or failed message follows) and opens the console when clicked. Reduced-motion settings are respected.
- **Check for updates in the window** (Setup, Maintenance): asks GitHub whether a newer release exists, only when pressed, and offers a confirmed one-click upgrade. `plasbench --help` and the README upgrade section now also cover the offline `--archive` install, `plasbench ui --tab` and `plasbench desktop-icon`.

## [0.4.1] - 2026-11-16

A fixes-only release: first-run problems reported from two Windows/WSL machines. Scores and rankings are unchanged from v0.4.0.

### Fixed -- first install and first launch
- **The desktop icon did nothing.** The launcher ran with `set -u`, and conda's own activate scripts (gcc and others) read variables they never set, so the shell exited with `SYS_SYSROOT: unbound variable` before the window started. `set -u` is now relaxed only around activation (`scripts/plasbench_launcher.sh`), with a regression test that fails without the fix.
- **`plasbench install-tools all` failed on a small PC.** The Trycycler environment (Trycycler, Flye and Medaka's PyTorch stack) is a very large solve and was killed for memory (exit 137), which failed the whole install although every other tool had installed. The base profiles (core, assembly, mobsuite, reconstruction) are still required; any other tool that cannot install is listed with how to retry, and `all` exits 0. A kill explains how to give WSL more memory (`.wslconfig`), and a warning appears before the Trycycler solve when under about 8 GB is free.
- `env/install_tools.sh` was stored as non-executable in git although its `all` loop re-invokes it; a plain git checkout failed every profile with "Permission denied". It is now executable.
- **A failed download now says why.** `scripts/install_latest.sh` reports curl's status; for a DNS failure ("Could not resolve host", common in WSL2 and behind VPNs) it says the network is the problem and gives the fixes. The new `--archive FILE` option installs a release file already on disk with no network, checking the `.sha256` beside it. README troubleshooting has a row for it.

### Fixed -- the window and the browser
- The PlasBench window opens in its own browser profile with extensions, sync and notifications off, or in a private window when no separate profile can be made; it never uses the everyday profile (`plasbench/appwindow.py`). PlasBench's page loads nothing from the internet, so unrelated advertising pages that open alongside it come from the browser or the computer, not from PlasBench.
- The "session key" page now says the key is new at every start, so an old tab or bookmark stops working, and how to get the full link again.

### Changed -- sample-level data stays out of git
- A study repository's managed `.gitignore` now ignores per-sample sub-folders (`results/*/`), `data/`, `reads/`, `assembly/`, `predictions*/`, `metadata/`, `clinical/` and files named for patient, clinical or line-list data, and more sequence and variant formats. The commit scan blocks the same files if forced in and blocks more direct-identifier columns (patient id, medical record number, NHS number, ward, bed number). A study repository made with the older block is upgraded the next time the block is ensured. Files already committed stay tracked until `git rm --cached`.
- The program repository's own `.gitignore` keeps sample-level sequence, alignment and metadata files untracked.

### Added
- `docs/INDEPENDENT_REVIEW.md`: an independent scientific review of PlasBench with an evidence ledger checked by `test/test_independent_review_ledger.py`.
- The README links the step-by-step lab guide from the top and its section links are fixed.
- `test/test_install_wiring.py` fails when the code calls an external tool no install route declares; mash, samtools, barrnap and the annotation callers are now wired into `install-tools` profiles and the setup check.

## [0.4.0] - 2026-11-15

### Added -- complete statistics simulation study, results by number of studies
- `simulate_validation.py` now simulates dominant and heavy studies, within-study correlation, missing outputs, resource failures (per isolate and whole studies), a dominant species (stratified functions) and Holm over many comparisons; results are summarised by number of independent studies (`benchmark.stats_validation_by_studies.tsv`) with a status that stays provisional unless a full run supports it. `--workers` runs scenarios in parallel.
- Full run (86 rows, all three interval methods) committed in `docs/stats_validation/` and written up in `docs/STATS_VALIDATION.md`: tests and Holm are calibrated; cluster-t (the default) covers 94-96% with balanced or moderately unbalanced studies but only 64-79% with a dominant study or two heavy studies; the percentile bootstrap under-covers elsewhere. The statistics stay provisional.

### Changed -- reference independence is its own classification (review of the reference standard)
- `truth_provenance.py` records two separate things per reference: `reference_quality` (validated / partially validated / provisional, the tier) and `evaluation_independence` (independent / partially independent / dependent / unknown, with `independence_reason`). Appended columns; the tier stays.
- The primary analysis needs a reference that is within `HEADLINE_MAX_REFERENCE_TIER` AND independent (`HEADLINE_INDEPENDENCE`, default `independent`), from at least `HEADLINE_MIN_CLUSTERS` independent clusters counted over the qualifying references only. Dependent and unknown references never enter it. Before, a tier-2 reference polished with the benchmark's own reads counted as primary; it is now partially independent and a sensitivity analysis. The pre-registration row `headline_independence` is marked proposed.
- Sensitivity populations: sensitivity 1 adds partially independent references, sensitivity 2 is every reference (`independent_references_only` and `independent_or_partial_references` cohort variants in the rank-sensitivity table; `benchmark.reference_independence.tsv`; per-class table and the two columns in the report's Headline design tab). README and the Scientific guide state the full rule.

### Fixed -- AMR placement forced one record per plasmid on classifiers
- `score_amr_placement.py` matched every tool's records to plasmids one-to-one, so a classifier that reported two contigs of one plasmid had the second contig marked wrong. It now takes `--task` (the registry's `evaluation_task`; stage 5 and the demo pass it): binners stay one-to-one; classifiers and reassemblers attribute each record to the plasmid it overlaps most.
- AMR-PRR and the pairs-kept-together figure are blank for classifiers (no plasmid-level reconstruction claim); the report says "not applicable (classifier)" and explains the rule. New columns `evaluation_task` and `attribution` (appended). Regression test `test/test_amr_placement_by_task.py`: one plasmid, two resistance genes on two contigs.

### Fixed -- classification, binning and reassembly were conflated (review of the task logic)
- The task of a tool was decided by `binning_capable` alone, so every tool that was not binning-capable was a classifier even when it reassembles plasmid sequences (plasmidSPAdes, and the demo's `spades_like`), while Plassembler, Hybracter and plsmd, which also reassemble, shared one reconstruction track with the binners. `config/tool_capabilities.tsv` now has an explicit `evaluation_task` column (`classification`, `binning_reconstruction`, `sequence_reassembly`) and the ranking code reads it (`headline_design.Design`, `tool_capabilities.evaluation_task`); `binning_capable` only says whether the output is a set of per-plasmid units that the bin metrics can score (yes for binning and reassembly, no for classification) and the registry reader refuses a row where the two disagree. A registry without the column keeps its old answers, telling a reassembler from a binner.
- Each task has its own pre-registered primary endpoint on every input track: base F1 (classification), length-weighted binning F1 (binning reconstruction), isolate-level CPRR (sequence reassembly). The track-specific exception that sent long-read and hybrid binners to CPRR is gone. `config/prereg.tsv`: `primary_endpoint` revised and `primary_endpoint_long_read` replaced by `primary_endpoint_reassembly`, both marked *proposed* until you confirm them (they were *fixed*).
- plasmidSPAdes and the demo's reassembler are now bin-scored (each reassembled record is its own bin, as `adapt_plasmidspades.sh` writes it), so they get a CPRR; the leaderboard shows three task groups.
- Recommendations are made for one task: `select_operational_method.py --task` takes `binning_reconstruction` (the default, as before minus the reassemblers), `sequence_reassembly`, `classification`, `all`, or the old `reconstruction` (= binning).
- A user tool's manifest states `task = binning_reconstruction`, `sequence_reassembly` or `classification`; the old `task = reconstruction` still means binning. The setup window lists and filters the three tasks. Results written before the split (task `reconstruction`) still render, labelled as older. `test/test_evaluation_tasks.py` is new.

### Release summary

A feature release that also changes how tools are scored and ranked: **scores and rankings from v0.4.0 are not
directly comparable with v0.3.0 or earlier**. New: the correct plasmid reconstruction rate (CPRR) with SV-PRR and
AMR plasmid context, the burden of unverified predicted sequence, a metric registry and evaluation ladder, more truth
audits, a structured evidence record per reference, real-binary checks, database provenance and validation tiers,
new report figures, a three-way recommender comparison, study folders, and a window that reuses what is already
installed. Changed: permutation tests need six independent units, the primary analysis is reported unavailable
instead of silently falling back, the recommendation model uses truth-free features only, and (after the second
external review) tools are ranked in the task their output declares, references polished with the benchmark's own
reads leave the primary analysis, intervals use a cluster-robust t method chosen by simulation, and AMR placement no
longer penalises tools that do not bin. See the [release notes](docs/releases/v0.4.0.md) and
[docs/reviews/SECOND_REVIEW_RESPONSE.md](docs/reviews/SECOND_REVIEW_RESPONSE.md). Compare: [v0.3.0...v0.4.0](https://github.com/ubeffiong/plasbench/compare/v0.3.0...v0.4.0).

### Changed -- the second external review (P0 and P1)
- **Evaluation task per tool.** `config/tool_capabilities.tsv` declares `evaluation_task` (`binning_reconstruction`, `sequence_reassembly`, `classification`) and `output_unit` from each tool's output contract. A tool without bins was ranked as a contig classifier, so plasmidSPAdes shared a leaderboard with Platon; it now has a reassembly track ranked by base-level sequence-recovery F1. User manifests accept `task = reassembly`; an older registry falls back to `binning_capable`. Each metric in `config/metrics.tsv` lists the tasks it can score. Leaderboards say what their ranking metric measures (binning F1 is grouping, not complete reconstruction).
- **Reference independence beside reference quality.** `truth_provenance.py` writes `reference_independence` and `reference_group`. By default (`HEADLINE_REFERENCE_INDEPENDENCE=independent`, pre-registered as proposed) a tier 2 reference polished with the benchmark's own reads is a dependent reference: it leaves the primary analysis and appears in the new `benchmark.reference_independence.tsv` (mean, rank and their change from the independent group), shown in the report. The headline design records the composition. `any` restores the tier-only rule.
- **Intervals chosen by simulation.** The percentile cluster bootstrap under-covers with few studies. `resampling.py` adds a cluster-robust t interval (CR1, t on G−1 df, stratified form) and a studentized cluster bootstrap; `simulate_validation.py` measures all three, plus stratified scenarios and the Holm family-wise error. The leaderboard and comparison intervals use `PLASBENCH_CI_METHOD` (default `cluster_t`), recorded in every output.
- **Effect before significance.** Paired comparisons gain `effect_status` and `testable`; equivalence needs an interval (`not_assessed` without one), so a small difference with no interval is no longer called equal performance.
- **AMR placement for tools that do not bin** is contig attribution: several records may come from one plasmid, so one-to-one matching no longer penalises a classifier. It is sequence attribution, not reconstruction; AMR-PRR and pairs kept together stay unavailable for such tools.
- **Recommender validation.** Isolate, study, clonal-group, study-and-clonal and species holdouts (`benchmark.recommender_holdouts.tsv`); two taxonomy-aware nearest-neighbour arms; robust scaling, a missingness penalty, abstention outside the training range, per-recommendation uncertainty (`benchmark.recommender_knn.tsv`), sensitivity to K, scaling and each feature, and feature correlation. An arm is enabled only when it adds value under the strictest holdout. The ridge model needs that evidence and calibrated out-of-study intervals before it is activated.
- **Pre-registration, scorecard, documents.** A new `unavailable` status resolves the A4/C2 bands (no truth variant set; nothing invented); nothing is `TO_FIX`. The scorecard orders tools on the metrics every tool has. The Scientific Guide names 0.4.0 (`test_doc_versions.py` keeps versions in step); the first independent review is labelled historical.

### Changed -- the window shows and reuses what is already installed
- Database paths in the New benchmark wizard and the command forms are an optional fold, *Use a different database
  copy*, closed unless one is filled in. Each field shows whether the database is installed and where; an empty
  field uses the installed copy, resolved like `config/config.sh` does: an explicit setting, then the machine-wide
  store (`PLASBENCH_DB_DIR`, default `~/.plasbench/databases`), then a copy under `DATA_DIR/db`. Databases are
  downloaded once per computer and reused by every benchmark.
- Settings shows what a shell-code default means on this computer (the resolved path, with *Installed* or *Not
  installed yet*), and the data, results and log folder fields say what leaving them empty does.
  `test/test_webui_databases.py` covers it.

### Fixed -- smaller findings of the end-to-end review
- The ranked CPRR registry row pointed at the pooled rate (`cprr`); the ranking metric is the per-isolate CPRR, so it now points at `cprr_isolate_mean`. `test_metric_registry.py` now cross-checks the registry against the scorecard for source and column (it checked only the id sets), so the two cannot drift apart.
- `test_tool_validation_tiers.py` accepted any record file containing the tool's name and the text 'pass' (so 'bypass' counted); it now needs a row for the tool whose status is exactly `pass`. The real-binary checker catches a tool timeout and still writes its summary row. `database_registry` in the manifest survives a malformed registry row. The documentation says that 'recorded' means recorded in the registry, not that this run used that database.
- The recommendation evidence panel said 'Expected performance' for the cohort's in-sample mean F1 and did not say that the recommender evaluation had found no gain from recommending per isolate; it now says 'Observed performance (this cohort)' and names the verdict.
- The radar and the complexity figure repeated colours after eight tools; the ninth and later tools now differ by line dash or marker shape. The maps' legends say what they leave out (genes across the origin, identity from the 300 longest blocks in the viewer). `plasbench analysis` lists `characterise-dataset`, `truth-marker-overlap` and `database-provenance`, which could not be re-run standalone.
- The new settings are in the Scientific guide's settings tables and the README (they were in prose only).

### Fixed -- AMR context follows CPRR's identity rule and never mistakes a draft for curated truth (end-to-end review)
- AMR-PRR used the CPRR table's identity-inclusive verdict for every isolate; on isolates whose truth was polished with the benchmark's own reads it now uses the verdict without the identity criterion, like CPRR (`collect --truth-provenance`, new gene-copy column `plasmid_cprr_correct_no_identity`).
- The scorer read `truth_amr.tsv` by filename only, so `cp truth_amr.draft.tsv truth_amr.tsv` made auto-derived rows count as curated despite the promotion gate. Each gene copy now carries its `truth_evidence_tier`, a warning is printed, the summary counts `draft_truth_copies`, and the report shows an *Uncurated truth* caution above the AMR table. The report text no longer hard-codes '1 kb' for the flank: it names `AMR_FLANK_BP`.

### Fixed -- the burden columns (end-to-end review)
- `ambiguously_mapped_pred_bp` was written as 0 when the ambiguity alignment was not made (`REPORT_MAPPING_AMBIGUITY=0`, or the secondary alignment failed), so the leaderboard showed 0.0% 'multi-mapped' for bases nobody checked. It is now blank (an empty alignment file is still a real 0), so the leaderboard shows blank, the perfect-recovery label stays 'not assessed' instead of being awarded, and the drill-down treats a blank as 0 only for its sums.
- The metric was described as bases 'with an alternative placement' in the registry, glossary, heatmap and report, but it counts mapped bases that align to BOTH a plasmid and a chromosome; the report header also used predicted bases as its denominator while the code divides by mapped bases. All texts now say what is counted (the heatmap column is *Plasmid+chromosome share*), and the burden shares need all three parts (mapped, unmapped, off-truth) or are blank instead of silently shrinking the denominator.

### Fixed -- SV-PRR now follows CPRR's identity rule (end-to-end review)
- SV-PRR used the CPRR table's `correct` (identity criterion included) for every isolate, while the leaderboard's CPRR drops the identity criterion on isolates whose truth was polished with the benchmark's own reads; on those isolates SV-PRR fell below CPRR for a reason that had nothing to do with structure, and the two were printed side by side. The structural step now writes `sv_prr_correct_without_identity` too, and the aggregation chooses per isolate by the same rule as CPRR (`headline_design.cprr_counts`). Because structural calling can fail for an isolate that CPRR still includes, the leaderboard gains `sv_prr_isolates` and `cprr_on_sv_isolates` (CPRR over exactly the isolates SV-PRR covers), and the leaderboard line and the report cell print that comparison instead of an unmatched pair.

### Fixed -- the recommender comparison's verdict rule (end-to-end review)
- An arm 'added value' on any positive gain, however small, counting a study of one isolate like a study of fifty. It now needs a mean-regret drop of at least 0.01 (`MIN_IMPROVEMENT`), a majority of at least three studies that each have two or more held-out isolates, and, for the feature-conditioned arm, at least half of the held-out isolates actually placed by their neighbours (`MIN_FEATURE_SHARE`). With no dataset features at all the arm silently equalled the single best and read 'no better'; it is now 'not assessed' with the reason, and `recommender_arms.tsv` gains `n_feature_based` and `share_feature_based` (shown as *Placed by neighbours*). The arms table now has a Not-run state when the file is absent.

### Added -- the missing half of plan A9 (end-to-end review)
- Rank sensitivity gains the `audit_clean_only` cohort variant: the ranking with isolates the truth-label audit flagged anything in left out, using the same `audit_sample` function and size thresholds as the audit table (the plan asked for sensitivity with and without exclusion; only the audit existed). `multi_replicon_plasmid` is documented as the noisiest flag. A malformed `tool_database_pattern` in `config/truth_marker_databases.tsv` now stops with a message naming the marker instead of a traceback.

### Fixed -- rank sensitivity (end-to-end review)
- The scoring-setting sweeps re-score base-level F1, and the docstring called F1 the leaderboard's ranking; it now says what the sweeps cover (base level) and where the fragility of the reconstruction headline is read (`metric:lw_bin_f1`, `cprr@t`). The `cprr@t` rows were compared with a literal 0.95 and labelled pre-registered even when `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE` were set differently: the baseline is now the configured threshold, and no sweep is written when the configuration is not on the grid. A setting variant equal to the configured setting (`min_length=500` with `MIN_ALIGNMENT_LENGTH=500`) is skipped instead of repeating the baseline, and a baseline that silently fell back to another truth scheme now warns.

### Fixed -- the primary analysis and the settings behind it (end-to-end review)
- The primary analysis was 'available' with a single tier-1/2 isolate, which has no interval and no test. It now needs references from at least `HEADLINE_MIN_CLUSTERS` (default 5) independent clusters; below that it is unavailable with the reason named. `HEADLINE_MAX_REFERENCE_TIER`, `HEADLINE_MIN_CLUSTERS` and `ALLOW_PRIMARY_FALLBACK` now have pre-registration rows (they could be changed in the environment unnoticed) and are defined in `config/config.sh`.
- `run_manifest.json` now records `RUN_STATS_VALIDATION`, `STATS_VALIDATION_MODE`, `CHROMID_MIN_BP`, `LARGE_PLASMID_BP`, `AMR_FLANK_BP`, `RUN_RANK_SENSITIVITY`, `ALLOW_PRIMARY_FALLBACK` and `HEADLINE_MIN_CLUSTERS`, so a run that changed a headline, a flag or an AMR number can be reproduced from its manifest. `RUN_RANK_SENSITIVITY` was only defaulted inside a stage script, so the setup window and `local.env` could not show it; it is now in `config/config.sh`, with a comment for every new setting.

### Fixed -- statistics (end-to-end review)
- A NaN difference gave a permutation p-value of about 1e-4 (`abs(x) >= nan` is false for every permutation) while the table called it exact; a NaN now gives no p-value and no interval (`not_estimated`) in the paired, stratified, bootstrap and ratio-bootstrap functions, and `permutation_method` says `not_estimated` with it. The literal 5 minimums are now the named constants.
- `underpowered` could never fire (a floor of at least 0.03125 is never above 0.05) and ignored that significance is judged after Holm over all comparisons. It now uses the smallest Holm-adjusted p a comparison can reach, m times its floor, written as the new last column `holm_min_attainable_p` of `benchmark.paired_comparisons.tsv`; the report's note says it. Stale 'five units / five shared samples' texts now say six independent units for a test.

### Fixed -- the recommender's 'truth-free' assembly features came from the reference (end-to-end review)
- `assembly_stats.tsv` is measured on the REFERENCE (stage 2): its contig count is the number of replicons and its size includes the true plasmids, so GC, N50, contig count and size were truth-derived while documented as the isolate's own assembly. An operational isolate has no such file, so those features were imputed at prediction time. They are now measured on the isolate's own contigs (`data/<sample>/contigs.fasta`) and named `input_gc_percent`, `input_n50`, `input_contig_count`, `input_assembly_size_bp`; the reference-derived names are forbidden (`TRUTH_DERIVED_FIELDS`), so a model fitted on them is refused at load and must be refitted (`plasbench` says which feature). `recommendation_model.TRUTH_FREE_FEATURES` is now an allowlist that `fit_feature_spec` asserts, in addition to the forbidden list. `select_unknown_sample.py` gains `--assembly` (contigs FASTA). The dataset-characterisation table, the feature-conditioned arm and the complexity figure use the same truth-free columns, and a test checks that no truth-free column is read from a reference-derived file. `compute_assembly_stats.scan_fasta` counts bases with `str.count` (same numbers, several times faster).

### Changed -- integration audit (plan F)
- `test/test_integration_audit.py` checks, in one place, what the release added against what it must be wired to: every CLI command is in the setup window's categories and documented in the README; every config setting a pre-registration row names exists in `config/config.sh`; every figure has help text, a layout label and a place in the Figures order; every glossary term used by the registry exists; every new report feature is in the feature manifest; `plasbench ui` lists every command (it is generated from the parser).
- Gaps the audit found and this release fixes: `promote-amr-truth` was missing from the window's categories; `collect-truth-provenance`, `discover-design-cohort` and `candidate-dataset` were in no documentation; `AMR_FLANK_BP` had a pre-registration row but no `config/config.sh` setting; the new report features had no feature-manifest rows.

### Added -- real-binary checks, database provenance and tool validation tiers (plan E1-E3)
- **E1** `.github/workflows/real-tools.yml` (weekly and on request, never on a pull request) runs the REAL MOB-suite, Platon and plasmidSPAdes on a known plasmid and passes the output through the real adapters (`test/real_tools/check_real_tool.py`): exit codes, the adapter contract, contig naming (every predicted record and bin member must be a contig of the input, for tools whose output is a subset of it), the bins table, a missing database named before the tool runs, and a known-output floor (`test/real_tools/expected.tsv`, 0 = recorded, not yet enforced, until the first reviewed run). `test/test_real_tool_checks.py` tests all of it offline against stand-in output through the real adapters. Not run here: the real binaries; the first scheduled run will be their first test.
- **E2** `config/tool_database_releases.tsv` gains `database_version`, `source_url`, `database_checksum_sha256` (versions and sources only where the registry already named them; every checksum is blank until filled from a real download). `python/database_provenance.py` computes the provenance status (recorded, partly, unrecorded, not applicable), writes `benchmark.database_provenance.tsv` (stage 6), records the registries in `run_manifest.json` (`database_registry`) and prints a checksum of a database file or folder. The report shows *Tool and database provenance* in *Truth plasmids in tool databases*.
- **E3** `config/tool_capabilities.tsv` gains `validation_status` (real_binary_checked, adapter_tested, untested, not_applicable) and `validation_evidence`. `test/test_tool_validation_tiers.py` checks every claim against its evidence file and fails when a tool is added at the untested tier without being acknowledged, so no adapter ships unvalidated by accident (plassembler is the one acknowledged). The tier is shown beside the database in the report. `adapters/REGISTRY.md` documents the tiers and the interface a tool must meet.

### Added -- AMR plasmid context and a gated truth-promotion step (plan B4)
- `score_amr_placement.py` adds, beside the placement and never ranking a tool: **flank context** (share of the 1 kb either side of a recovered copy that the same record covers), **co-localisation** (recovered copies on one plasmid kept in the same bin) and **AMR-PRR** (plasmids with a curated AMR copy whose copies are all on the right plasmid and that were reconstructed correctly; `amr_complete_rate` is the same without the CPRR condition). New gene-copy columns `flank_covered`, `plasmid_cprr_correct`; new summary columns `n_amr_plasmids`, `amr_complete_rate`, `amr_prr`, `n_pairs`, `n_colocalised_pairs`, `colocalisation_rate`, `flank_context_rate`. Stage 5 passes `--cprr`; `AMR_FLANK_BP` sets the flank (pre-registration row `amr_flank_bp`, proposed).
- `python/promote_amr_truth.py` (`plasbench promote-amr-truth`): turns a reviewed `truth_amr.draft.tsv` into `truth_amr.tsv` only with `--reviewed-by`, `--confirm-reviewed` and the real `--database-version`; it validates the result, records reviewer, date and the draft's checksum, and refuses to overwrite without `--force`. `validate_amr_truth.py` now exposes `validate()` (same checks and messages).
- Report: five new columns in *AMR genes on the right plasmid*, registry rows, glossary terms and help text; without curated truth the section still says Not run.

### Added -- figures: complexity, outcome matrix, recommendation evidence, map identity and resistance brackets, TP/FP encodings (plan D3-D7)
- **D3** new figure `fig-complexity` (*Figures*): per analysis track, base F1 of each tool on each isolate against the isolate characteristics of `benchmark.dataset_features.tsv` (plasmids in the truth, largest repeat fraction, contigs, read depth), each marked as knowable without a reference or needing it; Spearman correlation per tool only with at least five isolates and some spread, otherwise 'not computed'.
- **D4** the plasmid matrix gains, under each track's coverage table, an outcome table (perfect, partial, fragmented, merged, fragmented and merged, missed; a tool that wrote no bins is 'not assessable', not a miss).
- **D5** the *Recommendations* section gains an evidence panel (`report_recommend_evidence.py`): expected performance, independent studies, reference quality, dataset similarity and whether choosing by similar isolates beat the single best, uncertainty, and the reason when nothing is recommended or the headline is provisional.
- **D6** the circular plasmid maps (static and the interactive viewer, kept in parity by `test/test_map_rings.py`) shade each tool ring's covered stretch by alignment identity (four blue bands) and bracket resistance regions (truth resistance genes within 5 kb) outside the scale; legends updated; the viewer payload gains `rz`. The viewer holds at most 300 blocks per tool and plasmid, so its identity can differ slightly from the static map when blocks were omitted.
- **D7** the 3D landscape can size and colour points by true-positive or false-positive bases (new run fields `tp_bp`, `fp_bp`), reading it as a true/false-positive scatter of the runs; no new 3D code.

### Added -- a radar fingerprint of each tool (plan D2)
- New figure `fig-radar` (*Figures*, beside the tool heatmap): one radar per analysis track, one polygon per tool, seven axes (accuracy F1, recovery, CPRR, SV-PRR, verified sequence = 1 - unmapped share, runtime score, reliability). It is a view over the heatmap's own data (`report_fig_radar.py` calls `report_fig_heatmap.build`, which is now kept for the report), validates its axes against `config/metrics.tsv`, skips an axis that is not available instead of drawing 0, and carries the numbers in a table. Help text, glossary term, layout, wiring and `test/test_report_fig_radar.py`.

### Added -- the numeric tool x metric heatmap carries the new metrics (plan D1)
- *Performance of every tool across every metric* (figure `fig-heatmap`, one block per analysis track, numbers in the cells) gains five leaderboard columns: SV-PRR, the unmapped, off-truth and multi-mapped predicted-base shares and the precision gap. The shares and the gap are marked lower-is-better (colour flipped); every column has a per-isolate drill-down derived from `scores.tsv`, and a blank stays 'not available', never 0. No new figure code: the existing heatmap reads the leaderboard.

### Added -- three-way recommender comparison (plan C2)
- `evaluate_recommender.py` now also compares, over the same leave-one-study-out folds, the single best tool, the organism recommender and a **feature-conditioned** arm (the best tool among the five most similar training isolates by the truth-free dataset features; a reference-derived column is refused). `benchmark.recommender_arms.tsv` reports per arm: regret, top-1 and near-optimal rates, improvement over the single best, the studies in which it beat it, calibration (error and bias), abstention and the regret when it would answer. An arm adds value only when it beats the single best on average and in most of at least three studies; the verdict JSON gains `arms` and `feature_conditioned_enabled`. The existing recommender outputs are unchanged. The arms table is in the *Recommendations* evaluation detail; `test/test_recommender_arms.py` is new.

### Added -- a dataset-characterisation table (plan C1)
- `python/characterise_dataset.py` composes the per-isolate measurements the pipeline already makes (assembly stats, read depth and quality, repeat content of the truth, difficulty signals, organism and Gram group) into `benchmark.dataset_features.tsv`; it measures nothing itself. Every column is marked truth-free (knowable for an isolate with no reference) or truth-derived (benchmark only); a value not measured is blank, never 0. `test/test_dataset_features.py` checks the truth-free columns never include a field the recommender forbids.
- Stage 6 builds it (an advisory job) and the report shows it as *Dataset characteristics* in the *Isolate difficulty* tab, with each column's basis in its header; file-explorer entry, help text and glossary term.

### Added -- SV-PRR, CPRR with the structural calls beside it (plan B3)
- `call_structural_variants.py` now counts, per tool and isolate, the CPRR-correct plasmids that no structural call touches (`sv_prr_correct` / `sv_prr_plasmids` in `structural_summary.tsv`); `merge_bin_metrics.py` carries them into `scores.tsv`; the leaderboard gains `sv_prr`, `sv_prr_correct`, `sv_prr_plasmids` (appended last). CPRR itself, its definition and every rank are unchanged; SV-PRR is reported, never ranked, and as unvalidated as the calls (no read or graph support).
- Report: the CPRR cell of the leaderboard shows SV-PRR; a glossary term, a registry row, a pre-registration row (`sv_prr_use`) and column groups in the explorer. `test/test_sv_prr.py` is new.

### Added -- the burden of unverified predicted sequence reaches the leaderboard and the report (review, plan B2)
- `score_plasmids.py` already wrote `unmapped_pred_bp`, `off_truth_pred_bp`, `mapped_pred_bp` and `ambiguously_mapped_pred_bp`, but the aggregation dropped them. The leaderboard gains (appended last, pooled over the isolates): `total_predicted_bp`, `total_unmapped_pred_bp`, `total_off_truth_pred_bp`, `total_ambiguous_pred_bp`, `unmapped_fraction`, `off_truth_fraction`, `ambiguous_fraction` (the multi-mapping burden) and `precision_gap` (permissive minus strict precision). A column the scores do not carry is blank, never 0. The ambiguity alignment is already on by default (`REPORT_MAPPING_AMBIGUITY=1`).
- Report: four columns in *Ranking confidence* (unmapped, off-truth, alternative placement, precision gap), four registry rows (`config/metrics.tsv`), a leaderboard column group in the file explorer, a glossary term and help text. `test/test_burden_columns.py` is new.

### Added -- a metric registry and the evaluation ladder (plan B1)
- `config/metrics.tsv` and `python/metric_registry.py`: every metric with its ladder rung (detection, sequence recovery, binning, sequence reconstruction, biological validity; computational efficiency beside it), the tool types it applies to, its inputs, whether it ranks tools, its evidence grade (published definition / defined by PlasBench / unvalidated estimate / not available), the table and column that hold it, its scorecard id and where it is shown. The glossary keeps the wording of each definition (no second copy); the registry is the metadata, cross-checked by tests.
- Report: the *Classification and reconstruction metrics* section carries the registry-driven **reconstruction evaluation ladder** and states its gaps (no ranked metric on the sequence-recovery or biological-validity rungs; nothing on biological validity rests on a published definition); the glossary table gains *Ladder rung* and *Use* columns; a help entry and a glossary term. `test/test_metric_registry.py` (validation, glossary, scorecard and endpoint cross-checks) and `test/test_metric_wiring.py` (the demo's leaderboard and scores columns, the report sections, the glossary, the ladder and the docs) are new.

### Added -- more truth audits (review H3, plan A9)
- `python/audit_truth_labels.py` adds a `flags` column (the `finding` column is unchanged): `integrated_plasmid_candidate`, `chromid_candidate`, `secondary_chromosome`, `large_plasmid`, `multi_replicon_plasmid`, `marker_free_plasmid`, `multimer_<k>x` (from `truth.corrections.tsv`) and `collapsed_repeat_candidate` / `low_depth_region` (from the depth-anomaly summary). The size thresholds are `CHROMID_MIN_BP` (350 kb) and `LARGE_PLASMID_BP` (500 kb), config variables and pre-registered as proposed.
- `python/detect_dimers.py` detects higher multimers (up to 6 tandem copies): a new `copies` column, a collapse keeps the first 1/k, and a tetramer is reported as 4, not 2.
- `python/truth_marker_overlap.py` writes `benchmark.truth_marker_overlap.tsv` from `config/truth_marker_databases.tsv` and `config/tool_database_releases.tsv`: which tools share a database with the evidence that labelled the truth (`yes` / `possible` / `no` / `unknown`; MOB-suite tools share the MOB-typing evidence). A name-level screen.
- Report: the *Truth labels* tab gets a Flags column, flagged-only rows and a *Marker databases shared with benchmarked tools* table (with a Not run state); help text, a glossary term, a file-explorer entry and feature-manifest rows. Stage 6 and the demo run the new steps. `test/test_truth_audits.py` is new.

### Changed -- the ranking-sensitivity analysis covers the headline endpoints and the alignment length (review C6 / H1, plan A8)
- `python/rank_sensitivity.py` adds: a minimum-alignment-length sweep (`min_length=100`, `min_length=500`; the pre-registered value is 200); the headline short-read endpoint (`metric:lw_bin_f1`) and the 50% recovery band (`metric:plasmid_recall_ge50`) as alternative rankings; and CPRR re-ranked at coverage/bin-share thresholds 0.80, 0.90, 0.95 and 0.99 (`cprr@...`, read from `benchmark.cprr_threshold_sweep.tsv`; compared with the pre-registered 0.95 ranking). The table gains a last column `compared_with` (the F1 `baseline`, or `cprr@0.95`), and the report's *Filter and metric sensitivity* table shows it. Existing columns and variants are unchanged. `test/test_rank_sensitivity.py` is extended.

### Fixed -- a run never stops silently
- **Every way a stage can stop is reported on the console, in red, and in `logs/run_errors.log`.**
  - A command failing under `set -e` without a message of its own now prints which script stopped, the command, the
    exit code and what it usually means. Before, the stage just ended.
  - A stage stopped by a signal says so: Ctrl+C, a closed terminal, Cancel in the window, or SIGTERM from the system.
  - A stage killed outright by SIGKILL, which is what the out-of-memory killer sends and cannot be caught, is
    reported by `run_all.sh`: `the run stopped in stage 3 (03_assemble.sh): killed (SIGKILL): usually out of memory,
    or WSL or the system ended it`. `run_all.sh` used to end without a word when a stage failed.
- **A run cut off with no chance to report** (WSL or the computer stopping) is reported by the next run: `the
  previous run stopped before it finished ... (started <time>, stage 3 ...)`, with a note that finished work is reused.
- **The `plasbench` command** explains a death by signal when the pipeline itself was killed. **The window**
  appends to the job's console how and why the command stopped, for example `killed (SIGKILL): usually out of
  memory`, so a failed job never ends on a blank line.

### Changed -- the sample report link is at the top of the README
- A link to open the sample HTML report (online preview; a relative path for a clone) now sits directly under the README title, not only in the report section. GitHub removes `target="_blank"` from README links, so the link says to Ctrl/Cmd-click or middle-click to open it in a new tab. `test/test_sample_report.py` keeps it there.


### Added -- statistics validated by simulation (review C4 / C6, plan A7)
- `python/simulate_validation.py` (also `plasbench analysis simulate-validation`) simulates paired differences with study effects, correlated isolates, unequal study sizes and missing observations and runs the real `resampling.bootstrap_ci` and `resampling.paired_permutation_pvalue` on them, writing `benchmark.stats_validation.tsv`: interval coverage (nominal 95%) with its standard error, the rejection rate at 0.05 (type-I error at effect 0, power above it), how often each could be estimated, the test method and a verdict that never rounds a shortfall up. `smoke` mode (100 replicates, seconds, indicative) and `full` mode (1,000 replicates and the production resampling counts, minutes) share one seed. Stage 6 runs it when `RUN_STATS_VALIDATION=1` (`STATS_VALIDATION_MODE`); the demo runs smoke mode. The report gets a *Statistical validation (simulation)* tab under Sensitivity, power and reproducibility (with an explicit Not run state), a help entry, a glossary term and a file-explorer entry. **First finding:** the percentile cluster bootstrap under-covers with few studies (coverage roughly 0.85 to 0.94 across the smoke scenarios, mostly below 0.95), so its intervals are optimistic for cohorts of that size; the sign-flip test kept type-I error near 0.05. `test/test_simulate_validation.py` covers the generator, the verdicts, the command, the report section and the wiring.

### Changed -- permutation tests need six independent units and are exact for small designs (review C4, plan A6)
- `python/resampling.py`: named thresholds `MIN_CLUSTERS_CI` (5), `MIN_CLUSTERS_TEST` (6) and `EXACT_MAX_UNITS` (12). A sign-flip test with five units can never report p below 0.0625, so it is no longer reported (six units give 0.03125). Up to 12 independent units every sign pattern is enumerated (an exact p-value in integer arithmetic, no random numbers; the stratified test enumerates the macro-mean the same way); above 12 the Monte Carlo estimate is unchanged, with the same random stream. `permutation_method` and `permutation_floor` expose which applies and the smallest attainable p. Bootstrap intervals still need five units.
- `benchmark.paired_comparisons.tsv` gains `permutation_method` (exact / monte_carlo / not_estimated), `min_attainable_p` and `p_status` (ok / underpowered / not_estimated), appended last. The report's paired-comparison table gets a *Permutation test* column ("exact, smallest attainable p 0.03125", "underpowered: cannot reach 0.05"). The thresholds are pre-registered rows. `test_resampling_equivalence.py` compares the exact path with an independent enumeration and keeps the Monte Carlo path bit-identical above 12 units; `test/test_permutation_reporting.py` is new.

### Changed -- the pre-registration is a draft until its proposed values are confirmed (plan A5)
- `config/prereg.tsv` gains a status, `proposed`: a value is proposed (rationale in the note) and awaits the maintainer's confirmation. The rows that were `TO_FIX` with a proposed default (the tool timeout, now proposed at 7200 s with its rationale; the integrated-element depth; the circular-path rule; the scorecard weights and bands; the scorecard minimum; the map size) are `proposed`; the A4/C2 bands, which have nothing to propose, stay `TO_FIX`. `min_alignment_length` (200) is now a pre-registered row.
- `freeze_prereg.py`: `proposed` and `TO_FIX` are *unfixed* and make the plan a **draft**; `--status` reports `proposed` and `draft`; a draft can be locked with `--write` (so a run records which draft it used) but `--strict` refuses to write it and fails `--verify` (`--require-fixed` now also fails on proposed rows). The manifest and the report's Pre-registration tab show the draft state ("frozen and unchanged, but a DRAFT: N value(s) ...") and list the proposed rows. `REQUIRE_PREREG=1` is unchanged in intent: it refuses a draft. `test/test_prereg_freeze.py` covers it. Nothing is frozen: confirming the values and freezing is the maintainer's decision.

### Changed -- stage 2 (truth) is faster, parallel, resumable and says where its time goes
- **Each sample's stage-2 steps are timed.** The times go to `data/<sample>/stage2_timing.tsv`, and the log names
  every step that took 10 s or more, for example `stage 2 for S1 took 21m05s: annotation 20m31s, repeat_content 14s`.
- **Samples run in parallel** with `MAX_PARALLEL_SAMPLES`, the same setting as stages 1, 3, 4 and 5. The default, 1,
  stays sequential. An unusable truth table still stops the stage, and the stop names the sample.
- **Reference annotation** (`RUN_REFERENCE_ANNOTATION=1`) runs its callers at the same time, instead of one after
  another, and gives them threads. ISEScan, the slowest by far, gets the whole `THREADS` allowance instead of 1;
  AMRFinderPlus gets half; MOB-typer, abricate and barrnap share a few.
- `measure_depth.py` counts both mates at the same time, decompresses with pigz/gzip in a separate process, and
  touches only the sequence lines, in C. That is about 2x faster on a 90x read pair, with identical counts.
- `repeat_content.py` slices k-mers in C instead of looping over every base in Python. That is 1.5x faster on a
  5 Mb genome, with identical output.
- `mash dist` (evidence labels) and `samtools sort` (depth anomalies) use `THREADS` instead of 1 and 2.
- **Re-runs reuse** repeat content and the depth-anomaly scan when their inputs have not changed, instead of
  recomputing them every time.

### Fixed -- a run cut off during assembly resumes cleanly
- **Stage 3 is crash-safe.** fastp now writes `*.trim.partial.fastq.gz` and renames the pair only when it succeeds;
  a `.fastp.complete` marker records a finished trim. Trimmed reads left by a run that was cut off (a full disk, WSL
  or the machine stopping) used to be taken for finished reads and assembled truncated; they are now trimmed again,
  with a log line saying so. An interrupted SPAdes/Unicycler folder is cleared before reassembling, and the contigs
  and graph are copied under `.partial` names first, so a half-copied `contigs.fasta` is never reused. Finished work
  is still reused, including samples trimmed and assembled by an earlier PlasBench.

### Changed -- warnings are yellow and errors red, in the window and in a terminal
- **The window's console** uses one colour code in all three tabs (Job output, Session log, Terminal): errors are
  red and bold, with a red bar in Job output, and warnings are yellow. A line PlasBench tags `WARNING:` (for example
  a tolerated `SPAdes failed for ...`) is yellow; `ERROR:`, tracebacks, `No space left on device`, `command not
  found` and non-zero exits are red. A success line that mentions a failure (`... -> PASS`) and zero counts such as
  `failed=0` are not flagged. The Terminal tab now colours command output, and the Session log shows failed jobs and
  terminal commands red, cancelled or interrupted ones yellow.
- **Runs in a terminal** print `WARNING:` lines yellow and `ERROR:` lines red (`scripts/lib.sh`), only when the
  output is a terminal, so log files stay plain. `NO_COLOR` or `PLASBENCH_COLOR=never` turns colour off, and
  `PLASBENCH_COLOR=always` forces it.

### Changed -- heavy files never go into git, and you can edit .gitignore from the window
- **One catalogue of heavy formats** (`plasbench/gitops.py`, `HEAVY`) drives both the managed `.gitignore` blocks and
  the commit check, so the two cannot drift apart. It covers:
  - reads (FASTQ, also bzip2/xz/zstd-compressed; SRA; nanopore FAST5/POD5/BLOW5);
  - alignments and their indexes (BAM, SAM, CRAM, BAI, CRAI, CSI, PAF);
  - variants (VCF, BCF, TBI);
  - coverage tracks (bigWig, bedGraph);
  - aligner indexes and tool databases (minimap2, Bowtie2, BWA, Kraken2, Mash, DIAMOND, BLAST, HMMER, SQLite, HDF5,
    model files);
  - archives (tar, zip, 7z, bz2, xz, zst);
  - in study repositories, assemblies and sequences (FASTA, GenBank, GFF, GFA).
  Previously SAM was missing from the developer rules, and VCF, CRAM/BAM indexes, nanopore signal, indexes, databases
  and archives were not covered at all.
- **Repositories set up by an earlier PlasBench get the new rules**: the managed block is brought up to date, and
  lines outside it are never touched.
- **Heavy files already committed** (before a rule covered them) are listed on Version control, with **Stop
  tracking** (`git rm --cached`: the files stay on disk).
- **Edit `.gitignore` in the window** (Version control > Ignored files). PlasBench's block is shown read-only. Your
  own rules are editable and come after it, so `!results/key_plasmids.fasta` brings back a file the block leaves
  out. **Test a path** shows whether a file is ignored and by which rule. A sequence file you keep with your own rule
  is a warning at commit time. Reads, alignments, variants, indexes and archives stay blocked whatever the rules say.

### Added -- a structured evidence record for every reference (review H3)
- `python/truth_provenance.py` records six evidence fields per reference, additively: assembly technology, circularity evidence, read support, replicon/MOB evidence, structural integrity and independent validation, each `declared` (new optional sample-sheet columns `truth_circularity_evidence`, `truth_read_support`, `truth_structural_integrity`, `truth_independent_validation`), `inferred` (NCBI metadata, `truth_labels.tsv`) or `unknown`; plus `evidence_recorded` and `evidence_sources`. The original columns keep their order. Unknown never demotes a reference; an explicit adverse value (read support none, unresolved repeats) caps Tier 1 at Tier 2 and says why. `validate_cohort.py` checks the new vocabularies; the headline design table gains an *Evidence recorded* column; the demo declares some evidence and now builds the provenance table before aggregating (so the headline and the report read the same references). `test/test_truth_evidence_record.py` covers it. The cohort `truth_quality_tier` column is kept for now: it still feeds the tier and replacing it needs the cohorts re-curated (maintainer-owned).

### Changed -- the primary analysis is unavailable, visibly, when no reference qualifies (review E27 / H4)
- `headline_design.Design.headline_selection` replaces the silent fallback to all samples. With no reference in tiers 1-2 (or no provenance table) the **primary analysis is unavailable**: the same numbers are computed on all samples but labelled provisional. New append-only leaderboard columns `primary_status` (`available` / `unavailable` / `fallback_allowed`) and `population`; `primary_status` in `benchmark.headline_design.tsv`; a PROVISIONAL banner in the markdown leaderboards; a stdout warning; and in the HTML a banner above the ranking, a "Leading method (provisional)" tile, a "Primary analysis unavailable" finding, and a Primary analysis column in the headline design table. `--allow-primary-fallback` / `ALLOW_PRIMARY_FALLBACK=1` (default off) keeps the numbers as the headline with the warning. An older leaderboard without the columns is read as available. `test/test_primary_eligibility.py` covers the design, the aggregation and the report; the review ledger rows (E26-E29) are re-pointed and E27 is marked fixed. **Public-v3 and the demo are in the unavailable state** (no Tier 1-2 reference / no provenance table).

### Fixed -- the recommendation model used truth-derived features
- `python/recommendation_model.py` fitted its ridge model on the truth's plasmid size and plasmid count and on the truth's AMR annotation, which are unknown for an isolate with no reference (they were imputed with the training mean there), so the model could learn the answer in a retrospective run. The inputs are now truth-free only: read depth, the isolate's own assembly statistics, tool, organism and Gram group. `TRUTH_DERIVED_FIELDS` lists what is barred, `assert_truth_free` enforces it when fitting, and `load_model` refuses a ready model whose spec used one (with the reason and the refit instruction); older specs still decode. `test/test_recommender_truth_free.py` covers it.

### Added -- reference figures folder (planning for v0.4.0)
- `docs/images/reference/README.md` (tracked) maps four third-party reference figures to the report features they inspire (map identity rings and resistance-region brackets, numeric heatmap, true/false-positive 3D scatter, radar fingerprint). The images are gitignored and not shipped. `test/test_reference_images.py` keeps the README and the ignore rules in place.

### Added
- **Study folders.** Every benchmark keeps everything it produces in its own folder, `<workspace>/<study>/`
  (results, report, logs, tmp and a `study.json` recording the sample sheet with its checksum, the cohort and every
  command). `plasbench run` names the study after the cohort or sample sheet, or `--study NAME`;
  `plasbench report --study NAME` rebuilds one. The workspace is `PlasBench/studies` by default, or
  `PLASBENCH_WORKSPACE`. Downloads, tool environments and databases stay shared between studies.
- **The window: Workspace & studies.** Choose and check the workspace (writable, free space, drive type, cloud-sync
  and long-path warnings; a missing chosen folder is reported, never silently replaced), recent workspaces, every
  study with its report and folder, and New study. The New benchmark wizard shows and names the study folder.
- **The window: Version control.** Git without the command line, after GenoSuv's design: status, staging, diffs,
  commit, branches, remote, fetch/pull/push (as console jobs) and history, for the PlasBench folder or the
  workspace. A managed `.gitignore` block keeps studies, results, downloads, reads and credentials out; every commit
  is scanned (reads and run folders, `config/local.env` with the NCBI API key, tokens, files over 100 MB); remote
  addresses may not carry credentials; nothing is force-pushed; AI co-author trailers are removed.
- **PlasBench starts like a desktop program.** The installer adds a PlasBench icon to the desktop and the
  applications/Start menu (`plasbench desktop-icon`; `--remove`, `--no-desktop`; `install.sh --no-icon` skips it).
  On Linux it is a `.desktop` entry, on macOS `~/Applications/PlasBench.app`, and on Windows, with PlasBench
  installed inside WSL2, a Windows shortcut that starts PlasBench in Ubuntu. Clicking it runs
  `scripts/plasbench_launcher.sh`, which activates the `plasbench` conda/mamba/micromamba environment and starts the
  window. A second click brings the running window back (one server per PlasBench folder, recorded in
  `~/.plasbench/ui/server.json`). The window opens as an app window (Edge/Chrome `--app`; `plasbench ui --tab` for a
  browser tab). **Quit** in the window stops PlasBench, and asks first if a job is still running.
- **The PlasBench logo and icon.** A plasmid map holding three rising benchmark bars (`plasbench/data/logo.svg`,
  `docs/images/plasbench-logo.svg`, `docs/images/plasbench-icon.svg`). It appears in the window's app bar, as its
  favicon, as the desktop icon (PNG/ICO/ICNS drawn from the same geometry, nothing downloaded) and at the top of the
  README.
- **A terminal in the window's console.** The console stays fixed at the bottom of the window and now has two tabs:
  **Job output** and **Terminal**, after GenoSuv's design. The Terminal runs your own commands in the PlasBench folder,
  confined to it and the studies workspace. It offers the login shell (Linux, macOS), Ubuntu (WSL) or PowerShell
  (Windows), keeps a command history, and records each command. `plasbench` there runs this PlasBench folder.
- **Set up this computer → This computer.** Operating system, WSL, architecture, CPUs and RAM, conda and the
  `plasbench` environment, Docker. It also gives the recommended way to run PlasBench there (the conda environment,
  or WSL2 on Windows), the steps still to do, the warnings (Apple Silicon, low RAM, `/mnt/c` speed) and Docker as the
  alternative, with its command. The checklist also checks for the `plasbench` environment.
- **Side panel and main-area tabs.** **Panel** (top bar) opens a right-hand panel as wide as the navigation rail,
  with three tabs. **Studies** (the default) is a folder tree of the workspace's studies: reports open in a report tab,
  and tables, logs and text files open as read-only tabs. **Jobs** shows running and recent jobs with cancel. **Git**
  (Ctrl+Shift+G) has changes with stage/unstage, commit, branches, remote, tracked files and history.
  The main area works like a browser. It opens with an Overview tab, and every page you open is its own tab. Reports
  (with **Open in browser**; Ctrl+click opens the browser directly), files, diffs (line numbers, Stage/Unstage) and
  commits (files changed, parents, patch) open in tabs next to the current one. Tabs close with × or a middle-click,
  and the last one closed brings back Overview.
- **Git history is colour-coded**: the commit you are on, pushed, not yet pushed, and merge commits, with branch and
  tag labels. Hovering a commit shows its author, date, labels and whether it is pushed; clicking it opens it in a tab.
- **Version control tracks your runs, not the program: one repository per study.** Each study folder is its own
  repository, with its own history and remote. Its managed `runs` `.gitignore` keeps the study's record, tables,
  reports, figures and logs, and leaves raw sequence data (reads, assemblies, FASTA, alignments), tmp folders and
  credentials out. Studies show whether they are tracked, with a Git button on Workspace & studies and in the side
  panel. A new repository can no longer be started in the
  PlasBench program folder, and a workspace inside a program checkout is no longer mistaken for that checkout.
- **`plasbench install-git`** (optional; Set up → Git → Install). On Windows it installs Git for Windows with Git Bash
  through winget, and you answer any prompt in the console. Elsewhere it installs conda-forge git into the plasbench
  environment, or prints the system command.
- **The Terminal lists each WSL distribution by name**, plus Git Bash (never the WSL launcher) and PowerShell, and runs
  `git` in every shell. When WSL does not respond, it says so and suggests `wsl --shutdown`.
- **Session log and run script.** The console has a third tab, **Session log**. It shows, one line per event, what
  happened in the session: commands started from the pages and how they ended, answers, cancels, terminal commands,
  settings, workspace and study changes. Earlier sessions can be chosen too. **Save as script** downloads the session
  as a bash script that repeats it, with failed commands, PowerShell commands and answers as comments. The log is
  `~/.plasbench/ui/sessions.jsonl`; secret settings are never written, and hidden answers are masked.
- **Help on every page.** A Help button on each page header, the **?** in the top bar, and F1 each explain the page:
  what it is for, the steps, what is good to know, and the command-line equivalent. **Add your own tool** has a full
  guide (**How it works**) covering the form's five sections, placeholders and output formats. Its worked example
  adds MOB-recon as a user tool, and **Load this example** fills the form with it.
- **Cohort details.** On the Cohorts page, **Details** describes each shipped cohort, from its sheet, its lock and
  `cohorts/README.md`: isolates and species, plasmids in the truth, read depth, BioProjects, Illumina read volume and
  the download estimate. Breakdowns cover organism, truth tier, truth technology and strategy, origin, country and
  plasmids per isolate. A searchable sample table has NCBI links and, from the lock, host, isolation source,
  collection date and how the reference was sequenced and assembled. It also says whether the lock still matches the
  sheet. Metagenomic sheets show their communities, regimes and truth status (`plasbench/cohort_info.py`).
- **The window's console answers questions.** A command that asks (for example "Install the missing items now?")
  shows the question in the console, which highlights it; answer in the reply box or with Yes/No.
- **Reference figures folder (planning for v0.4.0).** `docs/images/reference/README.md` (tracked) maps four third-party reference figures to the report features they inspire (map identity rings and resistance-region brackets, numeric heatmap, true/false-positive 3D scatter, radar fingerprint). The images are gitignored and not shipped. `test/test_reference_images.py` keeps the README and the ignore rules in place.

### Changed
- **One `PlasBench` folder, updated in place.** `install_latest.sh` installs into `~/PlasBench` (or
  `$PLASBENCH_INSTALL_DIR/PlasBench`), and `update.sh` / `plasbench upgrade` update that folder instead of creating
  `plasbench-<version>` folders. Only files the previous release installed are replaced (`scripts/release_sync.sh`
  keeps a checksummed list; an edited release file is backed up to `.plasbench-backup/`); studies, settings, own
  tools, downloads, tool environments and databases are kept. An older versioned install is carried in: its runs
  move to `PlasBench/studies/`, its settings and own tools are copied, its downloads move to the shared folder once,
  and the old folder is deleted after confirmation (`--yes`, or kept with `--keep-old`).
- Script prompts print their question explicitly, so it is visible when the command runs from the window.
- `scripts/docker_run.sh` mounts the studies workspace (`PLASBENCH_WORKSPACE`, default `./studies`) at
  `/work/studies`, so a run in the container lands in the same study folder as a native run. An explicit
  `RESULTS_DIR` in the environment is honoured like `--results-dir`.
- The console is open by default (a quarter of the window) and remembers its height and whether you closed it.
- The fixed console never hides the end of a page: the page keeps a bottom margin as tall as the console, and
  scrolling to a field stops above it. The body was `height:100%`, so that margin used to end at the first screen.
- `test_install_latest.sh` follows the installer into the one `PlasBench` folder.
- The Terminal's command box is an expandable text area: one line by default, it grows as you type (Shift+Enter for
  a new line) and can be dragged taller.

## [0.3.0] - 2026-11-13

A feature release: benchmark your own tools without changing PlasBench's code, and do everything from a window in your browser with `plasbench ui`. No scoring, ranking or report change for the built-in tools. See the [release notes](docs/releases/v0.3.0.md). Compare: [v0.2.3...v0.3.0](https://github.com/ubeffiong/plasbench/compare/v0.2.3...v0.3.0).

### Added
- **The PlasBench window: `plasbench ui`.** Everything the command line does, from a page in your browser: a setup
  checklist with one-click fixes, NCBI credentials, the tool catalogue with installs and default switches, a form
  that writes and installs your own tool's manifest, every setting with its default (saved to `config/local.env`),
  a five-step New benchmark wizard, your own isolates, cohorts, runs and reports (open, PDF, rebuild), a job console
  with live logs and cancel, and every `plasbench` command as a form generated from the CLI parser itself. It is
  served only to this computer, with a per-session key, a Host-header check and same-origin POSTs, and it runs
  nothing but `plasbench` commands that the real parser has accepted. No network resources; light and dark themes.
- **Bring your own tool.** Any plasmid reconstruction or classification tool can be benchmarked without changing
  PlasBench's code: a `plasbench-tool.ini` manifest declares its task and track, how to install it (conda, pip, a
  script, or nothing), how to run it per sample (a command with `{contigs}`, `{graph}`, `{reads_1}`, `{long_reads}`,
  `{outdir}`, ... placeholders) or where its existing outputs are, and how to read its output (contig-bin table,
  contig labels with probabilities, plasmid FASTA, a folder of FASTA files, or its own adapter). New commands:
  `plasbench tools new|validate|list|show|add|install`, `plasbench install-tools NAME` and `plasbench run --tool NAME`
  (`USER_TOOLS` in the config). User tools share the built-in tools' timeouts, retries, outcome states, result reuse,
  leakage check, long-read circularity rule, scoring, ranking and report, and their manifest, checksum and version
  are recorded in `run_manifest.json`. Guide: docs/ADDING_TOOLS.md; examples: tools.d/examples/.

## [0.2.3] - 2026-11-13

A patch release: database downloads resume, `plasbench check` fetches Platon's database itself, RFPlasmid's CheckM starts again, and `plasbench test` passes on a release install. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.3.md). Compare: [v0.2.2...v0.2.3](https://github.com/ubeffiong/plasbench/compare/v0.2.2...v0.2.3).

### Fixed
- **MOB-suite and Platon database downloads resume.** A new `resumable_download` helper (`scripts/lib.sh`) keeps every byte already received, continues with `curl -C -` after a dropped connection or a re-run, pauses while the internet is down instead of spending retries, checks the size, and only then renames the `.part` file. `mob_init` cannot resume (it truncates its archive on every attempt), so PlasBench downloads MOB-suite's archive itself and hands `mob_init` the finished file as a `file://` mirror; `mob_init` then only unpacks and builds.
- **`plasbench check` downloads Platon's database** from its documented Zenodo file (1,690,687,855 bytes, size-verified) instead of asking for a URL.
- **RFPlasmid / CheckM start again.** CheckM imports `pkg_resources`, removed in setuptools 81; the `rfplasmid` profile now pins `setuptools<81`.
- **`plasbench test` passes on a release install.** The review-ledger test no longer fails on `.github/` files, which release archives do not ship (still checked in a git checkout and CI).
- MOB-suite database paths no longer show conda-forge's `lib/python3.1` alias in messages.

### Added
- README **Step 7d**: one-time setup for AMRFinderPlus (`amrfinder -u`), RFPlasmid's CheckM data and Plasmer's database (links, checksums, default folder, RAM check). The installer's closing message points to it.

## [0.2.2] - 2026-11-13

A patch release: the `trycycler` install no longer stalls. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.2.md). Compare: [v0.2.1...v0.2.2](https://github.com/ubeffiong/plasbench/compare/v0.2.1...v0.2.2).

### Fixed
- **Trycycler and Medaka install into their own environment, `plasbench-trycycler`.** Solving Medaka's PyTorch stack into the large main environment ran for 45+ minutes without finishing during `install-tools all` / `install_latest.sh --tools`; in a fresh environment the same packages install in about 4 minutes. Wrappers for `trycycler`, `medaka` and `medaka_consensus` go into the main environment; the main environment's own `flye` is left untouched.

## [0.2.1] - 2026-11-13

A patch release: `plasbench install-tools all` now completes. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.1.md). Compare: [v0.2.0...v0.2.1](https://github.com/ubeffiong/plasbench/compare/v0.2.0...v0.2.1).

### Fixed
- **PlaScope, Plasmer and PlasmidHunter install into their own environments.** None could be solved into the python 3.12 main environment: PlaScope's pinned Centrifuge 1.0.3 is built only for python <= 3.6, Plasmer only for python 3.10, and every PlasmidHunter release requires python 3.10. Each now lives in `plasbench-plascope`, `plasbench-plasmer` or `plasbench-plasmidhunter`, with wrappers in the main environment, as MOB-suite already does. You still only activate `plasbench`.
- PlasmidHunter is pinned (1.4) with `setuptools<81`, which it needs for `pkg_resources`; the installer now proves each isolated tool starts instead of only checking that its file exists, and rebuilds an environment that does not.
- Plasmer no longer pulls Anaconda's commercial `defaults` channel.


## [0.2.0] - 2026-11-10

A minor release: rankings, the recommendation output and some column names differ from v0.1.5, and the HTML report is rebuilt. Read **Upgrading from v0.1.5** in the [release notes](docs/releases/v0.2.0.md) first; everything below is the detail behind them. Compare: [v0.1.5...v0.2.0](https://github.com/ubeffiong/plasbench/compare/v0.1.5...v0.2.0).

### Changed -- the sample report is replaced by every demo run
- `test/run_demo.sh` (so `plasbench demo` and the demo tests too) ends by running `python/refresh_sample_report.py`, which replaces `docs/sample_report/benchmark.report.html` with the demo report just built. It is skipped, with a printed reason, when `docs/sample_report/` is absent, `PLASBENCH_SAMPLE_REPORT=0`, or the report is incomplete or holds a local path, and it never fails the demo. `test/test_refresh_sample_report.py` covers it.


### Added -- a download button per isolate in the plasmid matrix
- In *Which tool recovered which plasmid* (one table per analysis track) every isolate has a small **FASTA** button that downloads that isolate's best reconstructed
  plasmid(s): the selected candidate, `selected_candidates/<isolate>/<isolate>.candidate.plasmid.fasta`. The button works when the report is open from its results
  folder. When the report has been copied away, so the file cannot be reached, the button is **greyed out** and says why; an isolate with no selected reconstruction is
  grey from the start. Over http(s) the check is a HEAD request; from a local file the browser forbids reading files, so the file is requested as a script (it loads when
  the file exists and fails when it does not; the browser may log one harmless parse error per file in its developer console).
- The notes under the Summary's sub-headings (the plasmid matrix, the report card) are now hover tooltips like every other section note; only the Summary's own lead
  stays visible.

### Added -- a sample report in the repository
- `docs/sample_report/benchmark.report.html` is the report built from the offline demo (synthetic data, about 11 MB), with a README that says what it is, how to regenerate it and what differs from a real run. The project README links to it, with an online preview link. `test/test_sample_report.py` keeps the link, the file and its contents honest.

### Added -- a "?" help button on every section and tab
- Every section and every tab of the report has a green **?** button beside its title. A click opens one help dialog that explains the analysis for a reader who is
  not a specialist, in the same six parts everywhere: *In plain words*, *Data used*, *How it was made*, *How to read it*, *Why it matters* and *Keep in mind*. Esc, the
  Close button or a click outside closes it; focus returns to the button; the button is hidden in print. The texts are in `python/report_help_text.py` (84 entries on
  the demo), injected by `python/report_help.py` as one JSON block, so the page grows by about 45 KB, not once per button.
- `test/test_report_help.py` fails when a section or tab has no entry or an entry leaves one of the six parts empty, so a new analysis cannot ship without its help.
  It sits beside the small "i" popovers, which still carry each section's own lead note on hover.

### Fixed -- 3D charts drawn flat
- Pruning a Not-run tab also removed the shared 3D engine script that was emitted after it, so the 3D landscape fell back to its flat static picture. Pruning now keeps
  script and style blocks, and a test checks the demo page carries the engine.

### Fixed -- out-of-memory failures counted as the tool's fault
- A run whose log shows "Cannot allocate memory", `std::bad_alloc`, `MemoryError` or "out of memory"
  is a **resource** failure, like exit 124/137: by default it still scores 0, but it is reported as
  `failed_resource`, and `--resource-failures exclude` drops it. Found on cohort 1, where plasmidSPAdes
  ran out of memory on one isolate (exit 250) and was counted as an ordinary tool failure.
- **PDF export from WSL**: a Windows Edge/Chrome found under `/mnt/c` is given Windows paths (`wslpath -w`)
  for the report, the PDF and its profile; it could not open Linux paths and wrote no PDF.

### Changed -- section review: duplicates, mixed tasks and not-run sections
- **Recommendations are made for one task.** `select_operational_method.py` now recommends among the reconstruction tools only (`binning_capable=yes` in
  `config/tool_capabilities.tsv`); classifiers are ranked separately and are no longer compared with reconstruction tools in one "recommended overall" line.
  `benchmark.recommendations.tsv` has a last column `task`; `--task all` keeps the old behaviour and warns. The report says "One task" above the recommendation.
- **One place for each result**: the Automated interpretation section (it repeated *Start here*) is gone; per-plasmid results live in Plasmid maps ("All per-plasmid
  results" is its tab); run outcomes are one table with a reason column; Assembly adequacy is a tab of Assembly quality; both database-leakage screens are one tab;
  the two truth-quality groups are one *Reference standard* group beside the Headline design (with the pre-registration); the contig layer no longer prints the
  independent second scorer twice.
- **Fewer views of the same data**: the scorecard and its by-scenario views and the five-dimension composite are one *Scorecard (exploratory)* view with tabs; the
  Overview keeps the result, its confidence and the findings, the rest moved to Detailed results and Methods; the per-isolate recommender evaluation is one
  *Recommender validation* card under Recommendation, closed by default.
- **Artifact explorer replaces the "Data in this report" table**: each of its files has a description (what it is, which step wrote it, where it is shown); empty
  Logs and Data folds are hidden.
- **Glossary**: the 40 key headings are one searchable table.
- **Not-run sections are listed once**: a section or tab that holds only a "Not run" notice is not shown; *Run metadata* lists it with its reason ("Not run in this
  run"), and the old section id still lands there. *Extended analyses and next steps* is one line in Run metadata unless results exist.
- **The interactive cohort dashboard is optional** (`--embed-dashboard` or `REPORT_EMBED_DASHBOARD=1`, default off): it repeats the heatmap and metric tables and
  adds about 1 MB (the 6.5 MB of evidence-explorer data is separate and stays, lazy-loaded). The evidence explorer is unaffected.
- Panels of the explorers no longer show two headings; "Selected reconstructions" says why a selection needs review. The feature manifest keeps an explicit
  `REMOVED_BY_DECISION` list (six rows, each with its reason and where the information went) so nothing is lost silently.

### Changed -- order and wording for readers who are deciding
- **View order**: Overview, Recommendation, Figures, Plasmid maps, Detailed results (was "Statistical diagnostics"), Data quality, Methods and limits, Scorecard
  (exploratory), Appendix. Menu labels equal view titles; section labels in the menu are two to four words. Figures run CPRR differences, CPRR distributions, heatmap,
  precision-recall, ladder, 3D landscape, then the interactive cohort dashboard; the dashboard (Figures) and the reconstruction evidence explorer (Plasmid maps, new
  section `evidence-explorer`) are no longer in the Appendix.
- **Banner**: the title only. The duplicate numbers (samples, tools, leader, execution issues) are gone; the Summary has them once, then *Start here*, the plasmid matrix,
  the report card and the scorecard overall. The eyebrow is no longer all capitals.
- **Phone top bar**: the isolate filter, palette, collapse all and print / save PDF sit behind one menu button; the search keeps the room.
- **Display names at build time** (`python/report_names.py`): tool ids in the page text become display names when the report is built (link text only when it is exactly
  one id; file names, attributes, options and code are left alone), so print, PDF and no-JavaScript readers see them too.

### Changed -- the two explorers load when first shown
- The interactive cohort dashboard and the reconstruction evidence explorer (7 to 8 MB each) were written into their iframes at page load even though they sit in the
  Appendix, which opens hidden. They are now written only when the frame first becomes visible (with a 400 px margin), when the reader presses *Load now*, or at once
  when printing or exporting a PDF (`?print=1`, `beforeprint`) or where `IntersectionObserver` is missing. The documents stay in the page (it is still one offline file).
  On the demo report the page finishes loading in about 1.5 s instead of 4.5 s. `test/test_lazy_frames.py` runs the loader in node against a stub DOM.

### Changed -- report layout, condensed analytics, full PDF
- **Page shell** (`python/report_layout.py`): fixed top bar and left rail, one view at a time (Overview, Scorecard, Figures, Plasmid maps, Diagnostics, Data quality,
  Recommendation, Methods, Appendix) in story order, compact title band, status-chip accordion for data quality, hash routing for every old id, no-JavaScript fallback
  (the full linear page). 73 top-level sections become 34.
- **Merged analyses** (`python/report_merge.py`): related sections become tabs of one container and keep their old id as the panel id (`python/report_aliases.py`
  resolves old links): Ranking confidence, Method ranking (chart, metric framework, MCC and F-beta, graded recovery, negative control, baselines), Cohort and truth
  quality, Run outcomes and cost, Bin diagnostics, Scorecard (composite as *Weights and sensitivity*), Recommendations, Recommender, All scores (by tool, by sample) and
  a Reference tables appendix. The duplicate paired-comparison table in the unseen-taxa section is gone (it was a second copy of the Paired tests table).
- **Isolate filter and plasmid matrix** (`python/report_isolates.py`): the Summary and the Scorecard used to show cohort-wide numbers only. The Summary now has a
  *Which tool recovered which plasmid* matrix (one row per truth plasmid, one column per tool, coverage with a tick, half circle or cross, the best tool starred, and
  per-tool counts of plasmids recovered and plasmids on which the tool was best; one table per analysis track). An **Isolate** filter in the top bar (default *All
  isolates*) swaps the report card, the scorecard overall, the whole Scorecard (every metric re-scored on that isolate alone) and the matrix to one isolate's own
  numbers; a scope label next to each heading says which isolate is shown, and the no-JavaScript and print views show all isolates. The run line under the title is
  removed (the run folder is in the top bar and the full run details are in *Run metadata*).
- **Content uses the full width; folds start open**: the right-hand "On this page" strip is gone and the list now sits at the bottom of the left rail (it follows the
  view on show and highlights the current section). Every fold (cards, folded tables, drill-downs) starts expanded and can be collapsed; the top-bar button reads
  *Collapse all* / *Expand all* according to the state of the view. Summaries written as "Show the X" read "The X".
- **Condensed tables** (`python/report_condense.py`): tables over 15 rows show 12 rows with a filter and *Show all*; consistent table typography.
- **Full PDF export** (the browser sandbox stays on; where it cannot start, e.g. a container, set `PLASBENCH_BROWSER_FLAGS=--no-sandbox` for that run): print stylesheet with cover and contents, one view per page, every fold open; `python/export_report_pdf.py` and `plasbench report-pdf`.
- **No feature lost**: `test/fixtures/report_feature_manifest.tsv` (254 features of the earlier report) is checked by `test/test_report_feature_manifest.py`.
- **Corrected statements**: the ranking metric is named where the ranking score is quoted; the claim that failed runs are excluded from means is replaced by the real rule
  (F1 = 0 for a failed run on a plasmid-bearing isolate); robustness column renamed; power table names its metric (`power_analysis.py --leaderboard`); scenario views share
  one definition; scorecard overall beside the report card; glossary covers CPRR, MCC, F2, scorecard terms and NGOC; `--scores` folder is the results directory.

### Added -- figure gallery
- **Reconstruction ladder** (`fig-ladder`, `docs/images/reconstruction_ladder.svg`): the five steps from contigs to a verified plasmid, the score layer that judges
  each, live values from the run, and three explicit distinctions (binning is not reconstruction, circular is not correct, 3D is illustrative), two of them quantified.
- **3D landscape** of accuracy, completeness and structural fidelity (`fig-landscape`), **tool-by-metric heatmap** with clustering (`fig-heatmap`), **CPRR distributions**
  and **forest plot** (`fig-distributions`, `fig-forest`), and an interactive **precision-recall** plot (`fig-pr`). Each has a side setup panel, tooltips, drilldown,
  a no-JavaScript fallback and SVG / PNG / CSV export. The shared 3D engine no longer uses `Math.random`.
- Plasmid viewer: linear **Reference versus reconstruction** pane and Alignment tab, linked to the circular map; per-tool alignment blocks in the payload.
- `python/report_collapse.py` folds the scorecard, accuracy, performance, stratified, replicon-recovery and graded-tier tables that a figure now draws into closed details
  (nothing is removed). `python/report_figures.py` wires the figure modules; a module that raises fails the build instead of leaving a silent gap.

### Added -- databases kept once per machine
- **`PLASBENCH_DB_DIR`** (default `~/.plasbench/databases`): every tool database default points
  there instead of `DATA_DIR/db`, so new checkouts, new `DATA_DIR`s and rebuilt environments reuse
  what is downloaded. A database still at the old `DATA_DIR/db` path is used until the store has it.
- **`env/preserve_databases.sh`** moves existing databases into the store and leaves a link at the
  old path; never deletes; reports duplicates.
- **MOB-suite's database** moves to the store and its environment folder becomes a link; setup and
  the MOB-suite installer link a rebuilt environment to the stored copy instead of downloading again.

### Fixed -- MOB-suite pandas incompatibility in local installs
- MOB-suite needs `pandas<=1.5.3`; in the main environment (pandas 3) `mob_recon` crashed at start
  and every run scored 0. `env/environment.yml` and its lock no longer include `mob_suite`;
  `env/install_tools.sh` installs it into its own environment, `<env>-mobsuite` (MOB-suite 3.1.9,
  the Dockerfile's pins), and writes `mob_recon`/`mob_typer`/`mob_cluster`/`mob_init` wrappers into
  the main environment. `setup_conda.sh` runs this step; `plasbench install-tools mobsuite` repairs
  an existing install. The MOB-suite database checks follow the wrapper (`scripts/lib.sh`
  `mobsuite_db_dir`), as does stage 6's database-containment step.

### Added -- downloads kept for future runs; broken tools caught early
- **Preserved downloads** (`PRESERVE_DOWNLOADS=1`): stage 1 writes `<sample>/downloads.sha256` for the
  reads and NCBI records and makes the reads read-only; a later run with the same `DATA_DIR` verifies
  them and downloads nothing, and re-fetches only a file that fails its checksum.
- **Tool smoke test at setup**: an enabled tool that is installed but cannot start (for example
  MOB-suite importing a name newer pandas removed) is reported as `[BROKEN]`, not `[ok]`.
- **Import failures are infrastructure failures**: a run whose log shows `ImportError`,
  `ModuleNotFoundError` or similar is never scored as the tool's F1 = 0; it is rerun after the fix.
- Download tests force `READ_SOURCE=sra`, so they never reach ENA over the network.

### Added -- interactive report views
- **Info popovers for explanatory notes** (`python/report_info.py`, `assets/report/info_script.html`): one post-processing step on the finished
  page moves section leads, "how to read" notes and figure captions into a circled "i" beside the heading that opens on hover, keyboard focus
  or tap (click pins, Esc closes, links inside stay usable, works inside collapsed sections). The plasmid viewer, the 3D views and the colour
  palette bar use the same icon for their hint lines. "Not run" notices, caution boxes, notes that carry a status or a value, and the Summary
  section stay on the page; the print view shows every note inline. Notes keep their original HTML and the page is shorter to read.
- **Interactive plasmid map viewer** (`assets/report/plasmid_viewer_*.html`, `python/report_maps.py`): one viewer with a side panel replaces the
  stack of static maps. Hover tooltips, click drilldown into a Detail tab, wheel zoom and drag rotate with labels re-laid out, region inputs,
  search, layer, class and tool filters, Tools / Features / Events tables as tabs, SVG, PNG and TSV export, shareable URL-hash state, keyboard
  and touch support. The static SVG maps stay as the no-JavaScript and print fallback.
- **3D views** (`python/report_3d.py`, `assets/report/viz3d_*.html`): rotatable SVG scenes (no libraries, offline) for the contig layer beside
  the reference layer (bars per tool and layer with the independent-scorer cross-check), the per-isolate recommender against the single best
  tool and the oracle (regret gaps and a verdict banner), and AMR genes on the right plasmid (a tower of rings, one per tool). A static server-
  rendered view is the no-JavaScript and print fallback; a test checks the JS and Python projections agree.
- Large tables are collapsed until opened: scorecard definitions, headline design and reference standard, classification and reconstruction
  metrics, interpretation limits, the per-plasmid table and the regret table (their rows are also in the viewer and 3D panels; nothing is removed).

### Added -- report overhaul: scorecard, maps, workflow, inventory
- **Workflow figure moved to the README**: it describes how the pipeline is built, not what one run produced, so the report no longer has a
  Workflow section. `python/report_workflow.py` now draws a static `docs/images/workflow.svg` (embedded in the README's "Benchmark workflow"
  section); a test fails if the committed file drifts from the generator.
- **Weighted scorecard** (`python/report_scorecard.py`, `config/scorecard.tsv`): 17 metrics A1-E3, piecewise-linear score (100/85/60/0), metric bands, overall
  bands (90/75/55), weights renormalised over scored metrics with the scored weight share, and non-exclusive scenarios (simple, complex, annotated,
  challenging) with an underpowered flag below `SCORECARD_MIN_SAMPLES` (5). Only the identity bands are `fixed`; the rest are `proposed` and registered in
  `config/prereg.tsv`. A4 and C2 are `undefined` (no truth variant set): no thresholds, excluded from the overall.
- **Circular plasmid maps** (`python/report_maps.py`): per truth plasmid, with truth genes, tool coverage rings, GC content and GC skew
  (`MAP_MAX_TOOLS` 8, `MAP_MAX_BP` 600000).
- **Data inventory** ("Data in this report", `python/report_surfaces.py`), per-plasmid detail, assembly-quality section, depth strip,
  grouped collapsible navigation, a column-group switch for the scores table, and links to `leaderboard.md` and `scoring_spec.md`.
- Corrected the paired-comparison table and the overlap wording.
- Docs: SCIENTIFIC_GUIDE 7.10, 13.3, 15, 17.4; METHODS; README. New variable `SCORECARD_MIN_SAMPLES`.

### Changed -- performance audit fixes ([docs/PERFORMANCE_AUDIT.md](docs/PERFORMANCE_AUDIT.md))
- **Bin matching is rectangular** (`python/matching.py`, shared by `score_bins.py`, `score_amr_placement.py` and
  `metagenomics.py`): O(r²c) instead of a padded O(max(B,P)³) square. Same optimal total weight; the same pairs
  wherever the optimum is unique (`test/test_matching.py`); 400 bins × 20 plasmids in 0.02 s.
- **Exact statistics without `Fraction` objects** (`python/resampling.py`): every mean, bootstrap interval and
  permutation p-value is bit-identical to before (`test/test_resampling_equivalence.py`), and resampling adds
  precomputed per-cluster integer sums. `headline_design` and `aggregate_results` no longer import each other.
- **Stage 4 reuses a tool result only when its fingerprint matches**: installed executable, adapter, database row,
  `<TOOL>_*` settings (thread counts excluded) and inputs are written into `.<tool>.complete`. An upgrade, a
  changed setting or a new assembly re-runs that tool. Markers from earlier releases re-run once
  (`REUSE_UNFINGERPRINTED=1` reuses them unchecked).
- **Capability registry read once per stage** (`tool_capabilities.py --dump`, `lib.sh load_capabilities`) instead
  of one `python3` launch per lookup (12.5% of the demo's wall time).
- **One minimap2 index per sample** in stage 5 (`.reference.<preset>.mmi`, deleted afterwards); byte-identical
  PAF across all 105 call shapes checked on the demo.
- **Stage 6 advisory analyses run as a bounded parallel group** (`STAGE6_PARALLEL_JOBS`, default 4; 1 restores
  the serial order).
- **`plasbench-score` applies the pre-registered alignment filters** the caller omits (`MIN_ALIGNMENT_*` when
  exported); a direct `score_plasmids.py` run without filters prints a note.
- **Shared, validated readers** in `plasbench_common.py` (`read_truth_table`, `read_bin_membership`, `iter_fasta`,
  `open_maybe_gz`, `union_length`) replace 20 local copies. `bin_quality.py` now applies the bin scorer's rules
  (a non-`PLASMID`/`CHROMOSOME` truth row, or a contig in two bins, is an error) instead of reading them differently.
- The leaderboard writer refuses a column/value count mismatch; `test/bench/` holds the timing harnesses.
- **Data-structure upgrades, results unchanged** (every output hash identical before and after,
  `test/bench/bench_dsa.py`): hash-map indexing in `bin_agreement.per_bin_rows` (64×) and hash-set dedup in
  `read_bins` (86×); hash sets for the matcher's live rows (6.8×); a bounded heap for the visualization top-k;
  a sliding window between N positions with bytes encoded once in `contig_crosscheck.sampled_kmers`; binary
  search in calibration bucketing; a `Counter` for duplicate checks; the permutation tests' fair-bit draw
  inlined (a bulk bit-decoding variant was measured slower and not kept).
- **Streaming reads**: `iter_fasta(path, wanted)` skips unwanted records without joining them; the database
  containment check no longer holds the chromosome (peak 12.7 → 0.4 MiB on a 5 Mb reference).
- **Parallel ENA downloads**: both mates at once and `ENA_DOWNLOAD_CONNECTIONS` (default 4) byte ranges per
  file of at least `ENA_SEGMENT_MIN_BYTES` (aria2c when installed; `ENA_USE_ARIA2=0` disables it), falling back
  to the resumable single stream and always MD5-verified (`test/test_fetch_ena_parallel.py`). 8.6 → 1.6 s for
  2 × 16 MiB at 4 MiB/s per connection.
- **Thread budget**: with `THREADS` unset, the cores are divided across `MAX_PARALLEL_SAMPLES × MAX_PARALLEL_TOOLS`
  instead of every job requesting every core (`test/test_thread_budget.sh`).
- Stage-4 fingerprints identify a tool's executable by path, size and modification time and never run it to ask
  its version (a tool that does not parse `--version` could otherwise start a real run).

### Fixed
- Leftover merge-conflict markers in this changelog.

### Changed -- track-specific endpoints and CPRR robustness
- **Long-read and hybrid reconstruction are now ranked on isolate-level CPRR** (`sample_cprr`); short-read reconstruction stays on
  length-weighted binning F1 with CPRR as the key secondary endpoint (`headline_design.ranking_metric()`; `config/prereg.tsv`
  `primary_endpoint`, `primary_endpoint_long_read`).
- **CPRR threshold sweep**: `score_bins.py` writes correct counts with coverage and bin share at 0.80-0.99; new
  `benchmark.cprr_threshold_sweep.tsv` and leaderboard `cprr_auc` (normalised area under the pooled curve).
- **Isolate-weighted CPRR** (`cprr_isolate_mean`, `cprr_isolates`) beside the pooled rate.
- **Stratified CPRR**: `cprr` and `n_cprr_assessed` per size band, replicon, MOB and AMR carriage in
  `benchmark.recovery_by_replicon.tsv` (identity rule via `--truth-provenance`), and pooled CPRR per reference tier.
- README evaluation framework and workflow sections; METHODS, PREREGISTRATION and the HTML report updated to match;
  `test/test_cprr_robustness.py` added.

### Added -- completing the plsMD, PlasEval and GAEMR follow-ups
- **PlasBin-flow output adapter** (`RUN_PLASBIN_FLOW`, `PLASBIN_FLOW_OUTPUTS_DIR`, `adapters/adapt_plasbin_flow.sh`): adapts the tool's own output
  (it needs a Gurobi licence, so PlasBench does not run it); a contig listed in several bins stays in the first and the rest are recorded.
- **Cross-check against the original PlasEval** (`test/test_plaseval_crosscheck.py`, optional, `PLASEVAL_SRC`): best-match precision, recall and F1
  agree on every case, and the normalised dissimilarity agrees on every case without repeated contigs.
- **Optional label evidence**: several Abricate replicon databases (`ANNOTATION_REPLICON_DB`) and BLAST-based ISFinder annotation (`ISFINDER_FASTA`).
- `env/download_plsdb.sh` now has an offline test and refuses a download that is not FASTA: the PLSDB address in plsMD's Dockerfile redirects to an HTML page.

### Fixed
- The `repeat_rich` scenario tag never fired on real annotation: it counted feature types `is` and `isescan`, while `annotate_reference.py` writes
  `insertion_sequence`.

### Added -- lessons from plsMD, PlasEval and GAEMR
- **plsMD wrapper** (`RUN_PLSMD`, `adapters/adapt_plsmd.sh`): an optional benchmarked reassembly tool, skipped with a recorded reason when
  its command, PLSDB index or Unicycler assembly is missing; PLSDB listed as its database for the leakage screens.
- **`baseline_replicon`**: a third trivial baseline (a replicon marker, with plsMD's Col-versus-Inc rule).
- **Bin agreement** (`python/bin_agreement.py`, PlasEval's published definitions reimplemented): best-match (non-one-to-one) precision, recall
  and F1, a split/join dissimilarity, a tool-vs-tool agreement matrix and a PlasEval-format export.
- **`CHIMERIC` contig label** and a `plasmids` column in the contig labels (GAEMR's misjoin idea).
- **Assembly adequacy**, **plasmid copy-number concordance**, **truth repeat content** and opt-in **truth depth anomalies**.
- **Origin-wrap fix**: a rotated circular plasmid is no longer reported as a tandem duplication by `call_structural_variants.py`.
- Local read pairing for `init-local --reads-dir` (`_1`, `_R1`, `_R1_001`), `env/download_plsdb.sh`, report sections for all of the above, and a README
  section on what PlasBench offers over the three projects, with where each is better.

### Added -- cross-check, ENA fallback, demo coverage
- **Independent second scorer for the contig layer** (`contig_crosscheck.py`): alignment-free k-mer
  labels and separately written metrics; per-run agreement table, report and validity statement.
- **ENA fallback for short reads** (`fetch_ena_reads.py`, `READ_SOURCE`): when `prefetch` fails (for
  example an old SRA Toolkit failing TLS), the same run is fetched from ENA and MD5-verified.
- The demo now has a synthetic assembly, so the contig layer, the cross-check, assembly statistics and
  the QC-gate warnings render with real values.

### Added -- scoring specification and panel examination
- **Pre-registration** (`config/prereg.tsv`, `freeze_prereg.py`): freeze/verify a SHA-256 lock; the
  manifest and report show the hash, lock state, `TO_FIX` items and departing settings;
  `REQUIRE_PREREG=1` gates stage 4.
- **Labelling schemes** (`label_schemes.py`, `TRUTH_LABEL_SCHEME`, default `ncbi`): the headline is
  now scored on NCBI labels (Scheme 3, decision E.15) instead of the evidence-checked truth; Scheme 1
  and the evidence scheme are rank-sensitivity variants. **Behaviour change:** set
  `TRUTH_LABEL_SCHEME=evidence` for the previous scoring.
- **Dimer collapse** (`detect_dimers.py`, `COLLAPSE_DIMERS`), **truth grades** A/B/C, optional cohort
  columns `same_extraction`, `split`, `genus`, `phylum`, `grade_source`, `collection_date`.
- **Scoring**: `TN_bp`, `mcc`, `f2`, `f0_5`, `abstention_rate`, `--min-contig-length`; per-plasmid
  outcome states (`score_bins.py --outcomes-out`); contig-level binning F1 and shared/unassigned
  lengths; AMR placement by gene class (`score_amr_placement.py`, `config/amr_gene_classes.tsv`).
- **Outcome states**: `infrastructure_failure` (never scored), `TOOL_RETRIES`, `TOOL_TIMEOUT_SECONDS`,
  `tool_outcomes.tsv`, `benchmark.outcome_states.tsv`; `tool_status.tsv` schema unchanged.
- **Statistics**: Wilcoxon signed-rank (exact n ≤ 25) with Holm, equivalence flag
  (`SMALLEST_DIFFERENCE`); new rank-sensitivity axes (schemes, min contig 500, micro, public/in-house,
  grade C excluded, MCC/F-beta/contig metrics).
- **Recommender evaluation** (`evaluate_recommender.py`, `evaluate_warnings.py`, `leave_taxon_out.py`):
  regret, near-optimal, gap closed, `benchmark_only` verdict, warning PPV/sensitivity, leave-taxon-out
  and a once-only holdout.
- **Panel items**: recommendation floor (`RECOMMENDATION_MIN_EXPECTED_SCORE`, D11); operational states
  `insufficient_sequence` and `ambiguous_between_references`; advisory assembly QC gate (D13); a
  "tools compared" reason table (D15).
- Ten new HTML report sections and `benchmark.scoring_spec.md`; the demo exercises all of them.
- Docs: `docs/PREREGISTRATION.md`, `docs/PANEL_ALIGNMENT.md`, the scientific guide, METHODS, and
  the question bank (clustering/relatedness answers cut to "outside this benchmark").

### Added -- metric rubric
- **Contig-level classification** (`contig_classification.py`): contigs labelled against truth
  (>= 95% identity over >= 80% of the contig; short, ambiguous and unplaced contigs excluded and
  counted); count-based and length-weighted precision, recall, F1 and **MCC** per tool.
- **ARI** (base-pair weighted) and **assembly-aware binning recall/F1** in `score_bins.py`.
- **Micro** (pooled-base) precision/recall/F1 beside the macro means.
- **Sequence-level database membership** (`database_containment.py`): truth plasmids checked against
  each tool's own database; recovery reported inside vs outside it.
- HTML sections "Classification and reconstruction metrics" and "Truth plasmids in tool databases";
  README metric tables updated, with a headline metric set.

### Added -- reviewer question bank
- **Trivial baselines** `baseline_coverage` and `baseline_reference`, scored like tools;
  leaderboard columns `is_baseline` and `beats_best_baseline`.
- **Probability calibration** for probability-exposing tools: Brier score, expected
  calibration error and a reliability table/diagram.
- HTML report sections **Baselines and calibration**, **Interpretation limits** and
  **Metadata completeness**; `benchmark.metadata_completeness.tsv`.
- `docs/FAQ_QUESTION_BANK.md` answers the 108-question reviewer bank.

### Fixed
- The run manifest now records every ranking-relevant setting added by recent releases.
- A duplicate `PLASMID_REFERENCE_SKETCH` default ignored `DATA_DIR`.
### Cohort and database data
- **`public-v3` panel** (98 isolates, locked): `public-v2` plus recorded truth provenance
  and 66 new long-read-first isolates, one per BioProject, across six species. All rows
  verified online; `accepted_accessions.tsv` regenerated; CI checks the v3 lock.
- `config/tool_database_releases.tsv`: release dates verified from each installed or pinned
  database's own record (MOB-suite DB v2.0.0 2020-05-04, Platon DB v1.5.0 2020-10-05,
  geNomad DB v1.9 2025-02-18, PlaScope 2018-07-13, RFPlasmid 0.0.18 models 2021-07-28);
  uninstalled databases left blank with the reason.
- New `python/collect_truth_provenance.py` and `python/discover_design_cohort.py`; the
  assembler pattern now tolerates NCBI's "Trycyler" misspelling.
### Added -- further benchmark dimensions (advisory; none changes the leaderboard)
- `python/alignment_accuracy.py`: nucleotide identity, mismatch, insertion and deletion rates decoded from the alignment CIGAR,
  and missing-region counts; `python/mask_accuracy.py` blanks the rates where the truth was polished with the benchmark's own
  reads (the same rule as the CPRR identity criterion). SNP concordance is not computed (no variant truth exists).
- `python/feature_preservation.py`: full-length, truncated and missed recovery per feature kind, and NGOC (gene or
  landmark-order conservation, strand and circularity aware), by projecting truth features through the alignments.
- `python/bin_quality.py`: high and medium quality-bin yield, homogeneity, completeness and V-measure, as secondary diagnostics.
- `python/performance_summary.py`: success rate, resource failures, runtime, memory, thread-seconds per recovered plasmid,
  CPU utilisation and scaling exponents. Stage 4 now records user and system CPU seconds beside peak memory.
- `python/power_analysis.py`, `python/scenario_tags.py`, `python/compare_runs.py`, and an optional gated composite with weight
  sensitivity (`python/composite_score.py`, `config/composite_weights.tsv`). The composite never changes the leaderboard.
- `python/stratify_recovery.py` also stratifies by size band and resistance-gene carriage and reports median and IQR;
  `python/audit_truth_labels.py` screens truth labels against replicon and MOB evidence; `plasbench derive-amr-truth`,
  `plasbench audit-truth-labels` and `plasbench analysis <name>` expose the standalone scripts.
- The HTML report gains sections for each of the above, with explicit empty states. `RUN_DIMENSION_ANALYSES=0` skips them.
- Tests: `test_alignment_accuracy.py`, `test_mask_accuracy.py`, `test_feature_preservation.py`, `test_bin_quality.py`,
  `test_performance_summary.py`, `test_power_analysis.py`, `test_scenario_tags.py`, `test_composite_score.py`,
  `test_compare_runs.py`, `test_audit_truth_labels.py`, `test_scoring_controls.py`, `test_scoring_real_minimap2.py`,
  `test_stratify_multilabel.py`, `test_script_wiring.py`, `test_demo_end_to_end.py`, `test_stage_dimensions.sh`.
- Docs: `FAQ.md` (evidence-backed answers, and the reviewer question bank answered section by section),
  `docs/REVIEW_TRACKER.tsv`, a METHODS section for the new dimensions, and the README metric-framework and roadmap section.
- CI installs minimap2 so the real-aligner golden test runs.

### Changed (breaking, experimental output only)
- **The Mash nearest-reference screen no longer claims novelty.** Its calls were renamed
  because they promised more than a Mash distance to 16 plasmids can show:
  `known_cluster` is now `close_reference_match`, `novel` is now `no_close_reference`, and
  the `confidence_score` column is now `distance_margin` (a linear margin to an uncalibrated
  threshold, not a probability). `plasmid_similarity.tsv` gains `mash_p_value` and
  `shared_hashes`. The default threshold is unchanged, but its documentation no longer calls
  it "roughly ANI >= 95%": for plasmids, two equal-size sequences sharing about 35% of their
  k-mers already reach it, and an exact piece under about 21% of a reference falls outside it.
  Anything that read the old labels or column must be updated. The feature remains off by
  default and unvalidated.
- **`make_truth.py` no longer guesses CHROMOSOME for a sequence it cannot label.** Such
  sequences are written as `REVIEW`, which `validate_truth_table.py` rejects, so stage 2 stops
  instead of silently biasing precision and recall. This now also covers location types other
  than Plasmid/Chromosome and reports that contradict themselves. `ALLOW_DEFAULTED_TRUTH=1`
  (or `--allow-default`) restores the old behaviour.
- A skipped tool run (command not installed, database missing, no assembly graph) no longer
  counts as a failure in the operational recommendation's `failure_rate`; it already lowers
  coverage, which gates eligibility.

### Added
- **`docs/SCIENTIFIC_GUIDE.md`**, a guide for domain experts: what PlasBench does, how and why,
  its scope, every metric and statistical procedure, the shipped cohorts, outputs and how to read
  them, reproducibility, how each kind of expert can check the claims, what has and has not been
  validated, and a scope matrix. It has a table of contents, a README section with its own
  contents list, and `python/build_guide_toc.py` keeps both in step with the headings.
  `test/test_guide_docs.py` checks the contents, every link, and that every configuration
  variable, command and `scores.tsv` column the guide names still exists in the code.
- `run_manifest.json` now lists selected candidates for a benchmark run. It looked only for the
  operational layout (`<sample>/selected_candidate/`), so an ordinary benchmark run listed none.
- `n_failed_resource` and `n_unknown_overlap` leaderboard columns; `--resource-failures
  {score-zero,exclude}` and `--tool-capabilities` on `aggregate_results.py`.
- A failed tool run's exit code is recorded in `tool_status.tsv`'s reason column
  (`exit_code=<n>`; the file's header is unchanged). Exit 124/137 is classed as a resource
  failure.
- The HTML report now shows the nearest-reference screen result in each sample's selection card,
  with its experimental caveat and support (p-value, shared hashes); reports from before the
  rename still display.
- `python/rank_sensitivity.py` and `benchmark.rank_robustness.tsv`: per-track sensitivity of the
  ranking to alignment filters (re-scored from the PAFs on disk) and to the metric (strict F1,
  per-plasmid recovery), with Kendall's tau and whether the top tool changes. Run from stage 6;
  `RUN_RANK_SENSITIVITY=0` skips it. It does not change the leaderboard.
- A leaderboard warning (stderr and the Markdown leaderboard) and a clearer HTML cell when the
  database-overlap screen could not judge any pair because `database_release_date` is blank.
- Tests: `test_scoring_adversarial.py`, `test_aggregate_failures.py`,
  `test_selection_undefined_metrics.py`, `test_study_groups.py`, `test_leakage_visibility.py`,
  `test_classifier_semantics.py`, `test_report_classifier_section.py`, `test_rank_sensitivity.py`, `test_failed_tool_exit_code.sh`.
### Changed -- research design (headline endpoints and reference standard)
- **Primary endpoint is now length-weighted binning F1** for binning-capable tools
  (`lw_bin_f1`, ungated Hungarian match; the count-based `bin_f1` is kept but not
  ranked). **CPRR** (Correct Plasmid Reconstruction Rate) is the secondary endpoint,
  with pre-specified `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE`/`CPRR_MIN_IDENTITY`.
  Classifier-only tools are ranked on a separate classification track by
  base-level F1. Leaderboards add `task`, `ranking_metric`, `ranking_score` (+ CI),
  `ranking_species_basis`, `cprr` (+ CI) and `mean_lw_bin_f1`.
- **Reference standard.** `truth_provenance.py` classifies how each truth was built
  (long-read-first vs short-read-first; polished with the benchmark's own reads or
  not) and assigns reference tiers 1-3. Short-read-first and unknown-provenance truth
  (tier 3) leave the headline and become a sensitivity analysis; the CPRR identity
  criterion is dropped for truth polished with the benchmark's reads.
- **Evidence-based truth labels.** `label_truth_evidence.py` confirms each replicon
  with plasmid markers, rRNA genes (new barrnap caller) and long-read support;
  conflicting replicons (chromids, marker-free or short-read-only plasmids) are
  AMBIGUOUS and excluded from scoring via `truth.scored.tsv`. Self-built truth is no
  longer labelled by size alone.
- **Species balance.** The ranking score averages per-species means over species with
  >= `MIN_SPECIES_CLUSTERS` independent clusters; clusters join shared BioProjects and
  clonal groups (`clonal_groups.py`), and CIs/permutation tests resample whole
  clusters within species. New `benchmark.species.tsv`,
  `benchmark.reference_tiers.tsv`, `benchmark.headline_design.tsv`.
- `validate_cohort.py` prints advisory composition warnings (species count, dominant
  species, species below the minimum) and validates the new optional sheet columns
  `truth_assembly_strategy`, `truth_polish_reads` and `clonal_group`.
- HTML report: leaderboards per task with ranking score, CI and CPRR; new "Headline
  design and reference standard" section with provenance, tiers, species balance and
  a tier-sensitivity chart.

### Fixed
- `benchmark.species.tsv` now lists a tool that failed on every sample (mean 0 over the plasmid-bearing
  samples), as the leaderboard already did. `species_table` called `shared_values` without the failed-only tool,
  so the two outputs disagreed. The tool list passed in comes from the same (track, task) group, so failures of
  other groups' tools are not counted.
- **A tool that failed on every sample no longer vanishes from the leaderboard.** It now ranks
  last with F1 = 0 on every plasmid-bearing sample, in its own track.
- Equal mean F1 now ranks by tool name instead of by row order in `scores.tsv`, which made the
  "runner-up" in the significance test arbitrary.
- The operational recommendation no longer averages an undefined F1, precision or recall (an
  isolate with no true plasmid) as 0.0.
- Leave-one-study-out validation no longer silently drops samples with a blank `source_study`:
  they join the study of any sample sharing their bioproject, else use the bioproject, and
  samples with neither are reported.
- The mash query sketch now uses the same sketch size as the reference (it used Mash's default
  of 1000 against a 10000-hash reference), and mash's p-value and shared-hash count are no
  longer discarded; a close but statistically unsupported hit is no longer a match.
- `make_truth.py`: the version-less accession fallback is no longer order-dependent, and a
  `chr_name` shared by several records no longer silently resolves to the last one.
- The scorer ignores secondary alignment rows (`tp:A:S`) in a supplied PAF and warns.
- `scorable_truth.py` reads truth with the scorer's own validation.
- Removed `write_track_leaderboards`, which nothing called.
- **Empty predictions no longer inflate mean F1.** On an isolate with true
  plasmid, a tool that predicts nothing now scores F1 = 0 (precision stays
  empty). Previously F1 was left empty and the sample was dropped from the
  tool's mean, so a tool that abstained on hard isolates could tie a perfect one.
- **Tools are ranked on the same samples.** `mean_f1`, its CI and median now use
  only samples shared by every ranked tool in the track; a failed tool run
  (`tool_status.tsv`) on a plasmid-bearing sample counts as F1 = 0 for that tool,
  in both the ranking and the paired comparisons. New leaderboard columns:
  `analysis_track`, `n_ranking_samples`, `ranking_basis`, `mean_f1_all_scored`,
  `n_f1_scored`, `n_failures_scored_zero`.
- **The combined leaderboard no longer ranks across input tracks.**
  `benchmark.leaderboard.tsv/.md` now hold each track's table ranked within that
  track, and `benchmark.paired_comparisons.tsv` only compares tools within a
  track (new `analysis_track` column). Previously the combined file ranked
  short-read, long-read and hybrid tools against each other.
- `make_truth.py` no longer claims that defaulting an unclassified sequence to
  CHROMOSOME "only ever creates false negatives": if it is really a plasmid, correct
  plasmid calls on it are scored as false positives. Its warnings now say so, and
  the plasmid-free note no longer suggests excluding negative-control isolates.
- The HTML report no longer says failed tool runs are excluded from F1 aggregation
  or never become zero scores; it now describes the failure-as-zero ranking rule.
- METHODS.md now states that `unmapped_pred_bp` includes predicted sequence whose
  alignments were all removed by the alignment filters, so it lowers neither
  precision nor F1.

### Added
- **Cluster-aware statistics.** Bootstrap CIs and paired permutation tests resample
  whole BioProject clusters (sample-sheet `bioproject`, else `source_study`), so
  same-study isolates are not counted as independent. New columns
  `n_independent_clusters` (leaderboard) and `paired_clusters` (comparisons).
  Unchanged results when no cluster column is present.
- **Recall-ceiling diagnostic** (`python/scorable_truth.py`, stage 5, on by default):
  `scorable_plasmid_bp`, `recall_ceiling` and `ceiling_adjusted_recall` show how much
  plasmid sequence (shared repeats, duplicate plasmids) no prediction can be credited
  for under the alignment filters. Config: `RUN_SCORABLE_TRUTH`,
  `SCORABLE_WINDOW_BP`, `SCORABLE_STEP_BP`.
- **Strict precision** (`strict_precision`, `mean_strict_precision`): also charges
  unmapped and filter-rejected predicted bases. Supplementary, never ranking.
- **Reference-database overlap screen** (`python/flag_database_overlap.py`, stage 6,
  `config/tool_database_releases.tsv`): flags truth genomes public before a tool's
  database; leaderboard adds `n_possible_db_overlap`, `n_after_database`,
  `mean_f1_after_database`; `EXCLUDE_DATABASE_OVERLAP=1` drops flagged rows before
  ranking. Stage 1 now keeps `assembly_data_report.jsonl` for the release date.
- **HTML report "Robustness diagnostics" section** with a table and three charts
  (recall vs ceiling, precision vs strict precision, F1 vs F1 after database);
  the leaderboard shows the shared-sample basis and the comparisons table shows
  cluster counts.
- `redundant_pred_bp` score column: reference bases claimed more than once by
  retained alignments (e.g. duplicate predicted records). Diagnostic only; it never
  changes TP, FP or F1.

## [0.1.5] - 2026-09-10

### Added

- Optional operational-mode novel-vs-known plasmid classification
  (`RUN_PLASMID_NOVELTY_CLASSIFICATION`, `python/classify_operational_plasmid.py`,
  `python/build_plasmid_reference_set.py`): Mash distance from a truth-unknown
  isolate's own reconstructed candidate to a small, curated reference plasmid
  set, independently reimplementing santirdnd/COPLA's own known-cluster-or-
  novel pattern with PlasBench's existing Mash dependency rather than COPLA's
  code or its `graph-tool`/nested-SBM machinery. Off by default -- a purely
  supplementary, operational-only signal never wired into
  `recommendation_model.py`'s training features, since a genuinely unknown
  isolate has no truth reference, the entire reason this signal exists.
  - `python/build_plasmid_reference_set.py` builds the reference Mash sketch
    and metadata once from a committed, curated accession list
    (`cohorts/reference_plasmids/curated_accessions.tsv`, 16 real NCBI
    plasmids spanning *E. coli*, *Salmonella enterica*, *Klebsiella
    pneumoniae*, *Acinetobacter baumannii*, and *Staphylococcus aureus*, each
    with a one-line provenance justification). The built sketch/metadata are
    real downloaded data, not tracked metadata, so -- the same convention as
    `PLATON_DB`/`GENOMAD_DB`/`PLASME_DB` -- they live under `DATA_DIR/db`,
    gitignored.
  - `python/classify_operational_plasmid.py` calls the built-in `mash dist`
    against that sketch and calls `known_cluster` when the nearest reference
    is within `PLASMID_NOVELTY_SIMILARITY_THRESHOLD` (default Mash distance
    0.05, roughly ANI >= 95%) AND that reference's cluster has at least
    `PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS` members (default 2); otherwise
    `novel`. A missing `mash` binary or reference set gives
    `insufficient_reference`, never a guess.
  - Wired into `scripts/08_operational_reconstruct.sh` (`plasbench
    reconstruct`); results land in `results/<sample>/plasmid_similarity.tsv`
    and under `plasmid_novelty` in `selection_report.json`. A failed or
    skipped classification never blocks reconstruction or the rest of the
    report -- it is supplementary, not a gate.
  - See `docs/OPERATIONAL_SELECTION.md`'s new "Novel-vs-known plasmid
    classification" section for the full usage walkthrough.

### Changed

- **Relicensed from MIT to the GNU General Public License, version 3
  (GPL-3.0-only)**, effective from this point forward. Releases v0.1.0
  through v0.1.4 remain published under the MIT License as distributed;
  this change is not retroactive. See `LICENSE`, `NOTICE`, and
  `CITATION.cff`.

### Documentation

- Recorded the two real, permanent Zenodo dataset DOIs minted by the
  existing `zenodo-upload.yml` workflow when the v0.1.3/v0.1.4 GitHub
  Releases were created during the v0.1.x renumbering
  ([10.5281/zenodo.22671309](https://doi.org/10.5281/zenodo.22671309),
  [10.5281/zenodo.22671314](https://doi.org/10.5281/zenodo.22671314)), in
  both release notes and `cohorts/README.md`, per `docs/RELEASING.md`'s own
  instruction. These are dataset-only DOIs (the archived `cohorts/*.tsv`),
  not a software citation.

### Removed

- **PyPI publishing.** `.github/workflows/release.yml`'s `pypa/gh-action-pypi-publish`
  step (and the now-unused `python -m build` step that only fed it) failed on
  every real attempt with `invalid-publisher` -- the trusted-publisher
  registration on PyPI's side never actually matched this workflow, and
  `plasbench` was never reachable at pypi.org/project/plasbench despite
  `continue-on-error` making every release job show green. A step that
  always fails silently is worse than no step: it lets a broken channel look
  configured. The GitHub Release archive remains the Python-package
  distribution; see `RELEASING.md` for how to re-add PyPI later with a
  verified trusted publisher.

## [0.1.4] - 2026-09-08

Supersedes the removed v0.2.5-v0.2.8 tags.

### Added

- A separately executable metagenomic community/bin scoring route:
  `plasbench metagenomics`, or `plasbench run --mode metagenomics`.
- Strict community manifests, three-class plasmid/chromosome/virus truth,
  normalized graph/bin tables, global one-to-one bin matching, split/merge
  and contamination diagnostics, a run manifest, and
  `metagenomics.report.html`.
- A metagenomics installer profile for the tested baseline runtime
  dependencies (`metaSPAdes` through SPAdes and geNomad).
- An auditable optional orthogonal-validation evidence validator for
  long-read, hybrid, PCR, plasmid-extraction, conjugation, Hi-C, and
  optical-mapping records. Evidence is preserved separately and cannot
  inflate a score.
- Public cohort release and governance standards, including two-reviewer,
  conflict-of-interest, versioning, representation, and annual-refresh
  rules.
- An `amr_context` decision profile that treats curated AMR-gene recovery,
  plasmid recovery, bin quality, and structural penalties as co-primary;
  it safely falls back when an AMR truth table is unavailable.
- A deterministic, offline metagenomic demonstration fixture covering bin
  recovery, merge and contamination trade-offs, three-class classifier
  calls, uncertainty, and non-scoring mobilome evidence.
- An auditable tool-installer registry covering every supported, non-demo
  adapter, with `plasbench install-tools list`, `plan`, and `validate`
  modes.
- An external-benchmark importer that preserves source data, checksums, and
  truth-definition boundaries instead of mixing external scores into native
  PlasBench results.
- A candidate-quality dataset builder for downstream research only.
  Aggregate tool scores are explicitly not converted into fabricated bin
  labels.
- Strict reference-recovery-rate metrics and nested-validation model cards.
- A complete user-facing release guide (`docs/RELEASES.md`), a reusable
  GitHub Release template, and version-specific release notes under
  `docs/releases/`.

### Changed

- Refreshed public project identity to **PlasBench: A Reproducible,
  Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction
  Tools** with the tagline *Benchmarking plasmid reconstruction from
  sequence to biological function.* The stable `plasbench` command is
  unchanged.
- The isolate and metagenomic HTML reports now carry the updated project
  identity, plus auto-sized reconstruction dashboard frames, balanced
  evidence panels, run labels, and a clearer heatmap/report handoff.
- Installation guidance defaults to the verified latest-release installer
  and separates normal laboratory use from recovery and troubleshooting.
- The CLI reports a clear recovery command when launched outside a
  PlasBench project directory.

### Fixed

- Reject duplicate or malformed BMock12 gold-standard memberships, fail
  clearly when truth-backed metagenomic scoring receives no normalized
  predictions, and safely escape cohort metadata embedded in a
  self-contained HTML dashboard.

### Safeguards

- Metagenomic and isolate reports/rankings are structurally separated.
  Candidate bins are never represented as host assignments, circular
  closure, or clinical confirmation without independent evidence.
- `gplas2` remains source-runtime-only until its upstream runtime and
  classifier provenance can be installed reproducibly. It is deliberately
  not misrepresented as a one-command package installation.

## [0.1.3] - 2026-09-07

Supersedes the removed v0.2.0-v0.2.4 tags. Nothing here is on by default --
an existing cohort run behaves exactly as before unless a new flag is
switched on.

### Added

- Three long-read/hybrid tools: `hybracter_long`, `hybracter_hybrid`, and
  `trycycler_mob_recon`, a second independent long-read assembly path
  alongside Flye+MOB-Recon and Plassembler (assembler choice materially
  affects plasmid completeness on ONT data). Hybracter reuses the
  Plassembler database.
- Three opt-in ML classifiers, all short-read-track contig classifiers, not
  binners: `genomad` (gene-based neural classifier), `plasme` (alignment +
  transformer hybrid), `plasgraph2` (GNN over assembly-graph nodes).
- A new `pr_auc` metric: where an adapter publishes a candidates universe
  plus per-record probabilities, scoring sweeps every distinct probability
  as a threshold and reports the area under the precision-recall curve.
  Ranking stays on `mean_f1`; PR-AUC is supplementary.
- A read-quality ladder, the long-read analog of the depth ladder, with
  combined length+quality `--rungs` cutoffs.
- A leave-one-study-out decision-support model and multi-track
  recommendation support.
- `./update.sh` / `plasbench upgrade` for one-command version upgrades that
  reuse shared data across releases, plus a latest-release bootstrap
  installer.

### Changed

- Each tool is now scored under its own declared `analysis_track`
  (`config/tool_capabilities.tsv`), so one run correctly scores short-read,
  long-read, and hybrid tools together instead of applying one global track
  to every tool. Stage 7 (long-read reconstruction) is now part of the
  default stage list, before scoring.
- **The circularity guard (truth independence from long reads) now applies
  to all five long-read/hybrid tools**, including retroactively to
  `flye_mob_recon`, which had no guard before. This is a real behavior
  change for existing cohorts: a sample lacking
  `truth_independent_of_long_reads=yes` is now correctly **skipped** where
  it previously ran; each tool has a `<TOOL>_ALLOW_CIRCULAR_TRUTH=1`
  override.
- `docs/COHORTS.md`/`docs/METHODS.md` now name all five guarded tools with
  their override variables, instead of the two they listed before.

### Fixed

- CI no longer lets a failed PyPI publish block the GHCR image/GitHub
  Release.
- An upgrade no longer re-fetches shared data it should reuse.

## [0.1.2] - 2026-09-05

Supersedes the removed v0.1.6-v0.1.9 tags.

### Added

- `plasbench init-local`, staging a user's own FASTQ reads and reference
  into the pipeline, writing the truth table and sample-sheet row.
  Unlabelled sequences are written as `REVIEW`, never guessed.
- Two input validators that run before any tool starts: staged reads
  (missing/empty/not actually gzipped, mates out of order) and the truth
  table (unmatched ids, unlabelled sequences, bad `molecule_type`, tabs vs.
  spaces, length mismatches).
- Cohort download-size estimation and confirmation before fetching.
- Plassembler support on the long-read/hybrid track, with a circularity
  guard.

### Changed

- `THREADS`/`MEMORY_GB` now default to 80% of the detected machine's
  cores/RAM (floor 2 GB) instead of a fixed value.
- Databases are checked for presence before being re-downloaded; a partial
  download is reported as **incomplete**, never mistaken for a working
  install. Re-downloading is opt-in via `--force`.

### Fixed

- A failed download no longer aborts the whole cohort: failures are
  recorded per sample in `results/download_status.tsv` with automatic
  linear-backoff retry (`NETWORK_RETRIES`, default 3); the stage aborts
  only when every sample fails.
- Two parallelism tests now assert that work genuinely overlaps, measured
  from the stubbed tools' own process logs, rather than comparing elapsed
  time.

## [0.1.1] - 2026-09-04

Supersedes the removed v0.1.1-v0.1.5 tags.

### Added

- The packaged install-archive distribution
  (`plasbench-<version>.tar.gz` + `.tar.gz.sha256`, installed with
  `./install.sh --tools`).
- Three Galaxy tool wrappers (align/score/aggregate) with a real bioconda
  recipe and `plasbench-score`/`plasbench-aggregate` PATH entry points.

### Fixed

- Release archives no longer ship CRLF line endings, which previously made
  `plasbench test` die with `set: pipefail: invalid option name`.
- The `public-v2` cohort lock was regenerated against LF content and
  re-verified online against NCBI (32/32 pairs).
- `plasbench run` with no stage numbers no longer exits 2 on Python <=
  3.12. `install.sh` now bootstraps Miniforge itself when no conda is
  present.
- A micromamba prefix-resolution bug that aborted `plasbench install-tools`
  with "No prefix found" against a working install. `install-tools all` no
  longer pulls the incompatible bioconda `gplas` package; the explicit
  `gplas` profile now warns and points at gplas2 instead.
- **Install-critical**: `env/setup_conda.sh` no longer destroys an existing
  environment (including MOB-suite's 450 MB database) when re-run against a
  working install -- an existing environment is detected and updated in
  place, non-destructively.

## [0.1.0] - 2026-09-01

Initial public release: the verified `public-v1` cohort, a reproducible
environment lock, capability-aware scoring metrics, and the depth-ladder
workflow.

## Release Reading Guide

- **GitHub Release assets** are the checksum-verified source distribution for
  terminal installations. There is no PyPI package (removed; see "Unreleased"
  above) -- external bioinformatics tools and databases are installed
  separately through the documented installer routes regardless.
- **GHCR** supplies the container image. Use an immutable version tag such as
  `ghcr.io/ubeffiong/plasbench:v0.1.5` for reproducible work, not `latest`.
- **Run manifests and cohort locks** are required companions when reporting or
  comparing scientific results; a software version alone is insufficient.
