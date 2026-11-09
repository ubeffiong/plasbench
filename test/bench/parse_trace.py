"""Summarise a `PS4='+ $EPOCHREALTIME ' bash -x` trace: wall time per top-level python3 script.

A top-level command's duration is the gap until the next top-level trace line, so
nested commands are attributed to the line that started them.
usage: python parse_trace.py <trace>
"""
import re
import sys
from collections import defaultdict

line_re = re.compile(r"^(\++) (\d+[.,]\d+) (.*)$")
events = []
for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = line_re.match(raw.rstrip("\n"))
    if m and len(m.group(1)) == 1:
        events.append((float(m.group(2).replace(",", ".")), m.group(3)))
total = events[-1][0] - events[0][0] if len(events) > 1 else 0.0
by_script, calls = defaultdict(float), defaultdict(int)
for (t, cmd), (t_next, _) in zip(events, events[1:]):
    m = re.search(r"^python3 .*?([A-Za-z0-9_]+\.py)", cmd)
    key = m.group(1) if m else "(shell / non-python)"
    by_script[key] += t_next - t
    calls[key] += 1
print(f"top-level commands={len(events)} traced_wall_s={total:.1f}")
print("seconds\tshare\tcalls\tscript")
for key, sec in sorted(by_script.items(), key=lambda kv: -kv[1])[:18]:
    print(f"{sec:7.1f}\t{sec / total:5.1%}\t{calls[key]}\t{key}")
print(f"python3 launches: {sum(v for k, v in calls.items() if k.endswith('.py'))}")
