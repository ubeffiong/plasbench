# Resource adaptation

Generated from `config/resource_signatures.tsv` by `python3 python/resource_adapt.py docs` (a test keeps it current). `real` = the wording was captured from a log or test in this repository;
`sample` = the wording comes from the tool's documentation or source and was not captured here.

| id | tool | cause | matches | exit codes | ladder | label |
|---|---|---|---|---|---|---|
| spades_hammer_need | `spades|unicycler|plasmidspades` | memory | `You need approx\.?\s*(?P<need>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>TB\|GB\|GiB\|MB\|MiB\|KB)?` | - | raise_memory > skip | real |
| spades_m_limit | `spades|unicycler|plasmidspades` | memory | `(memory limit\|[Mm]emory).{0,40}(exceed\|reached\|too low)\|not enough memory` | - | raise_memory > halve_threads > skip | sample |
| bad_alloc | `.*` | memory | `std::bad_alloc\|bad_alloc` | 134 | raise_memory > halve_threads > skip | real |
| cannot_allocate | `.*` | memory | `[Cc]annot allocate memory\|unable to allocate (os )?memory\|memory allocation (failed\|error)` | - | raise_memory > halve_threads > skip | real |
| python_memoryerror | `.*` | memory | `MemoryError` | - | raise_memory > halve_threads > skip | real |
| oom_kill | `.*` | memory | `-` | 137,-9 | raise_memory > halve_threads > skip | real |
| samtools_sort_memory | `samtools|minimap2` | memory | `(samtools sort\|bam_sort).{0,40}couldn't allocate memory\|\[bam_sort_core\].{0,40}memory` | - | raise_memory > halve_threads > skip | sample |
| java_heap | `.*` | memory | `OutOfMemoryError: Java heap space\|GC overhead limit exceeded` | - | raise_memory > skip | sample |
| open_files | `.*` | open_files | `Too many open files\|\[Errno 24\]\|EMFILE` | - | raise_ulimit > skip | real |
| tmp_no_space | `.*` | tmp_space | `No space left on device.{0,200}(/tmp\|tmp\|temp)\|(/tmp\|tmp\|temp).{0,200}No space left on device` | - | move_tmp > skip | sample |
| disk_no_space | `.*` | disk | `No space left on device\|[Dd]isk quota exceeded\|ENOSPC\|\[Errno 28\]` | - | move_tmp > skip | real |
| thread_limit | `.*` | thread_limit | `pthread_create\|can'?t start new thread\|Resource temporarily unavailable\|std::system_error` | - | halve_threads > skip | sample |
| timeout_wrapper | `.*` | timeout_slow | `-` | 124 | extend_timeout > skip | real |
| amrfinder_db | `amrfinder` | db_missing | `Could not find the AMRFinder database\|database.{0,30}(not found\|not installed)` | - | skip | real |
| gpu_missing | `.*` | gpu_missing | `no CUDA-capable device\|CUDA (driver\|error)\|could not load library libcuda` | - | skip | sample |
| permission | `.*` | permission | `[Pp]ermission denied\|\[Errno 13\]` | - | skip | real |
| network | `.*` | network | `[Cc]ould not resolve host\|[Cc]onnection (timed out\|refused\|reset)` | - | skip | sample |

## What each response does

- **raise_memory**: budget = ceil(need x 1.15 + 0.5 GB) when it fits in 85% of the memory free now (else the need rounded up when it fits in 92%); with no stated need 1.5 x the budget when it fits. Never lowers a budget.
- **halve_threads**: threads = max(1, threads / 2), only for tools flagged `scales_with_threads`.
- **move_tmp**: moves the tool's work folder (TMPDIR) to the roomiest other folder with enough free space (scratch on the local disk, the system temp, the data folder).
- **raise_ulimit**: `ulimit -n` for the tool up to the hard limit; never beyond it, never a system setting; says so when the hard limit is the problem.
- **extend_timeout**: doubles the time limit once (cap 7 days), only when the tool shows progress.
- **skip**: always possible: the isolate or tool is skipped with the exact need and what is free, and the run continues.

## Limits

- Each response is tried at most once per tool, isolate and cause; at most `RESOURCE_MAX_ATTEMPTS` (default 2) adjustments per tool and isolate.
- Only resources change: never k-mer sizes, thresholds or modes. The one mode-changing option, SPAdes `--only-assembler`, is opt-in (`ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1`) and recorded as a different assembly mode.
- The budget never exceeds what the machine has free now (cgroup and WSL aware, MB-precise).
- Learned needs are kept in `results/resource_profile.tsv`, keyed by a checksum of the isolate's reads; a changed read set invalidates them.

## Adding a signature

Add one row to `config/resource_signatures.tsv` (tab-separated): `tool` and `message_regex` are regular expressions (use named groups `need` and `unit` to read an amount), `exit_codes` a comma list or `-`,
`cause` one of the known causes, `ladder` the ordered responses (ending in `skip`), `label` `real` or `sample`. `python3 test/test_resource_adapt.py` validates the table.

## Turning it off

`AUTO_RESOURCES=0` (config/config.sh, or the environment) restores fixed behaviour: one attempt with the budget you set. `RESOURCE_MAX_ATTEMPTS` caps the adjustments.
