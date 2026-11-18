#!/usr/bin/env python3
"""NMI, Variation of Information and ARI penalise a plasmid that no bin covers (audit AU-003), checked against an independent per-base brute force."""

import math
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
from score_bins import adjusted_rand, clustering_agreement  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def brute(truth_labels, pred_labels):
    """(nmi, vi, ari) from two per-base label lists, written from the definitions (not from score_bins)."""
    n = len(truth_labels)
    joint = Counter(zip(truth_labels, pred_labels))
    a, b = Counter(truth_labels), Counter(pred_labels)
    h = lambda c: -sum(v / n * math.log(v / n) for v in c.values())      # noqa: E731
    mi = sum(v / n * math.log((v / n) / ((a[x] / n) * (b[y] / n))) for (x, y), v in joint.items())
    ha, hb = h(a), h(b)
    nmi = 1.0 if ha < 1e-12 and hb < 1e-12 else 0.0 if ha < 1e-12 or hb < 1e-12 else 2 * mi / (ha + hb)
    c2 = lambda m: m * (m - 1) / 2                                          # noqa: E731
    index = sum(c2(v) for v in joint.values())
    sa, sb = sum(c2(v) for v in a.values()), sum(c2(v) for v in b.values())
    expected = sa * sb / c2(n)
    ari = (index - expected) / ((sa + sb) / 2 - expected) if (sa + sb) / 2 != expected else None
    return nmi, ha + hb - 2 * mi, ari


def expand(plasmids, bins, chromosome_claims):
    """Per-base truth and prediction labels for the scoped table: bases of true plasmids (each missed base is its own predicted cluster) plus claimed chromosome bases."""
    truth, pred, k = [], [], 0
    for plasmid, length in plasmids.items():
        covered = 0
        for bin_id, cover in bins.get(plasmid, {}).items():
            truth += [plasmid] * cover
            pred += [bin_id] * cover
            covered += cover
        for _ in range(length - covered):
            truth.append(plasmid)
            pred.append(f"missed{k}")
            k += 1
    for bin_id, bp in chromosome_claims.items():
        truth += ["CHROMOSOME"] * bp
        pred += [bin_id] * bp
    return truth, pred


def run(plasmids, bins, chromosome_claims):
    overlaps = {(b, p): bp for p, d in bins.items() for b, bp in d.items()}
    return clustering_agreement(overlaps, plasmids, chromosome_claims, set()), adjusted_rand(overlaps, plasmids, chromosome_claims)


fixtures = {
    "the audit's fixture: two exact bins, the third plasmid never binned": ({"p1": 100, "p2": 200, "p3": 50}, {"p1": {"A": 100}, "p2": {"B": 200}}, {}),
    "two plasmids missed": ({"p1": 100, "p2": 200, "p3": 50, "p4": 70}, {"p1": {"A": 100}, "p2": {"B": 200}}, {}),
    "a half-covered plasmid": ({"p1": 100, "p2": 200}, {"p1": {"A": 100}, "p2": {"B": 100}}, {}),
    "chromosome claimed by a bin": ({"p1": 100, "p2": 200}, {"p1": {"A": 100}, "p2": {"B": 200}}, {"B": 30}),
    "everything binned correctly": ({"p1": 100, "p2": 200, "p3": 50}, {"p1": {"A": 100}, "p2": {"B": 200}, "p3": {"C": 50}}, {}),
    "merged bin plus a missed plasmid": ({"p1": 100, "p2": 200, "p3": 50}, {"p1": {"A": 100}, "p2": {"A": 200}}, {}),
}
results = {}
for label, (plasmids, bins, chrom) in fixtures.items():
    (nmi, vi), ari = run(plasmids, bins, chrom)
    want_nmi, want_vi, want_ari = brute(*expand(plasmids, bins, chrom))
    results[label] = (nmi, vi, ari)
    check(f"{label}: NMI, VI and ARI equal the per-base brute force (nmi {nmi:.4f}, vi {vi:.4f}, ari {ari:.4f})",
          abs(nmi - want_nmi) < 1e-9 and abs(vi - want_vi) < 1e-9 and ari is not None and abs(ari - want_ari) < 1e-9, ((nmi, vi, ari), (want_nmi, want_vi, want_ari)))

nmi, vi, ari = results["the audit's fixture: two exact bins, the third plasmid never binned"]
check("a wholly missed plasmid is no longer perfect: NMI < 1, VI > 0, ARI < 1", nmi < 0.999 and vi > 0.01 and ari < 0.999, (nmi, vi, ari))
nmi_ok, vi_ok, ari_ok = results["everything binned correctly"]
check("binning everything correctly is still perfect (1, 0, 1)", abs(nmi_ok - 1) < 1e-9 and abs(vi_ok) < 1e-9 and abs(ari_ok - 1) < 1e-9)
check("missing two plasmids scores worse than missing one", results["two plasmids missed"][0] < nmi and results["two plasmids missed"][1] > vi)

print("ALL BIN CLUSTERING MISSED-PLASMID TESTS PASSED" if ok else "BIN CLUSTERING MISSED-PLASMID TESTS FAILED")
sys.exit(0 if ok else 1)
