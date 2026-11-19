#!/usr/bin/env python3
"""The short-read QC panel (python/report_readqc_panel.py): builders, threshold gauges, empty and absent states, escaping, print layout markers,
the toolbar, the side panel, the sub-navigation, the "All values" fold, and a build of the demo and of results_real_cohort1.

Hand-made fixtures so every figure can be checked. A page with no table says "Not measured in this run" with the command that produces it;
a synthetic table says so; every sub-section is written out statically so the PDF export prints all of them.
"""
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_readqc_panel as qp  # noqa: E402
import report_reviewers as rv  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


def qc(sample, status, reasons="", pairs="2000000", depth="120", q="35", q30="0.9", length="150", gc="50.5", dup="0.02", ada="0.01", n="0.0003",
       mm="0", basis="exact", assumed="no", integrity="ok", policy="frozen"):
    return {"sample": sample, "qc_status": status, "reasons": reasons, "integrity": integrity, "read_pairs_total": pairs, "pairs_basis": basis,
            "estimated_depth_x": depth, "genome_size_assumed": assumed, "genome_size_mb": "5", "mean_quality": q, "q30_fraction": q30, "median_read_length": length,
            "gc_percent": gc, "duplication_fraction": dup, "adapter_fraction": ada, "n_fraction": n, "pair_mismatch_fraction": mm, "read_pairs_sampled": "200000",
            "contamination_screen": "not_evaluated", "policy_status": policy, "thresholds_sha": "abc123def456"}


def cand(sample, name, sel, n50, eligible="yes", reasons=""):
    return {"sample": sample, "assembler": name, "eligible": eligible, "reasons": reasons, "n_contigs": "40", "total_length": "5000000", "n50": n50, "l50": "5",
            "largest_contig": "300000", "gc_percent": "50.1", "bp_ge_1kb": "4900000", "bp_ge_10kb": "4800000", "mapped_read_fraction": "0.95", "selected": sel,
            "selection_reason": "quality: highest N50" if sel == "yes" else "", "policy": "quality", "primary": "spades"}


def well_formed(svg):
    try:
        return ET.fromstring(svg).tag.endswith("svg")
    except ET.ParseError:
        return False


def svgs(html):
    return [c[c.index("<svg"):] + "</svg>" for c in html.split("</svg>")[:-1] if "<svg" in c]


TH = qp.load_thresholds()
rows = [qc("good1", "PASS"), qc("warn1", "WARN", "q30_fraction 0.7 < 0.75 (warn)", q30="0.7"),
        qc("bad1", "REJECT", "mean_quality 15 < 20 (reject)", q="15", pairs="9000", depth="8"), qc("<b>x</b>&", "PASS")]
cands = [cand("good1", "spades", "no", "1000"), cand("good1", "unicycler", "yes", "9000"), cand("bad1", "spades", "no", "10", "no", "read support 0.5 < 0.8")]
scores = [{"sample": s, "tool": t, "f1": f} for s, t, f in (("good1", "A", "0.9"), ("good1", "B", "0.8"), ("warn1", "A", "0.2"), ("warn1", "B", "0.8"),
                                                              ("<b>x</b>&", "A", "0.9"), ("<b>x</b>&", "B", "0.7"))]

print("thresholds and the judging rule")
check("the frozen thresholds load with a hash and a frozen date", TH and TH["policy"] == "frozen" and len(TH["sha"]) == 12 and "2026" in TH["frozen_on"], TH and TH["frozen_on"])
t = TH and {r["metric"]: r for r in TH["rows"]}
check("judge follows short_read_qc.decide: min below reject, min below warn, max above warn, none", qp.judge(9, t["estimated_depth_x"]) == "reject"
      and qp.judge(25, t["estimated_depth_x"]) == "warn" and qp.judge(35, t["estimated_depth_x"]) == "pass" and qp.judge(.2, t["adapter_fraction"]) == "warn"
      and qp.judge(None, t["adapter_fraction"]) is None)
check("a metric with no reject limit never rejects", qp.judge(0.99, t["adapter_fraction"]) == "warn")
check("a threshold file that is missing gives None", qp.load_thresholds("/nonexistent/x.tsv") is None)

print("gauges")
g = qp.gauge_svg(0.7, t["q30_fraction"], 100, 1, "% Q30")
check("a gauge is well-formed SVG with its two limits labelled", well_formed(g) and "warn 75" in g and "reject 50" in g, g[:200])
check("a max-direction gauge draws too", well_formed(qp.gauge_svg(0.14, t["adapter_fraction"], 100, 1, "% adapter")) and "warn 10" in qp.gauge_svg(0.14, t["adapter_fraction"], 100, 1, "a"))
check("an absent value or threshold draws no gauge", qp.gauge_svg(None, t["q30_fraction"], 100, 1, "x") == "" and qp.gauge_svg(1, None, 1, 1, "x") == "")
text, state = qp.verdict(0.7, t["q30_fraction"], 100, 1, "% Q30")
check("the reason says warned, with the value and the limit", state == "warn" and text.startswith("warned") and "70.0" in text and "75.0" in text, text)
check("a pass says passed and rejection says rejected", qp.verdict(0.9, t["q30_fraction"], 100, 1, "x")[0].startswith("passed") and qp.verdict(0.4, t["q30_fraction"], 100, 1, "x")[0].startswith("rejected"))

print("the panel")
html = qp.build(rows, "", TH, None, cands, scores, False)
check("the sub-navigation lists all ten sub-sections", all(label in html for _g, label in qp.GROUPS) and html.count("<nav class='qp-nav'") == 1, [l for _g, l in qp.GROUPS if l not in html])
check("every sub-section is written out statically (so print has them all)", all(f"id='qp-{gid}'" in html for gid, _ in qp.GROUPS) and html.count("class='qp-sec") == len(qp.GROUPS))
check("the toolbar has the five MultiQC tools", all(w in html for w in ("Copy table", "Configure columns", "Scatter plot", "Violin plot", "Export as CSV")) and "role='toolbar'" in html)
check("the side panel exists, is hidden until used, and is labelled", "id='qp-panel'" in html and "aria-label='Sample QC record'" in html and "qp-close" in html)
check("each sample name is a real button (keyboard reachable)", "<button type='button' class='qp-name' data-s='good1'" in html)
check("the table keeps the General statistics columns with inline bars", "class='rv-bar'" in html and "Mean Phred" in html and "% Q30" in html and "% adapter" in html)
check("an interactive page script and its data are present once", html.count("id='qp-data'") == 1 and "QP.toCsv" in html)
check("every figure is well-formed SVG", all(well_formed(s) for s in svgs(html)), [s[:80] for s in svgs(html) if not well_formed(s)][:1])
check("points carry the decision as a shape and a word (not only a colour)", "<polygon" in html and "<rect" in html and "WARN" in html and "REJECT" in html)
check("distribution plots draw the thresholds as lines", "warn 75" in html and "reject 50" in html and "reject 20" in html)
check("the record of a flagged sample states the reason it warned", "warned: 70.0" in html and "q30_fraction 0.7 &lt; 0.75 (warn)" in html)
check("the record says whether it was excluded or only flagged", "belongs in the sensitivity analysis" in html and "excluded from the primary benchmark when SHORT_READ_QC_MODE=enforce" in html)
check("the record lists integrity checks and the assembly selection outcome", "Integrity checks" in html and "Selected: unicycler" in html and "not eligible (read support 0.5 &lt; 0.8)" in html)
check("the thresholds section states status, hash, and that it matches the shipped file", "frozen on" in html and TH["sha"] in html and "does not match" in html, html[html.index("qp-thresholds"):][:200])
check("the reviewer box answers all five questions with links to the evidence", html.split("What the reviewer asked")[1].split("</ul>")[0].count("<li><b>") == 5 and html.count("data-go='") >= 5 and "What the reviewer asked" in html)
check("the sensitivity ranking is computed from scores.tsv and says what changed", "Mean F1, without flagged" in html and ("changed" in html or "same" in html))
check("marker characters in sample names are escaped everywhere", "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;&amp;" in html)
check("no </script> can be injected through the data", html.count("</script>") == 2, html.count("</script>"))
check("print: all sections shown, toolbar and nav hidden, folds not needed", "@media print" in qp.CSS and "display:block!important" in qp.CSS and "qp-nav,.qp-toolbar,.qp-panel" in qp.CSS)
check("phone width and dark theme rules exist", "@media (max-width:900px)" in qp.CSS and "prefers-color-scheme:dark" in qp.CSS and ':root:not([data-theme="light"])' in qp.CSS)
check("focus is visible", "focus-visible" in qp.CSS)

print("synthetic, sensitivity and absent states")
syn = qp.build(rows, "", TH, None, cands, scores, True)
check("a synthetic table is labelled as synthetic, twice", "Synthetic." in syn and "make_demo_readqc.py" in syn and "Synthetic record" in syn)
check("a real table carries no synthetic label", "Synthetic." not in html and "Synthetic record" not in html)
nodata = qp.build(rows, "", TH, None, None, None, False)
check("without scores the sensitivity is stated as not computed", "Not computed" in nodata and "scores.tsv" in nodata)
check("without candidates the assembly selection says not measured", "Not measured in this run" in nodata and "assembly_candidates.tsv" in nodata)
allpass = qp.build([qc("a", "PASS"), qc("b", "PASS")], "", TH, None, None, None, False)
check("when nothing is flagged the sensitivity says there is nothing to leave out", "No sample was flagged" in allpass)
nothr = qp.build(rows, "", False, None, None, None, False)
check("a missing threshold file is said, and the decisions still show", "Thresholds not available" in nothr and "good1" in nothr)
sparse = qp.build([{"sample": "s1", "qc_status": "REJECT", "reasons": "integrity: truncated (R1)", "integrity": "truncated", "policy_status": "frozen", "thresholds_sha": "x"}], "", TH, None, None, None, False)
check("a sample with no metrics (integrity failure) still builds and explains itself", "Integrity failed (truncated)" in sparse and "No metric was measured" in sparse)
m = qp.Model(rows, TH)
sens = qp.sensitivity_block(qp.Model(rows, TH, None, None, scores))
check("the sensitivity table lists each tool with a rank with and without the flagged sample", "<td>A</td>" in sens and "<td>B</td>" in sens and "1 flagged sample" in sens, sens[:300])
many = [qc(f"s{i}", "PASS") for i in range(qp.CARD_LIMIT + 5)] + [qc("flag", "WARN", "x")]
big = qp.build(many, "", TH, None, None, None, False)
check("with a very large cohort full records are written for flagged samples only, and it says so", big.count("class='qp-rec'") == 1 and "Full records are written for the 1 flagged" in big)

print("not measured")
nm = qp.not_measured("")
check("the absent state names what is missing and gives the exact commands", "Not measured in this run" in nm and "short_read_qc.tsv" in nm and "SHORT_READ_QC_MODE=report plasbench run --cohort" in nm and "python python/qc_pilot.py" in nm)
check("it is never an empty or fake panel", "qp-nav" not in nm and "<svg" not in nm and "qp-data" not in nm)
sec = rv.readqc_section(None, None, {"results_dir": ""})
check("the section for a run without the table is the not-measured box", "Not measured in this run" in sec and "id='learn-readqc'" in sec)
check("the assembly section for a run without the table says the same", "Not measured in this run" in rv.assembly_section(None, {"results_dir": ""}))

print("the section keeps the earlier table in a fold")
secq = rv.readqc_section(rows, None, {"results_dir": "", "thresholds": TH, "synthetic": False})
check("an 'All values' fold holds the earlier table (decision bar, reasons, inline-bar table)", "<details class='qp-all'><summary>All values</summary>" in secq
      and "Reasons recorded" in secq and "<th>% duplicates</th>" in secq and "Median length" in secq)
check("the earlier thresholds note is kept", "Thresholds are" in secq)

print("the assembly comparison")
asm = rv.assembly_section([cand("good1", "spades", "no", "1000"), cand("good1", "unicycler", "yes", "9000")], {"results_dir": "", "synthetic": False})
check("a Show heatmap checkbox, the Worst-Median-Best legend and the chosen assembly marked", "Show heatmap" in asm and "Worst" in asm and "Median" in asm and "Best" in asm
      and "&#9733; selected" in asm and "qp-sel" in asm and "<strong>Reason:</strong>" in asm)
check("shading is a variable that the checkbox switches off, and print keeps it", "--heat:" in asm and "qp-noheat" in asm and "qp-noheat" in rv.CSS)

print("build for the demo and for results_real_cohort1")
page = "<html><body><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></body></html>"
with tempfile.TemporaryDirectory() as tmp:
    done = subprocess.run([sys.executable, os.path.join(ROOT, "test", "demo_dataset.py"), "--out-dir", tmp], capture_output=True, text=True)
    done2 = subprocess.run([sys.executable, os.path.join(ROOT, "python", "make_demo_readqc.py"), "--results-dir", tmp, "--sample-sheet", os.path.join(tmp, "samples.tsv")],
                           capture_output=True, text=True)
    check("the demo data and its synthetic QC are generated", done.returncode == 0 and done2.returncode == 0, done.stderr + done2.stderr)
    out = rv.inject(page, tmp)
    check("the demo page shows the panel, populated, labelled synthetic", "id='qp'" in out and "Synthetic." in out and "ecoli_a" in out and "abauma_b" in out and "Not measured in this run" not in out)
    check("the demo shows PASS, WARN and REJECT", all(f">{k}</span>" in out for k in ("PASS", "WARN", "REJECT")))
    check("the demo's assembly comparison shows candidates and a chosen assembly", "Show heatmap" in out and "&#9733; selected" in out and "megahit" in out)
    check("the demo's sensitivity ranking says the samples are synthetic or not computed", "synthetic" in out.split("Do the flagged samples change the conclusion?")[1][:3000].lower() or "Not computed" in out)
    check("the demo page's SVGs are all well-formed", all(well_formed(s) for s in svgs(out)))
cohort1 = os.path.join(ROOT, "results_real_cohort1")
if os.path.isdir(cohort1):
    out1 = rv.inject(page, cohort1)
    check("results_real_cohort1 shows 'Not measured in this run', what is missing and the command", "Not measured in this run" in out1 and "missing" in out1
          and "SHORT_READ_QC_MODE=report plasbench run --cohort" in out1 and "0.2.3" in out1)
    # The folder keeps the two isolates whose QC was regenerated from their reads (plasbench regenerate-visuals): the panel is real for those two, and never labelled synthetic.
    regenerated = os.path.isfile(os.path.join(cohort1, "short_read_qc.tsv"))
    check("results_real_cohort1: a real panel for the regenerated isolates (upec_ecpf5, upec_ecpf7) and none when no QC table is kept; never a synthetic label",
          "Synthetic." not in out1 and (("id='qp'" in out1 and "upec_ecpf5" in out1 and "upec_ecpf7" in out1) if regenerated else ("id='qp'" not in out1 and "qp-data" not in out1)))
else:
    print("  skip  results_real_cohort1 is not in this checkout")

print()
if not ok:
    print("READQC PANEL TESTS FAILED")
    sys.exit(1)
print("ALL READQC PANEL TESTS PASSED")
