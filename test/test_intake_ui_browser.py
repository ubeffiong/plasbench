#!/usr/bin/env python3
"""The "Your own isolates" page in a REAL browser (test/intake_ui_browser.mjs): add a folder, find the isolates, place them, run the quick test, label the undecided
sequences in the dialog, and reach "Benchmark this sheet". Needs Node 22+ and Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1.
"""
import gzip
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def genome(seed, length):
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(length))


def fasta(path, records):
    path.write_text("".join(f">{h}\n{s}\n" for h, s in records), encoding="utf-8")


def reads(path, seq, seed, n=300, length=100):
    rng = random.Random(seed)
    with gzip.open(path, "wt") as handle:
        for i in range(n):
            start = rng.randrange(0, len(seq) - length)
            handle.write(f"@r{i}\n{seq[start:start + length]}\n+\n{'I' * length}\n")


def main():
    if os.environ.get("PLASBENCH_BROWSER_TESTS") != "1":
        print("  skip  set PLASBENCH_BROWSER_TESTS=1 to run the real-browser checks of Your own isolates (needs Node 22+ and Chrome or Edge)")
        print("ALL INTAKE UI BROWSER TESTS PASSED (skipped)")
        return 0
    from plasbench import appwindow
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  skip  node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "my_isolates"
    src.mkdir()
    chromosome, plasmid, other = genome(1, 60000), genome(2, 4000), genome(3, 60000)
    reads(src / "KP01_R1.fastq.gz", chromosome, 1)
    reads(src / "KP01_R2.fastq.gz", chromosome, 1)
    fasta(src / "KP01.fna", [("NZ_1.1 Klebsiella pneumoniae strain A chromosome, complete genome", chromosome), ("NZ_2.1 Klebsiella pneumoniae strain A plasmid pA, complete sequence", plasmid)])
    reads(src / "EC02_R1.fastq.gz", other, 2)
    reads(src / "EC02_R2.fastq.gz", other, 2)
    fasta(src / "EC02.fna", [("seq_a", other), ("seq_b", plasmid)])   # headers say nothing: the labels are the person's decision
    sheet, data = tmp / "sheet.tsv", tmp / "data"
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), HOME=str(tmp), USERPROFILE=str(tmp), PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", "8881", "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(80):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--remote-debugging-port=9334", f"--user-data-dir={tmp}/chrome", "--window-size=1280,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen("http://127.0.0.1:9334/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        done = subprocess.run([node, str(ROOT / "test" / "intake_ui_browser.mjs"), url, str(src), str(sheet), str(data), str(tmp / "isolates.png")], capture_output=True, text=True, timeout=400)
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-800:])
        print(f"screenshots: {tmp}")
        return done.returncode
    finally:
        chrome.kill()
        server.kill()


if __name__ == "__main__":
    sys.exit(main())
