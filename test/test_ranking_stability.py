#!/usr/bin/env python3
"""ranking_stability.py: leave-one-study-out, leave-one-species-out and equal-study-weighted rankings on a built cohort."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)

import ranking_stability as rs  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(header)
        w.writerows(rows)


def table(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=TAB))


tmp = tempfile.mkdtemp()
# Tool A leads only because of study S1 (10 isolates); in S2 and S3 tool B is better. Two species.
sheet, scores = [], []
for study, species, n, a, b in (("S1", "Escherichia coli", 10, 0.9, 0.5), ("S2", "Klebsiella pneumoniae", 3, 0.4, 0.7), ("S3", "Escherichia coli", 3, 0.4, 0.7)):
    for i in range(n):
        s = f"{study}_{i}"
        sheet.append([s, species, study, study])
        for tool, v in (("mob_recon", a), ("gplas2_mob", b)):
            scores.append([s, tool, "short_read", f"{v:.3f}"])
write(os.path.join(tmp, "samples.tsv"), ["sample_id", "organism", "bioproject", "source_study"], sheet)
write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "analysis_track", "lw_bin_f1"], scores)
prefix = os.path.join(tmp, "benchmark")
done = subprocess.run([sys.executable, os.path.join(PY, "ranking_stability.py"), "--scores", os.path.join(tmp, "scores.tsv"),
                       "--sample-sheet", os.path.join(tmp, "samples.tsv"), "--out-prefix", prefix, "--min-isolates", "2"],
                      capture_output=True, text=True)
check("the script runs", done.returncode == 0, done.stderr[-300:])
stab = table(prefix + ".ranking_stability.tsv")
check("one summary row for the binning task", len(stab) == 1 and stab[0]["evaluation_task"] == "binning_reconstruction", stab)
s = stab[0]
check("the full-cohort leader is the tool that wins the big study", s["baseline_leader"] == "mob_recon", s)
check("the shares of the largest study and species are reported", s["largest_study"] == "S1" and abs(float(s["largest_study_share"]) - 10 / 16) < 1e-3
      and s["largest_species"] == "Escherichia coli", s)
by_study = {r["left_out"]: r for r in table(prefix + ".study_sensitivity.tsv")}
check("leaving the large study out changes the leader", by_study["S1"]["leader_changed"] == "yes" and by_study["S1"]["leader"] == "gplas2_mob", by_study.get("S1"))
check("leaving a small study out does not", by_study["S2"]["leader_changed"] == "no", by_study.get("S2"))
by_species = {r["left_out"]: r for r in table(prefix + ".species_sensitivity.tsv")}
check("the species leave-out is reported", set(by_species) == {"Escherichia coli", "Klebsiella pneumoniae"}, set(by_species))
check("giving every study equal weight changes the leader", s["equal_study_leader"] == "gplas2_mob", s)
check("the verdict calls this ranking fragile", s["verdict"].startswith("fragile"), s["verdict"])

# a stable cohort
scores2 = [[f"S{k}_{i}", t, "short_read", f"{v:.3f}"] for k in range(3) for i in range(4) for t, v in (("mob_recon", 0.9), ("gplas2_mob", 0.5))]
sheet2 = [[f"S{k}_{i}", "Escherichia coli" if k < 2 else "Klebsiella pneumoniae", f"S{k}", f"S{k}"] for k in range(3) for i in range(4)]
write(os.path.join(tmp, "samples2.tsv"), ["sample_id", "organism", "bioproject", "source_study"], sheet2)
write(os.path.join(tmp, "scores2.tsv"), ["sample", "tool", "analysis_track", "lw_bin_f1"], scores2)
rs.main(["--scores", os.path.join(tmp, "scores2.tsv"), "--sample-sheet", os.path.join(tmp, "samples2.tsv"), "--out-prefix", os.path.join(tmp, "b2"), "--min-isolates", "2"])
check("a cohort where one tool always wins is called stable", table(os.path.join(tmp, "b2.ranking_stability.tsv"))[0]["verdict"].startswith("stable"))

# no sample sheet: no study or species rows, said so
rs.main(["--scores", os.path.join(tmp, "scores2.tsv"), "--out-prefix", os.path.join(tmp, "b3")])
r3 = table(os.path.join(tmp, "b3.ranking_stability.tsv"))[0]
check("without a sample sheet it says it could not assess, and does not claim stability", r3["verdict"].startswith("not_assessed"), r3["verdict"])

print("ALL RANKING STABILITY TESTS PASSED" if ok else "RANKING STABILITY TESTS FAILED")
sys.exit(0 if ok else 1)
