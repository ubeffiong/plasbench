#!/usr/bin/env python3
"""`plasbench net-bench` (python/net_bench.py) against the fake ENA: it measures MB/s with 1, 4, 8 and 16 connections from small Range reads, prints one line per setting, recommends a
total, warns that single measurements are noisy, never reads more than the time box, and is declared in the network catalogue (so the command-line pre-flight and the window gate it).
The server limits each connection's speed the way a per-connection throttle does, so more connections must show a higher rate.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import net_bench as nb  # noqa: E402
from ena_range_server import Content, FakeENA  # noqa: E402

ok = True
MIB = 1 << 20


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def main():
    s = FakeENA(rate=1 * MIB)          # 1 MiB/s per connection
    s.add_file("/f/big_1.fastq.gz", Content(400 * MIB, 3))
    s.start()
    url = s.url("/f/big_1.fastq.gz")
    env = dict(os.environ, PLASBENCH_ASSUME_ONLINE="1")
    r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "net_bench.py"), "--url", url, "--mib", "8", "--seconds", "4", "--settings", "1,4,8,16"], env=env, capture_output=True, text=True)
    out = r.stdout
    check("it runs and prints one MB/s line per setting", r.returncode == 0 and all(f"{n:>2} connection" in out for n in (1, 4, 8, 16)) and out.count("MB/s") >= 4, (r.returncode, out, r.stderr[-300:]))
    rates = {}
    for line in out.splitlines():
        parts = line.split()
        if "MB/s" in parts and parts[1].startswith("connection"):
            rates[int(parts[0])] = float(parts[parts.index("MB/s") - 1])
    check("with a per-connection throttle, more connections give more throughput (1 < 4 < 8)", rates.get(1, 0) < rates.get(4, 0) < rates.get(8, 0), rates)
    check("it recommends a total ENA_MAX_CONNECTIONS (and never above 16)", "Recommended: ENA_MAX_CONNECTIONS=" in out and int(out.split("ENA_MAX_CONNECTIONS=")[1].split()[0]) <= 16, out)
    check("it warns about noise and says to run it twice", "noisy" in out and "twice" in out, out)
    check("nothing larger than the request was read: at most the time box and the byte budget per setting", s.stats()["ranged_bytes"] < 4 * 4 * 16 * MIB)
    r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "net_bench.py"), "--url", url, "--mib", "4", "--seconds", "2", "--settings", "1,4", "--json"], env=env, capture_output=True, text=True)
    data = json.loads(r.stdout)
    check("--json gives the rows and the recommendation", [x["connections"] for x in data["results"]] == [1, 4] and data["recommended_connections"] in (1, 4) and "noisy" in data["noise_warning"], data)
    check("the settings are capped at 16 connections", nb.recommend([{"connections": 16, "mb_per_s": 5.0}]) == 16 and max(sorted({max(1, min(nb.HARD_MAX, 64))})) == 16)
    check("the recommendation is the smallest setting within 90% of the best", nb.recommend([{"connections": 1, "mb_per_s": 0.8}, {"connections": 4, "mb_per_s": 3.0}, {"connections": 8, "mb_per_s": 3.1},
                                                                                    {"connections": 16, "mb_per_s": 4.25}]) == 16
          and nb.recommend([{"connections": 1, "mb_per_s": 0.8}, {"connections": 4, "mb_per_s": 3.0}, {"connections": 8, "mb_per_s": 3.1}, {"connections": 16, "mb_per_s": 3.2}]) == 4)
    s.honour_range = False
    r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "net_bench.py"), "--url", url, "--settings", "1"], env=env, capture_output=True, text=True)
    check("a server that does not honour Range is reported plainly, exit 3", r.returncode == 3 and "cannot read" in r.stderr, (r.returncode, r.stderr))
    s.stop()
    # declared for the network gate
    sys.path.insert(0, str(ROOT))
    from plasbench import cli, netcheck  # noqa: E402
    table = netcheck.command_table(ROOT / "config" / netcheck.CATALOGUE_NAME)
    check("`plasbench net-bench` is declared in config/network_services.tsv (service ena), so the pre-flight and the window gate it", ("net-bench", "") in table and "ena" in table[("net-bench", "")]["services"])
    parser = cli.build_parser()
    args = parser.parse_args(["net-bench", "--settings", "1,4"])
    check("the command exists with --run, --url, --mib, --seconds, --settings, --json", args.command == "net-bench" and args.settings == "1,4" and args.run == "SRR36114699" and args.mib == 32.0)
    off = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "net_bench.py")], env=dict(os.environ, PLASBENCH_OFFLINE="1"), capture_output=True, text=True)
    check("offline (PLASBENCH_OFFLINE=1) it says it needs the internet and exits, without trying", off.returncode == 3 and ("internet" in off.stderr.lower() or "offline" in off.stderr.lower()), (off.returncode, off.stderr))
    print("ALL NET-BENCH TESTS PASSED" if ok else "SOME NET-BENCH TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
