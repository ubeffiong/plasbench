#!/usr/bin/env python3
"""
docs/SCIENTIFIC_GUIDE.md must stay true to the code it describes.

  * its table of contents matches its headings (python/build_guide_toc.py);
  * every internal anchor and every relative file link resolves;
  * every configuration variable, command and scores.tsv column the guide names
    exists in the code, so a rename or removal cannot leave the guide describing
    something that is gone.
"""

import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(HERE).parent
sys.path.insert(0, str(ROOT / "python"))

import build_guide_toc as toc  # noqa: E402

GUIDE = ROOT / "docs" / "SCIENTIFIC_GUIDE.md"


def section(text, start, end):
    """Text from the heading containing `start` up to the heading containing `end`."""
    i = text.index(start)
    j = text.index(end, i + 1)
    return text[i:j]


def code_corpus():
    parts = []
    for folder in ("config", "scripts", "python", "plasbench", "adapters", "env"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".sh", ".py", ".tsv", ".yml", ".md", ".env"}:
                try:
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
    return "\n".join(parts)


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  [{detail}]" if detail and not condition else ""))

    text = GUIDE.read_text(encoding="utf-8")

    print("table of contents")
    check("the generated contents list matches the committed one", toc.with_toc(text) == text,
          "run: python python/build_guide_toc.py")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("the README's guide-contents list matches the guide's headings",
          toc.with_readme_toc(readme, text) == readme, "run: python python/build_guide_toc.py")
    heads = toc.headings(text)
    check("the guide has numbered top-level sections 1 to 19",
          [t.split(".")[0] for lvl, t, _ in heads if lvl == 2] == [str(n) for n in range(1, 20)])

    print("links")
    anchors = {slug for _, _, slug in heads}
    dead_anchor = sorted({a for a in re.findall(r"\]\(#([^)]+)\)", text) if a not in anchors})
    check("every internal anchor resolves", not dead_anchor, ", ".join(dead_anchor))
    missing = []
    for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)#]+)(?:#[^)]*)?\)", text):
        if not (GUIDE.parent / target).resolve().exists():
            missing.append(target)
    check("every relative file link exists", not missing, ", ".join(sorted(set(missing))))

    corpus = code_corpus()

    print("configuration variables named in section 15 exist in the code")
    config = section(text, "## 15. Configuration reference", "## 16.")
    names = sorted({n for n in re.findall(r"`([A-Z][A-Z0-9_]{3,})`", config) if "<" not in n})
    absent = [n for n in names if n not in corpus]
    check(f"all {len(names)} named variables are defined or read somewhere", not absent, ", ".join(absent))

    print("commands named in section 15 exist in the CLI")
    cli = (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8")
    commands = sorted({c for row in config.splitlines() if row.startswith("| ") and any(
        g in row for g in ("Run |", "Set up", "Cohorts |", "Experiments |", "Evidence |", "Metagenomics |"))
        for c in re.findall(r"`([a-z][a-z0-9-]+)`", row)})
    absent = [c for c in commands if f'"{c}"' not in cli and f"'{c}'" not in cli]
    check(f"all {len(commands)} named commands are registered", not absent, ", ".join(absent))

    print("scores.tsv columns named in section 13.2 exist in the code")
    columns_text = section(text, "### 13.2 The `scores.tsv` columns", "### 13.3")
    cols = sorted({c for c in re.findall(r"`([a-z][a-z0-9_]+)`", columns_text)})
    absent = [c for c in cols if c not in corpus]
    check(f"all {len(cols)} named columns appear in the scoring and merge code", not absent, ", ".join(absent))

    print("the scope statement is present and unambiguous")
    scope = section(text, "### 1.3 What it is not", "### 1.4")
    for must in ("identification", "transmission", "diagnostic"):
        check(f"section 1.3 says what it is not: {must}", must.lower() in scope.lower())
    matrix = section(text, "## 18. Scope matrix", "## 19.")
    check("the scope matrix marks transmission inference as not implemented", "Not implemented" in matrix)

    print()
    if not ok:
        print("GUIDE DOCUMENTATION TESTS FAILED")
        sys.exit(1)
    print("ALL GUIDE DOCUMENTATION TESTS PASSED")


if __name__ == "__main__":
    main()
