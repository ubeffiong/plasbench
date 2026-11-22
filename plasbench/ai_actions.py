"""What the AI help may propose to run, and the checks that stand between a proposal and a command.

The model's reply can contain action blocks: a fenced block whose language is `pb-action` holding one JSON object
    {"cmd": "plasbench status", "where": "window", "why": "one sentence", "risk": "safe"}
This module only READS such a block and decides what the window may offer for it. It never runs anything. Running is a separate, deliberate step that goes through the
window's existing path: the person clicks Run in PlasBench, sees the exact command in the consent dialog, and the command is started by Jobs.start with an argument list
(no shell), after ui_schema.validate_argv has parsed it with the real parser. This module's own rules are stricter than that parser and exist so that text which came from
a model (and, through retrieved documents or command output, possibly from an attacker) cannot smuggle in more than one plain `plasbench` command:

  * the line must be one `plasbench` command: no shell operators (; & | < > ` $ ( ) { } \\ # newline), no environment assignment, no other program;
  * no absolute path, home path (~), parent folder (..) or --project-root: only the study and project folders are reachable;
  * the sub-command must exist in the real parser and must not be one that starts a window, a server, or a shutdown (ui, stop --all, ...);
  * a command that installs, upgrades, stops or removes is marked `needs_extra_confirm` (the window asks once more, in words);
  * `where` other than window/terminal is never runnable here (PowerShell, WSL and host commands are shown with Copy only).

`redact_output` is what a finished command's output goes through before the person may send it to the assistant. Standard library only.
"""
from __future__ import annotations

import getpass
import json
import re
import shlex
from pathlib import Path

from . import issue_report, ui_schema

WHERE = ("window", "terminal", "powershell", "wsl", "host")
RISKS = ("safe", "changes_files", "destructive")
MAX_CMD = 400
MAX_ACTIONS = 4
MAX_ASKS = 1          # one clarifying question per reply
ASK_OPTIONS = 5
ASK_TEXT = 220
ASK_OPTION_TEXT = 70
SHELL_CHARS = re.compile(r"[;&|<>`$(){}\\#\r\n\t!*?\[\]]")
ABS_PATH = re.compile(r"^(?:/|~|[A-Za-z]:[\\/]|\\\\)")
# Commands that open a window or a server, or end this one, are not started from the assistant: the person runs them from the terminal.
NEVER_IN_WINDOW = frozenset(["ui", "desktop-icon", "picker-check", "install-git", "ask", "ai", "docs", "concept-note"])
SAFE_COMMANDS = frozenset(["status", "diagnose", "profile-run", "ui-state", "issue-report", "net", "open-report", "check-results", "validate-cohort", "validate-orthogonal-evidence",
                           "validate-meta-intake", "selection-report", "compare-published", "scan-isolates", "check"])
INSTALL_SUBS = {"tools": {"install", "remove", "add", "new"}, "runtime": {"pull", "build", "use", "test"}}


def _risk_rank(r: str) -> int:
    return RISKS.index(r) if r in RISKS else 1


def parse_command(cmd: str):
    """(argv, problem): argv is the list after `plasbench` when the line is one plain plasbench command, else None and a short reason."""
    cmd = (cmd or "").strip()
    if not cmd:
        return None, "the command is empty"
    if len(cmd) > MAX_CMD:
        return None, "the command is too long"
    bad = SHELL_CHARS.search(cmd)
    if bad:
        ch = bad.group(0)
        shown = {"\n": "a line break", "\r": "a line break", "\t": "a tab", "\\": "a backslash"}.get(ch, repr(ch))
        return None, f"it contains {shown}: only one plain plasbench command is run from here (no pipes, redirects, chained commands, variables or quoting tricks)"
    odd = next((ch for ch in cmd if not (ch == " " or "!" <= ch <= "~")), None)
    if odd is not None:     # a lookalike letter (Cyrillic a), a zero-width or direction-changing character, a non-breaking space: it can look like `plasbench status` and not be it
        return None, "it contains a character that is not plain ASCII (U+%04X): a lookalike or invisible character can hide what a command really is" % ord(odd)
    if "&&" in cmd or "||" in cmd:
        return None, "it chains commands"
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        return None, "its quotes do not match"
    if not parts or parts[0] != "plasbench":
        return None, "it is not a plasbench command (only `plasbench ...` can be run from here; other commands are for your own terminal)"
    argv = parts[1:]
    if not argv or argv[0].startswith("-"):
        return None, "it names no plasbench command"
    for tok in argv:
        if "=" in tok and not tok.startswith("-") and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            return None, "it sets an environment variable"
        if ABS_PATH.match(tok) or any(p == ".." for p in re.split(r"[\\/]", tok)):
            return None, "it uses an absolute or parent-folder path (use a path inside the study or project folder)"
        opt, _, value = tok.partition("=")
        if opt == "--project-root" or (value and (ABS_PATH.match(value) or ".." in re.split(r"[\\/]", value))):
            return None, "it points outside the project folder"
    return argv, ""


def _first_positionals(argv: list) -> list:
    return [a for a in argv[1:] if not a.startswith("-")]


def classify(argv: list) -> dict:
    """{"risk", "needs_extra_confirm", "why_extra"} from the command itself (the model's own risk label can only raise this, never lower it)."""
    cmd, rest = argv[0], argv[1:]
    pos = _first_positionals(argv)
    risk, extra, why = "changes_files", False, ""
    if cmd in SAFE_COMMANDS and "--yes" not in rest:
        risk = "safe"
    if cmd == "stop":
        risk, extra, why = "destructive", True, "stops running benchmarks (and, with --all, every PlasBench window server)"
    elif cmd == "upgrade" and "--check-only" not in rest:
        risk, extra, why = "destructive", True, "replaces the PlasBench files with a new version"
    elif cmd in ("install-tools", "install-conda") and "--dry-run" not in rest and not (pos and pos[0] in ("plan", "list", "validate", "locked")):
        risk, extra, why = "destructive", True, "downloads and installs software on this computer"
    elif cmd in INSTALL_SUBS and pos and pos[0] in INSTALL_SUBS[cmd]:
        risk, extra, why = "destructive", True, "installs, builds, switches or removes tools or images"
    elif cmd == "check" and "--yes" in rest:
        risk, extra, why = "destructive", True, "installs the tools and databases that are missing"
    if "--wsl-shutdown" in rest:
        risk, extra, why = "destructive", True, "shuts down WSL, which ends everything running in it"
    return {"risk": risk, "needs_extra_confirm": extra, "why_extra": why}


def validate(cmd: str, where: str = "window", risk: str = "") -> dict:
    """What the window may do for one proposed command line.

    {"ok": the line is one valid plasbench command, "runnable": the window may offer Run in PlasBench, "argv", "risk", "needs_extra_confirm", "why_extra",
     "reason": why not (empty when runnable), "where": the (checked) place}."""
    where = where.strip().lower() if isinstance(where, str) and where.strip().lower() in WHERE else "host"    # an unknown place is never runnable here
    out = {"cmd": (cmd or "").strip(), "where": where, "ok": False, "runnable": False, "argv": None, "risk": risk if risk in RISKS else "safe",
           "needs_extra_confirm": False, "why_extra": "", "reason": ""}
    argv, problem = parse_command(cmd)
    if argv is None:
        out["reason"] = problem
        return out
    ok, message = ui_schema.validate_argv(argv)
    if not ok:
        out["reason"] = f"plasbench does not accept it ({message})"
        return out
    out["ok"], out["argv"] = True, argv
    info = classify(argv)
    out["risk"] = max(info["risk"], out["risk"], key=_risk_rank)
    out["needs_extra_confirm"], out["why_extra"] = info["needs_extra_confirm"], info["why_extra"]
    rest = argv[1:]
    if where not in ("window", "terminal"):
        out["reason"] = {"powershell": "it belongs in Windows PowerShell, outside this window", "wsl": "it belongs in your Ubuntu (WSL) terminal, outside this window",
                         "host": "it belongs in a terminal on this computer, outside this window"}[where]
    elif argv[0] in NEVER_IN_WINDOW:
        out["reason"] = f"`plasbench {argv[0]}` is not started from the assistant; run it yourself in a terminal"
    elif argv[0] == "stop" and (set(rest) & {"--all", "--windows", "--wsl-shutdown"} or "--runs" not in rest):
        out["reason"] = "this stop would end this window or WSL; run it yourself in a terminal (only `plasbench stop --runs` can be started from here)"
    elif "--watch" in rest:
        out["reason"] = "--watch never ends; run it in your own terminal (or leave --watch out)"
    else:
        out["runnable"] = True
    return out


# One run of blanks only: `[ \t]*(tag)?[ \t]*` was quadratic on a long run of spaces (60,000 spaces took 36 s), so a reply could freeze the window's thread.
_BLOCK = re.compile(r"```(?:[ \t]*(pb[-_ ]?action|pb[-_ ]?ask|pb[-_ ]?ui|pb[-_ ]?files|json|js|javascript)[ \t]*)?\r?\n(.*?)(?:```|\Z)", re.S | re.I)
MAX_BLOCK = 60000     # a block longer than this is never read as a proposal (it stays plain text)
MAX_REPLY = 400000    # the part of a reply that is searched for blocks
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _first_object(text: str):
    """The first balanced {...} in the text (commentary after it is ignored), or None."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def lenient_json(text: str):
    """The object in a block that a small model wrote: smart quotes, trailing commas, text after the object, an unclosed fence are tolerated. Returns a dict or None.

    This only reads the SHAPE of the proposal. What the command may be is decided by validate(), which is not lenient at all."""
    if len(text or "") > MAX_BLOCK:
        return None
    raw = _first_object((text or "").replace("“", '"').replace("”", '"').replace("’", "'"))
    if raw is None:
        return None
    for candidate in (raw, _TRAILING_COMMA.sub(r"\1", raw)):
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except (ValueError, RecursionError):
            pass
    try:                                         # a Python-style object with single quotes
        import ast
        obj = ast.literal_eval(_TRAILING_COMMA.sub(r"\1", raw))
        return obj if isinstance(obj, dict) else None
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def clean_ask(obj):
    """A clarifying question the model wants to put to the person: {"q": text, "options": [short answers]}, or None. Plain text only (the page escapes it), at most ASK_OPTIONS
    options, each short; it can never become a command: choosing an option only sends that text as the person's next message."""
    if not isinstance(obj, dict) or not isinstance(obj.get("q"), str) or not obj["q"].strip():
        return None
    options = []
    for raw in obj.get("options") if isinstance(obj.get("options"), list) else []:
        text = re.sub(r"\s+", " ", str(raw)).strip()[:ASK_OPTION_TEXT]
        if text and text not in options:
            options.append(text)
        if len(options) >= ASK_OPTIONS:
            break
    return {"q": re.sub(r"\s+", " ", obj["q"]).strip()[:ASK_TEXT], "options": options}


def clean_files(obj):
    """A file plan the model proposes: {"ops": [...], "why": text} with at most 40 plain-JSON operations, or None. The plan is only SHAPED here; the folder grant, the closed
    operation set and the sheet checks are applied by plasbench/ai_files.py when the person looks at it (the dry run), and again when the person presses Apply."""
    if not isinstance(obj, dict) or not isinstance(obj.get("ops"), list) or not obj["ops"] or len(obj["ops"]) > 40:
        return None
    if not all(isinstance(o, dict) and isinstance(o.get("op"), str) for o in obj["ops"]):
        return None
    try:
        if len(json.dumps(obj["ops"])) > 48000:
            return None
    except (TypeError, ValueError):
        return None
    return {"ops": obj["ops"], "why": re.sub(r"\s+", " ", str(obj.get("why") or "")).strip()[:240]}


def parse_reply(reply: str, project=None) -> dict:
    """{"text": the reply without the blocks that were read as proposals, "actions": [validated commands], "asks": [question], "ui": [window actions], "files": [file plans]}.

    A block is an action when it is a ```pb-action fence (or a ```json fence that has "cmd", "where" and "why") holding an object with a string "cmd". A block that cannot be read
    stays in the text as a plain code block and never becomes a proposal. At most MAX_ACTIONS commands, MAX_UI window actions and one file plan are taken. Only text the MODEL wrote
    is passed here: retrieved excerpts, command output and folder content are never parsed for proposals, and the prompt builder defuses any such fence in them."""
    from . import ai_ui
    reply = (reply or "")[:MAX_REPLY]
    actions, asks, uis, files, pieces, last = [], [], [], [], [], 0
    for m in _BLOCK.finditer(reply):
        tag = re.sub(r"[-_ ]", "", (m.group(1) or "").lower())
        obj = lenient_json(m.group(2)) if tag else None
        take = False
        if tag == "pbui" and isinstance(obj, dict):
            if len(uis) < ai_ui.MAX_UI:
                uis.append(ai_ui.validate(obj, project))
            take = True
        elif tag == "pbfiles" and isinstance(obj, dict):
            plan = clean_files(obj)
            if plan and not files:
                files.append(plan)
            take = plan is not None
        elif isinstance(obj, dict) and "q" in obj and "cmd" not in obj and (tag == "pbask" or "options" in obj):
            ask = clean_ask(obj)
            if ask:                      # a valid question is always taken out of the text; only the first one is kept
                if len(asks) < MAX_ASKS:
                    asks.append(ask)
                take = True
        elif isinstance(obj, dict) and isinstance(obj.get("cmd"), str) and (tag.startswith("pb") or ("where" in obj and "why" in obj)) and len(actions) < MAX_ACTIONS:
            v = validate(obj["cmd"], str(obj.get("where") or "terminal"), str(obj.get("risk") or ""))
            v["why"] = str(obj.get("why") or "")[:240]
            actions.append(v)
            take = True
        if take:
            pieces.append(reply[last:m.start()])
            last = m.end()
    pieces.append(reply[last:])
    return {"text": re.sub(r"\n{3,}", "\n\n", "".join(pieces)).strip(), "actions": actions, "asks": asks, "ui": uis, "files": files}


def extract_actions(reply: str) -> list:
    return parse_reply(reply)["actions"]


def strip_action_blocks(text: str) -> str:
    return parse_reply(text)["text"]


# --------------------------------------------------------------------------------------------------------------------------------- redaction
_WIN_USERS = re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)[^\\/\s\"']+")
_SK = re.compile(r"sk-or-[A-Za-z0-9_-]{8,}")


def redact_output(text: str, tail_lines: int = 40, max_chars: int = 6000, home=None, user=None, hostname=None) -> str:
    """The last `tail_lines` lines of command output with the home folder, user name, e-mail addresses, tokens and keys, and IP addresses removed (idempotent)."""
    home = str(home) if home else str(Path.home())
    try:
        user = user or getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name known: the home-folder forms are still removed
        user = ""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [l[:400] for l in lines][-max(1, int(tail_lines)):]
    out = "\n".join(lines)
    out = _SK.sub("<hidden>", out)
    out = issue_report.redact(out, home, user, hostname)
    out = _WIN_USERS.sub(r"\1<user>", out)
    out = _SK.sub("<hidden>", out)
    return out[-max_chars:]
