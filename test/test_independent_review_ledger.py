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
}
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
    raise KeyError(name)


def main():
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
        else:
            raise SystemExit(f"unknown kind {kind}")
        if got != expected or type(got) is not type(expected):
            print(f"  {ident}: FAIL {claim} -> the code now gives {got!r}, the row says {expected!r}")
            ok = False
        else:
            asserted_done.append(ident)
    print(f"  behaviour asserted for {len(asserted_done)} rows ({', '.join(asserted_done)})")
    print(f"  citation-only (line and enclosing definition checked, behaviour not): {len(citation_only)} rows ({', '.join(citation_only)})")
    if len(asserted_done) < MIN_ASSERTED:
        print(f"  FAIL fewer rows asserted ({len(asserted_done)}) than the {MIN_ASSERTED} recorded; a row lost its behaviour check")
        ok = False
    print("ALL REVIEW LEDGER TESTS PASSED" if ok else "REVIEW LEDGER TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
