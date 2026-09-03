#!/usr/bin/env python3
"""Every inline script in the report must parse.

A script that fails to parse emits nothing and reports nothing: the browser
drops it silently and the panel it owned simply never appears. Four fragments
were dead this way -- the dot plot, protein recovery, structural diagnostics
and the whole score-table filter block -- for two reasons that both look
harmless in the Python source:

  * a forEach whose closing paren was missing, and
  * '\\n' written into an f-string, which Python turns into a real newline
    inside a single-quoted JavaScript string.

Nothing in the suite noticed, because the markers those panels are asserted on
are emitted by the report builder whether or not the script ever runs.
"""

import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

# Scripts the browser never executes as JavaScript.
DATA_TYPES = ("application/json", "text/template")
SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.S)


def inline_scripts(page):
    """Executable inline scripts, excluding the embedded iframe documents."""
    # The vendored designs are carried inside text/template and are parsed by
    # the browser only after being handed to srcdoc, so strip them whole first.
    page = re.sub(r"<script[^>]*type=['\"]text/template['\"][^>]*>.*?</script>",
                  "", page, flags=re.S)
    out = []
    for attrs, body in SCRIPT.findall(page):
        if any(kind in attrs for kind in DATA_TYPES):
            continue
        if body.strip():
            out.append(body)
    return out


def unterminated_string(body):
    """Find a quoted JS string broken across lines.

    This is what an unescaped ``\\n`` in an f-string produces, and it is worth
    catching without a JavaScript engine because it is the easier mistake to
    make and the harder one to see.
    """
    for number, line in enumerate(body.split("\n"), 1):
        index, quote = 0, None
        while index < len(line):
            char = line[index]
            if quote is None:
                # An apostrophe in a comment is prose, not an open string.
                if char == "/" and line[index + 1:index + 2] == "/":
                    break
                if char in "\"'":
                    quote = char
            elif char == "\\":
                index += 1
            elif char == quote:
                quote = None
            index += 1
        if quote is not None:
            # Template literals legitimately span lines; plain quotes do not.
            if quote in "\"'" and line.count("`") % 2 == 0:
                return number, line.strip()[:120]
    return None


def main():
    with tempfile.TemporaryDirectory(prefix="report_js_") as tmp:
        results = os.path.join(tmp, "results")
        sample_dir = os.path.join(results, "s1")
        os.makedirs(sample_dir)
        # Most fragments are only emitted once there is a visualization payload
        # to drive them, so the fixture has to produce one.
        truth = os.path.join(tmp, "truth.tsv")
        rows = [["sequence_id", "molecule_type", "length"],
                ["chr1", "CHROMOSOME", 8000], ["pA", "PLASMID", 2000], ["pB", "PLASMID", 1500]]
        with open(truth, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t").writerows(rows)
        paf = [("q1", 2000, 0, 2000, "+", "pA", 2000, 0, 2000),
               ("q2", 1500, 0, 1500, "+", "pB", 1500, 0, 1500),
               ("q3", 400, 0, 400, "+", "chr1", 8000, 0, 400)]
        with open(os.path.join(sample_dir, "toolx.pred_vs_ref.paf"), "w",
                  newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t").writerows(
                [list(row) + [100, 100, 60] for row in paf])
        subprocess.run([sys.executable, os.path.join(ROOT, "python", "build_visualization_data.py"),
                        "--truth", truth, "--results-dir", results, "--sample", "s1",
                        "--out", os.path.join(sample_dir, "visualization", "alignment_blocks.json")],
                       check=True, capture_output=True)
        scores = os.path.join(results, "scores.tsv")
        with open(scores, "w", encoding="utf-8") as handle:
            handle.write("sample\ttool\ttrue_plasmid_bp\tTP_bp\tFP_bp\tFN_bp\t"
                         "unmapped_pred_bp\tplasmid_recall\tprecision\trecall\tf1\n")
            handle.write("s1\ttoolx\t3500\t3500\t400\t0\t0\t1.0000\t0.8974\t1.0000\t0.9459\n")
        leaderboard = os.path.join(results, "benchmark.leaderboard.tsv")
        with open(leaderboard, "w", encoding="utf-8") as handle:
            handle.write("rank\ttool\tn_samples\tn_completed\tn_failed\tn_skipped\t"
                         "mean_precision\tmean_recall\tmean_plasmid_recall\tmean_bin_f1\t"
                         "mean_f1\tf1_ci_low\tf1_ci_high\tmedian_f1\n")
            handle.write("1\ttoolx\t1\t1\t0\t0\t0.8974\t1.0000\t1.0000\t\t"
                         "0.9459\t0.9459\t0.9459\t0.9459\n")
        out = os.path.join(results, "report.html")
        subprocess.run([sys.executable, os.path.join(ROOT, "python", "build_html_report.py"),
                        "--project-root", ROOT, "--scores", scores,
                        "--tool-status", os.path.join(results, "absent.tsv"),
                        "--leaderboard", leaderboard, "--out", out],
                       check=True, capture_output=True)
        page = open(out, encoding="utf-8").read()

    scripts = inline_scripts(page)
    assert len(scripts) >= 10, f"only {len(scripts)} inline scripts found; extraction is wrong"

    # Always available: a quoted string that never closes on its line.
    for index, body in enumerate(scripts, 1):
        broken = unterminated_string(body)
        assert not broken, (
            f"inline script #{index} has a string broken across lines at line "
            f"{broken[0]}: {broken[1]!r}. A '\\n' in an f-string becomes a real "
            "newline; write '\\\\n' so the browser receives the escape.")

    # A real parse, when a JavaScript engine is available.
    node = shutil.which("node")
    if not node:
        print(f"ALL REPORT JAVASCRIPT TESTS PASSED ({len(scripts)} scripts, "
              "string check only: node not found)")
        return

    with tempfile.TemporaryDirectory(prefix="report_js_parse_") as tmp:
        failures = []
        for index, body in enumerate(scripts, 1):
            path = os.path.join(tmp, f"script_{index}.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
            done = subprocess.run([node, "--check", path],
                                  capture_output=True, text=True)
            if done.returncode != 0:
                head = body.strip().replace("\n", " ")[:110]
                failures.append(f"#{index}: {done.stderr.strip().splitlines()[-1]}\n"
                                f"      starts: {head}")
        assert not failures, (
            "inline scripts failed to parse and would emit nothing at all:\n  "
            + "\n  ".join(failures))

    print(f"ALL REPORT JAVASCRIPT TESTS PASSED ({len(scripts)} inline scripts parse)")


if __name__ == "__main__":
    main()
