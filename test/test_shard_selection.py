#!/usr/bin/env python3
"""Test sharding (test/shard_select.py, PB_SHARD/PB_SHARDS in test/run_tests.sh): the shards partition the registered tests
exactly, the weight table covers every test, unsharded behaviour is unchanged, and every test goes through pb_run."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shard_select  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("  PASS: " if condition else "  FAIL: ") + label + ("" if condition else f"  {detail}"))
    if not condition:
        failures.append(label)


def registered():
    env = dict(os.environ, PB_LIST="1")
    env.pop("PB_SHARDS", None)
    done = subprocess.run([os.environ.get("PLASBENCH_BASH") or "bash", str(HERE / "run_tests.sh")], capture_output=True, text=True, env=env, cwd=HERE.parent)
    return done.returncode, done.stdout.split()


code, names = registered()
check("PB_LIST=1 lists the registered tests without running them", code == 0 and len(names) > 400, f"exit {code}, {len(names)} names")
check("every registered test file exists", all((HERE / n).is_file() for n in names), str([n for n in names if not (HERE / n).is_file()]))
check("run_tests.sh itself is not registered and no name is blank", "run_tests.sh" not in names and all(names))

script = (HERE / "run_tests.sh").read_text(encoding="utf-8")
direct = [l for l in script.splitlines() if re.search(r'(python3|bash) "\$HERE/', l) and "pb_run()" not in l
          and 'shard_select.py' not in l and 'run_demo.sh' not in l and 'run_tests.sh' not in l and '"$interpreter"' not in l]
check("every test is run through pb_run (a direct invocation would escape the shards)", not direct, str(direct[:3]))

weights = shard_select.read_weights(HERE / "shard_weights.tsv")
check("shard_weights.tsv has a weight for every registered test", not (set(names) - set(weights)),
      "add a 'name<TAB>seconds' line for: " + ", ".join(sorted(set(names) - set(weights))))
check("shard_weights.tsv names no test that is not registered", not (set(weights) - set(names)), ", ".join(sorted(set(weights) - set(names))))
check("every weight is positive", all(w > 0 for w in weights.values()))

for shards in (1, 2, 3, 4, 5, 7):
    picked = []
    for shard in range(1, shards + 1):
        picked += shard_select.select(names, weights, shard, shards)
    check(f"{shards} shard(s): the union is every distinct test exactly once", sorted(picked) == sorted(set(names)), f"{len(picked)} vs {len(set(names))}")
    again = []
    for shard in range(1, shards + 1):
        again += shard_select.select(names, weights, shard, shards)
    check(f"{shards} shard(s): the assignment is deterministic", picked == again)

dupes = [n for n in set(names) if names.count(n) > 1]
if dupes:
    owner = {n: [s for s in range(1, 5) if n in shard_select.select(names, weights, s, 4)] for n in dupes}
    check("a test registered twice stays in one shard (and so runs as often as unsharded)", all(len(v) == 1 for v in owner.values()), str(owner))

# Balance: with real weights no shard may carry much more than its share.
load = [sum(weights[n] * names.count(n) for n in shard_select.select(names, weights, s, 4)) for s in range(1, 5)]
check("4 shards are balanced by weight (heaviest within 5 percent of the mean)", max(load) <= 1.05 * (sum(load) / 4), str(load))

# A new test without a weight is still assigned (median weight), never dropped.
extended = names + ["test_brand_new_unweighted.py"]
mine = [s for s in range(1, 5) if "test_brand_new_unweighted.py" in shard_select.select(extended, weights, s, 4)]
check("an unweighted new test is assigned to exactly one shard", len(mine) == 1, str(mine))
check("an empty weight table still assigns everything", sorted(shard_select.select(["a.py", "b.py", "c.py"], {}, 1, 1)) == ["a.py", "b.py", "c.py"])

try:
    shard_select.select(names, weights, 5, 4)
    check("an out-of-range shard is rejected", False)
except ValueError:
    check("an out-of-range shard is rejected", True)

with tempfile.TemporaryDirectory() as tmp:
    bad = Path(tmp) / "w.tsv"
    bad.write_text("test_a.py 3\n", encoding="utf-8")
    try:
        shard_select.read_weights(bad)
        check("a malformed weight line is rejected", False)
    except ValueError:
        check("a malformed weight line is rejected", True)

# The command line, end to end: the selector reads the names on stdin and prints its shard.
done = subprocess.run([sys.executable, str(HERE / "shard_select.py"), "--shard", "2", "--shards", "4"], input="\n".join(names), capture_output=True, text=True)
check("shard_select.py prints shard 2 of 4 on the command line", done.returncode == 0 and done.stdout.split() == shard_select.select(names, weights, 2, 4))

if failures:
    print(f"{len(failures)} check(s) failed")
    sys.exit(1)
print("ALL SHARD SELECTION TESTS PASSED")
