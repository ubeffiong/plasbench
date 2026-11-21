#!/usr/bin/env python3
"""No secret of the AI help sign-in is in the repository: no Google client secret, no OpenRouter or Hugging Face key, no long client_secret value; the ignore file keeps local
credential files out; no code reads a client secret from the repository; and the AI help holds no key of its own (the keys are the person's, stored under ~/.plasbench/ai).
The patterns are built in pieces so that this file does not match itself."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


PATTERNS = {
    "a Google client secret": re.compile("GOC" + "SPX-[A-Za-z0-9_-]{6,}"),
    "an OpenRouter key": re.compile("sk-" + "or-v1-(?!FAKE|ABC)[A-Za-z0-9]{20,}"),
    "a Hugging Face token": re.compile(r"(?<![A-Za-z0-9_])hf" + "_(?!oauth_FAKE|AbCd|ABCD)[A-Za-z0-9]{30,}"),
    "a long client_secret value": re.compile(r"client" + r"_secret[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']"),
    "a Google OAuth client id": re.compile(r"[0-9]{9,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com"),
}
try:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
except (OSError, subprocess.CalledProcessError):
    files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
files += ["plasbench/data/ai_kb.json.gz"]
import gzip  # noqa: E402

bad = []
for rel in sorted(set(files)):
    p = ROOT / rel
    if not p.is_file() or p.stat().st_size > 8 * 2**20 or p.suffix in (".png", ".jpg", ".jpeg", ".docx", ".pdf", ".xlsx", ".woff2", ".ico", ".zip", ".bam", ".cram"):
        continue
    try:
        text = gzip.decompress(p.read_bytes()).decode("utf-8", "replace") if p.suffix == ".gz" and p.name.startswith("ai_kb") else p.read_bytes().decode("utf-8", "replace")
    except OSError:
        continue
    for name, rx in PATTERNS.items():
        if rx.search(text):
            bad.append(f"{rel}: {name}")
check("no secret-looking value in any tracked file", not bad, bad[:5])
gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
for entry in ("*.oauth.json", "google-client.json", "openrouter.json", "huggingface.json"):
    check(f".gitignore lists {entry}", re.search(r"^" + re.escape(entry) + r"\s*$", gi, re.M))
code = "\n".join((ROOT / "plasbench" / n).read_text(encoding="utf-8") for n in ("ai_openrouter.py", "ai_providers.py", "ai_help.py", "ai_cli.py", "ai_actions.py", "ai_prompt.py"))
check("no Google sign-in code or host in the AI help", not re.search(r"accounts\.google|googleapis|google-client", code, re.I))
check("no key literal in the code (keys come from the stored file only)", not re.search(r"[\"']sk-or-[A-Za-z0-9_-]{8,}|[\"']hf_[A-Za-z0-9_]{12,}", code))
tsv = (ROOT / "config" / "network_services.tsv").read_text(encoding="utf-8")
check("the network table has OpenRouter and Hugging Face, and no Google host", "openrouter.ai" in tsv and "router.huggingface.co" in tsv and "google" not in tsv.lower().replace("googleapis_none", ""))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
