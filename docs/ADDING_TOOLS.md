# Adding your own tool

PlasBench benchmarks any plasmid reconstruction or classification tool you describe in one manifest file. You do
not edit PlasBench's code: the manifest says how to install the tool, how to run it on each sample (or where its
existing outputs are), and how to read its output. PlasBench then runs it with the same timeouts, retries, resource
accounting and result reuse as the built-in tools, scores it with the same metrics, ranks it in the same
leaderboards and shows it in the same report.

```bash
plasbench tools new my_tool              # 1. write a commented manifest (~/.plasbench/tools/my_tool/)
$EDITOR ~/.plasbench/tools/my_tool/plasbench-tool.ini
plasbench tools validate my_tool         # 2. every problem, with the fix
plasbench install-tools my_tool          # 3. install it into its own environment
USER_TOOLS=my_tool plasbench check      #    (optional) confirm it is installed
plasbench run --tool my_tool ...         # 4. benchmark it with the built-in tools
```

`--tool` can be repeated (`--tool a --tool b`) or given `all`; in `config/config.sh` the same is `USER_TOOLS=a,b`.

## How it fits together

```
plasbench-tool.ini ──► python/user_tools.py ──► registries (task, track, install, database)  ── scoring, ranking, report
        │                                                                                         (unchanged)
        ├─ [run]    ──► scripts/04_run_tools.sh  run_user_tool: inputs ─► command (or imported file)
        └─ [output] ──► python/user_tool_adapter.py: tool output ─► pred_<tool>.plasmid.fasta (+ .bins.tsv, .scores.tsv)
```

Everything after `pred_<tool>.*` is the unchanged built-in path, so a user tool is scored exactly like a built-in.

## Where manifests live

PlasBench looks in these folders, first match wins. Each holds one sub-folder per tool, named anything, containing
`plasbench-tool.ini` and any files the manifest refers to (scripts, an adapter):

1. every folder in `$PLASBENCH_TOOLS_PATH` (separated like `PATH`)
2. `~/.plasbench/tools/` (where `plasbench tools new` and `plasbench tools add` put them)
3. `tools.d/` in the PlasBench checkout

A tool may not reuse a built-in name (`mob_recon`, `platon`, ...). `PLASBENCH_USER_TOOLS=off` hides every user tool.
`tools.d/examples/` has one worked manifest per output format; examples are never run.

## The manifest

An INI file with five sections. Unknown sections or keys are reported, never ignored, so a typo cannot silently
change a benchmark. Comments start with `#` or `;`, also at the end of a line.

### `[tool]` – what it is

| key | meaning |
|---|---|
| `name` | **required.** The tool's id in every table: lower-case letters, digits and `_`. |
| `display_name` | The name readers see in the report (default: `name`). |
| `task` | **required.** `reconstruction` (groups contigs into plasmids: bin metrics, CPRR, ranked by length-weighted binning F1) or `classification` (labels contigs plasmid/chromosome: ranked by base-level F1). |
| `analysis_track` | **required.** `short_read`, `long_read` or `hybrid`. Tools are only ranked within their track. |
| `requires_independent_long_read_truth` | `auto` (default: yes for long_read/hybrid), `yes` or `no`. When yes, a sample whose truth was built from the same long reads is skipped unless the sample sheet says `truth_independent_of_long_reads=yes` (or `<NAME>_ALLOW_CIRCULAR_TRUTH=1`). |
| `method_class`, `description`, `citation`, `url` | Shown in the registry, the run manifest and the report. |
| `version_command` | Its first output line is recorded as the tool's version in `run_manifest.json` and the report. |

### `[install]` – how `plasbench install-tools NAME` installs it

| `method` | what happens |
|---|---|
| `conda` | `conda create -n <env_name> -c <channels> <packages>`; optional `pip_packages` are added inside it. |
| `pip` | a fresh environment with `python` (default 3.10) and `pip install <pip_packages>`. |
| `script` | runs `script` (a file beside the manifest) as `script <env_name>`; for git checkouts, compiled tools, licences. |
| `none` | nothing is installed; the command must already be on `PATH` (or the tool runs in import mode). |

`env_name` defaults to `plasbench-<name>`. `verify_command` (for example `mytool --help`) is run after installing and
by `plasbench check` when the tool is selected (`USER_TOOLS`); a failure is listed with the install command, and
`plasbench check --yes` installs it. Commands run inside the tool's
own environment when it exists, so its dependencies never touch PlasBench's.

### `[database]` – for the leakage check

If the tool searches a plasmid database, set `uses_reference_database = yes`, `database` (its name and version) and
`release_date` (YYYY-MM-DD). PlasBench then flags truth plasmids that were public before the database was built,
exactly as for the built-in tools. `path` is substituted for `{db}` in the command.

### `[run]` – how it runs

**`mode = command`**: PlasBench runs `command` once per sample, in an empty working folder, with these placeholders
replaced by the sample's files (each value is shell-quoted, so paths with spaces are safe):

| placeholder | value |
|---|---|
| `{contigs}` | the sample's assembly contigs (FASTA) – the ids your output must refer to |
| `{graph}` | the sample's assembly graph (GFA) |
| `{reads_1}`, `{reads_2}` | trimmed short reads (FASTQ.gz) |
| `{long_reads}` | the sample's long reads (FASTQ.gz) |
| `{db}` | `[database] path` |
| `{outdir}` | an empty folder for this tool and sample: write the output here |
| `{threads}` | `threads` from this section, else `USER_TOOL_THREADS` (default: `THREADS`) |
| `{sample}`, `{tool_dir}` | the sample id; the folder holding the manifest (for scripts shipped with it) |

`requires` lists the inputs the command needs (`contigs, graph`, ...). A sample without one is recorded as
**skipped** with the reason, never as a tool failure. `timeout_seconds` overrides `TOOL_TIMEOUT_SECONDS`. A command
may continue over several indented lines. A command that exits non-zero is **failed** (timeouts and out-of-memory
kills are classified as for every tool). Set `env = path` to run from `PATH` even
when an environment exists.

**`mode = import`**: you already ran the tool. `dir` is the folder holding one output per sample and `pattern` its
file name (default `{sample}.tsv`). The outputs must be made from the **same assemblies** PlasBench scores; an output
naming contigs the assembly does not have is skipped as "output unusable for this assembly". A missing file is
skipped with its path.

### `[output]` – mapping the tool's output onto PlasBench's

`path` is where the tool writes its output, relative to `{outdir}` (command mode). Then pick the `format`:

| `format` | the tool writes | keys |
|---|---|---|
| `contig_bins` | a table, one row per contig with its plasmid bin | `contig_column`, `bin_column` |
| `contig_labels` | a table, one row per contig with a label and/or probability | `contig_column`, `label_column` + `plasmid_values`, `score_column`, `threshold` |
| `plasmid_fasta` | one FASTA of predicted plasmid sequence | – (each record is one plasmid) |
| `fasta_dir` | a folder with one FASTA per predicted plasmid | `fasta_glob` (default `*.fa, *.fasta, *.fna`, gzipped too) |
| `adapter` | anything else | `adapter`: your script, run as `adapter <output> <contigs> <pred_<tool>.plasmid.fasta>`, which writes the native files of `adapters/BINS.md` and `adapters/SCORES.md` |

Tables: `delimiter` (`tab` default, `comma`, `semicolon`, `whitespace`, or a character), `header` (`yes` default; a
header may start with `#`), `comment` (default `#`: such lines are skipped). Columns are named, or numbered from 1.

Contig ids must match the assembly's. `contig_id_from = first_token` keeps the first word (`contig_7 len=4512` →
`contig_7`); `contig_id_strip_regex` removes a pattern (`_length_.*$` turns `NODE_1_length_5000_cov_12` into
`NODE_1`). A contig listed in two bins stays in the first; the others are recorded in
`pred_<tool>.<tool>.provenance.json`.

For `contig_labels`, a contig is called plasmid when its `label_column` value is in `plasmid_values`; without a label
column, when its score is at least `threshold` (default 0.5). A `score_column` (values in [0, 1]) also gives the tool
a precision-recall curve and PR-AUC. A classifier (`task = classification`) gets no bins; a reconstruction tool
whose output is per-contig labels gets one bin per plasmid contig.

## What PlasBench records

- `tool_status.tsv` / `tool_outcomes.tsv`: one row per sample, as for built-in tools (completed, reused, skipped
  with the reason, failed with the exit code, infrastructure failure).
- `results/<sample>/pred_<tool>.*` and the provenance JSON of the conversion.
- `run_manifest.json` → `user_tools`: manifest path and SHA-256, task, track, run mode, output format, install method,
  citation and version; the version also appears in the report.
- A finished result is reused only while its fingerprint is unchanged: the manifest folder's checksum, the rendered
  command (or the imported file's checksum) and the inputs. Editing the manifest re-runs the tool.

## Safety

In command mode PlasBench runs the command you wrote, as you. It only reads manifests from the search path above, so
a manifest arrives there only because you put it there (`plasbench tools add` validates it first). Read a manifest
someone sends you before adding it, as you would any script.

## Contributing a tool to PlasBench

A user tool that proves useful can become built-in: open a pull request adding its manifest under `tools.d/` (or a
dedicated adapter under `adapters/`), with a small test like `test/test_user_tool_stage.sh`.
