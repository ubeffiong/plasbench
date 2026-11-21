#!/usr/bin/env python3
"""`plasbench ask` and `plasbench ai`: against the local stubs. The notice is shown first, the answer, sources and proposed commands are printed, nothing is ever executed, errors
have their own exit codes, and the same stored sign-in and free-model rules apply as in the window."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
import ai_stub  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:400]}")
    ok &= bool(good)


stub = ai_stub.Stub()
tmp = tempfile.mkdtemp(prefix="pb_aicli_")
env = dict(os.environ, **stub.env(), PLASBENCH_AI_HOME=tmp + "/ai", PLASBENCH_UI_HOME=tmp + "/ui", PYTHONIOENCODING="utf-8", PLASBENCH_LOCAL_SETTINGS=tmp + "/local.env")
env.pop("AI_PROVIDER", None)


def run(*args, extra=None):
    e = dict(env, **(extra or {}))
    r = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT)] + list(args), capture_output=True, text=True, env=e, timeout=120, cwd=str(ROOT))
    return r.returncode, r.stdout, r.stderr


code, out, err = run("ai", "status")
check("ai status works with nothing set up and prints no key", code == 0 and "not signed in" in out and "openrouter" in out, out + err)
code, out, err = run("ask", "what", "is", "cprr")
check("ask before the notice prints it and exits 2", code == 2 and "--accept-notice" in err and "free" in err.lower(), err[:300])
code, out, err = run("ask", "--accept-notice", "what", "is", "cprr")
check("ask before signing in exits 2 and says to sign in", code == 2 and "Sign in" in err, err)
# sign in by saving a key the way the window does
sys.path.insert(0, str(ROOT))
os.environ.update({"PLASBENCH_AI_HOME": tmp + "/ai"})
from plasbench import ai_openrouter as orr  # noqa: E402

orr.KeyStore().save(ai_stub.FAKE_KEY, "pasted")
stub.requests.clear()
code, out, err = run("ask", "--model", "stub/free-a:free", "how", "do", "I", "check", "my", "installation")
check("ask prints the answer, the sources and the proposed command", code == 0 and "plasbench status" in out and "Sources:" in out and "Proposed commands" in out, out + err)
check("it says where to run the command and that it was not run", "Terminal tab" in out and "not run" in out)
check("it prints the model and the tokens on stderr", "stub/free-a:free" in err and "1240 tokens" in err, err)
check("it never prints the key", ai_stub.FAKE_KEY not in out + err)
code, out, err = run("ask", "--json", "--model", "stub/free-b:free", "what", "is", "cprr")
d = json.loads(out)
check("--json gives the text, the actions and the usage", code == 0 and d["model"] == "stub/free-b:free" and d["actions"][0]["runnable"] and d["usage"]["total"] == 1240, out)
code, out, err = run("ask", "--model", "stub/paid-x", "what", "is", "cprr")
check("a paid model is refused (exit 2) and nothing is sent", code == 2 and "not a free model" in err and not stub.chat_requests()[2:], err)
stub.mode = "402"
code, out, err = run("ask", "--model", "stub/free-a:free", "what", "is", "cprr")
check("no credits is exit 1 with a clear message", code == 1 and "credits" in err, err)
stub.mode = "ok"
code, out, err = run("ask", "--accept-notice", "x", extra={"PLASBENCH_OFFLINE": "1"})
check("forced offline exits 3", code == 3, err)
code, out, err = run("ai", "signout")
check("ai signout deletes the key", code == 0 and not (Path(tmp) / "ai" / "openrouter.json").exists())
code, out, err = run("ask", "--accept-notice", "--provider", "local", "what", "is", "cprr")
check("the local provider needs no sign-in", code == 0 and "Authorization" not in stub.chat_requests()[-1]["headers"], err)
code, out, err = run("ask", "x", extra={"AI_HELP_ENABLED": "0"})
check("AI_HELP_ENABLED=0 refuses ask", code == 2 and "off" in err.lower(), err)
stub.stop()
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
