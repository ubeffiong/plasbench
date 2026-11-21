#!/usr/bin/env python3
"""Build the knowledge index of PlasBench's AI help (plasbench/data/ai_kb.json.gz).

The assistant answers from PlasBench's own material, not from the model's memory. This script turns that material into small chunks (about 150-350 words, cut at
headings) that plasbench/ai_kb.py ranks with BM25 and the window sends, three to five at a time, with a question. The index is shipped inside the package
(package data), because the installed program (pip, conda, Docker) may not have the docs folder next to it.

Sources: the guides (README, FAQ, INSTALL, SUPPORT, docs/*), the workflow table (config/workflow_steps.tsv), the tool table (config/tool_capabilities.tsv), the Settings
of config/config.sh (key, default, comment), the metric and window help texts, the command line (built from the argparse parser of plasbench/cli.py, so it cannot drift),
the failure signatures (config/resource_signatures.tsv, the Docker and assembler diagnosis rules) and the exit codes.

Deterministic: the same sources give the same bytes (sorted keys, gzip without a time stamp), so test/test_ai_kb.py can require that the shipped file is current:
    python python/build_ai_kb.py            # rebuild plasbench/data/ai_kb.json.gz
    python python/build_ai_kb.py --check    # exit 1 when the shipped file is out of date
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "plasbench" / "data" / "ai_kb.json.gz"
SCHEMA = 1

GUIDES = ["README.md", "FAQ.md", "INSTALL.md", "SUPPORT.md", "docs/USER_GUIDE.md", "docs/METHODS.md", "docs/SCIENTIFIC_GUIDE.md", "docs/METAGENOMICS.md",
          "docs/ADDING_TOOLS.md", "docs/RESOURCE_ADAPTATION.md", "docs/TOOL_INSTALL_AUDIT.md", "docs/publishing/README.md", "docs/INPUT_GUIDE.md", "docs/FINDING_DATA.md",
          "docs/COHORTS.md", "SECURITY.md", "docs/AI_HELP.md", "docs/AI_CAPABILITIES.md"]
MIN_WORDS, MAX_WORDS = 70, 330

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))


def words(text: str) -> int:
    return len(text.split())


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading (lower case, punctuation dropped, spaces to hyphens)."""
    s = re.sub(r"`([^`]*)`", r"\1", heading).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.U)
    return re.sub(r"\s", "-", s)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"<[^>\n]{1,200}>", "", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)    # links keep their words, not their addresses
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def blocks_of(body: str) -> list:
    """Paragraph-sized pieces; a code fence or a table stays in one piece."""
    out, cur, fence = [], [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            fence = not fence
            cur.append(line)
            continue
        if fence:
            cur.append(line)
            continue
        if not line.strip():
            if cur:
                out.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


def split_words(block: str, limit: int) -> list:
    """A block longer than the limit (a huge table or code fence) is cut at line breaks."""
    if words(block) <= limit:
        return [block]
    parts, cur, n = [], [], 0
    for line in block.split("\n"):
        w = words(line)
        if cur and n + w > limit:
            parts.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += w
    if cur:
        parts.append("\n".join(cur))
    return parts


def pack(title: str, body: str, max_words: int = MAX_WORDS) -> list:
    """Cut one section into chunks of at most max_words, at block boundaries; a tiny last piece joins the one before."""
    pieces = []
    for b in blocks_of(body):
        pieces.extend(split_words(b, max_words))
    chunks, cur, n = [], [], 0
    for p in pieces:
        w = words(p)
        if cur and n + w > max_words:
            chunks.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        chunks.append("\n\n".join(cur))
    if len(chunks) > 1 and words(chunks[-1]) < 40:
        last = chunks.pop()
        chunks[-1] += "\n\n" + last
    return chunks


def markdown_chunks(rel: str, text: str) -> list:
    """Chunks of one guide: a section per heading (levels 1-4), small sections joined with the next one, big sections cut."""
    text = clean(text)
    sections, stack, cur = [], [], {"path": [], "anchor": "", "lines": []}
    fence = False
    seen = {}
    for line in text.split("\n"):
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,4})\s+(.+?)\s*#*$", line)
        if m:
            sections.append(cur)
            level, title = len(m.group(1)), m.group(2).strip()
            stack = [s for s in stack if s[0] < level] + [(level, title)]
            base = slug(title)
            n = seen.get(base, 0)
            seen[base] = n + 1
            cur = {"path": [t for _, t in stack], "anchor": base if n == 0 else f"{base}-{n}", "lines": []}
        else:
            cur["lines"].append(line)
    sections.append(cur)
    out, carry = [], None
    for sec in sections:
        body = "\n".join(sec["lines"]).strip()
        path = sec["path"] or [Path(rel).stem]
        if carry:
            body = (carry["body"] + "\n\n" + (("## " + path[-1] + "\n") if sec["path"] else "") + body).strip()
            first = carry
            carry = None
        else:
            first = {"path": path, "anchor": sec["anchor"]}
        if not body:
            continue
        if words(body) < MIN_WORDS and sec is not sections[-1]:
            carry = {"path": first["path"], "anchor": first["anchor"], "body": body}
            continue
        for i, piece in enumerate(pack(" > ".join(first["path"]), body)):
            out.append({"src": rel, "title": " > ".join(first["path"]) + (f" (part {i + 1})" if i else ""), "anchor": first["anchor"], "kind": "guide", "text": piece})
    if carry:
        out.append({"src": rel, "title": " > ".join(carry["path"]), "anchor": carry["anchor"], "kind": "guide", "text": carry["body"]})
    return out


def tsv_rows(path: Path) -> list:
    with open(path, encoding="utf-8", newline="") as fh:
        lines = [l for l in fh if not l.startswith("#")]
    return list(csv.DictReader(io.StringIO("".join(lines)), delimiter="\t"))


def one(rel, title, text, kind):
    return {"src": rel, "title": title, "anchor": "", "kind": kind, "text": text.strip()}


def workflow_chunks() -> list:
    rel = "config/workflow_steps.tsv"
    steps = {}
    for r in tsv_rows(ROOT / rel):
        steps.setdefault((int(r["step_order"]), r["step_id"]), []).append(r)
    out = []
    for (order, sid), rows in sorted(steps.items()):
        head = rows[0]
        lines = [f"Workflow stage {head['stage']} - {head['step_name']} (script {head['script']}). {head['step_blurb']}"]
        for r in rows:
            bits = [f"- {r['label']} [{r['kind']}]: {r['description']}"]
            if r["setting_key"]:
                bits.append(f"Setting {r['setting_key']} on={r['on_value'] or '1'} off={r['off_value'] or '0'} default {r['default'] or 'on'}")
            if r["cli_flag"]:
                bits.append(f"flag {r['cli_flag']}")
            if r["requires"]:
                bits.append(f"requires {r['requires']}")
            if r["needs_internet"] and r["needs_internet"] != "no":
                bits.append(f"needs internet: {r['needs_internet']}")
            lines.append(" ".join(bits))
        text = "\n".join(lines)
        for i, piece in enumerate(pack(head["step_name"], text, MAX_WORDS)):
            out.append(one(rel, f"Workflow stage {head['stage']}: {head['step_name']}" + (f" (part {i + 1})" if i else ""), piece, "workflow"))
    return out


def tool_chunks() -> list:
    rel = "config/tool_capabilities.tsv"
    rows = tsv_rows(ROOT / rel)
    lines = [f"{r['tool']}: {r['method_class']}, binning={r['binning_capable']}, input={r['primary_input']}, track={r['analysis_track']}, validation={r['validation_status']}. {r['description']}" for r in rows]
    out, cur, n = [], [], 0
    for l in lines:
        if cur and n + words(l) > MAX_WORDS:
            out.append(one(rel, f"Tools and what each can do (part {len(out) + 1})", "\n".join(cur), "tools"))
            cur, n = [], 0
        cur.append(l)
        n += words(l)
    if cur:
        out.append(one(rel, f"Tools and what each can do (part {len(out) + 1})", "\n".join(cur), "tools"))
    return out


def settings_chunks() -> list:
    rel = "config/config.sh"
    from plasbench import webui
    rows = webui.Project(ROOT)._parse_config_sh(ROOT / rel)
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    out = []
    for group, items in groups.items():
        cur, n, part = [], 0, 1
        for r in items:
            line = f"{r['key']} (default {r['default'] or 'empty'}): {r['comment']}".strip()
            line = re.sub(r"\s+", " ", line)
            if cur and n + words(line) > MAX_WORDS:
                out.append(one(rel, f"Settings: {group}" + (f" (part {part})" if part > 1 else ""), "\n".join(cur), "settings"))
                cur, n, part = [], 0, part + 1
            cur.append(line)
            n += words(line)
        if cur:
            out.append(one(rel, f"Settings: {group}" + (f" (part {part})" if part > 1 else ""), "\n".join(cur), "settings"))
    return out


def cli_chunks() -> list:
    rel = "plasbench/cli.py"
    from plasbench import ui_schema
    sch = ui_schema.schema()
    out = []

    def render(cmd, prefix):
        name = (prefix + " " + cmd["name"]).strip()
        head = f"plasbench {name}: {cmd['help'] or cmd['description'] or ''}".strip()
        lines = []
        for a in cmd["args"]:
            flags = " ".join(a.get("flags") or []) or a["dest"]
            extra = []
            if a.get("choices"):
                extra.append("choices " + "/".join(str(c) for c in a["choices"]))
            if a.get("default") not in (None, "", False, []):
                extra.append("default " + str(a["default"]).replace("\\", "/"))    # a Path default prints with the platform's separator: the index must not depend on the OS
            lines.append(f"  {flags}: {(a.get('help') or '').strip()} {'(' + '; '.join(extra) + ')' if extra else ''}".rstrip())
        subs = [s["name"] for s in cmd["subcommands"]]
        if subs:
            lines.append("  subcommands: " + ", ".join(subs))
        text = head + "\n" + "\n".join(lines)
        text = re.sub(r"[ \t]+", " ", text)
        for i, piece in enumerate(pack(name, text, MAX_WORDS)):
            out.append(one(rel, f"Command: plasbench {name}" + (f" (part {i + 1})" if i else ""), piece, "cli"))
        for s in cmd["subcommands"]:
            render(s, name)

    for cmd in sch["commands"]:
        render(cmd, "")
    glob = "\n".join(f"  {' '.join(a.get('flags') or [])}: {(a.get('help') or '').strip()}" for a in sch["global_args"])
    out.append(one(rel, "Command: global options of plasbench", "Options that go before the command name:\n" + glob, "cli"))
    cats = "\n".join(f"{c['title']}: {', '.join(c['commands'])}" for c in sch["categories"])
    out.append(one(rel, "Command: list of all plasbench commands by group", "plasbench commands grouped by purpose:\n" + cats, "cli"))
    return out


def help_chunks() -> list:
    out = []
    from report_help_text import FIELDS, HELP
    rel = "python/report_help_text.py"
    for key in sorted(HELP):
        ent = HELP[key]
        text = "\n".join(f"{label}: {ent[f]}" for f, label in FIELDS if ent.get(f))
        out.append(one(rel, f"Report section and metric help: {key.replace('_', ' ')}", text, "metrics"))
    from plasbench import ui_help
    rel = "plasbench/ui_help.py"
    cur, n, part = [], 0, 1
    for table in (ui_help.WIZARD, ui_help.ENVIRONMENT, ui_help.TOOLS):
        for key in sorted(table):
            ent = table[key]
            if not isinstance(ent, dict):
                continue
            summ = ent.get("summary") or ""
            ch = ent.get("choices")
            if isinstance(ch, dict) and ch:
                summ += " Choices: " + "; ".join(f"{k}: {v}" for k, v in ch.items())
            if ent.get("when"):
                summ += " " + ent["when"]
            line = re.sub(r"\s+", " ", f"{key}: {summ}").strip()
            if not summ:
                continue
            if cur and n + words(line) > MAX_WORDS:
                out.append(one(rel, f"Window help texts (part {part})", "\n".join(cur), "help"))
                cur, n, part = [], 0, part + 1
            cur.append(line)
            n += words(line)
    if cur:
        out.append(one(rel, f"Window help texts (part {part})", "\n".join(cur), "help"))
    return out


def signature_chunks() -> list:
    out = []
    rel = "config/resource_signatures.tsv"
    rows = tsv_rows(ROOT / rel)
    cur, n = [], 0
    for r in rows:
        line = re.sub(r"\s+", " ", f"Failure signature {r['id']} ({r['tool']}): log text matching /{r['message_regex']}/ means a {r['cause']} problem. Exit codes {r['exit_codes']}. "
                                   f"What PlasBench tries: {r['ladder']}. {r['note']}")
        if cur and n + words(line) > MAX_WORDS:
            out.append(one(rel, f"Failure signatures in tool logs (part {len(out) + 1})", "\n".join(cur), "troubleshooting"))
            cur, n = [], 0
        cur.append(line)
        n += words(line)
    if cur:
        out.append(one(rel, f"Failure signatures in tool logs (part {len(out) + 1})", "\n".join(cur), "troubleshooting"))
    import assembler_diagnosis as ad
    rel = "python/assembler_diagnosis.py"
    for rule in ad.RULES:
        rid, title, conf, pats, _a, _b, advice = rule[:7]
        text = f"Assembler failure: {title}. Log text that shows it: " + "; ".join(p.replace("\\", "") for p in pats) + f"\nWhat to do: {advice}"
        out.append(one(rel, f"Assembler failure: {rid.replace('_', ' ')}", re.sub(r"[ \t]+", " ", text), "troubleshooting"))
    import docker_diagnosis as dd
    rel = "python/docker_diagnosis.py"
    for rule in dd.RULES:
        adv = rule["advice"]
        lines = [f"Docker problem: {rule['title']}. Error text that shows it: " + "; ".join(p.replace("\\", "") for p in rule["patterns"])]
        for env in sorted(adv):
            lines.append(f"[{env}] " + " ".join(adv[env]))
        text = re.sub(r"[ \t]+", " ", "\n".join(lines))
        for i, piece in enumerate(pack(rule["cause"], text, MAX_WORDS)):
            out.append(one(rel, f"Docker problem: {rule['cause'].replace('_', ' ')}" + (f" (part {i + 1})" if i else ""), piece, "troubleshooting"))
    return out


def exit_chunks() -> list:
    from plasbench import exitcodes
    lines = [f"Exit code {k}: {v}" for k, v in sorted(exitcodes._MEANING.items())]
    lines += [f"Exit code {k} of plasbench install-tools: {v}" for k, v in sorted(exitcodes._INSTALL_MEANING.items())]
    return [one("plasbench/exitcodes.py", "Exit codes and what they mean", "\n".join(lines), "troubleshooting")]


def build_chunks() -> list:
    chunks = []
    for rel in GUIDES:
        p = ROOT / rel
        if p.is_file():
            chunks.extend(markdown_chunks(rel, p.read_text(encoding="utf-8", errors="replace")))
    chunks += workflow_chunks() + tool_chunks() + settings_chunks() + cli_chunks() + help_chunks() + signature_chunks() + exit_chunks()
    for i, c in enumerate(chunks):
        c["id"] = i
    return chunks


def version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "plasbench" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def build_raw() -> bytes:
    """The index as JSON bytes: identical on every system. (The compressed file can differ between zlib builds, so freshness is judged on this, not on the .gz bytes.)"""
    payload = {"schema": SCHEMA, "chunks": build_chunks()}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def is_current(path=None, raw: bytes = None) -> bool:
    path = Path(path or OUT)
    try:
        return path.is_file() and gzip.decompress(path.read_bytes()) == (raw if raw is not None else build_raw())
    except (OSError, EOFError, gzip.BadGzipFile):
        return False


def build_bytes(raw: bytes = None) -> bytes:
    raw = raw if raw is not None else build_raw()
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the shipped index is not what the sources give")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    data = build_bytes()
    out = Path(args.out)
    if args.check:
        same = is_current(out)
        print("ai_kb.json.gz is current" if same else "ai_kb.json.gz is out of date: run python python/build_ai_kb.py")
        return 0 if same else 1
    with open(out, "wb") as fh:
        fh.write(data)
    n = len(json.loads(gzip.decompress(data).decode("utf-8"))["chunks"])
    print(f"wrote {out} ({len(data) // 1024} KB, {n} chunks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
