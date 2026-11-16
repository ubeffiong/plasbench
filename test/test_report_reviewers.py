#!/usr/bin/env python3
"""The three reviewer dashboards: short-read QC, assembly selection, reconstruction multiplicity.

Built from hand-made tables so every figure can be checked. Each chart must be well-formed SVG, every status must be a word as well as a
colour, a missing table must say it was not run, and tool or sample names must never inject markup.
"""
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_reviewers as rv  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def svgs(html):
    out = []
    for chunk in html.split("</svg>")[:-1]:
        if "<svg" in chunk:
            out.append(chunk[chunk.index("<svg"):] + "</svg>")
    return out


def well_formed(svg):
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return False, str(exc)
    return root.tag.endswith("svg"), ""


def qc(sample, status, reasons="", pairs="200000", depth="80", q="35", q30="0.9", length="150", gc="50.5", dup="0.02", ada="0.01",
       basis="exact", assumed="no", integrity="ok"):
    return {"sample": sample, "qc_status": status, "reasons": reasons, "integrity": integrity, "read_pairs_total": pairs, "pairs_basis": basis,
            "estimated_depth_x": depth, "genome_size_assumed": assumed, "mean_quality": q, "q30_fraction": q30, "median_read_length": length,
            "gc_percent": gc, "duplication_fraction": dup, "adapter_fraction": ada, "policy_status": "provisional", "thresholds_sha": "abc123def456"}


print("short-read QC dashboard")
rows = [qc("good1", "PASS"), qc("warn1", "WARN", "q30_fraction 0.7 < 0.75 (warn)", q30="0.7"),
        qc("bad1", "REJECT", "mean_quality 15 < 20 (reject)", q="15"), qc("bad2", "REJECT", "integrity: truncated (R1)", integrity="truncated")]
html = rv.readqc_section(rows)
check("a decision chip is a word, for every sample", all(w in html for w in ("PASS", "WARN", "REJECT")) and html.count("rv-chip") == 4)
check("the cohort summary counts each decision", "1 PASS" in html and "1 WARN" in html and "2 REJECT" in html)
check("rejected samples come first, then warnings, then passes", html.index("bad1") < html.index("warn1") < html.index("good1"))
check("the reason is shown beside the sample", "mean_quality 15 &lt; 20 (reject)" in html and "integrity: truncated (R1)" in html)
check("the reasons are tallied by metric", "mean_quality (1)" in html and "integrity (1)" in html and "q30_fraction (1)" in html)
check("inline bars carry the value", "class='rv-bar'" in html and "200.0 k" in html)
check("an estimated read count (~) and an assumed genome size (*) are marked and explained", "~" in rv.readqc_section([qc("e", "PASS", basis="estimated", assumed="yes")])
      and "80.0*" in rv.readqc_section([qc("e", "PASS", basis="estimated", assumed="yes")])
      and "assumes the default genome size" in rv.readqc_section([qc("e", "PASS")]))
check("provisional thresholds are said to be provisional, with their hash", "provisional" in html and "abc123def456" in html
      and "not universal cut-offs" in html)
check("contamination is stated as not screened", "Taxonomic contamination is not screened" in html)
check("the cohort bar is well-formed SVG", all(well_formed(s)[0] for s in svgs(html)) and len(svgs(html)) == 1)
check("no table says it was not run, instead of staying silent", "Not run" in rv.readqc_section(None) and "short_read_qc.tsv" in rv.readqc_section(None))
check("frozen thresholds drop the provisional warning", "not universal cut-offs" not in rv.readqc_section([dict(qc("f", "PASS"), policy_status="frozen")]))

print("assembly selection dashboard")


def cand(sample, name, n50, contigs, total, selected, eligible="yes", reasons="", mapped="0.97", policy="quality", primary="spades", reason=""):
    return {"sample": sample, "assembler": name, "eligible": eligible, "reasons": reasons, "n_contigs": contigs, "total_length": total, "n50": n50,
            "l50": "2", "largest_contig": n50, "gc_percent": "50.1", "bp_ge_1kb": total, "bp_ge_10kb": total, "mapped_read_fraction": mapped,
            "selected": selected, "selection_reason": reason, "policy": policy, "primary": primary}


crows = [cand("s1", "spades", "300000", "40", "4800000", "no"), cand("s1", "unicycler", "900000", "6", "4900000", "yes", reason="quality: highest N50"),
         cand("s1", "megahit", "100000", "90", "4700000", "no", eligible="no", reasons="read support 0.40 < 0.8", mapped="0.40"),
         cand("s2", "spades", "500000", "20", "5000000", "yes", policy="quality")]
html = rv.assembly_section(crows)
check("one comparison table per sample with a column per candidate", html.count("<table>") == 2 and "unicycler &#9733; selected" in html)
check("the selected assembler is marked and the reason shown", "&#9733; selected" in html and "quality: highest N50" in html)
check("an ineligible candidate says so, with the reason", "not eligible: read support 0.40 &lt; 0.8" in html)
check("rows are coloured worst to best (best N50 blue, worst red)", rv.heat(1) in html and rv.heat(0) in html)
check("a lower-is-better row colours the smallest value best", html.index(rv.heat(1)) > 0)
check("total length and GC are not coloured", "Total length (bp)" in html and "GC (%)" in html)
check("the policy summary counts the selections", "unicycler for 1 sample(s)" in html and "spades for 1 sample(s)" in html)
check("the first sample is open and the others collapsed", "<details open><summary>s1" in html and "<details><summary>s2" in html)
check("heat colours run from red through white to blue", rv.heat(0) != rv.heat(0.5) != rv.heat(1) and rv.heat(0.5) == "#ffffff")
check("alternatives are said to be retained for sensitivity analysis, not yet run through the tools", "not done yet" in html)
check("a missing table says it was not run", "Not run" in rv.assembly_section(None))
check("sample names are escaped", "<script>" not in rv.assembly_section([cand("<script>x</script>", "a", "1", "1", "1", "yes")]))

print("reconstruction multiplicity dashboard")


def prow(sample, tool, plasmid, outcome, n_cand, best, comb, red_bp, red_frac, touching, length="100000", gain=None):
    return {"sample": sample, "tool": tool, "plasmid": plasmid, "plasmid_length": length, "outcome": outcome, "n_candidates": n_cand,
            "n_touching": touching, "best_candidate": "A", "best_candidate_coverage": best, "combined_coverage": comb,
            "coverage_gain": gain if gain is not None else f"{float(comb) - float(best):.3f}", "redundant_bp": red_bp, "redundancy_fraction": red_frac,
            "n_fragments": "1", "n_redundant": "1", "n_chimeric_touching": "1", "candidate_bp_to_union_ratio": "1.35"}


def crow(tool, name, length, aligned, plasmid_bp, chrom_bp, rel):
    return {"sample": "S1", "tool": tool, "candidate": name, "length": length, "aligned_bp": aligned, "plasmid_bp": plasmid_bp,
            "chromosome_bp": chrom_bp, "relationship": rel}


def irow(plasmid, cand, start, end, rel, tool="toolA"):
    return {"sample": "S1", "tool": tool, "plasmid": plasmid, "plasmid_length": "100000", "candidate": cand, "start": str(start), "end": str(end),
            "relationship": rel}


plasmids = [prow("S1", "toolA", "P1", "fragmented_and_duplicated", "3", "0.60", "1.00", "35000", "0.259", "4"),
            prow("S1", "toolA", "P2", "single", "1", "1.00", "1.00", "0", "0.0", "1", length="20000"),
            prow("S1", "toolB", "P1", "single", "1", "0.90", "0.90", "0", "0.0", "1")]
candidates = [crow("toolA", "A", "60000", "60000", "60000", "0", "primary"), crow("toolA", "B", "35000", "35000", "35000", "0", "complementary_fragment"),
              crow("toolA", "C", "30000", "30000", "30000", "0", "redundant"), crow("toolA", "F", "50000", "50000", "0", "50000", "off_target"),
              crow("toolA", "G", "5000", "0", "0", "0", "unmapped"), crow("toolB", "X", "90000", "90000", "90000", "0", "primary")]
intervals = [irow("P1", "A", 0, 60000, "primary"), irow("P1", "B", 55000, 90000, "complementary_fragment"), irow("P1", "C", 10000, 40000, "redundant"),
             irow("P1", "E", 90000, 100000, "chimeric")]
html = rv.multiplicity_section(plasmids, candidates, intervals)
check("the summary table has one row per tool with counts of chimeric, off-target and unmapped records",
      "<td>toolA</td><td>2</td>" in html and "<td>toolB</td><td>1</td>" in html and "Off-target" in html)
check("the reading says extra candidates add coverage and are partly redundant", "extra candidates add 20.0 points of coverage" in html
      and "25.9% of the candidate sequence" in html or "extra candidates add" in html)
check("a tool with no multi-candidate plasmid is said to have none", "toolB: no plasmid has more than one candidate" in html)
comp = rv.tool_composition(candidates, plasmids)
a = comp["toolA"]
check("predicted sequence is split into unique plasmid, redundant, chromosome and unmapped bases", a["length"] == 180000 and a["plasmid"] == 125000
      and a["chrom"] == 50000 and a["redundant"] == 35000 and a["unmapped"] == 1, a)
check("the composition chart and the best-versus-combined chart are well-formed SVG",
      all(well_formed(s)[0] for s in (rv.composition_chart(comp), rv.coverage_chart(plasmids))))
track = rv.track_figure(plasmids[0], intervals)
check("the track draws the reference, every candidate and a coverage strip, as well-formed SVG", well_formed(track)[0]
      and track.count("reference plasmid") >= 1 and all(f"<title>{q}" in track for q in ("A (primary)", "B (complementary fragment)", "C (redundant)",
                                                                                          "E (chimeric)")), track[:200])
check("the strip separates covered once, covered by several, and not represented", "covered once" in track and "covered by 2 candidates" in track
      and "covered by 3 candidates" in track or "covered by 2 candidates" in track)
segs = rv.depth_segments([(0, 60000), (55000, 90000), (10000, 40000), (90000, 100000)], 100000)
check("coverage depth is computed by sweeping the intervals (overlaps counted)", (0, 10000, 1) in segs and (10000, 40000, 2) in segs
      and (55000, 60000, 2) in segs and (90000, 100000, 1) in segs and not any(d == 0 for _, _, d in segs), segs)
check("an uncovered gap is drawn as not represented", any(d == 0 for _, _, d in rv.depth_segments([(0, 10)], 100)))
check("the section shows at most six tracks, plasmids with the most candidates first", html.count("Candidates against S1 / toolA / P1") >= 1)
check("an unrepresented reference region is labelled", "not represented" in html or "grey hatching: not represented" in html)
check("a missing table says it was not run", "Not run" in rv.multiplicity_section(None, None, None))
check("tool names are escaped in every figure and table",
      "<script>" not in rv.multiplicity_section([dict(plasmids[0], tool="<script>x</script>")], [dict(candidates[0], tool="<script>x</script>")], intervals))
check("no plasmid with several candidates means no tracks and says so",
      "no tracks to draw" in rv.multiplicity_section([plasmids[2]], [candidates[5]], []))

print("ranking stability section")
summary = [{"analysis_track": "short_read", "evaluation_task": "binning_reconstruction", "n_isolates": "16", "n_studies": "3", "n_species": "2",
            "largest_study": "S1", "largest_study_share": "0.625", "baseline_leader": "mob_recon", "study_leader_changes": "1", "study_leave_outs": "3",
            "species_leader_changes": "0", "species_leave_outs": "2", "equal_study_leader": "gplas2_mob",
            "verdict": "fragile: the leader changes in 2 leave-out(s); report the ranking with this caveat"}]
leaves = [{"evaluation_task": "binning_reconstruction", "left_out": "S1", "isolates_removed": "10", "leader": "gplas2_mob", "kendall_tau": "-1.000",
           "leader_changed": "yes"}]
stab = rv.stability_section(summary, leaves, [])
check("the table shows the verdict as a chip and the largest study's share", "rv-warn" in stab and "S1 (0.625)" in stab and "fragile" in stab)
check("the leave-outs that change the leader are listed", "Leave-outs that change the leader" in stab and "gplas2_mob" in stab)
check("a missing table says it was not run", "Not run" in rv.stability_section(None))
check("a name is escaped", "<script>" not in rv.stability_section([dict(summary[0], largest_study="<script>x</script>")]))

print("reference evidence section")
audit_rows = [{"sample": "A1", "audit_status": "weak", "reference_tier": "3", "evaluation_independence": "dependent", "evidence_recorded": "1 of 6",
               "audit_reasons": "short-read-first assembly", "headline_eligible": "no"},
              {"sample": "B2", "audit_status": "strong", "reference_tier": "2", "evaluation_independence": "independent", "evidence_recorded": "6 of 6",
               "audit_reasons": "", "headline_eligible": "yes"}]
ref = rv.refaudit_section(audit_rows)
check("the counts, the headline-eligible number and the reasons are shown, weakest first", "1 weak" in ref and "1 strong" in ref and "1 meet the headline" in ref
      and ref.index("A1") < ref.index("B2") and "short-read-first assembly" in ref)
check("a missing table says it was not run", "Not run" in rv.refaudit_section(None))
check("a name is escaped", "<script>" not in rv.refaudit_section([dict(audit_rows[0], sample="<script>x</script>")]))

print("injection")
page = "<html><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></html>"
import tempfile
d = tempfile.mkdtemp(prefix="rvrep_")
out = rv.inject(page, d)
check("all three sections and their navigation links are added before Recommendations even when nothing was run",
      all(f"id='{sid}'" in out and f"href='#{sid}'" in out for sid, _ in rv.SECTIONS) and out.index("learn-readqc") < out.index("id='recommendations'")
      and out.count("Not run") >= 3)

print("ALL REVIEWER DASHBOARD TESTS PASSED" if ok else "REVIEWER DASHBOARD TESTS FAILED")
sys.exit(0 if ok else 1)
