#!/usr/bin/env python3
"""Console colours (plasbench/data/ui.html "termcolor"): ANSI colour codes are rendered as text styles and every other escape is removed, without ever parsing log text as
HTML; each line gets a type (error, warning, success, note, heading, detail, output); Copy and Save give plain text; the colour tokens are readable (WCAG contrast >= 4.5:1
on both console backgrounds); big logs stay cheap. The page's own code runs under node against a minimal DOM (no browser needed); the colour tokens are read from the page.
Also: the Terminal tab's server keeps colour codes only (plasbench/terminal.py), and scripts/lib.sh honours PLASBENCH_COLOR=0/1 and NO_COLOR.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PAGE = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{str(detail)[:600]}]"))
    if not ok:
        FAILED.append(name)


# ---------------------------------------------------------------------------------------------------------------- the page
check("the console never inserts log text as HTML (no colorize/insertAdjacentHTML of output)",
      "colorize(" not in PAGE and 'insertAdjacentHTML("beforeend", colorize' not in PAGE and "new TermStream($(\"#clog\"))" in PAGE)
check("the Terminal tab renders a command's output with the same renderer", 'tcRender(out + "\\n", b)' in PAGE)
check("Copy gives the text, not the markup", ".textContent, \"Copied\")" in PAGE)
check("Save writes the whole job output as plain text", '$("#csave").onclick' in PAGE and "tcPlain(parts.join(\"\"))" in PAGE)
check("what is sent to the assistant is plain text", "const tail = tcPlain(j.log" in PAGE)
check("a .log file opened in the window uses the console colours", 'tcRender(f.text, $("#fv_log"))' in PAGE)
modes = re.findall(r'<select id="tcmode">(.*?)</select>', PAGE, re.S)
check("the Colours menu offers Headers and status (default), Full by type, Off", modes and re.findall(r'value="(\w+)"', modes[0]) == ["status", "full", "off"]
      and 'const TC = {mode: "status"' in PAGE)
check("the page has no stray control characters", not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", PAGE))


# ---------------------------------------------------------------------------------------------------------------- contrast
def hexrgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def lum(c):
    f = [(v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def contrast(a, b):
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


block = PAGE[PAGE.index("/* ---- console colours (termcolor"):]
root = re.search(r":root\{(--tc-err:.*?)\}", block, re.S).group(1)
tokens = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})", root))
more = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})", re.search(r"@media \(prefers-contrast:more\)\{:root\{(.*?)\}\}", block).group(1)))
backs = {"light theme": re.search(r"--term-bg:(#[0-9a-f]{6})", PAGE).group(1)}
backs["dark theme"] = re.search(r":root\[data-theme=dark\]\{.*?--term-bg:(#[0-9a-f]{6})", PAGE, re.S).group(1)
text = [k for k in tokens if k.startswith("tc-") and not k.endswith("-bg")] + [f"a{i}" for i in range(16)]
low = [(k, name, round(contrast(hexrgb(tokens[k]), hexrgb(bg)), 2)) for k in text for name, bg in backs.items() if contrast(hexrgb(tokens[k]), hexrgb(bg)) < 4.5]
check(f"every console colour ({len(text)} tokens) reads at 4.5:1 or more on both console backgrounds", not low and len(text) >= 23, low)
low = [(k, round(contrast(hexrgb(v), hexrgb(backs['light theme'])), 2)) for k, v in more.items() if contrast(hexrgb(v), hexrgb(backs["light theme"])) < 7]
check("with 'more contrast' asked for by the system, the overrides reach 7:1", not low, low)
check("forced colours (Windows high contrast) keep the markers and weights", "@media (forced-colors:active)" in block)
check("errors, warnings, successes and notes have distinct markers (colour is never the only signal)",
      all(g in block for g in ('content:"\\2716"', 'content:"\\25B2"', 'content:"\\2714"', 'content:"\\25CF"')))

# ---------------------------------------------------------------------------------------------------------------- the renderer, under node
HARNESS = r"""
class N0 { constructor(t) { this.nodeType = t; this.childNodes = []; this.parentNode = null; }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { if (!this.parentNode) return null; const c = this.parentNode.childNodes; let i = this._i;   // a cached index, corrected when stale: a walk stays O(1) a step
    if (c[i] !== this) i = this._i = c.indexOf(this); const nx = c[i + 1] || null; if (nx) nx._i = i + 1; return nx; }
  appendChild(n) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; this.childNodes.push(n); n._i = this.childNodes.length - 1; return n; }
  append(...ns) { ns.forEach(n => this.appendChild(n)); }
  insertBefore(n, ref) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; if (!ref) { this.childNodes.push(n); return n; } this.childNodes.splice(this.childNodes.indexOf(ref), 0, n); return n; }
  removeChild(n) { this.childNodes.splice(this.childNodes.indexOf(n), 1); n.parentNode = null; return n; }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(c => c.textContent).join(""); }
  set textContent(v) { this.childNodes.forEach(c => { c.parentNode = null; }); this.childNodes = []; if (v !== "") this.appendChild(new TX(String(v))); } }
class TX extends N0 { constructor(v) { super(3); this.nodeValue = v; }
  splitText(i) { const t = new TX(this.nodeValue.slice(i)); this.nodeValue = this.nodeValue.slice(0, i); this.parentNode.insertBefore(t, this.nextSibling); return t; } }
const made = new Set();
class EL extends N0 { constructor(tag) { super(1); this.tagName = tag; made.add(tag); this.className = ""; this.style = {}; this.dataset = {}; }
  get classList() { const s = this; return {contains: c => s.className.split(/\s+/).includes(c)}; } }
class RG { setStartAfter(n) { this.p = n.parentNode; this.s = this.p.childNodes.indexOf(n) + 1; } setEndAfter(n) { this.e = n.parentNode.childNodes.indexOf(n) + 1; }
  deleteContents() { this.p.childNodes.splice(this.s, this.e - this.s).forEach(c => { c.parentNode = null; }); } }
const document = {createElement: t => new EL(t), createTextNode: v => new TX(v), querySelectorAll: () => [], createRange: () => new RG()};
const ser = n => n.nodeType === 3 ? n.nodeValue : `<${n.className || n.tagName}${n.style.color ? " c=" + n.style.color : ""}${n.style.backgroundColor ? " bg=" + n.style.backgroundColor : ""}>${n.childNodes.map(ser).join("")}</>`;
const out = {};
const box = () => new EL("pre");
function run(chunks) { const b = box(), s = new TermStream(b); for (const c of chunks) s.feed(c); s.flush(); return {b, s}; }
const lines = b => b.childNodes.filter(n => n.nodeType === 1);
"""

TESTS = r"""
let r;
r = run(["\x1b[31mred\x1b[0m plain\n"]); out.sgr16 = ser(r.b);
r = run(["\x1b[1;38;5;196mX\x1b[38;2;10;10;10mY\x1b[22;39mZ\x1b[44mB\x1b[0m\n"]); out.sgrmix = ser(r.b);
r = run(["\x1b[3", "1mred", "\x1b", "[0m ok\n"]); out.split = ser(r.b);
r = run(["10%\r50%\r100%\n"]); out.cr = r.b.textContent;
r = run(["a\r", "\nb\n"]); out.crlf = r.b.textContent;
r = run(["\x1b[2K\x1b[1Gabc\x1b[?25l\x1b[3;4H\x1b(B\x1b7d\n"]); out.csi = r.b.textContent;
r = run(["\x1b]0;window title\x07x\x1b]8;;http://e.example\x1b\\link\x1b]8;;\x1b\\\n"]); out.osc = r.b.textContent;
r = run(["<script>alert(1)</script>\x1b[31m<img src=x onerror=alert(2)>\x1b[0m &amp;\n"]); out.hostile = r.b.textContent; out.tags = [...made].sort();
r = run(["start \x1b[", "1;".repeat(400), "m tail\n"]); out.longesc = r.b.textContent.length > 0;
r = run(["dangling \x1b"]); out.dangling = r.b.textContent;
r = run(["[2026-11-14 21:40:00] WARNING: SPAdes failed for s1; excluded\n"]); out.warnline = ser(r.b);
r = run(["\x1b[31mSomething went wrong without a keyword\x1b[0m\n", "\x1b[32mall good\x1b[0m\n"]); out.hints = lines(r.b).map(n => n.className);
r = run(["Traceback (most recent call last):\n", "  File \"x.py\", line 1, in <module>\n", "    boom()\n", "ValueError: no\n", "after\n"]); out.tb = lines(r.b).map(n => n.className);
const sample = "=== Assemble s1 ===\n[2026-11-14 21:36:10]   fastp trimming (e_coli) ...\n\x1b[33mwarning:\x1b[0m deprecated option\nWhat to do: run it again\nNOTE: the computer was asleep\n$ plasbench check\n[you] y\nStage 3 (assembly) complete: 4 of 4 assembled.\n[exit 3]\n10%\r100%\nplain output\n";
r = run([sample]); out.types = lines(r.b).map(n => n.className); out.plainEq = r.b.textContent === tcPlain(sample); out.plain = tcPlain(sample);
out.tcplain = tcPlain("\x1b[1;31mA\x1b[0m\r\nB 1%\rB 99%\r\nC\x1b]0;t\x07D\x07E\n");
// classify cost does not grow with a pathological line
let t0 = Date.now(); r = run(["a".repeat(100000) + " ERROR " + "-".repeat(100000) + "\n", ("=".repeat(50000) + " " ).repeat(2) + "\n", "(".repeat(100000) + "\n"]); out.longline_ms = Date.now() - t0;
out.longline_text = r.b.textContent.length;
// 200,000 lines in 256 KB pieces, as the console receives them, with the display cap
TC.MAX_LINES = 50000;
const big = []; for (let i = 0; i < 200000; i++) big.push(i % 997 === 0 ? `[2026-11-14 21:40:00] ERROR: line ${i} failed` : i % 101 === 0 ? `WARNING: line ${i}` : `line ${i} of tool output with some text`);
const text = big.join("\n") + "\n";
t0 = Date.now(); const bb = box(), ss = new TermStream(bb); for (let i = 0; i < text.length; i += 262144) ss.feed(text.slice(i, i + 262144)); out.big_ms = Date.now() - t0;
out.big_lines = ss.lines; out.big_first = bb.firstChild.className; out.big_last = lines(bb).slice(-1)[0].textContent;
TC.MAX_LINES = 50000;
// TC_TYPES legend and modes are defined
out.types_n = TC_TYPES.length; out.modes = Object.keys(TC_MODES);
// the readable fallback for a too-dark true colour
out.readable = tcContrast(tcReadable([10, 10, 10]), [0x1f, 0x23, 0x29]) >= 4.5;
console.log(JSON.stringify(out));
"""

node = shutil.which("node")
if not node:
    print("  skip  node not installed: the renderer was not run")
else:
    heads = [l for l in PAGE.split("\n") if l.startswith(("const RX_OK", "const RX_ERR", "const RX_WARN", "const RX_TAG"))]
    lv = PAGE[PAGE.index("function lineLevel(l) {"):]
    lv = lv[:lv.index("\n}\n") + 3]
    mod = PAGE[PAGE.index("/* ---- termcolor: begin ----"):PAGE.index("/* ---- termcolor: end ---- */")]
    js = "const localStorage = undefined;\n" + "\n".join(heads) + "\n" + lv + HARNESS + mod + TESTS
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "tc.js"
        f.write_text(js, encoding="utf-8")
        done = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=300)
    try:
        o = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        o = {}
    check("node ran the page's renderer", bool(o), done.stderr[-800:])
    if o:
        check("a red SGR becomes a class, the reset ends it, and the producer's red makes the line an error", o["sgr16"] == "<pre><ln lv-err><a a-f1>red</> plain</>\n</>", o["sgr16"])
        check("bold + 256 colour (pure red lightened to 4.5:1), a too-dark true colour made readable, 22/39 reset bold and colour, a background",
              o["sgrmix"].startswith("<pre><ln><a a-b c=rgb(") and "rgb(255,0,0)" not in o["sgrmix"] and "rgb(10,10,10)" not in o["sgrmix"]
              and "</>Z<a a-g4>B</>" in o["sgrmix"], o["sgrmix"])
        check("an escape split across two reads still works", o["split"] == "<pre><ln lv-err><a a-f1>red</> ok</>\n</>", o["split"])
        check("a carriage return rewrites the line (progress bars)", o["cr"] == "100%\n", o["cr"])
        check("CR LF split across two reads is one line end", o["crlf"] == "a\nb\n", o["crlf"])
        check("cursor, erase, charset and save codes are removed", o["csi"] == "abcd\n", repr(o["csi"]))
        check("window titles and hyperlink codes are removed, the link text stays", o["osc"] == "xlink\n", repr(o["osc"]))
        check("hostile text stays text: no element but span/pre is ever created", o["hostile"] == "<script>alert(1)</script><img src=x onerror=alert(2)> &amp;\n" and o["tags"] == ["pre", "span"], o)
        check("a run-away escape sequence is dropped without hanging", o["longesc"] is True)
        check("an escape left unfinished at the end shows nothing of itself", o["dangling"] == "dangling ", repr(o["dangling"]))
        check("a PlasBench warning: amber marker on the line, the timestamp dimmed, the word marked",
              o["warnline"].startswith("<pre><ln lv-warn><ts>[2026-11-14 21:40:00] </>") and "<lw>WARNING</>" in o["warnline"], o["warnline"])
        check("the program's own red / green decide the type first", o["hints"] == ["ln lv-err", "ln lv-ok"], o["hints"])
        check("a traceback and its frames are one failure block; the next line is plain again",
              o["tb"] == ["ln lv-err", "ln lv-err blk", "ln lv-err blk", "ln lv-err blk", "ln"], o["tb"])
        check("headings, timestamps, warnings, details, notes, commands, answers, successes, exit codes, progress and output each get their type",
              o["types"] == ["ln lv-head", "ln", "ln lv-warn", "ln lv-det", "ln lv-info", "ln lv-cmd", "ln lv-you", "ln lv-ok", "ln lv-err", "ln", "ln"], o["types"])
        check("the rendered text equals the plain text (Copy gives no codes or markers)", o["plainEq"] is True, o["plain"])
        check("plain text: colour codes, carriage-return rewrites and titles removed", o["tcplain"] == "A\nB 99%\nCDE\n", repr(o["tcplain"]))
        check(f"three 100,000-character lines cost little ({o['longline_ms']} ms)", o["longline_ms"] < 3000 and o["longline_text"] > 300000, o["longline_ms"])
        check(f"200,000 lines in 256 KB pieces render in bounded time ({o['big_ms']} ms) and keep at most 50,000 lines with one note at the top",
              o["big_ms"] < 60000 and o["big_lines"] <= 50000 and "tc-cut" in o["big_first"] and o["big_last"] == "line 199999 of tool output with some text", o)
        check("the legend and the three modes are defined", o["types_n"] == 7 and o["modes"] == ["status", "full", "off"], o)
        check("a true colour too dark for the console is lightened to 4.5:1", o["readable"] is True)

# ---------------------------------------------------------------------------------------------------------------- the server and the shell
from plasbench import terminal as T  # noqa: E402
got = T.clean_output("\x1b[1;31mred\x1b[0m\x1b]0;title\x07 ok\x1b[2K\x1b[3;4H\x00\r\n", keep_colour=True)
check("the Terminal server keeps colour codes only (cursor, erase, title codes removed)", got == "\x1b[1;31mred\x1b[0m ok\n", repr(got))
check("without keep_colour everything is removed, as before", T.clean_output("\x1b[31mred\x1b[0m ok\r\n") == "red ok\n")
from plasbench.webui import utf8_cut  # noqa: E402
sample = "aé€😀".encode("utf-8")
check("a job-log read never ends inside a character (the next read starts at its first byte)",
      [utf8_cut(sample[:i]) for i in range(len(sample) + 1)] == [0, 0, 1, 0, 1, 2, 0, 1, 2, 3, 0])
bash = shutil.which("bash")
if bash and os.name == "posix":
    lib = (ROOT / "scripts" / "lib.sh").as_posix()

    def run_sh(extra):
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "PLASBENCH_COLOR")}
        env.update(extra)
        return subprocess.run([bash, "-c", f'source "{lib}"; warn "w"'], capture_output=True, env=env).stderr.decode()
    check("PLASBENCH_COLOR=1 forces colour, =0 turns it off", "\x1b[33m" in run_sh({"PLASBENCH_COLOR": "1"}) and "\x1b[" not in run_sh({"PLASBENCH_COLOR": "0"}))
else:
    print("  skip  bash (POSIX) not available: PLASBENCH_COLOR=0/1 not run here")
print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all terminal-colour checks passed'}")
sys.exit(1 if FAILED else 0)
