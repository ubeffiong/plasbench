#!/usr/bin/env python3
"""config/report_inputs.tsv (python/report_inputs.py) and docs/REPORT_INPUTS.md.

Every file the report reads (the report_surfaces.py registry) is a row; every row's writer exists under python/ or scripts/; every regen_key belongs to
`plasbench regenerate-visuals`; the page is the table rendered; and the figure inputs the new report sections read are rows with the right role.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_inputs  # noqa: E402
import report_surfaces  # noqa: E402
import regenerate_visuals  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {str(detail)[:500]}"))
    ok = ok and bool(good)


rows = report_inputs.load()
table = report_inputs.by_pattern(rows)
registry = [e["pattern"] for e in report_surfaces._file_entries()]
check("the table is not empty and has the documented columns", len(rows) > 150 and set(report_inputs.COLUMNS) <= set(rows[0]), len(rows))
check("every output the report reads appears in the table", not [p for p in registry if p not in table], [p for p in registry if p not in table][:5])
check("no row names a file the report does not read", not [p for p in table if p not in registry], [p for p in table if p not in registry][:5])
bad_writers = [(r["pattern"], t) for r in rows for t in r["written_by"].split(" / ") if not report_inputs.writer_exists(t)]
check("every row's writer exists under python/ or scripts/", not bad_writers, bad_writers[:5])
check("report_inputs.problems() is empty", report_inputs.problems(rows) == [], report_inputs.problems(rows)[:5])
check("every row says what it needs and what it can be rebuilt from", all(r["needs"] and r["regenerable_from"] for r in rows))
check("every regen_key is one regenerate-visuals implements", all(not r["regen_key"] or r["regen_key"] in regenerate_visuals.ALL_KEYS for r in rows))
for pattern, key in (("{sample}/visualization/alignment_blocks.json", "alignments"), ("{sample}/truth.tsv", "truth"), ("short_read_qc.tsv", "qc"),
                     ("{sample}/{tool}.pred_vs_ref.paf", "paf"), ("{sample}/truth_features.tsv", "truth-features")):
    check(f"{pattern} is rebuilt by --only {key}", table[pattern]["regen_key"] == key, table[pattern])
check("predictions can only come from a tool re-run", table["{sample}/pred_{tool}.plasmid.fasta"]["regen_key"] == "" and "re-run the tool" in table["{sample}/pred_{tool}.plasmid.fasta"]["regenerable_from"])
check("alignment_blocks.json feeds the synteny ribbons, the plasmid maps and the figure sections",
      {"learn-synteny", "plasmid-maps", "samples", "fig-presence", "fig-facets", "fig-fingerprint"} <= set(table["{sample}/visualization/alignment_blocks.json"]["sections"].split(",")))
check("short_read_qc.tsv feeds the QC panel and is required by it", "learn-readqc" in table["short_read_qc.tsv"]["sections"] and table["short_read_qc.tsv"]["role"] == "required")
check("match() finds the row of a concrete path", (report_inputs.match("iso1/visualization/alignment_blocks.json") or {}).get("regen_key") == "alignments"
      and (report_inputs.match("iso1/mob_recon.pred_vs_ref.paf") or {}).get("regen_key") == "paf")
doc = open(report_inputs.DOC, encoding="utf-8", newline="").read()
check("docs/REPORT_INPUTS.md is the table rendered (python3 python/report_inputs.py --write-doc)", doc == report_inputs.render_markdown(rows))
check("the page lists every pattern", all(f"`{r['pattern']}`" in doc for r in rows))
# a file the pipeline gains but forgets to list is caught
extra = rows + [dict(rows[0], pattern="{sample}/brand_new_output.tsv")]
check("a registry/table mismatch is reported", any("brand_new_output" in p for p in report_inputs.problems(extra)))
missing_writer = [dict(r, written_by="no_such_script.py") if i == 0 else r for i, r in enumerate(rows)]
check("a writer that does not exist is reported", any("no_such_script.py" in p for p in report_inputs.problems(missing_writer)))
print("ALL REPORT-INPUTS TESTS PASSED" if ok else "REPORT-INPUTS TESTS FAILED")
sys.exit(0 if ok else 1)
