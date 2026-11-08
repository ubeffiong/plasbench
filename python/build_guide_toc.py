#!/usr/bin/env python3
"""
build_guide_toc.py -- keep the Scientific Guide's contents lists in step with its
headings.

docs/SCIENTIFIC_GUIDE.md is long, and a contents list that has drifted from the
headings sends a reader to the wrong place. The list between <!-- TOC --> and
<!-- /TOC --> is generated here from the "##" and "###" headings (outside code
fences), with the anchors GitHub gives them.

The README carries a shorter list (top-level sections only) between
<!-- GUIDE-TOC --> and <!-- /GUIDE-TOC -->, generated from the same headings so
the two cannot disagree.

test/test_guide_docs.py fails if either committed list differs from this script's
output, or if any internal link in the guide is dead.

Usage:
  build_guide_toc.py [--check] [guide] [readme]
      (defaults: docs/SCIENTIFIC_GUIDE.md and README.md)

Standard library only.
"""

import argparse
import re
import sys
from pathlib import Path

OPEN, CLOSE = "<!-- TOC -->", "<!-- /TOC -->"
README_OPEN, README_CLOSE = "<!-- GUIDE-TOC -->", "<!-- /GUIDE-TOC -->"
GUIDE_LINK = "docs/SCIENTIFIC_GUIDE.md"
HEADING = re.compile(r"^(#{2,3}) +(.+?) *$")


def slugify(text):
    """GitHub's heading anchor: lower-case, drop punctuation, spaces to hyphens."""
    text = text.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def headings(markdown):
    """[(level, text, slug)] for ## and ### headings outside code fences."""
    found, seen, in_fence = [], {}, False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        match = None if in_fence else HEADING.match(line)
        if not match:
            continue
        text = match.group(2)
        slug = slugify(text)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.append((len(match.group(1)), text, slug if not count else f"{slug}-{count}"))
    return found


def render_toc(markdown):
    lines = []
    for level, text, slug in headings(markdown):
        label = text.replace("`", "")
        lines.append(f"{'  ' * (level - 2)}- [{label}](#{slug})")
    return "\n".join(lines)


def current_block(markdown):
    match = re.search(re.escape(OPEN) + r"\n(.*?)\n" + re.escape(CLOSE), markdown, re.S)
    return match.group(1) if match else None


def with_toc(markdown):
    """The guide with its contents list regenerated (markers added if absent)."""
    # The contents must not list itself, so build it from the document without a block.
    stripped = re.sub(re.escape(OPEN) + r".*?" + re.escape(CLOSE), "<!--TOC-->", markdown, flags=re.S)
    if "<!--TOC-->" not in stripped:
        raise SystemExit("ERROR: no <!--TOC--> placeholder or <!-- TOC --> block found")
    block = f"{OPEN}\n{render_toc(stripped)}\n{CLOSE}"
    return stripped.replace("<!--TOC-->", block, 1)


def readme_list(guide_text):
    """Numbered list of the guide's top-level sections, linked into the guide."""
    stripped = re.sub(re.escape(OPEN) + r".*?" + re.escape(CLOSE), "", guide_text, flags=re.S)
    lines = []
    for level, text, slug in headings(stripped):
        if level == 2:
            number, _, title = text.partition(". ")
            lines.append(f"{number}. [{title.replace('`', '')}]({GUIDE_LINK}#{slug})")
    return "\n".join(lines)


def with_readme_toc(readme_text, guide_text):
    """The README with its guide-contents list regenerated."""
    pattern = re.escape(README_OPEN) + r".*?" + re.escape(README_CLOSE)
    if not re.search(pattern, readme_text, flags=re.S):
        raise SystemExit(f"ERROR: README has no {README_OPEN} ... {README_CLOSE} block")
    block = f"{README_OPEN}\n{readme_list(guide_text)}\n{README_CLOSE}"
    return re.sub(pattern, lambda _: block, readme_text, count=1, flags=re.S)


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("guide", nargs="?", default=str(root / "docs" / "SCIENTIFIC_GUIDE.md"))
    ap.add_argument("readme", nargs="?", default=str(root / "README.md"))
    ap.add_argument("--check", action="store_true", help="exit 1 if either contents list is stale; write nothing")
    args = ap.parse_args()
    guide_path, readme_path = Path(args.guide), Path(args.readme)
    guide = guide_path.read_text(encoding="utf-8")
    new_guide = with_toc(guide)
    readme = readme_path.read_text(encoding="utf-8")
    new_readme = with_readme_toc(readme, new_guide)
    stale = [p for p, old, new in ((guide_path, guide, new_guide), (readme_path, readme, new_readme)) if old != new]
    if args.check:
        for path in stale:
            print(f"{path}: contents list is out of date; run python/build_guide_toc.py", file=sys.stderr)
        if not stale:
            print("guide and README contents lists are current")
        return 1 if stale else 0
    for path, new in ((guide_path, new_guide), (readme_path, new_readme)):
        if path in stale:
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"{path}: contents list updated")
    if not stale:
        print("guide and README contents lists already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
