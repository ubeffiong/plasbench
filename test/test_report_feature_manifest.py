#!/usr/bin/env python3
"""No analytic is lost when the report is restructured: every feature of every old section is checked.

test/data/report_feature_manifest.tsv lists one machine-checkable row per feature of the report's
old sections (a table's columns, a filter, a download link, a caveat sentence, ...). This test builds
the demo report ONCE into a temporary copy of results_demo (so the report sits beside its data) and
evaluates every row. A row is resolved through test/report_regions.region(), which finds a
<section id>, a panel inside a container, or an alias from python/report_aliases.LEGACY_IDS, so the
same manifest holds before and after sections are merged into containers.

Kinds (see the audit notes in the manifest): table_headers, element_id, attr, text, heading,
not_text, string, file_link, file_glob, page_file_link, anchor, tab, view, preset, unique,
svg_count>=1, sortable, consistency.
"""
import csv
import html as _html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "python"))

import report_aliases  # noqa: E402
import report_regions as rr  # noqa: E402

MANIFEST = HERE / "data" / "report_feature_manifest.tsv"

# Rows that are expected to fail until the work that makes them true is done. Keep this a plain,
# sorted list: the lead empties it at the end of the container merge, and a row that is listed
# here but passes is reported (so the list can shrink) without failing the test.
#   * tab / view / preset / unique rows assert the merged structure (containers with tabs, the
#     leaderboard column presets, the scores group-by views, one copy of the paired table);
#   * the remaining rows assert a fix that needs the merged structure to be meaningful.
PENDING = sorted([])   # every manifest row passes: the structure rows were satisfied by the phase B merges



def build_report(workdir):
    """Build the demo report into <workdir>/results (a copy of results_demo); return (html, results_dir)."""
    results = Path(workdir) / "results"
    shutil.copytree(ROOT / "results_demo", results)
    return build_into(results, results / "benchmark.report.html"), results


def build_into(results, out):
    """Run build_html_report.py on a results folder with the arguments test/run_demo.sh uses."""
    d = str(results)
    prefix = os.path.join(d, "benchmark")
    args = [sys.executable, str(ROOT / "python" / "build_html_report.py"),
            "--project-root", str(ROOT),
            "--scores", os.path.join(d, "scores.tsv"),
            "--tool-status", os.path.join(d, "tool_status.tsv"),
            "--leaderboard", prefix + ".leaderboard.tsv",
            "--sample-sheet", os.path.join(d, "samples.tsv"),
            "--recommendations", prefix + ".recommendations.tsv",
            "--recommendation-validation", prefix + ".recommendation_validation.tsv",
            "--manifest", os.path.join(d, "run_manifest.json"),
            "--recovery-by-replicon", prefix + ".recovery_by_replicon.tsv",
            "--truth-label-audit", prefix + ".truth_label_audit.tsv",
            "--dimensions-prefix", prefix,
            "--comparisons", prefix + ".paired_comparisons.tsv",
            "--stratified", prefix + ".stratified.tsv",
            "--rank-robustness", prefix + ".rank_robustness.tsv",
            "--data-dir", d,
            "--label-schemes", prefix + ".label_schemes.tsv",
            "--label-scheme-summary", prefix + ".label_scheme_summary.tsv",
            "--truth-provenance", prefix + ".truth_provenance.tsv",
            "--outcome-states", prefix + ".outcome_states.tsv",
            "--recommender-eval", prefix + ".recommender_eval.tsv",
            "--recommender-verdict", prefix + ".recommender_verdict.json",
            "--warning-eval", prefix + ".warning_eval.tsv",
            "--leave-taxon-out", prefix + ".leave_taxon_out.tsv",
            "--amr-placement", prefix + ".amr_placement.tsv",
            "--contig-crosscheck", prefix + ".contig_crosscheck.tsv",
            "--out", str(out)]
    done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert done.returncode == 0, done.stderr[-2000:]
    return Path(out).read_text(encoding="utf-8")


# ---- checks ------------------------------------------------------------------------------------

def _page_text(page):
    return rr.text_of(page)


def _glob_regex(pattern):
    return re.compile("(^|/)" + "[^/]+".join(re.escape(part) for part in pattern.split("*")) + "$")


def _anywhere_ids(page, ident):
    """An element id anywhere, including inside an escaped srcdoc iframe."""
    pattern = r"""\bid\s*=\s*(?:'%s'|"%s"|&quot;%s&quot;|&#39;%s&#39;|\\"%s\\")""" % ((re.escape(ident),) * 5)
    return re.search(pattern, page) is not None


def _tab_like(markup):
    """Labels (lower-cased) of tabs, view toggles and presets in a container."""
    labels = set()
    for tag in re.finditer(r"<(button|a|li|span|div|option|label)\b([^>]*)>(.*?)</\1>", markup, re.S | re.I):
        attrs = tag.group(2)
        if re.search(r"""role\s*=\s*['"]tab['"]|data-(?:tab|view|preset|cg-preset|panel)\b""", attrs, re.I):
            labels.add(rr.text_of(tag.group(3)).lower())
            for value in re.findall(r"""data-(?:tab|view|preset|cg-preset|panel)\s*=\s*['"]([^'"]+)['"]""", attrs, re.I):
                labels.add(value.lower())
    return labels


def _has_headers(heads, check):
    """Every ' | '-separated header in ``check`` is a <th> text of the table (or starts one)."""
    wanted = [_html.unescape(h.strip()) for h in check.split(" | ")]
    return all(any(h == w or h.startswith(w) for h in heads) for w in wanted)


def check_row(page, row, text_cache):
    kind, check, old = row["kind"], row["check"], row["old_section"]
    block = rr.region(page, old)
    if kind == "table_headers":
        for _, heads in rr.tables(block):
            if _has_headers(heads, check):
                return True, ""
        return False, "no table in #%s has all of: %s" % (old, check)
    if kind == "element_id":
        return (_anywhere_ids(page, check), "no element id '%s'" % check)
    if kind == "attr":
        m = re.match(r"\[([\w-]+)='([^']*)'\]$", check)
        name, value = m.group(1), m.group(2)
        found = re.search(r"""%s\s*=\s*['"]%s['"]""" % (re.escape(name), re.escape(value)), block)
        return (found is not None, "no %s in #%s" % (check, old))
    if kind in ("text", "heading"):
        if not block:
            return False, "no region #%s" % old
        return (check.lower() in rr.text_of(block).lower(), "#%s lacks text: %s" % (old, check))
    if kind == "not_text":
        if not block:
            return False, "no region #%s" % old
        return (check.lower() not in rr.text_of(block).lower(), "#%s still says: %s" % (old, check))
    if kind == "string":
        return (check in page or check in _html.unescape(page), "page lacks string: %s" % check)
    if kind in ("file_link", "file_glob"):
        links = rr.hrefs(block)
        if kind == "file_link":
            ok = any(h.endswith(check) for h in links)
        else:
            ok = any(_glob_regex(check).search(h) for h in links)
        return ok, "#%s has no link to %s" % (old, check)
    if kind == "page_file_link":
        return (any(h.endswith(check) for h in rr.hrefs(page)), "page has no link to %s" % check)
    if kind == "anchor":
        target = check.lstrip("#")
        linked = re.search(r"""href\s*=\s*['"]#%s['"]""" % re.escape(target), page) is not None
        resolves = rr.id_exists(page, target) or _anywhere_ids(page, target) \
            or report_aliases.resolve(target) != target
        return (linked and resolves, "link #%s: linked=%s resolves=%s" % (target, linked, resolves))
    if kind in ("tab", "view", "preset"):
        labels = _tab_like(block)
        return (check.lower() in labels, "#%s has no %s '%s'" % (old, kind, check))
    if kind == "unique":
        count = sum(1 for _, heads in rr.tables(page) if _has_headers(heads, check))
        return (count == 1, "table with %s appears %d times" % (check, count))
    if kind == "svg_count>=1":
        return ("<svg" in block, "no <svg> in #%s" % old)
    if kind == "sortable":
        return (re.search(r"<table\b[^>]*class\s*=\s*['\"][^'\"]*\bsortable\b", block) is not None,
                "no sortable table in #%s" % old)
    if kind == "consistency":
        return scenario_consistency(page)
    return False, "unknown kind %s" % kind


def scenario_consistency(page):
    """The exclusive scenario table and the scorecard scenario views count the same isolates per tag.

    The scorecard headings carry data-scenario / data-n; the exclusive section states the overlapping tag counts it was
    derived from in data-tag-counts. Both come from report_scorecard.scenario_membership, so they must be identical
    (the partition itself is checked in test_scenario_definition.py)."""
    new = {m.group(1): int(m.group(2)) for m in re.finditer(r"data-scenario='([a-z_]+)' data-n='(\d+)'", page)}
    found = re.search(r"data-tag-counts='([^']*)'", rr.region(page, "scenarios"))
    if not new or not found:
        return False, "scenario counts not found (scorecard %d tags, exclusive note %s)" % (len(new), bool(found))
    old = {name: int(n) for name, n in re.findall(r"([a-z_]+) (\d+)", found.group(1))}
    return (old == new, "tag counts differ: exclusive section %s, scorecard %s" % (old, new))


def evaluate(page, rows):
    failures = []
    for row in rows:
        try:
            ok, why = check_row(page, row, None)
        except Exception as error:  # a broken check is a failed row, not a crashed test
            ok, why = False, "check raised %r" % (error,)
        if not ok:
            failures.append((row["feature_id"], row["kind"], row["check"], why))
    return failures


def load_manifest():
    with open(MANIFEST, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    rows = load_manifest()
    ids = [r["feature_id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate feature ids in the manifest"
    assert PENDING == sorted(set(PENDING)) and set(PENDING) <= set(ids), "PENDING must be a sorted list of manifest ids"
    # enterprise rows check strings inside the lazily written iframe; every other kind is evaluated.
    with tempfile.TemporaryDirectory() as work:
        page, _ = build_report(work)
    failures = evaluate(page, rows)
    failed = {f[0] for f in failures}
    unexpected = [f for f in failures if f[0] not in PENDING]
    stale = [p for p in PENDING if p not in failed]
    print("manifest rows: %d; passing: %d; failing: %d; pending (expected failing): %d"
          % (len(rows), len(rows) - len(failures), len(failures), len(PENDING)))
    if PENDING:
        print("pending ids: " + ", ".join(PENDING))
    if stale:
        print("pending rows that now pass (remove from PENDING): " + ", ".join(stale))
    for fid, kind, check, why in unexpected:
        print("FAIL %s [%s] %s -- %s" % (fid, kind, check, why))
    assert not unexpected, "%d manifest feature(s) missing from the report" % len(unexpected)
    print("OK: every manifest feature outside PENDING is present")


if __name__ == "__main__":
    main()
