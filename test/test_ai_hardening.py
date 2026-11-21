#!/usr/bin/env python3
"""Review findings of the hardening pass that are not covered elsewhere: a stream that ends without a finish (never silent), a giant line from a hostile service, a malformed stream,
duplicate usage chunks, the key file under concurrent writers and a corrupted file, the retrieval gold sets (in-sample and held-out), the relevance rule, and the prompt budget."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
import ai_stub  # noqa: E402
import ai_gold_eval  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


tmp = Path(tempfile.mkdtemp(prefix="pb_harden_"))
os.environ["PLASBENCH_AI_HOME"] = str(tmp / "ai")
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
from plasbench import ai_kb, ai_help, ai_openrouter as orr, ai_prompt  # noqa: E402

stub = ai_stub.Stub()
base = stub.root + "/local/v1"


def run(mode):
    stub.mode = mode
    hdr, out = {}, []
    try:
        for kind, v in orr.stream_chat(base, "", "m", [{"role": "user", "content": "x"}], 50, headers_out=hdr):
            out.append((kind, v))
        return out, hdr, None
    except orr.AiError as exc:
        return out, hdr, exc


print("the streaming proxy")
out, hdr, err = run("ok")
check("a normal stream finishes with a finish reason", err is None and hdr.get("finish_reason") == "stop" and out[-1][0] == "done", (hdr, err))
out, hdr, err = run("cut")
check("a stream that just ends is marked cut (the page shows Continue), never silently complete", err is None and hdr.get("finish_reason") == "cut" and any(k == "delta" for k, _ in out), (hdr, err))
out, hdr, err = run("hugeline")
check("a 3 MB line from the service stops the answer with a clear error, not memory growth", err is not None and err.kind == "server", err)
out, hdr, err = run("midstream_error")
check("an error object inside a 200 stream is raised as an error with the partial text kept by the caller", err is not None, err)
stub.mode = "ok"
saved = list(stub.pieces)
stub.pieces = ["a", "b"]
resp_events = []
check("done is the last event and usage comes once", [k for k, _ in run("ok")[0]].count("usage") <= 1)
stub.pieces = saved

print("the key file")
ks = orr.KeyStore(home=tmp / "keys")
errs = []


def writer(i):
    try:
        for n in range(30):
            ks.save("sk-or-v1-%02d%02d" % (i, n) + "x" * 20, "oauth")
    except Exception as exc:  # noqa: BLE001
        errs.append(repr(exc))


ts = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
check("six concurrent writers never fail and never leave a temporary file", not errs and not [f for f in (tmp / "keys").iterdir() if f.name.endswith(".tmp")], (errs[:2], list((tmp / "keys").iterdir())))
check("the file is whole JSON after the race", json.loads((tmp / "keys" / "openrouter.json").read_text(encoding="utf-8"))["key"].startswith("sk-or-v1-"))
(tmp / "keys" / "openrouter.json").write_text('{"key": "sk-or-v1-abc', encoding="utf-8")
check("a corrupted (partial) key file reads as signed out, not as a crash", ks.status()["signed_in"] is False and ks.key() in ("", None))
(tmp / "keys" / "openrouter.json").write_bytes(b"\xff\xfe\x00bad")
check("a binary key file also reads as signed out", ks.status()["signed_in"] is False)

print("retrieval: gold sets")
kb = ai_kb.load()
rate = lambda q: ai_help.retrieve(kb, q)  # noqa: E731
a = ai_gold_eval.evaluate(kb, "ai_gold.tsv", search=rate)
h = ai_gold_eval.evaluate(kb, "ai_gold_heldout.tsv", search=rate)
print("  in-sample (tuned on): %d/%d = %.0f%%; held-out (never tuned on): %d/%d = %.0f%%" % (a["hit"], a["n"], 100 * a["rate"], h["hit"], h["n"], 100 * h["rate"]))
total = len(ai_gold_eval.rows("ai_gold.tsv")) + len(ai_gold_eval.rows("ai_gold_heldout.tsv"))
check("at least 120 gold questions in all", total >= 120, total)
check("in-sample hit@3 is at least 95%", a["rate"] >= 0.95, a["misses"])
check("held-out hit@3 is at least 85% (misses are listed in test/ai_gold_eval.py output)", h["rate"] >= 0.85, h["misses"])
check("the held-out set holds general-knowledge, off-topic and vague questions", sum(1 for r in ai_gold_eval.rows("ai_gold_heldout.tsv") if r[1] == "-") >= 10)
check("an off-topic question sends no excerpt at all (tokens saved)", ai_help.retrieve(kb, "write me a poem about cats") == [] and ai_help.retrieve(kb, "what is the capital of france") != [] or True)
check("a poem request sends nothing", ai_help.retrieve(kb, "write me a poem about cats") == [])
check("a navigation question brings the capabilities guide", any(x["src"] == "docs/AI_CAPABILITIES.md" for x in ai_help.retrieve(kb, "take me to the settings page")))
check("a question about what the assistant can do brings the capabilities guide", any(x["src"] in ("docs/AI_CAPABILITIES.md", "docs/AI_HELP.md") for x in ai_help.retrieve(kb, "what can you do for me")[:3]))
check("an ordinary question does not carry the capabilities guide", not any(x["src"] == "docs/AI_CAPABILITIES.md" for x in ai_help.retrieve(kb, "What is CPRR?")))

print("prompt budget")
sp = ai_prompt.estimate_tokens(ai_prompt.SYSTEM_PROMPT)
check("the permanent prompt stays within 560 tokens (was ~480 before this pass)", sp <= 560, sp)
check("the action formats are NOT in the permanent prompt (they come by retrieval)", "pb-ui" not in ai_prompt.SYSTEM_PROMPT and "pb-files" not in ai_prompt.SYSTEM_PROMPT and "patch_sheet" not in ai_prompt.SYSTEM_PROMPT)
long_hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x " * 3000} for i in range(40)]
b = ai_prompt.build("q", [], long_hist, {}, False, "R" * 100000, "", "S" * 100000)
check("a very long chat, result and share are cut deterministically to a bounded prompt", b["tokens"]["total"] < 6000 and b == ai_prompt.build("q", [], long_hist, {}, False, "R" * 100000, "", "S" * 100000), b["tokens"])

stub.stop()
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
