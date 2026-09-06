#!/usr/bin/env python3
"""The per-isolate assembly statistics must actually reach the model.

python/compute_assembly_stats.py computes gc_percent, n50, contig_count and
assembly_size_bp per sample during stage 2. Those were originally consumed
only by the advisory cohort-QC outlier flagger; the recommendation model never
saw them, even though isolate GC content was named as a wanted feature from
the start. This pins the join: stats are loaded from data/<sample>/, attached
to score rows, and a signal that exists ONLY in a stats field is enough to
make the model beat its fixed-weight baseline -- which it cannot do if the
field never reaches the feature matrix.

Also pins backward compatibility: a model JSON fitted before these fields
existed stored three continuous coefficients and no field list. Decoding it
against today's longer field tuple would silently misalign every coefficient
after the third, so the legacy layout must still be honoured.
"""

import csv
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from recommendation_model import (  # noqa: E402
    ASSEMBLY_STAT_FIELDS, CONTINUOUS_FIELDS, LEGACY_CONTINUOUS_FIELDS,
    attach_assembly_stats, encode_row, load_assembly_stats, spec_continuous_fields,
)

FIT = os.path.join(ROOT, "python", "fit_recommendation_model.py")
SAMPLE_FIELDS = ["sample_id", "organism", "gram_group", "read_depth_x", "source_study"]
SCORE_FIELDS = ["sample", "tool", "f1", "precision", "recall", "plasmid_recall",
                "true_plasmid_bp", "true_plasmid_count"]


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " -> PASS")


def write_stats(data_dir, sample, gc):
    sdir = os.path.join(data_dir, sample)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "assembly_stats.tsv"), "w", encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_size_bp\tcontig_count\tn50\tgc_percent\tplasmid_count\n")
        handle.write(f"{sample}\t5000000\t4\t4800000\t{gc:.4f}\t2\n")


# --- the join itself ---------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = os.path.join(tmp, "data")
    write_stats(data, "s1", 50.5)
    write_stats(data, "s2", 62.0)
    stats = load_assembly_stats(data)
    check("stats are loaded for every sample directory", set(stats) == {"s1", "s2"}, str(stats))
    check("every declared assembly-stat field is present",
          set(stats["s1"]) == set(ASSEMBLY_STAT_FIELDS), str(stats["s1"]))

    rows = [{"sample": "s1", "tool": "t"}, {"sample": "s2", "tool": "t"}, {"sample": "unknown", "tool": "t"}]
    attach_assembly_stats(rows, stats)
    check("a row gets its own sample's GC", rows[0]["gc_percent"] == "50.5000", str(rows[0]))
    check("a different sample gets a different GC", rows[1]["gc_percent"] == "62.0000", str(rows[1]))
    check("a sample with no stats is left alone (model imputes it later)",
          "gc_percent" not in rows[2], str(rows[2]))

    check("assembly stats are part of the model's continuous features",
          all(field in CONTINUOUS_FIELDS for field in ASSEMBLY_STAT_FIELDS), str(CONTINUOUS_FIELDS))

# --- a stats-only signal must be learnable -----------------------------------
# f1 depends ONLY on gc_percent here. read_depth_x is deliberately constant, so
# nothing in scores.tsv alone can explain the target: if the model beats the
# per-tool mean baseline, the GC feature demonstrably reached the fit.
with tempfile.TemporaryDirectory() as tmp:
    data = os.path.join(tmp, "data")
    rng = random.Random(20260906)
    sample_rows, score_rows = [], []
    sid = 0
    for study in range(4):
        for _ in range(8):
            sid += 1
            sample = f"s{sid}"
            gc = 40.0 + (sid % 20)
            f1 = min(0.99, max(0.01, 0.02 * (gc - 40.0) + 0.3 + rng.uniform(-0.01, 0.01)))
            write_stats(data, sample, gc)
            sample_rows.append({"sample_id": sample, "organism": "E. coli", "gram_group": "negative",
                                "read_depth_x": "50", "source_study": f"study{study}"})
            score_rows.append({"sample": sample, "tool": "toolA", "f1": f"{f1:.4f}",
                               "precision": f"{f1:.4f}", "recall": f"{f1:.4f}",
                               "plasmid_recall": f"{f1:.4f}",
                               "true_plasmid_bp": "100000", "true_plasmid_count": "2"})
    sheet, scores = os.path.join(tmp, "sheet.tsv"), os.path.join(tmp, "scores.tsv")
    with open(sheet, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, delimiter="\t")
        writer.writeheader(); writer.writerows(sample_rows)
    with open(scores, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS, delimiter="\t")
        writer.writeheader(); writer.writerows(score_rows)

    def fit(with_stats):
        out = os.path.join(tmp, f"model_{with_stats}.json")
        args = [sys.executable, FIT, "--scores", scores, "--sample-sheet", sheet, "--out", out,
                "--min-studies", "3", "--min-training-samples", "20"]
        if with_stats:
            args += ["--data-dir", data]
        subprocess.run(args, check=True, capture_output=True, text=True)
        return json.load(open(out, encoding="utf-8"))

    with_stats, without = fit(True), fit(False)
    check("with --data-dir, a GC-only signal makes the model ready",
          with_stats["model_ready"] is True, json.dumps(with_stats)[:400])
    check("without --data-dir the same cohort cannot learn it (the join is what matters)",
          without["model_ready"] is False, json.dumps(without)[:400])
    check("the fitted spec records the assembly-stat fields",
          all(field in with_stats["spec"]["continuous"] for field in ASSEMBLY_STAT_FIELDS),
          str(with_stats["spec"].get("continuous")))

# --- backward compatibility with a pre-stats model ---------------------------
legacy_spec = {
    "means": {field: 1.0 for field in LEGACY_CONTINUOUS_FIELDS},
    "stds": {field: 1.0 for field in LEGACY_CONTINUOUS_FIELDS},
    "vocab": {"tool": ["toolA"], "organism": ["E. coli"], "gram_group": ["negative"],
              "amr_status": ["not_recorded"]},
}
check("a spec with no field list decodes in the legacy 3-field order",
      spec_continuous_fields(legacy_spec) == list(LEGACY_CONTINUOUS_FIELDS),
      str(spec_continuous_fields(legacy_spec)))
legacy_vector = encode_row({"tool": "toolA", "organism": "E. coli", "gram_group": "negative"}, legacy_spec)
check("and produces a vector sized for that older layout, not today's",
      len(legacy_vector) == len(LEGACY_CONTINUOUS_FIELDS) + 4,
      f"got {len(legacy_vector)}")

print("ALL RECOMMENDATION MODEL FEATURE TESTS PASSED")
