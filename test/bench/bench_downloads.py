"""Time a paired ENA download against a local, per-connection-throttled HTTP server.

usage: python test/bench/bench_downloads.py <python_dir> [size_mb] [mb_per_s_per_connection]
The server honours HTTP Range; each connection is capped, as public mirrors effectively
are, so parallel connections show the gain a real link would (when it is not saturated).
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import test_fetch_ena_parallel as mock  # noqa: E402

python_dir = Path(sys.argv[1]).resolve()
size_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 16
rate = float(sys.argv[3]) if len(sys.argv) > 3 else 4
os.environ.setdefault("ENA_USE_ARIA2", "0")
mock.Handler.rate = int(rate * (1 << 20))
server = mock.serve(size=size_mb << 20)
with tempfile.TemporaryDirectory() as tmp:
    t0 = time.perf_counter()
    mock.fetch(python_dir, server, tmp)
    dt = time.perf_counter() - t0
    mock.verify(tmp)
server.shutdown()
print(f"{python_dir.parent.name}/{python_dir.name}: 2 x {size_mb} MiB at {rate:g} MiB/s per connection "
      f"-> {dt:.1f} s ({2 * size_mb / dt:.1f} MiB/s), files verified")
