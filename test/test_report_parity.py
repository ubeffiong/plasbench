#!/usr/bin/env python3
"""Parity between the sample report (docs/sample_report, built from the demo) and a report built the way a real run builds it.

A real run builds its report in stage 6 (scripts/06_aggregate.sh); the demo (test/run_demo.sh) builds the sample with its own arguments. This test keeps the two from
drifting apart for reasons that are not missing data:

  * the arguments of build_html_report.py in run_demo.sh are those of scripts/06_aggregate.sh, except the ones that need an external tool or a real run
    (OPTIONAL_REAL_ONLY) and the opt-in dashboard flag (DEMO_ONLY);
  * a report built from results_real_cohort1 with the pipeline's own argument list holds the same sections, in the same order, with the same headings as the sample;
    a section the sample has and the real-cohort report lacks must be listed in that report's "Not run in this run" block with its reason (a section never disappears
    silently), or be an opt-in section (OPT_IN);
  * the sample shows the sections the demo can produce (candidate multiplicity, ranking stability, reference evidence), not a "Not run" note for them;
  * no two figure style sheets define the same class name unless the pair is listed in SHARED_CLASSES (a prefix shared by two figures once made the fingerprint's styles
    resize and overlap the presence matrix).

Plain script. The real-cohort build is skipped with a printed reason when results_real_cohort1 is absent.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(label, condition, detail=""):
    global ok
    ok &= bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))


# Flags of the stage-6 report call that the demo cannot pass (they need an external tool, an orthogonal validation run or a failed-scoring table).
OPTIONAL_REAL_ONLY = {"--quast-diagnostics", "--orthogonal-summary", "--score-failures"}
DEMO_ONLY = {"--embed-dashboard"}                       # opt-in in a real run (REPORT_EMBED_DASHBOARD=1): the sample shows the dashboard so every feature can be seen
OPT_IN = {"enterprise"}                                 # sections that exist only when that flag is given; the real report says so under 'Optional analyses not run'


def report_flags(text, start_marker):
    """The --flags of one shell command (it continues over lines that end in a backslash)."""
    out = []
    for line in text[text.index(start_marker):].splitlines():
        out.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return set(re.findall(r"--[a-z][a-z-]*", " ".join(out)))


def sections(page):
    """[(id, heading)] of every <section> with an <h2>, in page order."""
    out = []
    for m in re.finditer(r"<section\b[^>]*\bid=['\"]([^'\"]+)['\"][^>]*>(.*?)(?=<section\b|$)", page, re.S):
        h = re.search(r"<h2[^>]*>([^<]*)", m.group(2)[:4000])
        out.append((m.group(1), h.group(1).strip() if h else ""))
    return out


def notrun_ids(page):
    return set(re.findall(r"<li id='([^']+)' data-notrun='", page))


demo_sh = (ROOT / "test" / "run_demo.sh").read_text(encoding="utf-8")
agg_sh = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
demo_flags = report_flags(demo_sh, 'python3 "$PY/build_html_report.py"')
real_flags = report_flags(agg_sh, 'python3 "$HERE/../python/build_html_report.py"')
check("the demo passes every report argument that stage 6 passes, except those that need an external tool or a real run",
      real_flags - demo_flags <= OPTIONAL_REAL_ONLY, sorted(real_flags - demo_flags - OPTIONAL_REAL_ONLY))
check("the demo passes no report argument that stage 6 does not, except the opt-in dashboard", demo_flags - real_flags <= DEMO_ONLY | {"--embed-dashboard"}, sorted(demo_flags - real_flags - DEMO_ONLY))
check("the demo runs the advisory stage-5/6 jobs whose sections the sample must show", all(w in demo_sh for w in (
    "candidate_multiplicity.py", "benchmark.candidate_multiplicity.tsv", "ranking_stability.py", "reference_evidence_audit.py")))

sample_path = ROOT / "docs" / "sample_report" / "benchmark.report.html"
sample = sample_path.read_text(encoding="utf-8") if sample_path.is_file() else ""
sample_sections = sections(sample)
check("the sample report is present and has sections", len(sample_sections) > 30)
sample_notrun = notrun_ids(sample)
for sid in ("learn-multiplicity", "learn-refaudit", "learn-stability"):
    check(f"the sample shows {sid}, not a 'Not run' note", sid not in sample_notrun and any(i == sid for i, _h in sample_sections), sid)
check("the sample's multiplicity section is the compact one, and its folds start closed (the layout pass opens every fold that is not marked data-closed)",
      "mx-tool" in sample and "class='mx-bar mx-oc'" in sample and not re.search(r"<details[^>]*open[^>]*mx-(tool|track|all)", sample) and not re.search(r"<details[^>]*mx-(tool|track|all)[^>]*open", sample))

# ------------------------------------------------------------------------------------------------ a report built with the pipeline's own argument list
COHORT = ROOT / "results_real_cohort1"
if COHORT.is_dir() and sample:
    with tempfile.TemporaryDirectory() as work:
        res = Path(work) / "results"
        shutil.copytree(COHORT, res, ignore=shutil.ignore_patterns("benchmark.report.html"))
        data = Path(work) / "data"
        data.mkdir()
        a = agg_sh.index('python3 "$HERE/../python/build_html_report.py"')
        block = agg_sh[a:agg_sh.index('log "Stage 6 complete."', a)]
        cmd = [sys.executable, str(ROOT / "python" / "build_html_report.py"), "--project-root", str(ROOT)]
        for flag, var, rest in re.findall(r'(--[a-z-]+) "\$([A-Z_]+)(?:/([^"]+))?"', block):
            if var == "RESULTS_DIR":
                cmd += [flag, str(res / rest)]
            elif var == "DATA_DIR":
                cmd += [flag, str(data)]
            elif var == "SCORES":
                cmd += [flag, str(res / "scores.tsv")]
            elif var == "SAMPLE_SHEET":
                cmd += [flag, str(res / "samples.tsv")]
        out = res / "benchmark.report.html"
        run = subprocess.run(cmd + ["--out", str(out)], capture_output=True, text=True, encoding="utf-8",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
        check("a report builds with the pipeline's argument list", run.returncode == 0, run.stderr[-500:])
        if run.returncode == 0:
            real = out.read_text(encoding="utf-8")
            real_sections = sections(real)
            rid, sid_ = [i for i, _h in real_sections], [i for i, _h in sample_sections]
            real_notrun = notrun_ids(real)
            missing = [i for i in sid_ if i not in rid]
            silent = [i for i in missing if i not in real_notrun and i not in OPT_IN]
            check("every section of the sample that the real-cohort report lacks is listed there as 'Not run' with a reason (or is opt-in)", not silent, silent)
            extra = [i for i in rid if i not in sid_]
            check("the real-cohort report has no section the sample lacks", not extra, extra)
            common_real = [i for i in rid if i in sid_]
            common_sample = [i for i in sid_ if i in rid]
            check("the sections both have come in the same order", common_real == common_sample, [x for x in zip(common_real, common_sample) if x[0] != x[1]][:3])
            ha, hb = dict(real_sections), dict(sample_sections)
            diff = [(i, ha[i], hb[i]) for i in common_real if ha[i] != hb[i]]
            check("the sections both have carry the same headings", not diff, diff[:3])
            check("a 'Not run' section names its reason", all(re.search(r"<li id='%s' data-notrun='[^']*'><strong>[^<]+</strong>\s*[^<\s]" % re.escape(i), real) for i in real_notrun))
            print(f"  INFO: sample has {len(sid_)} sections, the real-cohort report {len(rid)}; not run there: {sorted(real_notrun)}")
else:
    print("  SKIPPED: results_real_cohort1 is absent, so no real-run report was built")

# ------------------------------------------------------------------------------------------------ compact, non-overlapping figures
read = lambda name: (ROOT / "assets" / "report" / name).read_text(encoding="utf-8")  # noqa: E731
fingerprint = "".join(read(n) for n in ("fig_fingerprint_style.html", "fig_fingerprint_ui.html", "fig_fingerprint_core.html")) + (ROOT / "python" / "report_fig_fingerprint.py").read_text(encoding="utf-8")
check("the fingerprint uses its own class prefix (fpr-), never the presence matrix's fp-", not re.search(r"(?<![A-Za-z0-9_])fp-", fingerprint))
check("the fingerprint has a tile size control and keeps every tile a whole element", "fpr-sizes" in fingerprint and "--fpr-tile" in fingerprint and "overflow:hidden" in read("fig_fingerprint_style.html"))
presence = read("fig_presence_core.html") + (ROOT / "python" / "report_fig_presence.py").read_text(encoding="utf-8")
check("the presence matrix draws its group titles slanted in a header band of their own (long titles never overlap)", presence.count("rotate(-40)") >= 2 and "TITH" in presence and "text-anchor='middle'>{rc.esc(b['l'])}" not in presence)
landscape = read("fig_landscape_ui.html") + read("fig_landscape_style.html")
check("the 3D landscape starts compact (panel closed, chart at most 300 px high) with a switch to the larger view", "open: false" in landscape and "data-act=\"size\"" in landscape and "max-height:300px" in landscape)

i_root, i_script = sample.find("id='fp-root'"), sample.find("presence/absence matrix, DOM glue")
check("in the sample the presence matrix's root element comes before its script (the script finds the root by id when it runs), and the id is unique", 0 <= i_root < i_script and sample.count("id='fp-root'") == 1)

# ------------------------------------------------------------------------------------------------ class names shared by two figure style sheets
SHARED_CLASSES = {"ct-btn", "ct-rowstat", "panel", "pb-iso", "pb-js", "rpt-figure", "rpt-info", "rpt-iso-slot", "rpt-on", "v3-svg"} | {f"ct-s{i}" for i in range(10)}
owners = {}
for path in sorted(glob.glob(str(ROOT / "assets" / "report" / "*_style.html"))):
    css = re.sub(r"/\*.*?\*/", "", Path(path).read_text(encoding="utf-8"), flags=re.S)
    for sel in re.findall(r"([^{}]+)\{", css):
        for name in re.findall(r"\.([A-Za-z][A-Za-z0-9_-]*)", sel):
            owners.setdefault(name, set()).add(os.path.basename(path))
clash = sorted((n, sorted(o)) for n, o in owners.items() if len(o) > 1 and n not in SHARED_CLASSES)
check("no two figure style sheets define the same class name (a shared prefix makes one figure restyle the other)", not clash, clash[:5])

print()
if not ok:
    print("REPORT PARITY TESTS FAILED")
    sys.exit(1)
print("ALL REPORT PARITY TESTS PASSED")
