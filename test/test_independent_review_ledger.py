#!/usr/bin/env python3
"""Every row of the evidence ledger in docs/INDEPENDENT_REVIEW.md still points at real code, and where
feasible the code still does what the row says (audit AU-045).

A row names `path:line` and a symbol. Three checks, each stricter than "the symbol is on that line":

  1. The symbol is on the cited line (a moved or renamed line fails here).
  2. For Python files the cited line sits inside the definition the row was written against
     (DEFINITION below, recorded from the code at the time of the audit). A symbol that now
     appears on the same line number inside a different function, or at module level, fails.
  3. For the rows in ASSERTED the cited behaviour is executed or read from the code and compared with
     the value the row states (a default, a threshold, a computed example). A row whose line still
     matches but whose behaviour changed fails here. Rows not in ASSERTED are citation-only; the test
     prints them and fixes their number so the share cannot fall unnoticed.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
ROW = re.compile(r"^\| (E\d+) \| (.*?) \| `([^`:]+):(\d+)` \| `([^`]+)` \|\s*$")

# Enclosing definition of the cited line, for each Python row ("<module>" = module-level statement).
DEFINITION = {
    "E1": "score", "E2": "score", "E3": "parse_paf_intervals", "E4": "main", "E5": "main", "E6": "main", "E7": "main",
    "E12": "main", "E13": "main", "E14": "main", "E15": "length_weighted_binning", "E16": "maximum_weight",
    "E17": "correct_reconstruction", "E20": "bootstrap_ci", "E21": "paired_permutation_pvalue", "E22": "holm_adjust",
    "E23": "attach_significance", "E24": "bootstrap_ci", "E25": "sample_clusters", "E26": "_join_clusters",
    "E27": "<module>", "E28": "__init__", "E29": "shared_values", "E30": "build_variants", "E31": "analyse",
    "E32": "main", "E33": "derive", "E35": "classify", "E36": "<module>", "E37": "write_model_card",
    "E38": "reference_bootstrap", "E40": "<module>", "E52": "<module>", "E53": "<module>", "E54": "label",
    "E55": "<module>",
}

# Behaviour check for a row: ("argparse_default", argument, expected), ("function_default", parameter, expected),
# ("shell_default", variable, expected), ("module_constant", name, expected) or ("call", callable, claim_token).
# claim_token must appear in the row's own wording, so the doc and the code cannot drift apart silently.
ASSERTED = {
    "E4": ("argparse_default", "--min-alignment-length", 1, "1"),
    "E5": ("argparse_default", "--min-alignment-identity", 0.0, "0"),
    "E6": ("argparse_default", "--min-alignment-mapq", 0, "0"),
    "E7": ("argparse_default", "--min-alignment-query-coverage", 0.0, "0"),
    "E8": ("shell_default", "MIN_ALIGNMENT_LENGTH", "200", "200"),
    "E9": ("shell_default", "MIN_ALIGNMENT_IDENTITY", "0.90", "0.90"),
    "E10": ("shell_default", "MIN_ALIGNMENT_MAPQ", "20", "20"),
    "E11": ("shell_default", "MIN_ALIGNMENT_QUERY_COVERAGE", "0.20", "0.20"),
    "E13": ("argparse_default", "--min-bin-purity", 0.9, "0.9"),
    "E14": ("argparse_default", "--split-threshold", 0.1, "0.1"),
    "E18": ("shell_default", "CPRR_MIN_COVERAGE", "0.95", "0.95"),
    "E19": ("shell_default", "CPRR_MIN_IDENTITY", "0.99", "0.99"),
    "E20": ("module_constant", ("resampling", "MIN_CLUSTERS_CI"), 5, "five"),
    "E21": ("module_constant", ("resampling", "MIN_CLUSTERS_TEST"), 6, "six"),
    "E28": ("function_default", "min_species_clusters", 20, "20"),
    "E32": ("argparse_default", "--min-long-read-depth", 5.0, "5"),
    "E42": ("shell_default", "EXCLUDE_DATABASE_OVERLAP", "0", "off"),
    "E1": ("call", "tp_is_covered_plasmid_bases", None),
    "E2": ("call", "fn_is_total_minus_tp", None),
    "E3": ("call", "unmapped_is_not_fp", None),
    "E22": ("call", "holm_values", None),
    # AU-045 second pass: the remaining rows whose claim is a constant, a default or a guard the code can be made to show.
    "E12": ("source_contains", "completeness[seq_id] >= 0.99995", True, "0.99995"),
    "E15": ("call", "length_weighted_uses_aligned_bases", None),
    "E16": ("call", "ungated_hungarian", None),
    "E17": ("call", "cprr_after_match", None),
    "E23": ("call", "significance_vs_runner_up", None),
    "E24": ("call", "percentile_cluster_bootstrap", None),
    "E25": ("call", "legacy_clusters_bioproject_or_study", None),
    "E26": ("call", "headline_union_find", None),
    "E27": ("module_constant", ("headline_design", "PRIMARY_UNAVAILABLE"), "unavailable", "unavailable"),
    "E29": ("call", "ranking_set_shared", None),
    "E33": ("call", "tier_from_strategy_polish_cohort", None),
    "E35": ("call", "date_overlap_screen", None),
    "E36": ("call", "mash_screen_marked_experimental", None),
    "E37": ("call", "ridge_penalty_disclosure", None),
    "E38": ("call", "bootstrap_oracle_matches", None),
    "E39": ("source_contains", "apt-get install -y -qq minimap2", True, "minimap2"),
    "E40": ("source_contains", '"base_level_metrics_valid": "yes" if polish in ("none", "independent") else "no"', True, "same-read polishing"),
    "E41": ("call", "tool_database_first_row", None),
    "E43": ("source_contains", "  - barrnap ", True, "barrnap"),
    "E44": ("source_contains", "need minimap2\nneed python3", True, "hard requirement"),
    "E52": ("module_constant", ("make_truth", "REVIEW"), "REVIEW", "REVIEW"),
    "E53": ("call", "allow_default_flag", None),
    "E54": ("call", "conflicting_evidence_ambiguous", None),
    "E55": ("module_constant", ("truth_provenance", "POLISH"), ("none", "independent", "same_as_benchmark", "unknown"), "polished"),
    "E56": ("call", "cohort_tiers", None),
}
# Kinds that read the cited file's text instead of executing it: the value is pinned, not exercised.
SOURCE_PINNED = ("source_contains",)
MIN_ASSERTED = len(ASSERTED)


def enclosing_definition(tree, line):
    best, best_line = "<module>", 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.lineno <= line <= node.end_lineno:
            if node.lineno >= best_line:
                best, best_line = node.name, node.lineno
    return best


def argparse_default(tree, argument):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == argument):
            for keyword in node.keywords:
                if keyword.arg == "default":
                    return ast.literal_eval(keyword.value)
    return "<no default>"


def function_default(tree, parameter):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            names = [a.arg for a in node.args.args]
            defaults = node.args.defaults
            offset = len(names) - len(defaults)
            if parameter in names and names.index(parameter) >= offset:
                return ast.literal_eval(defaults[names.index(parameter) - offset])
    return "<no default>"


def shell_default(text, variable):
    match = re.search(r'export ' + re.escape(variable) + r'="\$\{' + re.escape(variable) + r':-([^}]*)\}"', text)
    return match.group(1) if match else "<no default>"


def behaviour_call(name):
    import score_plasmids as sp
    import aggregate_results as ar
    truth = {"pA": ("PLASMID", 100), "chr": ("CHROMOSOME", 500)}
    if name == "tp_is_covered_plasmid_bases":
        return sp.score(truth, 100, {"pA": [(0, 40)]})[0] == 40
    if name == "fn_is_total_minus_tp":
        return sp.score(truth, 100, {"pA": [(0, 40)]})[2] == 60
    if name == "unmapped_is_not_fp":
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            paf = os.path.join(tmp, "x.paf")
            with open(paf, "w", encoding="utf-8") as handle:
                handle.write("q1\t100\t0\t100\t+\tpA\t100\t0\t100\t100\t100\t60\ttp:A:P\n")
            covered, unmapped, _, mapped, _, _ = sp.parse_paf_intervals(paf, truth, {"q1": 100, "q2": 50})
        return unmapped == 50 and mapped == 100 and sp.score(truth, 100, covered)[1] == 0
    if name == "holm_values":
        got = ar.holm_adjust([0.01, 0.04, 0.03, 0.20])
        return all(abs(a - b) < 1e-12 for a, b in zip(got, [0.04, 0.09, 0.09, 0.20]))
    if name in EXTRA:
        return EXTRA[name]()
    raise KeyError(name)


def _tmp_file(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def _extra_checks():
    """Executable checks for the second-pass rows; each returns True only when the code gives the row's stated behaviour."""
    import csv
    import datetime
    import tempfile
    checks = {}

    def length_weighted_uses_aligned_bases():
        import score_bins as sb
        # 100 bp of plasmid truth, 100 bp mapped into the bin, 50 of them on the matching plasmid: precision is over MAPPED (aligned) bases.
        got = sb.length_weighted_binning({("b1", "pA"): 50}, {"pA": 100}, {"b1": 100}, {"b1"})
        fewer_mapped = sb.length_weighted_binning({("b1", "pA"): 50}, {"pA": 100}, {"b1": 50}, {"b1"})
        return got["precision"] == 0.5 and got["recall"] == 0.5 and fewer_mapped["precision"] == 1.0
    checks["length_weighted_uses_aligned_bases"] = length_weighted_uses_aligned_bases

    def ungated_hungarian():
        import score_bins as sb
        # A 1 bp overlap is still matched (no purity or coverage gate inside the match), and the match is one-to-one.
        one = sb.maximum_weight({("b1", "pA"): 1}, ["b1"], ["pA"]) == [("b1", "pA", 1)]
        two = sb.maximum_weight({("b1", "pA"): 10, ("b2", "pA"): 9}, ["b1", "b2"], ["pA"])
        return one and two == [("b1", "pA", 10)]
    checks["ungated_hungarian"] = ungated_hungarian

    def cprr_after_match():
        import score_bins as sb
        ident = {("b1", "pA"): (99, 100)}
        ok_row = sb.correct_reconstruction([("b1", "pA", 96)], {("b1", "pA"): 96}, {"pA": 100}, {"b1": 100}, ident, {}, 0.95, 0.9, 0.99)
        short = sb.correct_reconstruction([("b1", "pA", 90)], {("b1", "pA"): 90}, {"pA": 100}, {"b1": 100}, ident, {}, 0.95, 0.9, 0.99)
        unmatched = sb.correct_reconstruction([], {}, {"pA": 100}, {}, {}, {}, 0.95, 0.9, 0.99)
        return (ok_row[0]["correct"] == "yes" and short[0]["correct"] == "no" and short[0]["coverage_ok"] == "no"
                and unmatched[0]["correct"] == "no" and unmatched[0]["identified"] == "no")
    checks["cprr_after_match"] = cprr_after_match

    def significance_vs_runner_up():
        import aggregate_results as ar

        def pair(p):
            return [{"tool_a": "b", "tool_b": "a", "permutation_p_value_holm": p}]
        sig = ar.attach_significance([{"tool": "a"}, {"tool": "b"}], pair(0.01))
        non = ar.attach_significance([{"tool": "a"}, {"tool": "b"}], pair(0.2))
        untested = ar.attach_significance([{"tool": "a"}, {"tool": "b"}], pair(None))
        single = ar.attach_significance([{"tool": "a"}], [])
        return (sig[0]["significant_vs_runner_up"] is True and sig[1]["significant_vs_runner_up"] == "not_assessed"
                and non[0]["significant_vs_runner_up"] is False and untested[0]["significant_vs_runner_up"] == "not_assessed"
                and single[0]["significant_vs_runner_up"] == "not_assessed")
    checks["significance_vs_runner_up"] = significance_vs_runner_up

    def percentile_cluster_bootstrap():
        import random
        import statistics
        import resampling
        values = [0.1, 0.4, 0.5, 0.7, 0.9, 0.3, 0.6]
        rng = random.Random(20260831)
        means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000))
        low, high = resampling.bootstrap_ci(values)
        ungrouped = abs(low - means[25]) < 1e-9 and abs(high - means[974]) < 1e-9
        # Clusters are the resampling unit: two clusters are fewer than the five independent units an interval needs, so no interval at all.
        clustered = resampling.bootstrap_ci([0.0] * 5 + [1.0] * 5, groups=["a"] * 5 + ["b"] * 5)
        return ungrouped and clustered == (None, None)
    checks["percentile_cluster_bootstrap"] = percentile_cluster_bootstrap

    def legacy_clusters_bioproject_or_study():
        import aggregate_results as ar
        with tempfile.TemporaryDirectory() as tmp:
            sheet = _tmp_file(tmp, "s.tsv", "sample_id\tbioproject\tsource_study\nx\tPRJ1\tS1\ny\t\tS2\nz\t\t\n")
            clusters, used = ar.sample_clusters(sheet)
        return clusters == {"x": "bioproject:PRJ1", "y": "source_study:S2"} and used == "bioproject" and "z" not in clusters
    checks["legacy_clusters_bioproject_or_study"] = legacy_clusters_bioproject_or_study

    def headline_union_find():
        import headline_design
        sheet = [{"sample_id": "a", "bioproject": "P1"}, {"sample_id": "b", "bioproject": "P2"}, {"sample_id": "c", "bioproject": "P3"},
                 {"sample_id": "d", "bioproject": "P1"}]
        joined = headline_design.Design._join_clusters(sheet, {"b": "g1", "c": "g1"})
        return joined["a"] == joined["d"] and joined["b"] == joined["c"] and joined["a"] != joined["b"]
    checks["headline_union_find"] = headline_union_find

    def ranking_set_shared():
        import headline_design
        rows = [{"tool": "t1", "sample": "s1", "f1": 0.5}, {"tool": "t1", "sample": "s2", "f1": 0.6},
                {"tool": "t2", "sample": "s2", "f1": 0.7}]
        by_tool, shared, zeros = headline_design.shared_values(rows, "f1", failed_samples={"t2": ["s1"]})
        _, shared_without_failure, _ = headline_design.shared_values(rows, "f1")
        return shared == {"s1", "s2"} and by_tool["t2"]["s1"] == 0.0 and zeros["t2"] == 1 and shared_without_failure == {"s2"}
    checks["ranking_set_shared"] = ranking_set_shared

    def tier_from_strategy_polish_cohort():
        import truth_provenance as tp
        got = (tp.tier("long_read_first_hybrid", "none", "A", True)[0],
               tp.tier("long_read_first_hybrid", "same_as_benchmark", "A", True)[0],
               tp.tier("long_read_first_hybrid", "none", "B", True)[0],
               tp.tier("short_read_first_hybrid", "none", "A", True)[0],
               tp.tier("long_read_only", "none", "C", True)[0])
        return got == ("1", "2", "2", "3", "3")
    checks["tier_from_strategy_polish_cohort"] = tier_from_strategy_polish_cohort

    def date_overlap_screen():
        import flag_database_overlap as fo
        got = (fo.classify(datetime.date(2020, 1, 1), "yes", datetime.date(2020, 5, 4))[0],
               fo.classify(datetime.date(2020, 5, 4), "yes", datetime.date(2020, 5, 4))[0],
               fo.classify(datetime.date(2021, 1, 1), "yes", datetime.date(2020, 5, 4))[0])
        return got == ("possible_overlap", "possible_overlap", "after_database")
    checks["date_overlap_screen"] = date_overlap_screen

    def mash_screen_marked_experimental():
        import classify_operational_plasmid as cop
        return "EXPERIMENTAL AND UNVALIDATED" in (cop.__doc__ or "")[:200]
    checks["mash_screen_marked_experimental"] = mash_screen_marked_experimental

    def ridge_penalty_disclosure():
        import fit_recommendation_model as fm
        claim = "lambda was selected on the same LOSO folds"
        with tempfile.TemporaryDirectory() as tmp:
            scores = _tmp_file(tmp, "scores.tsv", "a\n")
            sheet = _tmp_file(tmp, "sheet.tsv", "b\n")
            card = os.path.join(tmp, "card.md")
            fm.write_model_card(card, {"validation": {"strategy": "approximate_loso"}}, scores, sheet, [])
            with open(card, encoding="utf-8") as handle:
                approx = handle.read()
            fm.write_model_card(card, {"validation": {"strategy": "nested"}}, scores, sheet, [])
            with open(card, encoding="utf-8") as handle:
                nested = handle.read()
        return claim in approx and claim not in nested
    checks["ridge_penalty_disclosure"] = ridge_penalty_disclosure

    def bootstrap_oracle_matches():
        import resampling
        path = os.path.join(ROOT, "test", "test_robustness_diagnostics.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        source = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "reference_bootstrap"]
        if not source:
            return False
        namespace = {"random": __import__("random"), "statistics": __import__("statistics")}
        exec(compile(ast.Module(body=source, type_ignores=[]), path, "exec"), namespace)
        values = [0.2, 0.5, 0.55, 0.8, 0.9, 0.35]
        ref = namespace["reference_bootstrap"](values)
        got = resampling.bootstrap_ci(values)
        return all(abs(a - b) < 1e-9 for a, b in zip(ref, got))
    checks["bootstrap_oracle_matches"] = bootstrap_oracle_matches

    def tool_database_first_row():
        with open(os.path.join(ROOT, "config", "tool_database_releases.tsv"), encoding="utf-8", newline="") as handle:
            first = next(csv.DictReader(handle, delimiter="\t"))
        return first["tool"] == "mob_recon" and first["uses_reference_database"] == "yes" and first["database_release_date"] == "2020-05-04"
    checks["tool_database_first_row"] = tool_database_first_row

    def allow_default_flag():
        with open(os.path.join(ROOT, "python", "make_truth.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--allow-default"):
                return any(k.arg == "action" and ast.literal_eval(k.value) == "store_true" for k in node.keywords)
        return False
    checks["allow_default_flag"] = allow_default_flag

    def conflicting_evidence_ambiguous():
        import label_truth_evidence as lt
        row = {"sequence_id": "s", "molecule_type": "CHROMOSOME", "length": "10"}
        status = {"markers": True, "rrna": True}
        conflict = lt.label(row, "big", {"s": {"repA"}}, {"s": 0}, status, None, None, 5.0)
        clean = lt.label(row, "s", {}, {"s": 3}, status, None, None, 5.0)
        return conflict["final_label"] == "AMBIGUOUS" and clean["final_label"] == "CHROMOSOME"
    checks["conflicting_evidence_ambiguous"] = conflicting_evidence_ambiguous

    def cohort_tiers():
        with open(os.path.join(ROOT, "cohorts", "public-v3.tsv"), encoding="utf-8", newline="") as handle:
            lines = [line for line in handle if line.strip() and not line.startswith("#")]
        rows = list(csv.DictReader(lines, delimiter="\t"))
        tiers = {r["truth_quality_tier"] for r in rows}
        return len(rows) >= 10 and tiers <= {"A", "B", "C"} and "A" in tiers and all(r["sample_id"] for r in rows)
    checks["cohort_tiers"] = cohort_tiers
    return checks


EXTRA = {}


def main():
    EXTRA.update(_extra_checks())
    with open(os.path.join(ROOT, "docs", "INDEPENDENT_REVIEW.md"), encoding="utf-8") as handle:
        rows = [ROW.match(line) for line in handle]
    rows = [match for match in rows if match]
    ok = len(rows) >= 40
    print(f"  ledger has {len(rows)} rows: {'PASS' if ok else 'FAIL'}")
    asserted_done, citation_only = [], []
    for match in rows:
        ident, claim, path, number, symbol = match.groups()
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full) and path.startswith(".github/") and not os.path.isdir(os.path.join(ROOT, ".github")):
            # Release archives (scripts/make_release.sh) leave out .github/; the
            # row is still checked in a git checkout and in CI.
            print(f"  {ident}: SKIP {path} is not shipped in release archives")
            continue
        if not os.path.isfile(full):
            print(f"  {ident}: FAIL missing file {path}")
            ok = False
            continue
        with open(full, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        lines = source.splitlines()
        index = int(number)
        if not (index <= len(lines) and symbol in lines[index - 1]):
            found = [n for n, text in enumerate(lines, 1) if symbol in text][:3]
            print(f"  {ident}: FAIL {path}:{number} lacks `{symbol}` (found at {found})")
            ok = False
            continue
        tree = None
        if path.endswith(".py"):
            tree = ast.parse(source)
            actual = enclosing_definition(tree, index)
            if ident not in DEFINITION:
                print(f"  {ident}: FAIL Python row has no recorded definition (add it to DEFINITION; it is `{actual}`)")
                ok = False
            elif actual != DEFINITION[ident]:
                print(f"  {ident}: FAIL {path}:{number} is now inside `{actual}`, the row was written against `{DEFINITION[ident]}`")
                ok = False
        spec = ASSERTED.get(ident)
        if spec is None:
            citation_only.append(ident)
            continue
        kind, target, expected = spec[0], spec[1], spec[2]
        token = spec[3] if len(spec) > 3 else None
        if token is not None and token not in claim:
            print(f"  {ident}: FAIL the row no longer states `{token}`: {claim}")
            ok = False
            continue
        if kind == "argparse_default":
            got = argparse_default(tree, target)
        elif kind == "function_default":
            got = function_default(tree, target)
        elif kind == "shell_default":
            got = shell_default(source, target)
        elif kind == "module_constant":
            module = __import__(target[0])
            got = getattr(module, target[1])
        elif kind == "call":
            got, expected = behaviour_call(target), True
        elif kind == "source_contains":
            got = target in source.replace("\r\n", "\n")
        else:
            raise SystemExit(f"unknown kind {kind}")
        if got != expected or type(got) is not type(expected):
            print(f"  {ident}: FAIL {claim} -> the code now gives {got!r}, the row says {expected!r}")
            ok = False
        else:
            asserted_done.append(ident)
    pinned = [i for i in asserted_done if ASSERTED[i][0] in SOURCE_PINNED]
    print(f"  behaviour asserted for {len(asserted_done)} rows ({', '.join(asserted_done)})")
    print(f"  of those, {len(pinned)} pin the value in the file's text and do not execute it ({', '.join(pinned)})")
    print(f"  citation-only (line and enclosing definition checked, behaviour not): {len(citation_only)} rows ({', '.join(citation_only)})")
    if len(asserted_done) < MIN_ASSERTED:
        print(f"  FAIL fewer rows asserted ({len(asserted_done)}) than the {MIN_ASSERTED} recorded; a row lost its behaviour check")
        ok = False
    print("ALL REVIEW LEDGER TESTS PASSED" if ok else "REVIEW LEDGER TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
