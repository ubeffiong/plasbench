#!/usr/bin/env python3
"""Helper-subprocess timeouts (audit AU-044) and atomic merged tables (audit AU-049).

  - python/plasbench_common.subprocess_timeout(): generous default, PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS overrides, 0/off removes the limit;
  - a hung helper (a fake minimap2 / mash that never returns) now stops with TimeoutExpired instead of hanging the stage, in database_containment
    and clonal_groups (two of the files that had no timeout); a static scan finds no un-timed subprocess.run/call/check_* in the helper scripts it covers;
  - merge_pr_metrics.py, merge_bin_metrics.py and performance_summary.py write their table beside the final file and rename it, so a failure while
    writing leaves the previous table intact (it used to truncate it first).
"""
import ast
import csv
import importlib
import os
import stat
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")
sys.path.insert(0, PY)
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


import plasbench_common  # noqa: E402

os.environ.pop("PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS", None)
check("default timeout is generous (6 hours)", plasbench_common.subprocess_timeout() == 21600)
os.environ["PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS"] = "2.5"
check("the environment overrides it", plasbench_common.subprocess_timeout() == 2.5)
os.environ["PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS"] = "off"
check("'off' removes the limit", plasbench_common.subprocess_timeout() is None)
os.environ["PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS"] = "nonsense"
check("an unreadable value falls back to the default", plasbench_common.subprocess_timeout() == 21600)

# a hung helper
with tempfile.TemporaryDirectory() as tmp:
    for name in ("minimap2", "mash"):
        path = os.path.join(tmp, name)
        open(path, "w").write("#!/bin/sh\nsleep 30\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    open(os.path.join(tmp, "a.fa"), "w").write(">a\nACGT\n")
    old_path = os.environ["PATH"]
    if os.name != "nt":
        os.environ["PATH"] = tmp + os.pathsep + old_path
        os.environ["PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS"] = "1"
        import database_containment
        import clonal_groups
        t0 = time.time()
        try:
            database_containment.containment(os.path.join(tmp, "a.fa"), os.path.join(tmp, "a.fa"), 1)
            raised = False
        except subprocess.TimeoutExpired:
            raised = True
        check("database_containment: a hung minimap2 raises TimeoutExpired after the limit", raised and time.time() - t0 < 10)
        t0 = time.time()
        try:
            clonal_groups.mash_pairs({"s1": os.path.join(tmp, "a.fa"), "s2": os.path.join(tmp, "a.fa")}, 0.05, 1)
            raised = False
        except subprocess.TimeoutExpired:
            raised = True
        check("clonal_groups: a hung mash raises TimeoutExpired after the limit", raised and time.time() - t0 < 10)
        os.environ["PATH"] = old_path
    else:
        print("  SKIP: the hung-helper checks need a POSIX shell")
os.environ.pop("PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS", None)

# static scan: the helper scripts that were fixed carry a timeout on every run/call/check_* call
FIXED = ["annotate_proteins", "assembly_selection", "baseline_predictors", "build_hybrid_truth", "clonal_groups", "copy_number", "database_containment",
         "detect_dimers", "fetch_ena_reads", "intake", "prepare_contribution", "qc_pilot", "run_quast_diagnostics", "simulate_reads",
         "user_tool_adapter", "export_report_pdf", "prereg_admin", "make_depth_ladder", "make_read_quality_ladder", "compute_difficulty_features",
         "audit_three_class_scoring", "compare_scoring_methods", "build_implementation_catalogue"]
missing = []
for name in FIXED:
    tree = ast.parse(open(os.path.join(PY, name + ".py"), encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                and node.func.attr in ("run", "call", "check_call", "check_output") and "timeout" not in {k.arg for k in node.keywords}):
            missing.append(f"{name}:{node.lineno}")
check("no un-timed subprocess.run/call/check_* remains in the covered helper scripts", not missing, missing)

# atomic merged tables: a failure while writing leaves the previous table intact
with tempfile.TemporaryDirectory() as tmp:
    scores = os.path.join(tmp, "scores.tsv")
    original = "sample\ttool\tf1\ns1\tt\t0.5\n"
    for module_name, args in (("merge_pr_metrics", ["--scores", scores, "--results-dir", tmp]), ("merge_bin_metrics", ["--scores", scores, "--results-dir", tmp])):
        open(scores, "w", newline="").write(original)
        module = importlib.import_module(module_name)
        real = csv.DictWriter

        class Boom(real):
            def writerows(self, rows):
                raise OSError("disk full while writing")
        module.csv.DictWriter = Boom
        old_argv = sys.argv
        sys.argv = [module_name + ".py"] + args
        try:
            try:
                module.main()
                failed = False
            except OSError:
                failed = True
        finally:
            sys.argv = old_argv
            module.csv.DictWriter = real
        check(f"{module_name}: a failure while writing raises", failed)
        check(f"{module_name}: the previous scores.tsv is intact", open(scores, newline="").read() == original, open(scores, newline="").read())
        open(scores, "w", newline="").write(original)
        sys.argv = [module_name + ".py"] + args
        try:
            module.main()
        finally:
            sys.argv = old_argv
        leftover = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
        check(f"{module_name}: a normal run renames the temporary file away", not leftover and os.path.getsize(scores) > 0, leftover)

print("ALL HELPER TIMEOUT AND ATOMIC TABLE TESTS PASSED" if OK else "HELPER TIMEOUT AND ATOMIC TABLE TESTS FAILED")
sys.exit(0 if OK else 1)
