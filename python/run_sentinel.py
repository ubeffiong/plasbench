#!/usr/bin/env python3
"""The run's sentinel: one small background process that lives exactly as long as the run.

  1. KEEP_AWAKE (default on): asks the operating system not to sleep while the run is active (python/keep_awake.py) and says so in one plain line.
  2. Suspend detection: polls the clock every few seconds. A jump the poll did not cause is a sleep: it is written to RESULTS_DIR/.suspend_gaps and as a
     `system_suspend` run event, so every elapsed time, "slow step", "no new output" and time-limit calculation can leave it out (python/awake_clock.py).
  3. Watchdog: it ends, and releases the sleep request, when the run's process (--pid) disappears, so a crash can never leave the machine unable to sleep.

  python3 run_sentinel.py --pid RUN_PID --results-dir DIR [--interval 5] [--threshold 60]
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awake_clock  # noqa: E402
import keep_awake  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, required=True, help="the run's process id: the sentinel ends when it does")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--interval", type=float, default=float(os.environ.get("SENTINEL_INTERVAL_SECONDS", "5")))
    parser.add_argument("--threshold", type=float, default=float(os.environ.get("SUSPEND_MIN_SECONDS", awake_clock.MIN_SUSPEND_SECONDS)))
    args = parser.parse_args(argv)
    results = args.results_dir
    events, gaps = os.path.join(results, "run_events.jsonl"), os.path.join(results, ".suspend_gaps")
    stopping = []
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stopping.append(1))
    holder = keep_awake.Holder(args.pid)
    method, note = holder.start()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {note}", flush=True)
    awake_clock.write_event(events, "keep_awake", method=method, note=note)
    last_wall, last_mono = time.time(), time.monotonic()
    try:
        while not stopping and keep_awake.pid_alive(args.pid):
            time.sleep(args.interval)
            wall, mono = time.time(), time.monotonic()
            gap = awake_clock.detect_gap(wall - last_wall, mono - last_mono, args.interval, args.threshold)
            if gap:
                awake_clock.record_gap(gaps, wall - gap, wall, events, "sentinel")
            last_wall, last_mono = wall, mono
    finally:
        holder.stop()
        awake_clock.write_event(events, "keep_awake_released", method=method)
    return 0


if __name__ == "__main__":
    sys.exit(main())
