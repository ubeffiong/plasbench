#!/usr/bin/env python3
"""
The reference-figure folder: tracked README, untracked third-party images.

  - docs/images/reference/README.md exists and maps each of the four images (1.jpg to 4.jpg) to the feature it inspires;
  - .gitignore ignores the images in that folder but not the README (so third-party figures are never committed or shipped);
  - git itself agrees when this is a git checkout: the images are ignored, the README is not.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "images" / "reference"


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    readme = (FOLDER / "README.md").read_text(encoding="utf-8") if (FOLDER / "README.md").is_file() else ""
    check("the folder has a README", bool(readme))
    check("it maps every image to the feature it inspires", all(f"`{n}.jpg`" in readme for n in (1, 2, 3, 4)) and "identity ring" in readme and "radar" in readme.lower())
    check("it says the images are third-party and not committed", "not committed" in readme and "third-party" in readme)
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(".gitignore ignores the images but keeps the README", "docs/images/reference/*.jpg" in ignore and "!docs/images/reference/README.md" in ignore)
    if (ROOT / ".git").exists():
        def ignored(path):
            return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
        check("git ignores an image in the folder", ignored("docs/images/reference/1.jpg"))
        check("git does not ignore the README", not ignored("docs/images/reference/README.md"))

    print()
    if not ok:
        print("REFERENCE IMAGES TESTS FAILED")
        sys.exit(1)
    print("ALL REFERENCE IMAGES TESTS PASSED")


if __name__ == "__main__":
    main()
