"""Window actions the AI help may propose (```pb-ui blocks): go somewhere, change a setting, prefill the New-benchmark form, open something, install tools, switch the runtime,
or start a guided flow.

Like every proposal from the assistant these only become a CARD with a plain-language description and a button; nothing happens without a click. The page then calls the window's
EXISTING functions (go(), the settings API, confirmRun, the runtime endpoints): there is no second privileged path. This module only decides whether a proposal is allowed and
describes it; the server runs `validate()` again on every request.

| id        | what it may do                                                         | risk          | confirmation                  | undo                           |
| go        | open an allowlisted page (and sub-page)                               | safe          | none (one click)              | browser Back                   |
| setting   | change one Settings key (never AI_*, secrets, paths, scoring decisions) | changes_files | dialog showing old -> new     | an Undo entry (old value)      |
| prefill   | fill New-benchmark fields, start nothing                              | safe          | none                          | edit the fields                |
| open      | open the report, or type a validated command in the Terminal tab      | safe          | none (the command still needs Enter) | -                       |
| install   | install tools of one known profile                                    | destructive   | the existing install dialog   | plasbench tools remove, by hand|
| runtime   | switch conda or Docker                                                | changes_files | dialog                        | switch back                    |
| flow      | start a guided flow (set up a run, fix a sheet, install, add, why failed) | safe      | each step asks               | -                              |
"""
from __future__ import annotations

import re

from . import ai_actions

VIEWS = ("home", "setup", "tools", "addtool", "prereg", "settings", "workspace", "git", "wizard", "isolates", "cohorts", "runs", "jobs", "commands", "help")
VIEW_NAMES = {"home": "Home", "setup": "Setup", "tools": "Tools", "addtool": "Add a tool", "prereg": "Pre-registration", "settings": "Settings", "workspace": "Workspace and studies",
              "git": "Version control", "wizard": "New benchmark", "isolates": "Your own isolates", "cohorts": "Cohorts", "runs": "Runs", "jobs": "Jobs", "commands": "Commands", "help": "Guides"}
SUBS = {"runs": ("ongoing", "attention", "completed", "all")}
FLOWS = {"setup_run": "Set up a run from my folder", "fix_sheet": "Fix my sample sheet", "install_tools": "Install the tools I need", "add_tool": "Add my own tool", "diagnose": "Why did my last run fail?"}
WIZ_SOURCES = ("demo", "cohort", "sheet", "meta")
STUDY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUNTIMES = ("conda", "docker")
SECRET_WORDS = re.compile(r"KEY|TOKEN|SECRET|PASS|CREDENTIAL|EMAIL|AUTH", re.I)
PATHY = re.compile(r"(_DIR|_PATH|_ROOT|_HOME|_FILE|_URL|_BASE|^PATH$|^HOME$)", re.I)
VALUE_RE = re.compile(r"^[A-Za-z0-9 ._,:+\-]{0,80}$")
UI_IDS = ("go", "setting", "prefill", "open", "install", "runtime", "flow")
MAX_UI = 3


def _bad(reason: str, ui: str = "") -> dict:
    return {"ok": False, "ui": ui, "reason": reason, "title": "", "desc": "", "risk": "safe", "confirm": False, "params": {}}


SCORING = re.compile(r"^(HEADLINE_|CPRR_|PLASBENCH_CI_METHOD|PLASBENCH_DOMINANT_SHARE|ALLOW_PRIMARY_FALLBACK)|THRESHOLD")


def settable(row: dict, ranged=(), listed: bool = False) -> str:
    """"" when a Settings row may be changed by the assistant, else the reason it may not."""
    key = row.get("key", "")
    if key in ranged or SCORING.search(key):
        return "a scoring decision (thresholds and headline rules are pre-specified and must not be tuned): change it yourself on the Settings page"
    if key.startswith("AI_") or key.startswith("PLASBENCH_AI"):
        return "the assistant never changes its own settings"
    if SECRET_WORDS.search(key):
        return "a setting that holds a key, address or credential is never changed from here"
    if PATHY.search(key) or (row.get("computed") and not listed):
        return "a setting that holds a path or address is never changed from here (use the Settings page)"
    default = str(row.get("default") or "")
    if not listed and ("/" in default or "\\" in default or "~" in default or default.startswith("$")):
        return "a setting that holds a path is never changed from here (use the Settings page)"
    return ""


def validate(obj, project=None) -> dict:
    """{"ok","ui","reason","title","desc","risk","confirm","params", ...} for one proposed window action (a dict as the model wrote it)."""
    if not isinstance(obj, dict) or obj.get("ui") not in UI_IDS:
        return _bad("not an allowed window action")
    ui = obj["ui"]
    out = {"ok": True, "ui": ui, "reason": "", "title": "", "desc": "", "risk": "safe", "confirm": False, "params": {}}
    why = str(obj.get("why") or "")[:200]
    if ui == "go":
        target, sub = str(obj.get("target") or ""), str(obj.get("sub") or "")
        if target not in VIEWS:
            return _bad("%s is not a page of this window" % re.sub(r"[^\w -]", "", target)[:30], ui)
        if sub and not ((target in SUBS and sub in SUBS[target]) or (target == "help" and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", sub) and ".." not in sub)):
            return _bad("that sub-page is not available", ui)
        out.update(title="Go to " + VIEW_NAMES[target], desc="Opens the %s page%s. Nothing is changed." % (VIEW_NAMES[target], " (" + sub + ")" if sub else ""), params={"target": target, "sub": sub})
    elif ui == "setting":
        key, value = str(obj.get("key") or ""), obj.get("value")
        value = "" if value is None else ("1" if value is True else "0" if value is False else str(value))
        rows = {r["key"]: r for r in (project.settings() if project is not None else [])}
        row = rows.get(key)
        table = allowed_settings(project)
        if row is None:
            return _bad("%s is not one of PlasBench's settings" % re.sub(r"[^\w]", "", key)[:40], ui)
        entry = table.get(key)
        if entry is None:       # first layer: only what config/ai_settable.tsv lists; a new setting is refused until someone lists it
            return _bad("%s is not on the list of settings the assistant may change (config/ai_settable.tsv); change it yourself on the Settings page" % key, ui)
        refused = settable(row, _ranged(project), listed=True)       # second layer: the never-settable rules
        if refused:
            return _bad(refused, ui)
        if not VALUE_RE.match(value):
            return _bad("the value has characters that are not allowed (letters, digits, space and . _ , : + - only)", ui)
        bad = check_value(entry, value)
        if bad:
            return _bad(bad, ui)
        try:
            project.setting_ranges().validate_changes({key: value}, project.local_env(), project.root)
        except ValueError as exc:
            return _bad(str(exc)[:200], ui)
        old = row.get("override") if row.get("override") is not None else row.get("default")
        out.update(title="Change setting %s" % key, desc="%s (%s): %s -> %s. It is saved for this computer (config/local.env) and can be undone." % (key, entry["label"], old, value),
                   risk="changes_files", confirm=True, params={"key": key, "value": value, "old": "" if old is None else str(old), "had_override": row.get("override") is not None, "level": entry["risk"]})
    elif ui == "prefill":
        f = obj.get("fields")
        if not isinstance(f, dict) or not f:
            return _bad("no fields to fill", ui)
        clean_f = {}
        for k, v in f.items():
            if k == "source" and v in WIZ_SOURCES:
                clean_f[k] = v
            elif k == "study" and isinstance(v, str) and STUDY_RE.match(v):
                clean_f[k] = v
            elif k == "max_isolates" and isinstance(v, (int, str)) and not isinstance(v, bool) and re.fullmatch(r"\d{1,6}", str(v)):
                clean_f[k] = str(v)
            elif k == "isolate_order" and v in ("", "file"):
                clean_f[k] = v
            elif k == "local_inputs" and isinstance(v, bool):
                clean_f[k] = v
            elif k == "cohort" and isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,60}", v):
                names = _cohort_names(project)
                if names is not None and v not in names:
                    return _bad("there is no cohort called %s" % v[:40], ui)
                clean_f[k] = v
            elif k == "samples" and isinstance(v, str):
                try:
                    from . import ai_folder
                    ai_folder.split_rel(v)
                except ValueError as exc:
                    return _bad("the sheet path is refused: %s" % exc, ui)
                clean_f[k] = v          # a path relative to the chosen folder; the server turns it into the real path
            else:
                return _bad("the field %s cannot be filled from here" % re.sub(r"[^\w]", "", str(k))[:30], ui)
        out.update(title="Fill the New benchmark form", desc="Fills %s. Nothing is started: you review the command on the last step." % ", ".join(sorted(clean_f)), params={"fields": clean_f})
    elif ui == "open":
        what = str(obj.get("what") or "")
        if what == "report":
            out.update(title="Open the report", desc="Opens the latest report in your browser.", params={"what": "report"})
        elif what == "terminal":
            v = ai_actions.validate(str(obj.get("cmd") or ""), "terminal", "")
            if not v["ok"]:
                return _bad(v["reason"], ui)
            out.update(title="Type a command in the Terminal tab", desc="Types the command; you press Enter to run it.", params={"what": "terminal", "cmd": v["cmd"]}, risk=v["risk"])
        else:
            return _bad("that cannot be opened from here", ui)
    elif ui == "install":
        prof = str(obj.get("profile") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_,-]{1,60}", prof):
            return _bad("not a tool profile name", ui)
        v = ai_actions.validate("plasbench install-tools " + prof.replace(",", ","), "window", "")
        if not v["ok"]:
            return _bad(v["reason"], ui)
        out.update(title="Install tools: %s" % prof, desc="Opens the install dialog for %s. Installing downloads software; nothing starts until you confirm there." % prof, risk="destructive", confirm=True, params={"profile": prof})
    elif ui == "runtime":
        rt = str(obj.get("use") or "")
        if rt not in RUNTIMES:
            return _bad("the runtime must be conda or docker", ui)
        out.update(title="Run the tools in %s" % rt, desc="Switches where PlasBench runs its tools to %s (you can switch back)." % rt, risk="changes_files", confirm=True, params={"use": rt})
    elif ui == "flow":
        name = str(obj.get("name") or "")
        if name not in FLOWS:
            return _bad("not a guided flow", ui)
        out.update(title=FLOWS[name], desc="Starts the guided steps in this pane. Each step asks you first.", params={"name": name})
    out["why"] = why
    return out


def _cohort_names(project):
    try:
        d = project.root / "cohorts"
        return {p.stem for p in d.glob("*.tsv")} if d.is_dir() else None
    except Exception:  # noqa: BLE001
        return None


def _ranged(project) -> set:
    try:
        return set(project.setting_ranges().load(project.root))
    except Exception:  # noqa: BLE001
        return set()


_TABLE = {}


def allowed_settings(project) -> dict:
    """key -> {"type", "allowed", "label", "risk"} from config/ai_settable.tsv (the explicit list of settings the assistant may change); {} when the file is missing, so nothing is settable."""
    try:
        path = project.root / "config" / "ai_settable.tsv"
        sig = (path.stat().st_mtime_ns, path.stat().st_size)
        got = _TABLE.get(str(path))
        if got and got[0] == sig:
            return got[1]
        table = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#") or line.startswith("key" + chr(9)):
                continue
            c = line.split(chr(9))
            if len(c) >= 5:
                table[c[0]] = {"type": c[1], "allowed": c[2], "label": c[3], "risk": c[4]}
        _TABLE[str(path)] = (sig, table)
        return table
    except (OSError, AttributeError):
        return {}


def check_value(entry: dict, value: str) -> str:
    """"" when the value fits the listed type, else the reason."""
    t, allowed = entry["type"], entry["allowed"]
    if t in ("flag", "choice"):
        return "" if value in allowed.split("|") else "the value must be one of: %s" % ", ".join(allowed.split("|"))
    if t == "int":
        lo, _, hi = allowed.partition("..")
        if not re.fullmatch(r"\d{1,9}", value) or not int(lo) <= int(value) <= int(hi):
            return "the value must be a whole number from %s to %s" % (lo, hi)
        return ""
    return "unknown type in the list"
