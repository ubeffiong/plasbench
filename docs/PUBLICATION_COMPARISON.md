# Publication cohorts, and comparing PlasBench with a paper's outcomes

You can run PlasBench on the isolates of a published plasmid benchmark and put your results beside what the paper reported for the
same isolates and tools. This is for **your own justification**: it shows whether PlasBench reproduces a published picture, and
where and by how much it differs. It is not a gate and not a ranking.

## The cohorts

Built by `plasbench build-publication-cohorts` from the candidate ledgers (`cohorts/candidates/`), the verified `public-v4`
sheet and NCBI resolution. Every row was verified online (`validate-cohort --online`, locked), is tier B, and has its truth
checked against the plasmids the paper used.

| Cohort | Isolates | Of the paper's | Truth check | Published outcomes shipped |
|---|---:|---:|---|---|
| [`pub-plsmd-novel`](../cohorts/pub-plsmd-novel.tsv) | 68 | 68 | all exact | plsMD, MOB-suite, gplas per-plasmid recall |
| [`pub-plsmd-filtered`](../cohorts/pub-plsmd-filtered.tsv) | 63 | 80 | 62 exact, 1 subset | plsMD, MOB-suite, gplas per-plasmid recall |
| [`pub-mobsuite`](../cohorts/pub-mobsuite.tsv) | 95 | 133 | 93 exact, 1 superset, 1 subset | MOB-suite recall, for the 63 isolates plsMD's paper also used |
| [`pub-teixeira2025`](../cohorts/pub-teixeira2025.tsv) | 5 | 250 | inferred (the paper lists no plasmid accessions) | 13 tools' contig-level calls on all 250 |
| [`publication-v1`](../cohorts/publication-v1.tsv) | 168 | 531 candidates | as above | all of the above |

`publication-v1` holds each isolate once. `published_studies` lists every study it belongs to (the plsMD filtered set is
inside the MOB-suite benchmark). **Do not pool the studies into one leaderboard**: their truth methods, independence and species differ.
The comparison keeps them apart.

`truth_match` per row: `exact` (the assembly's plasmids are exactly the paper's truth plasmids, ignoring version and the RefSeq
`NZ_` prefix), `superset` (the assembly has more), `subset` (it lacks some: those plasmids are "published only", never zero),
`inferred` (Teixeira: the assembly is the prior published hybrid; not compared). An isolate whose plasmids share nothing with the
paper's truth is left out. `paper_run_used` says whether the row's reads are the run the paper itself used. Where the paper's run
is one of the verified paired runs it is used.

### Why isolates are not in the cohorts

`cohorts/candidates/publication_cohort_audit.tsv` lists every one of the 531 candidates and what happened. In short:

* **Teixeira (245 of 250):** no complete assembly is deposited. Their truth must be rebuilt from the deposited long and short reads
  (`python/build_hybrid_truth.py`; the list is `cohorts/candidates/teixeira2025_self_build_candidates.tsv`). This is a download-heavy
  step that was not run. The published contig-level outcomes for all 250 still ship, so a rebuilt isolate can be compared.
* **MOB-suite (38 of 133) and plsMD filtered (17 of 80):** no deposited complete assembly (long and short reads exist: rebuildable), no
  usable read pair at NCBI (5), or NCBI records no long-read platform for the assembly, which therefore cannot serve as long-read truth (25).
* Nothing is left out for a poor result.

## Compare after a run

```bash
plasbench run --cohort pub-plsmd-novel --max-isolates 20        # or the whole cohort; add the tools you want
plasbench compare-published --results-dir results --samples cohorts/pub-plsmd-novel.tsv --html results/published_comparison.html
```

Stage 6 does this automatically when the sample sheet holds published isolates (setting `RUN_PUBLISHED_COMPARISON`, default `auto`;
`off` skips it), and the HTML report gains a **Comparison with published outcomes** section. It is matched by **BioSample**, so
it works with any sheet that carries the `biosample` column, including your own sheet of the same isolates. The window's Cohorts page
shows how each publication cohort was built, the funnel, why isolates are missing, and the command to compare.

### What is compared

| Study | Published metric | PlasBench metric | Tools with a counterpart |
|---|---|---|---|
| plsMD 2026 (both sets) | per-plasmid recall, copied from the paper's supplement | `completeness` per truth plasmid (`<sample>/<tool>.per_plasmid.tsv`), matched by accession | plsMD ↔ `plsmd`, MOB-suite ↔ `mob_recon`, gplas ↔ `gplas2_mob` (gplas2 is gplas's successor: similar, not identical) |
| Teixeira 2025 | per-isolate contig precision, recall and F1, by contig count and by contig length, **computed by PlasBench from the paper's published calls** and truth (not the paper's printed figures) | `contig_*_count` and `contig_*_bp` in `scores.tsv` | MOB-recon, PLASMe, PlaScope, Plasmer, Platon, RFPlasmid, geNomad, gplas2, plASgraph2, PlasBin-Flow, PlasmidEC. HyAsP and PlasmidFinder have no PlasBench counterpart: shown as published only |
| PlasEval 2024 | dissimilarity of the original program | see [`PLASEVAL_REPLICATION.md`](PLASEVAL_REPLICATION.md) (`plasbench analysis plaseval-replication`, and the comparison gate) | MOB-recon, HyAsP, gplas2, PlasBin-Flow |
| MOB-suite 2018 | none shipped per isolate: its recall for the 63 shared isolates is in the plsMD paper's table | as for plsMD | `mob_recon` |

For each tool and metric the output gives the number of matched pairs, the published mean, the PlasBench mean, the mean difference and
mean absolute difference, the correlation, the share of pairs within the tolerance (0.05), and a verdict: `consistent` (mean absolute
difference within the tolerance), `differs`, or `too few pairs` (under 5). Per study it adds whether the **tool order** agrees
(Spearman correlation and whether the same tool leads, when three or more tools are compared). Per-plasmid results are also split by the
paper's plasmid size class.

Outputs: `benchmark.published_comparison.tsv` (summary), `benchmark.published_comparison_pairs.tsv` (every matched isolate or plasmid with both
values), `benchmark.published_comparison.json` (verdicts, tools with no counterpart, caveats, definitions) and the stand-alone page.

### How to read a gap

Read the caveats printed with every study. The common reasons PlasBench differs from a paper, none of them an error in either result:

* **Different assembly.** PlasBench assembles the reads with its own assembler; the paper used its own. Per-plasmid recall and contig
  results depend on the assembly. Per-isolate numbers are compared as means, not contig by contig.
* **Different tool or database version.** plsMD and PlaScope depend on a database release (PLSDB, Plasmid DB); the paper's release is
  not yours. `config/tool_database_releases.tsv` records yours.
* **Different metric definition.** plsMD's recall and PlasBench's completeness are the same idea, not the same code. PlasBench drops contigs
  under `CONTIG_MIN_LENGTH` and treats ambiguous and chimeric contigs as unscorable; the published table keeps all.
* **Different truth.** The papers' truth is their own closed or hybrid assembly; PlasBench's is the resolved NCBI assembly, matched by
  accession. Where truth was built on the same Illumina reads as the benchmark input, every tool is flattered (check `truth_polish_reads`).
* **Selection.** The plsMD filtered set keeps only samples whose Unicycler assembly is explained by the closed genome, which favours every tool.
  The novel set's absence from PLSDB is the paper's claim, not verified here (23 of its 68 runs were public before the stated sequencing date).

A published value PlasBench could not match (tool not run or failed, or the plasmid is not in PlasBench's truth) is counted as "published only",
never as a zero.

## Rebuild or extend

```bash
plasbench analysis build-published-outcomes --plsmd-xlsx <Additional file 2> --teixeira-xlsx <predictions.xlsx>   # rebuilds cohorts/published/
plasbench build-publication-cohorts --online --resolved mobsuite=<resolved.tsv> ...                                # rebuilds the cohorts; needs NCBI_EMAIL
```

`cohorts/published/<study>.meta.json` records each table's source URL, SHA-256, definitions and caveats. To add a study, add a published table
and a meta file there (the metric map names the PlasBench column to compare against) and a candidate ledger with BioSample accessions.

**Validated so far:** the comparison is tested on constructed results, and the shipped tables are checked against the papers (the plsMD
filtered set's mean plsMD recall is 93.07 percent, as the paper reports). **Not yet done:** no tool has been run on these cohorts, so no real
PlasBench-versus-paper result exists yet.
