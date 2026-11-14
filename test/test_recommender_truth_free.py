#!/usr/bin/env python3
"""
The recommendation model is fitted on truth-free features only (python/recommendation_model.py).

  - the continuous and categorical features are disjoint from TRUTH_DERIVED_FIELDS (true plasmid size and count, the truth's AMR annotation);
  - fit_feature_spec() records both field lists, and refuses a truth-derived feature (assert_truth_free);
  - a spec from before the explicit lists still decodes (legacy continuous and categorical layouts), and truth_derived_in_spec() reports what it used;
  - load_model() does not serve a ready model whose spec used a truth-derived feature, and says why; a truth-free model is served;
  - a model fitted from score rows that carry the truth columns does not use them: the encoded vector has no slot for them and changing them changes nothing.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python"))

import recommendation_model as rm  # noqa: E402


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + str(detail), file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " -> PASS")


ROWS = [{"tool": t, "organism": o, "gram_group": "neg", "read_depth_x": d, "gc_percent": 50.0 + d / 10, "n50": 1e5, "contig_count": 100 + d,
         "assembly_size_bp": 5e6, "true_plasmid_bp": 1000 * d, "true_plasmid_count": d % 4, "amr_status": "AMR annotated" if d % 2 else "AMR not annotated"}
        for t in ("a", "b") for o in ("E. coli", "K. pneumoniae") for d in (10, 20, 30, 40)]

print("the features")
check("no continuous feature is truth-derived", not (set(rm.CONTINUOUS_FIELDS) & rm.TRUTH_DERIVED_FIELDS), rm.CONTINUOUS_FIELDS)
check("no categorical feature is truth-derived", not (set(rm.CATEGORICAL_FIELDS) & rm.TRUTH_DERIVED_FIELDS), rm.CATEGORICAL_FIELDS)
check("the truth-free inputs are the measured read depth, the assembly's own statistics and the organism metadata",
      set(rm.CONTINUOUS_FIELDS) == {"read_depth_x", "gc_percent", "n50", "contig_count", "assembly_size_bp"} and set(rm.CATEGORICAL_FIELDS) == {"tool", "organism", "gram_group"})
try:
    rm.assert_truth_free(["gc_percent", "true_plasmid_count"])
    refused = False
except ValueError as error:
    refused = "true_plasmid_count" in str(error)
check("assert_truth_free refuses a truth-derived field and names it", refused)
rm.assert_truth_free(list(rm.CONTINUOUS_FIELDS) + list(rm.CATEGORICAL_FIELDS))

print("the fitted spec")
spec = rm.fit_feature_spec(ROWS)
check("the spec records both field lists, truth-free", spec["continuous"] == list(rm.CONTINUOUS_FIELDS) and spec["categorical"] == list(rm.CATEGORICAL_FIELDS)
      and not rm.truth_derived_in_spec(spec), spec)
check("the vocabulary has no amr_status block", "amr_status" not in spec["vocab"])
base = rm.encode_row(ROWS[0], spec)
changed = dict(ROWS[0], true_plasmid_bp=1, true_plasmid_count=99, amr_status="whatever")
check("the encoded vector ignores the truth columns", rm.encode_row(changed, spec) == base and len(base) == len(rm.CONTINUOUS_FIELDS) + sum(len(spec["vocab"][f]) for f in spec["categorical"]))

print("older specs and models")
legacy = {"means": {f: 1.0 for f in rm.LEGACY_CONTINUOUS_FIELDS}, "stds": {f: 1.0 for f in rm.LEGACY_CONTINUOUS_FIELDS},
          "vocab": {f: ["x", "y"] for f in rm.LEGACY_CATEGORICAL_FIELDS}}
check("a spec without explicit lists still decodes against the legacy layouts",
      rm.spec_continuous_fields(legacy) == list(rm.LEGACY_CONTINUOUS_FIELDS) and rm.spec_categorical_fields(legacy) == list(rm.LEGACY_CATEGORICAL_FIELDS)
      and len(rm.encode_row({"tool": "x"}, legacy)) == len(rm.LEGACY_CONTINUOUS_FIELDS) + 2 * len(rm.LEGACY_CATEGORICAL_FIELDS))
check("truth_derived_in_spec lists what the legacy spec used", rm.truth_derived_in_spec(legacy) == ["amr_status", "true_plasmid_bp", "true_plasmid_count"], rm.truth_derived_in_spec(legacy))
with tempfile.TemporaryDirectory() as tmp:
    old = os.path.join(tmp, "old.json")
    json.dump({"model_ready": True, "reason": "", "spec": legacy}, open(old, "w", encoding="utf-8"))
    model, ready, reason = rm.load_model(old)
    check("load_model does not serve a model fitted with truth-derived features, and says why and what to do",
          model is None and ready is False and "truth-derived" in reason and "refit" in reason and "true_plasmid_bp" in reason, reason)
    notready = os.path.join(tmp, "notready.json")
    json.dump({"model_ready": False, "reason": "too few studies", "spec": None}, open(notready, "w", encoding="utf-8"))
    check("a not-ready model keeps its own reason", rm.load_model(notready) == (None, False, "too few studies"))

print()
print("ALL RECOMMENDER TRUTH-FREE TESTS PASSED")
