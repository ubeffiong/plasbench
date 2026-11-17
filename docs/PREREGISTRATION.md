# Scoring decisions (pre-registration): what was decided, and how to change it

*Written for: anyone who uses PlasBench results, with no statistics background assumed.*

## What this is, in plain words

When tools are compared, a lot depends on rules chosen along the way: which score ranks a tool, which reference sequences are trusted, how wide an uncertainty range is drawn, how long a
tool may run. If those rules are chosen after seeing the results, it is easy (even without meaning to) to pick the ones that make a favourite tool win.

So PlasBench fixes its rules **before** any result is looked at, writes them down, and records who agreed to them and when. This is called *pre-registration*. The rules are in the window
under **Scoring decisions**, and in the file `config/prereg.tsv`. Every report and run records that these decisions were in force.

## What has been decided

**On 16 November 2026 the project owner confirmed all 29 decisions that had been proposed.** Nothing was left open. Together with the decisions settled earlier, and one added on 17 November 2026 (`interval_method_stratified`, decided by Claude as an expert on the full interval simulation, with the project owner's delegation), all 70 decisions are
now confirmed (one of them, the scorecard bands for variant concordance and structural variants, is marked *unavailable by design*: there is no independent set of true variants to compare
with, so PlasBench shows those two measures as unavailable instead of inventing a threshold).

The record of that confirmation (who, when, why) is in `config/prereg_decisions.tsv`, and in the window under **Scoring decisions > Decision record**.

The decisions that matter most for how to read a result:

| Decision | Value | In plain words |
|---|---|---|
| How classifiers and binners are ranked | base-level F1; length-weighted binning F1 | how many bases they label or place correctly |
| How reassemblers are ranked | isolate-level CPRR | the share of each isolate's plasmids rebuilt completely and accurately |
| Which references feed the main ranking | independent only | references built mainly from long reads and not corrected with the same short reads the tools are tested on |
| Fewest independent studies for the main ranking | 5 | with fewer, the ranking is marked provisional |
| How uncertainty ranges are drawn | cluster-robust t | treats each independent study as one unit |
| When that is replaced | one study holds more than 30% of the isolates | the simulation found the default too narrow then, so a different method is used |
| How long one tool may run on one isolate | no limit | 7200 seconds was confirmed and then changed the same day: a limit scores a slow tool zero, and big isolates and many tools make runs of many hours normal. Set a generous limit only to stop a truly stuck run |

## All the decisions

Each row says what the decision means, the value that was decided, and whether you can change it.

<!-- prereg-table:start -->
### How tools are ranked

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **The score that ranks classifiers and binners** (`primary_endpoint`) | Tools that only label sequence as plasmid or not (classifiers) are ranked by how many bases they label correctly (base-level F1). Tools that group contigs into plasmids (binners) are ranked by how correctly each base is placed in the right plasmid (length-weighted binning F1). Complete reconstruction (CPRR) is shown beside the binning score as the second measure. | `length-weighted binning F1 (lw_bin_f1) for binning reconstruction; base F1 for classification; CPRR key secondary for binning reconstruction` | no (written into the program) |
| **The score that ranks reassemblers** (`primary_endpoint_reassembly`) | Tools that build new plasmid sequences are ranked by the share of each isolate's plasmids they reconstructed completely and accurately (isolate-level CPRR). Binning F1 is shown beside it. | `isolate-level CPRR (sample_cprr) for sequence reassembly on every input track; lw_bin_f1 secondary` | no (written into the program) |
| **How sensitive complete-reconstruction scores are to the cut-off** (`cprr_threshold_sweep`) | The report also shows how the reconstruction score would move if the coverage and purity cut-offs were stricter or looser (0.80 to 0.99). It is for information and never changes a rank. | `0.80-0.99 step 0.01 on coverage and bin share; normalised AUC` | no (written into the program) |
| **Whether isolates with many plasmids dominate** (`cprr_isolate_weighting`) | Both versions of the reconstruction rate are reported: counting every plasmid equally, and averaging per isolate so that an isolate with many plasmids does not dominate. | `pooled over plasmids and mean over isolates, both reported` | no (written into the program) |
| **How structural checks are used** (`sv_prr_use`) | The extra structural check (SV-PRR) is shown beside the reconstruction rate and never used to rank tools. | `reported beside CPRR, never ranked; counts a CPRR-correct plasmid only when no structural call touches it` | no (written into the program) |

### Which references count

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **How reference sequences are called plasmid or chromosome** (`primary_label_scheme`) | The main ranking uses the labels from the NCBI sequence report. The other two labelling schemes are used only to check whether the ranking would change. | `ncbi` | yes, in the window or with `plasbench analysis prereg set` |
| **Which other labellings are used as a check** (`sensitivity_label_schemes`) | The ranking is repeated with the two other labelling schemes, and the report says how much the order changed. | `nonchromosomal,evidence` | no (written into the program) |
| **How the reference assembly must have been built** (`truth_construction`) | Only references built mainly from long reads count for the main ranking. References built from short reads first are shown separately. | `long-read-first only for the headline` | no (written into the program) |
| **How species are weighted in the main score** (`species_averaging`) | The main score is the average of per-species averages, so one over-represented species cannot dominate. A species needs enough independent studies to be included. | `macro over species with >= MIN_SPECIES_CLUSTERS clusters` | no (written into the program) |
| **How many independent studies a species needs** (`min_species_clusters`) | A species counts in the species-balanced score only when its isolates come from at least this many independent studies (or clonal groups). | `20` | yes, in the window or with `plasbench analysis prereg set` |
| **Lowest reference quality allowed in the main ranking** (`headline_max_reference_tier`) | References are graded 1 (best) to 3. The main ranking accepts grades 1 and 2; grade 3 is used only as a check. | `2` | yes, in the window or with `plasbench analysis prereg set` |
| **Which references are independent enough for the main ranking** (`headline_independence`) | A reference is independent when it was built mainly from long reads and was not corrected with the same short reads the tools are tested on. The main ranking uses only independent references. Partly independent ones are a first check, and all references are a second check. | `independent` | yes, in the window or with `plasbench analysis prereg set` |
| **Older on/off form of the independence rule** (`headline_reference_independence`) | The older two-valued version of the rule above: independent only, or any. Kept so existing set-ups keep working. | `independent` | yes, in the window or with `plasbench analysis prereg set` |
| **Fewest independent studies for the main ranking** (`headline_min_clusters`) | The main ranking is only produced when its references come from at least this many independent studies. Otherwise the ranking is marked provisional. | `5` | yes, in the window or with `plasbench analysis prereg set` |
| **Whether a weaker ranking may replace the main one** (`allow_primary_fallback`) | 0 means that when no reference qualifies, the report says the main ranking is unavailable. 1 would silently show a ranking on all samples instead, with a warning. | `0` | yes, in the window or with `plasbench analysis prereg set` |

### Tool runs

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **What a tool scores when it crashes or gives no output** (`failed_tool_score`) | A tool that crashes or produces nothing on an isolate scores zero for that isolate and is still ranked. A tool cannot move up by failing on hard isolates. | `0` | no (written into the program) |
| **What happens when the computer, not the tool, fails** (`infrastructure_failure_scored`) | If the run was killed by the computer (out of memory, a timeout, a lost disk) it is re-run and not scored against the tool. | `no` | no (written into the program) |
| **How many times a failed run is retried automatically** (`tool_retries`) | A tool that fails is run once more before it is counted as failed. | `1` | yes, in the window or with `plasbench analysis prereg set` |
| **How long one tool may run on one isolate** (`tool_timeout_seconds`) | By default there is no limit. If you set one, a tool that runs longer on one isolate is stopped and counted as failed, and a failure scores zero for that tool. The limit is per tool per isolate, the same for every tool, not for the whole pipeline. | `unset` | yes, in the window or with `plasbench analysis prereg set` |

### Alignment filters

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Smallest accepted sequence match** (`min_alignment_identity`) | When a prediction is compared with the reference, an alignment below this identity is ignored. | `0.90` | yes, in the window or with `plasbench analysis prereg set` |
| **Shortest accepted alignment** (`min_alignment_length`) | Alignments shorter than this many bases are ignored when predictions are compared with the reference. | `200` | yes, in the window or with `plasbench analysis prereg set` |
| **Smallest accepted alignment confidence** (`min_alignment_mapq`) | Alignments the aligner is not confident about (below this quality) are ignored. | `20` | yes, in the window or with `plasbench analysis prereg set` |
| **Smallest share of a contig that must align** (`min_alignment_query_coverage`) | A predicted contig must align over at least this share of its length for the alignment to count. | `0.20` | yes, in the window or with `plasbench analysis prereg set` |

### Reference checks

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Size above which a second chromosome is suspicious** (`chromid_min_bp`) | A reference replicon labelled chromosome that is not the largest and is at least this long is flagged as a possible second chromosome (chromid). | `350000` | yes, in the window or with `plasbench analysis prereg set` |
| **Size above which a plasmid is flagged as large** (`large_plasmid_bp`) | A plasmid at least this long is flagged, because it may really be a second chromosome. | `500000` | yes, in the window or with `plasbench analysis prereg set` |
| **How similar two halves must be to call a double copy** (`dimer_min_identity`) | A reference plasmid whose two halves match at least this well is treated as a head-to-tail double copy (a dimer). | `0.95` | yes, in the window or with `plasbench analysis prereg set` |
| **How much each half must cover** (`dimer_min_half_coverage`) | Each half must align over at least this share to count as a double copy. | `0.90` | yes, in the window or with `plasbench analysis prereg set` |
| **Whether double copies are collapsed** (`collapse_dimers`) | 1 means a reference that is a double copy of a plasmid is reduced to one copy before scoring; 0 leaves it. | `1` | yes, in the window or with `plasbench analysis prereg set` |
| **Read depth that supports an integrated element** (`integrated_element_min_depth`) | A candidate plasmid integrated into a chromosome needs at least this read depth to be considered supported. | `3` | no (written into the program) |
| **Whether a candidate must form a circle** (`unverified_candidate_requires_circular_path`) | An unverified candidate needs a circular path in the assembly graph to be considered. | `yes` | no (written into the program) |
| **Distance below which a close reference exists** (`no_close_reference_mash_distance`) | A distance report treats a plasmid as having a close relative in the reference set when the distance is below this value. | `0.01` | no (written into the program) |

### Statistics

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Fewest independent studies for a confidence interval** (`min_clusters_ci`) | An interval is only computed when the scores come from at least this many independent studies. With fewer, the report says the interval cannot be estimated. | `5` | no (written into the program) |
| **Fewest independent studies for a significance test** (`min_clusters_test`) | A comparison test between two tools is only run with at least this many independent studies. With fewer, the smallest possible p-value is too large to be meaningful. | `6` | no (written into the program) |
| **When tests are exact and when they are simulated** (`exact_permutation_max_units`) | Up to this many independent studies the test counts every possible outcome exactly; above it, it samples outcomes at random. | `12` | no (written into the program) |
| **Difference too small to matter** (`smallest_difference`) | Two tools whose scores differ by less than this are reported as practically equivalent. | `0.05` | yes, in the window or with `plasbench analysis prereg set` |
| **The test used to compare two tools** (`paired_test`) | Two tools are compared with a permutation test on whole studies, with a second test beside it, and p-values are adjusted for the number of comparisons (Holm). | `sign-flip permutation (primary) and Wilcoxon signed-rank` | no (written into the program) |
| **How confidence intervals are calculated when species are balanced** (`interval_method_stratified`) | When the ranking averages per-species means (the usual headline), the interval uses a studentised cluster bootstrap: whole studies are resampled within each species and each draw is scaled by its own standard error. Without species balancing the cluster-robust t interval of the previous decision is still used. | `bootstrap_t` | yes, in the window or with `plasbench analysis prereg set` |
| **How confidence intervals are calculated** (`interval_method`) | The default is a cluster-robust t interval, which treats each independent study as one unit. Two other methods stay available and are measured beside it. | `cluster_t` | yes, in the window or with `plasbench analysis prereg set` |
| **When one study is too large for the default interval** (`dominant_study_share`) | If one study holds more than this share of the isolates, intervals switch to the percentile method, which the simulation found less bad in that situation. | `0.30` | yes, in the window or with `plasbench analysis prereg set` |

### Recovery definitions

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **How much of a plasmid counts as recovered** (`plasmid_recovery_threshold`) | A plasmid counts as recovered when at least this share of it is covered by the prediction. | `0.90` | yes, in the window or with `plasbench analysis prereg set` |
| **How exact a plasmid must be to count as perfect** (`perfect_threshold`) | A plasmid is perfect when both its precision and its recall reach this value. | `0.95` | yes, in the window or with `plasbench analysis prereg set` |
| **When a plasmid is called fragmented** (`fragment_share`) | A plasmid is fragmented when a second bin holds at least this share of it. | `0.20` | yes, in the window or with `plasbench analysis prereg set` |
| **When a plasmid is called missed** (`missed_recall`) | A plasmid is missed when the best bin recovers less than this share of it. | `0.50` | yes, in the window or with `plasbench analysis prereg set` |

### Contig layer

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Shortest contig scored in the contig view** (`contig_min_length`) | The contig-level view (shown beside, never used for ranking) ignores contigs shorter than this. | `1000` | yes, in the window or with `plasbench analysis prereg set` |
| **Smallest match for the contig view** (`contig_min_identity`) | Minimum identity for a contig to be assigned in the contig view. | `0.95` | yes, in the window or with `plasbench analysis prereg set` |
| **Smallest coverage for the contig view** (`contig_min_coverage`) | Minimum share of a contig that must align in the contig view. | `0.80` | yes, in the window or with `plasbench analysis prereg set` |

### Recommendation

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **How close to the best counts as near-optimal** (`near_optimal_margin`) | A recommendation is near-optimal when its score is within this distance of the best tool for that isolate. | `0.05` | yes, in the window or with `plasbench analysis prereg set` |
| **Smallest gain that justifies recommending per isolate** (`oracle_gap_floor`) | If always choosing the single best tool is within this distance of the perfect per-isolate choice, per-isolate recommendation is not worth it and the verdict says so. | `0.02` | yes, in the window or with `plasbench analysis prereg set` |
| **How bad a recommendation must be to count as failed** (`recommendation_failure_regret`) | A recommendation that scores this much worse than the best tool is counted as a failure. | `0.10` | yes, in the window or with `plasbench analysis prereg set` |
| **Lowest score at which a tool is still recommended** (`recommendation_min_expected_score`) | If the best expected score is below this value, no tool is recommended, because none is good enough. | `0.40` | yes, in the window or with `plasbench analysis prereg set` |
| **The locked test set for the recommender** (`holdout_split`) | The recommender's test set is locked and may be evaluated once, so it cannot be tuned against. | `locked; evaluated once with --confirm-holdout` | no (written into the program) |

### Scorecard and maps

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Weights in the overall scorecard** (`scorecard_weights`) | How much each measure counts in the overall scorecard grade. The scorecard is an extra view and never changes a ranking. | `A1=10 A2=5 A3=5 A4=10 B1=10 B2=5 B3=5 C1=8 C2=7 C3=5 C4=5 D1=5 D2=5 D3=5 E1=4 E2=3 E3=3 (sum 100)` | by editing `config/scorecard.tsv` |
| **Grade boundaries of the overall scorecard** (`scorecard_overall_bands`) | The overall score cut-offs for excellent, good, moderate and poor. | `excellent>=90 good>=75 moderate>=55 else poor` | by editing `config/scorecard.tsv` |
| **Boundaries for sequence identity** (`scorecard_bands_A1`) | Cut-offs for grading sequence identity. | `excellent>=99.9 good>=99.0 moderate>=95.0 floor=90 (percent)` | by editing `config/scorecard.tsv` |
| **Boundaries for mismatch rate** (`scorecard_bands_A2`) | Cut-offs for grading how many mismatches there are per 100 aligned bases. | `excellent<=0.1 good<=0.5 moderate<=2.0 floor=10 (per 100 aligned columns)` | by editing `config/scorecard.tsv` |
| **Boundaries for insertion and deletion accuracy** (`scorecard_bands_A3`) | Cut-offs for grading insertions and deletions. | `excellent>=99.9 good>=99.5 moderate>=98 floor=90 (percent)` | by editing `config/scorecard.tsv` |
| **Variant concordance and structural variants** (`scorecard_bands_A4_C2`) | No grading is applied: there is no independent set of true variants to compare with, so these two measures are shown as unavailable. | `none: no independent truth variant set exists` | by editing `config/scorecard.tsv` |
| **Boundaries for reference coverage** (`scorecard_bands_B1`) | Cut-offs for grading how much of the reference is covered. | `excellent>=0.99 good>=0.95 moderate>=0.8 floor=0.5` | by editing `config/scorecard.tsv` |
| **Boundaries for completeness and plasmid recovery** (`scorecard_bands_B2_B3`) | Cut-offs for grading reconstruction completeness and plasmid recovery. | `excellent>=0.95 good>=0.85 moderate>=0.6 floor=0.2` | by editing `config/scorecard.tsv` |
| **Boundaries for structural accuracy** (`scorecard_bands_C1`) | Cut-offs for grading structural accuracy (an estimate from alignments). | `excellent>=0.95 good>=0.85 moderate>=0.7 floor=0.4` | by editing `config/scorecard.tsv` |
| **Boundaries for circularisation** (`scorecard_bands_C3`) | Cut-offs for grading whether circular plasmids were closed correctly. | `excellent>=0.9 good>=0.7 moderate>=0.4 floor=0` | by editing `config/scorecard.tsv` |
| **Boundaries for repeat resolution** (`scorecard_bands_C4`) | Cut-offs for grading how well repeats were resolved. | `excellent>=0.95 good>=0.85 moderate>=0.6 floor=0.2` | by editing `config/scorecard.tsv` |
| **Boundaries for gene recovery** (`scorecard_bands_D1`) | Cut-offs for grading how many genes were recovered. | `excellent>=0.99 good>=0.95 moderate>=0.85 floor=0.5` | by editing `config/scorecard.tsv` |
| **Boundaries for annotation agreement** (`scorecard_bands_D2_D3`) | Cut-offs for grading how well annotations agree with the reference. | `excellent>=0.95 good>=0.85 moderate>=0.7 floor=0.4` | by editing `config/scorecard.tsv` |
| **Boundaries for run time** (`scorecard_bands_E1`) | Cut-offs for grading run time in seconds. They depend on the computer. | `excellent<=60 good<=300 moderate<=1800 floor=14400 (seconds)` | by editing `config/scorecard.tsv` |
| **Boundaries for memory use** (`scorecard_bands_E2`) | Cut-offs for grading peak memory in GB. They depend on the computer. | `excellent<=2 good<=8 moderate<=32 floor=256 (GB)` | by editing `config/scorecard.tsv` |
| **Boundaries for success rate** (`scorecard_bands_E3`) | Cut-offs for grading how often a tool finishes. | `excellent>=0.99 good>=0.95 moderate>=0.8 floor=0.5` | by editing `config/scorecard.tsv` |
| **Fewest isolates for a scorecard** (`scorecard_min_samples`) | A scenario scorecard based on fewer isolates than this is marked as having too little data. | `5` | yes, in the window or with `plasbench analysis prereg set` |
| **Largest plasmid drawn as a circle** (`map_max_bp`) | Plasmids longer than this are not drawn as circular maps in the report. | `600000` | no (written into the program) |

### Resistance genes

| Decision | What it means | Value | Can be changed |
|---|---|---|---|
| **Region around a resistance gene that must also be recovered** (`amr_flank_bp`) | A resistance gene counts as recovered with its context when this many bases on either side are also covered by the same contig. | `1000` | yes, in the window or with `plasbench analysis prereg set` |
<!-- prereg-table:end -->

## How to look at them

In the PlasBench window, open **Set up > Scoring decisions**. You will see whether every decision is confirmed, whether they are locked (see below), and every decision in plain words. Use
the search box or the topic buttons to find one. If a setting on your computer differs from the decision, the page says so in a yellow box, because a run on your computer would then not follow
the plan.

From the command line:

```bash
plasbench analysis prereg list                 # every decision with its value and status
plasbench analysis prereg show interval_method # one decision in full, with its history
plasbench analysis prereg history              # the whole decision record
plasbench analysis prereg check                # are the files consistent?
```

## How to change a decision

You can change a decision, but not quietly. A change always needs **your name** and **a reason**, and both are kept in the decision record.

**In the window**

1. Open **Set up > Scoring decisions** and find the decision.
2. Press **Change**. (A decision that is built into the program has no Change button, see below.)
3. Enter the new value, say why, and give your name. PlasBench explains what would change.
4. Press **Record the change**. The new value is used on this computer straight away.
5. Press **Lock the decisions** again when you are happy (see "The lock").

**From the command line**

```bash
plasbench analysis prereg set dominant_study_share 0.40 \
    --by "Your Name" --reason "The cohort has two very large studies"
plasbench analysis prereg lock
```

Add `--update-default` to `set` if you work from a source checkout and want the new value to become the default for everyone who uses it (it also edits `config/config.sh`).

### What cannot be changed here, and why

| Kind | Examples | Why | What to do |
|---|---|---|---|
| **Built into the program** | which score ranks each kind of tool; how failures are scored | the rule is in the scoring code, so changing the text would *record* something the program does not *do* | ask for a code change; it becomes a new version of PlasBench |
| **A scorecard table** | the grade boundaries of the scorecard | the values live in `config/scorecard.tsv` | edit that file, then note the change in the record |
| **A setting** | time limits, thresholds, which references count, the interval method | PlasBench reads them as settings | change it here |

### What happens when you change one

- **Results made before the change cannot be compared with results made after it.** The rules were different. Keep the old and the new results apart.
- The lock (below) no longer matches until you lock again, and the report shows that the decisions changed after they were locked.
- Some changes alter only how a result is *drawn* (the uncertainty range, the scorecard grade). Others change the scores themselves (how references are labelled, the alignment filters). Each
  decision's row says which; the **If changed** text in the window says it too.

## The lock

*Locking* records a fingerprint of the decisions. Every run notes that fingerprint, so anyone can later check that the decisions used for a result are the decisions that were recorded. If a
decision changes after the lock, the fingerprint no longer matches and the report says so.

- **Lock the decisions** in the window, or `plasbench analysis prereg lock`.
- Locking is refused while any decision is still unconfirmed.
- Locking again after a change is normal and expected: it makes the new decisions the recorded ones.
- To make a run refuse to start unless the lock matches and nothing departs from the plan, set `REQUIRE_PREREG=1`.

## Questions

**Can I change a decision after I have seen results?** PlasBench lets you, because it is your project, but it keeps the record and warns that results before and after are not comparable. If a
change is made *because* of what a result showed, say so in the reason; a reader of your record will want to know.

**Why does the page say "this computer differs"?** A setting on your computer (in `config/local.env`) is different from the confirmed decision. A run here would not follow the plan. Change the
setting back on the **Settings** page, or record a decision to change it.

**What happens when I upgrade PlasBench?** The decision files come with the release, so an upgrade brings the release's decisions. Your own settings in `config/local.env` are kept. If you had
changed a decision, check **Scoring decisions** after upgrading: a setting that departs from the plan is flagged, and you can record the change again.

**Where is it all stored?** `config/prereg.tsv` (the decisions), `config/prereg_plain.tsv` (the plain-language text), `config/prereg_decisions.tsv` (the record), `config/prereg.lock.json` (the lock).
For the technical background and the older tooling, see [SCIENTIFIC_GUIDE.md](SCIENTIFIC_GUIDE.md) and `python/freeze_prereg.py`.

## What was not adopted from the original scoring specification

| Item | Reason |
|---|---|
| Plasmid-free isolates scored 0 in F1 averages | F1 is undefined there; PlasBench reports them in the negative-control table instead. |
| Summed assigned-contig length as the primary recall denominator | Kept as a contig-layer-only definition; the headline uses the reference. |
| A context model / contamination gate beyond the advisory assembly QC gate | Needs real data; the recommendation-model audit is still owed. |
| More than 100 in-house isolates | A data-collection task, not code. |

See [PANEL_ALIGNMENT.md](PANEL_ALIGNMENT.md) for how each panel question maps to what was implemented, and [METHODS.md](METHODS.md#scoring-specification) for the definitions.
