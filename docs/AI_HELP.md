# AI help

PlasBench has an assistant in its own right-hand drawer of the window (the **AI help** button in the top bar, or Alt+Shift+H; it takes the place of the side panel with Studies, Jobs and Git, and **Panel** brings that back) and on the command line (`plasbench ask`). It answers questions about PlasBench from PlasBench's own guides, suggests the exact command to run, tells you where to run it, and can run a safe command for you after you press a button and confirm it. It never runs anything by itself.

## Where it is, and how the pane is laid out

The **AI help** button in the top bar (or Alt+Shift+H) opens the AI help as its own drawer on the right, in the place of the side panel (Studies, Jobs, Git): one drawer at a time. **Panel** brings the side panel back, and the AI help button again brings the AI help back. Hiding a drawer never clears it: the conversation, a half-typed question, the scroll position, the chosen folder, the cards and an answer that is still arriving are all kept, and a dot on the AI help button says that something arrived while it was hidden. Escape or the close button closes the AI drawer and returns to the button. The window remembers which drawer was open.

The pane keeps one place for each fact:

* The top line has the provider and the model, **Brief** and **Remember chats** (each with an (i) that says what it does and costs: Brief caps an answer at 600 tokens instead of 2,000; Remember chats keeps the last 30 messages in this browser's local storage, nowhere else), and **New chat**.
* **Quick actions** is one fold-out: open on an empty chat, folded once the conversation has started (it then remembers whether you opened or closed it). It holds **Choose a folder** (its **remember** option is in the ⋯ next to it) or the chosen folder's chip with **Look inside** and **Revoke**, and the guided flows. The chosen folder's name is also shown on the fold-out's own line.
* Under each answer, **Sources (n)** is one folded line that opens to the list of sources with their full titles (a source cited twice is listed once with both numbers); the [n] markers in the answer are small buttons whose label is the full title and which open the source. The model, the tokens and whether it was free are in the answer's (i), next to the two votes.
* A command card is unchanged: **Suggested command**, the risk badge, the command, where to run it, why, and **Run in PlasBench**, **Copy**, **Open Terminal tab** (a test pins it).
* The promise "The assistant can't see your files" is one line with an (i) holding the full sentence; the footer shows the free/local badge and one small usage indicator ("48 left", or "3 today" when the provider gives no free-request figure); its (i) holds the three lines it replaces: today's requests and tokens, the last answer's tokens in and out, and the free requests left of the daily limit (left out when not known, never guessed). At 5 or fewer free requests left the indicator itself turns amber with the number, and red when none are left.
* Every (i) opens on hover, on keyboard focus and on tap, and Escape closes it; every fold-out is a real `<details>`.

## What the assistant can and cannot see

**The assistant never opens your files.** If you choose a folder, PlasBench itself reads names, sizes and the first lines on your computer and shows you what it found; a summary goes to the assistant only when you press Share. Without that, it has no access to your FASTQ or FASTA files, sample sheets, results, logs, reports, databases or settings, and it does not know what is on your computer. It knows PlasBench's documentation, a short non-personal setup line (version, system type, WSL or not, conda or Docker, the stage or failure the window knows about) and what you type or choose to send (**Send result**, redacted; **Share**, a summary you have read). It cannot run anything without your click. This is said in the first-use notice, in a line that stays under the chat, in `plasbench ask`, and to the model itself.

**It can ask you questions.** When a missing fact decides the answer (your system, whether you use Docker or conda, the stage, the exact error text, which file) it asks one short question and shows quick-reply buttons; a button only sends that text as your next message, it never runs anything. You can also type your own answer.

**General knowledge.** For questions closely related to PlasBench (plasmids, sequencing, resistance genes, conda, Docker, WSL, reading results) the assistant may use the knowledge of its model and its own judgement. Those parts begin with "General knowledge:" and can be wrong, so check anything important; facts about PlasBench itself (commands, options, settings, metrics) come only from the documentation, and it is told never to invent a PlasBench command or option. Unrelated topics are declined.

## What it knows, and how it answers

The assistant does not answer from a model's memory. For every question PlasBench first searches a small index of its own material and sends only the best three to five excerpts (about 1,400 tokens) with the question:

- the guides: README, FAQ, INSTALL, SUPPORT, SECURITY, `docs/USER_GUIDE.md`, `docs/METHODS.md`, `docs/SCIENTIFIC_GUIDE.md`, `docs/METAGENOMICS.md`, `docs/ADDING_TOOLS.md`, `docs/INPUT_GUIDE.md`, `docs/FINDING_DATA.md`, `docs/COHORTS.md`, `docs/RESOURCE_ADAPTATION.md`, `docs/TOOL_INSTALL_AUDIT.md`, `docs/publishing/README.md` and this page;
- the workflow and pipeline stages 0 to 8 with their switches (`config/workflow_steps.tsv`), the tool table (`config/tool_capabilities.tsv`) and every Setting with its default and comment (`config/config.sh`);
- the metric and window help texts, and the whole command line, built from the real parser so that it cannot drift from the program;
- the failure signatures (`config/resource_signatures.tsv`, the Docker and assembler diagnosis rules) and the exit codes.

The index is a single file shipped inside the package (`plasbench/data/ai_kb.json.gz`), built by `python python/build_ai_kb.py`; a test fails when it is out of date with its sources. Ranking is BM25 with small boosts for an exact command or option, an error message quoted from a log, a few synonyms ("stuck", "stalled", "hang") and a nearest-word match for misspellings. No service, embedding or network is involved in finding the excerpts.

The answer cites the excerpts as small chips under it; a chip opens the guide section on the Guides page. If the excerpts do not answer a question about PlasBench itself (its commands, options, settings, metrics) the assistant is told to say "not in the documentation" and point to `plasbench issue-report`, not to guess.

(Measured before the hardening pass.) Measured on the 51 realistic questions of `test/fixtures/ai_gold.tsv` (install, Docker, WSL, commands, inputs, metrics, workflow, troubleshooting, exit codes, misspellings and error strings such as "You need approx 5.2 GB of free RAM" and "Could not open lockfile"): the right source is among the top three excerpts for all of them (the set of acceptable sources per question was widened after reading the misses: before that, 29 of 51 had the first-choice source in the top three). The average prompt is about 1,570 tokens (largest 1,830) without conversation history; the fixed instructions are about 410 of them.

## Providers

The pane has a provider switch that shows only the providers that are configured.

| Provider | Cost | Sign-in | Notes |
| --- | --- | --- | --- |
| **OpenRouter** (default) | Free models only | A pop-up window (OAuth with PKCE); no key is pasted | Only models whose price fields in OpenRouter's live list are all zero are offered or called. Routers such as `openrouter/auto` and `openrouter/free` are never used, because a router can pick a paid model. |
| **Hugging Face** | Models marked free by the router's own list; with `AI_HF_USE_CREDITS=1` also cheap models that spend your own Hugging Face credits | A pop-up window (public OAuth app, PKCE, no client secret), once the owner has registered the app | Off until `AI_HF_CLIENT_ID` is set; pasting a token still works without it. |
| **This computer** (Ollama, LM Studio) | Free, no account | None | Nothing leaves the computer. Found by listing `http://localhost:11434/v1/models` or `http://localhost:1234/v1/models`; set `AI_LOCAL_BASE` to use another address. Only loopback addresses are used unless `AI_LOCAL_ALLOW_REMOTE=1`. |

The default provider is OpenRouter when you are signed in to it, otherwise a local server when one is found, otherwise the sign-in choices.

### OpenRouter free models: what was checked

From OpenRouter's documentation (21 November 2026): free models have ids ending in `:free`; free usage is limited to 20 requests a minute and 50 requests a day, or 1000 a day once at least 10 credits have ever been bought; a 429 carries `X-RateLimit-*` and sometimes `Retry-After`; `GET /api/v1/key` reports `free_model_daily_requests`; a negative credit balance can make even free models fail; the pages do not say whether an account or key is required for `:free` models, but every call needs a bearer key and PlasBench asks you to sign in. The documentation says prompts are not logged by default, and that providers that log or train are used only if you allow it in your OpenRouter privacy settings; it does not say how free models in particular are handled. Read the model's page before you send anything you consider sensitive. A fallback to a paid model is billed by OpenRouter, so PlasBench never lists one: its fallback goes to the next free model, and only when "try another free model on limits" (`AI_FREE_FALLBACK`, on by default) allows it.

The default model is the best-suited free model in the live list: an instruction-tuned model with a long context window (at least 32k) and no reasoning switched on by default, so that the answer budget is not spent on hidden reasoning. When the list was read on 21 November 2026 that was `google/gemma-4-31b-it:free` (262k context). Choose another from the picker, or with `AI_MODEL`. If the model list cannot be read, a short built-in list of `:free` ids is shown marked as possibly out of date.

### Hugging Face: registering the app

Hugging Face signs users in with OAuth; a public app (no client secret) works with the authorization-code flow and PKCE. The owner of the PlasBench installation registers one app at <https://huggingface.co/settings/applications/new>, chooses *without a secret*, adds the scope `inference-api`, and registers the redirect address `http://localhost/ai/hf/callback` (Hugging Face accepts any port for a registered port-less `http://localhost/...` address; also register `http://127.0.0.1/ai/hf/callback` if you open the window by that address). Then set `AI_HF_CLIENT_ID` to the app's client id. A client id is an identifier, not a secret. PlasBench stores the signed-in token on the computer of the person who signed in, never in the project.

What Hugging Face's pricing page says (checked 21 November 2026): free accounts have **no** included credits (PRO accounts include $2.00 a month) and use is pay-as-you-go beyond that. So a Hugging Face account without credits can use only the models the router lists at price zero, and a 402 answer is shown as "no credits" with the billing link. Which account an OAuth token's calls are charged to is not stated outright on the pages read; the scope description says the token makes requests "on behalf of the user".

### A model on this computer

Install [Ollama](https://ollama.com) or LM Studio, load a model, and open the AI help: the provider switch then offers *This computer*. Nothing is sent anywhere. Small local models follow instructions less reliably, so the assistant's commands pass the same strict checks as always.

### Providers considered

A provider qualifies only if it offers **native OAuth**: sign-in in a small pop-up window opened from PlasBench that returns to PlasBench by itself (authorization code with PKCE, redirect to this window's server), with no secret key in the project, no code or key to copy and paste, no embedded browser or iframe, and a free allowance for the user. (The "paste my own key" box is an advanced fallback, not the main path.) The table comes from public pages checked on 21 November 2026 and may change.

| Provider | Built? | Reason |
| --- | --- | --- |
| OpenRouter | Yes | Pop-up PKCE, no client secret or registration, free `:free` models. |
| Hugging Face | Yes | Public OAuth app with PKCE (client id only); pricing page lists no free credits for free accounts, so only price-zero models are used by default. |
| Ollama and LM Studio (local) | Yes | No sign-in needed, free, nothing leaves the computer. |
| GitHub Models | No | GitHub's documentation says "As of July 30, 2026, GitHub Models has been fully retired", including the inference API. GitHub's device flow would also make you type a code on another site, which fails the criterion. |
| Google AI Studio / Gemini | No | Its OAuth needs a Google client and restricted-scope verification; Google sign-in was dropped from this project. |
| Qwen | No | The only OAuth is the device flow of the Qwen Code command-line tool with that tool's own client id; reusing another product's client id would be unauthorised, and no third-party app registration is documented. |
| MiniMax | No | Device-code sign-in is reported only by third-party tools and tied to a paid plan; no standing free allowance or third-party app registration is documented. |
| Parallel (parallel.ai) | No | An API-key product (free credits need a card) with no documented OAuth sign-in. |
| "OpenBYO" | No | No such provider was found (the closest, `byokey`, is a local proxy for subscriptions). The paste-a-key option already covers bring-your-own-key. |
| Puter.js | No | Its user-pays model needs a remote script loaded into the window's own page, which holds the window's session key; that is unacceptable unless sandboxed. |
| Groq, Mistral, Cerebras, Cloudflare, NVIDIA, Cohere | No | API-key products without third-party OAuth sign-in. |
| Pollinations | No | An anonymous service with no stated terms or reliability. |

## Signing in

**Sign up / Sign in** opens a small window (about 520 by 720 pixels) from the click itself. In it you sign up or sign in to the provider and approve PlasBench; the window closes by itself and the pane switches to signed in. The PlasBench window is never navigated away and no tab is opened. If your browser blocks the window, the pane says so: allow pop-ups for this page and press *Try again*. If you close the window without finishing, the pane says "Sign-in cancelled".

How it is made safe: the window server starts the sign-in and keeps a random `state` and the PKCE verifier for ten minutes; the provider redirects the pop-up to `http://localhost:<port>/ai/openrouter/callback` (or `/ai/hf/callback`) with a one-time code; the server checks the state (it works once, only for that provider, only within ten minutes), exchanges the code with the verifier, and stores the key. The callback page is static: it reflects nothing from the address, and tells the opener with `postMessage` to one fixed origin (the page also polls the server, so it works even if the message does not arrive). The callback uses `localhost` because OpenRouter's documentation names localhost callbacks on any port and does not mention `127.0.0.1`.

Under *Advanced* you can paste your own key instead. **Sign out** deletes the stored key.

## What is sent, and where your key lives

Sent to the provider: your question, the excerpts found for it, the last few turns of the chat, and a short setup line (PlasBench version, system type, WSL or not, conda or Docker, the stage or the failure the window knows). Command output is sent only when you press **Send result**, and the window shows you the redacted text first. Never sent: file names and folder paths, your user name or e-mail address, accession lists or your data, any key. Nothing is sent when the page loads or in the background, and nothing before you have read the notice and pressed *I understand* (once per provider).

The key or token is stored in `~/.plasbench/ai/<provider>.json` (mode 0600, folder 0700 where the system supports it). It is never returned to the page, written to a log, a manifest, a job's environment or an issue report, or included in an error message. The log `~/.plasbench/ui/ai.log` holds counts and status codes only. Deleting the folder `~/.plasbench/ai` removes everything; you can also revoke the key or the app at the provider.

## The tokens it uses

The system prompt is about 540 tokens (budget: 560) and identical on every call (410 at first, 480 with the declaration and clarifying questions, 538 with the folder-summary rule and the limits rule). The action formats (window actions, file plans) are not in it: they come by retrieval from `docs/AI_CAPABILITIES.md`, as one extra excerpt, only when the question looks like navigation, setup, a file task or a question about what the assistant can do. The excerpts are cut at sentence ends to about 1,400 tokens, deduplicated, with at most two per section. Only the last six turns are kept and each long turn is cut. Answers may use up to 2,000 tokens (600 with **Brief**); the assistant is told to be terse, and an answer that still reaches the model's length limit shows a **Continue** button. The pane shows the tokens of the last answer (from the provider's `usage`), today's requests and tokens, and, on OpenRouter, how many free requests are left today. PlasBench puts no daily limit of its own on the AI help: `AI_DAILY_TOKEN_CAP` defaults to 0 (none) and is there only if you want to set one. The providers' own limits (for example OpenRouter's free-model requests per minute and per day) still apply and are reported in plain words. Prompt caching: providers such as OpenAI and Gemini cache prefixes of 1,024 tokens or more automatically; this stable prefix is shorter than that, so expect little caching from it.

## Commands the assistant suggests

A command appears as a card: the command in a box, a line "Run it here: ..." (PlasBench's Terminal tab, Windows PowerShell (not inside Ubuntu), your Ubuntu (WSL) terminal, or a terminal on this computer), why, a risk label, and buttons.

- **Run in PlasBench** appears only when the server's checks pass. It opens the same consent dialog as every other command, with the exact command; nothing runs before you press Run. Commands that install, upgrade or stop get one more confirmation in words.
- **Copy** and **Open Terminal tab** (types the command into the Terminal tab; you press Enter).
- When the checks fail the card says "Not runnable here" with the reason, and only Copy is offered.
- **Send result to the assistant** appears after a run ends; it shows the last 40 lines with your folder names, user name, e-mail addresses, keys and IP addresses removed, and sends only when you press Send.

The checks (`plasbench/ai_actions.py`): one plain `plasbench` command; no pipes, redirects, chaining, variables, backticks, quotes tricks, environment assignment, other programs, absolute or parent paths or `--project-root`; the sub-command must exist and its options must parse with the real parser (`ui_schema.validate_argv`); `ui`, `docs`, `ask`, `ai`, `desktop-icon` and `stop` other than `stop --runs` are never started from the assistant; `--watch` is not started; the model's risk label can raise the risk but never lower it; the command is started by the Jobs machinery with an argument list, never a shell. Text in retrieved excerpts or in command output is data: the prompt defuses any action fence in it, and only the model's own reply is read for actions. A small model's format slips (a missing closing fence, a trailing comma, single quotes, text after the JSON) are tolerated when the shape is clear; anything else is shown as plain text and never becomes a button.

## Settings

`AI_HELP_ENABLED` (default 1; 0 hides the pane and refuses its requests), `AI_PROVIDER`, `AI_MODEL`, `AI_DAILY_TOKEN_CAP`, `AI_BRIEF`, `AI_FREE_FALLBACK`, `AI_HF_CLIENT_ID`, `AI_HF_USE_CREDITS`, `AI_LOCAL_BASE`, `AI_LOCAL_ALLOW_REMOTE`, and `AI_OPENROUTER_BASE`, `AI_HF_BASE`, `AI_HF_HUB`, which replace the service addresses for tests and for a self-hosted gateway that speaks the same API (the key is sent to that address, so set them only to a service you trust). All are documented in `config/config.sh`.

## On the command line

`plasbench ask "your question"` prints the answer, its sources and the proposed commands (never run) with where to run each; `--provider`, `--model`, `--brief`, `--json`; the first use prints the notice and needs `--accept-notice`. Exit codes: 0 answered; 1 the service refused or failed (no credits, limit, outage); 2 not ready (not signed in, notice not accepted, AI help off, a model that is not free); 3 no internet. `plasbench ai status` shows where you are signed in; `plasbench ai signout` deletes the key. Sign in once in the window.

## Troubleshooting

- *The sign-in window does not open*: allow pop-ups for the page, then press *Try again*.
- *The sign-in finished but the pane did not change*: press the tab again; the pane also polls the server.
- *"Free models are rate-limited"*: wait, or pick another free model; with `AI_FREE_FALLBACK=1` the next free model is tried by itself.
- *"No credits"*: Hugging Face free accounts have no credits; use a model marked free, or add credits. On OpenRouter a negative balance can block even free models.
- *"Cannot load models"*: the provider's list could not be read (offline, proxy); the built-in list, if shown, may be out of date.
- *"The daily token limit is reached"*: you set `AI_DAILY_TOKEN_CAP` yourself; set it to 0 to remove it. (By default there is none.)
- *Nothing is sent and the pane says it is off*: `AI_HELP_ENABLED` is 0.

## What was verified, and what was not

Verified by tests against local stand-ins for OpenRouter, Hugging Face and an Ollama-style server (`test/ai_stub.py`): the PKCE vector of RFC 7636, the one-time state, the callback page, key storage and its absence from every response, log and report, the free-only rule (paid models, routers and a model that turned paid are never offered or called), streaming with usage, the error mapping, the fallback, abort, the routes' token, Host and origin checks, the command checks and the prompt-injection cases, redaction, the knowledge index, and the page in a real browser (Edge, headless: the pop-up that opens, redirects back and closes itself, a streamed answer, an action card, the consent dialog before a run, Send result, escaping, phone width). **Not verified here**: a real sign-in at OpenRouter or Hugging Face, a real model's answer, real free-tier limits and any cost; the provider documentation was read on 21 November 2026.

## Threat model

Assets: the provider key or token (`~/.plasbench/ai/*.json`); the window's session token; the person's files; the person's trust in what a card says it will do.

Attackers and what stops them:

| Attacker | What it can try | Guard | Test |
| --- | --- | --- | --- |
| A malicious or confused model | A command with shell text, a lookalike command (Cyrillic or zero-width letters), a plan that deletes or leaves the folder, a setting that raises its own privileges, a reply made to hang the parser | Commands are checked by `ai_actions.validate` (plain ASCII only, one `plasbench` command, real parser); window actions by an allowlist (`ai_ui.py`); plans by a closed operation set and the folder grant; `AI_*`, secret, path and scoring-decision settings are never settable; the block pattern is linear (it was quadratic: 60,000 spaces took 36 s); blocks over 60 KB stay plain text | `test_ai_window_actions.py`, `test_ai_files.py`, `test_ai_actions.py` |
| Prompt injection through retrieved documents, command output or folder content | A pb-action fence in a document, a FASTA header or a sheet cell | Only the model's own reply is parsed for blocks; every quoted source is defused (`defuse`, `ai_folder.clean`) and wrapped as data (`<doc>`, `<out>`, `<dir>`); a proposal still needs validation and a click | `test_ai_actions.py`, `test_ai_folder.py`, `test_ai_files.py` (hostile names and cells) |
| A hostile web page talking to localhost | Read status or usage, start a sign-in, call a folder route | Every `/api/ai/` route needs the session token (an HttpOnly, SameSite=Strict cookie or header), a loopback Host (DNS rebinding) and, for POST and now GET too, a same-origin Origin | `test_ai_routes.py`, `test_ai_routes2.py` |
| Another local user | Read the key file | Files are created 0600 in a 0700 folder where the system supports it; on Windows the home folder's own ACL applies (not changed here) | `test_ai_providers.py` |
| A malicious `AI_LOCAL_BASE` or other base address | Send the key or the questions to another host | Loopback only unless `AI_LOCAL_ALLOW_REMOTE=1`; the other base settings are documented as "set only to a service you trust" | `test_ai_providers.py` |
| A hostile provider response | An endless line, a 3 MB event, an error inside a 200 stream, a stream that stops without finishing | Lines are capped at 1 MB and a stream at 8 MB; an error object becomes an error with the partial text kept; a stream that ends with no finish reason is marked cut and the pane offers Continue | `test_ai_hardening.py` |
| Hostile folder content | Names or cells with control, bidi or zero-width characters, `..`, device names, links that point outside | `ai_folder.check_name` and `Grant.resolve` (realpath containment, no links or junctions, no hidden or system entries), `clean()` on everything shown or shared | `test_ai_folder.py`, `test_ai_files.py` |

Not defended: a person who is tricked into pressing Apply on a plan whose dry run they did not read; a provider that logs prompts (see the notice); malware already running as the same user.

## Window actions

The model may write one fenced `pb-ui` block (up to 3 per reply). The server validates it (`plasbench/ai_ui.py`, route `ai/ui/validate`, again on every click); the page shows a card and calls the window's existing functions.

| id | What it may do | Risk | Confirmation | Undo | Tests |
| --- | --- | --- | --- | --- | --- |
| `go` | Open a page (home, setup, tools, addtool, prereg, settings, workspace, git, wizard, isolates, cohorts, runs, jobs, commands, help) and a sub-page (runs tabs, a guide name) | safe | none | browser Back | `test_ai_window_actions.py` |
| `setting` | Change one Settings key, only if it is listed in `config/ai_settable.tsv` (key, type, allowed values or range, label, risk: the workflow `RUN_*` and `ANNOTATE_WITH_*` switches, resource settings such as `THREADS`, `MEMORY_GB` and the parallel-job counts, download settings (`READ_DEPTH_CAP_X`, which takes `off` or a depth in x, `ENA_MAX_CONNECTIONS`, `MAX_PARALLEL_DOWNLOADS`, `ENA_CHUNK_MIB`, `ENA_USE_ARIA2`), `READ_SOURCE`, `MULTIQC_REPORT` and similar); a setting that is not listed is refused, so a new setting is refused until someone lists it | changes files | dialog with old and new value | an Undo button restores the old value | same; the never-settable rules stay as a second layer (`AI_*`, key, token, e-mail, path and address settings, scoring decisions: thresholds, `HEADLINE_*`, `CPRR_*`, anything with a range in `config/setting_ranges.tsv`); a value must fit the listed type or range; the test checks that every listed key exists in `config/config.sh` and that unlisted, `AI_*` and `HEADLINE_*` keys are refused. `WORK_DIR` is not listed: it holds a path |
| `prefill` | Fill New benchmark fields (source, cohort, study, max isolates, order, local inputs, a sheet inside the chosen folder) | safe | none; nothing starts | edit the form | same |
| `open` | Open the report, or type a validated command in the Terminal tab | safe | none; Enter still needed | none | same |
| `install` | Start the install dialog for one tool profile | destructive | the existing install dialog | none (remove by hand) | same |
| `runtime` | Switch conda or Docker | changes files | dialog | switch back | same |
| `flow` | Start a guided flow | safe | each step asks | none | same |

## A folder, and file plans

Choose a folder with the pane's **Choose a folder** (the native Browse picker). The grant is per session; the **remember** tick stores it in `~/.plasbench/ai/grants.json`. A chip shows its name and a **Revoke** button. Reads and writes stay inside it (realpath containment; links and junctions, hidden and system entries, `..`, drive and absolute paths, Windows device names, trailing dots and spaces, bidi and zero-width characters are refused).

**Look inside** (`ai_folder.scan`, read only, bounded to 4 levels, 3,000 entries, 12 s, 256 KB per sheet): file types, FASTQ pairs (`_R1/_R2`, `_1/_2`, Illumina lane names) with the first records checked, FASTA record counts and duplicate ids, sheets checked with the stage-0 rules of `scripts/lib.sh` (`validate_sample_sheet`) and the delimiter rule, Excel workbooks reported as unsupported. The result is shown first as a card with the exact text that **Share** would send (about 800 tokens at most, relative names only, nothing absolute, cleaned and marked as data). **Share this summary** shows that text again in a confirmation; only then does it go with your next message, once. The server makes the summary itself; text from the page is ignored.

A file plan (`pb-files`, from the model, or made by the guided flows without one) holds operations from a closed set: `mkdir`, `copy`, `move` (also rename), `write_sheet`, `patch_sheet`. Never: delete, overwrite without a backup, write outside the folder, link, change permissions, run anything, hidden or system files, binary edits; compress and decompress are not offered. The dry run (`ai/files/plan`) lists every operation with its check box, bytes to copy, free space (a margin of 50 MB), collisions (also names that differ only in letter case) and a unified diff for sheets. A sheet repair is offered only when the repaired sheet passes the sheet check; a change to sample ids is flagged and needs a second confirmation. **Apply** re-validates, runs in the background with progress and Cancel, and writes a journal (`~/.plasbench/ai/journal/<id>/journal.json`, plus backups of replaced sheets); a failure or cancel rolls back what was done; **Undo** restores, leaving alone any file that changed since. Rate limits: 10 scans, 30 plan checks, 8 applies, 8 undos and 60 action checks a minute. The audit log `~/.plasbench/ui/ai.log` holds the action id, the outcome and counts, never a name or a path.

## Guided flows (work without a model)

Quick-action chips in the pane, also startable by a `pb-ui` `flow` card (`setup_isolates`, `check_sheet`, `why_failed`, `where_run`, `install_tools`, `add_tool`; the earlier names `setup_run`, `fix_sheet` and `diagnose` still work). *Set up my isolates from a folder* and *Check my sample sheet*: see [Your isolates, through the intake](#your-isolates-through-the-intake). *Why did my run fail?* and *Where is my run?*: see [Troubleshooting a run](#troubleshooting-a-run). A sheet inside the chosen folder can still get the mechanical repairs (tab separator, column names, unsafe ids) as a file plan. *Install the tools I need*: the existing install-enabled dialog. *Add my own tool*: questions, then the manifest that `plasbench tools new` would write (same builder) checked by `plasbench tools validate`'s checks, shown, and saved with the existing save route. *Why did my last run fail?*: the safe `plasbench diagnose` card, then Send result.

## Your isolates, through the intake

*Set up my isolates from a folder* is PlasBench's own intake (`python/intake.py`, the code of `plasbench intake scan|stage|check`), run in the window's server on the folder you chose. It is not a second implementation: the plan comes from `intake.plan_stage`, the planner `plasbench intake stage` itself executes, so the card shows exactly what `plasbench intake stage --dry-run` prints (the card also shows that command), and Stage does exactly that. So the AI route names isolates as the intake does (Illumina lane names, several lanes joined, `_1/_2`, `R1/R2`, `.fq`, the folder name when the read names are generic), compresses uncompressed reads, matches each reference by name, folder or as the only FASTA and says how sure it is, reads the organism from the header, drafts the truth table with `REVIEW` where a header does not say, and runs the intake's checks.

1. **Choose the folder** (the pane's folder chip). Before the intake opens any file, each one is proved to be inside that folder by real path, not a link or junction, not hidden, not a device name; a refused file is listed and never read. A folder over the scan limits (3,000 entries, 12 s) is refused with a plain sentence.
2. **Where the isolates go**, chosen by you from a closed list: PlasBench's data folder (shared by every study), or a study's own data folder (`--keep-data-in-study`). The sheet is `config/<name>.tsv`; the page never sends a path. The destination may not be inside the chosen folder.
3. **The review card**: per isolate the reads found (lanes, compression), the reference and how sure the match is, the organism (editable), the truth status, the warnings with their rule codes, the sample id (editable) and a tick box; the files not used (unmatched FASTA, long reads, single-end reads) and the refused ones; the sample sheet before and after as a diff, checked with the run's own sheet rules (`intake.validate_sheet_text`, stage 0's rules with `REQUIRE_CURATED_METADATA=0`) before Stage is offered.
4. **Questions only you can answer** are asked, never guessed: when two FASTA files could be an isolate's reference the card asks which (it becomes `--reference ID=FILE`); which sequences are plasmids is a form after staging (the `REVIEW` rows; saved by `intake.save_truth`, which refuses an incomplete answer).
5. **Stage**: the server makes the plan again and refuses it if it is not the one you reviewed (a fingerprint of every operation and the sheet). The AI route never replaces a file: an isolate whose files are already in the destination is left out with the reason. An undo journal records every file and folder created and a copy of the sheet; **Undo** removes only files that are unchanged since.
6. **The quick test** (`plasbench intake check`, with the reads-versus-reference comparison) is shown per isolate; **Fix what has one right answer** runs `--fix` (the sheet and truth tables are backed up first); then the `plasbench run --samples config/<name>.tsv --local-inputs` command as a Run-in-PlasBench card. With `--local-inputs` a sheet of your own isolates (no curated columns) no longer needs `REQUIRE_CURATED_METADATA=0` in front.

**Share** sends a summary of the plan (isolate ids, counts, how sure each reference match is, the rule codes; at most about 600 tokens, never a path or file contents), made again by the server.

*Check my sample sheet* runs `plasbench intake check` on a sheet of your own isolates under `config/` (a sheet with a LOCAL or NA row), with the same Fix and labelling; for a sheet inside the chosen folder it offers the mechanical repairs as a file plan.

## Troubleshooting a run

The assistant can also explain the run-speed and robustness settings (`AUTO_PARALLEL`, `ASSEMBLY_SLOT_GB`, the local working copy `WORK_DIR`, `PIPELINE_OVERLAP`, the one retry of an annotation caller, the run profiles) and the console's **Jump to latest** button: they are described in [AI_CAPABILITIES.md](AI_CAPABILITIES.md#speed-and-robustness-parallel-stages-the-local-working-copy-overlap-retries-the-console).

*Where is my run?* reads the latest study with `python/run_status.py` (what `plasbench status` prints) and shows the state, the stage and what that stage does, the isolate and step and for how long, progress, where the time went, and the hints with their figures. No model is involved.

*Why did my run fail?* runs `plasbench diagnose --json` through the usual consent dialog, then builds a digest on the server (`plasbench/ai_diagnose.py`): state, stage, isolate and step; progress; failed assemblies with their cause; the machine figures; the hints; the failed command with its exit code in words; cause codes from PlasBench's own tables (`config/resource_signatures.tsv` through `resource_adapt.classify`, `python/assembler_diagnosis.py`, `python/docker_diagnosis.py`, the intake rules of `python/intake.py`); the evidence lines and the last lines of the failed command's log. It is redacted (home folder, user name, e-mail, keys, IP addresses removed), fences and tags are defused, and it is cut to 700 tokens (about 2,500 characters). The card shows what PlasBench found, the exact text Send would send, **Resume the failed run** (the window's own resume), and the safe next steps as cards: setting changes through the allow-list (`MAX_PARALLEL_SAMPLES`, `THREADS` for memory causes), `plasbench check --yes` for missing tools or databases, `plasbench net` for network causes, a re-run with `--profile fast`, `plasbench status` and `plasbench issue-report`. **Send to the assistant** sends the digest as data (`<out>`), and the system prompt asks for cause, check, fix.

What was not verified: the answers of a real model to these digests and summaries, the flows on real user folders at scale (thousands of isolates), and the native folder picker (driven by the picker's own tests, not here).

## Hardening pass: measured results

Retrieval (`python test/ai_gold_eval.py`): 51 in-sample questions (tuned on) 51/51 at top 3; 67 held-out questions with a source (written before the pass, never tuned on) 61/67 = 91% (61/67 before the pass: unchanged; the new documentation chunks displaced one earlier match); 11 more need no source (general knowledge, off topic, vague). A question whose best excerpt contains little of its words and scores low (an off-topic request) now sends no excerpt; weak tails below 0.3 of the best score are dropped. The average prompt without history is about 1,680 tokens (1,570 before; the permanent prompt grew by about 58 tokens and the indexed material by the capabilities guide). The held-out misses are listed by the script. Real model behaviour with these actions was not measured.

The UI review table is in `docs/qa/AI_UI_REVIEW.md`.
