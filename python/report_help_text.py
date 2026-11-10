#!/usr/bin/env python3
"""
report_help_text.py -- the words behind the "?" help button on every section and tab of the HTML report.

One entry per section id and per tab (panel) id. Each entry answers the same six questions, in plain language for a reader who is not a specialist:

  plain    what this shows, in one or two plain sentences (what question it answers)
  data     the data it uses
  how      how the numbers were made (the method)
  read     how to read it: what a high or low value, a bar, a colour or a row means
  why      why it matters: what it tells you, what decision it informs
  careful  what to keep in mind: the limits and the usual misreadings

Terms used throughout (they are also in the Keys section): "truth" is the complete, trusted reference assembly of an isolate; a "tool" is one plasmid-reconstruction
method; a "track" is one kind of input (short-read, long-read or hybrid) and tracks are never mixed; "F1" is one number that balances precision (how much of what the
tool called plasmid really is plasmid) and recall (how much of the real plasmid the tool found), from 0 (nothing right) to 1 (perfect); "CPRR" is the share of truth
plasmids a tool reconstructed correctly.

Entries are checked by test/test_report_help.py: every section and tab of the demo report has one, and every entry fills all six fields. Add an entry here when a section
or tab is added; the build leaves a section without an entry without a button, and the test names it.

Standard library only.
"""

FIELDS = (("plain", "In plain words"), ("data", "Data used"), ("how", "How it was made"), ("read", "How to read it"), ("why", "Why it matters"),
          ("careful", "Keep in mind"))


def H(plain, data, how, read, why, careful):
    return {"plain": plain, "data": data, "how": how, "read": read, "why": why, "careful": careful}


HELP = {
    # ------------------------------------------------------------------ Overview
    "summary": H(
        "The one-screen answer: how many methods and isolates were compared, which method leads, and what to look at first.",
        "Everything on this page is taken from the other sections of this report; nothing new is measured here.",
        "The headline numbers are counted from the run. The leading method is the one with the highest ranking score in the leaderboard. Each method gets a letter grade "
        "from four parts: base F1, plasmid recall, how little chromosome it wrongly calls plasmid, and how many runs completed.",
        "Start with 'Start here'. A grade A-E is a quick label; open the leaderboard for the actual numbers. The matrix shows, for each real plasmid and each tool, how much "
        "of that plasmid the tool covered.",
        "It tells you where to look and whether the result is solid enough to act on. It is the entry point, not a second source: every figure is repeated, in full, below.",
        "A grade is an opinion built from the stated weights, not a standard. The leader is only the leader on this cohort and this track."),
    "leaderboard": H(
        "The ranking of reconstruction methods: which tool recovered plasmids best on this cohort.",
        "Scores of every tool on every isolate, compared with the complete reference assembly (the truth).",
        "Tools are ranked separately for each track and task, never mixed. On the short-read track the ranking score is length-weighted binning F1; on long-read and hybrid "
        "tracks it is the share of truth plasmids reconstructed correctly (CPRR).",
        "Higher is better. Rank 1 leads. Read the interval and the 'significant vs runner-up' column before treating a gap as real.",
        "It answers the main question of the benchmark: which method to trust to rebuild plasmids from a given kind of data.",
        "A top rank on this cohort is not proof that a tool is right for every isolate. A failed run on an isolate that has plasmids counts as zero."),
    "leaderboard-main": H(
        "The full ranking table, one row per tool.",
        "Per-isolate scores of binning-capable tools (those that group contigs into plasmid bins) against the reference.",
        "The ranking score is computed per isolate and averaged. Plasmid recall counts every real plasmid equally, so one huge plasmid cannot dominate. 'Perfect' means "
        "everything found and nothing extra; 'strict' also forbids ambiguous bases.",
        "Compare the ranking score first, then precision (is what it called plasmid really plasmid?) and recall (did it find the plasmid?). The 95% interval shows the "
        "uncertainty.",
        "Shows who is best and how the leader wins: by finding more, or by being more careful.",
        "With few isolates the interval is wide and ranks can swap. Columns marked 'not computed' were not available for this run."),
    "chart": H(
        "The ranking as bars: precision, recall and F1 for each tool.",
        "The same scores as the ranking table.",
        "Each bar is a tool's average over isolates. Green is precision, amber is recall, dark green is F1; the bar length runs from 0 to 1.",
        "A long dark-green bar is good. A tool with high precision but low recall is cautious and misses plasmids; the opposite over-calls.",
        "A quick picture of the trade-off each tool makes.",
        "Averages hide isolates where the tool did badly; use the figures for the spread."),
    "robustness": H(
        "How far the ranking can be trusted: the checks behind the headline and the paired tests between tools.",
        "The same scores as the ranking, re-examined on shared samples and in pairs.",
        "Tools are compared on the isolates they all have, and paired differences are tested, grouping isolates that come from the same study so they are not counted twice.",
        "Look for gaps that are large and clearly different from chance.",
        "Tells you whether 'A beats B' is a real difference or noise.",
        "These checks never change the ranking; they add or remove confidence in it."),
    "robustness-main": H(
        "A set of checks on how solid each headline number is.",
        "Scores on the isolates all ranked tools share, and the number of independent studies behind them.",
        "Every tool is ranked on the same shared isolates. Isolates from one study are grouped into one 'independent cluster' because they are not independent evidence. "
        "Strict precision, recall ceiling and database overlap are extra safeguards.",
        "'Ranked on' says how many isolates the number rests on; 'independent clusters' says how many separate studies. Small numbers mean weak evidence.",
        "Shows whether the result rests on enough independent data.",
        "These columns are not the ranking score: mean base F1 here is a different, simpler measure."),
    "statistics": H(
        "Tool-against-tool tests: is the difference between two tools bigger than chance?",
        "Scores of both tools on the isolates they share.",
        "For each pair the difference (A minus B) is averaged, with a confidence interval and permutation and Wilcoxon p-values. Whole studies are resampled together when "
        "the sample sheet records them. Holm adjustment corrects for making many comparisons.",
        "A small adjusted p-value and an interval that excludes zero point to a real difference. 'Equivalent within delta' means the tools are practically the same.",
        "Stops you from over-reading small gaps.",
        "With fewer than five independent units a test is 'not estimated'. A p-value says a difference is unlikely to be chance, not that it matters in practice."),
    "metadata": H(
        "What was run: the folder, the cohort, when the report was made, which inputs were used, and which analyses were not run.",
        "The run's own records (manifest, execution status and the files it wrote).",
        "Read straight from the run's manifest and output folder; the 'not run' list names every analysis that was skipped and why.",
        "Use it to confirm you are looking at the run you expect, and to see what is missing.",
        "Lets a reader reproduce or audit the run, and shows gaps honestly instead of hiding them.",
        "An analysis listed as not run is not a failure of the tools; it simply was not switched on or lacked its input."),
    # ------------------------------------------------------------------ Recommendation
    "recommendations": H(
        "Which reconstruction method to use where. This is advice for choosing, not the ranking.",
        "Per-isolate scores grouped by organism, plasmid size, read depth and resistance genes.",
        "A tool is recommended for a group only when enough isolates support it. The choice weighs accuracy first, then failure rate, structure checks, runtime and memory.",
        "'Primary' is the first choice for that group; the reason column says why. A group with too little data gets no recommendation.",
        "Turns the benchmark into a practical choice for a real laboratory.",
        "Only reconstruction tools are compared here, never classifiers. The advice is only as good as the cohort behind it."),
    "recommendations-main": H(
        "The recommendation table: the suggested method for each group of isolates.",
        "Scores of reconstruction tools in each group (organism, size, depth, resistance).",
        "A multi-objective choice that is gated by evidence: groups with too few isolates are withheld, not guessed.",
        "Find your situation in the 'Group' column and read the primary method and its reason.",
        "It informs which tool to run on a new isolate that looks like one of these groups.",
        "It is advisory. A recommendation is not proof that any individual predicted plasmid is right."),
    "stratified": H(
        "The evidence behind each recommendation, group by group.",
        "Per-tool scores inside each organism, size, depth or resistance group.",
        "Coverage (how many isolates in the group the tool was scored on) and mean F1 are tabulated, and the evidence gate decides whether a recommendation is allowed.",
        "Look at coverage and the number of samples first; a high score on two isolates means little.",
        "Shows whether a recommendation stands on enough data.",
        "It never changes the leaderboard."),
    "selected": H(
        "For each isolate, the reconstruction chosen as the best candidate, with the evidence for it and a warning when it needs checking.",
        "The tool outputs that were already produced and the comparison with the reference.",
        "The selected output is the retained file from the completed run; downloading it does not re-run anything. The confidence line lists the reasons for caution.",
        "Read 'Why this selection needs review' before using a sequence.",
        "Helps a user pick a sequence and see how far to trust it.",
        "A benchmark-validated candidate is still a prediction. Confirm important plasmids with long reads."),
    "recommender-eval": H(
        "A research check: does choosing a tool per isolate really beat always using the single best tool?",
        "Scores of each tool on each isolate, with each study held out in turn.",
        "The recommender is trained without a study and tested on it (leave-one-study-out). Regret is how much F1 is lost against the best tool for that isolate.",
        "The verdict line says whether per-isolate choice helps or whether to simply use the leaderboard.",
        "Guards against recommendations that look clever but add nothing.",
        "This is method research, not the benchmark result. It is closed by default."),
    "recommender-eval-main": H(
        "The verdict and numbers for per-isolate selection.",
        "Held-out isolates and the single best tool.",
        "Regret = best tool's F1 minus the recommended tool's F1. Gap closed = how much of the single-best tool's regret the recommender removes. If the possible gain is tiny, "
        "the verdict is 'use the leaderboard'.",
        "Lower regret is better; a gap closed near 100% means the recommender is close to ideal.",
        "Says whether a per-isolate recommender is worth using.",
        "With few isolates the verdict is weak evidence."),
    "taxon-transfer": H(
        "Does the advice still work on organisms the recommender never saw?",
        "Isolates grouped by genus or phylum, each left out in turn.",
        "The recommender is built without one genus or phylum and tested on it; isolates without a taxon are counted, not dropped.",
        "Low regret on unseen groups means the advice transfers.",
        "Shows how far a recommendation can be trusted for a new organism.",
        "Holdout isolates stay locked until they are evaluated once on purpose."),
    "validation": H(
        "Does the advice still work on studies it was not built from?",
        "Isolates grouped by source study.",
        "For each study, the method is chosen from all other studies and judged only on that study.",
        "'Withheld' means there are not enough independent studies yet; it is not a failure.",
        "The fairest test of whether a recommendation generalises.",
        "A cohort with few studies cannot show this well."),
    # ------------------------------------------------------------------ Figures
    "fig-forest": H(
        "Do tools do better or worse on some kinds of isolate (species, plasmid size, reference quality) than on average?",
        "The share of plasmids reconstructed correctly (CPRR) per isolate, grouped.",
        "Each row is a group; the square is the group's CPRR minus the tool's overall CPRR, the line is its 95% interval. The diamond is the overall value.",
        "A square left of the dashed line is worse than the tool's average; right is better. A line crossing the dashed line means no clear difference.",
        "Shows where a tool is strong or weak, which an overall average hides.",
        "Groups with few plasmids have long lines; read them as hints."),
    "fig-distributions": H(
        "How the results spread across isolates, not just the average.",
        "One CPRR value per isolate and tool.",
        "Each point is one isolate. Violins or boxes show where most isolates sit; points show the individuals.",
        "A tool with a tall thin shape near 1 is consistently good; a wide shape is erratic.",
        "Two tools with the same average can behave very differently; this shows it.",
        "Groups with fewer than the minimum isolates are drawn as points only."),
    "fig-heatmap": H(
        "Every tool against every metric on one grid.",
        "The scorecard metrics and the leaderboard metrics, per tool and track.",
        "Each cell shows the value; colour runs from poor to good, with lower-is-better metrics flipped so bright always means good.",
        "Scan rows for an all-bright tool and columns for a metric nobody does well.",
        "A fast overview of strengths and weaknesses across families of metrics.",
        "Colours are relative within a column unless you choose raw values; gaps ('not measured') are not zeros."),
    "fig-pr": H(
        "The trade-off between finding plasmid sequence (recall) and not calling chromosome by mistake (precision).",
        "Plasmid bases recovered and falsely called, from tools that write a score for each call.",
        "A curve is drawn by moving a score threshold; tools without a score show their single operating point.",
        "The closer a line is to the top-right corner, the better.",
        "Shows how a tool behaves if you make it stricter or looser.",
        "If no tool wrote a curve file for a track, the figure says so and nothing is drawn."),
    "fig-ladder": H(
        "A map of how this benchmark scores a result, from raw contigs to a verified plasmid.",
        "No data; it explains the five scoring steps.",
        "Five steps: contigs, binning, ordering and orientation, the reconstructed plasmid, and checking against the reference. Each step lists the score that judges it.",
        "Click a step to see which report sections cover it.",
        "Helps a newcomer see what each score actually measures.",
        "It is a guide; the numbers are in the sections it links to."),
    "fig-landscape": H(
        "A 3D view of how accurate, how complete and how structurally faithful each result is, all at once.",
        "Per-run accuracy, completeness and structure scores.",
        "Each point is one tool on one isolate (or a tool average): across = accuracy, depth = completeness, up = structure. Structure is estimated from alignments and is "
        "not independently validated.",
        "Points near the far top corner are best on all three. Drag to rotate.",
        "Shows trade-offs, for example a tool that is accurate but incomplete.",
        "The axes are metrics, not a physical shape. A run missing any axis is listed, never drawn at zero."),
    "enterprise": H(
        "An interactive dashboard of the same results with filters, a heatmap and drill-downs.",
        "This run's measured results (nothing else).",
        "It draws the existing results in its own frame, so values never measured show 'not measured' rather than 0.",
        "Use the filters to narrow isolates, then click a cell to see the plasmid.",
        "Lets you explore without reading every table.",
        "It repeats information found elsewhere and is optional."),
    # ------------------------------------------------------------------ Plasmid maps
    "plasmid-maps": H(
        "Pictures of each real plasmid with what every tool recovered.",
        "Reference plasmid sequences and annotations, and the alignments of each tool's output.",
        "A circular map per plasmid: genes on the outside, one ring per tool showing which parts it covered, plus structure and GC content.",
        "A solid ring means the tool covered that part. Gaps mean missing parts. Hover for details.",
        "Lets you see where and how a tool failed, not just a score.",
        "A map shows coverage, not proof that the plasmid was joined in the right order."),
    "plasmid-maps-main": H(
        "The interactive maps.",
        "Truth plasmids, annotated genes and each tool's alignments.",
        "Choose a sample and plasmid. Outer ring: genes; tool rings: covered regions; markers: structural events.",
        "Click anything to open its detail tab.",
        "Shows exactly which parts of a plasmid were rebuilt.",
        "Plasmids over the size limit are shown as a note, not a map."),
    "per-plasmid-detail": H(
        "A table with one row for every real plasmid and every tool.",
        "Coverage, outcome class and bin for each plasmid and tool.",
        "Taken from the per-plasmid outputs; filter by sample, tool, outcome or repeat content.",
        "Outcome classes say whether a plasmid was recovered perfectly, split, merged or missed.",
        "Answers 'which plasmids did this tool get?' directly.",
        "Without JavaScript every row is shown."),
    "evidence-explorer": H(
        "A close-up of one truth plasmid: alignments, structural calls and annotation.",
        "Alignment blocks, structural calls and bin relationships from this run.",
        "Loaded only when opened. Identity and mapping quality are measured; read depth is not computed, so it reads 'not measured'.",
        "Pick a plasmid, then step through tools and regions.",
        "For checking a specific result in detail.",
        "It is large; use the Load now button if it has not opened."),
    "amr-placement": H(
        "Did each tool put antibiotic-resistance genes on the right plasmid?",
        "A curated list of resistance gene positions on the reference plasmids.",
        "Each gene copy is matched by position. Level 2: the bin holding it is matched to the gene's own plasmid. Level 1: it shares a replicon type. Shared or unassigned "
        "contigs form their own category.",
        "More genes at Level 2 is better. A gene on the wrong plasmid can mislead a resistance spread study.",
        "Resistance genes are the reason many people study plasmids; this tests whether a tool keeps them with the right plasmid.",
        "Only curated genes are counted."),
    "contig-layer": H(
        "A second, contig-by-contig way of scoring, shown beside the main one.",
        "Assembly contigs labelled against the reference.",
        "Each contig is labelled plasmid or chromosome and each tool's calls are scored per contig, weighted by length. Its recall denominator is defined by contigs, not "
        "by reference bases.",
        "Compare it with the main layer; big disagreements flag a scoring-choice effect.",
        "A cross-check that the ranking does not depend on one way of counting.",
        "It is never the headline."),
    # ------------------------------------------------------------------ Detailed results
    "more-metrics": H(
        "More ways to score the same results beyond the headline.",
        "The same predictions, scored with other metrics.",
        "MCC and F-beta, graded recovery, a negative control and baselines.",
        "Use a tab when the headline hides something you care about.",
        "Different users value different things: precision, recall or completeness.",
        "None of these replaces the ranking metric."),
    "scoring-additions": H(
        "Extra single-number scores: MCC, F2 and F0.5, and how often a tool returned nothing.",
        "Base-level results against the reference.",
        "MCC counts chromosome bases not called as correct rejections; it is blank on plasmid-free isolates. F2 favours recall, F0.5 favours precision. Macro averages per "
        "isolate; micro pools all bases.",
        "Higher is better. A high abstention rate means the tool often gave no answer.",
        "Shows whether a tool's rank holds under a metric that suits your needs.",
        "MCC is undefined where there are no plasmids."),
    "graded-tiers": H(
        "How much of each plasmid was recovered: half, most, or all, and circular when it should be.",
        "Per-plasmid coverage and known circularity.",
        "The share of a tool's real plasmids reaching at least 50% and at least 90% coverage, and complete-and-circular recovery where circularity is known.",
        "Higher is better at every level; the drop from 50% to 90% shows how often a tool leaves gaps.",
        "A plasmid that is 60% found is not a usable plasmid; this shows how many are really usable.",
        "Circular recovery is only measured where circular truth is known."),
    "zero-plasmid": H(
        "Does a tool wrongly invent plasmids on isolates that have none?",
        "Isolates with no true plasmid.",
        "Precision, recall and F1 are undefined here, so specificity and the chromosome bases wrongly called plasmid are reported.",
        "High specificity and few false bases are good.",
        "It is the only direct measure of false alarms.",
        "Needs plasmid-free isolates in the cohort."),
    "baselines-calibration": H(
        "How the tools compare with simple rules, and whether their confidence is honest.",
        "Two trivial baselines (a depth rule and a reference-similarity rule) and tool confidence scores.",
        "Baselines are scored like tools. Calibration (Brier score and expected error) checks whether a tool's stated confidence matches how often it is right.",
        "A tool should beat the baselines. Lower Brier and ECE mean better-calibrated.",
        "A tool that cannot beat a simple rule is not adding value.",
        "Baselines are shown only when they were run."),
    "ranking-sensitivity": H(
        "Would the ranking change under other choices, and is there enough data to say?",
        "The saved alignments and the cohort.",
        "Scoring settings are changed one at a time, power is estimated, database leakage is checked and repeat runs are compared.",
        "Stable rankings under many choices are trustworthy.",
        "Separates solid results from fragile ones.",
        "These are advisory checks."),
    "rank-robustness": H(
        "Does the order of tools change if scoring choices change?",
        "The saved alignments, re-scored under variants.",
        "Each row changes one filter, or ranks by strict precision or per-plasmid recovery, and reports Kendall tau against the baseline order.",
        "Tau near 1 means the same order. 'Top tool unchanged' says whether the leader holds.",
        "Shows if the winner depends on a technical choice.",
        "It never changes the leaderboard."),
    "power": H(
        "How big a difference between two tools this cohort could actually detect.",
        "Paired differences between tools, grouped by study.",
        "Differences are averaged within each study first. The minimum detectable difference is the smallest gap that would show up reliably.",
        "If the observed gap is smaller than the minimum detectable difference, the cohort cannot tell.",
        "Prevents confident claims from too little data.",
        "'Clusters needed' tells you how many more studies would help."),
    "database-membership": H(
        "Did a tool see the answer in its own database?",
        "Tool databases (such as plasmid reference collections) and the truth plasmids.",
        "A truth plasmid is 'in the database' when one record covers at least 95% of it at 99% identity. Scores are compared for in-database and novel plasmids.",
        "A tool much better on in-database plasmids is partly remembering, not inferring.",
        "Shows if a score will carry over to new plasmids.",
        "Not checked when no database or tool was available; the section says so."),
    "reproducibility": H(
        "If the benchmark is run again, do we get the same answer?",
        "Two or more results folders from repeat runs.",
        "Compared with the compare-runs tool: identical scores and sequences, same scores from different sequences, or moved scores.",
        "'Reproducible' is the best outcome; 'variable' means scores moved between runs.",
        "A result that cannot be repeated cannot be trusted.",
        "Needs at least two runs."),
    "replicon-recovery": H(
        "Which kinds of plasmid each tool recovers.",
        "Replicon (Inc/rep) and relaxase (MOB) labels on the truth plasmids.",
        "Recovery is tabulated by plasmid type for each tool.",
        "Look for a type with low recovery for every tool.",
        "Shows biases: tools can be good at common plasmid types and poor at others.",
        "Rare types have few examples."),
    "bin-diagnostics": H(
        "How well each tool grouped contigs into plasmid bins.",
        "Predicted bins and the truth plasmids.",
        "Bins are matched one-to-one to truth plasmids; splits, merges and contamination are counted.",
        "More matched bins, fewer splits and merges is better.",
        "Explains why a tool scores as it does.",
        "Only tools that output bins are shown."),
    "bin-diagnostics-main": H(
        "Bin counts and bin-level scores for each sample and tool.",
        "Predicted bins and truth plasmids.",
        "A split is one real plasmid spread over several bins; a merge is one bin that holds several plasmids; contaminated bins carry chromosome.",
        "Fewer splits, merges and contaminated bins is better.",
        "Shows the type of mistake.",
        "Repeats inside plasmids make some splits unavoidable."),
    "bin-quality": H(
        "Would a laboratory trust each bin?",
        "Bin completeness and contamination against the truth.",
        "Bins are put into quality tiers by thresholds on both.",
        "High-tier bins are those you could use directly.",
        "A practical test for surveillance work.",
        "A secondary measure, not the endpoint."),
    "plasmid-outcomes": H(
        "What happened to each real plasmid: perfect, fragmented, merged, partial or missed.",
        "Each truth plasmid and the bin holding most of it.",
        "Perfect: its bin is precise and complete enough. Fragmented: another bin holds a share. Merged: its bin also holds another plasmid. Missed: nothing reached the bar.",
        "More 'perfect' is better. A high 'merged' count means the tool lumps plasmids together.",
        "Gives a plain count of successes and failure types.",
        "Thresholds are set in the configuration."),
    "learn-agreement": H(
        "A second opinion on bin quality using an independent definition.",
        "Predicted bins against the truth.",
        "Best-match precision, recall and F1, and a dissimilarity score that separates splits from joins, re-implemented from a published method.",
        "Agreement with the main score is reassuring.",
        "Checks that the ranking does not depend on one definition.",
        "It never changes the ranking."),
    "scores": H(
        "Every score for every tool and every isolate in one place.",
        "The full score table.",
        "Each row is one tool on one isolate; filters narrow the rows and you can export what you see.",
        "Sort and filter to find an isolate where a tool failed.",
        "The ground truth of the report; every other number is derived from it.",
        "Unavailable values are shown as '-', never as zero."),
    "scores-main": H(
        "The full table of scores.",
        "One row per tool and isolate.",
        "Filter by performance, tool or cohort information. Predicted bases are split into unambiguous, ambiguous and unmapped.",
        "Use it to look up an exact value.",
        "Lets you verify any figure.",
        "Resistance and circular recovery need curated truth annotations."),
    "tools": H(
        "Results grouped by tool.",
        "The score table.",
        "Open a tool to see its scores on every isolate, ordered by F1.",
        "Look for isolates far below the tool's average.",
        "Shows whether a tool is consistently good or only good on some isolates.",
        "A tool's average hides its bad cases."),
    "samples": H(
        "Results grouped by isolate.",
        "The score table.",
        "Open an isolate to compare every tool side by side.",
        "Look for isolates where every tool struggles; they are hard cases.",
        "Shows which isolates drive the differences.",
        "One hard isolate can pull down every average."),
    # ------------------------------------------------------------------ Data and reference quality
    "headline-design": H(
        "What the ranking rests on: the samples, species and the quality of the reference.",
        "Sample sheet, truth assembly details and the pre-registered settings.",
        "Truth assemblies are graded in tiers by how independent and checked they are. Alternative labelling schemes are re-ranked as sensitivity checks.",
        "Prefer Tier 1 truth. A ranking resting on lower tiers is weaker.",
        "A ranking is only as good as its reference standard.",
        "Settings fixed in advance cannot be tuned after seeing results."),
    "headline-design-main": H(
        "The design in one table: reference standard, truth provenance, tiers and species balance.",
        "Truth assembly provenance and the sample sheet.",
        "Tiers: 1 = long-read-first truth independent of the benchmark reads with checked labels; 2 = long-read-first truth that fails a tier-1 condition.",
        "Check the tier and species basis for your track.",
        "Shows how trustworthy and balanced the headline is.",
        "Tiers describe the reference, not the tool."),
    "prereg": H(
        "The scoring decisions that were fixed before the results were seen.",
        "The pre-registration file and this run's settings.",
        "The file is hashed and this run's settings are checked against it.",
        "'Frozen' and matching means no changes after the fact.",
        "Protects against tuning the scoring to favour a tool.",
        "If it says 'not frozen', the protection is not in force."),
    "truth-label-audit": H(
        "Are the plasmid and chromosome labels in the truth actually right?",
        "Truth sequences and their replicon and MOB evidence.",
        "Each label is compared with replicon, relaxase and related evidence.",
        "'Consistent' is good; conflicts are flagged.",
        "Wrong truth gives wrong scores.",
        "It does not change a score."),
    "label-schemes": H(
        "How the truth was labelled, and what happens if it were labelled differently.",
        "Three labelling schemes: the pre-registered NCBI scheme, one that calls every non-main replicon a plasmid, and an evidence-checked scheme.",
        "The ranking is repeated under each scheme as a sensitivity analysis.",
        "A stable ranking across schemes is reassuring.",
        "Shows if the winner depends on labelling choices.",
        "The headline stays on the pre-registered scheme."),
    "orthogonal-evidence": H(
        "Independent laboratory evidence, if any was supplied.",
        "Optional laboratory or independent-technology results.",
        "Recorded next to the run; it never alters a score.",
        "'None supplied' is normal.",
        "Adds confidence when available: an independent measurement agreeing with a prediction is stronger than a computed score alone.",
        "It is optional, and it never changes a benchmark score."),
    "learn-truthqc": H(
        "Which parts of the truth are hard: repeats and unusual read depth.",
        "The reference sequences and, if available, read depth.",
        "k-mer repeat content flags repeat-rich plasmids; windows with depth far from the median flag collapsed repeats or misjoins.",
        "Repeat-rich plasmids are harder to separate.",
        "Explains why some plasmids are missed by every tool.",
        "Advisory; it edits nothing."),
    "assembly-quality": H(
        "Was each short-read assembly good enough to start from?",
        "The assembly of each isolate.",
        "Size, contig count, N50 and GC are computed and a quality gate is applied.",
        "'Passed' means the assembly is usable.",
        "Bad assemblies make every tool look bad.",
        "Failing the gate does not remove an isolate by itself."),
    "assembly-quality-main": H(
        "The size and quality gate for each assembly.",
        "The short-read assembly of each isolate (its contigs and their statistics).",
        "Size, contigs, long contigs, N50 and GC are tabulated with a pass/fail reason.",
        "Read the reason when an isolate fails.",
        "Flags isolates where poor assembly rather than a tool is the cause.",
        "Thresholds are in the configuration."),
    "learn-adequacy": H(
        "Does the assembly even contain the plasmids?",
        "The isolate's own assembly and the truth plasmids.",
        "The share of each truth plasmid present in the assembly, and the share of contig bases that are chimeric or unplaced.",
        "'Adequate' means a tool had a chance to find the plasmid.",
        "No tool can recover what the assembly never contained.",
        "A low value is about the data, not the tool."),
    "cohort-qc": H(
        "Checks on the set of isolates itself.",
        "Assembly statistics, sample metadata and difficulty signals.",
        "Outliers are flagged statistically; missing metadata is listed; difficulty comes from the truth.",
        "Flagged isolates may need a second look.",
        "A skewed cohort gives a skewed ranking.",
        "A flag is a prompt to check, not an exclusion."),
    "cohort-qc-main": H(
        "Isolates that are statistical outliers.",
        "N50, contig count, GC% and plasmid count per isolate.",
        "A robust outlier test (modified z-score) per measure.",
        "An outlier is unusual compared with the rest.",
        "Spots odd isolates early.",
        "Not rule-based; a flagged isolate may be fine."),
    "metadata-completeness": H(
        "Which isolates lack information, and what that changes.",
        "The sample sheet.",
        "Missing fields are listed with the analysis each one affects.",
        "Missing study or species changes how an isolate is grouped.",
        "Explains odd groupings.",
        "Isolates still run without metadata."),
    "isolate-difficulty": H(
        "How hard each isolate is to separate into plasmid and chromosome, regardless of tool.",
        "Assembly graph and truth-derived signals.",
        "Features like graph dead ends and plasmid-to-chromosome depth ratio.",
        "Higher difficulty means every tool should struggle.",
        "Helps explain low scores.",
        "Never a tool measure and not used in recommendations. Off by default."),
    "health": H(
        "How every run ended and what it cost.",
        "Execution status, runtime and memory records.",
        "Counted from the run records.",
        "Failed runs and their reasons are the ones to read.",
        "A tool that often fails is a poor choice even if it is accurate when it works.",
        "Infrastructure failures say nothing about the tool."),
    "health-main": H(
        "One row per run.",
        "Status, runtime, peak memory and reason.",
        "Elapsed wall-clock seconds and peak memory when the machine recorded them.",
        "Sort to find slow or failed runs.",
        "Reproduces the status of any run.",
        "A failed tool run counts as F1 = 0 in the ranking."),
    "outcome-states": H(
        "A count of every kind of run ending, per tool, with the most common reason.",
        "The run records written by the pipeline: the status and exit code of every tool run.",
        "States: completed, reused, failed (tool), failed (resource), infrastructure failure, not applicable, retried.",
        "Read the reason column.",
        "Separates tool faults from machine faults.",
        "Infrastructure failures are never scored."),
    "performance": H(
        "Speed and memory.",
        "Runtime and memory records.",
        "Medians of elapsed seconds, memory and success rate; cost per recovered plasmid.",
        "Lower time and memory is better.",
        "Informs whether a tool is practical at scale.",
        "Depends on the computer used."),
    # ------------------------------------------------------------------ Methods and limits
    "metric-framework": H(
        "The definitions of the metrics used.",
        "None; it explains the metrics.",
        "Two tasks are scored separately: classification (is a contig plasmid?) and reconstruction (which plasmid?). Metrics include F1, MCC and binning F1.",
        "Use it as a reference.",
        "Makes sure numbers are not compared across different tasks.",
        "Labels for short contigs follow stated rules."),
    "interpretation-limits": H(
        "What the results support and what they do not.",
        "The design, the reference tiers and validation coverage.",
        "A plain statement of valid and invalid claims.",
        "Read before quoting a number.",
        "Prevents over-claiming: it keeps a methods benchmark from being quoted as proof about patients or outbreaks.",
        "A methods benchmark does not answer surveillance questions."),
    "interpretation-limits-main": H(
        "A plain list of what these results do and do not show, and what the key words mean.",
        "The study design: which reference tiers, how many independent studies, which tracks.",
        "Written from the run's own facts, so the list changes when the cohort changes.",
        "Use only the claims listed as supported when you quote the results; treat the rest as open questions.",
        "A benchmark of reconstruction tools answers a methods question (which tool rebuilds plasmids best here). It does not by itself answer surveillance or lineage "
        "questions, and this keeps readers from stretching it.",
        "Supported does not mean proven for every isolate or organism."),
    "validity": H(
        "Which conclusions were actually tested on data held back from the choice, and which are extrapolations.",
        "Reference tiers, the number of independent studies and how much of the cohort was evaluated.",
        "Each claim (for example 'the ranking holds for these isolates') is marked validated when it was measured on held-out data here, and extrapolated when it was not.",
        "'Extrapolated' means do not rely on it yet. 'Validated' means it was checked here.",
        "Sets honest expectations for how far a result can be generalised.",
        "More independent studies are needed to move a claim from extrapolated to validated."),
    "method": H(
        "How a result is turned into a score, step by step, so anyone could repeat it.",
        "The complete reference assemblies (the truth) and each tool's predicted plasmid sequences.",
        "Every sequence in the truth is labelled plasmid or chromosome from the NCBI sequence report. Each tool's output is aligned to the truth; the aligned bases are "
        "counted as correct, wrong or missing, and those counts become precision, recall, F1 and the other metrics.",
        "Follow the steps in order to see where a number comes from; the same rules apply to every tool.",
        "It lets you check that the comparison was fair, and reproduce any number yourself.",
        "Choices such as the alignment filters are fixed in advance (see Pre-registration) and tested for their effect in the sensitivity section."),
    "keys": H(
        "A searchable glossary: every term used in the report, what it measures and why it matters.",
        "No data; it is a dictionary of the report's own terms.",
        "Each entry is the same text that pops up when you hover over the term elsewhere in the report.",
        "Type part of a term in the filter box to find it, then read 'what it measures' and 'why it matters'.",
        "Plasmid benchmarking uses many abbreviations (F1, CPRR, MCC, N50). This is the place to look them up.",
        "Colour bands such as 'High F1' are visual aids, not acceptance thresholds."),
    # ------------------------------------------------------------------ Scorecard (exploratory)
    "scorecard": H(
        "An exploratory score-sheet of every tool against 17 metrics.",
        "Scores for accuracy, completeness, structure, biology and performance.",
        "Each metric becomes 0-100 using example thresholds and weights; the overall score is the weighted mean of the metrics that could be scored.",
        "Bands: Excellent, Good, Moderate, Poor. Compare overall score and the share of weight scored.",
        "A single glance at breadth of performance.",
        "Not the ranking; thresholds are mostly proposed, not standards."),
    "scorecard-main": H(
        "The tools-by-metrics table.",
        "Per-tool metric values.",
        "Value, band and score per cell. The isolate filter re-scores on one isolate.",
        "Look across a row for a profile.",
        "Shows strengths and weaknesses.",
        "Metrics that cannot be computed are 'not available' and their weight is excluded."),
    "scorecard-scenarios": H(
        "The scorecard repeated for kinds of isolate.",
        "Isolates tagged by scenario.",
        "Scenarios overlap; fewer than five isolates is flagged underpowered.",
        "Read underpowered rows as illustration.",
        "A tool should not look good by meeting only easy isolates.",
        "Runtime, memory and success are not scored per scenario."),
    "scenarios": H(
        "Performance by kind of isolate, counting each isolate once.",
        "Scenario tags from sample facts.",
        "Each isolate falls into the first matching scenario: plasmid-free, challenging, complex, annotated, simple.",
        "Compare a tool's results across scenarios.",
        "Shows where performance drops.",
        "Small groups are flagged."),
    "composite": H(
        "A five-dimension composite score and how it changes with the weights.",
        "Accuracy, completeness, structure, biology and performance scores.",
        "Each is scored 0-100 and combined with proposed weights (30, 20, 25, 15, 10).",
        "Check whether the order changes when weights change.",
        "Shows the effect of value choices.",
        "Not the benchmark ranking."),
    "scorecard-definitions": H(
        "The weights and thresholds behind the scorecard.",
        "The scorecard configuration.",
        "Score is piecewise linear through excellent 100, good 85, moderate 60.",
        "Status 'fixed' is a stated definition, 'proposed' is open to change.",
        "So thresholds can be challenged.",
        "'Undefined' metrics cannot be graded."),
    # ------------------------------------------------------------------ Appendix
    "appendix-reference": H(
        "The detailed tables behind the scorecard and the structure checks, for anyone who wants to trace a number back to its source.",
        "Alignments of each tool's output to the truth, and the optional QUAST comparison.",
        "Each tab is a complete section with its own downloads; the scorecard takes its accuracy and feature values from these tables.",
        "Open a tab when a scorecard cell surprises you and you want to see the rows it came from.",
        "It gives a full audit trail: nothing in the scorecard is a black box.",
        "Reference material; the ranking does not depend on it."),
    "accuracy-dimension": H(
        "Are the bases a tool recovered correct?",
        "Alignments of tool output to the truth.",
        "Identity, mismatches and indels in the aligned parts, plus the share of the plasmid missing.",
        "Higher identity and less missing is better.",
        "Coverage alone can hide wrong bases.",
        "Only aligned bases are judged."),
    "feature-preservation": H(
        "Do genes and functional elements survive in order?",
        "Truth features projected through the alignments.",
        "Full length = at least 95% covered; truncated = partly covered; missed = not covered. NGOC is the share of adjacent genes kept in order.",
        "Higher full-length rate is better.",
        "A plasmid is only useful if its genes work.",
        "Gene order is estimated from alignments and not independently validated."),
    "quast-diagnostics": H(
        "An extra structural check using QUAST.",
        "Predicted plasmid sequences and the truth.",
        "Run three ways: all truth plasmids, one at a time and chromosome only.",
        "High chromosome genome fraction means chromosome leaked into the call.",
        "A second, independent way to see structural errors (misjoins, duplications, chromosome leaking into a plasmid call).",
        "It is an optional check and shows only when QUAST was run."),
    "files": H(
        "Every file the run produced, with a description of each.",
        "The results folder.",
        "Listed as a tree with size, date, producer and where it is shown.",
        "Open a folder, then click a file to download.",
        "Lets you reuse the raw results.",
        "Large files are not shown inline."),
    # ------------------------------------------------------------------ appear only when the data exist
    "excluded-replicons": H(
        "Replicons the evidence-checked labelling excluded as ambiguous.",
        "The labelling scheme results.",
        "Replicons where the sources conflicted were left out of that scheme.",
        "Few excluded is good.",
        "Shows the truth that could not be settled.",
        "Appears only when something was excluded."),
    "learn-copynumber": H(
        "Estimated copy number of each plasmid.",
        "Assembly read-depth headers and matched bins.",
        "Plasmid depth relative to chromosome depth.",
        "Higher ratio means more copies.",
        "Copy number relates to plasmid behaviour.",
        "Needs depth headers; otherwise listed as not run."),
    "extended": H(
        "Optional extended analyses and next steps.",
        "Depth and read-quality ladders.",
        "Shown only when results exist.",
        "Read the status lines to see which extra analyses ran.",
        "Gives extra context on how read depth and read quality affect results.",
        "It is optional and appears only when its results exist."),
}
