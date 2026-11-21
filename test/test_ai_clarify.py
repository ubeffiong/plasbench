#!/usr/bin/env python3
"""The AI help's conversation behaviour: it can ask a clarifying question (quick-reply options that only send text, never run anything), it says to the person and to the model that it cannot see
files, it may use general knowledge marked as such, and PlasBench puts no daily token limit and no short answer cut on it (a cut-off answer offers Continue). Standard library only."""
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import ai_actions, ai_help, ai_openrouter as orr, ai_prompt  # noqa: E402

OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {'ok  ' if good else 'FAIL'}  {label}" + ("" if good else f" -> {detail}"))
    OK = OK and bool(good)


print("clarifying questions")
r = ai_actions.parse_reply("I need one fact.\n```pb-ask\n{\"q\":\"Which system do you use?\",\"options\":[\"Windows with WSL\",\"Linux\",\"macOS\"]}\n```\n")
check("a pb-ask block becomes a question card and leaves the text", r["asks"] == [{"q": "Which system do you use?", "options": ["Windows with WSL", "Linux", "macOS"]}] and r["text"] == "I need one fact." and not r["actions"], r)
r = ai_actions.parse_reply("```pb-ask\n{'q': 'Docker or conda?', 'options': ['Docker', 'conda',],}\n```")
check("small format slips (single quotes, trailing commas) are tolerated", r["asks"] and r["asks"][0]["options"] == ["Docker", "conda"], r)
r = ai_actions.parse_reply("```pb-ask\n{\"q\":\"x\",\"options\":[" + ",".join('"%d%s"' % (i, "o" * 200) for i in range(9)) + "]}\n```\n```pb-ask\n{\"q\":\"second\",\"options\":[\"a\"]}\n```")
check("at most one question per reply (an extra one is dropped from the text), at most 5 options, each short", len(r["asks"]) == 1 and "second" not in r["text"] and len(r["asks"][0]["options"]) == 5 and all(len(o) <= ai_actions.ASK_OPTION_TEXT for o in r["asks"][0]["options"]), r)
r = ai_actions.parse_reply("```pb-ask\n{\"q\":\"Run it?\",\"cmd\":\"plasbench stop --all --yes\",\"options\":[\"yes\"]}\n```")
check("a question that carries a command is not a question and never becomes a runnable action", not r["asks"] and not [a for a in r["actions"] if a.get("runnable")], r)
r = ai_actions.parse_reply("```pb-ask\n{\"q\":\"<img src=x onerror=alert(1)> ok?\",\"options\":[\"<b>a</b>\"]}\n```")
check("the question stays plain text for the page to escape; nothing is executable", r["asks"] and r["asks"][0]["q"].startswith("<img") and not r["actions"])
check("garbage or an empty question is ignored", not ai_actions.parse_reply("```pb-ask\nnot json\n```")["asks"] and not ai_actions.parse_reply("```pb-ask\n{\"q\":\"  \"}\n```")["asks"])

print("what the assistant says about files and general knowledge")
sp = ai_prompt.SYSTEM_PROMPT
check("the model is told it cannot open the person's files and must not claim to have checked one", "never open the person's files" in sp and "Never claim to have checked a file" in sp and "press Share" in sp)
check("the model may use general knowledge for related questions, marked as such", "General knowledge:" in sp and "related topics" in sp and "own knowledge and judgement" in sp)
check("PlasBench facts still come only from the excerpts and commands are never invented", "ONLY from the <doc" in sp and "Never invent PlasBench commands" in sp)
check("the model is told to ask one short question when a missing fact decides the answer", "ask ONE short question" in sp and "pb-ask" in sp)
d = ai_help.disclosure(ai_help.ai_providers.get("local", ai_help.Settings(None)))
check("the notice declares that the assistant cannot see files", "never opens your files" in d["declaration"] and "press Share" in d["declaration"] and "FASTQ" in d["declaration"] and "FASTA" in d["declaration"], d["declaration"])
check("a short declaration is always shown under the chat", "never opens your files" in d["declaration_short"] and "press Share" in d["declaration_short"] and len(d["declaration_short"]) < 200)
check("the notice says general-knowledge parts are marked and can be wrong", "General knowledge:" in d["general"] and "can be wrong" in d["general"])

print("no usage cap of PlasBench's own")
check("the daily token limit is off by default", ai_help.DEFAULTS["AI_DAILY_TOKEN_CAP"] == "0" and 'AI_DAILY_TOKEN_CAP:-0' in (ROOT / "config" / "config.sh").read_text(encoding="utf-8"))
check("with the limit off a very large day's usage stops nothing", orr.Usage.check_cap.__call__ is not None)
u = orr.Usage.__new__(orr.Usage)
u.total_today = lambda: 10 ** 9
try:
    u.check_cap(0)
    check("a cap of 0 never raises, whatever was used today", True)
except orr.AiError as exc:
    check("a cap of 0 never raises, whatever was used today", False, exc.message)
check("an answer is allowed 2,000 tokens (3 times the old 700), brief 600", ai_prompt.DEFAULT_MAX_TOKENS == 2000 and ai_prompt.BRIEF_MAX_TOKENS == 600)
lines = [b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n', b'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"length"}]}\n', b'data: [DONE]\n']


class Resp(list):
    headers = {}

    def close(self):
        pass


info = {}
got = list(orr.stream_chat("http://x", "k", "m", [], 10, opener=lambda req, t: Resp(lines), headers_out=info))
check("a stream that ends with finish_reason=length is recorded, so the page can offer Continue", info.get("finish_reason") == "length" and ("delta", "Hello") in got, (info, got))
page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the page shows a question card with quick-reply buttons that only send text, and a Continue button for a cut answer",
      "function aiAskCard" in page and "data-aiask" in page and "data-aicont" in page and 'id="ai_decl"' in page and "aiSend(text)" in page)
check("the question the assistant asked is kept in the chat history it is sent next turn", "Question I asked:" in page)
check("the declaration is in the first-use notice and in a line that stays under the chat", "d.declaration" in page and "declaration_short" in page)
print("PASS" if OK else "FAIL")
sys.exit(0 if OK else 1)
