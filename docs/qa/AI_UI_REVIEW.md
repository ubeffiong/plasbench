# AI help: UI review (headless Edge)

Run: `PLASBENCH_BROWSER_TESTS=1 PB_SHOTS=<folder> python test/test_ai_ui_review.py` (Edge through the DevTools protocol, a real window server, the local stub provider of `test/ai_stub.py`). The checks that need no browser run in CI (`test/test_ai_pane_logic.py`: the Markdown renderer and every card against an XSS corpus, in a bare node VM). The browser test is opt-in.

Reviewed on 21 November 2026 with Microsoft Edge on Windows 11. Not covered: Firefox, Safari, a screen reader, real touch, a real sign-in pop-up in this run (the earlier `test_ai_ui_browser.py` covers the pop-up against the stub), the native folder picker (the folder is granted through the same route its callback uses).

## Findings and fixes

| Finding | Severity | Fix | Check |
| --- | --- | --- | --- |
| A streamed answer whose connection ended without a finish was shown as complete (silent truncation) | High | The server marks it `cut`; the page also notices a stream with no `done`; both show the Continue button | `test_ai_hardening.py`, page logic |
| With the new folder bar and quick chips the chat area shrank to about 170 px and the composer disappeared below the fold at 320 x 640 | High | The four starter buttons are hidden once there is a message, the quick chips become a single scrolling row, the log's minimum height is 96 px | `at 320 x 640 the composer ... is inside the visible window` |
| After Undo, the form-prefill card pointed at a sheet that no longer existed | Low | The card says `Not filled: ... does not exist` instead of filling a dead path (correct behaviour, kept; the test now fills before undoing) | the prefill check |
| Re-rendering the log replaces the DOM (a text selection in an old answer is lost when a new message arrives; thumbs do the same) | Low | Not fixed: the log is re-drawn by design to keep one delegated listener; scroll position is kept when the reader is near the bottom | the scroll check below |
| A hostile name in a card (script, handler, javascript: link, quotes, bidi) | none found | Every card text goes through `esc()`; a strict tag and attribute reader checks 31 payloads in 10 renderers | `test_ai_pane_logic.py` |

## Checks run in the browser (all passed in the final run)

| Area | Check | Result |
| --- | --- | --- |
| first use | the notice states the folder rule and that a summary goes only on Share | pass |
| first use | the composer, folder bar and quick actions are hidden until the notice is accepted | pass |
| sign-in | the local provider needs no sign-in: the pane opens | pass |
| pane | the declaration line under the chat names the Share rule | pass |
| pane | five quick-action chips are shown | pass |
| pane | the folder bar offers Choose a folder (the native picker is not driven here) | pass |
| grant | the chip shows only the folder's own name, with Revoke | pass |
| setup flow | it asks for a study name in a dialog | pass |
| setup flow | a scan card shows what PlasBench found (read only), with problems | pass |
| setup flow | a file plan card lists the operations with check boxes, nothing applied yet | pass |
| setup flow | nothing has been written yet | pass |
| setup flow | the share summary is shown in full, exactly, before anything is sent | pass |
| setup flow | a form-prefill card follows (Nothing is started) | pass |
| apply | Apply asks for confirmation and lists what it will do | pass |
| apply | the plan is applied and an Undo button appears | pass |
| prefill | the New benchmark form is filled in and nothing was started | pass |
| undo | Undo restores the folder and says so | pass |
| sheet fix | the plan shows a diff and flags the sample-id change | pass |
| window actions | a setting card shows old -> new, and a refused one says why | pass |
| navigation card | Go there opens the page with one click | pass |
| model path | pb-ui and pb-files blocks in a streamed answer become cards | pass |
| model path | the raw fences are not left in the text | pass |
| model path | Review the plan runs the server's dry run before any Apply | pass |
| share | Share shows the exact text in a confirmation, and sends nothing until Share is pressed | pass |
| share | the shared answer arrives | pass |
| ui review | no uncaught page error so far | pass |
| ui review | the log is a polite live region with a name; the status line is a separate status region | pass |
| ui review | every button in the pane has an accessible name | pass |
| ui review | every form control in the pane has a name | pass |
| ui review | touch targets: chips and buttons are at least 24 px high | pass |
| ui review | text contrast is at least 4.5:1 in the light theme (measured above) | pass |
| ui review | text contrast is at least 4.5:1 in the dark theme (measured above) | pass |
| ui review | Tab from the composer reaches the next control (no keyboard trap) | pass |
| ui review | a card's button is activated by keyboard: Enter on a focused quick chip starts the flow | pass |
| ui review | a double click on Go there does not break the page | pass |
| ui review | very long unbroken text and 40 cards do not widen the pane or the page | pass |
| ui review | 30 re-renders of a heavy chat take under 3 s (1384 ms) | pass |
| ui review | the pane adds no per-card listeners (one delegated click handler) | pass |
| ui review | at 200% zoom (750 css px) the composer and chips are usable and nothing overflows | pass |
| ui review | at 320 px the pane itself does not overflow horizontally | pass |
| ui review | at 320 x 640 the composer (where the question is typed) is inside the visible window | pass |
| ui review | with reduced motion, no animation or transition longer than 0.01 s runs in the pane | pass |
| ui review | in forced-colours mode the chips and cards keep a visible border | pass |
| ui review | when the user has scrolled up, a streaming answer does not pull the view down | pass |
| ui review | reloading during a stream leaves the window working (the pane opens again) | pass |
| ui review | closing the drawer closes the pane (and it can be opened again by button and by Alt+Shift+H) | pass |
| ui review | no uncaught page error during the whole pass | pass |

Measured contrast ratios (text colour against its effective background; WCAG AA needs 4.5:1 for normal text): light theme 5.0 to 16.2, dark theme 5.6 to 12.8, for the quick chips, declaration line, user messages, card text, buttons, footer, folder chip and risk labels.

Page-wide horizontal overflow at 320 px with the pane open: 0 px (the existing 390 px page-wide scroll was not reproduced with the pane open in this run).

## Not checked or only partly

- Screen readers: roles and names are present (`role=log`, a separate `role=status`, names on every control) and were checked by script, not by listening.
- The live region announces only `The assistant is answering` and `finished`, never the streamed text; this was read from the code, not measured with a reader.
- Focus: a keyboard Tab from the composer moves on (no trap) and the dialogs use the window's existing modal helper (focus returns to the opener); closing the drawer by Escape in every state was not scripted.
- Sign-in pop-up blocked, cancelled, closed early and two clicks: covered by the earlier `test_ai_ui_browser.py` for the success path only; blocked and cancelled states are not driven in a headless browser.
- 200% zoom was emulated as 750 css px at device scale 2, not a real browser zoom. Touch targets were measured by height (at least 24 px), not by touch.
- Memory and listener leaks over a very long chat were checked only as: 30 re-renders of a 2-message chat holding 40 cards and very long text finish in under 3 s and no per-card listener exists.

## Screenshots

- `docs/qa/ai_ui/02-folder-chip.png`
- `docs/qa/ai_ui/04-scan-card.png`
- `docs/qa/ai_ui/05-file-plan-preview.png`
- `docs/qa/ai_ui/07-applied-undo.png`
- `docs/qa/ai_ui/08-wizard-prefilled.png`
- `docs/qa/ai_ui/09-sheet-fix-diff.png`
- `docs/qa/ai_ui/10-window-action-cards.png`
- `docs/qa/ai_ui/11-model-proposals.png`
- `docs/qa/ai_ui/12-share-confirm.png`
- `docs/qa/ai_ui/13-dark.png`
- `docs/qa/ai_ui/16-320px.png`
