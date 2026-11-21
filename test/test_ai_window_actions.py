#!/usr/bin/env python3
"""Window actions (```pb-ui blocks, plasbench/ai_ui.py) and the parser hardening of plasbench/ai_actions.py: schema checks, the allowlists, lookalike commands, the old quadratic
regex, deep nesting, and a seeded fuzz of parse_reply. Nothing here runs a command."""
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(Path(tempfile.mkdtemp(prefix="pb_wa_")) / "local.env")
from plasbench import ai_actions, ai_ui, webui  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


project = webui.Project(ROOT)
rows = {r["key"]: r for r in project.settings()}
ranged = ai_ui._ranged(project)
flag, intkey = "RUN_DIMER_DETECTION", "NETWORK_RETRIES"
V = lambda o: ai_ui.validate(o, project)  # noqa: E731

print("go")
v = V({"ui": "go", "target": "settings"})
check("a page is allowed and described", v["ok"] and v["risk"] == "safe" and not v["confirm"] and v["params"]["target"] == "settings", v)
check("runs with a tab, help with a guide", V({"ui": "go", "target": "runs", "sub": "attention"})["ok"] and V({"ui": "go", "target": "help", "sub": "USER_GUIDE.md"})["ok"])
for bad in [{"ui": "go", "target": "../x"}, {"ui": "go", "target": "javascript:alert(1)"}, {"ui": "go", "target": "runs", "sub": "evil"}, {"ui": "go", "target": "help", "sub": "../../etc"}, {"ui": "go"}, {"ui": "go", "target": 5}]:
    check("refused: %s" % json.dumps(bad), not V(bad)["ok"])

print("setting")
v = V({"ui": "setting", "key": flag, "value": "1"})
check("a switch can be changed: old -> new shown, confirmation required, risk labelled", v["ok"] and v["confirm"] and v["risk"] == "changes_files" and "->" in v["desc"] and "old" in v["params"], v)
check("a switch refuses a value that is not 0 or 1", not V({"ui": "setting", "key": flag, "value": "maybe"})["ok"])
check("a number refuses text", not V({"ui": "setting", "key": intkey, "value": "lots"})["ok"])
for key in ("PLASMID_RECOVERY_THRESHOLD", "CPRR_MIN_COVERAGE", "HEADLINE_INDEPENDENCE", "AI_HELP_ENABLED", "AI_PROVIDER", "AI_DAILY_TOKEN_CAP", "AI_LOCAL_BASE", "AI_LOCAL_ALLOW_REMOTE", "AI_MODEL", "NCBI_API_KEY", "NCBI_EMAIL", "PATH", "HOME", "PLASBENCH_LOCAL_SETTINGS", "NOT_A_SETTING"):
    check("refused: %s" % key, not V({"ui": "setting", "key": key, "value": "1"})["ok"])
table = ai_ui.allowed_settings(project)
check("the explicit list is loaded and non-trivial", len(table) >= 60 and "RUN_DIMER_DETECTION" in table, len(table))
check("a made-up key, an AI_ key and a HEADLINE_ key are refused (not listed)", all(not V({"ui": "setting", "key": k, "value": "1"})["ok"] for k in ("MADE_UP_SETTING", "AI_PROVIDER", "HEADLINE_INDEPENDENCE", "HEADLINE_MIN_CLUSTERS")))
v = V({"ui": "setting", "key": "HEADLINE_INDEPENDENCE", "value": "independent"})
check("the reason names the list", "config/ai_settable.tsv" in v["reason"] or "not one of" in v["reason"], v["reason"])
sc = open(ROOT / "config" / "config.sh", encoding="utf-8").read()
setting_ranges = ai_ui._ranged(project)
check("every listed key exists in config/config.sh", all(("export " + k) in sc for k in table), [k for k in table if ("export " + k) not in sc])
check("no listed key is a scoring decision, an AI_ key, a secret or a path (the second layer agrees)", all(not ai_ui.settable(rows[k], setting_ranges, listed=True) for k in table), [k for k in table if ai_ui.settable(rows[k], setting_ranges, listed=True)])
check("no listed key has a range in config/setting_ranges.tsv", not (set(table) & set(setting_ranges)))
bad_types = [k for k, e in table.items() if e["type"] not in ("flag", "int", "choice") or e["risk"] not in ("low", "medium") or not e["label"]]
check("every entry has a known type, a risk and a label", not bad_types, bad_types)
ok_all, why = True, []
for k, e in table.items():
    good = {"flag": "1", "choice": e["allowed"].split("|")[0], "int": e["allowed"].split("..")[0]}[e["type"]]
    r = V({"ui": "setting", "key": k, "value": good})
    if not r["ok"]:
        ok_all = False
        why.append((k, r["reason"]))
check("a valid value of every listed key is accepted", ok_all, why[:3])
check("a value outside the listed type or range is refused", not V({"ui": "setting", "key": "THREADS", "value": "100000"})["ok"] and not V({"ui": "setting", "key": "READ_SOURCE", "value": "ftp"})["ok"] and
      not V({"ui": "setting", "key": "RUN_PLATON", "value": "2"})["ok"] and not V({"ui": "setting", "key": "SHORT_READ_QC_MODE", "value": "enforce"})["ok"])
check("a listed key whose range file entry exists would be refused by the range check (validate_changes is still called)", "validate_changes" in open(ROOT / "plasbench" / "ai_ui.py", encoding="utf-8").read())
for val in ("1; rm -rf /", "$(id)", "a\nb", "x" * 100, "/etc/passwd", "..\\x", "`x`"):
    check("a value with unsafe text is refused: %r" % val[:20], not V({"ui": "setting", "key": flag, "value": val})["ok"])

print("prefill")
v = V({"ui": "prefill", "fields": {"source": "sheet", "study": "my_study", "max_isolates": 5, "local_inputs": True, "samples": "config/my_isolates.tsv"}})
check("the wizard fields can be filled, nothing starts", v["ok"] and v["risk"] == "safe" and not v["confirm"] and "Nothing is started" in v["desc"], v)
for bad in [{"source": "rm"}, {"study": "../x"}, {"study": "a b"}, {"max_isolates": "5; ls"}, {"samples": "/etc/passwd"}, {"samples": "../x.tsv"}, {"samples": "C:/x.tsv"}, {"cohort": "nope_cohort_zz"}, {"unknown": 1}, {"local_inputs": "yes"}]:
    check("refused: %s" % json.dumps(bad), not V({"ui": "prefill", "fields": bad})["ok"])
check("empty fields are refused", not V({"ui": "prefill", "fields": {}})["ok"])

print("open, install, runtime, flow")
check("report", V({"ui": "open", "what": "report"})["ok"])
check("a terminal command passes the command checks", V({"ui": "open", "what": "terminal", "cmd": "plasbench status"})["ok"] and not V({"ui": "open", "what": "terminal", "cmd": "rm -rf /"})["ok"] and not V({"ui": "open", "what": "terminal", "cmd": "plasbench status; id"})["ok"])
check("something else cannot be opened", not V({"ui": "open", "what": "/etc/passwd"})["ok"])
v = V({"ui": "install", "profile": "core"})
check("install is destructive-labelled and needs the dialog", v["ok"] and v["risk"] == "destructive" and v["confirm"], v)
check("an install profile with shell text is refused", not V({"ui": "install", "profile": "core; id"})["ok"] and not V({"ui": "install", "profile": "$(x)"})["ok"] and not V({"ui": "install", "profile": "../x"})["ok"])
check("runtime must be conda or docker", V({"ui": "runtime", "use": "docker"})["ok"] and not V({"ui": "runtime", "use": "podman"})["ok"])
check("flows are a closed list", V({"ui": "flow", "name": "setup_run"})["ok"] and not V({"ui": "flow", "name": "format_disk"})["ok"])
check("an unknown ui id and a non-object are refused", not V({"ui": "eval", "code": "x"})["ok"] and not V("go")["ok"] and not V(None)["ok"] and not V([1])["ok"])

print("parse_reply: blocks")
reply = ("Sure.\n```pb-ui\n{\"ui\":\"go\",\"target\":\"settings\"}\n```\n```pb-ui\n{\"ui\":\"setting\",\"key\":\"AI_HELP_ENABLED\",\"value\":\"0\"}\n```\n"
         "```pb-files\n{\"ops\":[{\"op\":\"mkdir\",\"path\":\"data\"}],\"why\":\"lay out\"}\n```\n```pb-action\n{\"cmd\":\"plasbench status\",\"where\":\"window\",\"why\":\"x\"}\n```")
pr = ai_actions.parse_reply(reply, project)
check("each block type is taken out of the text and validated", len(pr["ui"]) == 2 and pr["ui"][0]["ok"] and not pr["ui"][1]["ok"] and len(pr["files"]) == 1 and len(pr["actions"]) == 1 and "pb-" not in pr["text"], pr)
check("at most 3 window actions and 1 file plan are taken", len(ai_actions.parse_reply("```pb-ui\n{\"ui\":\"go\",\"target\":\"home\"}\n```\n" * 9, project)["ui"]) == 3 and
      len(ai_actions.parse_reply("```pb-files\n{\"ops\":[{\"op\":\"mkdir\",\"path\":\"a\"}]}\n```\n" * 3, project)["files"]) == 1)
check("a plan with more than 40 operations or a huge body is not taken", not ai_actions.parse_reply("```pb-files\n" + json.dumps({"ops": [{"op": "mkdir", "path": "a"}] * 41}) + "\n```", project)["files"] and
      not ai_actions.parse_reply("```pb-files\n" + json.dumps({"ops": [{"op": "mkdir", "path": "a" * 60000}]}) + "\n```", project)["files"])
check("a plain json block without pb tag never becomes a window action", not ai_actions.parse_reply("```json\n{\"ui\":\"go\",\"target\":\"home\"}\n```", project)["ui"])

print("lookalike and invisible characters in commands")
for cmd, why in [("plasbench status", "plain"), ("plаsbench status", "Cyrillic a"), ("plasbench\u00a0status", "no-break space"), ("plasbench st\u200batus", "zero width"), ("plasbench status\u202e", "bidi"),
                 ("plasbench s\u0442atus", "Cyrillic t"), ("\uff50lasbench status", "fullwidth p"), ("plasbench\u2028status", "line separator")]:
    v = ai_actions.validate(cmd, "window")
    check("%s: %s" % (why, "accepted" if why == "plain" else "refused"), v["ok"] == (why == "plain"), v["reason"])

print("ReDoS and nesting (the old pattern took 36 s on 60,000 spaces)")
for name, text in [("spaces after a fence", "```" + " " * 1_000_000), ("tab run", "```\t" + "\t" * 500000), ("many fences", "```\n" * 200000), ("deep array", "```pb-action\n" + "[" * 300000 + "{"),
                   ("deep object", "```pb-action\n" + '{"a":' * 200000), ("quotes", "```pb-action\n{" + '"' * 500000), ("unclosed", "```pb-ui\n{" + "x" * 900000), ("one mb of text", "word " * 200000),
                   ("backslashes", "```pb-action\n{\"cmd\":\"" + "\\" * 500000), ("fence soup", ("```pb-ui ``` " * 100000)), ("huge block", "```pb-files\n" + "{" * 100000)]:
    t0 = time.time()
    try:
        ai_actions.parse_reply(text, project)
        done = True
    except BaseException as exc:  # noqa: BLE001
        done = type(exc).__name__
    check("%s: no hang, no exception (%.2f s)" % (name, time.time() - t0), done is True and time.time() - t0 < 5, done)

print("seeded fuzz of parse_reply")
rng = random.Random(20261121)
pieces = ["```", "```pb-action", "```pb-ui", "```pb-files", "```pb-ask", "```json", "\n", "{", "}", "[", "]", '"cmd"', '"ui"', '"ops"', ":", ",", '"plasbench status"', '"go"', '"settings"', "\u202e", "\u200b", "\x00", " ",
          "\t", "'", "\\", "<out>", "</doc>", "plasbench", "stop --all", "; rm -rf /", "$(id)", "../", "C:\\", "\U0001f600", "\ud7ff", "null", "true", "1e999", "-0"]
bad = 0
for i in range(3000):
    text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 60)))
    try:
        r = ai_actions.parse_reply(text, project)
        for a in r["actions"]:
            if a["runnable"] and (any(c in a["cmd"] for c in ";|&$`\n") or not a["cmd"].startswith("plasbench ")):
                bad += 1
        for u in r["ui"]:
            if u["ok"] and u["ui"] not in ai_ui.UI_IDS:
                bad += 1
        if len(r["actions"]) > 4 or len(r["ui"]) > 3 or len(r["files"]) > 1 or not isinstance(r["text"], str):
            bad += 1
    except BaseException:  # noqa: BLE001
        bad += 1
check("3,000 random replies: no exception, no runnable command with shell text, caps respected", bad == 0, bad)
bad = 0
for i in range(2000):
    cmd = "".join(rng.choice("abcdefgh -_=./\u202e\u0430;|&$`'\"\\\n") for _ in range(rng.randint(0, 50)))
    try:
        v = ai_actions.validate("plasbench " + cmd, rng.choice(ai_actions.WHERE))
        if v["runnable"] and (not (v["cmd"].isascii()) or any(c in v["cmd"] for c in ";|&$`\\\n<>")):
            bad += 1
    except BaseException:  # noqa: BLE001
        bad += 1
check("2,000 random command lines: never an exception, never runnable with shell characters or non-ASCII", bad == 0, bad)

print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
