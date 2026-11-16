#!/usr/bin/env python3
"""
build_implementation_catalogue.py -- write docs/IMPLEMENTATION_CATALOGUE.md.

The catalogue is one document that lists everything PlasBench implements. Its hand-written sections (docs/implementation_catalogue/head.md,
capabilities.md, tail.md) explain each capability; its indexes of tools, modules, outputs, run switches and merged changes are built here from the
repository itself, so they cannot drift from the code (test/test_implementation_catalogue.py regenerates the page and compares).

  python python/build_implementation_catalogue.py                    # rewrite docs/IMPLEMENTATION_CATALOGUE.md
  python python/build_implementation_catalogue.py --check            # exit 1 if the committed page is out of date
  python python/build_implementation_catalogue.py --refresh-history  # re-read merged pull requests with the GitHub CLI first
"""

import argparse
import ast
import csv
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import report_surfaces as rs  # noqa: E402

PARTS = os.path.join(ROOT, "docs", "implementation_catalogue")
OUT = os.path.join(ROOT, "docs", "IMPLEMENTATION_CATALOGUE.md")
TAB, NL = chr(9), chr(10)


def cat(*parts):
    return os.path.join(ROOT, *parts)


def module_rows():
    rows = []
    for f in sorted(glob.glob(cat("python", "*.py"))):
        with open(f, encoding="utf-8") as handle:
            doc = ast.get_docstring(ast.parse(handle.read())) or ""
        line = ""
        for l in doc.split(NL):
            l = l.strip()
            if l and not set(l) <= set("=-"):
                line = l
                break
        line = re.sub(r"^[\w.]+\.py\s*(--|—|-|:)\s*", "", line).replace("|", "/")
        rows.append((os.path.basename(f), line[:160]))
    return rows


GROUPS = [
    ("Truth, references and cohorts", r"^(make_truth|truth_|collect_truth|label_|audit_truth|detect_dimers|reference_evidence|scorable_truth|validate_truth|build_hybrid|materialize|"
     r"discover_|resolve_ncbi|curate_|review_candidate|import_contributed|import_external|build_accession|build_plasmid_reference|parse_teixeira|validate_cohort|validate_local|"
     r"init_local|prepare_contribution|repeat_content|compute_assembly_stats|compute_difficulty|characterise|long_read_support|measure_|estimate_download|fetch_ena|read_pairing|"
     r"simulate_reads|make_depth|make_read_quality|summarize_)"),
    ("Input control and assembly", r"^(short_read_qc|assembly_|assembler_|run_quast)"),
    ("Scoring (per sample and tool)", r"^(score_|alignment_accuracy|mask_accuracy|feature_preservation|bin_quality|bin_agreement|candidate_multiplicity|contig_|matching|call_structural|"
     r"copy_number|baseline_predictors|plasbin_flow_adapter|mob_to_gplas|validate_gplas|normalize_metagenomic|derive_amr|promote_amr|validate_amr|validate_structural|validate_orthogonal|"
     r"import_mobilome|plaseval_)"),
    ("Aggregation, statistics and robustness", r"^(aggregate_|headline_design|resampling|simulate_validation|power_analysis|rank_|ranking_|study_groups|clonal_groups|merge_|composite_|"
     r"performance_summary|stratify_|scenario_tags|metric_registry|freeze_prereg|compare_|flag_|database_|evaluate_warnings|leave_taxon|plasbench_common|tool_capabilities|tool_installer|"
     r"user_tool|write_manifest|write_operational)"),
    ("Recommender and operational path", r"^(recommendation_model|fit_recommendation|evaluate_recommender|validate_recommendations|select_|classify_operational|build_candidate_quality)"),
    ("Metagenomics", r"^(metagenomics|audit_metagenomic|design_synthetic|validate_metagenomic)"),
    ("HTML report", r"^(report_|build_html|build_explorer|build_enterprise|build_visualization|build_guide|build_implementation|export_report|refresh_sample)"),
    ("Protein and annotation", r"^(annotate_)"),
]


def group_of(name):
    for title, pattern in GROUPS:
        if re.match(pattern, name):
            return title
    return "Other"


def module_section():
    rows = module_rows()
    by = {}
    for name, line in rows:
        by.setdefault(group_of(name), []).append((name, line))
    out = [f"{len(rows)} modules in `python/`. Every one has a header that says what it is for; the one-line summary below is taken from it.", ""]
    for title, _ in GROUPS + [("Other", "")]:
        if title in by:
            out += [f"### {title}", "", "| Module | What it does |", "|---|---|"]
            out += [f"| `{n}` | {l} |" for n, l in by[title]]
            out.append("")
    return NL.join(out), rows


def tools_section():
    with open(cat("config", "tool_capabilities.tsv"), encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=TAB))
    real = [r for r in rows if r["validation_status"] != "not_applicable"]
    base = [r for r in rows if r["validation_status"] == "not_applicable"]
    out = [f"The registry (`config/tool_capabilities.tsv`) lists {len(rows)} entries: {len(real)} real tools and {len(base)} baselines and stand-ins used to calibrate the scores "
           "(a baseline is a trivial predictor every real tool should beat). Each tool is bound to one evaluation task, and that task, not its output format, decides which endpoint ranks it.",
           "", "| Tool | Method class | Track | Evaluation task | Validation status |", "|---|---|---|---|---|"]
    out += [f"| `{r['tool']}` | {r['method_class']} | {r['analysis_track']} | {r['evaluation_task']} | {r['validation_status']} |" for r in real + base]
    return NL.join(out), len(rows), len(real)


def outputs_section():
    surf = rs.SURFACES
    out = [f"{len(surf)} registered pipeline outputs, each with the module that writes it and where the report shows it. "
           "`shown` means the report draws or tabulates it; `partly` means it is available as a download or is summarised.", "",
           "| Output | Written by | Report section | Shown | What it holds |", "|---|---|---|---|---|"]
    for s in sorted(surf, key=lambda x: (x["level"], x["pattern"])):
        reason = (s.get("reason") or "").replace("|", "/")
        out.append(f"| `{s['pattern']}` | {s['producer'].replace('|', '/')} | {s['section']} | {s['status']} | {s['label']}: {reason} |")
    return NL.join(out)


def switches_section():
    out = ["| Switch | Default | What it controls |", "|---|---|---|"]
    n = 0
    with open(cat("config", "config.sh"), encoding="utf-8") as handle:
        for line in handle:
            m = re.match(r'^export (RUN_[A-Z0-9_]+)="\$\{[A-Z0-9_]+:-([^}]*)\}"\s*(?:#\s*(.*))?$', line.rstrip())
            if m:
                n += 1
                out.append(f"| `{m.group(1)}` | `{m.group(2)}` | {(m.group(3) or 'see the comment block above it in config/config.sh').replace('|', '/')} |")
    return NL.join(out), n


def refresh_history():
    done = subprocess.run(["gh", "pr", "list", "--state", "merged", "--limit", "300", "--json", "number,title,mergedAt",
                           "-q", r'.[] | "\(.number)" + "\t" + (.mergedAt[:10]) + "\t" + .title'], capture_output=True, text=True, cwd=ROOT)
    if done.returncode or not done.stdout.strip():
        raise SystemExit("could not read merged pull requests with the GitHub CLI: " + (done.stderr.strip() or "no output"))
    rows = sorted((l for l in done.stdout.splitlines() if l.count(TAB) == 2), key=lambda l: int(l.split(TAB)[0]))
    with open(os.path.join(PARTS, "history.tsv"), "w", encoding="utf-8", newline="") as handle:
        handle.write(NL.join(rows) + NL)


def history_section():
    with open(os.path.join(PARTS, "history.tsv"), encoding="utf-8") as handle:
        rows = sorted((tuple(l.rstrip(NL).split(TAB, 2)) for l in handle if l.count(TAB) == 2), key=lambda r: int(r[0]))
    out = [f"{len(rows)} merged pull requests, in order. Each is a reviewed, tested change; the title says what it did.", "",
           "| PR | Merged | What it did |", "|---|---|---|"]
    out += [f"| #{n} | {d} | {t.replace('|', '/')} |" for n, d, t in rows]
    return NL.join(out), len(rows)


def test_count():
    return len(glob.glob(cat("test", "test_*.py"))) + len(glob.glob(cat("test", "test_*.sh")))


def read_part(name):
    with open(os.path.join(PARTS, name), encoding="utf-8") as handle:
        return handle.read()


def build():
    mod_text, mods = module_section()
    tools_text, n_tools, n_real = tools_section()
    sw_text, n_sw = switches_section()
    hist_text, n_prs = history_section()
    page = read_part("head.md").format(modules=len(mods), tools=n_tools, real_tools=n_real, tests=test_count(), outputs=len(rs.SURFACES),
                                       switches=n_sw, prs=n_prs)
    page += read_part("capabilities.md")
    page += NL + "## 5. The tools" + NL + NL + tools_text + NL
    page += NL + "## 6. Every module" + NL + NL + mod_text + NL
    page += NL + "## 7. Every output file and where the report shows it" + NL + NL + outputs_section() + NL
    page += (NL + "## 8. Every run switch" + NL + NL + "These `RUN_*` settings in `config/config.sh` turn an analysis on or off (1 = on). "
             "Other settings (thresholds, paths, thread counts) are documented in the same file." + NL + NL + sw_text + NL)
    page += NL + "## 9. History: every merged change" + NL + NL + hist_text + NL
    page += read_part("tail.md")
    return page


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split(NL)[2])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh-history", action="store_true")
    a = ap.parse_args(argv)
    if a.refresh_history:
        refresh_history()
    page = build()
    if a.check:
        current = ""
        if os.path.isfile(OUT):
            with open(OUT, encoding="utf-8", newline="") as handle:
                current = handle.read()
        if current != page:
            print("docs/IMPLEMENTATION_CATALOGUE.md is out of date: run python python/build_implementation_catalogue.py")
            return 1
        print("docs/IMPLEMENTATION_CATALOGUE.md is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="") as handle:
        handle.write(page)
    print(f"wrote {OUT}: {len(page)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
