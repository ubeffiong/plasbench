# AI help

PlasBench has an assistant in the side panel of the window (the **AI help** tab, the **AI help** button in the top bar, or Alt+Shift+H) and on the command line (`plasbench ask`). It answers questions about PlasBench from PlasBench's own guides, suggests the exact command to run, tells you where to run it, and can run a safe command for you after you press a button and confirm it. It never runs anything by itself.

## What the assistant can and cannot see

**The assistant cannot see your files.** It has no access to your FASTQ or FASTA files, sample sheets, results, logs, reports, databases or settings, and it does not know what is on your computer. It knows PlasBench's documentation, a short non-personal setup line (version, system type, WSL or not, conda or Docker, the stage or failure the window knows about) and what you type or choose to send with **Send result** (redacted). It cannot check, open or analyse your data: to diagnose something it suggests a command, you run it, and you send the output. This is said in the first-use notice, in a line that stays under the chat, in `plasbench ask`, and to the model itself.

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

Measured on the 51 realistic questions of `test/fixtures/ai_gold.tsv` (install, Docker, WSL, commands, inputs, metrics, workflow, troubleshooting, exit codes, misspellings and error strings such as "You need approx 5.2 GB of free RAM" and "Could not open lockfile"): the right source is among the top three excerpts for all of them (the set of acceptable sources per question was widened after reading the misses: before that, 29 of 51 had the first-choice source in the top three). The average prompt is about 1,570 tokens (largest 1,830) without conversation history; the fixed instructions are about 410 of them.

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

Install [Ollama](https://ollama.com) or LM Studio, load a model, and open the AI help tab: the provider switch then offers *This computer*. Nothing is sent anywhere. Small local models follow instructions less reliably, so the assistant's commands pass the same strict checks as always.

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

The system prompt is about 480 tokens and identical on every call (it was 410 before it learned to say it cannot see files, to ask a clarifying question and to use marked general knowledge). The excerpts are cut at sentence ends to about 1,400 tokens, deduplicated, with at most two per section. Only the last six turns are kept and each long turn is cut. Answers may use up to 2,000 tokens (600 with **Brief**); the assistant is told to be terse, and an answer that still reaches the model's length limit shows a **Continue** button. The pane shows the tokens of the last answer (from the provider's `usage`), today's requests and tokens, and, on OpenRouter, how many free requests are left today. PlasBench puts no daily limit of its own on the AI help: `AI_DAILY_TOKEN_CAP` defaults to 0 (none) and is there only if you want to set one. The providers' own limits (for example OpenRouter's free-model requests per minute and per day) still apply and are reported in plain words. Prompt caching: providers such as OpenAI and Gemini cache prefixes of 1,024 tokens or more automatically; this stable prefix is shorter than that, so expect little caching from it.

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
