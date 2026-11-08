#!/usr/bin/env python3
"""Leave-one-study-out grouping: no silent drops, and a study is never split."""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from study_groups import group_samples_by_study  # noqa: E402


def rows(*samples):
    return [{"sample": s} for s in samples]


def grouped(scores, metadata):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = group_samples_by_study(scores, metadata)
    return {k: v for k, v in result.items()}, err.getvalue()


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("declared source_study is used as before")
    groups, err = grouped(rows("a", "b"), {"a": {"source_study": "S1"}, "b": {"source_study": "S2"}})
    check("two studies, one sample each", groups == {"S1": {"a"}, "S2": {"b"}})
    check("nothing reported when nothing is dropped", err == "")

    print("a blank source_study falls back to its bioproject")
    groups, err = grouped(rows("a", "b"), {"a": {"source_study": "", "bioproject": "PRJ1"},
                                           "b": {"source_study": "", "bioproject": "PRJ2"}})
    check("each bioproject becomes a group", groups == {"PRJ1": {"a"}, "PRJ2": {"b"}})

    print("a study is never split across folds")
    meta = {"a": {"source_study": "Smith_2020", "bioproject": "PRJ1"},
            "b": {"source_study": "", "bioproject": "PRJ1"},
            "c": {"source_study": "", "bioproject": "PRJ9"}}
    groups, _ = grouped(rows("a", "b", "c"), meta)
    check("b joins a's study through the shared bioproject", groups["Smith_2020"] == {"a", "b"})
    check("c, with no sibling, keeps its own bioproject", groups["PRJ9"] == {"c"})
    check("no stray PRJ1 group", "PRJ1" not in groups)

    print("samples that cannot be assigned are reported, not silently dropped")
    groups, err = grouped(rows("a", "b", "c"), {"a": {"source_study": "S1"}, "b": {}, "c": {"bioproject": ""}})
    check("assigned sample kept", groups == {"S1": {"a"}})
    check("stderr names the count and the samples", "2 of 3" in err and "b" in err and "c" in err)

    print("repeated rows for a sample do not double count")
    groups, err = grouped(rows("a", "a", "a"), {"a": {}})
    check("counted once in the dropped total", "1 of 1" in err)

    print()
    if not ok:
        print("STUDY GROUP TESTS FAILED")
        sys.exit(1)
    print("ALL STUDY GROUP TESTS PASSED")


if __name__ == "__main__":
    main()
