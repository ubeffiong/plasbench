"""Find the parts of PlasBench's own documentation that answer a question (the retrieval half of the AI help).

The index is plasbench/data/ai_kb.json.gz, built by python/build_ai_kb.py from the guides, the workflow and tool tables, the Settings, the metric help, the command line
and the failure signatures, and shipped inside the package. Ranking is BM25 over title and text with small boosts for what makes a support question exact: a command or
`--option` written as in the docs, an error message quoted from a log, and a few synonyms ("stuck", "stalled", "hang"). A misspelt word is matched to the nearest word the
index knows. No embeddings, no service, no network: standard library only.
"""
from __future__ import annotations

import difflib
import gzip
import json
import math
import re
import threading
from pathlib import Path

KB_FILE = Path(__file__).resolve().parent / "data" / "ai_kb.json.gz"
K1, B = 1.4, 0.72
TITLE_WEIGHT = 3          # a title word counts like this many text words
PHRASE_BONUS = 2.5        # a 3-word run of the question found verbatim in a chunk (an error message pasted from a log)
COMMAND_BONUS = 6.0       # the question names a plasbench command and the chunk describes it
LITERAL_BONUS = 5.0       # a `--option` or command written in the question found in the chunk
STOP = frozenset("a an the and or of to in on is are was were be been it its this that these those for with as at by from do does did how what why when where which who can could should would "
                 "i my me we you your our not no yes if then so than but about into over just also any all there have has had will".split())

# Words people use for the same thing as the documentation. Each key is added to (never replaces) the question's words.
SYNONYMS = {
    "stuck": ["stalled", "stall", "hang", "frozen"], "stalled": ["stuck", "stall", "hang"], "hang": ["stalled", "stuck", "stall"], "hangs": ["stalled", "stuck"], "hanging": ["stalled", "stuck"],
    "frozen": ["stalled", "stuck"], "freezes": ["stalled", "stuck"], "slow": ["stalled", "duration", "time"],
    "ram": ["memory"], "oom": ["memory", "killed"], "crash": ["failed", "fail", "error"], "crashed": ["failed", "fail", "error"], "crashes": ["failed", "error"], "broken": ["failed", "error"],
    "error": ["failed", "fail"], "errors": ["failed", "fail"], "fails": ["failed", "fail"],
    "install": ["installation"], "installation": ["install"], "delete": ["remove", "uninstall"], "uninstall": ["remove"], "setup": ["install"], "installing": ["install"],
    "quit": ["stop"], "kill": ["stop", "cancel"], "cancel": ["stop"],
    "readme": ["guide"], "csv": ["tsv", "sheet"], "spreadsheet": ["sheet", "tsv"], "reads": ["fastq", "reads"], "fastq": ["reads"],
    "win": ["windows"], "windows": ["wsl", "powershell"], "ubuntu": ["wsl"], "mac": ["macos"], "macbook": ["macos"],
    "precision": ["metric"], "recall": ["metric"], "f1": ["metric"], "cprr": ["metric", "recovery"], "score": ["metric"], "scoring": ["metric", "score"],
    "container": ["docker"], "containers": ["docker"], "image": ["docker", "image"],
    "pipeline": ["workflow", "stage"], "stage": ["workflow"], "stages": ["workflow", "stage"], "step": ["stage"], "steps": ["stage"],
    "login": ["sign"], "key": ["token"], "gpu": ["threads"], "cpu": ["threads"], "cores": ["threads"],
}
_WORD = re.compile(r"[a-z0-9][a-z0-9_.+-]*[a-z0-9]|[a-z0-9]", re.I)
_OPTION = re.compile(r"(?<![\w-])--?[a-z][a-z0-9-]{1,}")


def stem(w: str) -> str:
    if len(w) > 5 and w.endswith("ies"):
        return w[:-3] + "y"
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[:-len(suf)]
            if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":    # gzipped -> gzipp -> gzip, running -> runn -> run
                w = w[:-1]
            return w
    return w


def tokens(text: str) -> list:
    """Lower-case words, with `max_isolates`, `max-isolates` and `--max-isolates` also giving their parts; a lightly stemmed form."""
    out = []
    for m in _WORD.finditer((text or "").lower()):
        w = m.group(0).strip(".-+")
        if not w:
            continue
        parts = [p for p in re.split(r"[_.\-+]", w) if p]
        for p in ([w] if len(parts) > 1 else []) + parts:
            if p in STOP or len(p) < 2 and not p.isdigit():
                continue
            out.append(stem(p))
    return out


def norm_words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


class KB:
    def __init__(self, chunks: list):
        self.chunks = chunks
        self.tf, self.len, self.df = [], [], {}
        self.norm = []
        for c in chunks:
            toks = tokens(" ".join(c["title"].split(" > ")[-2:])) * TITLE_WEIGHT + tokens(c["text"])   # the last two heading levels: the guide's own title is in every chunk and says nothing
            counts = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            self.len.append(len(toks))
            for t in counts:
                self.df[t] = self.df.get(t, 0) + 1
            self.norm.append(" " + " ".join(norm_words(c["title"] + " " + c["text"])) + " ")
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
        self.n = len(chunks)
        self.vocab = [t for t, d in self.df.items() if d >= 2 and len(t) >= 5]
        self.postings = {}
        for i, counts in enumerate(self.tf):
            for t in counts:
                self.postings.setdefault(t, []).append(i)

    def idf(self, t: str) -> float:
        d = self.df.get(t, 0)
        return math.log(1 + (self.n - d + 0.5) / (d + 0.5))

    def expand(self, query: str) -> dict:
        """term -> weight: the question's words (a misspelling mapped to the nearest known word) and their synonyms at half weight."""
        weights = {}
        for t in tokens(query):
            if t not in self.df and len(t) >= 5:
                near = difflib.get_close_matches(t, self.vocab, n=1, cutoff=0.82)
                if near:
                    t = near[0]
            weights[t] = max(weights.get(t, 0), 1.0)
        for raw in re.findall(r"[a-z0-9]+", query.lower()):
            for s in SYNONYMS.get(raw, ()):
                s = stem(s)
                weights[s] = max(weights.get(s, 0), 0.5)
        return weights

    def score_all(self, query: str, hint: str = "") -> dict:
        weights = self.expand(query)
        scores = {}
        for t, wq in weights.items():
            idf = self.idf(t)
            for i in self.postings.get(t, ()):
                f = self.tf[i][t]
                scores[i] = scores.get(i, 0.0) + wq * idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * self.len[i] / self.avg))
        if not scores:
            return scores
        q_low = query.lower()
        literals = [m.group(0) for m in _OPTION.finditer(q_low)] + [c.strip() for c in re.findall(r"`([^`]{2,80})`", q_low)]
        qw = norm_words(query)
        qset = set(re.findall(r"[a-z0-9-]+", q_low))
        grams = {" ".join(qw[i:i + 3]) for i in range(len(qw) - 2)} if len(qw) >= 3 else set()
        for i in list(scores):
            text_low = self.chunks[i]["text"].lower()
            for lit in literals:
                if lit and lit in text_low:
                    scores[i] += LITERAL_BONUS
            if grams:
                hit = sum(1 for g in grams if " " + g + " " in self.norm[i])
                if hit:
                    scores[i] += PHRASE_BONUS * min(hit, 5)
            if self.chunks[i]["kind"] == "cli":
                name = re.match(r"Command: plasbench ([a-z0-9-]+)", self.chunks[i]["title"])
                if name and name.group(1) in qset:
                    scores[i] += COMMAND_BONUS
            if hint and self.chunks[i]["kind"] == "troubleshooting":
                scores[i] *= 1.15
        return scores

    def search(self, query: str, k: int = 5, hint: str = "", per_source: int = 2, max_overlap: float = 0.6) -> list:
        """The k best chunks, best first: at most `per_source` from one section, none that mostly repeats a better one."""
        scores = self.score_all(query, hint)
        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        picked, seen_sets, per = [], [], {}
        for i in ranked:
            c = self.chunks[i]
            key = (c["src"], c["anchor"])
            if per.get(key, 0) >= per_source:
                continue
            ts = set(self.tf[i])
            if any(len(ts & o) / max(1, min(len(ts), len(o))) > max_overlap for o in seen_sets):
                continue
            picked.append(dict(c, score=round(scores[i], 3)))
            seen_sets.append(ts)
            per[key] = per.get(key, 0) + 1
            if len(picked) >= k:
                break
        return picked


_LOCK = threading.Lock()
_CACHE = {}


def load(path=None) -> KB:
    """The shipped index (read once). Raises FileNotFoundError when the package has no index."""
    path = Path(path) if path else KB_FILE
    with _LOCK:
        key = str(path)
        sig = (path.stat().st_mtime_ns, path.stat().st_size)
        got = _CACHE.get(key)
        if got and got[0] == sig:
            return got[1]
        with gzip.open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        kb = KB(data["chunks"])
        _CACHE[key] = (sig, kb)
        return kb


def available() -> bool:
    return KB_FILE.is_file()
