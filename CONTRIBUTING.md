# Contributing to PlasBench

## Code changes

Standard GitHub flow: fork or branch, make your change, run
`plasbench test` (or `bash test/run_tests.sh`) and `plasbench demo`, and open
a pull request. `.github/CODEOWNERS` requires the maintainer's review on
every PR regardless of who else approves it, so don't expect a fast merge —
explain your reasoning in the PR description to make review quick.

## Contributing a new isolate to a public cohort

PlasBench's public cohorts (`cohorts/public-v1.tsv`, `cohorts/public-v2.tsv`)
grow by adding new, independently-verified assembly/read pairs — see
[`docs/FINDING_DATA.md`](docs/FINDING_DATA.md) for where to find them and the
evidence rules every row must satisfy. Adding one is a **local-only**
process: nothing is pushed on your behalf, and no account or token beyond
your own GitHub login is required.

1. **Find and verify a pair.** Follow
   [`docs/FINDING_DATA.md`](docs/FINDING_DATA.md#finding-matched-pairs-the-real-curation-task):
   NCTC 3000 first, then GenomeTrakr/PulseNet, then a published tool paper's
   supplementary cohort, in that priority order. Confirm a complete assembly
   with declared plasmid replicons and a matched paired-end Illumina run on
   the same BioSample.
2. **Benchmark it yourself.** Stage the isolate (`plasbench init-local` or
   your own sample sheet) and run `plasbench run --samples your_sheet.tsv`
   through to stage 6, so you have a real `results/scores.tsv` (and
   `results/tool_status.tsv`) for the new sample_id.
3. **Write the new cohort row(s).** A small TSV using the same columns as
   the target cohort file's own header (e.g.
   `cohorts/public-v2.tsv`'s first line).
4. **Run `plasbench prepare-contribution`:**
   ```bash
   plasbench prepare-contribution --cohort public-v2 \
     --new-rows my_new_rows.tsv --scores results/scores.tsv \
     --tool-status results/tool_status.tsv
   ```
   This checks, in order: schema, NCBI-linked evidence (the same rules
   `validate-cohort --online` applies), cross-cohort BioSample dedup against
   `cohorts/accepted_accessions.tsv`, a privacy/content screen (no local file
   paths, environment-variable references, hostnames, or raw sequence/
   assembly files in any field — only public accessions and metrics belong
   here), and metric sanity bounds (precision/recall/F1 in `[0, 1]`,
   non-negative runtime/memory). Any failure prints its reason and writes
   nothing; nothing is pushed automatically, ever.
5. **On success**, you're left on a new local branch
   (`contrib/<sample-id-or-label>`) with everything already committed: the
   new cohort row(s), appended `scores.tsv`/`tool_status.tsv` rows, an
   updated verification lock, and a regenerated ledger. Review the commit
   (`git show`), then push it yourself and open the PR:
   ```bash
   git push -u origin contrib/<label>
   ```
6. **Review.** `.github/CODEOWNERS` requires the maintainer's review before
   merge, the same as any other PR to this repository. Expect follow-up
   questions about provenance or curation — that scrutiny is what keeps the
   cohort's evidence rules meaningful.

### What this is not

This is a manual, one-contributor-at-a-time workflow, not an automated
anonymous-intake pipeline (no GitHub App, no auto-push from a running
benchmark, no hosted service). That is a deliberate choice at the project's
current scale — a single reviewer and a cohort of a few dozen isolates — and
may be revisited if manual review of contributions becomes a genuine
bottleneck.
