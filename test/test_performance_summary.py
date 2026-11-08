#!/usr/bin/env python3
"""performance_summary.py: reliability, efficiency, CPU utilisation and scaling, by hand."""
import csv
import math
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "performance_summary.py")
HEAD = "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n"


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        data, logs = os.path.join(tmp, "data"), os.path.join(tmp, "logs")
        os.makedirs(logs)
        status = HEAD
        scores = "sample\ttool\trecovered_plasmid_count\n"
        # Tool "lin": runtime exactly proportional to genome length over 6 samples (exponent 1);
        # tool "quad": runtime proportional to length squared (exponent 2).
        for i, size in enumerate((1000, 1500, 2000, 3000, 4000, 8000)):
            sample = f"s{i}"
            os.makedirs(os.path.join(data, sample))
            open(os.path.join(data, sample, "truth.tsv"), "w").write(
                f"sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t{size}\n")
            status += f"{sample}\tlin\tcompleted\tx\t\t{size / 100}\t1048576\n"
            status += f"{sample}\tquad\tcompleted\tx\t\t{(size / 100) ** 2}\t2097152\n"
            scores += f"{sample}\tlin\t2\n{sample}\tquad\t1\n"
            open(os.path.join(logs, f"{sample}.lin.rss"), "w").write(f"1048576 {size / 200} {size / 200}\n")
        # Tool "flaky": 1 completed, 1 failed (tool), 1 killed by the OOM killer, 1 skipped.
        status += "s0\tflaky\tcompleted\tx\t\t10\t524288\n"
        status += "s1\tflaky\tfailed\t\tsegfault; exit_code=1\t\t\n"
        status += "s2\tflaky\tfailed\t\tnope; exit_code=137\t\t\n"
        status += "s3\tflaky\tskipped\t\tnot installed\t\t\n"
        scores += "s0\tflaky\t1\n"
        sp, sc, out = (os.path.join(tmp, n) for n in ("status.tsv", "scores.tsv", "perf.tsv"))
        open(sp, "w").write(status)
        open(sc, "w").write(scores)
        subprocess.run([sys.executable, SCRIPT, "--tool-status", sp, "--scores", sc, "--logs-dir", logs,
                        "--data-dir", data, "--threads", "4", "--out", out], check=True, capture_output=True)
        rows = {r["tool"]: r for r in csv.DictReader(open(out, newline=""), delimiter="\t")}

        check("flaky: success rate 1 of 3 attempts (skipped is not a failure)",
              abs(float(rows["flaky"]["success_rate"]) - 1 / 3) < 1e-6 and rows["flaky"]["n_skipped"] == "1")
        check("flaky: the out-of-memory kill is a resource failure, the segfault is not",
              rows["flaky"]["n_failed"] == "2" and rows["flaky"]["n_resource_failures"] == "1")
        check("lin: runtime scales linearly (exponent 1), quad quadratically (exponent 2)",
              abs(float(rows["lin"]["runtime_scaling_exponent"]) - 1) < 1e-6
              and abs(float(rows["quad"]["runtime_scaling_exponent"]) - 2) < 1e-6)
        check("memory exponent 0 when memory does not grow with input", abs(float(rows["lin"]["memory_scaling_exponent"])) < 1e-6)
        total_runtime = sum(s / 100 for s in (1000, 1500, 2000, 3000, 4000, 8000))
        check("cost per recovered plasmid = thread-seconds / plasmids recovered",
              abs(float(rows["lin"]["thread_seconds_per_recovered_plasmid"]) - total_runtime * 4 / 12) < 1e-4)
        check("memory reported in GB (1048576 kB = 1 GB)", abs(float(rows["lin"]["median_peak_memory_gb"]) - 1) < 1e-6)
        # CPU: user+system = runtime/100*... per run is size/100 s of cpu on 4 threads of runtime size/100 -> 0.25.
        check("cpu utilisation = cpu seconds / (runtime x threads) = 0.25",
              abs(float(rows["lin"]["cpu_utilisation"]) - 0.25) < 1e-6)
        check("a tool with no CPU files has blank utilisation (not evaluated)", rows["quad"]["cpu_utilisation"] == "")
        check("flaky has too few points for a scaling exponent (blank)", rows["flaky"]["runtime_scaling_exponent"] == "")
    print("ALL PERFORMANCE SUMMARY TESTS PASSED" if ok else "PERFORMANCE SUMMARY TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
