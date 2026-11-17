# Replicating the PlasEval paper, and the comparison gate

PlasBench reimplements PlasEval's best-match scores and its repeat-aware bin dissimilarity from the paper
(Mane et al. 2024, *BMC Bioinformatics* 25:365, [doi 10.1186/s12859-024-05941-0](https://doi.org/10.1186/s12859-024-05941-0)).
No PlasEval code is used: the PlasEval repository has no licence file, so PlasBench neither copies nor ships it. That makes one
question unavoidable: **does the reimplementation give the original program's numbers on real data?** This page is how to answer it.

## What ships

| Piece | Where | What it is |
|---|---|---|
| The cohort | `cohorts/plaseval-ecoli53.tsv` | The paper's 53 *E. coli* isolates (Saskatchewan broiler farms), with BioSample, short-read and long-read SRA runs and GenBank assembly from the paper's `Ecoli_samples.csv`. Reference tier 3: the truth is a Unicycler hybrid built on the same Illumina reads, so this is a replication panel, not a headline panel. Schema-validated only; the online NCBI check has not been run (the sheet header gives the command). |
| The paper's bins | `cohorts/plaseval_ecoli53/bins/` | The ground truth and the bins of MOB-recon, HyAsP, gplas2 and PlasBin-flow for each isolate, unchanged from the paper's Zenodo record (CC BY 4.0, [10.5281/zenodo.10785150](https://doi.org/10.5281/zenodo.10785150)). |
| The replication | `plasbench analysis plaseval-replication` | Scores those published bins with PlasBench (no tool is re-run), draws the error profile, and, when the original program is found, runs it on the same pairs. |
| The gate | `python/plaseval_gate.py`, stage 6 | The same comparison inside any run: it runs the original on the bins stage 5 exported and writes `benchmark.plaseval_gate.tsv` and `.json`, shown in the report's Bin agreement section. |

## What has been measured so far

**On constructed cases (verified, Linux):** the original program (`github.com/acme92/PlasEval`, commit 8238356) and PlasBench agree on best-match
precision, recall and F1 and on the normalised dissimilarity in all 59 cases of `test/test_plaseval_crosscheck.py`, 44 of them with repeated
contigs (hand-built and seeded random bin sets, and PlasEval's own examples).

**On the paper's real bins, PlasBench alone (alpha 0.5, all 212 isolate-tool pairs):**

| Tool | Mean dissimilarity (lower is better) | Best-match F1 (bp) | Largest part of the error |
|---|---:|---:|---|
| MOB-recon | 0.253 | 0.873 | missing contigs (71%) |
| gplas2 | 0.316 | 0.807 | missing contigs (80%) |
| PlasBin-flow | 0.370 | 0.728 | missing contigs (66%) |
| HyAsP | 0.479 | 0.565 | extra contigs (69%) |

These are PlasBench's numbers on the paper's published bins. They have **not been compared with the figures printed in the paper** (the paper's text was read for definitions, not for these numbers).

## Comparison with the original program

**Result against the original program (reference run, 16 Nov 2026, PlasEval commit 8238356, alpha 0.5):** on the paper's 53 isolates and four tools (212 isolate-tool pairs) the original finished 211 pairs and PlasBench's dissimilarity **agreed within 0.001 on 210 of them** (gplas2, HyAsP and MOB-recon on all 53 isolates each, differences 0.000000; PlasBin-flow on 51 of 52). There were **no disagreements**. One pair, EC_9226_3S1_D with PlasBin-flow (26 repeat families), differs by 0.003 (PlasBench 0.5415, original 0.5385): PlasBench's repeat search hit its call cap there, so its value is a stated upper bound, not an error. One pair, EC_9226_C5_H with PlasBin-flow, did not finish in the original within 900 s and is not compared. The original's answers are kept in `cohorts/plaseval_ecoli53/original_reference.tsv`.

**Confirm it yourself.** `python python/plaseval_replication.py --out-dir out` re-scores the cohort and writes `out/plaseval_replication.html`; its section *Comparison with the original PlasEval program* shows the verdict, a per-tool table, the agreement scatter and the pairs not compared. Without a PlasEval checkout it compares with the recorded reference run (and says so on the page); with `--plaseval-src` it re-runs the original. The finished page from the reference run is `cohorts/plaseval_ecoli53/replication_report.html`.

Facts about the data worth knowing: repeated contigs are common (87 of the 212 pairs have at least one repeat family, and 246 contigs sit in more
than one truth bin), so the repeat-aware matching matters here; two searches (PlasBin-flow, large repeat families) reached the call cap
(`DISSIMILARITY_MAX_CALLS`, default 200,000) and are upper bounds; and the tool order depends on the length exponent (at alpha 0 PlasBin-flow
is first; at alpha 0.5 and 1 MOB-recon is), so the exponent must be reported with any result. The released ground truth has 184 plasmid bins
(mean 48,908 bp); the paper's text says 190 (mean 48,365 bp).

## Running the comparison on a computer that can

The original needs only Python with four small packages. Run these where you have the time; the largest repeat families take minutes per pair in
the original's pure-Python search.

```bash
# 1. the original program, pinned to the commit this was checked against (PlasBench never bundles it)
mkdir -p ~/.local/share/plasbench/tools && cd ~/.local/share/plasbench/tools
git clone https://github.com/acme92/PlasEval.git && git -C PlasEval checkout 8238356
pip install "networkx<3.4" "pandas<4" "bidict<1" "psutil<7"      # into the plasbench environment

# 2. the paper's real bins: PlasBench against the original, all 212 pairs
plasbench analysis plaseval-replication --out-dir results_plaseval --original-timeout 600 --workers 4
#    -> results_plaseval/plaseval_replication.html and plaseval_replication.scores.tsv

# 3. the gate inside a real benchmark of the cohort (needs the reads; hours and tens of GB)
export RUN_PLASEVAL_GATE=on          # stop the run if the original is missing or disagrees
plasbench run --cohort plaseval-ecoli53 --threads 16
#    -> results/benchmark.plaseval_gate.tsv and .json; the report's Bin agreement section shows the verdict
```

The original is found automatically in `~/.local/share/plasbench/tools/PlasEval/src` (or `$DATA_DIR/tools/PlasEval/src`, or `~/PlasEval/src`);
set `PLASEVAL_SRC` to the `src/` folder otherwise. `PLASEVAL_PYTHON`, `PLASEVAL_TIMEOUT` (seconds per pair, default 300),
`PLASEVAL_GATE_TOLERANCE` (default 0.001) and `PLASEVAL_GATE_WORKERS` are in `config/config.sh`.

### Reading the verdict

| Verdict | Meaning |
|---|---|
| `PASS` | Every compared pair agrees within the tolerance, on the dissimilarity and on best-match precision, recall and F1. A PlasBench value from a search that reached its cap may exceed the original's (it is an upper bound) and still passes. |
| `FAIL` | At least one pair disagrees. Treat PlasBench's dissimilarity as unverified for this run and report the disagreeing pairs. A capped value *below* the original's is impossible and counts as a failure. |
| `PARTIAL` | The pairs that could be compared agree; others timed out or failed in the original. |
| `NOT_RUN` | The original was not found (the reason says how to get it), the gate is off, or it could not run on any pair. |
| `NO_DATA` | The run exported no bins to compare (for example, only assemblers, which output sequences rather than contig bins). |

With `RUN_PLASEVAL_GATE=auto` (the default) the gate compares whenever the original is found and otherwise records `NOT_RUN`; it never changes a
score or a ranking. With `on`, a missing original or a `FAIL` stops stage 6. The gate checks the *scoring* against the original on the same
bins; it does not check that a tool behaves as in the paper, and agreement on one cohort is not agreement everywhere.

## What the replication does not show

It uses the paper's published tool predictions, so it says nothing about whether PlasBench's own runs of those tools reproduce them. The truth is
the paper's (hybrid contigs labelled by length and circularity, mapped onto the short-read contigs), not PlasBench's reference-based truth. The
dissimilarity compares which contigs are in which bin: it says nothing about sequence accuracy and does not apply to tools that output reassembled
sequences. The results above are for one species and one collection.
