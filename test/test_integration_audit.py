#!/usr/bin/env python3
"""The integration audit (plan F): what a release adds must be wired everywhere it belongs, checked in one place.

The per-feature tests each check one piece. This checks the seams between them, the places a feature is silently left out:

  commands     every `plasbench` command is in a category of the setup window (plasbench/ui_schema.py: it is generated from the same parser, so none can be
               missing from the window, but an uncategorised one is hidden under 'More commands') and is documented in the README
  settings     every config variable a pre-registration row names exists in config/config.sh; every RUN_* switch has a default
  figures      every figure section has help text, a layout label and a place in the Figures view
  glossary     every term the metric registry or a figure uses is a glossary term
  surfaces     every output the report names is registered in report_surfaces.py
  manifest     every section id in this release's feature rows is a real section
  registries   the validation tiers, the database provenance and the metric registry cover every tool and metric
  user tools   a bring-your-own tool is listed with the built-ins (tier untested, provenance unrecorded) with no special case
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")

    print("commands")
    from plasbench import ui_schema
    from plasbench.cli import build_parser
    names = []
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            names = [n for n in action.choices if n not in ui_schema.ALIASES]
    categorised = {c for _k, _t, _d, commands in ui_schema.CATEGORIES for c in commands}
    check("every command is in a category of the setup window", set(names) <= categorised, sorted(set(names) - categorised))
    check("no category names a command that does not exist", categorised <= set(names), sorted(categorised - set(names)))
    undocumented = [n for n in names if f"`{n}`" not in readme and f"plasbench {n}" not in readme]
    check("every command is documented in the README", not undocumented, undocumented)

    print("settings")
    with open(ROOT / "config" / "prereg.tsv", newline="", encoding="utf-8") as handle:
        prereg = list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"))
    named = {r["config_variable"] for r in prereg if r.get("config_variable")}
    check("every config variable a pre-registration row names is set in config/config.sh", all(re.search(rf"export {v}=", config) for v in named), [v for v in named if not re.search(rf"export {v}=", config)])
    switches = re.findall(r'export (RUN_[A-Z0-9_]+)="\$\{', config)
    check("every RUN_ switch in config/config.sh has a default", len(switches) > 20 and all(switches))

    print("figures")
    import report_figures as figs
    import report_help_text as help_text
    import report_layout as layout
    check("every figure section has help text", all(s in help_text.HELP for s in figs.FIGURE_SECTIONS), [s for s in figs.FIGURE_SECTIONS if s not in help_text.HELP])
    figures_view = next(v for v in layout.VIEWS if v[0] == "figures")
    check("every figure section is in the Figures view", all(s in figures_view[-1].split() for s in figs.FIGURE_SECTIONS), [s for s in figs.FIGURE_SECTIONS if s not in figures_view[-1].split()])
    labels = layout.SECTION_LABELS if hasattr(layout, "SECTION_LABELS") else {}
    layout_source = (ROOT / "python" / "report_layout.py").read_text(encoding="utf-8")
    check("every figure section has a tab label in the layout", all(f'"{s}":' in layout_source for s in figs.FIGURE_SECTIONS), [s for s in figs.FIGURE_SECTIONS if f'"{s}":' not in layout_source])
    del labels

    print("glossary")
    import metric_registry as mr
    page_source = (ROOT / "python" / "build_html_report.py").read_text(encoding="utf-8")
    check("every metric registry term is a glossary term", all(f'"{r["term"]}": {{' in page_source for r in mr.load() if r["term"]), [r["term"] for r in mr.load() if r["term"] and f'"{r["term"]}": {{' not in page_source])
    check("the terms this release introduced are glossary terms", all(f'"{t}": {{' in page_source for t in (
        "SV-PRR", "AMR-PRR", "Fingerprint", "Dataset characteristics", "Validation tier", "Database provenance", "Recommendation evidence", "Predicted-sequence burden")))

    print("surfaces and the manifest")
    import report_surfaces as surfaces
    names_registered = " ".join(str(s) for s in surfaces.SURFACES)
    for name in ("benchmark.dataset_features.tsv", "benchmark.database_provenance.tsv", "benchmark.recommender_arms.tsv", "benchmark.truth_marker_overlap.tsv"):
        check(f"{name} is registered in report_surfaces", name in names_registered)
    with open(ROOT / "test" / "fixtures" / "report_feature_manifest.tsv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    ids = [r["feature_id"] for r in rows]
    check("feature ids are unique", len(ids) == len(set(ids)))
    for needed in ("fig-radar.01", "fig-complexity.01", "recommendations.evidence", "amr-placement.context", "database-membership.provenance", "isolate-difficulty.dataset"):
        check(f"the manifest guards {needed}", needed in ids)

    print("one definition of each constant (the places that repeat a value must agree)")
    import audit_truth_labels as atl
    import freeze_prereg
    import score_amr_placement as sap
    import truth_provenance as tpv
    import validate_cohort as vc

    def cfg(name):
        match = re.search(rf'export {name}="\$\{{{name}:-([^}}]*)\}}"', config)
        return match.group(1) if match else None
    pre = {r["parameter"]: r for r in freeze_prereg.read_rows(ROOT / "config" / "prereg.tsv")}
    check("the audit size thresholds: config.sh, the module defaults and the pre-registration agree",
          cfg("CHROMID_MIN_BP") == str(atl.CHROMID_MIN_BP) and cfg("LARGE_PLASMID_BP") == str(atl.LARGE_PLASMID_BP)
          and all(str(atl.__dict__[k]) == pre[p]["value"] for k, p in (("CHROMID_MIN_BP", "chromid_min_bp"), ("LARGE_PLASMID_BP", "large_plasmid_bp")) if p in pre),
          (cfg("CHROMID_MIN_BP"), atl.CHROMID_MIN_BP, cfg("LARGE_PLASMID_BP"), atl.LARGE_PLASMID_BP))
    check("AMR_FLANK_BP: config.sh, the module default and the pre-registration agree", cfg("AMR_FLANK_BP") == str(sap.FLANK_BP) == pre["amr_flank_bp"]["value"], (cfg("AMR_FLANK_BP"), sap.FLANK_BP))
    check("the headline settings in config.sh equal their pre-registered values",
          all(cfg(var) == pre[row]["value"] for var, row in (("HEADLINE_MAX_REFERENCE_TIER", "headline_max_reference_tier"), ("HEADLINE_MIN_CLUSTERS", "headline_min_clusters"),
                                                             ("ALLOW_PRIMARY_FALLBACK", "allow_primary_fallback"))),
          [(var, cfg(var)) for var in ("HEADLINE_MAX_REFERENCE_TIER", "HEADLINE_MIN_CLUSTERS", "ALLOW_PRIMARY_FALLBACK")])
    import resampling
    check("the cluster minimums in the code equal the pre-registered ones", (str(resampling.MIN_CLUSTERS_CI), str(resampling.MIN_CLUSTERS_TEST), str(resampling.EXACT_MAX_UNITS))
          == (pre["min_clusters_ci"]["value"], pre["min_clusters_test"]["value"], pre["exact_permutation_max_units"]["value"]))
    check("the evidence-field vocabularies of the cohort validator and the provenance module are the same",
          [vc.PROVENANCE_VALUES[k] for k in ("truth_circularity_evidence", "truth_read_support", "truth_structural_integrity", "truth_independent_validation")]
          == [tpv.CIRCULARITY, tpv.READ_SUPPORT, tpv.STRUCTURAL, tpv.VALIDATION])   # replicon evidence is inferred, not a cohort column

    print("registries and user tools")
    import database_provenance as dp
    import tool_capabilities as tc
    caps = tc.read_capabilities(ROOT / "config" / "tool_capabilities.tsv")
    table = {r["tool"]: r for r in dp.rows(dp.fdo.read_rows(ROOT / "config" / "tool_database_releases.tsv"), caps)}
    check("every tool of the capability registry has a provenance row", set(caps) <= set(table), sorted(set(caps) - set(table)))
    check("a tool no registry knows is listed as untested and unrecorded, with no special case",
          dp.rows([], {"my_tool": {}})[0]["validation_status"] == "untested" and dp.rows([], {"my_tool": {}})[0]["provenance_status"] == "unrecorded")
    gaps = mr.gaps()
    check("the registry still states its gaps (nothing is hidden)", bool(gaps))
    print()
    if not ok:
        print("INTEGRATION AUDIT FAILED")
        sys.exit(1)
    print("ALL INTEGRATION AUDIT CHECKS PASSED")


if __name__ == "__main__":
    main()
