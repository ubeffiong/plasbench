#!/usr/bin/env python3
"""Build the self-contained HTML dashboard emitted after benchmark aggregation."""

import argparse
import re
import base64
import csv
import datetime as dt
import html
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote
from plasbench_common import display_tool_name  # noqa: E402


def info_script():
    """Positions the info popovers (hover, focus, click to pin, Esc); see python/report_info.py."""
    return report_asset("info_script.html")


def report_asset(name):
    """Static CSS/JS/HTML fragment shipped in assets/report/ (kept out of the code so this
    module holds logic, not 1,000+ lines of embedded web assets)."""
    path = Path(__file__).resolve().parent.parent / "assets" / "report" / name
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()

# Placeholder swapped in for any case-insensitive "</script" match found in a
# vendored document before it is wrapped in an outer <script type='text/template'>
# tag, then swapped back to a literal (always-lowercase) closing tag by the
# frame-loading script. Plain text so it survives HTML text-node parsing
# untouched, unlike a NUL or other control character.
SCRIPT_END_SENTINEL = "PB_SCRIPT_END_7f21ac93"


def lazy_frame_js(doc_id):
    """JavaScript (an expression statement list, no surrounding function) defining `lazyFrame(f)` for the iframe `f` whose document is the text of
    <script id=doc_id type='text/template'>.

    The two explorers carry 7 to 8 MB documents. Writing them into srcdoc at page load made the browser run both dashboards even though they sit in a
    view that is hidden when the page opens. The document stays in the page (the report is one offline file), but it is written into the frame only when the
    frame first becomes visible (an IntersectionObserver, with a margin so it starts just before), when the reader presses Load now, when the page is
    printed or exported to PDF (?print=1 and beforeprint load it eagerly, as before), or at once where IntersectionObserver does not exist.
    `f.pbLoad()` loads it on demand (a link that jumps to the explorer can call it).
    """
    return ("const lazyFrame=f=>{if(!f)return;const note=f.parentElement&&f.parentElement.querySelector('.pb-lazy-note');"
            "const load=()=>{if(f.dataset.pbLoaded)return;f.dataset.pbLoaded='1';"
            f"const raw=document.getElementById('{doc_id}').textContent;"
            f"f.srcdoc=raw.split('{SCRIPT_END_SENTINEL}').join('</scr'+'ipt');if(note)note.hidden=true}};"
            "f.pbLoad=load;const btn=note&&note.querySelector('button');if(btn)btn.addEventListener('click',load);"
            "if(/[?&]print(=|&|$)/.test(location.search)||!('IntersectionObserver' in window)){load();return}"
            "window.addEventListener('beforeprint',load);"
            "const io=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting)){io.disconnect();load()}},{rootMargin:'400px 0px'});"
            "io.observe(f)};")


def lazy_frame_note(what):
    """The placeholder shown in the panel until the frame loads."""
    return (f"<div class='pb-lazy-note' style='padding:18px 16px;font:14px Arial,sans-serif;color:#314238;background:#f6f8f6;border-bottom:1px solid #d5ddd6'>"
            f"The {what} loads when this section is opened, to keep the report quick to open. <button type='button' style='margin-left:8px;font:600 12px Arial,sans-serif;"
            "padding:4px 12px;border:1px solid #1f6f56;border-radius:14px;background:#fff;color:#14231c;cursor:pointer'>Load now</button> "
            "<noscript>(This section needs JavaScript.)</noscript></div>")


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


ANALYSIS_TRACKS = ("short_read", "long_read", "hybrid")


def read_track_leaderboards(leaderboard_path):
    """Read the per-track leaderboards aggregation writes beside the pooled one.

    aggregate_results.py emits <prefix>.leaderboard.tsv (every tool, pooled)
    AND <prefix>.<track>.leaderboard.tsv per declared track, precisely so track
    claims are never mixed. Ranking a long-read tool against a short-read one
    compares different inputs on the same isolates, which is exactly the
    comparison docs/METHODS.md says must not be made -- so the report ranks
    within each track and never pools. Returns {} when the per-track files are
    absent (an older results directory), and the caller falls back to the
    pooled file it was given.
    """
    path = Path(leaderboard_path)
    if not path.name.endswith(".leaderboard.tsv"):
        return {}
    prefix = path.name[: -len(".leaderboard.tsv")]
    found = {}
    for track in ANALYSIS_TRACKS:
        candidate = path.with_name(f"{prefix}.{track}.leaderboard.tsv")
        if candidate.is_file():
            rows = read_tsv(candidate)
            if rows:
                found[track] = rows
    return found


def read_sample_metadata(path):
    if not path or not Path(path).is_file():
        return {}
    return {row["sample_id"]: row for row in read_tsv(path) if row.get("sample_id")}


def read_difficulty_features(data_dir, samples):
    """sample -> difficulty_features.tsv row, for every sample that has one.

    difficulty_features.tsv (python/compute_difficulty_features.py) lives
    under DATA_DIR/<sample>/, not RESULTS_DIR -- the only per-sample file
    this report reads from there, since every other input lives under
    RESULTS_DIR or is the sample sheet itself. Off by default
    (RUN_DIFFICULTY_FEATURES=0), so an absent --data-dir, or a sample with
    no difficulty_features.tsv at all, is the normal case, not an error.
    """
    if not data_dir:
        return {}
    features = {}
    for sample in samples:
        path = Path(data_dir) / sample / "difficulty_features.tsv"
        if not path.is_file():
            continue
        rows = read_tsv(path)
        if rows:
            features[sample] = rows[0]
    return features


# One definition per term, used in three places: the keys section renders from
# it, every occurrence of the term in the report is annotated from it, and the
# guided findings quote it. Adding a term here makes it explained everywhere.
#
# "what" is the measurement. "why" is the reason a reader should care, which is
# the half a label can never carry and the half that was missing.
GLOSSARY = {
    "Base F1": {
        "what": "Harmonic mean of base-level precision and recall, 0 to 1.",
        "why": "It is a single number for two different failures -- claiming "
               "sequence that is not plasmid, and missing sequence that is. A "
               "method can score well on either alone; F1 only rises when both "
               "hold. It is not a measure of structural correctness.",
    },
    "Perfect reference recovery": {
        "what": "Rate of scored samples with F1 and plasmid recall of 1, and no ambiguous, unmapped, or off-truth predicted bases.",
        "why": "It identifies fully supported recovery against this reference, while remaining stricter than a high average F1. It does not prove nucleotide identity or circular closure.",
    },
    "Strict reconstruction": {
        "what": "Perfect reference recovery plus perfect available bin diagnostics, with no split, merge, contamination, or repeat-ambiguity events.",
        "why": "It is the stronger structural screen when a tool provides validated bins. It is withheld, not treated as zero, for tools without bin evidence.",
    },
    "Base precision": {
        "what": "TP / (TP + FP) over reference bases.",
        "why": "How much of what the method called plasmid really is plasmid. "
               "Low precision means chromosome sequence in the answer.",
    },
    "Base recall": {
        "what": "TP / (TP + FN) over reference bases. Also called completeness.",
        "why": "How much of the true plasmid was recovered. Low recall means "
               "the plasmid is there but the method did not find it.",
    },
    "Completeness": {
        "what": "Fraction of one truth plasmid's bases covered by the prediction.",
        "why": "Recall stated per plasmid rather than per sample, so a large "
               "recovered plasmid cannot hide a small missed one.",
    },
    "Purity": {
        "what": "Fraction of a predicted bin's aligned bases that belong to its "
                "matched truth plasmid.",
        "why": "A bin can be complete and still be wrong, if it also carries "
               "chromosome or a second plasmid. Measured per bin, not per plasmid.",
    },
    "Plasmid recall": {
        "what": "Fraction of truth plasmids recovered above the configured "
                "completeness threshold.",
        "why": "Counts plasmids, not bases, so recovering one large replicon "
               "does not compensate for missing three small ones.",
    },
    "Structural concordance": {
        "what": "Collinear aligned bases over all aligned bases, from the "
                "alignment blocks alone.",
        "why": "A reconstruction can contain every correct base in the wrong "
               "order. This is the only number here that notices, and it is a "
               "diagnostic proxy: it is not validated against a closed genome.",
    },
    "Split": {
        "what": "One truth plasmid represented by more than one predicted bin "
                "from the same method.",
        "why": "The sequence was found but not assembled into one unit, so a "
               "high completeness can still mean an unusable reconstruction.",
    },
    "Merge": {
        "what": "One predicted bin carrying high-completeness evidence for more "
                "than one truth plasmid.",
        "why": "Two replicons fused into one answer. Downstream this reads as a "
               "single plasmid that never existed.",
    },
    "Chromosomal contamination": {
        "what": "Chromosome-reference bases covered by a predicted-plasmid "
                "alignment, as a fraction of all truth-mapped bases.",
        "why": "The most consequential error for AMR work: a resistance gene "
               "called plasmid-borne when it is chromosomal changes the "
               "conclusion about transmissibility.",
    },
    "Unmapped predicted bp": {
        "what": "Predicted bases with no alignment to any labelled reference.",
        "why": "Reported on its own rather than counted as a false positive, "
               "because the reference cannot say whether it is wrong or absent "
               "from the truth set.",
    },
    "TP bp": {"what": "Plasmid-reference bases covered by a predicted-plasmid alignment.",
              "why": "The numerator of both precision and recall."},
    "FP bp": {"what": "Chromosome-reference bases covered by a predicted-plasmid alignment.",
              "why": "Chromosomal contamination, counted in bases."},
    "FN bp": {"what": "True plasmid-reference bases no predicted alignment covers.",
              "why": "Sequence the method missed."},
    "AMR recovery": {
        "what": "Fraction of curated AMR genes recovered above the configured threshold.",
        "why": "Only available when curated AMR truth was supplied; otherwise it "
               "reads as unavailable rather than zero.",
    },
    "Circular truth recovery": {
        "what": "Fraction of circular reference plasmids recovered above the threshold.",
        "why": "It does not establish that the predicted sequence is closed. "
               "Nothing in this report does.",
    },
    "Collinear fraction": {
        "what": "Aligned bases that keep reference order and orientation, over "
                "all aligned bases.",
        "why": "The quantity behind structural concordance.",
    },
    "Bin F1": {
        "what": "Harmonic mean of bin precision and bin recall, over predicted bins.",
        "why": "Base F1 asks whether the right bases were called. Bin F1 asks "
               "whether they were grouped into the right plasmids.",
    },
    "PR-AUC": {
        "what": "Area under the precision-recall curve, swept across every "
                "distinct probability threshold an ML classifier emits.",
        "why": "F1 fixes the tool's own default threshold. PR-AUC asks how good "
               "the tool's underlying ranking is across every threshold, "
               "showing whether a different cutoff would change its apparent "
               "performance. Only available for tools that expose a per-record "
               "probability (adapters/SCORES.md); absent, not zero, otherwise.",
    },
    "Significant vs runner-up": {
        "what": "Whether the top-ranked tool's F1 advantage over the second-ranked "
                "tool clears a paired, shared-sample, sign-flip permutation test "
                "(Holm-adjusted p < 0.05, at least 5 shared samples).",
        "why": "A leaderboard rank alone cannot say whether a gap is real or just "
               "sample-to-sample noise. This is the same test behind the Paired "
               "tool comparisons table below, applied specifically to the winner "
               "versus its closest competitor. \"Not assessed\" means too few "
               "shared samples existed for the test to run at all -- never read "
               "that as a negative result.",
    },
    "Mean NMI": {
        "what": "Normalized Mutual Information between a tool's predicted bins "
                "and the true plasmids, bp-weighted, over a universe that "
                "includes an unassigned bucket (true-plasmid bp no bin covers) "
                "and a chromosome bucket (chromosome bp a bin wrongly claims).",
        "why": "Bin F1 asks whether individual bins matched a truth plasmid "
               "closely enough. NMI is supplementary: it scores the whole "
               "partition at once, so it can surface a tool that merges several "
               "plasmids into one bin or splits one plasmid across many, even "
               "when a lenient per-bin match would still look reasonable. Read "
               "it alongside Mean VI, not alone: NMI collapses to 0 for BOTH a "
               "genuinely random assignment and a single giant over-merged bin, "
               "and only VI's unnormalized scale tells those two apart.",
    },
    "Mean VI": {
        "what": "Variation of Information between a tool's predicted bins and "
                "the true plasmids, in nats, over the same bp-weighted universe "
                "as NMI. 0 is a perfect partition; there is no fixed upper bound.",
        "why": "NMI is normalized to [0, 1] and can look identical for very "
               "different failure modes. VI's unnormalized scale distinguishes "
               "them -- a merged bin (a smaller information loss) reads as a "
               "lower VI than a truly independent, random assignment, even when "
               "both give NMI = 0. Never a replacement for Bin F1 or the split/"
               "merge/contamination counts; always supplementary.",
    },
    "Zero-plasmid specificity": {
        "what": "For isolates with NO true plasmid only: 1 minus the fraction of "
                "that isolate's chromosome bases a tool wrongly called plasmid.",
        "why": "Precision and recall are undefined on a plasmid-free isolate (there "
               "is nothing to recover, and a tool that predicts nothing gets a "
               "correct abstention, not a score of zero). These isolates are "
               "still valuable: they are the only ones that directly measure a "
               "tool's false-positive behavior. A specificity of 1.0 means the "
               "tool correctly called the whole chromosome not-plasmid; lower "
               "values mean real chromosomal sequence was misclassified.",
    },
    "Recall ≥50% complete": {
        "what": "Fraction of a tool's true plasmids that are at least half covered "
                "by its own predicted sequence, per isolate, averaged across isolates.",
        "why": "An intermediate band between total failure and perfect recovery: a "
               "plasmid the tool got half of is a very different outcome from one "
               "it missed entirely, but Mean plasmid recall's single configured "
               "threshold cannot show that distinction on its own. Supplementary "
               "only -- never a replacement for Mean F1 or Mean plasmid recall.",
    },
    "Recall ≥90% complete": {
        "what": "Fraction of a tool's true plasmids that are at least 90% covered "
                "by its own predicted sequence, per isolate, averaged across isolates.",
        "why": "A stricter band than the ≥50% one, closer to (but not the same as) "
               "Perfect reference recovery in the main ranking table -- shows how "
               "many plasmids a tool nearly finished, not just started. "
               "Supplementary only -- never a replacement for Mean F1.",
    },
    "GFA dead-end count": {
        "what": "The isolate's own assembly graph dead-end count "
                "(rrwick/GFA-dead-end-counter), a direct fragmentation signal.",
        "why": "A more fragmented graph is intrinsically harder for every tool to "
               "correctly resolve into complete plasmid/chromosome sequences, not "
               "just a weak one -- this describes the ISOLATE, never a tool's own "
               "performance on it. Only available with RUN_DIFFICULTY_FEATURES=1 "
               "and an assembly graph.",
    },
    "Plasmid/chromosome depth ratio": {
        "what": "Median plasmid-contig read depth divided by median "
                "chromosome-contig read depth, from this isolate's own truth "
                "reference and short reads.",
        "why": "A very low or very high depth ratio can make plasmid-vs-chromosome "
               "separation intrinsically harder (e.g. a low-copy plasmid barely "
               "distinguishable from chromosomal depth) -- a difficulty signal "
               "about the isolate, never a tool-performance measure.",
    },
    "Plasmid/chromosome Mash distance": {
        "what": "The MINIMUM Mash (k-mer) distance between this isolate's own "
                "truth plasmid sequence(s) and its own truth chromosome.",
        "why": "A plasmid sharing many k-mers with its own chromosome (shared IS "
               "elements, integrated regions) is intrinsically harder to "
               "correctly separate for every tool -- the minimum across a "
               "multi-plasmid isolate is reported, since the most "
               "chromosome-similar plasmid is the harder case to flag.",
    },
    "Complete + circular recall": {
        "what": "Fraction of a tool's CIRCULAR true plasmids that are essentially "
                "fully covered by its own predicted sequence -- the strictest "
                "per-plasmid completeness band this report computes.",
        "why": "Only defined for isolates whose circular truth is actually known "
               "(score_plasmids.py's --circular-plasmids); shown as 'not assessed', "
               "never a fabricated 0, when that evidence is unavailable. Distinct "
               "from the whole-sample Perfect reference recovery/Strict "
               "reconstruction labels in the main table, which score every "
               "predicted base across the whole sample, not one plasmid at a time.",
    },
    "CPRR": {
        "what": "Correct plasmid reconstruction rate: the share of truth plasmids reconstructed correctly, meaning matched to a bin, "
                "coverage at least 0.95, that bin at least 95% from this plasmid, not split, and (where base-level metrics are valid) "
                "alignment identity at least 0.99. Pooled over plasmids with a cluster bootstrap interval; the isolate-level form "
                "(correct plasmids over truth plasmids of each isolate) is the ranking metric on the long-read and hybrid tracks.",
        "why": "It asks the question a laboratory asks: did the tool give me the whole plasmid, cleanly? Base F1 can stay high "
               "while a small plasmid is missed or a bin is split. The thresholds are pre-specified and not tuned.",
    },
    "Length-weighted binning F1": {
        "what": "F1 of bases placed in the correct bin, after a one-to-one match between predicted bins and truth plasmids; "
                "precision and recall are weighted by sequence length.",
        "why": "It is the short-read reconstruction ranking score (primary endpoint), so it differs from Base F1, which only asks "
               "whether a base is called plasmid at all.",
    },
    "MCC": {
        "what": "Matthews correlation coefficient of the plasmid versus chromosome call, -1 to 1, counted per contig or weighted by contig length.",
        "why": "Plasmid contigs are a small minority, so accuracy and F1 can look good for a tool that calls almost nothing; "
               "MCC stays near 0 for a rule that does no better than chance.",
    },
    "F2 and F0.5": {
        "what": "F-beta scores at the base level: F2 weights recall twice as much as precision, F0.5 weights precision twice as much as recall.",
        "why": "Which error is worse depends on the use: missing a resistance plasmid (favour F2) or reporting chromosome as plasmid (favour F0.5).",
    },
    "Scorecard score": {
        "what": "A 0 to 100 score for one metric, piecewise linear through the thresholds of config/scorecard.tsv (excellent 100, good 85, "
                "moderate 60, floor 0), clamped; the overall is the weighted mean of the metrics that could be scored, with the weights renormalised.",
        "why": "It is another view of the same results, never the ranking, and its thresholds are mostly proposed rather than standards.",
    },
    "Scorecard band": {
        "what": "Excellent, good, moderate or poor, by the metric's own thresholds (a value on an edge takes the better band); "
                "overall bands are 90 or more excellent, 75 or more good, 55 or more moderate, otherwise poor.",
        "why": "It is the one band vocabulary of the scorecard. The grade A to D in the Summary and the High, Medium and Low "
               "F1 colours are separate, simpler readings and are not the same bands.",
    },
    "Scored weight share": {
        "what": "The weight of the scorecard metrics that could be scored, divided by the total weight of 100. A share below 0.5 is marked provisional.",
        "why": "A metric that cannot be scored is left out, never counted as zero, so the overall says how much of the scorecard it rests on. "
               "SNP concordance and structural variant F1 have no bands, so the share is at most 0.83.",
    },
    "NGOC": {
        "what": "Neighbouring gene order conservation: the share of adjacent feature pairs in the reference that are still adjacent, "
                "in the same orientation, on the same predicted record.",
        "why": "It shows whether genes and landmarks stay in order, which base-level scores cannot. With landmark features only it is "
               "landmark-order conservation; the feature count says which. Alignment-derived and not validated.",
    },
    "Outcome states": {
        "what": "How every run ended: completed, reused, failed (tool), failed (resource: timeout or out-of-memory kill), "
                "infrastructure failure (the container or command never started, or the disk was full) or not applicable (skipped).",
        "why": "A failed run on a plasmid-bearing isolate scores F1 = 0 for that tool; resource failures score 0 by default; an infrastructure "
               "failure says nothing about the tool, is never scored and should be rerun.",
    },
}

# Terms whose label in the interface differs from the glossary key.
GLOSSARY_ALIASES = {
    "F1": "Base F1", "Mean F1": "Base F1", "Median F1": "Base F1",
    "Precision": "Base precision", "Mean precision": "Base precision",
    "Recall": "Base recall", "Mean base recall": "Base recall",
    "Struct. Concord.": "Structural concordance",
    "Split events": "Split", "Merge events": "Merge",
    "Contamination fraction": "Chromosomal contamination",
    "Mean plasmid recall": "Plasmid recall",
    "Mean PR-AUC": "PR-AUC",
    "Perfect reference recovery": "Perfect reference recovery",
    "Strict reconstruction": "Strict reconstruction",
}


def glossary_tooltip(term):
    """The full explanation, for a title attribute."""
    entry = GLOSSARY.get(term)
    if not entry:
        return ""
    return f"{term}. {entry['what']} Why it matters: {entry['why']}"


def glossary_section():
    """Render the keys section from the single glossary."""
    rows = "".join(
        f"<div class='term-card'><h3>{esc(term)}</h3>"
        f"<p class='what'>{esc(entry['what'])}</p>"
        f"<p class='why'><strong>Why it matters.</strong> {esc(entry['why'])}</p></div>"
        for term, entry in GLOSSARY.items())
    return rows


# Grade bands. Stated here rather than buried in the renderer, because a grade
# is an opinion and the reader is entitled to see the rule that produced it.
GRADE_BANDS = ((0.90, "A"), (0.80, "B"), (0.65, "C"), (0.45, "D"))

# What the grade is made of, and how much each part counts. Every component is
# measured; none is a proxy for another. Weights sum to 1.
GRADE_COMPONENTS = (
    ("mean_f1", 0.40, "Base F1", False),
    ("mean_plasmid_recall", 0.25, "Plasmid recall", False),
    ("contamination", 0.20, "Chromosomal contamination", True),
    ("completion", 0.15, "Runs completed", False),
)


def grade_for(value):
    for threshold, letter in GRADE_BANDS:
        if value >= threshold:
            return letter
    return "E"


def report_cards(leaderboard, scores):
    """A grade per method, from measured metrics only.

    Deliberately not a verdict: it compresses four measurements a reader would
    otherwise have to weigh by hand, and every component is shown beside it so
    the compression can be undone.
    """
    contamination = defaultdict(list)
    for row in scores:
        true_bp = optional_number(row.get("true_plasmid_bp")) or 0
        false_bp = optional_number(row.get("FP_bp")) or 0
        total = true_bp + false_bp
        if total:
            contamination[row["tool"]].append(false_bp / total)

    cards = []
    for row in leaderboard:
        tool = row["tool"]
        scored = number(row.get("n_samples")) or 0
        completed = number(row.get("n_completed")) or 0
        dirt = contamination.get(tool, [])
        parts = {
            "mean_f1": optional_number(row.get("mean_f1")),
            "mean_plasmid_recall": optional_number(row.get("mean_plasmid_recall")),
            "contamination": (sum(dirt) / len(dirt)) if dirt else None,
            "completion": (completed / scored) if scored else None,
        }
        # A component that was never measured is dropped and the remaining
        # weights are renormalised, rather than counted as a zero.
        total_weight, running = 0.0, 0.0
        for key, weight, _label, invert in GRADE_COMPONENTS:
            value = parts[key]
            if value is None:
                continue
            running += weight * ((1 - value) if invert else value)
            total_weight += weight
        composite = (running / total_weight) if total_weight else None
        cards.append({
            "tool": tool,
            "grade": grade_for(composite) if composite is not None else "-",
            "composite": composite,
            "parts": parts,
            "measured": total_weight,
        })
    return cards


def guided_findings(leaderboard, cards, scores, status_counts):
    """Findings a reader should look at, each pointing at where to look.

    The report already interprets its own tables; this turns those readings
    into somewhere to click, because a finding the reader cannot act on is
    just more text.
    """
    findings = []
    if not leaderboard:
        return findings

    best = leaderboard[0]
    best_f1 = headline_value(best)
    if best_f1 is not None:
        low = optional_number(best.get("ranking_ci_low") or best.get("f1_ci_low"))
        high = optional_number(best.get("ranking_ci_high") or best.get("f1_ci_high"))
        spread = (f" Its 95% interval spans {low:.3f} to {high:.3f}"
                  if low is not None and high is not None else "")
        second = headline_value(leaderboard[1]) if len(leaderboard) > 1 else None
        margin = (f", {best_f1 - second:+.3f} ahead of {esc(leaderboard[1]['tool'])}"
                  if second is not None else "")
        sig_raw = (best.get("significant_vs_runner_up") or "").strip().lower()
        sig_clause = {
            "true": " This lead is statistically significant against its closest competitor "
                    "(paired sign-flip permutation test, Holm-adjusted).",
            "false": " This lead is NOT statistically significant (paired permutation test) -- "
                     "treat the rank as provisional, not a settled result.",
        }.get(sig_raw, " Too few samples are shared with the runner-up for a paired "
                       "significance test yet, so this lead is not statistically assessed.")
        findings.append({
            "tone": "good" if sig_raw == "true" else "caution", "label": f"Highest {headline_label(best)}",
            "text": f"{esc(best['tool'])} leads on {esc(headline_label(best))} at {best_f1:.3f}{margin}."
                    f"{spread + '.' if spread else ''}{sig_clause}",
            "target": "#statistics", "action": "See the paired evidence",
        })

    dirty = [c for c in cards if (c["parts"]["contamination"] or 0) > 0.05]
    if dirty:
        worst = max(dirty, key=lambda c: c["parts"]["contamination"])
        findings.append({
            "tone": "caution", "label": "Chromosomal contamination",
            "text": f"{esc(worst['tool'])} carries {worst['parts']['contamination'] * 100:.1f}% "
                    "chromosome sequence among its truth-mapped bases. For AMR work this is the "
                    "error that changes the conclusion, because a chromosomal gene reported as "
                    "plasmid-borne reads as transmissible.",
            "target": "#scores", "action": "Open the score table",
        })

    missed = [row for row in leaderboard
              if (optional_number(row.get("mean_plasmid_recall")) or 1) < 0.9
              and (optional_number(row.get("mean_f1")) or 0) > 0.8]
    if missed:
        row = missed[0]
        findings.append({
            "tone": "caution", "label": "High F1, missed plasmids",
            "text": f"{esc(row['tool'])} scores {optional_number(row['mean_f1']):.3f} on Base F1 but "
                    f"recovers only {optional_number(row['mean_plasmid_recall']):.0%} of truth "
                    "plasmids. Base F1 counts bases, so one large recovered replicon can mask "
                    "several small missed ones.",
            "target": "#pb-explorer-view", "action": "Inspect the tracks",
        })

    failed = status_counts.get("failed", 0)
    if failed:
        findings.append({
            "tone": "caution", "label": "Runs that did not complete",
            "text": f"{failed} run(s) failed. In the ranking a failed run on a plasmid-bearing isolate "
                    "scores 0 for that tool, so a method that fails often is penalised for it "
                    "(timeouts and out-of-memory kills score 0 by default; a run that never "
                    "started because of the infrastructure is never scored; a skipped run is "
                    "left out of the ranking).",
            "target": "#health", "action": "Open execution health",
        })
    return findings


def recommendation_note(recommendations, headline):
    """One line saying why the overall primary method differs from the headline leader, when it does."""
    overall = [r for r in recommendations if r.get("scope") == "overall" and r.get("recommendation") == "primary"]
    if not overall or not headline:
        return ""
    primary = overall[0]
    leader = headline.get("tool")
    if primary.get("tool") == leader:
        return ""
    other = next((r for r in recommendations if r.get("scope") == "overall" and r.get("tool") == leader), None)
    score = optional_number(primary.get("decision_score"))
    other_score = optional_number(other.get("decision_score")) if other else None
    both = (f" (decision score {score:.3f} against {other_score:.3f} for {esc(leader)})"
            if score is not None and other_score is not None else "")
    f1 = optional_number(primary.get("mean_f1"))
    other_f1 = optional_number(other.get("mean_f1")) if other else None
    tie = (f" Their mean F1 is {f1:.3f} and {other_f1:.3f}." if f1 is not None and other_f1 is not None else "")
    return ("<p class='lead'><strong>Why this is not always the headline leader.</strong> The method recommended overall is "
            f"{esc(primary.get('tool'))}, chosen by the decision score{both}, which puts accuracy first and then counts failure "
            "rate, structural diagnostics, runtime and memory; the leaderboard leader "
            f"({esc(leader)}) is ranked by {esc(headline_label(headline))} alone.{tie}</p>")


def grade_rows_html(cards):
    """The report-card table rows (tool, grade, Base F1, plasmid recall, contamination, runs completed) for `cards` from report_cards()."""
    return "".join(
        "<tr><td>{tool}</td><td><span class='grade grade-{low}'>{grade}</span></td>"
        "<td>{f1}</td><td>{recall}</td><td>{contam}</td><td>{done}</td></tr>".format(
            tool=esc(c["tool"]), low=c["grade"].lower(), grade=c["grade"],
            f1=("-" if c["parts"]["mean_f1"] is None else f"{c['parts']['mean_f1']:.3f}"),
            recall=("-" if c["parts"]["mean_plasmid_recall"] is None
                    else f"{c['parts']['mean_plasmid_recall']:.0%}"),
            contam=("not measured" if c["parts"]["contamination"] is None
                    else f"{c['parts']['contamination']:.1%}"),
            done=("-" if c["parts"]["completion"] is None else f"{c['parts']['completion']:.0%}"))
        for c in cards)


def summary_section(leaderboard, cards, findings, scores, status_counts, metadata, scope=""):
    """The headline numbers, the grades, and what to look at first."""
    if not leaderboard:
        return ""
    samples = len({row["sample"] for row in scores})
    plasmids = sum(number(row.get("true_plasmid_count")) or 0
                   for row in scores if row["tool"] == leaderboard[0]["tool"])
    best = leaderboard[0]

    stats = [
        ("Methods compared", str(len(leaderboard)), "Tools with at least one scored run."),
        ("Isolates", str(samples), "Samples with a truth set and at least one scored method."),
        ("Truth plasmids", str(int(plasmids)), "Reference plasmids the methods were measured against."),
        # `scope` names the analysis track when several were scored (" · Short-read track"): the leader belongs to one track, never to a pooled ranking
        ("Leading method", esc(best["tool"]),
         f"Highest {headline_label(best)} ({headline_value(best) or 0:.3f}){scope} · method ranking only."),
        ("Runs not completed", str(status_counts.get("failed", 0) + status_counts.get("skipped", 0)),
         "Failed runs on plasmid-bearing isolates count as zero for that tool; skipped runs are left out."),
    ]
    stat_html = "".join(
        f"<div class='sum-stat' title='{esc(hint)}'><small>{esc(label)}</small>"
        f"<strong>{value}</strong></div>" for label, value, hint in stats)

    grade_html = grade_rows_html(cards)

    find_html = "".join(
        f"<li class='finding {f['tone']}'><span class='flabel'>{esc(f['label'])}</span>"
        f"<p>{f['text']}</p><a href='{f['target']}' class='goto'>{esc(f['action'])} &rarr;</a></li>"
        for f in findings) or "<li class='finding'><p>No finding stood out from these tables.</p></li>"

    return (
        "<section id='summary'><h2>Summary</h2>"
        "<p class='lead'>The headline numbers, a grade per method, and what to look at first. "
        "Every figure here is repeated in full further down; this is the entry point, not a "
        "second source.</p>"
        f"<div class='sum-stats'>{stat_html}</div>"
        "<h3>Start here</h3>"
        f"<ul class='findings'>{find_html}</ul>"
        "<h3>Report card <span class='pb-scope' data-iso-scope>All isolates</span></h3>"
        "<p class='lead'>A reading aid, not an acceptance threshold. The grade is a weighted "
        "composite of Base F1 (40%), plasmid recall (25%), freedom from chromosomal "
        "contamination (20%) and completed runs (15%); A &ge;0.90, B &ge;0.80, C &ge;0.65, "
        "D &ge;0.45. A component that was not measured is dropped and the rest reweighted, "
        "never counted as zero. The components are shown so the grade can be taken apart.</p>"
        "<div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Grade</th>"
        "<th>Base F1</th><th>Plasmid recall</th><th>Chromosomal contamination</th>"
        f"<th>Runs completed</th></tr></thead><tbody data-iso-slot='summary-card'>{grade_html}</tbody></table></div>"
        "<!--pb-after-report-card-->"
        "</section>")


def accessibility_script():
    """A colour-blind safe palette and a print form, both opt-in.

    Green against red is the least distinguishable pair for the commonest forms
    of colour vision deficiency, and it is the pair this report leans on. The
    safe palette swaps it for blue against orange, which separates under
    deuteranopia and protanopia and still reads as good against bad.

    Colour is never the only channel here -- heatmap cells print their value,
    grades print a letter, segments carry a label -- so the switch changes hue
    only, and nothing depends on it.
    """
    return report_asset("accessibility_script.html")


def explain_script():
    """Click any chart mark and be told what it means, not just what it says.

    The marks already carried their facts in a <title>: a band knows it is
    "4/5 methods", a ribbon knows it is "6,000 bp". What none of them carried
    was the reading -- whether four of five agreeing is reassuring, what a
    ribbon that splits implies downstream. This adds that second half, from one
    panel every chart shares rather than a bespoke popup per chart.
    """
    return report_asset("explain_script.html")


def section_nav_script():
    """Mark the section the reader is actually in.

    A strip of links that never says where you are is a table of contents, not
    navigation. This tracks the section in view and keeps its pill in sight, so
    the bar answers "where am I" as well as "where can I go".
    """
    return report_asset("section_nav_script.html")


def agreement_pointer_script():
    """Put a draggable pointer on the agreement track.

    The sweep shows how many methods cover each interval, but reading a
    particular coordinate off it means eyeballing a band against a ruler. The
    pointer is dragged along the track and reports the position it is on: which
    interval, how many methods cover it, which ones by name, and what that
    means. Naming them is the part the picture cannot do -- "4 of 5" does not
    say which one disagrees.
    """
    return report_asset("agreement_pointer_script.html")


def read_tool_versions(path):
    """Map report tool labels to versions recorded at the time of the run.

    Two sources, in order. The executable map covers the adapters that ship
    here, whose report label differs from the command they invoke. A run may
    also record ``method_versions`` keyed by report label, which is the only
    way a method outside that fixed list -- a new adapter, or a synthetic
    method -- can report a version at all; it wins where both are present.
    """
    if not path or not Path(path).is_file():
        return {}
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    tools = manifest.get("tools", {}) or {}
    executable = {
        "mob_recon": "mob_recon", "platon": "platon",
        "plasmidspades": "plasmidspades.py", "gplas": "gplas",
        "gplas2_external": "gplas", "gplas2_mob": "gplas",
        "plassembler": "plassembler", "flye_mob_recon": "flye",
        "genomad": "genomad", "plasme": "PLASMe.py",
        "plasgraph2": "plASgraph2_classify.py",
        "rfplasmid": "rfplasmid", "plasmidhunter": "plasmidhunter", "plasmer": "Plasmer",
        "plascope": "plaScope.sh",
    }
    versions = {label: details.get("version", "unreported")
                for label, name in executable.items()
                if (details := tools.get(name, {})).get("available")}
    declared = manifest.get("method_versions", {}) or {}
    if isinstance(declared, dict):
        versions.update({str(label): str(value) for label, value in declared.items() if value})
    return versions


def optional_analysis_html(manifest_path, results_dir, report_path):
    """Summarise optional decision-support artifacts without treating absence as failure."""
    model = {}
    try:
        model = json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("models", {}).get("recommendation", {})
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    if model.get("available"):
        strategy = model.get("validation_strategy", "not recorded").replace("_", " ")
        claim = model.get("validation_claim", "No validation claim recorded.")
        card = results_dir / "benchmark.recommendation_model.card.md"
        card_link = f" <a href='{relative_link(card, report_path)}' download>Download model card</a>." if card.is_file() else ""
        model_html = (f"<p><strong>Recommendation model:</strong> {'ready for guarded decision support' if model.get('model_ready') else 'withheld'}; "
                      f"validation: {esc(strategy)}. {esc(claim)}{card_link}</p>")
    else:
        model_html = "<p><strong>Recommendation model:</strong> not enabled for this run; fixed transparent recommendation rules were used.</p>"
    ladders = []
    for svg in sorted(results_dir.glob("*.recovery.svg")):
        summary = svg.with_name(svg.name.replace(".recovery.svg", ".summary.tsv"))
        label = "Read-quality ladder" if "quality" in svg.name.lower() else "Read-depth ladder"
        links = f"<a href='{relative_link(svg, report_path)}' download>Download SVG</a>"
        if summary.is_file(): links += f" · <a href='{relative_link(summary, report_path)}' download>Download summary TSV</a>"
        ladders.append(f"<li><strong>{esc(label)}:</strong> {links}. These are controlled sensitivity experiments, not independent benchmark samples.</li>")
    ladder_html = "<ul>" + "".join(ladders) + "</ul>" if ladders else "<p><strong>Depth/read-quality ladders:</strong> not run for this report. Their absence is not a failed benchmark.</p>"
    return model_html + ladder_html


def number(value):
    return float(value) if value not in (None, "") else 0.0


def optional_number(value):
    return float(value) if value not in (None, "") else None


def rate_text(rate, assessed):
    rate = optional_number(rate)
    assessed = optional_number(assessed)
    return f"{rate:.1%} (n={int(assessed)})" if rate is not None and assessed is not None else "not assessed"


def esc(value):
    return html.escape(str(value), quote=True)


def relative_link(target, report_path):
    try:
        relative = os.path.relpath(target, report_path.parent).replace(os.sep, "/")
    except ValueError:
        # Windows cannot compute a relative path across drive letters. A file
        # URI preserves the report's direct-download explorer in that case.
        return Path(target).resolve().as_uri()
    return quote(relative, safe="/._-~")


def size_text(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


def file_tree(root, report_path, excluded_paths=()):
    root = Path(root)
    if not root.exists():
        return "<p class='muted'>Not created in this run.</p>", 0, 0

    excluded = {Path(path).resolve() for path in excluded_paths if path}

    entries = []
    for path in sorted(root.rglob("*"), key=lambda p: (p.is_file(), str(p).lower())):
        if path.is_file() and path.resolve() != report_path.resolve() and path.resolve() not in excluded:
            rel = path.relative_to(root).as_posix()
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            entries.append((rel, path, path.stat().st_size, modified))

    tree = {"dirs": {}, "files": []}
    for rel, path, size, modified in entries:
        node = tree
        parts = rel.split("/")
        for part in parts[:-1]:
            node = node["dirs"].setdefault(part, {"dirs": {}, "files": []})
        node["files"].append((parts[-1], path, size, modified))

    def render(node):
        chunks = ["<ul class='file-tree'>"]
        for name, child in sorted(node["dirs"].items()):
            chunks.append(f"<li><details><summary>{esc(name)}/</summary>{render(child)}</details></li>")
        for name, path, size, modified in node["files"]:
            href = relative_link(path, report_path)
            chunks.append(
                "<li class='file'><a href='{}' download>{}</a>"
                "<span>{} · {}</span></li>".format(href, esc(name), size_text(size), esc(modified))
            )
        chunks.append("</ul>")
        return "".join(chunks)

    return render(tree), len(entries), sum(entry[2] for entry in entries)


def score_band(value):
    """Return a display class; thresholds are visual aids, not pass/fail calls."""
    if value >= 0.90:
        return "high"
    if value >= 0.70:
        return "medium"
    return "low"


def size_band(bp):
    if bp < 10_000:
        return "small"
    if bp < 100_000:
        return "medium"
    return "large"


def score_row(row, metadata, tool_versions):
    sample_metadata = metadata.get(row["sample"], {})
    depth = sample_metadata.get("read_depth_x", "")
    try:
        depth_value = float(depth) if depth else None
    except ValueError:
        depth_value = None
    truth_bp = int(number(row["true_plasmid_bp"]))
    version = tool_versions.get(row["tool"], "not recorded")
    band = score_band(number(row["f1"]))
    # Self-built truth (truth_source=self_assembled_hybrid, see docs/COHORTS.md):
    # the reference was assembled in-house from this isolate's own long+short
    # reads (python/build_hybrid_truth.py), not downloaded as an existing NCBI
    # assembly. Flagged inline rather than as its own column, since it applies
    # to only some rows and a reader scanning by sample benefits from seeing
    # it right next to the sample id.
    truth_source = (sample_metadata.get("truth_source") or "ncbi_deposited").strip() or "ncbi_deposited"
    self_built = truth_source == "self_assembled_hybrid"
    simulated = truth_source == "simulated"
    sample_cell = esc(row["sample"])
    if self_built:
        sample_cell += ("<span class='truth-source-badge' "
                        "title='Truth reference built in-house from this isolate&#39;s own long+short "
                        "reads (python/build_hybrid_truth.py), not downloaded as an existing NCBI "
                        "assembly -- see docs/COHORTS.md.'>self-built truth</span>")
    elif simulated:
        # A distinct badge (not the self-built-truth one above): the truth
        # reference here IS a real, independently-deposited assembly, but
        # the READS were generated locally (python/simulate_reads.py), never
        # a real sequencing run -- a simulated isolate must never be
        # silently read as a real-world result. See docs/COHORTS.md.
        sample_cell += ("<span class='truth-source-badge simulated-badge' "
                        "title='Reads generated locally from a real reference assembly "
                        "(python/simulate_reads.py: InSilicoSeq + Badread), never a real "
                        "sequencing run -- see docs/COHORTS.md.'>simulated reads</span>")
    return (
        "<tr data-sample='{sample}' data-tool='{tool}' data-band='{band}' "
        "data-organism='{organism}' data-tech='{tech}' data-tier='{tier}' "
        "data-origin='{origin}' data-size='{size}' data-depth='{depth}' data-version='{version}' "
        "data-track='{track}' data-truth-source='{truth_source}'>"
        "<td>{sample_cell}</td><td>{tool}</td><td>{version}</td><td>{origin}</td><td>{depth_text}</td>"
        "<td>{truth:,}</td><td>{tp:,}</td><td>{fp:,}</td><td>{fn:,}</td><td>{unambiguous:,}</td><td>{ambiguous:,}</td><td>{unmapped:,}</td>"
        "<td>{precision}</td><td>{recall}</td><td>{amr}</td><td>{circular}</td>"
        "<td><strong class='score {band}'>{f1}</strong></td></tr>"
    ).format(
        sample=esc(row["sample"]), sample_cell=sample_cell, tool=esc(row["tool"]), version=esc(version),
        organism=esc(sample_metadata.get("organism", "")), tech=esc(sample_metadata.get("truth_technology", "")),
        tier=esc(sample_metadata.get("truth_quality_tier", "")), origin=esc(sample_metadata.get("sample_origin", "")),
        track=esc(row.get("analysis_track") or "short_read"), truth_source=esc(truth_source),
        size=size_band(truth_bp), depth="" if depth_value is None else depth_value,
        depth_text=esc(depth) if depth_value is not None else "-", truth=truth_bp,
        tp=int(number(row["TP_bp"])), fp=int(number(row["FP_bp"])), fn=int(number(row["FN_bp"])),
        unmapped=int(number(row["unmapped_pred_bp"])), unambiguous=int(number(row.get("unambiguously_mapped_pred_bp"))),
        ambiguous=int(number(row.get("ambiguously_mapped_pred_bp"))), precision=esc(row["precision"]),
        recall=esc(row["recall"]), amr=esc(row.get("amr_gene_recall") or "-"),
        circular=esc(row.get("circular_plasmid_recall") or "-"), f1=esc(row["f1"]), band=band,
    )


def interpretation(leaderboard, status_counts):
    """Only report directly observed comparisons from the report input tables."""
    notes = []
    if not leaderboard:
        return ["No tool has a score row yet, so performance cannot be interpreted."], "neutral"

    winner = leaderboard[0]
    winner_f1 = headline_value(winner) or 0.0
    if len(leaderboard) == 1:
        notes.append(f"{winner['tool']} is the only scored tool ({headline_label(winner)} {winner_f1:.3f}); no between-tool comparison is available.")
    else:
        runner = leaderboard[1]
        runner_f1 = headline_value(runner) or 0.0
        gap = winner_f1 - runner_f1
        # Uses aggregate_results.py's own paired, shared-sample, sign-flip
        # permutation test (Holm-adjusted) -- never a raw-gap-size heuristic.
        # A large mean-F1 gap can still be statistically unsupported with few
        # shared samples, and a small gap can still be real with many.
        sig_raw = (winner.get("significant_vs_runner_up") or "").strip().lower()
        if sig_raw in ("true", "1"):
            notes.append(
                f"{winner['tool']} leads {runner['tool']} by {gap:.3f} {headline_label(winner)} "
                f"({winner_f1:.3f} versus {runner_f1:.3f}), and this margin is statistically "
                "significant against its closest competitor (paired sign-flip permutation "
                "test, Holm-adjusted p<0.05 -- see Significant vs runner-up)."
            )
        elif sig_raw in ("false", "0"):
            notes.append(
                f"{winner['tool']} ranks above {runner['tool']} by {gap:.3f} {headline_label(winner)} "
                f"({winner_f1:.3f} versus {runner_f1:.3f}), but this margin is NOT "
                "statistically significant (paired permutation test) -- this run alone "
                "does not establish a real difference between the two."
            )
        else:
            notes.append(
                f"{winner['tool']} ranks above {runner['tool']} by {gap:.3f} {headline_label(winner)} "
                f"({winner_f1:.3f} versus {runner_f1:.3f}); too few samples are shared "
                "between them for the paired significance test to run, so this margin "
                "is not yet statistically assessed either way."
            )

    for row in leaderboard:
        precision, recall = number(row["mean_precision"]), number(row["mean_recall"])
        delta = precision - recall
        if delta >= 0.15:
            notes.append(f"{row['tool']} is more precise than complete (precision {precision:.3f}, recall {recall:.3f}); missed plasmid sequence is the larger limitation.")
        elif delta <= -0.15:
            notes.append(f"{row['tool']} recovers more plasmid sequence than it classifies cleanly (recall {recall:.3f}, precision {precision:.3f}); chromosomal contamination is the larger limitation.")

    issues = status_counts["failed"] + status_counts["skipped"]
    if issues:
        notes.append(f"{issues} tool-sample execution(s) were not scored ({status_counts['failed']} failed, {status_counts['skipped']} skipped); compare completed and scored counts before relying on rank order.")
        tone = "caution"
    else:
        notes.append("All recorded tool-sample executions completed or were reused; the coverage columns still show the number of scored samples per tool.")
        tone = "positive"
    return notes, tone


ROBUSTNESS_TRACK_LABELS = {"short_read": "Short-read track", "long_read": "Long-read track",
                           "hybrid": "Hybrid (long + short) track"}


def _value_or(row, key, missing="-"):
    value = (row.get(key) or "").strip() if isinstance(row.get(key), str) else row.get(key)
    return esc(str(value)) if value not in (None, "") else missing


def ceiling_chart(rows):
    """Base recall against the recall ceiling each tool could have reached.

    The pale bar is the ceiling (plasmid bases a prediction could be scored on
    under the alignment filters); the solid bar is the recall achieved. The
    gap between the solid bar and the pale bar is recall a tool genuinely
    missed; the gap between the pale bar and 1.0 is unscorable sequence
    (repeats shared with the chromosome, duplicate plasmids) that no tool can
    be credited for.
    """
    rows = [r for r in rows if optional_number(r.get("mean_recall_ceiling")) is not None]
    if not rows:
        return ("<p class='muted'>Recall ceiling not computed in this run "
                "(RUN_SCORABLE_TRUTH=0, or minimap2 was unavailable at stage 5).</p>")
    row_height = 30
    width, label_width, chart_width = 760, 145, 470
    height = 30 + len(rows) * row_height
    parts = [f"<svg class='performance-chart' viewBox='0 0 {width} {height}' role='img' "
             "aria-label='Mean base recall against mean recall ceiling by tool'>",
             f"<text x='{label_width}' y='14' class='axis'>0</text>"
             f"<text x='{label_width + chart_width - 18}' y='14' class='axis'>1.0</text>"]
    for index, row in enumerate(rows):
        y = 22 + index * row_height
        recall = optional_number(row.get("mean_recall")) or 0.0
        ceiling = optional_number(row.get("mean_recall_ceiling")) or 0.0
        parts.append(f"<text x='0' y='{y + 12}' class='label'>{esc(row['tool'])}</text>")
        parts.append(f"<rect x='{label_width}' y='{y}' width='{chart_width}' height='14' fill='#e0e8e1'/>")
        parts.append(f"<rect x='{label_width}' y='{y}' width='{chart_width * ceiling:.1f}' height='14' fill='#f1d6a8'>"
                     f"<title>{esc(row['tool'])} recall ceiling: {ceiling:.3f}</title></rect>")
        parts.append(f"<rect x='{label_width}' y='{y + 3}' width='{chart_width * recall:.1f}' height='8' fill='#d18b2a'>"
                     f"<title>{esc(row['tool'])} base recall: {recall:.3f}</title></rect>")
        parts.append(f"<text x='{label_width + chart_width + 8}' y='{y + 12}' class='axis'>"
                     f"{recall:.2f} of {ceiling:.2f} reachable</text>")
    legend = ("<div class='chart-legend'><span><i style='background:#d18b2a'></i>Base recall achieved</span>"
              "<span><i style='background:#f1d6a8'></i>Recall ceiling (scorable plasmid bases)</span></div>")
    return legend + "".join(parts) + "</svg>"


def dumbbell_chart(rows, left_key, right_key, left_label, right_label, aria, empty_text):
    """Per-tool pair of 0-1 values joined by a line (e.g. F1 vs F1 after DB)."""
    rows = [r for r in rows
            if optional_number(r.get(left_key)) is not None and optional_number(r.get(right_key)) is not None]
    if not rows:
        return f"<p class='muted'>{esc(empty_text)}</p>"
    row_height = 28
    width, label_width, chart_width = 760, 145, 470
    height = 30 + len(rows) * row_height
    left_color, right_color = "#174b3a", "#bd4b42"
    parts = [f"<svg class='performance-chart' viewBox='0 0 {width} {height}' role='img' aria-label='{esc(aria)}'>",
             f"<text x='{label_width}' y='14' class='axis'>0</text>"
             f"<text x='{label_width + chart_width - 18}' y='14' class='axis'>1.0</text>"]
    for index, row in enumerate(rows):
        y = 30 + index * row_height
        left = optional_number(row.get(left_key))
        right = optional_number(row.get(right_key))
        x1, x2 = label_width + chart_width * left, label_width + chart_width * right
        parts.append(f"<text x='0' y='{y + 4}' class='label'>{esc(row['tool'])}</text>")
        parts.append(f"<line x1='{label_width}' x2='{label_width + chart_width}' y1='{y}' y2='{y}' stroke='#e0e8e1' stroke-width='6'/>")
        parts.append(f"<line x1='{x1:.1f}' x2='{x2:.1f}' y1='{y}' y2='{y}' stroke='#8a9a90' stroke-width='2'/>")
        parts.append(f"<circle cx='{x1:.1f}' cy='{y}' r='6' fill='{left_color}'><title>{esc(row['tool'])} "
                     f"{esc(left_label)}: {left:.3f}</title></circle>")
        parts.append(f"<circle cx='{x2:.1f}' cy='{y}' r='6' fill='{right_color}'><title>{esc(row['tool'])} "
                     f"{esc(right_label)}: {right:.3f}</title></circle>")
        parts.append(f"<text x='{label_width + chart_width + 8}' y='{y + 4}' class='axis'>"
                     f"{left:.2f} → {right:.2f}</text>")
    legend = (f"<div class='chart-legend'><span><i style='background:{left_color}'></i>{esc(left_label)}</span>"
              f"<span><i style='background:{right_color}'></i>{esc(right_label)}</span></div>")
    return legend + "".join(parts) + "</svg>"


def robustness_section(track_leaderboards, ordered_tracks, overlap_statuses=None):
    """How much each headline number can be trusted, per analysis track."""
    blocks = []
    for track in ordered_tracks:
        rows = track_leaderboards.get(track) or []
        if not rows:
            continue
        heading = (f"<h3>{esc(ROBUSTNESS_TRACK_LABELS.get(track, track))}</h3>"
                   if len(ordered_tracks) > 1 else "")
        body = []
        for row in rows:
            basis = row.get("ranking_basis") or ""
            ranked_on = _value_or(row, "n_ranking_samples")
            ranked_on += " shared" if basis == "shared_samples" else (" own (no overlap)" if basis else "")
            overlap = "-"
            if row.get("n_possible_db_overlap") not in (None, ""):
                possible = optional_number(row.get("n_possible_db_overlap")) or 0
                after_db = optional_number(row.get("n_after_database")) or 0
                unknown = optional_number(row.get("n_unknown_overlap")) or 0
                if possible == 0 and after_db == 0 and unknown > 0:
                    # The screen ran but could not judge these pairs (database release
                    # date not filled in). That is not the same as "checked and clean".
                    overlap = (f"<strong>not assessed</strong> ({int(unknown)} pair(s) unknown: "
                               f"database release date not filled in)")
                elif possible == 0 and after_db == 0 and unknown == 0:
                    # 0/0/0 is two different things: a tool with no reference database, or a screen with no rows for
                    # the tool. benchmark.database_overlap.tsv tells them apart; without it the cell says it cannot.
                    import report_wiring
                    overlap = esc(report_wiring.overlap_cell(0, 0, 0, (overlap_statuses or {}).get(row["tool"], [])))
                elif possible == 0 and unknown == 0:
                    import report_wiring
                    overlap = esc(report_wiring.overlap_cell(0, after_db, 0, []))
                else:
                    overlap = f"{esc(row['n_possible_db_overlap'])} possible / {_value_or(row, 'n_after_database', '0')} after"
                    if unknown > 0:
                        overlap += f" / {int(unknown)} unknown"
            redundant = optional_number(row.get("total_redundant_pred_bp"))
            body.append(
                "<tr><td>{tool}</td><td><strong>{f1}</strong></td><td>{ranked_on}</td><td>{clusters}</td>"
                "<td>{f1_all}</td><td>{zeros}</td><td>{precision}</td><td>{strict}</td><td>{recall}</td>"
                "<td>{ceiling}</td><td>{adjusted}</td><td>{redundant}</td><td>{overlap}</td><td>{f1_after}</td></tr>".format(
                    tool=esc(row["tool"]), f1=_value_or(row, "mean_f1"), ranked_on=ranked_on,
                    clusters=_value_or(row, "n_independent_clusters"),
                    f1_all=_value_or(row, "mean_f1_all_scored"),
                    zeros=_value_or(row, "n_failures_scored_zero", "0"),
                    precision=_value_or(row, "mean_precision"),
                    strict=_value_or(row, "mean_strict_precision"),
                    recall=_value_or(row, "mean_recall"),
                    ceiling=_value_or(row, "mean_recall_ceiling", "not computed"),
                    adjusted=_value_or(row, "mean_ceiling_adjusted_recall", "not computed"),
                    redundant=f"{int(redundant):,}" if redundant is not None else "-",
                    overlap=overlap,
                    f1_after=_value_or(row, "mean_f1_after_database", "not assessed"),
                ))
        table = ("<div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Mean base F1 (shared samples)</th>"
                 "<th>Ranked on samples</th><th>Independent clusters</th><th>Mean F1, all scored</th>"
                 "<th>Failed runs scored 0</th><th>Mean precision</th><th>Strict precision</th><th>Base recall</th>"
                 "<th>Recall ceiling</th><th>Ceiling-adjusted recall</th><th>Redundant predicted bp</th>"
                 "<th>Database overlap (samples)</th><th>Mean F1 after database</th></tr></thead>"
                 f"<tbody>{''.join(body)}</tbody></table></div>")
        charts = (
            "<div class='chart-card'><h4>Recall against what was reachable</h4>" + ceiling_chart(rows) + "</div>"
            "<div class='chart-card'><h4>Precision vs strict precision</h4>"
            + dumbbell_chart(rows, "mean_precision", "mean_strict_precision", "Precision", "Strict precision",
                             "Mean precision and strict precision by tool",
                             "Strict precision is not available for these score rows.") + "</div>"
            "<div class='chart-card'><h4>F1 on all samples vs samples released after the tool's database</h4>"
            + dumbbell_chart(rows, "mean_f1", "mean_f1_after_database", "Mean base F1 (shared samples)",
                             "Mean F1, truth released after database",
                             "Mean F1 overall and on samples released after the tool's database",
                             "Not assessed: fill database_release_date in config/tool_database_releases.tsv "
                             "and keep each sample's assembly_data_report.jsonl.") + "</div>"
        )
        blocks.append(heading + table + charts)
    content = "".join(blocks) or "<p class='muted'>No leaderboard rows to assess.</p>"
    return (
        "<section id='robustness'><h2>Robustness diagnostics</h2>"
        "<p class='lead'>How far each headline number can be trusted. None of these change the ranking. "
        "<strong>Mean base F1 (shared samples)</strong> is the base-level F1 on those shared samples; it is not the "
        "leaderboard's ranking score, which is length-weighted binning F1 or CPRR depending on the track. "
        "<strong>Ranked on</strong>: every tool is ranked on the samples all ranked tools share, and a "
        "failed tool run on a plasmid-bearing sample counts as F1 = 0. <strong>Independent clusters</strong>: "
        "confidence intervals and permutation tests resample whole BioProjects, because isolates from one "
        "study are not independent. <strong>Strict precision</strong> also charges predicted bases that "
        "never aligned or failed the alignment filters, which ordinary precision ignores. "
        "<strong>Recall ceiling</strong> is the largest recall any prediction could reach: plasmid sequence "
        "repeated elsewhere in the genome cannot be placed uniquely and is never credited. "
        "<strong>Redundant predicted bp</strong> are reference bases claimed more than once. "
        "<strong>Database overlap</strong> counts samples whose truth genome was public before the tool's "
        "own reference database, so the tool may already contain it; <strong>Mean F1 after database</strong> "
        "uses only samples it cannot contain. This is a date-based screen, not proof of inclusion.</p>"
        + content + "</section>"
    )


METRIC_LABELS = {"lw_bin_f1": "length-weighted binning F1", "f1": "base-level F1",
                 "sample_cprr": "isolate-level CPRR"}
TASK_LABELS = {"reconstruction": "Plasmid reconstruction", "classification": "Plasmid classification"}
TASK_BLURBS = {
    "reconstruction": ("Binning-capable tools. On the short-read track they are ranked by length-weighted "
                       "binning F1 (primary endpoint): bases placed in the correct one-to-one matched bin, with "
                       "CPRR, the share of truth plasmids reconstructed correctly, as the key secondary endpoint. "
                       "On the long-read and hybrid tracks, whose tools aim to close whole plasmids, the "
                       "primary endpoint is isolate-level CPRR and binning F1 is secondary. The CPRR cell also "
                       "gives the per-isolate rate and the area under the CPRR curve over thresholds 0.80-0.99."),
    "classification": ("Classifier-only tools, ranked by base-level plasmid/chromosome F1. They are not scored "
                       "on binning, a task they do not attempt."),
}


def headline_value(row):
    """The value a row is ranked by: ranking_score, else legacy mean_f1."""
    value = optional_number(row.get("ranking_score"))
    return value if value is not None else optional_number(row.get("mean_f1"))


def headline_label(row):
    metric = row.get("ranking_metric") or "f1"
    return METRIC_LABELS.get(metric, metric)


def primary_task_rows(rows):
    """Rows of the primary task present (reconstruction first), else all rows."""
    tasks = [row.get("task") or "" for row in rows]
    for task in ("reconstruction", "classification"):
        if task in tasks:
            return [row for row in rows if (row.get("task") or "") == task]
    return rows


def headline_design_section(out_dir):
    """Reference standard, provenance tiers and species balance behind the headline."""
    design = read_tsv(out_dir / "benchmark.headline_design.tsv") if (out_dir / "benchmark.headline_design.tsv").is_file() else []
    provenance = read_tsv(out_dir / "benchmark.truth_provenance.tsv") if (out_dir / "benchmark.truth_provenance.tsv").is_file() else []
    species = read_tsv(out_dir / "benchmark.species.tsv") if (out_dir / "benchmark.species.tsv").is_file() else []
    tiers = read_tsv(out_dir / "benchmark.reference_tiers.tsv") if (out_dir / "benchmark.reference_tiers.tsv").is_file() else []
    if not (design or provenance or species or tiers):
        return ""
    design_rows = "".join(
        f"<tr><td>{esc(r.get('analysis_track'))}</td><td>{esc(TASK_LABELS.get(r.get('task'), r.get('task')))}</td>"
        f"<td>{esc(METRIC_LABELS.get(r.get('ranking_metric'), r.get('ranking_metric')))}</td>"
        f"<td>{esc(r.get('reference_basis'))}</td><td>{esc(r.get('species_basis') or 'pooled')}</td></tr>"
        for r in design) or "<tr><td colspan='5'>Not recorded.</td></tr>"
    tier_counts = Counter(r.get("reference_tier") for r in provenance)
    provenance_rows = "".join(
        f"<tr><td>{esc(r.get('sample'))}</td><td>{esc(r.get('reference_tier'))}</td>"
        f"<td>{esc(r.get('truth_assembly_strategy'))}</td><td>{esc(r.get('truth_polish_reads'))}</td>"
        f"<td>{esc(r.get('base_level_metrics_valid'))}</td><td>{esc(r.get('labels_evidence_checked'))}</td>"
        f"<td>{esc(r.get('ambiguous_plasmids') or '0')}</td><td>{esc(r.get('tier_reason'))}</td></tr>"
        for r in provenance) or "<tr><td colspan='8'>No provenance table.</td></tr>"
    species_rows = "".join(
        f"<tr><td>{esc(r.get('analysis_track'))} / {esc(r.get('task'))}</td><td>{esc(r.get('tool'))}</td>"
        f"<td><em>{esc(r.get('species'))}</em></td><td>{esc(r.get('n_samples'))}</td><td>{esc(r.get('n_clusters'))}</td>"
        f"<td>{esc(r.get('mean_metric'))}</td><td>{'yes' if r.get('in_headline') == 'yes' else 'described only'}</td></tr>"
        for r in species) or "<tr><td colspan='7'>No species information.</td></tr>"
    # Sensitivity: headline tiers (1-2) versus provisional tier 3, per tool.
    by_tool = defaultdict(lambda: {"head": [0.0, 0], "prov": [0.0, 0]})
    for r in tiers:
        value, n = optional_number(r.get("mean_metric")), int(optional_number(r.get("n_samples")) or 0)
        if value is None or not n:
            continue
        key = "prov" if r.get("reference_tier") == "3" else "head"
        by_tool[r.get("tool")][key][0] += value * n
        by_tool[r.get("tool")][key][1] += n
    chart_rows = [{"tool": tool, "head": v["head"][0] / v["head"][1], "prov": v["prov"][0] / v["prov"][1]}
                  for tool, v in sorted(by_tool.items()) if v["head"][1] and v["prov"][1]]
    chart = dumbbell_chart(chart_rows, "head", "prov", "Reference tiers 1-2 (headline)",
                           "Tier 3 (provisional truth)", "Ranking metric on headline versus provisional truth",
                           "No tool was scored on both headline-tier and tier-3 truth in this run.")
    return (
        "<section id='headline-design'><h2>Headline design and reference standard</h2>"
        "<p class='lead'>Which samples and species the headline ranking rests on. Truth assemblies are graded: "
        "<strong>Tier 1</strong> long-read-first truth independent of the benchmark reads with evidence-checked "
        "labels; <strong>Tier 2</strong> long-read-first truth that fails a Tier-1 condition (for example, "
        "polished with the benchmark's own Illumina reads, so identity-based criteria are not applied); "
        "<strong>Tier 3</strong> short-read-first hybrid or unknown provenance, provisional and outside the "
        "headline. Replicons whose plasmid/chromosome label conflicts with marker, rRNA or long-read evidence are "
        "AMBIGUOUS and excluded from scoring. The ranking score averages per-species means over species with "
        "enough independent (non-clonal) isolates; smaller species are described only.</p>"
        "<details class='rpt-collapsible'><summary>Show the reference standard, truth provenance, tier sensitivity and species balance</summary>"
        "<div class='panel'><table><thead><tr><th>Track</th><th>Task</th><th>Ranking metric</th>"
        f"<th>Reference standard</th><th>Species basis</th></tr></thead><tbody>{design_rows}</tbody></table></div>"
        f"<h3>Truth provenance</h3><p class='muted'>Tier counts: "
        + (", ".join(f"tier {esc(t)}: {n}" for t, n in sorted(tier_counts.items()) if t) or "none")
        + ". Derived values are heuristics from NCBI assembly metadata; set truth_assembly_strategy and "
        "truth_polish_reads in the sample sheet to override.</p>"
        "<div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Tier</th><th>Assembly strategy</th>"
        "<th>Polishing reads</th><th>Identity criteria valid</th><th>Labels evidence-checked</th>"
        f"<th>AMBIGUOUS plasmids</th><th>Reason</th></tr></thead><tbody>{provenance_rows}</tbody></table></div>"
        "<h3>Reference-tier sensitivity</h3><div class='chart-card'>" + chart + "</div>"
        "<h3>Species balance</h3><div class='panel'><table class='sortable'><thead><tr><th>Track / task</th>"
        "<th>Tool</th><th>Species</th><th>Samples</th><th>Independent clusters</th><th>Mean ranking metric</th>"
        f"<th>In headline</th></tr></thead><tbody>{species_rows}</tbody></table></div></details></section>"
    )


def performance_chart(leaderboard):
    if not leaderboard:
        return "<p class='muted'>No scored tools yet.</p>"
    row_height = 42
    width, label_width, chart_width = 760, 145, 520
    height = 42 + len(leaderboard) * row_height
    colors = [("Precision", "#2c7a62"), ("Recall", "#d18b2a"), ("F1", "#174b3a")]
    parts = [f"<svg class='performance-chart' viewBox='0 0 {width} {height}' role='img' aria-label='Mean precision, recall, and F1 by tool'>"]
    parts.append("<text x='145' y='16' class='axis'>0</text><text x='638' y='16' class='axis'>1.0</text>")
    for index, row in enumerate(leaderboard):
        y = 30 + index * row_height
        parts.append(f"<text x='0' y='{y + 14}' class='label'>{esc(row['tool'])}</text>")
        for metric_index, (label, color) in enumerate(colors):
            value = number(row[f"mean_{label.lower()}"])
            bar_y = y + metric_index * 9
            parts.append(f"<rect x='{label_width}' y='{bar_y}' width='{chart_width}' height='6' fill='#e0e8e1'/>")
            parts.append(f"<rect x='{label_width}' y='{bar_y}' width='{chart_width * value:.1f}' height='6' fill='{color}'><title>{esc(row['tool'])} {label}: {value:.3f}</title></rect>")
    legend = "".join(f"<span><i style='background:{color}'></i>{label}</span>" for label, color in colors)
    return "<div class='chart-legend'>" + legend + "</div>" + "".join(parts) + "</svg>"


def read_pr_curve(results_dir, sample, tool):
    """Per (sample, tool) PR-curve points written by scripts/05_score.sh
    (adapters/SCORES.md); absent for every tool with no probability output."""
    path = results_dir / sample / f"{tool}.pr_curve.tsv"
    if not path.is_file():
        return []
    return read_tsv(path)


def pr_curve_chart(points, pr_auc=None):
    """Inline precision-vs-recall curve for one sample/tool.

    Unlike every other chart here (a bar spanning 0-1 on a single axis), this
    is a genuine 2-axis XY plot: each swept probability threshold is one point
    at (recall, precision), connected in recall order.
    """
    if not points:
        return "<p class='muted'>No PR-curve data.</p>"
    width, height, pad = 220, 220, 30
    plot = width - pad - 12

    def sx(recall):
        return pad + number(recall) * plot

    def sy(precision):
        return pad + (1 - number(precision)) * plot

    ordered = sorted(points, key=lambda p: number(p["recall"]))
    coords = " ".join(f"{sx(p['recall']):.1f},{sy(p['precision']):.1f}" for p in ordered)
    dots = "".join(
        f"<circle cx='{sx(p['recall']):.1f}' cy='{sy(p['precision']):.1f}' r='2.5' fill='#174b3a'>"
        f"<title>threshold {esc(p['threshold'])}: precision {number(p['precision']):.3f}, recall {number(p['recall']):.3f}</title>"
        "</circle>"
        for p in ordered
    )
    auc_text = f"PR-AUC {number(pr_auc):.3f}" if pr_auc not in (None, "") else "PR-AUC not available"
    return (
        f"<svg class='pr-chart' viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='Precision-recall curve, {esc(auc_text)}'>"
        f"<rect x='{pad}' y='{pad}' width='{plot}' height='{plot}' fill='none' stroke='#d9e1da'/>"
        f"<text x='{pad}' y='{pad + plot + 14}' class='axis'>0</text>"
        f"<text x='{pad + plot - 20}' y='{pad + plot + 14}' class='axis'>1.0 recall</text>"
        f"<text x='0' y='{pad + 4}' class='axis'>1.0</text>"
        f"<text x='0' y='{pad + plot}' class='axis'>0 prec.</text>"
        f"<polyline points='{coords}' fill='none' stroke='#174b3a' stroke-width='2'/>"
        f"{dots}"
        f"<text x='{pad}' y='{pad - 10}' class='pr-auc-label'>{esc(auc_text)}</text>"
        "</svg>"
    )


NEAREST_REFERENCE_LABELS = {
    "close_reference_match": "Close match to a reference plasmid",
    "no_close_reference": "No close reference in the reference set",
    "insufficient_reference": "Could not be assessed",
    "insufficient_sequence": "Not compared: record too short for a Mash distance",
    "ambiguous_between_references": "Ambiguous: equally close to references in different clusters",
    # Labels written before the screen was renamed; reports from earlier runs
    # still open, and show the same meaning under today's wording.
    "known_cluster": "Close match to a reference plasmid (recorded as 'known_cluster')",
    "novel": "No close reference in the reference set (recorded as 'novel')",
}


def nearest_reference_block(novelty):
    """HTML for a selection report's `plasmid_novelty` mapping, or '' when absent.

    The result is experimental and easy to over-read, so the caveat is part of the
    block and not a footnote: a Mash distance under the threshold is not "95%
    similar" for plasmids, and "no close reference" is not evidence of novelty.
    """
    if not novelty:
        return ""
    rows = []
    for record_id, row in novelty.items():
        status = row.get("cluster_membership_status", "")
        margin = row.get("distance_margin") or row.get("confidence_score") or "-"
        rows.append(
            "<tr><td>{record}</td><td>{status}</td><td>{reference}</td><td>{distance}</td><td>{support}</td>"
            "<td>{margin}</td></tr>".format(
                record=esc(record_id),
                status=esc(NEAREST_REFERENCE_LABELS.get(status, status or "not recorded")),
                reference=esc(" ".join(part for part in (row.get("best_reference_id"), row.get("best_reference_plasmid_name")) if part) or "-"),
                distance=esc(row.get("mash_distance") or "-"),
                support=esc(" / ".join(part for part in (
                    f"p={row['mash_p_value']}" if row.get("mash_p_value") else "",
                    f"shared {row['shared_hashes']}" if row.get("shared_hashes") else "") if part) or "-"),
                margin=esc(margin)))
    return (
        "<details><summary>Nearest-reference screen (experimental, unvalidated)</summary>"
        "<p class='muted'>How close each predicted record is, by Mash distance, to a small curated "
        "set of reference plasmids. It is not a plasmid classification, not evidence of relatedness, "
        "and not a test of novelty. A distance under the threshold does not mean 95% similarity: "
        "two equal-size plasmids sharing about a third of their sequence already pass it, and a "
        "fragment under about a fifth of a reference plasmid can fail it. Each record is judged on "
        "its own, so one plasmid split into contigs can receive different calls.</p>"
        "<table><thead><tr><th>Record</th><th>Call</th><th>Nearest reference</th><th>Mash distance</th>"
        "<th>Support</th><th>Distance margin</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "</details>")


def selection_card(sample, results_dir, report_path):
    """Render a plain-language view of a machine-readable selection report."""
    # Candidates live in one collection directory, each file carrying its sample
    # id; the older per-sample location is still read so existing runs open.
    directory = results_dir / "selected_candidates" / sample
    report_file = directory / f"{sample}.selection_report.json"
    for fallback in (directory / "selection_report.json",
                     results_dir / sample / "selected_candidate" / "selection_report.json",
                     results_dir / sample / "selection_report.json"):
        if report_file.is_file():
            break
        report_file = fallback
    if not report_file.is_file():
        return "<p class='muted'>No selected reconstruction was created for this sample.</p>"
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "<p class='muted'>The selected-reconstruction record could not be read; download the JSON file for inspection.</p>"
    selected_tool = report.get("selected_tool") or "No method selected"
    truth_set = report.get("selection_type") == "truth_set_best_candidate"
    confidence = report.get("confidence_tier", "requires_confirmation")
    confirmation = report.get("long_read_confirmation_reasons") or []
    status = "Benchmark-validated candidate" if truth_set else "Candidate only: operational method recommendation"
    confidence_label = "Ready for routine research review" if confidence == "high" else "Long-read confirmation required"
    metrics = report.get("candidate_metrics") or {}
    score_text = "No complete-reference score is available for this sample."
    if metrics:
        score_text = "Reference comparison: F1 {f1}, plasmid recovery {plasmid}, precision {precision}.".format(
            f1=esc(metrics.get("f1", "-")), plasmid=esc(metrics.get("plasmid_recall", "-")),
            precision=esc(metrics.get("precision", "-")))
    # The selection report names the files it actually copied, so use that
    # rather than a filename convention: the convention changed when candidates
    # were given sample-prefixed names, and this link silently went dead.
    copied = [name for name in (report.get("copied_files") or [])
              if name.endswith(".plasmid.fasta")]
    candidates = [directory / name for name in copied]
    candidates += [directory / f"{sample}.candidate.plasmid.fasta",
                   directory / "candidate.plasmid.fasta"]
    fasta = next((path for path in candidates if path.is_file()), None)
    fasta_link = (f"<a class='download-button' href='{relative_link(fasta, report_path)}' download>Download selected plasmid FASTA</a>"
                  if fasta else "<span class='muted'>No standardized candidate FASTA was available.</span>")
    report_link = f"<a href='{relative_link(report_file, report_path)}' download>Download technical JSON record</a>"
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in confirmation) or "<li>No automated confirmation trigger was recorded.</li>"
    rejected = report.get("rejected_candidates") or []
    alternatives = ", ".join(esc(item.get("tool", "unnamed method")) for item in rejected) or "No alternative scored candidate was recorded."
    agreement = report.get("cross_tool_agreement") or {}
    agreement_text = agreement.get("reason") or (
        f"{agreement.get('status', 'not assessed')} agreement (mean reference-footprint overlap "
        f"{agreement.get('mean_reference_footprint_jaccard', '-')}).")
    structural = report.get("structural_evidence") or {}
    structural_text = (f"{len(structural.get('items', []))} validated source-evidence item(s), including {len(structural.get('validated_closure_items', []))} supported closure item(s)."
                       if structural.get("status") == "validated_source_evidence" else "No validated replicon, MOB, or closure evidence was supplied.")
    return """<div class='selection-card {tone}'>
<div><span class='selection-label'>{status}</span><h3>{sample}: {tool}</h3><p>{score}</p><p><strong>Confidence:</strong> {confidence}</p></div>
<div class='selection-actions'>{fasta}<br>{report}</div>
<details><summary>Why this selection needs review</summary><ul>{reasons}</ul><p><strong>Agreement between methods:</strong> {agreement}</p><p><strong>Structural evidence:</strong> {structural}</p><p><strong>Other evaluated methods:</strong> {alternatives}</p><p class='muted'>This card does not claim that the sequence is closed, circular, or clinically validated.</p></details>
{nearest}
</div>""".format(
        tone="confirmation" if confidence != "high" else "confident", status=esc(status), sample=esc(sample),
        tool=esc(selected_tool), score=score_text, confidence=esc(confidence_label), fasta=fasta_link,
        report=report_link, reasons=reasons, alternatives=alternatives, agreement=esc(agreement_text), structural=esc(structural_text),
        nearest=nearest_reference_block(report.get("plasmid_novelty")))


INLINE_VISUALIZATION_BUDGET = 6 * 1024 * 1024


def stage_visualizations(scores, results_dir, report_path, inline_budget=INLINE_VISUALIZATION_BUDGET):
    """Inline small visualization payloads; publish large ones as sibling files.

    Every sample's alignment blocks embedded in one page does not survive a real
    cohort: at ~219 bytes per retained block a 32-sample run reaches tens of
    megabytes, all parsed before anything renders. Small runs stay a single
    portable file; larger ones are fetched per sample on selection.
    """
    available, inline, total = {}, {}, 0
    for sample in sorted({row["sample"] for row in scores}):
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        available[sample] = len(text)
        total += len(text)
        inline[sample] = payload
    if total <= inline_budget:
        return inline, {}, {"mode": "inline", "bytes": total, "samples": len(inline)}
    # Publish beside the report so the browser can fetch one sample at a time.
    out_dir = report_path.parent / "visualization"
    out_dir.mkdir(parents=True, exist_ok=True)
    external = {}
    for sample in available:
        source = results_dir / sample / "visualization" / "alignment_blocks.json"
        target = out_dir / f"{sample}.json"
        try:
            shutil.copyfile(source, target)
        except OSError:
            continue
        external[sample] = f"visualization/{quote(sample, safe='')}.json"
    return {}, external, {"mode": "external", "bytes": total, "samples": len(external)}


def visual_quality_section(scores, status, results_dir, report_path=None):
    """Return a linked heatmap and reference-coordinate alignment explorer."""
    report_path = report_path or (results_dir / "benchmark.report.html")
    visualizations, external, staging = stage_visualizations(scores, results_dir, report_path)
    state = {(row.get("sample"), row.get("tool")): row.get("status", "scored") for row in status}
    # Runtime and peak RSS are recorded in stage 4; collinear_fraction in stage 5.
    profile = {}
    for row in status:
        try:
            runtime = float(row["runtime_seconds"]) / 60 if row.get("runtime_seconds") else None
            memory = float(row["peak_rss_kb"]) / (1024 * 1024) if row.get("peak_rss_kb") else None
        except (TypeError, ValueError):
            runtime = memory = None
        profile[(row.get("sample"), row.get("tool"))] = {"runtime_seconds": runtime, "peak_rss_kb": memory}
    structural = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "structural_summary.tsv"
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    value = row.get("collinear_fraction")
                    structural[(sample, row.get("tool"))] = float(value) if value else None
        except (OSError, ValueError):
            continue
    matrix = []
    for row in scores:
        tp, fp = number(row.get("TP_bp")), number(row.get("FP_bp"))
        base_f1, plasmid_recall = optional_number(row.get("f1")), optional_number(row.get("plasmid_recall"))
        bin_f1 = optional_number(row.get("bin_f1"))
        contamination = fp / (tp + fp) if tp + fp else None
        components = [(0.45, base_f1), (0.25, plasmid_recall), (0.15, bin_f1),
                      (0.15, 1 - contamination if contamination is not None else None)]
        available = [(weight, value) for weight, value in components if value is not None]
        composite = sum(weight * value for weight, value in available) / sum(weight for weight, _ in available) if available else None
        matrix.append({"sample": row["sample"], "tool": row["tool"], "status": state.get((row["sample"], row["tool"]), "scored"),
                       "f1": number(row.get("f1")), "precision": number(row.get("precision")), "recall": number(row.get("recall")),
                       "plasmid_recall": plasmid_recall, "bin_f1": number(row["bin_f1"]) if row.get("bin_f1") else None,
                       "contamination": contamination, "unmapped": number(row.get("unmapped_pred_bp")), "composite": composite,
                       # Execution cost and structural concordance are already measured;
                       # surfacing them as heatmap metrics needs no new computation.
                       "runtime_min": (profile.get((row["sample"], row["tool"]), {}).get("runtime_seconds") or None),
                       "memory_gb": (profile.get((row["sample"], row["tool"]), {}).get("peak_rss_kb") or None),
                       "collinear": structural.get((row["sample"], row["tool"]))})
    payload = json.dumps({"matrix": matrix, "visualizations": visualizations,
                          "visualization_sources": external, "staging": staging},
                         separators=(",", ":")).replace("<", "\\u003c")
    return """<div id='cohort-evidence-explorer'>
<p class='lead'>Analyses that share the explorer's selection above: per-plasmid recovery, method
agreement, bin assignment, method comparison, dot plots, curated context, protein recovery and
structural diagnostics. They use retained primary PAF blocks on truth-reference coordinates; none of
them is a raw nucleotide alignment or an independent structural-validation claim.</p>
<div class='controls'><label>Sample <select id='vq-sample'></select></label><label>Tool <select id='vq-tool'></select></label><label>Truth plasmid <select id='vq-plasmid'></select></label><button id='vq-fit' type='button'>Fit</button><button id='vq-in' type='button'>Zoom in</button><button id='vq-out' type='button'>Zoom out</button><label>Start <input id='vq-start' type='number' min='0'></label><label>End <input id='vq-end' type='number' min='1'></label><a id='vq-download' class='download-button' download>Download JSON</a></div>
<div class='panel' id='vq-anchor'><div id='vq-tracks' class='muted'>Choose a sample with visualization data.</div><div id='vq-detail' class='insight neutral'></div></div>

<script id='vq-data' type='application/json'>__PAYLOAD__</script><script>
(()=>{const d=JSON.parse(document.getElementById('vq-data').textContent),m=d.matrix,v=d.visualizations,$=id=>document.getElementById(id),samples=[...new Set(m.map(x=>x.sample))].sort(),tools=[...new Set(m.map(x=>x.tool))].sort();let range=null;
const select=(e,items)=>e.innerHTML=items.map(x=>`<option value="${x}">${x}</option>`).join('');
function setTools(){select($('vq-tool'),tools.filter(t=>m.some(r=>r.sample===$('vq-sample').value&&r.tool===t)))}function setPlasmids(){let a=v[$('vq-sample').value];select($('vq-plasmid'),a?Object.keys(a.truth_plasmids).sort():[])}
function draw(){let s=$('vq-sample').value,t=$('vq-tool').value,p=$('vq-plasmid').value,a=v[s];if(!a||!p){$('vq-tracks').textContent='No visualization data. Re-run stage 5 after retaining PAF scoring alignments.';return}let len=a.truth_plasmids[p].length,[lo,hi]=range||[0,len];lo=Math.max(0,Math.min(lo,len-1));hi=Math.max(lo+1,Math.min(hi,len));range=[lo,hi];$('vq-start').value=Math.floor(lo);$('vq-end').value=Math.ceil(hi);$('vq-download').href=s+'/visualization/alignment_blocks.json';let names=Object.keys(a.tools),scale=x=>180+(x-lo)/(hi-lo)*880,svg=`<svg viewBox="0 0 1100 ${55+names.length*38}"><text x="180" y="15" font-size="12">${pbEsc(p)}: ${Math.floor(lo).toLocaleString()}–${Math.ceil(hi).toLocaleString()} / ${len.toLocaleString()} bp</text>`;names.forEach((name,i)=>{let y=40+i*38,z=a.tools[name],rec=z.plasmid_recovery[p]||{},bs=z.blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi);svg+=`<text x="4" y="${y+7}" font-size="12">${name}</text><text x="105" y="${y+7}" font-size="11">${((rec.completeness||0)*100).toFixed(1)}%</text><rect x="180" y="${y-8}" width="880" height="16" fill="#f7f8f5" stroke="#d6ddd5"/>`;bs.forEach((b,i)=>{let x=Math.max(180,scale(b.target_start)),r=Math.min(1060,scale(b.target_end));svg+=`<rect class="vq-block" data-n="${name}" data-i="${i}" x="${x}" y="${y-8}" width="${Math.max(1,r-x)}" height="16" fill="${b.strand==='-'?'#7f5aa2':'#16805a'}"><title>${pbEsc(b.record_id)}</title></rect>`})});a.amr_features.filter(f=>f.sequence_id===p&&f.start>=lo&&f.start<=hi).forEach(f=>{let x=scale(f.start);svg+=`<path d="M${x} 25 l5 -9 l5 9z" fill="#2275ad"><title>${pbEsc(f.label)}</title></path>`});svg+='</svg>';$('vq-tracks').innerHTML=svg+'<p class="muted">Displayed primary blocks; '+names.map(n=>n+': '+a.tools[n].blocks_omitted+' omitted').join(' · ')+'</p>';document.querySelectorAll('.vq-block').forEach(e=>e.onclick=()=>{let b=a.tools[e.dataset.n].blocks.filter(x=>x.target===p&&x.target_end>lo&&x.target_start<hi)[e.dataset.i];$('vq-detail').textContent=`${e.dataset.n} | ${b.record_id} | query ${b.query_start}-${b.query_end}/${b.query_length} | reference ${b.target_start}-${b.target_end} | ${b.strand} strand | identity ${(100*b.matches/Math.max(1,b.block_length)).toFixed(2)}% | MAPQ ${b.mapq}`})}
$('vq-sample').onchange=()=>{range=null;setTools();setPlasmids();draw()};$('vq-tool').onchange=draw;$('vq-plasmid').onchange=()=>{range=null;draw()};$('vq-start').onchange=()=>{range=[+$('vq-start').value,+$('vq-end').value];draw()};$('vq-end').onchange=()=>{range=[+$('vq-start').value,+$('vq-end').value];draw()};$('vq-fit').onclick=()=>{range=null;draw()};$('vq-in').onclick=()=>{if(range){let c=(range[0]+range[1])/2,z=(range[1]-range[0])/2;range=[c-z/2,c+z/2];draw()}};$('vq-out').onclick=()=>{if(range){let c=(range[0]+range[1])/2,z=(range[1]-range[0])*2;range=[c-z/2,c+z/2];draw()}};$('vq-tracks').addEventListener('wheel',e=>{if(!range)return;e.preventDefault();let c=(range[0]+range[1])/2,z=(range[1]-range[0])*(e.deltaY<0?.7:1.4);range=[c-z/2,c+z/2];draw()},{passive:false});select($('vq-sample'),samples);setTools();setPlasmids();draw()})();
</script></div>""".replace("__PAYLOAD__", payload)


def advanced_visual_script():
    """Enhance the base explorer with dot plot, flows, exports, and local bases."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),data=JSON.parse($('vq-data').textContent),tracks=$('vq-tracks'),detail=$('vq-detail');
const dot=document.createElement('div'),flow=document.createElement('div'),actions=document.createElement('span');dot.id='vq-dotplot';flow.id='vq-flow';tracks.after(dot,flow);actions.innerHTML='<button id="vq-svg" type="button">Download track SVG</button><button id="vq-png" type="button">Download track PNG</button>';$('vq-download').after(actions);
function current(){let a=data.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;let lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||a.truth_plasmids[p].length;return {a,p,t,lo,hi,blocks:a.tools[t].blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi)}}
function renderFlow(){let x=current();if(!x){flow.innerHTML='';return}let f=x.a.tools[x.t].bin_assignment_flows||[];flow.innerHTML=f.length?'<h3>Bin-to-truth assignment flow</h3><p class="muted">Only scored bin assignments are shown; unobserved alternative links are not fabricated.</p><ul>'+f.map(r=>`<li>${r.bin_id||'no bin'} → ${r.true_plasmid||r.status}: ${r.aligned_bp.toLocaleString()} bp (${r.status})</li>`).join('')+'</ul>':''}
function local(e){let x=current();if(!x)return;let b=x.blocks[Number(e.target.dataset.i)];if(!b)return;const n=v=>Number(v).toLocaleString();
// Every block carries measured alignment evidence. Only the nucleotide view
// needs a CIGAR, so a block without one still has something to report.
let pct=b.block_length?100*b.matches/b.block_length:0;
let rows=[['Predicted record',b.record_id],
 ['Truth reference',b.target+' ('+String(b.molecule_type||'unknown').toLowerCase()+')'],
 ['Reference span',n(b.target_start)+'–'+n(b.target_end)+'  ('+n(b.target_end-b.target_start)+' bp)'],
 ['Record span',n(b.query_start)+'–'+n(b.query_end)+' of '+n(b.query_length)+' bp'],
 ['Orientation',b.strand==='-'?'reverse (−)':'forward (+)'],
 ['Identity',pct.toFixed(1)+'%  ('+n(b.matches)+'/'+n(b.block_length)+' matching bases)'],
 ['Mapping quality',String(b.mapq)]];
let html='<strong>Selected alignment block</strong><table class="vq-kv">'+rows.map(r=>'<tr><th>'+r[0]+'</th><td>'+pbEsc(r[1])+'</td></tr>').join('')+'</table>';
let a=b.local_alignment;
if(a){let marks=[...a.reference].map((c,i)=>c===a.prediction[i]?' ':'^').join('');
 html+='<strong>Local nucleotide alignment</strong><code>Reference  '+a.reference+'<br>           '+marks+'<br>Prediction '+a.prediction+'</code><p class="muted">'+a.meaning+'</p>'}
else{html+='<p class="muted">No nucleotide view for this block: it carries no <code>cg:Z:</code> CIGAR tag, or it is longer than the display cap. The evidence above is measured from the alignment record itself.</p>'}
detail.innerHTML=html}
document.addEventListener('click',e=>{if(e.target.classList.contains('vq-block'))setTimeout(()=>local(e),0)});['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end','vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(renderFlow,0)));$('vq-fit').addEventListener('click',()=>setTimeout(renderFlow,0));$('vq-in').addEventListener('click',()=>setTimeout(renderFlow,0));$('vq-out').addEventListener('click',()=>setTimeout(renderFlow,0));
function download(name,blob){let a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0)}$('vq-svg').onclick=()=>{let svg=tracks.querySelector('svg');if(svg)download('plasbench-recovery-tracks.svg',new Blob([svg.outerHTML],{type:'image/svg+xml'}))};$('vq-png').onclick=()=>{let svg=tracks.querySelector('svg');if(!svg)return;let image=new Image(),url=URL.createObjectURL(new Blob([svg.outerHTML],{type:'image/svg+xml'}));image.onload=()=>{let c=document.createElement('canvas');c.width=1100;c.height=svg.viewBox.baseVal.height;c.getContext('2d').drawImage(image,0,0);c.toBlob(b=>download('plasbench-recovery-tracks.png',b));URL.revokeObjectURL(url)};image.src=url};renderFlow();})();
</script>"""


def evidence_selection_script():
    """Keep evidence-explorer deep links after retiring its duplicate matrix."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),keys=[['sample','vq-sample'],['tool','vq-tool'],['plasmid','vq-plasmid'],['start','vq-start'],['end','vq-end']];let restoring=false;
function write(){if(restoring)return;const params=new URLSearchParams();keys.forEach(([key,id])=>{const value=$(id)?.value;if(value)params.set(key,value)});history.replaceState(null,'','#'+params.toString())}
function read(){const params=new URLSearchParams(location.hash.slice(1));if(![...params].length)return;restoring=true;for(const [key,id]of keys){const value=params.get(key),element=$(id);if(value!=null&&element){element.value=value;element.dispatchEvent(new Event('change'))}}restoring=false}
window.addEventListener('message',event=>{if(event.source!==$('pb-enterprise')?.contentWindow)return;const value=event.data;if(!value||value.type!=='plasbench-selection'||!value.sample)return;const sample=$('vq-sample');sample.value=value.sample;sample.dispatchEvent(new Event('change'));const tool=$('vq-tool');if(value.tool&&[...tool.options].some(option=>option.value===value.tool)){tool.value=value.tool;tool.dispatchEvent(new Event('change'))}const plasmid=$('vq-plasmid');if(value.plasmid&&[...plasmid.options].some(option=>option.value===value.plasmid)){plasmid.value=value.plasmid;plasmid.dispatchEvent(new Event('change'))}});
keys.forEach(([,id])=>$(id)?.addEventListener('change',()=>setTimeout(write,0)));read();})();
</script>"""


def bin_flow_script():
    """Interactive alluvial bin-to-truth flow.

    Clustering moved to the dashboard's own control; this keeps the flow, which
    is the only rendering of bin_assignment_flows in the report.
    """
    return report_asset("bin_flow_script.html")


def agreement_and_comparison_script():
    """Per-region tool agreement, and a baseline-versus-comparator view.

    Agreement counts how many methods cover each reference interval. It is a
    support count, not a correctness claim: methods sharing a bias agree with
    each other and with nothing else, which the caption states plainly.
    """
    return report_asset("agreement_and_comparison_script.html")


def explorer_chrome_script():
    """Present the analysis panels as the adopted tabbed dashboard.

    The panels are emitted by several independent fragments and used to stack
    flat, then as one long accordion. This groups them into tabs and cards
    without moving any of them out of the element its fragment re-renders into,
    and turns the shared selection row into a context bar.

    The adopted design ships a dark palette and sample data. Only its structure
    and proportions are taken: the colours are the report's, and every value on
    screen still comes from the panel that measured it.
    """
    return report_asset("explorer_chrome_script.html")


def explorer_navigation_script():
    """Search, row management, drag navigation, and event-to-event jumping."""
    return report_asset("explorer_navigation_script.html")


def glossary_script():
    """Attach the glossary to every occurrence of a term in the report.

    A definition on a reference page at the foot of the document is not an
    explanation: the reader meets the term in a column header. This marks each
    occurrence with the definition and the reason it matters, so hovering a
    header answers the question where it is asked.
    """
    entries = {term: glossary_tooltip(term) for term in GLOSSARY}
    for alias, term in GLOSSARY_ALIASES.items():
        entries[alias] = glossary_tooltip(term)
    payload = json.dumps(entries, separators=(",", ":")).replace("<", "\\u003c")
    return ("<style>.term{border-bottom:1px dotted var(--muted);cursor:help}"
            "th .term{border-bottom-color:#8a9a90}</style>"
            f"<script id='pb-glossary' type='application/json'>{payload}</script><script>"
            "(()=>{const G=JSON.parse(document.getElementById('pb-glossary').textContent);"
            "const keys=Object.keys(G).sort((a,b)=>b.length-a.length);"
            "const norm=s=>s.replace(/\\s+/g,' ').trim().replace(/[:\u2014-]$/,'').trim();"
            "function mark(el){const t=norm(el.textContent);"
            "for(const k of keys){if(t===k||t.toLowerCase()===k.toLowerCase()){"
            "el.title=G[k];if(!el.querySelector('.term'))"
            "el.innerHTML='<span class=\"term\">'+el.innerHTML+'</span>';return true}}return false}"
            "function sweep(root){root.querySelectorAll('th,.metric small,label,option,.stat-lab')"
            ".forEach(el=>{if(el.dataset.termed)return;el.dataset.termed='1';mark(el)})}"
            "sweep(document);"
            "if(window.MutationObserver){let queued=false;"
            "new MutationObserver(()=>{if(queued)return;queued=true;"
            "requestAnimationFrame(()=>{queued=false;sweep(document)})})"
            ".observe(document.body,{childList:true,subtree:true})}"
            "})();</script>")


def evidence_explorer_section(project_root, scores, results_dir, vendor_html, panels_html=""):
    """Embed the vendored reconstruction evidence explorer.

    Like the cohort dashboard, the design ships as a whole document that styles
    bare ``*`` and ``body``, so it runs in an isolated frame. Selection changes
    in this report are forwarded to it by postMessage.
    """
    template = Path(project_root) / "assets" / "explorer" / "template.html"
    if not template.is_file():
        return ""
    try:
        import build_explorer_view as explorer
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_explorer_view as explorer

    visualizations, structural = {}, {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if path.is_file():
            try:
                visualizations[sample] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        calls = results_dir / sample / "visualization" / "structural_calls.json"
        if calls.is_file():
            try:
                structural[sample] = json.loads(calls.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    if not visualizations:
        return ""

    versions = read_tool_versions(results_dir / "run_manifest.json")
    data = explorer.build(visualizations, structural, versions)
    if not data["samples"]:
        return ""
    document = explorer.render(template, data, vendor_html)
    # HTML's script-end-tag matching is case-insensitive ("</SCRIPT>" closes a
    # <script> element just as well), so the guard must be too, or a crafted
    # record id/label breaks out of this wrapping template tag.
    encoded = re.sub(r"</script", SCRIPT_END_SENTINEL, document, flags=re.IGNORECASE)
    # The report's own sample and plasmid controls drive the frame, so one
    # selection is followed everywhere instead of being re-picked inside it.
    return ("<div id='pb-explorer-view'><h3>Reconstruction evidence explorer</h3>"
            "<p class='lead'>Alignment blocks, structural calls, bin relationships and reference "
            "annotation for one truth plasmid at a time. Identity, mapping quality and every span are "
            "measured from this run. Read depth is not computed by projection scoring, so per-segment "
            "coverage reads “not measured” rather than zero, and the nucleotide view resolves only "
            "where a CIGAR-bounded local alignment exists.</p>"
            "<div class='panel' style='padding:0'>" + lazy_frame_note("reconstruction evidence explorer")
            + "<iframe id='pb-explorer' "
            "title='PlasBench reconstruction evidence explorer' "
            "style='width:100%;height:1180px;border:0;display:block'></iframe></div>"
            f"<script id='pb-explorer-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-explorer');"
            + lazy_frame_js("pb-explorer-doc") + "lazyFrame(f);"
            "const push=()=>{const s=document.getElementById('vq-sample'),"
            "p=document.getElementById('vq-plasmid');if(!f.contentWindow)return;"
            "f.contentWindow.postMessage({pbExplorer:'select',"
            "sample:s?s.value:null,plasmid:p?p.value:null},'*')};"
            # The explorer is emitted above the controls it follows, so the
            # listener is delegated rather than bound to elements that do not
            # exist yet when this runs.
            "document.addEventListener('change',e=>{"
            "if(e.target&&(e.target.id==='vq-sample'||e.target.id==='vq-plasmid'))"
            "setTimeout(push,60)},true);"
            "f.addEventListener('load',()=>setTimeout(push,150));"
            # Focus chosen inside the frame drives the panels below it, so one
            # method or record is followed everywhere rather than re-picked.
            "window.addEventListener('message',e=>{const m=e.data;"
            "if(!m||!m.pbExplorerSelected)return;"
            "const set=(id,v)=>{const el=document.getElementById(id);"
            "if(!el||!v||el.value===v)return;el.value=v;"
            "el.dispatchEvent(new Event('change',{bubbles:true}))};"
            "set('vq-sample',m.sample);set('vq-plasmid',m.plasmid);set('vq-tool',m.tool);"
            "if(m.record){const r=[...document.querySelectorAll('#pb-explorer-view select')]"
            ".find(s=>!s.id&&[...s.options].some(o=>o.value===m.record));"
            "if(r&&r.value!==m.record){r.value=m.record;"
            "r.dispatchEvent(new Event('change',{bubbles:true}))}}});"
            "})();</script>"
            + panels_html + "</div>")


def evidence_section(evidence_html):
    """The reconstruction evidence explorer (and the panels that follow it) as its own section, `evidence-explorer`, listed with the plasmid maps."""
    if not evidence_html:
        return ""
    return "<section id='evidence-explorer'>" + evidence_html.replace(
        "<h3>Reconstruction evidence explorer</h3>", "<h2>Reconstruction evidence explorer</h2>", 1) + "</section>"


def enterprise_view_section(project_root, scores, status, leaderboard, metadata,
                            results_dir, vendor_html, evidence_html=""):
    """Embed the vendored enterprise dashboard, driven by measured results.

    The dashboard is rendered inside an isolated iframe. Its stylesheet styles
    bare `*` and `body`, so inlining it into this page would restyle the whole
    report; the iframe keeps the adopted look byte-for-byte without leaking.
    """
    template = Path(project_root) / "assets" / "enterprise" / "template.html"
    if not template.is_file():
        return ""
    try:
        import build_enterprise_view as enterprise
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_enterprise_view as enterprise

    visualizations = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "visualization" / "alignment_blocks.json"
        if path.is_file():
            try:
                visualizations[sample] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    structural = {}
    for sample in {row["sample"] for row in scores}:
        path = results_dir / sample / "structural_summary.tsv"
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    value = row.get("collinear_fraction")
                    structural[(sample, row.get("tool"))] = float(value) if value else None
        except (OSError, ValueError):
            continue
    capabilities = {}
    registry = Path(project_root) / "config" / "tool_capabilities.tsv"
    if registry.is_file():
        with registry.open(encoding="utf-8", newline="") as handle:
            capabilities = {row["tool"]: row for row in csv.DictReader(handle, delimiter="\t")}
    versions = read_tool_versions(results_dir / "run_manifest.json")

    manifest_version = "version not recorded"
    manifest_path = results_dir / "run_manifest.json"
    if manifest_path.is_file():
        try:
            manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "tool_version", manifest_version)
        except (OSError, json.JSONDecodeError):
            pass
    data = enterprise.build(scores, status, leaderboard, metadata, capabilities,
                            versions, visualizations, structural, manifest_version)
    document = enterprise.render(template, data, vendor_html)
    # The iframe is written from a template script tag rather than srcdoc so the
    # document needs no HTML-entity escaping of its own markup.
    # Escape only what would close the outer template tag; the frame script
    # restores it before handing the document to srcdoc.
    encoded = re.sub(r"</script", SCRIPT_END_SENTINEL, document, flags=re.IGNORECASE)
    return ("<section id='enterprise'><h2>Interactive cohort dashboard</h2>"
            "<p class='lead'>The adopted enterprise dashboard, driven entirely by this run's measured "
            "results. Values that were never measured render as “not measured” rather than as zero. "
            "It runs in an isolated frame so its own stylesheet cannot restyle this report.</p>"
            "<div class='panel' style='padding:0'>" + lazy_frame_note("interactive cohort dashboard")
            + "<iframe id='pb-enterprise' title='PlasBench interactive cohort dashboard' "
            "style='width:100%;min-height:900px;height:1240px;border:0;display:block'></iframe></div>"
            f"<script id='pb-enterprise-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-enterprise');"
            + lazy_frame_js("pb-enterprise-doc") + "lazyFrame(f);"
            "window.addEventListener('message',event=>{if(event.source!==f.contentWindow)return;"
            "const value=event.data;if(!value||value.type!=='plasbench-enterprise-height')return;"
            "const height=Number(value.height);if(!Number.isFinite(height)||height<1)return;"
            "f.style.height=Math.max(900,Math.min(50000,Math.ceil(height)+24))+'px';});})();</script>"
            + "</section>" + evidence_section(evidence_html))


def vendor_assets(project_root):
    """Inline the vendored font and icon assets as base64.

    The report must render identically offline and years later, so it carries
    its own faces rather than requesting a CDN at view time. A missing vendor
    directory degrades to system fonts instead of failing the build.
    """
    vendor = Path(project_root) / "assets" / "vendor"
    fonts = vendor / "fonts"
    inter_css, icon_css = vendor / "inter.css", vendor / "fontawesome-subset.css"
    if not (inter_css.is_file() and icon_css.is_file()):
        return ("<style>/* Vendored web fonts absent; falling back to system faces. "
                "Run assets/vendor setup to restore the packaged appearance. */</style>")

    def data_uri(name):
        path = fonts / name
        if not path.is_file():
            return None
        return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    inter = inter_css.read_text(encoding="utf-8")
    inter_uri = data_uri("inter-variable.woff2")
    if inter_uri:
        inter = re.sub(r"url\(fonts/inter-[^)]+\)", f"url({inter_uri})", inter)
    icons = icon_css.read_text(encoding="utf-8")
    icon_uri = data_uri("fa-solid-900.woff2")
    icons = icons.replace("__FA_WOFF2__", icon_uri) if icon_uri else ""
    return f"<style>\n{inter}\n{icons}\n</style>"


def humanise_tool_labels_script(tools):
    """Translate reader-facing names while keeping IDs and download paths stable."""
    labels = {tool: display_tool_name(tool) for tool in tools}
    return """<script>
(()=>{const labels=%s,raw=Object.keys(labels);if(!raw.length)return;
const pattern=new RegExp('\\\\b('+raw.map(x=>x.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')).join('|')+')\\\\b','g');
const skip=new Set(['SCRIPT','STYLE','CODE','PRE','A','OPTION']);
const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),nodes=[];
while(walk.nextNode())nodes.push(walk.currentNode);
nodes.forEach(node=>{if(skip.has(node.parentElement?.tagName))return;
 node.nodeValue=node.nodeValue.replace(pattern,value=>labels[value]||value);});
})();</script>""" % json.dumps(labels, sort_keys=True)


def lazy_visualization_script():
    """Fetch per-sample alignment payloads on demand when they were published.

    Loading every sample up front is what makes a large cohort report unusable,
    so external mode resolves one sample at a time and caches it. A file:// open
    cannot fetch siblings, so that failure is reported as an instruction rather
    than as missing data.
    """
    return """<style>
#vq-loading{font:12px Arial,sans-serif;color:#5f6d6b;margin:6px 0}
#vq-loading.busy::before{content:'\\u25CF ';color:#c68221}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const sources=d.visualization_sources||{},staging=d.staging||{};
if(!Object.keys(sources).length)return;                    // inline mode: nothing to do
const note=document.createElement('div');note.id='vq-loading';$('vq-tracks').before(note);
note.textContent=`Alignment detail is published per sample (${staging.samples} file(s), ${(staging.bytes/1048576).toFixed(1)} MB total) and loads on selection.`;
const cache=new Map();let token=0;
async function load(sample){
 if(d.visualizations[sample])return d.visualizations[sample];
 if(cache.has(sample))return cache.get(sample);
 const url=sources[sample];if(!url)return null;
 const mine=++token;note.className='busy';note.textContent=`Loading alignment detail for ${sample}\\u2026`;
 try{const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);
  const payload=await r.json();cache.set(sample,payload);d.visualizations[sample]=payload;
  if(mine===token){note.className='';note.textContent=`Loaded ${sample}. Detail for other samples loads on selection.`}
  return payload}
 catch(err){if(mine===token){note.className='';
   note.innerHTML='Could not load <code>'+url+'</code>. A report opened directly from the file system cannot read sibling files. Serve the report directory instead, for example <code>python -m http.server</code> in the results folder, then reload over http://localhost:8000.'}
  return null}}
// Re-dispatch the selection once data has arrived so the existing views redraw.
async function ensure(){const s=$('vq-sample').value;if(!s||d.visualizations[s])return;
 const payload=await load(s);if(payload){$('vq-sample').dispatchEvent(new Event('change'))}}
$('vq-sample').addEventListener('change',()=>{setTimeout(ensure,0)},true);
ensure();})();
</script>"""


def plasmid_summary_script():
    """Add a per-truth-plasmid summary table and surface contamination on tracks.

    The base track view filters blocks to the selected plasmid, so a predicted
    record that is partly chromosomal renders identically to a clean one. This
    flags those records instead of leaving the contamination invisible.
    """
    return report_asset("plasmid_summary_script.html")


def context_visual_script():
    """Render supplied contextual annotations and a truth-scoped circular map."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),host=document.createElement('div');host.id='vq-context';$('vq-dotplot').after(host);
function render(){let a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t]){host.innerHTML='';return}let features=(a.context_features||[]).filter(f=>f.sequence_id===p),types={};features.forEach(f=>(types[f.feature_type]??=[]).push(f));let html='<h3>Context and circular-truth view</h3>';if(a.circular_truth_plasmids?.includes(p)){let len=a.truth_plasmids[p].length,intervals=a.tools[t].plasmid_recovery[p]?.covered_intervals||[],arc=(s,e)=>{let A=s/len*2*Math.PI-Math.PI/2,B=e/len*2*Math.PI-Math.PI/2,x1=120+80*Math.cos(A),y1=100+80*Math.sin(A),x2=120+80*Math.cos(B),y2=100+80*Math.sin(B),large=B-A>Math.PI?1:0;return `<path d="M${x1} ${y1} A80 80 0 ${large} 1 ${x2} ${y2}" fill="none" stroke="#16805a" stroke-width="14"/>`};html+='<p class="muted">Circular truth plasmid only. Green arcs are recovered reference intervals; this does not claim the predicted output is circular or closed.</p><svg viewBox="0 0 240 200" width="240"><circle cx="120" cy="100" r="80" fill="none" stroke="#e2e8e2" stroke-width="14"/>'+intervals.map(x=>arc(x[0],x[1])).join('')+'<text x="75" y="104" font-size="11">truth circular</text></svg>'}if(features.length){html+='<p><strong>Curated contextual features</strong></p><ul>'+Object.entries(types).map(([k,v])=>`<li>${k}: ${v.map(f=>`${pbEsc(f.label)} (${f.start}-${f.end}; ${pbEsc(f.source)} ${pbEsc(f.version)})`).join(', ')}</li>`).join('')+'</ul>'}else html+='<p class="muted">No versioned replicon, MOB, insertion-sequence, or AMR-context feature table was supplied.</p>';host.innerHTML=html}['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));render()})();
</script>"""


def record_dotplot_script():
    """Use one predicted-record coordinate system per dot plot."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),select=document.createElement('select'),label=document.createElement('label');label.textContent='Predicted record ';label.append(select);$('vq-tool').closest('label').after(label);
function state(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;return a&&a.tools[t]?{a,p,t}:null}
function render(){const x=state();if(!x||!x.p){select.innerHTML='';return}const records=[...new Set(x.a.tools[x.t].blocks.filter(b=>b.target===x.p).map(b=>b.record_id))].sort();select.innerHTML=records.map(r=>`<option value="${pbEsc(r)}">${pbEsc(r)}</option>`).join('');draw()}
function draw(){const x=state(),record=select.value;if(!x||!record)return;const blocks=x.a.tools[x.t].blocks.filter(b=>b.target===x.p&&b.record_id===record).map((b,i)=>Object.assign({__i:i},b)),query=Math.max(...blocks.map(b=>b.query_length),1),truth=x.a.truth_plasmids[x.p].length,sx=v=>30+v/truth*420,sy=v=>450-v/query*420;const lines=blocks.map(b=>`<line class="dpl" data-i="${b.__i}" x1="${sx(b.target_start)}" y1="${sy(b.query_start)}" x2="${sx(b.target_end)}" y2="${sy(b.query_end)}" stroke="${b.strand==='-'?'#7f5aa2':'#16805a'}" stroke-width="3" style="cursor:pointer"><title>${pbEsc(b.record_id)} ${b.target_start.toLocaleString()}–${b.target_end.toLocaleString()} on ${pbEsc(b.target)}, ${b.strand==='-'?'reverse':'forward'} strand, ${(100*b.matches/Math.max(1,b.block_length)).toFixed(1)}% identity, mapQ ${b.mapq}</title></line>`).join('');$('vq-dotplot').innerHTML=`<h3>Dot plot: ${pbEsc(record)} vs ${pbEsc(x.p)}</h3><p class="muted">One predicted-record coordinate system is shown at a time. Forward diagonals support collinearity; reverse diagonals show reverse orientation. This is a diagnostic, not structural validation.</p><svg viewBox="0 0 480 480" width="480" role="img" aria-label="Dot plot"><rect x="30" y="30" width="420" height="420" fill="#f7f8f5" stroke="#849387"/>${lines}<text x="180" y="475" font-size="11">truth plasmid coordinate</text><text x="2" y="20" font-size="11">predicted-record coordinate</text></svg>`}
['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(draw,0)));select.addEventListener('change',draw);render()})();
</script>"""


def structural_and_feature_tracks_script():
    """Overlay contextual features and expose structural diagnostics in HTML."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const host=document.createElement('div');host.id='vq-structural';$('vq-context').after(host);
const colors={replicon:'#5b7fb6',mob:'#9b59b6',insertion_sequence:'#d06d28',amr_context:'#1f8a70'};
function current(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;return {a,p,t,lo:Number($('vq-start').value)||0,hi:Number($('vq-end').value)||a.truth_plasmids[p].length}}
function overlay(){const x=current();if(!x)return;const svg=$('vq-tracks').querySelector('svg');if(!svg)return;svg.querySelectorAll('[data-context-feature]').forEach(n=>n.remove());const scale=v=>180+(v-x.lo)/(x.hi-x.lo)*880;(x.a.context_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi).forEach(f=>{const y=17,color=colors[f.feature_type]||'#5f6d6b',left=Math.max(180,scale(f.start)),right=Math.min(1060,scale(f.end));const r=document.createElementNS('http://www.w3.org/2000/svg','rect');r.setAttribute('data-context-feature','1');r.setAttribute('x',left);r.setAttribute('y',y);r.setAttribute('width',Math.max(2,right-left));r.setAttribute('height','6');r.setAttribute('fill',color);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${f.feature_type}: ${f.label} (${f.source} ${f.version})`;r.append(title);svg.append(r)});}
function render(){const x=current();if(!x){host.innerHTML='';return}const s=x.a.tools[x.t].structural_diagnostics||{};host.innerHTML='<h3>Structural alignment diagnostics</h3><p class="muted">Computed from all retained scoring blocks, not only blocks displayed in the SVG. This is a triage proxy, not a validated misassembly call.</p><div class="panel"><table><thead><tr><th>Concordance proxy</th><th>Breakpoints</th><th>Reverse blocks</th><th>Multi-target records</th><th>Order conflicts</th></tr></thead><tbody><tr><td>'+((s.structural_concordance_proxy??'-'))+'</td><td>'+(s.alignment_breakpoints??'-')+'</td><td>'+(s.reverse_orientation_blocks??'-')+'</td><td>'+(s.multi_truth_target_records??'-')+'</td><td>'+(s.order_conflicts??'-')+'</td></tr></tbody></table></div>';overlay()}
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('click',()=>setTimeout(render,0)));render()})();
</script>"""


def protein_annotation_script():
    """Render standardized protein labels without overstating functional proof."""
    return """<style>
#vq-proteins{margin-top:16px}.vq-protein-controls{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0;font:12px Arial,sans-serif}
#vq-proteins table{min-width:680px}.vq-protein-status{font-weight:bold}.vq-protein-status.complete{color:#087250}.vq-protein-status.partial{color:#9a5b00}.vq-protein-status.missing{color:#a53028}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),host=document.createElement('div');host.id='vq-proteins';($('vq-structural')||$('vq-tracks')).after(host);
const high=new Set(['amr','replication','mobility','maintenance','mobile_element']),colors={amr:'#2275ad',replication:'#5b7fb6',mobility:'#9b59b6',maintenance:'#16805a',mobile_element:'#d06d28',hypothetical:'#8b9292',other:'#64736a'};
function state(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t])return null;return {a,p,t,lo:Number($('vq-start').value)||0,hi:Number($('vq-end').value)||a.truth_plasmids[p].length}}
function label(f){return f.gene||f.product||f.feature_id||'CDS'}
function status(f,pred){const n=Math.max(0,...pred.filter(x=>x.sequence_id===f.sequence_id&&x.end>f.start&&x.start<f.end).map(x=>x.projection_fraction||0));return n>=.95?'complete':n>=.3?'partial':'missing'}
function overlay(){const x=state(),svg=$('vq-tracks').querySelector('svg');if(!x||!svg)return;svg.querySelectorAll('[data-protein-feature]').forEach(n=>n.remove());const width=Math.max(1,x.hi-x.lo),scale=v=>180+(v-x.lo)/width*880,truth=(x.a.protein_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi),pred=(x.a.tools[x.t].protein_features||[]).filter(f=>f.sequence_id===x.p&&f.end>x.lo&&f.start<x.hi),names=Object.keys(x.a.tools),row=names.indexOf(x.t);
 function arrow(f,y,opacity){const left=Math.max(180,scale(f.start)),right=Math.min(1060,scale(f.end)),tip=Math.min(7,Math.max(2,right-left));const forward=f.strand!=='-';const points=forward?`${left},${y} ${right-tip},${y} ${right},${y+4} ${right-tip},${y+8} ${left},${y+8}`:`${right},${y} ${left+tip},${y} ${left},${y+4} ${left+tip},${y+8} ${right},${y+8}`;const n=document.createElementNS('http://www.w3.org/2000/svg','polygon');n.setAttribute('data-protein-feature','1');n.setAttribute('points',points);n.setAttribute('fill',colors[f.category]||colors.other);n.setAttribute('fill-opacity',opacity);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`${label(f)} | ${f.product||'unlabelled CDS'} | ${f.category||'other'} | ${f.source} ${f.version}`;n.append(title);svg.append(n);if(high.has(f.category)&&right-left>28){const text=document.createElementNS('http://www.w3.org/2000/svg','text');text.setAttribute('data-protein-feature','1');text.setAttribute('x',left);text.setAttribute('y',y-2);text.setAttribute('font-size','9');text.textContent=label(f);svg.append(text)}}
 truth.forEach(f=>arrow(f,26,.9));pred.forEach(f=>arrow(f,40+row*38+10,.72));}
 function render(){const x=state();if(!x)return;const truth=(x.a.protein_features||[]).filter(f=>f.sequence_id===x.p),pred=x.a.tools[x.t].protein_features||[];const categories=[...new Set(truth.map(f=>f.category||'other'))].sort();host.innerHTML='<h3>Protein annotations and coordinate recovery</h3><p class="muted">Names are standardized annotation products. Recovery is projected through nucleotide alignments and is not amino-acid identity, orthology, frameshift, or closure evidence.</p><div class="vq-protein-controls"><label>Category <select id="vq-protein-category"><option value="">All</option>'+categories.map(c=>`<option value="${c}">${c}</option>`).join('')+'</select></label><label>Search <input id="vq-protein-search" type="search" placeholder="gene or product"></label><span>Truth CDS: '+truth.length+' · mapped predicted CDS: '+pred.length+'</span></div><div class="panel"><table><thead><tr><th>Protein</th><th>Product</th><th>Category</th><th>Truth coordinates</th><th>Projected recovery</th><th>Annotation provenance</th></tr></thead><tbody id="vq-protein-body"></tbody></table></div>';
 const refresh=()=>{const q=($('vq-protein-search').value||'').toLowerCase(),c=$('vq-protein-category').value,shown=truth.filter(f=>(!c||f.category===c)&&(!q||(`${label(f)} ${f.product||''} ${f.dbxref||''}`).toLowerCase().includes(q)));$('vq-protein-body').innerHTML=shown.map(f=>{const s=status(f,pred);return `<tr><td>${pbEsc(label(f))}</td><td>${pbEsc(f.product||'hypothetical protein')}</td><td>${f.category||'other'}</td><td>${f.start}-${f.end} (${f.strand})</td><td><span class="vq-protein-status ${s}">${s==='complete'?'coordinate-complete':s==='partial'?'coordinate-partial':'not projected'}</span></td><td>${f.source} ${f.version} · ${f.confidence}</td></tr>`}).join('')||'<tr><td colspan="6">No protein annotations match this filter. Enable standardized annotation to populate this view.</td></tr>'};$('vq-protein-category').addEventListener('change',refresh);$('vq-protein-search').addEventListener('input',refresh);refresh();overlay()}
 ['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('click',()=>setTimeout(render,0)));render()})();
</script>"""


def resolve_results_dir(scores_path, out):
    """The results directory is the folder that holds --scores, not the parent of --out.

    Every per-sample file (bin matches, selected candidates, maps, visualisations) and every
    benchmark.*.tsv table the report reads lives beside scores.tsv. Taking the folder from --out
    silently turned about ten sections into 'Not run' whenever the report was written elsewhere."""
    scores_dir = Path(scores_path).resolve().parent
    results_dir = scores_dir
    if not scores_dir.is_dir():
        results_dir = out.parent
        print(f"WARNING: the folder of --scores ({scores_dir}) does not exist; "
              f"reading results from the parent of --out: {results_dir}", file=sys.stderr)
    if not any(results_dir.glob("benchmark.*.tsv")):
        print(f"WARNING: {results_dir} contains no benchmark.*.tsv tables; sections that read them "
              f"will show 'Not run'. Point --scores at the results folder.", file=sys.stderr)
    if out.parent != results_dir:
        print(f"Note: report written to {out.parent}; results are read from {results_dir}", file=sys.stderr)
    return results_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--data-dir", help="Optional DATA_DIR, to surface per-sample difficulty_features.tsv "
                                       "(python/compute_difficulty_features.py) when RUN_DIFFICULTY_FEATURES=1.")
    ap.add_argument("--scores", required=True)
    ap.add_argument("--tool-status", required=True)
    ap.add_argument("--leaderboard", required=True)
    ap.add_argument("--sample-sheet", help="Optional curated sample-sheet TSV for cohort filters.")
    ap.add_argument("--manifest", help="Optional run manifest used to show/filter tool versions.")
    ap.add_argument("--comparisons", help="Optional paired-comparison TSV from aggregation.")
    ap.add_argument("--score-failures", help="Optional score failure TSV from stage 5.")
    ap.add_argument("--recommendations", help="Optional coverage-gated operational recommendation TSV.")
    ap.add_argument("--recommendation-validation", help="Optional leave-one-study-out recommendation validation TSV.")
    ap.add_argument("--cohort-qc-flags", help="Optional advisory cohort outlier-flagging TSV (flag_cohort_outliers.py).")
    ap.add_argument("--recovery-by-replicon", help="Optional descriptive recovery-by-replicon/MOB TSV (stratify_recovery.py).")
    ap.add_argument("--quast-diagnostics", help="Optional QUAST supplementary diagnostics TSV (run_quast_diagnostics.py, RUN_QUAST_DIAGNOSTICS=1).")
    ap.add_argument("--rank-robustness", help="Optional ranking-robustness TSV (rank_sensitivity.py).")
    ap.add_argument("--truth-label-audit", help="Optional advisory truth-label audit TSV (audit_truth_labels.py).")
    ap.add_argument("--stratified", help="Optional evidence-gated stratified performance TSV (select_operational_method.py).")
    ap.add_argument("--orthogonal-summary", help="Optional orthogonal-validation summary JSON (validate_orthogonal_evidence.py).")
    ap.add_argument("--dimensions-prefix", help="Prefix of the stage-6 dimension tables (<prefix>.accuracy.tsv, .feature_preservation.tsv, .bin_quality.tsv, .performance.tsv, .power.tsv, .scenarios.tsv, .composite.tsv, ...); rendered by report_dimensions.py.")
    # Scoring specification and panel sections (python/report_scoring_spec.py).
    ap.add_argument("--label-schemes", help="benchmark.label_schemes.tsv (label_schemes.py collect)")
    ap.add_argument("--label-scheme-summary", help="benchmark.label_scheme_summary.tsv")
    ap.add_argument("--truth-provenance", help="benchmark.truth_provenance.tsv (reference tiers, truth grades)")
    ap.add_argument("--outcome-states", help="benchmark.outcome_states.tsv (aggregate_results.py)")
    ap.add_argument("--recommender-eval", help="benchmark.recommender_eval.tsv (evaluate_recommender.py)")
    ap.add_argument("--recommender-verdict", help="benchmark.recommender_verdict.json")
    ap.add_argument("--warning-eval", help="benchmark.warning_eval.tsv (evaluate_warnings.py)")
    ap.add_argument("--leave-taxon-out", help="benchmark.leave_taxon_out.tsv (leave_taxon_out.py)")
    ap.add_argument("--amr-placement", help="benchmark.amr_placement.tsv (score_amr_placement.py collect)")
    ap.add_argument("--contig-crosscheck", help="benchmark.contig_crosscheck.tsv (contig_crosscheck.py compare)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    project = Path(args.project_root).resolve()
    out = Path(args.out).resolve()
    results_dir = resolve_results_dir(args.scores, out)
    scores = read_tsv(args.scores)
    status = read_tsv(args.tool_status) if Path(args.tool_status).is_file() else []
    leaderboard = read_tsv(args.leaderboard)
    # Rank WITHIN each analysis track, never across them. The pooled file is
    # kept only as a fallback for a results directory written before per-track
    # leaderboards existed.
    track_leaderboards = read_track_leaderboards(args.leaderboard)
    metadata = read_sample_metadata(args.sample_sheet)
    tool_versions = read_tool_versions(args.manifest)
    comparisons = read_tsv(args.comparisons) if args.comparisons and Path(args.comparisons).is_file() else []
    score_failures = read_tsv(args.score_failures) if args.score_failures and Path(args.score_failures).is_file() else []
    recommendations = read_tsv(args.recommendations) if args.recommendations and Path(args.recommendations).is_file() else []
    recommendation_validation = read_tsv(args.recommendation_validation) if args.recommendation_validation and Path(args.recommendation_validation).is_file() else []
    cohort_qc_flags = read_tsv(args.cohort_qc_flags) if args.cohort_qc_flags and Path(args.cohort_qc_flags).is_file() else []
    recovery_by_replicon = (read_tsv(args.recovery_by_replicon)
                            if args.recovery_by_replicon and Path(args.recovery_by_replicon).is_file() else [])
    quast_diagnostics = (read_tsv(args.quast_diagnostics)
                         if args.quast_diagnostics and Path(args.quast_diagnostics).is_file() else [])
    rank_robustness = (read_tsv(args.rank_robustness)
                       if args.rank_robustness and Path(args.rank_robustness).is_file() else [])
    truth_label_audit = (read_tsv(args.truth_label_audit)
                         if args.truth_label_audit and Path(args.truth_label_audit).is_file() else [])
    stratified_rows = (read_tsv(args.stratified)
                       if args.stratified and Path(args.stratified).is_file() else [])
    orthogonal_summary = {}
    if args.orthogonal_summary and Path(args.orthogonal_summary).is_file():
        try:
            orthogonal_summary = json.loads(Path(args.orthogonal_summary).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            orthogonal_summary = {}
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    tools = sorted({row["tool"] for row in scores} | {row["tool"] for row in status})
    samples = sorted({row["sample"] for row in scores} | {row["sample"] for row in status})
    difficulty_features = read_difficulty_features(args.data_dir, samples)
    organisms = sorted({row.get("organism") or "" for row in metadata.values()} - {""})
    technologies = sorted({row.get("truth_technology") or "" for row in metadata.values()} - {""})
    tiers = sorted({row.get("truth_quality_tier") or "" for row in metadata.values()} - {""})
    origins = sorted({row.get("sample_origin") or "" for row in metadata.values()} - {""})
    versions = sorted(set(tool_versions.values()))
    track_counts = Counter(row.get("analysis_track") or "short_read" for row in scores)
    tracks = sorted(track_counts)
    if not track_leaderboards:
        track_leaderboards = {(tracks[0] if tracks else "short_read"): leaderboard}
    # Every headline claim ("leading method", the summary cards, the metric
    # chart) is made about ONE track -- the one carrying most of this run's
    # observations -- and says so, rather than silently topping a mixed table.
    headline_track = (track_counts.most_common(1)[0][0] if track_counts
                      else next(iter(track_leaderboards)))
    headline_leaderboard = track_leaderboards.get(headline_track) or leaderboard
    # Headline claims are about the primary task present (reconstruction,
    # ranked by length-weighted binning F1), never a mix of tasks.
    headline_leaderboard = primary_task_rows(headline_leaderboard)
    multi_track = len(track_leaderboards) > 1
    status_counts = Counter(row["status"] for row in status)
    best = headline_leaderboard[0] if headline_leaderboard else None
    score_by_sample = defaultdict(list)
    score_by_tool = defaultdict(list)
    for row in scores:
        score_by_sample[row["sample"]].append(row)
        score_by_tool[row["tool"]].append(row)

    def significance_text(row):
        """Human-readable rendering of aggregate_results.py's
        significant_vs_runner_up: True/False/"not_assessed" (as a raw TSV
        string) -> a labeled statement naming the exact test, never a bare
        yes/no that could be mistaken for an unsupported eyeball comparison."""
        raw = (row.get("significant_vs_runner_up") or "").strip().lower()
        if raw in ("true", "1"):
            return "significant", "Yes (paired permutation, Holm p<0.05)"
        if raw in ("false", "0"):
            return "not-significant", "No (paired permutation)"
        return "not-assessed", "Not assessed (too few shared samples)"

    def leaderboard_row_html(row):
        sig_class, sig_text = significance_text(row)
        return (
            "<tr><td>{rank}</td><td>{tool}</td><td>{scored}</td><td>{completed}</td>"
            "<td>{failed}</td><td>{skipped}</td><td>{precision}</td><td>{recall}</td><td>{plasmid_recall}</td><td>{perfect}</td><td>{strict}</td><td>{bin_f1}</td><td>{nmi}</td><td>{vi}</td><td>{pr_auc}</td>"
            "<td><strong class='score {band}'>{score}</strong><span class='f1-bar {band}'><i style='width:{f1_width}%'></i></span>{ranked_on}</td>"
            "<td>{ci}</td><td>{cprr}</td><td>{f1}</td>"
            "<td><span class='sig-badge {sig_class}'>{sig_text}</span></td></tr>".format(
                rank=esc(row.get("rank", "-")), tool=esc(row["tool"]),
                scored=esc(row.get("n_samples", "0")), completed=esc(row.get("n_completed", "0")),
                failed=esc(row.get("n_failed", "0")), skipped=esc(row.get("n_skipped", "0")),
                precision=esc(row["mean_precision"]), recall=esc(row["mean_recall"]),
                plasmid_recall=esc(row.get("mean_plasmid_recall") or "not annotated"),
                perfect=esc(rate_text(row.get("reference_perfect_recovery_rate"), row.get("n_reference_perfect_assessed"))),
                strict=esc(rate_text(row.get("strict_reference_reconstruction_rate"), row.get("n_strict_reconstruction_assessed"))),
                bin_f1=esc(row.get("mean_bin_f1") or "not bin-scored"),
                nmi=esc(row.get("mean_nmi") or "not bin-scored"),
                vi=esc(row.get("mean_variation_of_information") or "not bin-scored"),
                pr_auc=esc(row.get("mean_pr_auc") or "not probability-scored"), f1=esc(row.get("mean_f1") or "-"),
                score=esc(f"{headline_value(row):.4f}" if headline_value(row) is not None else "-"),
                f1_width=max(0, min(100, round((headline_value(row) or 0) * 100))),
                band=score_band(headline_value(row) or 0),
                ci=esc(f"{row['ranking_ci_low']}–{row['ranking_ci_high']}" if row.get("ranking_ci_low") else "< 5 independent units"),
                cprr=esc((f"{number(row['cprr']):.1%} ({row.get('cprr_correct')}/{row.get('cprr_plasmids')})"
                          + (f"; per isolate {number(row['cprr_isolate_mean']):.1%}"
                             if row.get("cprr_isolate_mean") else "")
                          + (f"; AUC {number(row['cprr_auc']):.3f}" if row.get("cprr_auc") else ""))
                         if row.get("cprr") else "not bin-scored"),
                ranked_on=(f"<small class='muted'> on {esc(row['n_ranking_samples'])} shared"
                           + (f" · {esc(row['ranking_species_basis'])}" if row.get("ranking_species_basis") else "")
                           + "</small>"
                           if row.get("n_ranking_samples") and row.get("ranking_basis") == "shared_samples" else ""),
                sig_class=sig_class, sig_text=esc(sig_text),
            )
        )

    TRACK_LABELS = {"short_read": "Short-read track",
                    "long_read": "Long-read track",
                    "hybrid": "Hybrid (long + short) track"}
    TRACK_BLURBS = {
        "short_read": "Tools reconstructing from a short-read assembly or its graph.",
        "long_read": "Tools reconstructing from long reads alone.",
        "hybrid": "Tools given long reads plus short reads.",
    }

    def single_table(rows):
        body = "".join(leaderboard_row_html(row) for row in rows) or "<tr><td colspan='20'>No scored tools yet.</td></tr>"
        return ("<div class='panel'><table class='sortable'><thead><tr><th>Rank</th><th>Tool</th><th>Scored</th>"
                "<th>Completed</th><th>Failed</th><th>Skipped</th><th>Mean precision</th><th>Mean base recall</th>"
                "<th>Mean plasmid recall</th><th>Perfect reference recovery</th><th>Strict reconstruction</th><th>Mean bin F1 (count-based)</th>"
                "<th>Mean NMI</th><th>Mean VI</th><th>Mean PR-AUC</th><th>Ranking score</th><th>95% CI</th><th>CPRR</th>"
                "<th>Mean base F1</th><th>Significant vs runner-up</th></tr></thead>"
                f"<tbody>{body}</tbody></table></div>")

    def leaderboard_table(rows):
        """One ranked table per task within a track; never one mixed ranking."""
        tasks = []
        for row in rows:
            if (row.get("task") or "") not in tasks:
                tasks.append(row.get("task") or "")
        if tasks == [""]:
            return single_table(rows)
        return "".join(
            f"<h4>{esc(TASK_LABELS.get(task, task))}</h4><p class='muted'>{esc(TASK_BLURBS.get(task, ''))}</p>"
            + single_table([row for row in rows if (row.get("task") or "") == task])
            for task in tasks)

    # One ranking per track. Pooling them would rank a tool given long reads
    # against one given only short reads on the same isolates -- different
    # inputs, so not the same question.
    ordered_tracks = [track for track in ANALYSIS_TRACKS if track in track_leaderboards]
    ordered_tracks += [track for track in sorted(track_leaderboards) if track not in ordered_tracks]
    if len(ordered_tracks) > 1:
        leaderboard_panels = (
            "<p class='lead'>This run scored "
            + esc(str(len(ordered_tracks))) + " analysis tracks. Each is ranked separately and they are "
            "never pooled: a tool handed long reads and a tool handed only short reads are answering "
            "different questions on the same isolates, so a single combined ranking would not be a "
            "like-for-like comparison. Compare within a table, not across them.</p>"
        ) + "".join(
            f"<h3>{esc(TRACK_LABELS.get(track, track))}</h3>"
            f"<p class='muted'>{esc(TRACK_BLURBS.get(track, ''))} "
            f"Full table: <a href='benchmark.{esc(track)}.leaderboard.tsv'>benchmark.{esc(track)}.leaderboard.tsv</a></p>"
            + leaderboard_table(track_leaderboards[track])
            for track in ordered_tracks
        )
    else:
        leaderboard_panels = leaderboard_table(
            track_leaderboards.get(ordered_tracks[0], leaderboard) if ordered_tracks else leaderboard)

    import report_wiring
    robustness_html = robustness_section(track_leaderboards, ordered_tracks or list(track_leaderboards),
                                         report_wiring.overlap_statuses(str(results_dir)))

    score_rows = "".join(score_row(row, metadata, tool_versions) for row in scores)
    score_rows = score_rows or "<tr><td colspan='13'>No score rows were produced.</td></tr>"

    bin_rows = []
    for row in scores:
        if not row.get("bin_f1"):
            continue
        sample, tool = row["sample"], row["tool"]
        matches = results_dir / sample / f"{tool}.bin_matches.tsv"
        detail = "-"
        if matches.is_file():
            detail = f"<a href='{relative_link(matches, out)}' download>Download matches TSV</a>"
        bin_rows.append(
            "<tr><td>{sample}</td><td>{tool}</td><td>{precision}</td><td>{recall}</td><td><strong class='score {band}'>{f1}</strong></td>"
            "<td>{matched}</td><td>{unmatched}</td><td>{missed}</td><td>{splits}</td><td>{merges}</td><td>{contaminated}</td><td>{repeat}</td><td>{contamination}</td><td>{detail}</td></tr>".format(
                sample=esc(sample), tool=esc(tool), precision=esc(row.get("bin_precision") or "-"),
                recall=esc(row.get("bin_recall") or "-"), f1=esc(row.get("bin_f1") or "-"),
                band=score_band(number(row.get("bin_f1"))), matched=esc(row.get("matched_bins") or "0"),
                unmatched=esc(row.get("unmatched_bins") or "0"), missed=esc(row.get("missed_plasmids") or "0"),
                splits=esc(row.get("split_events") or "0"), merges=esc(row.get("merge_events") or "0"),
                contaminated=esc(row.get("contaminated_bins") or "0"),
                repeat=esc(row.get("repeat_ambiguity_bp") or "0"),
                contamination=esc(row.get("contamination_fraction") or "-"), detail=detail,
            )
        )
    bin_diagnostics_html = "".join(bin_rows) or "<tr><td colspan='14'>No tool supplied validated bin membership in this run.</td></tr>"

    # Zero-plasmid negative control: a per-tool summary, not per-sample, from
    # the leaderboard rows aggregate_results.py already computed (n_samples
    # with true_plasmid_count==0, their mean isolate_specificity, and their
    # total chromosome false-positive bp). Precision/recall/F1 are correctly
    # undefined on these isolates -- this is the ONLY place their false-
    # positive behavior is actually measured, so it gets its own section
    # rather than being buried as blank cells in the main leaderboard.
    zero_plasmid_rows = []
    for row in leaderboard:
        n_zero = number(row.get("n_zero_plasmid_isolates")) or 0
        if n_zero <= 0:
            continue
        spec = row.get("mean_zero_plasmid_specificity") or ""
        fp_bp = row.get("total_zero_plasmid_chromosome_fp_bp") or "0"
        spec_value = optional_number(spec)
        zero_plasmid_rows.append(
            "<tr><td>{tool}</td><td>{n}</td><td><strong class='score {band}'>{spec}</strong></td><td>{fp_bp:,}</td></tr>".format(
                tool=esc(row["tool"]), n=int(n_zero),
                spec=esc(spec) if spec else "-",
                band=score_band(spec_value) if spec_value is not None else "low",
                fp_bp=int(number(fp_bp)) if fp_bp else 0,
            )
        )
    zero_plasmid_html = "".join(zero_plasmid_rows) or ("<tr><td colspan='4'>No plasmid-free isolate was scored in this run. There is no switch for this: the "
        "section fills when the cohort contains an isolate whose truth has no plasmid and a tool was run on it.</td></tr>")

    # Graded plasmid-recovery completeness tiers: a supplementary breakdown
    # between "any recall" (Mean plasmid recall, at its own configured
    # threshold) and "Perfect reference recovery" in the main leaderboard --
    # never a ranking replacement for either. mean_complete_circular_plasmid_recall
    # is only defined for tools/runs where circular-truth evidence was
    # supplied at all (score_plasmids.py's --circular-plasmids), so a tool
    # with n_complete_circular_assessed==0 shows "not assessed", never 0.
    graded_tier_rows = []
    for row in leaderboard:
        ge50 = optional_number(row.get("mean_plasmid_recall_ge50"))
        ge90 = optional_number(row.get("mean_plasmid_recall_ge90"))
        n_circular = int(number(row.get("n_complete_circular_assessed")) or 0)
        circular = optional_number(row.get("mean_complete_circular_plasmid_recall")) if n_circular > 0 else None
        graded_tier_rows.append(
            "<tr><td>{tool}</td>"
            "<td><strong class='score {ge50_band}'>{ge50}</strong></td>"
            "<td><strong class='score {ge90_band}'>{ge90}</strong></td>"
            "<td><strong class='score {circ_band}'>{circ}</strong></td></tr>".format(
                tool=esc(row["tool"]),
                ge50=f"{ge50:.3f}" if ge50 is not None else "not annotated",
                ge50_band=score_band(ge50) if ge50 is not None else "low",
                ge90=f"{ge90:.3f}" if ge90 is not None else "not annotated",
                ge90_band=score_band(ge90) if ge90 is not None else "low",
                circ=f"{circular:.3f}" if circular is not None else "not assessed",
                circ_band=score_band(circular) if circular is not None else "low",
            )
        )
    graded_tiers_html = "".join(graded_tier_rows) or "<tr><td colspan='4'>No tool was scored in this run.</td></tr>"

    # Isolate difficulty (python/compute_difficulty_features.py, gated by
    # RUN_DIFFICULTY_FEATURES, off by default): truth-derived, per-ISOLATE
    # (not per-tool) signals for how intrinsically hard this isolate is to
    # separate into plasmid vs. chromosome -- never a tool-performance
    # measure, and never wired into recommendation_model.py (see
    # docs/METHODS.md). Each of the three fields is independently optional;
    # a row is shown only for a sample with at least one real value.
    difficulty_rows = []
    for sample in samples:
        row = difficulty_features.get(sample)
        if not row:
            continue
        dead_ends = (row.get("gfa_dead_end_count") or "").strip()
        depth_ratio = optional_number(row.get("plasmid_chromosome_depth_ratio"))
        mash_distance = optional_number(row.get("plasmid_chromosome_mash_distance"))
        if not dead_ends and depth_ratio is None and mash_distance is None:
            continue
        difficulty_rows.append(
            "<tr><td>{sample}</td><td>{dead_ends}</td><td>{depth_ratio}</td><td>{mash_distance}</td></tr>".format(
                sample=esc(sample),
                dead_ends=esc(dead_ends) if dead_ends else "not available",
                depth_ratio=f"{depth_ratio:.4f}" if depth_ratio is not None else "not available",
                mash_distance=f"{mash_distance:.6f}" if mash_distance is not None else "not available",
            )
        )
    difficulty_html = "".join(difficulty_rows) or (
        "<tr><td colspan='4'>No isolate difficulty features are available for this run "
        "(RUN_DIFFICULTY_FEATURES=0 by default, or --data-dir was not supplied to the report).</td></tr>"
    )

    # Cohort QC flags (advisory only): only flagged rows shown by default,
    # the full advisory table (including every non-flagged value and any
    # withholding/MAD==0 note rows) stays downloadable from the file explorer.
    cohort_qc_flagged = [row for row in cohort_qc_flags if row.get("flagged") == "true"]
    cohort_qc_rows = "".join(
        "<tr><td>{sample}</td><td>{field}</td><td>{value}</td><td>{median}</td><td>{mad}</td><td>{z}</td><td>{note}</td></tr>".format(
            sample=esc(row["sample_id"]), field=esc(row["field"]), value=esc(row["value"]),
            median=esc(row["cohort_median"]), mad=esc(row["cohort_mad"]), z=esc(row["modified_z_score"]),
            note=esc(row["note"]),
        ) for row in cohort_qc_flagged
    )
    if not cohort_qc_flags:
        cohort_qc_html = ("<tr><td colspan='7'>No cohort QC flags file was available for this run. Stage 6 writes it when "
                         "COHORT_QC_FLAGS_ENABLED=1 and the cohort has at least COHORT_QC_MIN_COHORT_SIZE isolates.</td></tr>")
    elif not cohort_qc_flagged:
        withheld = next((row for row in cohort_qc_flags if row.get("note", "").startswith("cohort has")), None)
        cohort_qc_html = ("<tr><td colspan='7'>{}</td></tr>".format(esc(withheld["note"])) if withheld
                          else "<tr><td colspan='7'>No robust outliers were flagged in this cohort.</td></tr>")
    else:
        cohort_qc_html = cohort_qc_rows
    cohort_qc_download = ""
    if args.cohort_qc_flags and Path(args.cohort_qc_flags).is_file():
        cohort_qc_download = " <a href='{}' download>Download the full advisory table</a> (every unflagged value included).".format(
            relative_link(Path(args.cohort_qc_flags), out))

    # Recovery by replicon / MOB type (descriptive only; never ranks tools).
    replicon_recovery_html = "".join(
        "<tr><td>{track}</td><td>{tool}</td><td>{kind}</td><td>{label}</td><td>{n}</td><td>{samples}</td>"
        "<td>{mean}</td><td>{median}</td><td>{recovered}</td><td>{cprr}</td><td>{flag}</td></tr>".format(
            track=esc(row.get("analysis_track", "-")), tool=esc(row.get("tool", "-")),
            kind=esc(row.get("feature_type", "-")), label=esc(row.get("label", "-")),
            n=esc(row.get("n_plasmids", "-")), samples=esc(row.get("n_samples", "-")),
            mean=esc(row.get("mean_completeness", "-")), recovered=esc(row.get("recovered_fraction", "-")),
            median=("{} ({}-{})".format(esc(row["median_completeness"]), esc(row.get("q1_completeness", "-")),
                                      esc(row.get("q3_completeness", "-")))
                    if row.get("median_completeness") else "-"),
            cprr=("{} (n={})".format(esc(row["cprr"]), esc(row.get("n_cprr_assessed", "-")))
                  if row.get("cprr") else "not bin-scored"),
            flag="underpowered (small n)" if row.get("underpowered") == "true" else "",
        ) for row in recovery_by_replicon
    ) or ("<tr><td colspan='11'>No recovery-by-replicon table was available. It needs per-plasmid "
          "scoring output and replicon/MOB annotation of the truth references.</td></tr>")
    replicon_recovery_download = ""
    if args.recovery_by_replicon and Path(args.recovery_by_replicon).is_file():
        replicon_recovery_download = " <a href='{}' download>Download the table</a>.".format(
            relative_link(Path(args.recovery_by_replicon), out))

    # Ranking robustness (advisory; never alters the leaderboard). One row per
    # track and scoring variant: how far the order moves and whether the top tool holds.
    robustness_seen, robustness_rows = set(), []
    for row in rank_robustness:
        key = (row.get("analysis_track", ""), row.get("variant", ""))
        if key in robustness_seen:
            continue
        robustness_seen.add(key)
        robustness_rows.append(
            "<tr><td>{track}</td><td>{variant}</td><td>{tau}</td><td>{top}</td><td>{same}</td></tr>".format(
                track=esc(key[0] or "-"), variant=esc(key[1] or "-"),
                tau=esc(row.get("kendall_tau_vs_baseline") or "-"), top=esc(row.get("top_tool") or "-"),
                same=esc(row.get("top_matches_baseline") or "-")))
    rank_robustness_html = "".join(robustness_rows) or (
        "<tr><td colspan='5'>No ranking-robustness table was available "
        "(rank_sensitivity.py writes benchmark.rank_robustness.tsv during stage 6).</td></tr>")
    rank_robustness_download = ""
    if args.rank_robustness and Path(args.rank_robustness).is_file():
        rank_robustness_download = " <a href='{}' download>Download the table</a>.".format(
            relative_link(Path(args.rank_robustness), out))

    # Truth-label audit (advisory): counts per finding, then only the sequences to review.
    audit_counts = {}
    for row in truth_label_audit:
        audit_counts[row.get("finding", "")] = audit_counts.get(row.get("finding", ""), 0) + 1
    audit_summary = ", ".join("{}: {}".format(esc(k), v) for k, v in sorted(audit_counts.items())) or "no audit table"
    audit_flagged = [r for r in truth_label_audit
                     if r.get("finding") in ("chromosome_with_plasmid_markers", "plasmid_without_markers")]
    truth_label_audit_html = "".join(
        "<tr><td>{sample}</td><td>{seq}</td><td>{mol}</td><td>{length}</td><td>{rep}</td><td>{mob}</td>"
        "<td>{finding}</td></tr>".format(
            sample=esc(r.get("sample", "-")), seq=esc(r.get("sequence_id", "-")),
            mol=esc(r.get("molecule_type", "-")), length=esc(r.get("length", "-")),
            rep=esc(r.get("replicon_labels") or "-"), mob=esc(r.get("mob_labels") or "-"),
            finding=esc(r.get("finding", "-"))) for r in audit_flagged
    ) or ("<tr><td colspan='7'>No truth sequence was flagged"
          + (" (sequences with no annotation are not evaluated, not cleared)." if truth_label_audit
             else "; no audit table was available (stage 6 writes it from the truth annotation: RUN_TRUTH_LABEL_EVIDENCE=1 "
                                   "or RUN_REFERENCE_ANNOTATION=1).") + "</td></tr>")
    truth_label_audit_download = ""
    if args.truth_label_audit and Path(args.truth_label_audit).is_file():
        truth_label_audit_download = " <a href='{}' download>Download the full audit</a>.".format(
            relative_link(Path(args.truth_label_audit), out))

    # Stratified performance (the detail behind the recommendations; advisory).
    stratified_html = "".join(
        "<tr><td>{scope}</td><td>{group}</td><td>{tool}</td><td>{n}</td><td>{cov}</td><td>{f1}</td>"
        "<td>{rec}</td><td>{reason}</td></tr>".format(
            scope=esc(r.get("scope", "-")), group=esc(r.get("group", "-")), tool=esc(r.get("tool", "-")),
            n=esc(r.get("n_scored", "-")), cov=esc(r.get("coverage", "-")), f1=esc(r.get("mean_f1") or "-"),
            rec=esc(r.get("recommendation", "-")), reason=esc(r.get("reason", "")))
        for r in stratified_rows
    ) or ("<tr><td colspan='8'>No stratified table was available "
          "(select_operational_method.py writes benchmark.stratified.tsv during stage 6).</td></tr>")
    stratified_download = ""
    if args.stratified and Path(args.stratified).is_file():
        stratified_download = " <a href='{}' download>Download the table</a>.".format(
            relative_link(Path(args.stratified), out))

    # Orthogonal (laboratory / independent-technology) evidence summary: counts only.
    def _count_rows(mapping):
        return "".join("<tr><td>{}</td><td>{}</td></tr>".format(esc(str(k)), esc(str(v)))
                       for k, v in sorted((mapping or {}).items()))
    orthogonal_html = (
        "<tr><td colspan='2'><strong>Records: {}</strong></td></tr>".format(esc(str(orthogonal_summary.get("records", 0))))
        + "<tr><th colspan='2'>By evidence type</th></tr>" + _count_rows(orthogonal_summary.get("by_evidence_type"))
        + "<tr><th colspan='2'>By status</th></tr>" + _count_rows(orthogonal_summary.get("by_status"))
    ) if orthogonal_summary else ("<tr><td colspan='2'>No orthogonal evidence was supplied. This is the normal "
                                  "case: laboratory confirmation is optional and never changes a score. To add some, run "
                                  "<code>plasbench validate-orthogonal-evidence --evidence evidence.tsv --out "
                                  "results/orthogonal_validation.summary.json</code> and rebuild the report "
                                  "(docs/ORTHOGONAL_VALIDATION.md).</td></tr>")
    orthogonal_boundary = esc(orthogonal_summary.get("claim_boundary", "Evidence is supplementary and does not change benchmark scores."))

    # QUAST supplementary diagnostics (descriptive only): summarised per tool and
    # reference type; the full per-sample table stays downloadable. Blank or
    # non-numeric QUAST fields are left out of a mean, never counted as zero.
    def _quast_number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    quast_groups = defaultdict(list)
    for row in quast_diagnostics:
        quast_groups[(row.get("tool", "-"), row.get("reference_type", "-"))].append(row)

    def _quast_mean(rows, field):
        values = [v for v in (_quast_number(r.get(field)) for r in rows) if v is not None]
        return f"{sum(values) / len(values):.2f}" if values else "n/a"

    def _quast_total(rows, field):
        values = [v for v in (_quast_number(r.get(field)) for r in rows) if v is not None]
        return f"{int(sum(values))}" if values else "n/a"

    quast_html = "".join(
        "<tr><td>{tool}</td><td>{kind}</td><td>{n}</td><td>{gf}</td><td>{mis}</td><td>{dup}</td></tr>".format(
            tool=esc(tool), kind=esc(kind), n=len(rows),
            gf=_quast_mean(rows, "genome_fraction_pct"), mis=_quast_total(rows, "misassembly_count"),
            dup=_quast_mean(rows, "duplication_ratio"))
        for (tool, kind), rows in sorted(quast_groups.items())
    ) or ("<tr><td colspan='6'>QUAST diagnostics were not run for this analysis (RUN_QUAST_DIAGNOSTICS=0, the "
          "default), or QUAST was unavailable. Enable them with RUN_QUAST_DIAGNOSTICS=1 after "
          "<code>plasbench install-tools quast</code>.</td></tr>")
    quast_download = ""
    if args.quast_diagnostics and Path(args.quast_diagnostics).is_file():
        quast_download = " <a href='{}' download>Download the full per-sample table</a>.".format(
            relative_link(Path(args.quast_diagnostics), out))

    recommendation_rows = "".join(
        "<tr><td>{scope}</td><td>{group}</td><td>{tool}</td><td>{state}</td><td>{n}</td><td>{coverage}</td>"
        "<td>{f1}</td><td>{plasmid}</td><td>{runtime}</td><td>{memory}</td><td>{reason}</td><td>{decision}</td></tr>".format(
            scope=esc(row.get("scope", "-")), group=esc(row.get("group", "-")),
            tool=esc(row.get("tool", "-")),
            state="Eligible operational method" if row.get("recommendation") == "primary" else "Candidate only",
            n=esc(row.get("n_scored", "0")), coverage=esc(row.get("coverage", "-")),
            f1=esc(row.get("mean_f1", "-")), plasmid=esc(row.get("mean_plasmid_recall", "-")),
            runtime=esc(row.get("median_runtime_seconds") or "not recorded"),
            memory=esc(row.get("median_peak_rss_kb") or "not recorded"),
            reason=esc(row.get("reason", "-")),
            decision=esc(row.get("decision_score") or "-"),
        ) for row in recommendations if row.get("recommendation") == "primary"
    ) or "<tr><td colspan='12'>No coverage-gated recommendation was produced for this cohort or stratum.</td></tr>"

    recommendation_why = recommendation_note(recommendations, headline_leaderboard[0] if headline_leaderboard else None)

    validation_rows = "".join(
        "<tr><td>{study}</td><td>{held}</td><td>{tool}</td><td>{train}</td><td>{f1}</td><td>{status}</td><td>{note}</td></tr>".format(
            study=esc(row.get("held_out_study") or "-"), held=esc(row.get("held_out_samples") or "0"),
            tool=esc(row.get("selected_method_from_training") or "No selection"),
            train=esc(row.get("training_samples") or "0"), f1=esc(row.get("held_out_mean_f1") or "-"),
            status=esc(row.get("status") or "not assessed"), note=esc(row.get("note") or "-"))
        for row in recommendation_validation
    ) or "<tr><td colspan='7'>No leave-one-study-out validation file was available.</td></tr>"

    def comparison_row(row):
        delta = row.get("smallest_difference")
        equivalent = row.get("equivalent") or ""
        equivalence = ({"yes": "yes", "no": "no"}.get(equivalent, "not assessed")
                       + (f" (delta {delta})" if delta and equivalent in ("yes", "no") else ""))
        return ("<tr><td>{track}</td><td>{task}</td><td>{metric}</td><td>{a}</td><td>{b}</td><td>{n}</td><td>{difference}</td>"
                "<td>{ci}</td><td>{p}</td><td>{holm}</td><td>{wholm}</td><td>{equiv}</td><td>{wins}/{ties}/{losses}</td></tr>").format(
            track=esc(row.get("analysis_track") or "not recorded"), task=esc(row.get("task") or "not recorded"),
            metric=esc(row.get("metric") or "f1"),
            a=esc(row["tool_a"]), b=esc(row["tool_b"]),
            n=esc(row["paired_samples"]) + (
                f" ({esc(row['paired_clusters'])} clusters)"
                if row.get("paired_clusters") and row.get("paired_clusters") != row.get("paired_samples") else ""),
            difference=esc(row["mean_f1_difference"]),
            ci=esc((row.get("difference_ci_low") and row.get("difference_ci_high") and
                    f"{row['difference_ci_low']} to {row['difference_ci_high']}") or "not estimated (n < 5)"),
            p=esc(row.get("permutation_p_value") or "not estimated (n < 5)"),
            holm=esc(row.get("permutation_p_value_holm") or "not estimated (n < 5)"),
            wholm=esc(row.get("wilcoxon_p_value_holm") or "not estimated"),
            equiv=esc(equivalence),
            wins=esc(row["wins_a"]), ties=esc(row["ties"]), losses=esc(row["wins_b"]))

    comparison_head = ("<thead><tr><th>Track</th><th>Task</th><th>Metric</th><th>Tool A</th><th>Tool B</th><th>Pairs</th>"
                       "<th>Mean difference (A minus B)</th><th>95% bootstrap CI</th><th>Permutation p</th><th>Holm-adjusted p</th>"
                       "<th>Wilcoxon p (Holm)</th><th>Equivalent within delta</th><th>A wins / ties / B wins</th></tr></thead>")
    comparison_tracks = []
    for row in comparisons:
        if (row.get("analysis_track") or "not recorded") not in comparison_tracks:
            comparison_tracks.append(row.get("analysis_track") or "not recorded")
    comparison_tables = "".join(
        f"<h3 class='rpt-trackrow'>Track: {esc(t)}</h3><div class='panel'><table class='sortable'>{comparison_head}<tbody>"
        + "".join(comparison_row(r) for r in comparisons if (r.get("analysis_track") or "not recorded") == t)
        + "</tbody></table></div>" for t in comparison_tracks
    ) or f"<div class='panel'><table class='sortable'>{comparison_head}<tbody><tr><td colspan='13'>No paired score rows are available.</td></tr></tbody></table></div>"
    score_failure_html = "".join(
        "<li><strong>{sample} / {tool}</strong> at {stage}: {reason}</li>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]), stage=esc(row["stage"]), reason=esc(row["reason"])
        ) for row in score_failures
    ) or "<li>No score-stage failures were recorded.</li>"

    status_rows = "".join(
        "<tr data-status='{state}'><td>{sample}</td><td>{tool}</td><td><span class='status {state}'>{state}</span></td>"
        "<td>{runtime}</td><td>{memory}</td><td>{reason}</td></tr>".format(
            sample=esc(row["sample"]), tool=esc(row["tool"]), state=esc(row["status"]),
            runtime=esc(row.get("runtime_seconds") or "-"), memory=esc(row.get("peak_rss_kb") or "-"),
            reason=esc(row.get("reason") or "-"),
        ) for row in status
    ) or "<tr><td colspan='4'>Stage 4 status was not available.</td></tr>"

    sample_sections = []
    selection_cards = []
    for sample in samples:
        rows = score_by_sample.get(sample, [])
        body = "".join(
            "<tr><td>{tool}</td><td>{p}</td><td>{r}</td><td><strong>{f1}</strong></td><td>{fp:,}</td><td>{unmapped:,}</td><td>{pr_auc}</td></tr>".format(
                tool=esc(row["tool"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                fp=int(number(row["FP_bp"])), unmapped=int(number(row["unmapped_pred_bp"])),
                pr_auc=esc(row.get("pr_auc") or "-"),
            ) for row in rows
        ) or "<tr><td colspan='7'>No completed tool was scored for this sample.</td></tr>"
        selection = results_dir / "selected_candidates" / sample / f"{sample}.selection_report.json"
        if not selection.is_file():
            selection = results_dir / sample / "selected_candidate" / "selection_report.json"
        selection_link = (f" <a href='{relative_link(selection, out)}' download>Download selected-candidate report</a>"
                          if selection.is_file() else "")
        selection_cards.append(selection_card(sample, results_dir, out))
        # PR-curve charts: only for tools that exposed a per-record probability
        # (adapters/SCORES.md) and were actually scored for this sample.
        pr_cards = "".join(
            "<div class='chart-card pr-chart-card'><h3>{tool}</h3>{chart}</div>".format(
                tool=esc(row["tool"]),
                chart=pr_curve_chart(read_pr_curve(results_dir, sample, row["tool"]), row.get("pr_auc")),
            ) for row in rows if row.get("pr_auc")
        )
        pr_section = f"<div class='pr-chart-grid'>{pr_cards}</div>" if pr_cards else ""
        sample_sections.append(
            "<details class='sample'><summary><strong>{}</strong><span>{} scored tool(s)</span></summary>"
            "<p class='lead'>{} </p><table><thead><tr><th>Tool</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th><th>PR-AUC</th>"
            "</tr></thead><tbody>{}</tbody></table>{}</details>".format(
                esc(sample), len(rows), selection_link or "No selected-candidate report was produced.", body, pr_section)
        )

    tool_sections = []
    for tool in tools:
        rows = score_by_tool.get(tool, [])
        if rows:
            mean_f1 = sum(number(row["f1"]) for row in rows) / len(rows)
            range_text = f"{min(number(row['f1']) for row in rows):.3f}–{max(number(row['f1']) for row in rows):.3f}"
            body = "".join(
                "<tr><td>{sample}</td><td>{p}</td><td>{r}</td><td><strong class='score {band}'>{f1}</strong></td>"
                "<td>{fp:,}</td><td>{unmapped:,}</td></tr>".format(
                    sample=esc(row["sample"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                    band=score_band(number(row["f1"])), fp=int(number(row["FP_bp"])),
                    unmapped=int(number(row["unmapped_pred_bp"])),
                ) for row in sorted(rows, key=lambda item: number(item["f1"]), reverse=True)
            )
            summary = f"{len(rows)} scored sample(s) · mean F1 {mean_f1:.3f} · F1 range {range_text}"
        else:
            body = "<tr><td colspan='6'>No completed sample was scored for this tool; consult execution health.</td></tr>"
            summary = "No score rows"
        tool_sections.append(
            "<details class='sample tool-detail'><summary><strong>{}</strong><span>{}</span></summary>"
            "<table class='sortable'><thead><tr><th>Sample</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th>"
            "</tr></thead><tbody>{}</tbody></table></details>".format(esc(tool), esc(summary), body)
        )

    roots = [("Results", results_dir), ("Logs", project / "logs"), ("Data", project / "data")]
    explorers = []
    artifact_count = 0
    artifact_bytes = 0
    # Inputs can be outside the run directory. Do not accidentally expose their
    # raw TSV contents merely because a temporary report shares their folder.
    report_inputs = (args.scores, args.tool_status, args.leaderboard, args.sample_sheet,
                     args.manifest, args.comparisons, args.score_failures, args.recommendations, args.recommendation_validation)
    for label, root in roots:
        tree, count, bytes_total = file_tree(root, out, report_inputs if label == "Results" else ())
        artifact_count += count
        artifact_bytes += bytes_total
        explorers.append(f"<details class='explorer' open><summary><strong>{label}</strong><span>{count} downloadable file(s)</span></summary>{tree}</details>")

    best_value = esc(best["tool"]) if best else "No scored tool"
    best_f1 = esc((best.get("ranking_score") or best.get("mean_f1") or "-") if best else "-")
    best_metric = esc(headline_label(best) if best and best.get("ranking_score") else "mean F1")
    run_folder = results_dir.name or "results"
    cohort_label = Path(args.sample_sheet).stem if args.sample_sheet else "not recorded"
    run_label = f"{run_folder} · cohort {cohort_label}"
    # With more than one track scored, this headline is about ONE of them --
    # say which, rather than letting it read as an overall winner.
    best_scope = (f" · {esc(TRACK_LABELS.get(headline_track, headline_track))}"
                  if best and multi_track else "")
    insight_notes, insight_tone = interpretation(headline_leaderboard, status_counts)
    cards = report_cards(headline_leaderboard, scores)
    optional_analysis = optional_analysis_html(args.manifest, results_dir, out)
    findings = guided_findings(headline_leaderboard, cards, scores, status_counts)
    summary_html = summary_section(headline_leaderboard, cards, findings, scores, status_counts, metadata, scope=best_scope)
    insight_html = "".join(f"<li>{esc(note)}</li>" for note in insight_notes)
    chart_html = performance_chart(headline_leaderboard)
    glossary_cards = glossary_section()
    vendor_html = vendor_assets(args.project_root)
    tool_options = "".join(
        f"<option value='{esc(tool)}'>{esc(display_tool_name(tool))}</option>"
        for tool in tools
    )
    visual_html = (visual_quality_section(scores, status, results_dir, out) + advanced_visual_script()
                   + record_dotplot_script() + context_visual_script() + evidence_selection_script()
                   + plasmid_summary_script() + structural_and_feature_tracks_script() + protein_annotation_script()
                   + bin_flow_script() + explorer_navigation_script()
                   + agreement_and_comparison_script()
                   + explorer_chrome_script()
                   + glossary_script()
                   + accessibility_script()
                   + explain_script()
                   + section_nav_script()
                   + agreement_pointer_script()
                   + lazy_visualization_script())
    explorer_html = evidence_explorer_section(args.project_root, scores, results_dir,
                                              vendor_html, visual_html)
    enterprise_html = enterprise_view_section(args.project_root, scores, status, leaderboard,
                                              metadata, results_dir, vendor_html, explorer_html)
    # Further benchmark dimensions (accuracy, feature preservation, bin quality, performance, power,
    # scenarios, composite, reproducibility): one module renders them all; missing tables show empty states.
    import report_dimensions
    dimension_nav_html, dimension_sections_html = report_dimensions.render(
        args.dimensions_prefix or str(out.with_suffix("")) + ".absent", esc, lambda path: relative_link(Path(path), out),
        scores_path=args.scores, samples_path=args.sample_sheet)
    page = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PlasBench report: {esc(run_label)}</title>
{vendor_html}
<style>
.eyebrow{{margin:0 0 8px!important;color:#c9e3d3!important;font:700 11px/1.3 Arial,sans-serif!important;letter-spacing:.12em;text-transform:uppercase}}
:root{{--ink:#17231d;--muted:#627067;--line:#d9e1da;--paper:#f6f8f4;--card:#fff;--green:#0c6b4f;--lime:#dcefdc;--amber:#9a5b00;--red:#a53028;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}} header{{background:#183a2d;color:#fff;padding:48px max(24px,calc((100vw - 1320px)/2));border-bottom:6px solid #a8d29b}} h1,h2,h3,th,.nav,button,select,input,.metric,.status,.selection-card{{font-family:Arial,sans-serif}} h1{{font-size:clamp(28px,5vw,48px);margin:0 0 8px;letter-spacing:-.04em}} header p{{margin:0;color:#d9e7de}} main{{max-width:1320px;margin:auto;padding:28px 24px 64px}} .nav{{display:flex;gap:6px;margin:0 0 26px;padding:6px;background:#fff;border:1px solid var(--line);border-radius:10px;overflow-x:auto;position:sticky;top:0;z-index:30;box-shadow:0 1px 3px rgba(21,36,28,.07);scrollbar-width:thin}} .nav a{{flex:0 0 auto;color:var(--muted);border:0;background:transparent;padding:8px 14px;text-decoration:none;font:600 13px Arial,sans-serif;border-radius:7px;white-space:nowrap;transition:background .15s,color .15s}} .nav a:hover{{background:#eef4ef;color:var(--ink)}} .nav a:focus-visible{{outline:2px solid var(--ink);outline-offset:-2px}} .nav a[aria-current='true']{{background:var(--green);color:#fff}} @media(prefers-reduced-motion:reduce){{.nav a{{transition:none}}}} section{{scroll-margin-top:64px}} .metrics{{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:12px;margin-bottom:28px}} .metric{{background:var(--card);border-top:4px solid var(--green);padding:15px;box-shadow:0 1px 3px #15241c12}} .metric small{{color:var(--muted);display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em}} .metric strong{{font-size:27px;display:block;margin-top:4px}} section{{margin:38px 0}} h2{{font-size:21px;margin:0 0 5px}} h3{{margin:6px 0;font-size:17px}} .lead,.muted{{color:var(--muted)}} .panel{{background:var(--card);border:1px solid var(--line);overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:760px;font-family:Arial,sans-serif;font-size:13px}} th{{background:#edf2ec;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .sortable th{{cursor:pointer}} .sortable th:hover{{background:#dcebdc}} td{{border-top:1px solid var(--line);padding:9px 10px;white-space:nowrap}} tr:hover td{{background:#f5faf4}} .f1-bar{{display:block;width:100%;height:5px;background:#deeadf;margin-top:4px;min-width:64px}} .f1-bar i{{display:block;height:100%;background:var(--green)}} .f1-bar.medium i{{background:#c68221}} .f1-bar.low i{{background:#bd4b42}} .score.high{{color:#087250}} .score.medium{{color:#9a5b00}} .score.low{{color:#a53028}} .insight{{border-left:6px solid var(--green);background:#e7f1e7;padding:16px 20px}} .insight.caution{{border-color:var(--amber);background:#fbf2df}} .insight ul{{margin:6px 0 0;padding-left:20px}} .chart-card{{background:#fff;border:1px solid var(--line);padding:18px;overflow:auto}} .performance-chart{{display:block;min-width:650px;width:100%;height:auto}} .performance-chart .axis,.performance-chart .label{{font:12px Arial,sans-serif;fill:#536158}} .pr-chart-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;padding:0 0 14px}} .pr-chart-card{{padding:10px}} .pr-chart-card h3{{margin:0 0 6px;font-size:13px}} .pr-chart{{display:block;width:100%;max-width:240px;height:auto}} .pr-chart .axis{{font:10px Arial,sans-serif;fill:#536158}} .pr-chart .pr-auc-label{{font:bold 11px Arial,sans-serif;fill:#174b3a}} .chart-legend,.legend{{display:flex;gap:16px;flex-wrap:wrap;font:12px Arial,sans-serif;margin:10px 0}} .chart-legend i,.legend i{{display:inline-block;width:10px;height:10px;margin-right:5px}} .metadata{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);font-family:Arial,sans-serif;font-size:13px}} .metadata div{{background:#fff;padding:12px}} .metadata small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.06em}} .controls{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}} select,input{{padding:7px;border:1px solid var(--line);background:#fff}} .count{{font:12px Arial,sans-serif;color:var(--muted);align-self:center}} .status,.selection-label{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold}} .completed,.reused{{background:#dcefdc;color:#07573e}} .failed{{background:#f7ddda;color:var(--red)}} .skipped{{background:#f6ead1;color:var(--amber)}} .sig-badge{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap}} .sig-badge.significant{{background:#dcefdc;color:#07573e}} .sig-badge.not-significant{{background:#e8e8e8;color:#4a4a4a}} .sig-badge.not-assessed{{background:#eef2ee;color:var(--muted)}} .truth-source-badge{{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:bold;background:#e4eef8;color:#17457e;font-family:Arial,sans-serif;vertical-align:middle}} .truth-source-badge.simulated-badge{{background:#f6ead1;color:#765000}} .selection-card{{display:grid;grid-template-columns:1fr auto;gap:14px;background:#fff;border:1px solid var(--line);border-left:6px solid var(--amber);padding:18px;margin:12px 0}} .selection-card.confident{{border-left-color:var(--green)}} .selection-label{{background:#f6ead1;color:#765000}} .confident .selection-label{{background:#dcefdc;color:#07573e}} .selection-actions{{text-align:right;min-width:190px}} .download-button{{display:inline-block;background:var(--green);color:#fff!important;padding:8px 10px;text-decoration:none;font-weight:bold}} .selection-card details{{grid-column:1/-1;border-top:1px solid var(--line)}} .selection-card summary{{padding:10px 0;cursor:pointer;font-weight:bold}} .selection-card ul{{margin:0;padding-left:20px}} details.sample,.explorer{{background:var(--card);border:1px solid var(--line);margin:10px 0;padding:0 14px}} details summary{{cursor:pointer;padding:13px 0;font-family:Arial,sans-serif}} details summary span{{float:right;color:var(--muted);font-size:12px}} .file-tree{{list-style:none;padding-left:18px;margin:0 0 15px;font-family:Arial,sans-serif;font-size:13px}} .file-tree li{{padding:3px 0}} .file-tree details summary{{padding:3px 0}} .file-tree a{{color:var(--green);text-decoration:none;font-weight:600}} .file-tree .file span{{color:var(--muted);font-size:11px;margin-left:8px}} .method{{columns:2;column-gap:32px;background:#ebf2ea;padding:18px 22px}}  .sum-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:14px 0 26px}} .sum-stat{{background:#fff;border:1px solid var(--line);border-top:4px solid var(--green);padding:14px 16px}} .sum-stat small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10.5px;letter-spacing:.08em}} .sum-stat strong{{display:block;font-size:24px;margin-top:5px;line-height:1.15}} .grade{{display:inline-block;min-width:30px;text-align:center;font-weight:bold;font-size:15px;padding:3px 9px;border-radius:5px;font-family:Arial,sans-serif}} .grade-a{{background:#dcefdc;color:#07573e;border:2px solid #17805a}} .grade-b{{background:#e4eef8;color:#17457e;border:2px solid #2563c9}} .grade-c{{background:#f6ead1;color:#765000;border:2px solid #a35c05}} .grade-d{{background:#f7ddda;color:#8c2018;border:2px solid #b3261e}} .grade-e{{background:#efe3e1;color:#5f1a14;border:2px solid #7a1b14}} .findings{{list-style:none;padding:0;margin:12px 0 0;display:grid;gap:10px}} .finding{{background:#fff;border:1px solid var(--line);border-left:5px solid var(--muted);padding:14px 18px}} .finding.good{{border-left-color:var(--green)}} .finding.caution{{border-left-color:var(--amber)}} .finding .flabel{{font:bold 11px Arial,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .finding p{{margin:5px 0 8px;font-size:14px}} .finding .goto{{font:bold 13px Arial,sans-serif;color:var(--green);text-decoration:none}} .finding .goto:hover{{text-decoration:underline}} .term-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} .term-card{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:14px 16px}} .term-card h3{{margin:0 0 6px;font-size:15px}} .term-card .what{{margin:0 0 8px;font-size:13.5px}} .term-card .why{{margin:0;font-size:13px;color:var(--muted)}} .method p{{margin-top:0;break-inside:avoid}} footer{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}} @media(max-width:700px){{main{{padding:20px 14px}}header{{padding:32px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metadata{{grid-template-columns:1fr}}.method{{columns:1}}.selection-card{{grid-template-columns:1fr}}.selection-actions{{text-align:left}}}}
</style></head><body>
<script>window.pbEsc=s=>String(s==null?'':s).replace(/[&<>\\u0022\\u0027]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\\u0022':'&quot;','\\u0027':'&#39;'}}[c]));</script>
<header><p class="eyebrow">Benchmarking plasmid reconstruction and classification tools against complete reference assemblies.</p><h1>PlasBench: A Reproducible, Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction Tools</h1><p><strong>Run:</strong> {esc(run_label)} · generated {esc(generated)} · offline HTML with direct artifact downloads</p></header>
<main><nav class='nav' aria-label='Report sections'><a href='#summary'>Summary</a><a href='#metadata'>Run metadata</a><a href='#insights'>Interpretation</a><a href='#chart'>Metric chart</a><a href='#leaderboard'>Method ranking</a><a href='#recommendations'>Recommendations</a><a href='#validation'>Study validation</a><a href='#extended'>Extended analyses</a><a href='#selected'>Selected reconstructions</a><a href='#scores'>All scores</a><a href='#statistics'>Statistics</a><a href='#bin-diagnostics'>Bin diagnostics</a><a href='#zero-plasmid'>Zero-plasmid isolates</a><a href='#graded-tiers'>Graded plasmid recovery</a><a href='#isolate-difficulty'>Isolate difficulty</a><a href='#cohort-qc'>Cohort QC flags</a><a href='#replicon-recovery'>Recovery by replicon</a><a href='#quast-diagnostics'>QUAST diagnostics</a><a href='#rank-robustness'>Ranking robustness</a><a href='#truth-label-audit'>Truth-label audit</a><a href='#stratified'>Performance by stratum</a><a href='#orthogonal-evidence'>Orthogonal evidence</a>{dimension_nav_html}<a href='#health'>Run health</a><a href='#tools'>Tool drill-down</a><a href='#samples'>Sample drill-down</a><a href='#keys'>Keys and legend</a><a href='#files'>File explorer</a><a href='#method'>Method</a></nav>
<div class='metrics'><div class='metric'><small>Samples observed</small><strong>{len(samples)}</strong></div><div class='metric'><small>Tools observed</small><strong>{len(tools)}</strong></div><div class='metric'><small>Benchmark winner: {best_metric}</small><strong>{best_f1}</strong><small>{best_value}{best_scope} · method ranking only</small></div><div class='metric'><small>Execution issues</small><strong>{status_counts['failed'] + status_counts['skipped']}</strong><small>{status_counts['failed']} failed · {status_counts['skipped']} skipped</small></div></div>
{summary_html}
<section id='metadata'><h2>Run and output metadata</h2><div class='metadata'><div><small>Run folder</small>{esc(run_folder)}</div><div><small>Input cohort / sheet</small>{esc(cohort_label)}</div><div><small>Report generated</small>{esc(generated)}</div><div><small>Score observations</small>{len(scores)} sample-tool row(s)</div><div><small>Tracked artifacts</small>{artifact_count} file(s) · {esc(size_text(artifact_bytes))}</div><div><small>Execution states</small>{status_counts['completed']} completed · {status_counts['reused']} reused · {status_counts['failed']} failed · {status_counts['skipped']} skipped</div><div><small>Scoring inputs</small>scores.tsv, tool_status.tsv, benchmark.leaderboard.tsv</div><div><small>Reference scope</small>Complete assembly reference bases; plasmid is the positive class</div></div></section>
<section id='insights'><h2>Automated interpretation</h2><div class='insight {insight_tone}'><p class='lead'>Generated from the score and execution-status tables. Where at least five shared samples exist, the statistics section adds paired confidence intervals and permutation evidence with Holm adjustment.</p><ul>{insight_html}</ul></div></section>
<section id='chart'><h2>Performance profile</h2><p class='lead'>Mean precision, recall, and F1 by tool. Green is precision, amber is recall, and dark green is F1; bar length spans 0 to 1.</p><div class='chart-card'>{chart_html}</div></section>
<section id='leaderboard'><h2>Benchmark method ranking</h2><p class='lead'>This compares methods across this benchmark cohort. It is not, by itself, a claim that the top method has produced a biologically confirmed plasmid for every sample. Plasmid recall gives equal weight to each truth plasmid, limiting domination by a large replicon. Perfect reference recovery requires F1 and plasmid recall of 1 with no ambiguous, unmapped, or off-truth predicted bases. Strict reconstruction additionally requires perfect available bin diagnostics; neither label proves nucleotide identity or circular closure. Mean bin F1 is shown only for declared binning methods; “not applicable” is not a zero. Mean PR-AUC is shown only for tools exposing a per-record probability (ML classifiers); it never replaces mean F1 in the ranking. Select a column heading to sort.</p>{leaderboard_panels}</section>
<section id='recommendations'><h2>Operational method recommendations</h2><p class='lead'>These are coverage-gated, multi-objective method recommendations, not proof that any individual predicted sequence is correct. Accuracy is primary; failure rate, structural diagnostics, runtime, and memory are included as lower-weighted practical considerations. Each scored isolate also has a reusable <code>selected_candidate/</code> folder containing the chosen already-generated FASTA and a JSON explanation.</p>{recommendation_why}<div class='panel'><table class='sortable'><thead><tr><th>Scope</th><th>Group</th><th>Primary method</th><th>State</th><th>Scored</th><th>Coverage</th><th>Mean F1</th><th>Mean plasmid recall</th><th>Median runtime s</th><th>Median peak RSS KiB</th><th>Decision note</th><th>Decision score</th></tr></thead><tbody>{recommendation_rows}</tbody></table></div></section>
<section id='validation'><h2>Leave-one-study-out validation</h2><p class='lead'>For each source study, the method is selected using all other studies and then evaluated only on the held-out study. A withheld result means the cohort does not yet have enough independent study evidence; it is not a failed method.</p><div class='panel'><table class='sortable'><thead><tr><th>Held-out study</th><th>Held-out samples</th><th>Training-selected method</th><th>Training samples</th><th>Held-out mean F1</th><th>Status</th><th>Interpretation</th></tr></thead><tbody>{validation_rows}</tbody></table></div></section>
<section id='extended'><h2>Extended analyses and next steps</h2><p class='lead'>These optional analyses add decision context. They do not replace the primary benchmark ranking, and an unavailable item means it was not requested or lacked suitable evidence.</p><div class='insight neutral'>{optional_analysis}</div></section>
<section id='selected'><h2>Selected reconstructions</h2><p class='lead'>Each card translates its <code>selection_report.json</code> into a research-facing decision. Downloading the selected FASTA does not rerun any reconstruction; it retrieves the original output retained from the completed tool run.</p>{''.join(selection_cards) or "<p class='muted'>No sample-level selection reports were produced.</p>"}</section>
<section id='scores'><h2>All sample-tool scores</h2><p class='lead'>Filter by performance, tool provenance, or cohort metadata; export the exact visible subset. Unambiguous, ambiguous, and unmapped predicted bases are separate categories. AMR and circular-truth recovery are unavailable (-) unless curated truth annotations were supplied. Circular-truth recovery is not evidence that a predicted sequence is closed.</p><div class='controls'><label>Sample <select id='sample-filter'><option value=''>All samples</option>{''.join(f"<option>{esc(s)}</option>" for s in samples)}</select></label><label>Tool <select id='tool-filter'><option value=''>All tools</option>{tool_options}</select></label><label>Tool version <select id='version-filter'><option value=''>All versions</option><option>not recorded</option>{''.join(f"<option>{esc(v)}</option>" for v in versions)}</select></label><label>Organism <select id='organism-filter'><option value=''>All organisms</option>{''.join(f"<option>{esc(v)}</option>" for v in organisms)}</select></label><label>Origin <select id='origin-filter'><option value=''>All origins</option>{''.join(f"<option>{esc(v)}</option>" for v in origins)}</select></label><label>Truth technology <select id='tech-filter'><option value=''>All technologies</option>{''.join(f"<option>{esc(v)}</option>" for v in technologies)}</select></label><label>Truth tier <select id='tier-filter'><option value=''>All tiers</option>{''.join(f"<option>{esc(v)}</option>" for v in tiers)}</select></label><label>Plasmid size <select id='size-filter'><option value=''>All sizes</option><option value='small'>Small (&lt;10 kb)</option><option value='medium'>Medium (10–100 kb)</option><option value='large'>Large (≥100 kb)</option></select></label><label>Depth ≥ <input id='depth-min' type='number' min='0' step='any' placeholder='any'></label><label>Depth ≤ <input id='depth-max' type='number' min='0' step='any' placeholder='any'></label><label>F1 band <select id='band-filter'><option value=''>All bands</option><option value='high'>High (≥0.90)</option><option value='medium'>Medium (0.70–0.89)</option><option value='low'>Low (&lt;0.70)</option></select></label><button id='export-scores' type='button'>Download filtered CSV</button><span id='score-count' class='count'></span></div><div class='panel'><table id='score-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Tool version</th><th>Origin</th><th>Read depth ×</th><th>True plasmid bp</th><th>TP bp</th><th>FP bp</th><th>FN bp</th><th>Unambiguous predicted bp</th><th>Ambiguous predicted bp</th><th>Unmapped predicted bp</th><th>Precision</th><th>Recall</th><th>AMR recovery</th><th>Circular truth recovery</th><th>F1</th></tr></thead><tbody>{score_rows}</tbody></table></div></section>
<section id='statistics'><h2>Paired tool comparisons</h2><p class='lead'>Differences are tool A minus tool B on shared samples. Confidence intervals and two-sided sign-flip permutation p-values resample whole BioProject clusters when the sample sheet records them (the cluster count is shown beside the pairs), and require at least five independent units. Holm values control family-wise error across comparisons and remain descriptive evidence, not a substitute for study design.</p>{comparison_tables}<p class='lead'>Score-stage isolation events:</p><ul>{score_failure_html}</ul></section>
<section id='bin-diagnostics'><h2>Bin reconstruction diagnostics</h2><p class='lead'>Only tools with validated bin membership are shown. A split is one truth plasmid represented by multiple candidate bins; a merge is one candidate bin with high-completeness evidence for multiple truth plasmids. Repeat ambiguity is bin sequence with both plasmid and chromosome mapping alternatives. Contamination fraction is chromosome-aligned bp divided by all truth-mapped bin bp. Open each matches TSV for bin-to-truth assignments, unmatched bins, and missed plasmids.</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Bin precision</th><th>Bin recall</th><th>Bin F1</th><th>Matched bins</th><th>Unmatched bins</th><th>Missed plasmids</th><th>Split events</th><th>Merge events</th><th>Contaminated bins</th><th>Repeat ambiguity bp</th><th>Contamination fraction</th><th>Record-level detail</th></tr></thead><tbody>{bin_diagnostics_html}</tbody></table></div></section>
<section id='zero-plasmid'><h2>Zero-plasmid isolates (negative control)</h2><p class='lead'>Precision, recall, and F1 are correctly undefined on an isolate with no true plasmid at all -- there is nothing to recover, and a tool predicting nothing has made a correct abstention, not scored a zero. These isolates are still valuable: they are the only ones that directly measure false-positive behavior. Isolate specificity is 1 minus the fraction of that isolate's chromosome a tool wrongly called plasmid; chromosome FP bp is the same false call in raw bases, summed across every plasmid-free isolate a tool was scored on. A specificity below 1.0 means real chromosomal sequence was misclassified as plasmid on a sample where NO plasmid exists to justify it.</p><div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Plasmid-free isolates scored</th><th>Mean isolate specificity</th><th>Total chromosome FP bp</th></tr></thead><tbody>{zero_plasmid_html}</tbody></table></div></section>
<section id='graded-tiers'><h2>Graded plasmid recovery</h2><p class='lead'>Mean plasmid recall (in the main ranking table above) reports one configured completeness threshold. These columns break that single number into intermediate bands: the fraction of a tool's true plasmids that reached at least half covered, at least 90% covered, and -- for isolates with known circular truth -- essentially fully covered AND circular, the strictest per-plasmid claim this report makes. None of these replace Mean F1 or Mean plasmid recall as the ranking metric; they exist to show WHERE a tool's misses tend to land, between total failure and perfect recovery.</p><div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Recall ≥50% complete</th><th>Recall ≥90% complete</th><th>Complete + circular recall</th></tr></thead><tbody>{graded_tiers_html}</tbody></table></div></section>
<section id='isolate-difficulty'><h2>Isolate difficulty</h2><p class='lead'>Truth-derived signals for how intrinsically hard THIS isolate is to correctly separate into plasmid vs. chromosome, independent of any tool's own performance on it -- never a tool-performance measure, and never wired into the recommendation model (see docs/METHODS.md). Off by default (RUN_DIFFICULTY_FEATURES); each field is independently optional and shown as "not available" rather than a guessed value when its own prerequisite (an assembly graph, short reads, or the external tool) was missing.</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>GFA dead-end count</th><th>Plasmid/chromosome depth ratio</th><th>Plasmid/chromosome Mash distance</th></tr></thead><tbody>{difficulty_html}</tbody></table></div></section>
<section id='cohort-qc'><h2>Cohort QC flags</h2><p class='lead'>Statistical, not rule-based: an isolate whose assembly N50, contig count, GC%, or plasmid count is a robust outlier (modified z-score) relative to the rest of this accepted cohort. <strong>Advisory only — never blocks or excludes a sample.</strong> An outlier may be the most scientifically interesting isolate in the cohort, not a bad one; review it, don't discard it on this signal alone. Only flagged values are shown here.{cohort_qc_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Field</th><th>Value</th><th>Cohort median</th><th>Cohort MAD</th><th>Modified z-score</th><th>Note</th></tr></thead><tbody>{cohort_qc_html}</tbody></table></div></section>
<section id='replicon-recovery'><h2>Recovery by plasmid type</h2><p class='lead'>Which kinds of plasmid each tool recovers, by Inc/rep and relaxase (MOB) label annotated on the truth references, by plasmid size band, and by antimicrobial-resistance-gene carriage. Per-plasmid recovery is skewed, so the median and interquartile range sit beside the mean. <strong>Descriptive only: it never ranks tools and never changes the leaderboard.</strong> A plasmid with several labels counts once under each. A plasmid with no label of that type is <em>untyped</em>; plasmids in samples with no annotation are left out rather than called untyped. Groups with few plasmids are flagged, so read patterns, not ranks. <strong>CPRR</strong> is the share of the group's plasmids reconstructed correctly (whole, alone and accurately), so a tool cannot look good only on small, simple plasmids. Tracks are never mixed.{replicon_recovery_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Track</th><th>Tool</th><th>Label type</th><th>Label</th><th>Plasmids</th><th>Samples</th><th>Mean completeness</th><th>Median (IQR)</th><th>Recovered fraction</th><th>CPRR</th><th>Note</th></tr></thead><tbody>{replicon_recovery_html}</tbody></table></div></section>
<section id='quast-diagnostics'><h2>QUAST structural diagnostics</h2><p class='lead'>Optional supplementary check of each tool's predicted plasmid sequence against the truth, run three ways: <em>combined</em> (all truth plasmids), <em>individual</em> (one run per truth plasmid) and <em>chromosome</em> (chromosome only). A high chromosome genome fraction means the tool's plasmid call contains chromosome sequence; misassemblies and duplication ratio flag structural problems that base-level F1 cannot see. <strong>Descriptive only: it never changes the ranking.</strong> Misassembly counts are alignment-derived and are not validated against read or graph support. Means skip blank values.{quast_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Reference</th><th>Comparisons</th><th>Mean genome fraction (%)</th><th>Total misassemblies</th><th>Mean duplication ratio</th></tr></thead><tbody>{quast_html}</tbody></table></div></section>
<section id='rank-robustness'><h2>Ranking robustness</h2><p class='lead'>How much the order of tools depends on scoring choices: each row re-scores the saved alignments with one filter changed (or ranks by strict precision or per-plasmid recovery) and reports Kendall tau against the baseline order and whether the top tool holds. <strong>Advisory only: it never changes the leaderboard.</strong> A low tau or a changed top tool means the ranking is sensitive to that choice.{rank_robustness_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Track</th><th>Variant</th><th>Kendall tau vs baseline</th><th>Top tool</th><th>Top tool unchanged</th></tr></thead><tbody>{rank_robustness_html}</tbody></table></div></section>
<section id='truth-label-audit'><h2>Truth-label audit</h2><p class='lead'>Does each PLASMID or CHROMOSOME label agree with replicon and MOB evidence on the reference? Findings: {audit_summary}. Only sequences to review are listed. A flagged sequence may be a chromid, an integrated plasmid, a cryptic plasmid the databases do not know, or a database false positive. <strong>Advisory only: it never edits truth or changes a score.</strong> <em>not_evaluated</em> means the annotation callers did not run, which is not the same as consistent.{truth_label_audit_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Sequence</th><th>Truth label</th><th>Length</th><th>Replicon</th><th>MOB</th><th>Finding</th></tr></thead><tbody>{truth_label_audit_html}</tbody></table></div></section>
<section id='stratified'><h2>Performance by stratum</h2><p class='lead'>The detail behind the recommendations: each tool's coverage and mean F1 within an organism, size, depth or AMR group, and whether the evidence gate allowed a recommendation. <strong>Advisory only: it never changes the leaderboard.</strong> A stratum with few samples is withheld, not guessed.{stratified_download}</p><div class='panel'><table class='sortable'><thead><tr><th>Scope</th><th>Group</th><th>Tool</th><th>Samples scored</th><th>Coverage</th><th>Mean F1</th><th>Recommendation</th><th>Reason</th></tr></thead><tbody>{stratified_html}</tbody></table></div></section>
<section id='orthogonal-evidence'><h2>Orthogonal evidence</h2><p class='lead'>Optional laboratory or independent-technology evidence recorded alongside the run. {orthogonal_boundary}</p><div class='panel'><table><tbody>{orthogonal_html}</tbody></table></div></section>
{dimension_sections_html}
<section id='health'><h2>Execution health</h2><p class='lead'>A failed tool run on an isolate with true plasmid counts as F1 = 0 for that tool's ranking; a skipped or unavailable tool is left out, and samples not shared by every ranked tool are left out of everyone's ranking. Runtime is elapsed wall-clock seconds; peak RSS is shown when the host profiler provides it.</p><div class='controls'><label>Status <select id='status-filter'><option value=''>All states</option><option value='completed'>Completed</option><option value='reused'>Reused</option><option value='failed'>Failed</option><option value='skipped'>Skipped</option></select></label><span id='status-count' class='count'></span></div><div class='panel'><table id='status-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Status</th><th>Runtime s</th><th>Peak RSS KiB</th><th>Reason / log location</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
<section id='tools'><h2>Tool drill-down</h2><p class='lead'>Open a tool to inspect its score distribution across samples. Rows are initially ordered by F1.</p>{''.join(tool_sections) or "<p class='muted'>No tools were found.</p>"}</section>
<section id='samples'><h2>Sample drill-down</h2><p class='lead'>Open a sample to compare every completed tool side-by-side.</p>{''.join(sample_sections) or "<p class='muted'>No samples were found.</p>"}</section>
<section id='keys'><h2>Keys, legend, and metric definitions</h2><p class='lead'>Every term the report uses, what it measures, and why it matters. The same text appears as a tooltip wherever the term is used, so this page is a reference rather than the only place an explanation exists.</p><div class='legend'><span><i style='background:#087250'></i>High F1: &ge;0.90</span><span><i style='background:#c68221'></i>Medium F1: 0.70&ndash;0.89</span><span><i style='background:#bd4b42'></i>Low F1: &lt;0.70</span><span class='muted'>Bands are visual aids, not acceptance thresholds.</span></div><div class='term-grid'>{glossary_cards}</div></section>
<section id='files'><h2>Artifact explorer</h2><p class='lead'>All files created or consumed by this project are listed below. Select a filename to open or download it; directory branches can be expanded independently.</p>{''.join(explorers)}</section>
<section id='method'><h2>Scoring method and interpretation</h2><div class='method'><p><strong>Truth:</strong> sequences in each complete reference assembly are labelled plasmid or chromosome from the NCBI sequence report.</p><p><strong>Prediction:</strong> each tool’s standardized predicted-plasmid FASTA is aligned to the reference using minimap2.</p><p><strong>Metrics:</strong> covered plasmid reference bases are TP; covered chromosome reference bases are FP; uncovered plasmid bases are FN. Precision measures contamination control; recall measures plasmid completeness; F1 balances both.</p><p><strong>Run integrity:</strong> a failed tool run on an isolate with true plasmid counts as F1 = 0 for that tool, so a tool cannot rise in the ranking by failing on hard isolates. A tool that runs but predicts nothing there also scores F1 = 0. Skipped tools and scoring-stage failures are not scored; every tool is ranked only on the samples all ranked tools share. All of these appear in execution health and in the leaderboard counts.</p></div></section>
<footer>Inputs: <a href='scores.tsv'>scores.tsv</a>, <a href='tool_status.tsv'>tool_status.tsv</a>, <a href='benchmark.leaderboard.tsv'>benchmark.leaderboard.tsv</a>. Report location: {esc(out.name)}.</footer></main>
<script>
const sf=document.getElementById('sample-filter'),tf=document.getElementById('tool-filter'),vf=document.getElementById('version-filter'),bf=document.getElementById('band-filter'),of=document.getElementById('organism-filter'),originf=document.getElementById('origin-filter'),cf=document.getElementById('tech-filter'),qf=document.getElementById('tier-filter'),sizef=document.getElementById('size-filter'),depthMin=document.getElementById('depth-min'),depthMax=document.getElementById('depth-max');
function filterScores(){{let visible=0;const min=depthMin.value===''?null:Number(depthMin.value),max=depthMax.value===''?null:Number(depthMax.value);document.querySelectorAll('#score-table tbody tr').forEach(r=>{{const depth=r.dataset.depth===''?null:Number(r.dataset.depth),outsideDepth=(min!==null&&(depth===null||depth<min))||(max!==null&&(depth===null||depth>max));const hide=(sf.value&&r.dataset.sample!==sf.value)||(tf.value&&r.dataset.tool!==tf.value)||(vf.value&&r.dataset.version!==vf.value)||(bf.value&&r.dataset.band!==bf.value)||(of.value&&r.dataset.organism!==of.value)||(originf.value&&r.dataset.origin!==originf.value)||(cf.value&&r.dataset.tech!==cf.value)||(qf.value&&r.dataset.tier!==qf.value)||(sizef.value&&r.dataset.size!==sizef.value)||outsideDepth;r.hidden=hide;if(!hide)visible++;}});document.getElementById('score-count').textContent=visible+' visible score row(s)';}}
[sf,tf,vf,bf,of,originf,cf,qf,sizef].forEach(el=>el.onchange=filterScores);[depthMin,depthMax].forEach(el=>el.oninput=filterScores);filterScores();
document.getElementById('export-scores').onclick=()=>{{const rows=Array.from(document.querySelectorAll('#score-table tr')).filter(r=>!r.hidden).map(r=>Array.from(r.cells).map(c=>'"'+c.innerText.replaceAll('"','""')+'"').join(','));const blob=new Blob([rows.join('\\n')+'\\n'],{{type:'text/csv'}}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='plasbench-filtered-scores.csv';link.click();URL.revokeObjectURL(link.href);}};
const statusFilter=document.getElementById('status-filter');function filterStatus(){{let visible=0;document.querySelectorAll('#status-table tbody tr').forEach(r=>{{const hide=statusFilter.value&&r.dataset.status!==statusFilter.value;r.hidden=hide;if(!hide)visible++;}});document.getElementById('status-count').textContent=visible+' visible execution row(s)';}}statusFilter.onchange=filterStatus;filterStatus();
document.querySelectorAll('table.sortable th').forEach((head,index)=>head.addEventListener('click',()=>{{const table=head.closest('table'),body=table.tBodies[0],rows=Array.from(body.rows),ascending=head.dataset.order!=='asc';rows.sort((a,b)=>{{const av=a.cells[index]?.innerText.trim()||'',bv=b.cells[index]?.innerText.trim()||'',an=Number(av.replace(/[^0-9.-]/g,'')),bn=Number(bv.replace(/[^0-9.-]/g,''));const result=Number.isNaN(an)||Number.isNaN(bn)?av.localeCompare(bv):an-bn;return ascending?result:-result;}});rows.forEach(row=>body.appendChild(row));table.querySelectorAll('th').forEach(h=>delete h.dataset.order);head.dataset.order=ascending?'asc':'desc';}}));
</script>
</body></html>"""
    page = page.replace("<a href='#scores'>", "<a href='#enterprise'>Interactive dashboard</a><a href='#scores'>")
    page = page.replace("<section id='scores'>", enterprise_html + "<section id='scores'>")
    design_html = headline_design_section(results_dir)
    page = page.replace("<section id='recommendations'>",
                        robustness_html + design_html + "<section id='recommendations'>", 1)
    page = page.replace("<a href='#recommendations'>Recommendations</a>",
                        "<a href='#robustness'>Robustness</a>"
                        + ("<a href='#headline-design'>Headline design</a>" if design_html else "")
                        + "<a href='#recommendations'>Recommendations</a>", 1)
    # Question-bank sections (baselines/calibration, interpretation limits,
    # metadata completeness): python/report_question_bank.py.
    import report_question_bank
    page = report_question_bank.inject(page, results_dir, leaderboard, args.data_dir)
    # Scoring specification and panel sections; each is fed by an explicit argument.
    import report_scoring_spec
    spec_sources = {"leaderboard": args.leaderboard, "manifest": args.manifest, "scores": args.scores,
                    "tool_status": args.tool_status,
                    "comparisons": args.comparisons, "data_dir": args.data_dir,
                    "label_schemes": args.label_schemes, "label_scheme_summary": args.label_scheme_summary,
                    "truth_provenance": args.truth_provenance, "outcome_states": args.outcome_states,
                    "recommender_eval": args.recommender_eval, "recommender_verdict": args.recommender_verdict,
                    "warning_eval": args.warning_eval, "leave_taxon_out": args.leave_taxon_out,
                    "amr_placement": args.amr_placement, "contig_crosscheck": args.contig_crosscheck}
    page = report_scoring_spec.inject(page, spec_sources)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / (out.name.split(".report")[0] + ".scoring_spec.md")).write_text(
        report_scoring_spec.markdown(spec_sources), encoding="utf-8")
    # Evaluation additions learned from PlasEval, plsMD and GAEMR (python/report_learnings.py): read from the stage-6 tables.
    import report_learnings
    page = report_learnings.inject(page, str(results_dir), args.scores)
    # Report overhaul: scorecard, circular plasmid maps and the "Data in this report" inventory
    # (python/report_scorecard.py, report_maps.py, report_surfaces.py; shared helpers in report_common.py).
    # The workflow figure is in the README (python/report_workflow.py writes docs/images/workflow.svg).
    import report_common
    import report_maps
    import report_scorecard
    import report_surfaces
    page = report_common.add_style(page)
    page = report_scorecard.inject(page, str(results_dir), args.scores,
                                   samples_path=args.sample_sheet, report_path=str(out))
    import report_isolates   # the isolate filter and the plasmid-by-tool matrix (python/report_isolates.py)
    page = report_isolates.inject(page, str(results_dir), args.data_dir, args.scores, report_cards=report_cards,
                                  grade_rows_html=grade_rows_html, label=display_tool_name)
    page = report_maps.inject(page, str(results_dir), args.data_dir, args.scores)
    import report_figures   # the figure gallery: ladder, 3D landscape, heatmap, distributions, forest, precision-recall
    page = report_figures.inject(page, str(results_dir), args.data_dir, args.scores)
    import report_post   # condense, fold and lay out the finished page (python/report_post.py lists the steps)
    page = report_post.run(page)
    # Outputs the report did not show before (per-plasmid detail, assembly quality, clonal groups, regret, truth depth, column
    # groups, Run files) and the grouped navigation (python/report_wiring.py). Before the inventory so it lists them as shown.
    page = report_wiring.inject(page, str(results_dir), args.data_dir, args.scores)
    page = report_surfaces.inject(page, str(results_dir), args.data_dir)
    page = report_wiring.finish(page)
    import report_merge    # fold related analyses into tabbed containers, keeping every old id as a panel id (python/report_merge.py)
    page = report_merge.transform(page)
    import report_layout   # the page shell: top bar, left rail, one view at a time, print/PDF form (python/report_layout.py)
    page = report_layout.transform(page)
    # Last step: move the explanatory notes into info popovers (python/report_info.py), then add their positioning script.
    import report_info
    page = report_info.transform(page, info_script())
    import report_names   # tool ids -> display names in the page text, so print, PDF and no-JavaScript readers see them too
    page = report_names.humanise(page, {tool: display_tool_name(tool) for tool in tools})
    page = page.replace("</body>", humanise_tool_labels_script(tools) + "</body>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote HTML report: {out}")


if __name__ == "__main__":
    main()
