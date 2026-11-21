"""Measure retrieval on the gold sets (a helper for test_ai_kb.py and for reports; run it by hand: python test/ai_gold_eval.py).

In-sample set: test/fixtures/ai_gold.tsv (51 questions; synonyms and boosts were tuned while it was open).
Held-out set: test/fixtures/ai_gold_heldout.tsv (written before the hardening pass; never used to tune anything). Rows whose source is "-" need no PlasBench excerpt (general
knowledge, off topic, too vague): for them the measure is how many excerpts the assistant would send (fewer is better).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def rows(name):
    out = []
    for line in (ROOT / "test" / "fixtures" / name).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            p = line.split("\t")
            out.append((p[0], p[1] if len(p) > 1 else "", p[2] if len(p) > 2 else ""))
    return out


def evaluate(kb, name, k=3, search=None):
    """{"n", "hit", "rate", "misses": [...], "neg_n", "neg_sent_avg"} for one gold file. `search(question)` returns the excerpts the assistant would send (default: kb.search top k)."""
    search = search or (lambda q: kb.search(q, 5))
    pos = [r for r in rows(name) if r[1] != "-"]
    neg = [r for r in rows(name) if r[1] == "-"]
    hit, misses = 0, []
    for q, src, phrase in pos:
        want = set(src.split("|"))
        got = search(q)[:k]
        ok = any(h["src"] in want and (not phrase or phrase in (h["title"] + " " + h["text"]).lower()) for h in got)
        hit += ok
        if not ok:
            misses.append(q)
    sent = [len(search(q)) for q, _s, _t in neg]
    return {"n": len(pos), "hit": hit, "rate": hit / max(1, len(pos)), "misses": misses, "neg_n": len(neg), "neg_sent_avg": (sum(sent) / len(sent)) if sent else 0.0}


if __name__ == "__main__":
    from plasbench import ai_kb
    kb = ai_kb.load()
    for f in ("ai_gold.tsv", "ai_gold_heldout.tsv"):
        r = evaluate(kb, f)
        print(f, "hit@3 %d/%d = %.0f%%" % (r["hit"], r["n"], 100 * r["rate"]), "| no-source questions: %d, excerpts sent on average %.1f" % (r["neg_n"], r["neg_sent_avg"]))
        for m in r["misses"]:
            print("   miss:", m)
