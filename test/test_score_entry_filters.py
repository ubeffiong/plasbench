#!/usr/bin/env python3
"""`plasbench-score` applies the pre-registered alignment filters the caller omits.

A bare call used to fall back to score_plasmids.py's unfiltered script defaults, so
it scored against a different rule from the pipeline and the Galaxy wrapper.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from plasbench.tools import with_preregistered_filters  # noqa: E402

FLAGS = ("--min-alignment-length", "--min-alignment-identity", "--min-alignment-mapq",
         "--min-alignment-query-coverage")


def value(argv, flag):
    return argv[argv.index(flag) + 1]


def main():
    saved = {k: os.environ.pop(k, None) for k in ("MIN_ALIGNMENT_LENGTH", "MIN_ALIGNMENT_IDENTITY",
                                                  "MIN_ALIGNMENT_MAPQ", "MIN_ALIGNMENT_QUERY_COVERAGE")}
    try:
        bare = with_preregistered_filters(["--truth", "t.tsv", "--paf", "a.paf"])
        assert [value(bare, f) for f in FLAGS] == ["200", "0.90", "20", "0.20"], bare
        # A filter the caller sets is kept, and not duplicated.
        given = with_preregistered_filters(["--min-alignment-identity", "0.95", "--truth", "t.tsv"])
        assert given.count("--min-alignment-identity") == 1 and value(given, "--min-alignment-identity") == "0.95"
        # --flag=value spelling is recognised too.
        eq = with_preregistered_filters(["--min-alignment-mapq=0"])
        assert "--min-alignment-mapq" not in eq
        # The exported pipeline values win over the built-in pre-registered ones.
        os.environ["MIN_ALIGNMENT_IDENTITY"] = "0.85"
        assert value(with_preregistered_filters([]), "--min-alignment-identity") == "0.85"
        # Help is passed through untouched.
        assert with_preregistered_filters(["--help"]) == ["--help"]
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    print("test_score_entry_filters: plasbench-score applies the pre-registered filters")


if __name__ == "__main__":
    main()
