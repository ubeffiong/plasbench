# Adding your own tool

PlasBench benchmarks any plasmid reconstruction or classification tool you describe in one manifest file. You do
not edit PlasBench's code: the manifest says how to install the tool, how to run it on each sample (or where its
existing outputs are), and how to read its output. PlasBench then runs it with the same timeouts, retries, resource
accounting and result reuse as the built-in tools, scores it with the same metrics, ranks it in the same
leaderboards and shows it in the same report.

```bash
plasbench tools new my_tool              # 1. write a commented manifest (~/.plasbench/tools/my_tool/)
#   options: --task classification,binning_reconstruction   --source conda|pip|url|local|script|installed
#            --url https://... --sha256 ...   --local-path ~/tools/my_tool   --output-format contig_bins,contig_labels|auto
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
`tools.d/examples/` has one worked manifest per output format plus a multi-task, a URL, a local-folder and an auto-detect example; examples are never run.

## The manifest

An INI file with five sections. Unknown sections or keys are reported, never ignored, so a typo cannot silently
change a benchmark. Comments start with `#` or `;`, also at the end of a line.

### `[tool]` – what it is

| key | meaning |
|---|---|
| `name` | **required.** The tool's id in every table: lower-case letters, digits and `_`. |
| `display_name` | The name readers see in the report (default: `name`). |
| `task` | **required.** What the tool does: `binning_reconstruction` (groups the contigs of an existing assembly into plasmids: bin metrics, ranked by length-weighted binning F1), `sequence_reassembly` (produces plasmid sequences of its own: bin metrics with each record as its own bin, ranked by isolate-level CPRR) or `classification` (labels contigs plasmid/chromosome: ranked by base-level F1). **A comma list** (`task = classification, binning_reconstruction`) declares a tool that does several: see [A tool with several tasks](#a-tool-with-several-tasks). The old value `reconstruction` still means `binning_reconstruction`. |
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
| `url` | the tool is downloaded from an **https** URL into `src/` beside the manifest: see [Where the tool comes from](#where-the-tool-comes-from). |
| `local` | the tool is already on this computer (a file or folder): copied (default) or linked: see the same section. |

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
| `{src}` | the downloaded or located tool (`[install] method = url` or `local`): a folder, or the file itself for a single-file source |

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

`path` is where the tool writes its output, relative to `{outdir}` (command mode). Then pick the `format` (one value, a
comma list of several, or `auto`: see [Several output types and `format = auto`](#several-output-types-and-format--auto)):

| `format` | the tool writes | keys |
|---|---|---|
| `contig_bins` | a table, one row per contig with its plasmid bin | `contig_column`, `bin_column` |
| `contig_labels` | a table, one row per contig with a label and/or probability | `contig_column`, `label_column` + `plasmid_values`, `score_column`, `threshold` |
| `plasmid_fasta` | one FASTA of predicted plasmid sequence | – (each record is one plasmid) |
| `fasta_dir` | a folder with one FASTA per predicted plasmid | `fasta_glob` (default `*.fa, *.fasta, *.fna`, gzipped too) |
| `adapter` | anything else | `adapter`: your script, run as `adapter <output> <contigs> <pred_<tool>.plasmid.fasta>`, which writes the native files of `adapters/BINS.md` and `adapters/SCORES.md`; `adapter_tasks` lists the tasks it writes them for (default: the primary task); it is called once per task with `PLASBENCH_TASK` set |
| `auto` | any of the above | `candidates`: files or folders (globs relative to `{outdir}`) that PlasBench recognises by content |

Tables: `delimiter` (`tab` default, `comma`, `semicolon`, `whitespace`, or a character), `header` (`yes` default; a
header may start with `#`), `comment` (default `#`: such lines are skipped). Columns are named, or numbered from 1.

Contig ids must match the assembly's. `contig_id_from = first_token` keeps the first word (`contig_7 len=4512` →
`contig_7`); `contig_id_strip_regex` removes a pattern (`_length_.*$` turns `NODE_1_length_5000_cov_12` into
`NODE_1`). A contig listed in two bins stays in the first; the others are recorded in
`pred_<tool>.<tool>.provenance.json`.

For `contig_labels`, a contig is called plasmid when its `label_column` value is in `plasmid_values`; without a label
column, when its score is at least `threshold` (default 0.5). A `score_column` (values in [0, 1]) also gives the tool
a precision-recall curve and PR-AUC. A classifier (`task = classification`) gets no bins; a binning or reassembly tool
whose output is per-contig labels gets one bin per plasmid contig.

### A tool with several tasks

```ini
[tool]
task = classification, binning_reconstruction     # the first listed is the primary task
```

The command runs **once per sample**. Each task is a row of its own in the registries, the status tables, the
scoring and the leaderboards, converted from that single run's output:

| row | id (and the file names `pred_<id>.*`) | label in the report |
|---|---|---|
| the primary task | `<name>` | `<display_name> (<task>)` |
| every other task | `<name>__<task>`, for example `my_tool__binning_reconstruction` | `<display_name> (<task>)` |

(`<task>` in a label is `binning`, `reassembly` or `classification`; a tool with one task keeps its plain
`display_name`.) Ids are lower-case letters, digits and `_` only, so they are safe as file names, and `__` is reserved:
a tool name may not contain it. The tool appears in **each selected task's leaderboard and ranking, within its
track, and is never ranked across tasks**. The additional rows are `completed` (converted) or `reused`; the command is
never run a second time, and each row has its own fingerprint (a changed manifest, command, input, or source re-runs the command and
converts every row afresh). `--tool my_tool__binning_reconstruction` selects the tool.

**Derivation table.** What each task needs from what the tool writes (`plasbench tools validate` prints this per task):

| the tool writes | classification | binning_reconstruction | sequence_reassembly |
|---|---|---|---|
| `contig_bins` | derived: a contig in any bin is plasmid (no probability, so no PR curve) | native | **not possible**: a table has no sequence of its own |
| `contig_labels` | native (with `score_column`, also the PR curve) | derived: one bin per plasmid contig, flagged as **not a real grouping** | **not possible** |
| `plasmid_fasta` / `fasta_dir` | **not possible**: no contig ids to label | **not possible**: it does not say which contigs belong together | native |
| `adapter` | native if listed in `adapter_tasks` | native if listed in `adapter_tasks` | native if listed in `adapter_tasks` |

A task that is *not possible* from the declared outputs is a validation **error for that task**, naming the reason and
the fix (add the output that can produce it, or drop the task). Nothing is guessed. A manifest with one task and one
output format (the only shape that existed before) keeps validating as before: the combinations above that used to be
accepted (for example `task = binning_reconstruction` with `plasmid_fasta`, each record its own bin) give a note, not an error.

### Several output types and `format = auto`

```ini
[output]
format = contig_bins, contig_labels          # several types: one [output.<format>] section each
[output.contig_bins]
path = bins.tsv
contig_column = contig
bin_column = bin
[output.contig_labels]
path = labels.csv
delimiter = comma
label_column = call
score_column = p
```

Each `[output.<format>]` section takes that format's keys (`path`, `contig_column`, ...); a key missing there falls back
to `[output]`. For each task PlasBench uses the **best available** output, by this priority: binning `contig_bins`, then
`contig_labels`; classification `contig_labels`, then `contig_bins`; reassembly `plasmid_fasta`, `fasta_dir` (an adapter
that lists the task comes first). If the preferred file was not written the next one serves the task, and the
provenance says which.

```ini
[output]
format = auto
candidates = contig_report.txt, plasmid_*.fasta      # globs relative to {outdir}
```

With `format = auto` PlasBench looks at each candidate's **content**, deterministically:

| what it finds | recognised as |
|---|---|
| a FASTA file (also `.gz`) | `plasmid_fasta` |
| a folder holding FASTA files (non-FASTA files in it are ignored and reported), or a pattern that matches several FASTA files | `fasta_dir` |
| a delimited table (comma, tab or semicolon; a header may start with `#`; comment lines before it are skipped) with a contig-id column and a bin/cluster column | `contig_bins` (`-`, `NA`, `none`, `unbinned` mean "in no bin") |
| ... with a label (`plasmid`/`chromosome`) or a probability column | `contig_labels` |

A table with both a bin and a label column (MOB-recon's `contig_report.txt`) serves both roles. Column names are
matched from a fixed vocabulary (`contig_id`, `contig`, `id`, `sequence_id`... for the contig; `bin`, `cluster`,
`primary_cluster_id`... for the bin; `label`, `prediction`, `molecule_type`... for the label; `probability`,
`score`... for the score). An `[output.<format>]` section next to `format = auto` supplies hints that win over detection.
**An ambiguous output is an error, never a guess**: two candidates that could equally be the bins, or nothing
recognisable, fail that task's row for that sample with a message listing every candidate and what was seen
(the other rows still convert). The choice made per sample is recorded in `pred_<id>.<id>.provenance.json`
(`chosen_format`, `chosen_path`, `candidates_seen`) and in the row's `tool_status.tsv` reason (for example
`binning_reconstruction <- contig_bins (contig_report.txt)`).

### Where the tool comes from

`[install] method = url` or `local` (the other methods are unchanged). Nothing is downloaded, copied or executed while
a manifest is validated; installing is explicit (`plasbench install-tools NAME`, or **Save & install** in the window).
`{src}` in `[run] command` (and in `build_command` and `verify_command`) is the downloaded or located tool.

```ini
[install]
method = url
url = https://github.com/example/tool/archive/refs/tags/v1.4.2.tar.gz
sha256 = 3f1c...                     # optional but strongly advised
build_command = make -j 4            # optional; runs inside {src}
verify_command = {src}/tool --help
```

| key | meaning |
|---|---|
| `url` | **https only.** `http`, `ftp`, `file`, `ssh`, `ext::` transports, a missing host and credentials in the URL are rejected. A redirect to anything but https is refused. |
| `sha256` | The file's checksum. Verified when given: a mismatch deletes the download and refuses the install, naming both checksums. When absent the install proceeds with a loud warning and records the observed checksum so you can pin it. Not used for git (pin `ref`). |
| `kind` | `archive` (`.zip`, `.tar.gz`, `.tgz`, `.tar.xz`, `.tar.bz2`), `git` (a repository URL) or `file` (one file). Detected from the URL when left out. |
| `ref`, `submodules` | git only: a tag, branch or commit; submodules are not fetched unless `submodules = yes`. The resolved commit is recorded. |
| `build_command` | Runs inside the source folder after it is installed, in the tool's environment when it has one. |
| `max_download_mb`, `download_timeout_seconds` | The size cap (default 2048 MB; also `PLASBENCH_TOOL_MAX_DOWNLOAD_MB`) and the connection timeout (default 600 s). An interrupted download resumes where it stopped. |
| `packages`, `pip_packages` | Optional conda/pip packages for an environment the tool builds or runs in. |

The source is placed in `src/` beside the manifest (managed by PlasBench; an archive with a single top-level folder has it
stripped). Every install appends a line to `download_provenance.jsonl` there: URL, final URL after redirects, size,
sha256 (or git commit), time. The run manifest (`run_manifest.json` → `user_tools`) carries the same.

```ini
[install]
method = local
path = ~/tools/mytool                # a file or a folder; ~, $VARS and, under WSL, Windows paths (C:\Tools\mytool)
mode = copy                          # copy (default) | link
```

`mode = copy` copies it into `src/` and records its sha256 (a tree checksum for a folder): later edits to the original do
not change the benchmark until you install again. `mode = link` uses it in place and records only the path, with a
warning that the tool can change under the benchmark. A copy larger than the size cap is refused (use `link`).
The fingerprint of a finished result includes the source: another URL, another pinned sha256, a newly recorded
download, a reinstalled copy, or (for a link) changed files re-run the tool.

**Safety of URLs.** A download is code you will run. PlasBench therefore: accepts https only; never runs anything while
validating; caps the size; verifies a pinned sha256; extracts archives itself and refuses absolute paths, `..`, drive
letters, device files, FIFOs, hard links and symlinks that leave the folder (and archives that expand past a size cap);
clones git with every transport except https disabled and without submodules unless asked; and records what it got.
Pin the `sha256` (or a git commit) of anything you did not build, and read the project before you install it.

### Reading a manifest from a program

`python/user_tools.py` exposes pure functions (no file or network access): `parse_text(text)` (the sections),
`validate_text(text)` → `{"ok", "problems", "warnings", "tasks": [{"task", "id", "status": "native|derived|not_possible", "how"}],
"source": {...}, "outputs": [...]}`, and the constants `TASKS`, `FORMATS`, `INSTALL_METHODS` with a plain sentence for each in `TASK_HELP`,
`FORMAT_HELP`, `SOURCE_HELP`. The window's form uses them.

## What PlasBench records

- `tool_status.tsv` / `tool_outcomes.tsv`: one row per sample, as for built-in tools (completed, reused, skipped
  with the reason, failed with the exit code, infrastructure failure).
- `results/<sample>/pred_<tool>.*` and the provenance JSON of the conversion.
- `run_manifest.json` → `user_tools`: manifest path and SHA-256, task(s) and row ids, track, run mode, declared output
  types and the type each row used per sample, the source (method, URL or path, final URL, size, sha256 or commit, whether
  the checksum was verified), citation and version; the version also appears in the report.
- A finished result is reused only while its fingerprint is unchanged: the manifest folder's checksum, the rendered
  command (or the imported file's checksum) and the inputs. Editing the manifest re-runs the tool.

## Safety

In command mode PlasBench runs the command you wrote, as you. It only reads manifests from the search path above, so
a manifest arrives there only because you put it there (`plasbench tools add` validates it first). Read a manifest
someone sends you before adding it, as you would any script. A `url` or `local` source adds code you did not write: see
"Safety of URLs" above.

## Contributing a tool to PlasBench

A user tool that proves useful can become built-in: open a pull request adding its manifest under `tools.d/` (or a
dedicated adapter under `adapters/`), with a small test like `test/test_user_tool_stage.sh`.
