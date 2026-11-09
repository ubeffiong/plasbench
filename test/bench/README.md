# Performance benchmarks

Timing harnesses behind [docs/PERFORMANCE_AUDIT.md](../../docs/PERFORMANCE_AUDIT.md). They are **not** part of
`test/run_tests.sh`: timings depend on the machine, so they are run by hand before and after a change that
touches a hot path, on the same machine and inputs. Correctness of the optimised code is guarded separately
by `test/test_matching.py` and `test/test_resampling_equivalence.py`, which do run in the suite.

| Script | Measures | Usage |
|---|---|---|
| `bench_matching.py` | Rectangular matcher vs the earlier square Hungarian | `python test/bench/bench_matching.py` |
| `bench_aggregate.py` | `aggregate_results.py` wall time on synthetic score tables | `python test/bench/bench_aggregate.py python <samples> <tools> <workers>` (`workers` 0 = all CPUs) |
| `bench_score.py` | `score_plasmids.py` and `score_bins.py` on synthetic PAF | `python test/bench/bench_score.py python` |
| `bench_dsa.py` | Data-structure hot spots (bin agreement, bins dedup, calibration, k-mer sampling, sparse matching, top-k, resampling) plus peak memory of a streaming reference read; prints a hash of each output so two versions can be checked for identical results | `python test/bench/bench_dsa.py <python_dir> [case ...]` |
| `bench_downloads.py` | A paired ENA download from a local server that honours HTTP Range and caps each connection's speed | `python test/bench/bench_downloads.py <python_dir> [size_mb] [mb_per_s]` |
| `bench_kmers.py` | `repeat_content` k-mer counting time and peak memory | `python test/bench/bench_kmers.py python <genome_mb>` |
| `parse_trace.py` | Wall time per Python script from a timestamped trace | `PS4='+ $EPOCHREALTIME ' bash -x test/run_demo.sh 2> trace.txt; python test/bench/parse_trace.py trace.txt` |

Run from the repository root. Each script writes only to a temporary directory.
