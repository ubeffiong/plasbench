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


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_sample_metadata(path):
    if not path or not Path(path).is_file():
        return {}
    return {row["sample_id"]: row for row in read_tsv(path) if row.get("sample_id")}


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
    best_f1 = optional_number(best.get("mean_f1"))
    if best_f1 is not None:
        low = optional_number(best.get("f1_ci_low"))
        high = optional_number(best.get("f1_ci_high"))
        spread = (f" Its 95% interval spans {low:.3f} to {high:.3f}"
                  if low is not None and high is not None else "")
        second = optional_number(leaderboard[1].get("mean_f1")) if len(leaderboard) > 1 else None
        margin = (f", {best_f1 - second:+.3f} ahead of {esc(leaderboard[1]['tool'])}"
                  if second is not None else "")
        findings.append({
            "tone": "good", "label": "Highest Base F1",
            "text": f"{esc(best['tool'])} leads on mean Base F1 at {best_f1:.3f}{margin}."
                    f"{spread}. A lead on few samples is not evidence of superiority: "
                    "the paired comparison section carries the interval and permutation evidence.",
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
            "text": f"{failed} run(s) failed and are excluded from every mean rather than "
                    "counted as zero. A method that fails often can still rank well on the "
                    "runs it finished.",
            "target": "#health", "action": "Open execution health",
        })
    return findings


def summary_section(leaderboard, cards, findings, scores, status_counts, metadata):
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
        ("Leading method", esc(best["tool"]),
         f"Highest mean Base F1 ({optional_number(best.get('mean_f1')) or 0:.3f})."),
        ("Runs not completed", str(status_counts.get("failed", 0) + status_counts.get("skipped", 0)),
         "Excluded from every mean rather than scored as zero."),
    ]
    stat_html = "".join(
        f"<div class='sum-stat' title='{esc(hint)}'><small>{esc(label)}</small>"
        f"<strong>{value}</strong></div>" for label, value, hint in stats)

    grade_html = "".join(
        "<tr><td>{tool}</td><td><span class='grade grade-{low}'>{grade}</span></td>"
        "<td>{f1}</td><td>{recall}</td><td>{contam}</td><td>{done}</td></tr>".format(
            tool=esc(c["tool"]), low=c["grade"].lower(), grade=c["grade"],
            f1=("-" if c["parts"]["mean_f1"] is None else f"{c['parts']['mean_f1']:.3f}"),
            recall=("-" if c["parts"]["mean_plasmid_recall"] is None
                    else f"{c['parts']['mean_plasmid_recall']:.0%}"),
            contam=("not measured" if c["parts"]["contamination"] is None
                    else f"{c['parts']['contamination']:.1%}"),
            done=("-" if c["parts"]["completion"] is None else f"{c['parts']['completion']:.0%}"))
        for c in cards) if False else "".join(
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
        "<h3>Report card</h3>"
        "<p class='lead'>A reading aid, not an acceptance threshold. The grade is a weighted "
        "composite of Base F1 (40%), plasmid recall (25%), freedom from chromosomal "
        "contamination (20%) and completed runs (15%); A &ge;0.90, B &ge;0.80, C &ge;0.65, "
        "D &ge;0.45. A component that was not measured is dropped and the rest reweighted, "
        "never counted as zero. The components are shown so the grade can be taken apart.</p>"
        "<div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>Grade</th>"
        "<th>Base F1</th><th>Plasmid recall</th><th>Chromosomal contamination</th>"
        f"<th>Runs completed</th></tr></thead><tbody>{grade_html}</tbody></table></div>"
        "<h3>Start here</h3>"
        f"<ul class='findings'>{find_html}</ul>"
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
    return """<style>
#pb-prefs{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 18px;
  font:13px Arial,sans-serif}
#pb-prefs button{font:13px Arial,sans-serif;padding:7px 13px;border:1px solid var(--line);
  background:#fff;border-radius:6px;cursor:pointer;color:var(--ink)}
#pb-prefs button:hover{background:#eef4ef;border-color:var(--green)}
#pb-prefs button[aria-pressed="true"]{background:var(--green);color:#fff;border-color:var(--green)}
#pb-prefs .note{color:var(--muted);font-size:12.5px}
/* Blue against orange: separable for deuteranopia and protanopia. */
:root[data-cvd="1"]{--green:#0b62a4;--lime:#d8e7f3;--amber:#a85a00;--red:#8a4500}
:root[data-cvd="1"] .score.high{color:#0b62a4}
:root[data-cvd="1"] .score.medium{color:#a85a00}
:root[data-cvd="1"] .score.low{color:#7a3c00}
:root[data-cvd="1"] .f1-bar i{background:#0b62a4}
:root[data-cvd="1"] .f1-bar.medium i{background:#c07000}
:root[data-cvd="1"] .f1-bar.low i{background:#7a3c00}
:root[data-cvd="1"] .grade-a{background:#dbe9f5;color:#08436f;border-color:#0b62a4}
:root[data-cvd="1"] .grade-b{background:#e6eef6;color:#0b4d7d;border-color:#3f87bd}
:root[data-cvd="1"] .grade-c{background:#f7e8d5;color:#7a3c00;border-color:#a85a00}
:root[data-cvd="1"] .grade-d{background:#f2ddc4;color:#63300a;border-color:#8a4500}
:root[data-cvd="1"] .grade-e{background:#e8d6c4;color:#4a2408;border-color:#63300a}
:root[data-cvd="1"] .completed,:root[data-cvd="1"] .reused{background:#dbe9f5;color:#08436f}
:root[data-cvd="1"] .failed{background:#f2ddc4;color:#63300a}
:root[data-cvd="1"] .skipped{background:#f7e8d5;color:#7a3c00}
:root[data-cvd="1"] .finding.good{border-left-color:#0b62a4}
:root[data-cvd="1"] .finding.caution{border-left-color:#a85a00}
@media print{
  #pb-prefs,.nav,.controls,#pb-tabs{display:none!important}
  body{background:#fff}
  header{background:#fff!important;color:#000!important;border-bottom:2px solid #000}
  header p{color:#333!important}
  main{max-width:none;padding:0}
  section{break-inside:avoid-page;page-break-inside:avoid;margin:0 0 18px}
  h2{break-after:avoid-page;page-break-after:avoid}
  .panel,.chart-card,.term-card,.sum-stat,.finding{border:1px solid #999!important;box-shadow:none!important}
  table{font-size:10pt} th{background:#eee!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  /* Every pane of a tabbed group prints, or the export loses six of seven. */
  .pb-tab[hidden]{display:block!important}
  .pb-tab{break-before:page;page-break-before:always}
  details{display:block} details>summary{font-weight:bold}
  details:not([open])>*:not(summary){display:block!important}
  iframe{break-inside:avoid;page-break-inside:avoid}
  a[href^="#"]::after{content:""}
  .muted,.lead{color:#333!important}
}
</style><script>
(()=>{const root=document.documentElement;
const bar=document.createElement('div');bar.id='pb-prefs';
bar.innerHTML='<button type="button" id="pb-cvd" aria-pressed="false" '
 +'title="Swap the green/red status palette for blue/orange, which stays separable with '
 +'deuteranopia or protanopia. Every value is also printed as text, so nothing depends on colour.">'
 +'Colour-blind safe palette</button>'
 +'<button type="button" id="pb-print" title="Open the print dialogue. Every tab, every collapsed '
 +'section and every table is expanded first, so the printed copy carries what the screen hides.">'
 +'Print / save as PDF</button>'
 +'<span class="note">Colour is never the only channel: cells print their value, grades print a letter.</span>';
const main=document.querySelector('main');
const first=main.querySelector('section');
if(first)main.insertBefore(bar,first);

function tellFrames(on){document.querySelectorAll('iframe').forEach(f=>{
 try{f.contentWindow.postMessage({pbPalette:on?'cvd':'default'},'*')}catch(e){}})}

function setCvd(on){root.dataset.cvd=on?'1':'';
 const b=document.getElementById('pb-cvd');b.setAttribute('aria-pressed',String(on));
 try{localStorage.setItem('pb-cvd',on?'1':'0')}catch(e){}
 tellFrames(on)}

document.getElementById('pb-cvd').addEventListener('click',function(){
 setCvd(root.dataset.cvd!=='1')});
let saved=null;try{saved=localStorage.getItem('pb-cvd')}catch(e){}
if(saved==='1')setCvd(true);
// A frame that loads after the preference was restored still has to hear it.
document.querySelectorAll('iframe').forEach(f=>f.addEventListener('load',
 ()=>setTimeout(()=>tellFrames(root.dataset.cvd==='1'),150)));

document.getElementById('pb-print').addEventListener('click',function(){
 // Print CSS can reveal a hidden pane, but a canvas drawn at zero width stays
 // blank, so the panes are shown and given a frame to lay out and redraw.
 document.querySelectorAll('.pb-tab[hidden]').forEach(p=>{p.dataset.wasHidden='1';p.hidden=false});
 document.querySelectorAll('details:not([open])').forEach(d=>{d.dataset.wasShut='1';d.open=true});
 window.dispatchEvent(new Event('resize'));
 setTimeout(()=>{window.print();
  document.querySelectorAll('.pb-tab[data-was-hidden]').forEach(p=>{p.hidden=true;delete p.dataset.wasHidden});
  document.querySelectorAll('details[data-was-shut]').forEach(d=>{d.open=false;delete d.dataset.wasShut});
  window.dispatchEvent(new Event('resize'))},400)});
})();
</script>"""


def explain_script():
    """Click any chart mark and be told what it means, not just what it says.

    The marks already carried their facts in a <title>: a band knows it is
    "4/5 methods", a ribbon knows it is "6,000 bp". What none of them carried
    was the reading -- whether four of five agreeing is reassuring, what a
    ribbon that splits implies downstream. This adds that second half, from one
    panel every chart shares rather than a bespoke popup per chart.
    """
    return """<style>
#pb-explain{position:fixed;right:18px;bottom:18px;width:380px;max-width:calc(100vw - 36px);
  max-height:62vh;overflow:auto;background:#fff;border:1px solid var(--line);
  border-left:5px solid var(--green);box-shadow:0 10px 34px rgba(22,33,28,.24);
  padding:16px 18px;z-index:70;display:none;font-size:14px}
#pb-explain.on{display:block}
#pb-explain h4{margin:0 0 4px;font:600 15px Arial,sans-serif}
#pb-explain .fact{margin:0 0 10px;font-family:'IBM Plex Mono',monospace;font-size:13px;
  background:#f2f6f3;padding:8px 10px;border-radius:4px;word-break:break-word}
#pb-explain p{margin:0 0 10px;font-size:13.5px;line-height:1.55}
#pb-explain .close{position:absolute;top:10px;right:12px;border:0;background:none;
  font-size:20px;line-height:1;cursor:pointer;color:var(--muted)}
#pb-explain .close:hover{color:var(--ink)}
#pb-explain .hintline{margin:0;font-size:12px;color:var(--muted)}
.pb-clickable{cursor:pointer}
@media print{#pb-explain{display:none!important}}
</style><script>
(()=>{
const panel=document.createElement('aside');panel.id='pb-explain';
panel.setAttribute('role','status');panel.setAttribute('aria-live','polite');
panel.innerHTML='<button type="button" class="close" aria-label="Close explanation">&times;</button>'
 +'<h4 id="pb-explain-title"></h4><p class="fact" id="pb-explain-fact"></p>'
 +'<div id="pb-explain-body"></div>'
 +'<p class="hintline">Click another mark to explain it, or press Escape to close.</p>';
document.body.append(panel);
panel.querySelector('.close').addEventListener('click',()=>panel.classList.remove('on'));
document.addEventListener('keydown',e=>{if(e.key==='Escape')panel.classList.remove('on')});

function explain(title,fact,paragraphs){
 document.getElementById('pb-explain-title').textContent=title;
 document.getElementById('pb-explain-fact').textContent=fact||'';
 document.getElementById('pb-explain-fact').style.display=fact?'block':'none';
 document.getElementById('pb-explain-body').innerHTML=paragraphs.map(p=>'<p>'+p+'</p>').join('');
 panel.classList.add('on');
 panel.scrollTop=0;
}
window.pbExplain=explain;

// The reading for each kind of mark. The fact comes from the mark itself; this
// is the part a reader cannot get from the picture.
const READINGS={
 agreement:[
  'This band is a stretch of the reference and the number of methods whose alignments cover it.',
  'Agreement is <strong>shared support, not evidence of correctness</strong>. Methods built on similar assumptions fail in similar ways, so a region every method covers can still be wrong, and a region only one method covers is not necessarily an error.',
  'Bands where support drops are the ones worth opening in the tracks above: either the region is genuinely hard, or one method is claiming something the others do not.'],
 flow:[
  'This ribbon is one predicted bin and the truth plasmid it was matched to, with the aligned bases between them.',
  'One truth plasmid reached by several ribbons is a <strong>split</strong>: the sequence was found but never assembled into one unit. One ribbon reaching several truth plasmids is a <strong>merge</strong>: two replicons fused into a single answer.',
  'Both can occur at high completeness, which is why a base-level score alone cannot tell you whether the reconstruction is usable.'],
 dotplot:[
  'Each line is one alignment block, drawn against the reference on the horizontal axis and the predicted record\u2019s own coordinates on the vertical.',
  'A single forward diagonal means the record follows the reference in order and orientation. Parallel offset diagonals mean the same sequence appears more than once. A <strong>reverse</strong> diagonal, drawn in purple, means the block aligns backwards.',
  'This is a diagnostic drawn from alignment blocks. It is not structural validation: nothing here is checked against a closed genome.'],
 plasmid:[
  'This row is one truth plasmid and how much of it the selected method recovered.',
  '<strong>Impure records</strong> are predicted records that also align to the chromosome or to another truth plasmid. Completeness alone cannot reveal them, which is why they are counted separately.',
  'Selecting the row loads its tracks above, where the recovered and missing intervals are drawn in reference coordinates.'],
 distribution:[
  'Each column is one method. The box spans the interquartile range, the heavy line is the median, the whiskers reach the extremes, and every sample is drawn behind them.',
  'A tight box means the method behaves consistently across isolates. A wide box, or a median far from the mean, means performance depends on the sample -- which matters more than the average for deciding whether to trust it on a new isolate.',
  'Failed and skipped runs are excluded rather than plotted as zero, so a short column can mean few completed runs, not poor scores. The count under each column says how many.']
};

function reading(kind,extra){
 const base=(READINGS[kind]||['No reading is available for this mark.']).slice();
 if(extra)base.unshift(extra);
 return base;
}

// One delegated listener: the marks are redrawn constantly by their own
// fragments, so binding to the container outlives every redraw.
function factOf(el){
 const t=el.querySelector('title');
 return t?t.textContent.trim():(el.getAttribute('aria-label')||'').trim();
}
document.addEventListener('click',function(e){
 const agree=e.target.closest('#vq-agree rect.agr');
 if(agree){explain('Method agreement band',factOf(agree),reading('agreement'));return}
 const link=e.target.closest('#vq-sankey path.lnk');
 if(link){explain('Bin-to-truth ribbon',factOf(link),reading('flow'));return}
 const seg=e.target.closest('#vq-dotplot line.dpl');
 if(seg){explain('Alignment block',factOf(seg),reading('dotplot'));return}
 const row=e.target.closest('#vq-summary tbody tr');
 if(row){const cells=[...row.cells].map(c=>c.textContent.trim());
  explain('Truth plasmid '+(cells[0]||''),cells.join('  \u00b7  '),reading('plasmid'));return}
});

// Marks that can be explained should look like it.
function markClickable(){
 document.querySelectorAll('#vq-agree rect.agr,#vq-sankey path.lnk,#vq-dotplot line.dpl,#vq-summary tbody tr')
  .forEach(el=>{if(!el.classList.contains('pb-clickable')){el.classList.add('pb-clickable');
   if(!el.getAttribute('tabindex'))el.setAttribute('tabindex','0')}});
}
markClickable();
if(window.MutationObserver){let queued=false;
 new MutationObserver(()=>{if(queued)return;queued=true;
  requestAnimationFrame(()=>{queued=false;markClickable()})})
 .observe(document.body,{childList:true,subtree:true})}
document.addEventListener('keydown',function(e){
 if(e.key!=='Enter'&&e.key!==' ')return;
 const el=document.activeElement;
 // SVG elements have no click() method, so the event is dispatched instead.
 if(el&&el.classList&&el.classList.contains('pb-clickable')){e.preventDefault();
  el.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
});

// The embedded dashboards speak into the same panel rather than opening their own.
window.addEventListener('message',function(e){
 const m=e.data;
 if(!m||m.pbExplain!==true)return;
 explain(m.title||'Chart',m.fact||'',reading(m.kind,m.extra));
});
})();
</script>"""


def section_nav_script():
    """Mark the section the reader is actually in.

    A strip of links that never says where you are is a table of contents, not
    navigation. This tracks the section in view and keeps its pill in sight, so
    the bar answers "where am I" as well as "where can I go".
    """
    return """<script>
(()=>{
// This fragment is emitted inside one of the sections it tracks, so at parse
// time every later section is still unwritten. Building the lookup then
// silently limited the bar to the sections above it.
function setup(){
const nav=document.querySelector('nav.nav');if(!nav)return;
const links=[...nav.querySelectorAll('a')];
const byId={};links.forEach(a=>{const id=a.getAttribute('href').slice(1);
 const target=document.getElementById(id);if(target)byId[id]={a,target}});
const ids=Object.keys(byId);if(!ids.length)return;

function mark(id){links.forEach(a=>a.removeAttribute('aria-current'));
 const hit=byId[id];if(!hit)return;hit.a.setAttribute('aria-current','true');
 // Keep the current pill visible without dragging the page with it.
 const bar=nav.getBoundingClientRect(),pill=hit.a.getBoundingClientRect();
 if(pill.left<bar.left||pill.right>bar.right)
  nav.scrollLeft+=pill.left-bar.left-16}

// Ratios from an IntersectionObserver go stale on a long jump, and a tall
// section keeps a non-zero ratio across thousands of pixels, so the mark stuck.
// The section in view is simply the last one whose top has passed the bar.
// A boolean latch cleared only inside requestAnimationFrame stops the tracker
// for good if a frame is never delivered -- which a throttled or backgrounded
// tab does. A time throttle cannot latch.
let lastRun=0,pending=null;
function locate(){lastRun=Date.now();
 const line=(document.querySelector('nav.nav')||{}).getBoundingClientRect
  ? document.querySelector('nav.nav').getBoundingClientRect().bottom+8 : 72;
 let current=ids[0],nearest=-Infinity;
 ids.forEach(id=>{const top=byId[id].target.getBoundingClientRect().top;
  if(top<=line&&top>nearest){nearest=top;current=id}});
 // At the foot of the document the last section may never reach the bar.
 if(window.innerHeight+window.scrollY>=document.body.scrollHeight-4)current=ids[ids.length-1];
 mark(current)}
function schedule(){const since=Date.now()-lastRun;
 if(since>=90){locate();return}
 if(pending)return;
 pending=setTimeout(()=>{pending=null;locate()},90-since)}
addEventListener('scroll',schedule,{passive:true});
addEventListener('resize',schedule);
locate();
links.forEach(a=>a.addEventListener('click',()=>mark(a.getAttribute('href').slice(1))));
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);
else setup();
})();
</script>"""


def agreement_pointer_script():
    """Put a draggable pointer on the agreement track.

    The sweep shows how many methods cover each interval, but reading a
    particular coordinate off it means eyeballing a band against a ruler. The
    pointer is dragged along the track and reports the position it is on: which
    interval, how many methods cover it, which ones by name, and what that
    means. Naming them is the part the picture cannot do -- "4 of 5" does not
    say which one disagrees.
    """
    return """<style>
#agr-pointer{cursor:ew-resize}
#agr-pointer line{stroke:#16211c;stroke-width:1.5}
#agr-pointer polygon{fill:#16211c}
#vq-agree svg{cursor:crosshair;touch-action:none}
#agr-readout{margin-top:10px;font:13px Arial,sans-serif;line-height:1.55;color:#3d4b44;
  background:#f7faf8;border:1px solid #d3ddd6;border-left:4px solid #17805a;
  border-radius:5px;padding:10px 13px}
#agr-readout b{color:#16211c}
#agr-readout .who{display:block;margin-top:5px;font-size:12.5px}
#agr-readout .who i{font-style:normal;display:inline-block;padding:1px 8px;margin:2px 4px 0 0;
  border-radius:10px;font-size:11.5px}
#agr-readout .yes{background:#dcefdc;color:#07573e}
#agr-readout .no{background:#f2e4e2;color:#8c2018}
#agr-readout .note{display:block;margin-top:6px;font-size:12px;color:#5d6b63}
</style><script>
(()=>{const $=id=>document.getElementById(id);
if(!$('vq-data'))return;
const data=JSON.parse($('vq-data').textContent);

function context(){const a=data.visualizations[($('vq-sample')||{}).value];
 const p=($('vq-plasmid')||{}).value;
 return (a&&p&&a.truth_plasmids&&a.truth_plasmids[p])?{a,p}:null}

// Which methods actually cover a reference position. The band knows the count;
// only the blocks know the names, and the name is what the reader needs.
function supportAt(bp){const x=context();if(!x)return null;
 const out=[];
 Object.keys(x.a.tools).sort().forEach(tool=>{
  const covered=x.a.tools[tool].blocks.some(b=>
   b.target===x.p&&b.target_start<=bp&&bp<b.target_end);
  out.push({tool,covered})});
 return out}

function build(){
 const host=$('vq-agree');if(!host)return;
 const svg=host.querySelector('svg');if(!svg)return;
 if(svg.dataset.pointer)return;
 const bands=[...svg.querySelectorAll('rect.agr')];if(!bands.length)return;
 svg.dataset.pointer='1';

 const left=Math.min(...bands.map(b=>+b.getAttribute('x')));
 const right=Math.max(...bands.map(b=>+b.getAttribute('x')+ +b.getAttribute('width')));
 const top=Math.min(...bands.map(b=>+b.getAttribute('y')));
 const height=Math.max(...bands.map(b=>+b.getAttribute('height')));

 const ns='http://www.w3.org/2000/svg';
 const group=document.createElementNS(ns,'g');
 group.setAttribute('id','agr-pointer');
 group.setAttribute('role','slider');
 group.setAttribute('tabindex','0');
 group.setAttribute('aria-label','Position on the agreement track');
 const line=document.createElementNS(ns,'line');
 line.setAttribute('y1',top-2);line.setAttribute('y2',top+height+2);
 const head=document.createElementNS(ns,'polygon');
 group.append(line,head);svg.append(group);

 let at=left;
 function place(x){
  at=Math.max(left,Math.min(right,x));
  line.setAttribute('x1',at);line.setAttribute('x2',at);
  head.setAttribute('points',
   (at-5)+','+(top-10)+' '+(at+5)+','+(top-10)+' '+at+','+(top-2));
  report()}

 function toUser(event){
  const point=svg.createSVGPoint();
  point.x=event.clientX;point.y=event.clientY;
  const ctm=svg.getScreenCTM();
  return ctm?point.matrixTransform(ctm.inverse()).x:left}

 function bandAt(x){
  return bands.find(b=>{const bx=+b.getAttribute('x');
   return x>=bx&&x<=bx+ +b.getAttribute('width')})||null}

 function report(){
  const box=$('agr-readout');if(!box)return;
  const x=context();if(!x){box.textContent='No plasmid is selected.';return}
  const length=x.a.truth_plasmids[x.p].length;
  const bp=Math.round((at-left)/Math.max(1,right-left)*length);
  const band=bandAt(at);
  const title=band?(band.querySelector('title')||{}).textContent||'':'';
  const support=supportAt(bp)||[];
  const yes=support.filter(s=>s.covered),no=support.filter(s=>!s.covered);
  const chips=support.map(s=>'<i class="'+(s.covered?'yes':'no')+'">'+s.tool+
   (s.covered?'':' \u2014 no cover')+'</i>').join('');
  let meaning;
  if(!support.length)meaning='No method has retained blocks on this plasmid.';
  else if(no.length===0)meaning='Every method covers this position. Shared support is not '
   +'evidence of correctness -- methods with similar assumptions fail in similar ways -- but '
   +'nothing here singles one of them out.';
  else if(yes.length===0)meaning='No method covers this position. A region every method '
   +'misses is more likely to be hard to assemble than to be a fault of any one of them.';
  else meaning='The methods disagree here, which is the interesting case: '+
   no.map(s=>s.tool).join(', ')+(no.length===1?' has':' have')+' no aligned block over this '
   +'position while '+yes.length+' other'+(yes.length===1?'':'s')+' do. Open the tracks above '
   +'at this coordinate to see whether it is missing, inverted, or assigned elsewhere.';
  box.innerHTML='<b>'+bp.toLocaleString()+' bp</b> on '+x.p+' \u00b7 <b>'+yes.length+' of '+
   support.length+'</b> methods cover it'+(title?' \u00b7 band '+title:'')+
   '<span class="who">'+chips+'</span>'+
   '<span class="note">'+meaning+'</span>'}

 let dragging=false;
 const move=e=>{if(!dragging)return;e.preventDefault();place(toUser(e))};
 svg.addEventListener('pointerdown',e=>{dragging=true;
  if(svg.setPointerCapture)try{svg.setPointerCapture(e.pointerId)}catch(err){}
  place(toUser(e))});
 svg.addEventListener('pointermove',move);
 svg.addEventListener('pointerup',()=>{dragging=false});
 svg.addEventListener('pointerleave',()=>{dragging=false});
 group.addEventListener('keydown',e=>{
  const step=(right-left)/100*(e.shiftKey?10:1);
  if(e.key==='ArrowLeft'){e.preventDefault();place(at-step)}
  if(e.key==='ArrowRight'){e.preventDefault();place(at+step)}
  if(e.key==='Home'){e.preventDefault();place(left)}
  if(e.key==='End'){e.preventDefault();place(right)}});

 let box=$('agr-readout');
 if(!box){box=document.createElement('div');box.id='agr-readout';
  box.setAttribute('aria-live','polite');host.append(box)}
 place(left+(right-left)/2)}

build();
// The panel is redrawn whenever the selection changes, taking the pointer with
// it, so it is rebuilt rather than bound once.
if(window.MutationObserver){let queued=false;
 new MutationObserver(()=>{if(queued)return;queued=true;
  requestAnimationFrame(()=>{queued=false;build()})})
 .observe(document.body,{childList:true,subtree:true})}
})();
</script>"""


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
    }
    versions = {label: details.get("version", "unreported")
                for label, name in executable.items()
                if (details := tools.get(name, {})).get("available")}
    declared = manifest.get("method_versions", {}) or {}
    if isinstance(declared, dict):
        versions.update({str(label): str(value) for label, value in declared.items() if value})
    return versions


def number(value):
    return float(value) if value not in (None, "") else 0.0


def optional_number(value):
    return float(value) if value not in (None, "") else None


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
    return (
        "<tr data-sample='{sample}' data-tool='{tool}' data-band='{band}' "
        "data-organism='{organism}' data-tech='{tech}' data-tier='{tier}' "
        "data-origin='{origin}' data-size='{size}' data-depth='{depth}' data-version='{version}' data-track='{track}'>"
        "<td>{sample}</td><td>{tool}</td><td>{version}</td><td>{origin}</td><td>{depth_text}</td>"
        "<td>{truth:,}</td><td>{tp:,}</td><td>{fp:,}</td><td>{fn:,}</td><td>{unambiguous:,}</td><td>{ambiguous:,}</td><td>{unmapped:,}</td>"
        "<td>{precision}</td><td>{recall}</td><td>{amr}</td><td>{circular}</td>"
        "<td><strong class='score {band}'>{f1}</strong></td></tr>"
    ).format(
        sample=esc(row["sample"]), tool=esc(row["tool"]), version=esc(version),
        organism=esc(sample_metadata.get("organism", "")), tech=esc(sample_metadata.get("truth_technology", "")),
        tier=esc(sample_metadata.get("truth_quality_tier", "")), origin=esc(sample_metadata.get("sample_origin", "")),
        track=esc(row.get("analysis_track") or "short_read"),
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
    winner_f1 = number(winner["mean_f1"])
    if len(leaderboard) == 1:
        notes.append(f"{winner['tool']} is the only scored tool (mean F1 {winner_f1:.3f}); no between-tool comparison is available.")
    else:
        runner = leaderboard[1]
        gap = winner_f1 - number(runner["mean_f1"])
        if gap >= 0.05:
            notes.append(f"{winner['tool']} leads {runner['tool']} by {gap:.3f} mean F1 ({winner_f1:.3f} versus {number(runner['mean_f1']):.3f}).")
        else:
            notes.append(f"The top two tools are close: {winner['tool']} leads {runner['tool']} by {gap:.3f} mean F1. This run alone does not establish a clear winner.")

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
</div>""".format(
        tone="confirmation" if confidence != "high" else "confident", status=esc(status), sample=esc(sample),
        tool=esc(selected_tool), score=score_text, confidence=esc(confidence_label), fasta=fasta_link,
        report=report_link, reasons=reasons, alternatives=alternatives, agreement=esc(agreement_text), structural=esc(structural_text))


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
function draw(){let s=$('vq-sample').value,t=$('vq-tool').value,p=$('vq-plasmid').value,a=v[s];if(!a||!p){$('vq-tracks').textContent='No visualization data. Re-run stage 5 after retaining PAF scoring alignments.';return}let len=a.truth_plasmids[p].length,[lo,hi]=range||[0,len];lo=Math.max(0,Math.min(lo,len-1));hi=Math.max(lo+1,Math.min(hi,len));range=[lo,hi];$('vq-start').value=Math.floor(lo);$('vq-end').value=Math.ceil(hi);$('vq-download').href=s+'/visualization/alignment_blocks.json';let names=Object.keys(a.tools),scale=x=>180+(x-lo)/(hi-lo)*880,svg=`<svg viewBox="0 0 1100 ${55+names.length*38}"><text x="180" y="15" font-size="12">${p}: ${Math.floor(lo).toLocaleString()}–${Math.ceil(hi).toLocaleString()} / ${len.toLocaleString()} bp</text>`;names.forEach((name,i)=>{let y=40+i*38,z=a.tools[name],rec=z.plasmid_recovery[p]||{},bs=z.blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi);svg+=`<text x="4" y="${y+7}" font-size="12">${name}</text><text x="105" y="${y+7}" font-size="11">${((rec.completeness||0)*100).toFixed(1)}%</text><rect x="180" y="${y-8}" width="880" height="16" fill="#f7f8f5" stroke="#d6ddd5"/>`;bs.forEach((b,i)=>{let x=Math.max(180,scale(b.target_start)),r=Math.min(1060,scale(b.target_end));svg+=`<rect class="vq-block" data-n="${name}" data-i="${i}" x="${x}" y="${y-8}" width="${Math.max(1,r-x)}" height="16" fill="${b.strand==='-'?'#7f5aa2':'#16805a'}"><title>${b.record_id}</title></rect>`})});a.amr_features.filter(f=>f.sequence_id===p&&f.start>=lo&&f.start<=hi).forEach(f=>{let x=scale(f.start);svg+=`<path d="M${x} 25 l5 -9 l5 9z" fill="#2275ad"><title>${f.label}</title></path>`});svg+='</svg>';$('vq-tracks').innerHTML=svg+'<p class="muted">Displayed primary blocks; '+names.map(n=>n+': '+a.tools[n].blocks_omitted+' omitted').join(' · ')+'</p>';document.querySelectorAll('.vq-block').forEach(e=>e.onclick=()=>{let b=a.tools[e.dataset.n].blocks.filter(x=>x.target===p&&x.target_end>lo&&x.target_start<hi)[e.dataset.i];$('vq-detail').textContent=`${e.dataset.n} | ${b.record_id} | query ${b.query_start}-${b.query_end}/${b.query_length} | reference ${b.target_start}-${b.target_end} | ${b.strand} strand | identity ${(100*b.matches/Math.max(1,b.block_length)).toFixed(2)}% | MAPQ ${b.mapq}`})}
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
let html='<strong>Selected alignment block</strong><table class="vq-kv">'+rows.map(r=>'<tr><th>'+r[0]+'</th><td>'+r[1]+'</td></tr>').join('')+'</table>';
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
    return """<style>
#vq-sankey svg{max-width:100%;height:auto}
#vq-sankey .lnk{fill-opacity:.45;cursor:pointer}
#vq-sankey .lnk:hover,#vq-sankey .lnk.on{fill-opacity:.85}
#vq-sankey .nd{fill:#2f4f45}
#vq-sankey text{font:11px Arial,sans-serif;fill:#26332d}
#vq-sankey-detail{font:12px Arial,sans-serif;color:#3b4746;margin-top:6px}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
// ---- alluvial flow ----
const host=document.createElement('div');host.id='vq-sankey';
const detail=document.createElement('div');detail.id='vq-sankey-detail';
($('vq-flow')||$('vq-tracks')).after(host);host.after(detail);
function render(){const a=d.visualizations[$('vq-sample').value],t=$('vq-tool').value;
 if(!a||!a.tools[t]){host.innerHTML='';detail.textContent='';return}
 const flows=(a.tools[t].bin_assignment_flows||[]).filter(f=>f.bin_id&&f.true_plasmid&&f.aligned_bp>0);
 if(!flows.length){host.innerHTML='<h3>Bin-to-truth flow</h3><p class="muted">No scored bin assignments for this method; contig-level classifiers do not declare bins.</p>';detail.textContent='';return}
 const bins=[...new Set(flows.map(f=>f.bin_id))],truths=[...new Set(flows.map(f=>f.true_plasmid))];
 const total=flows.reduce((s,f)=>s+f.aligned_bp,0);
 const H=Math.max(160,Math.max(bins.length,truths.length)*46),W=760,gap=6;
 const lay=(names,x)=>{let y=20,m={};const tot=names.reduce((s,n)=>s+flows.filter(f=>(x?f.true_plasmid:f.bin_id)===n).reduce((q,f)=>q+f.aligned_bp,0),0)||1;
  names.forEach(n=>{const bp=flows.filter(f=>(x?f.true_plasmid:f.bin_id)===n).reduce((q,f)=>q+f.aligned_bp,0);
   const h=Math.max(12,(H-40)*bp/tot-gap);m[n]={y,h,bp,cursor:y};y+=h+gap});return m};
 const L=lay(bins,0),R=lay(truths,1);
 let paths='';flows.sort((a2,b2)=>b2.aligned_bp-a2.aligned_bp).forEach((f,i)=>{
  const l=L[f.bin_id],r=R[f.true_plasmid];const lh=Math.max(2,l.h*f.aligned_bp/l.bp),rh=Math.max(2,r.h*f.aligned_bp/r.bp);
  const y1=l.cursor,y2=r.cursor;l.cursor+=lh;r.cursor+=rh;
  paths+=`<path class="lnk" data-i="${i}" fill="${f.status==='matched'?'#16805a':'#9a5a05'}" d="M150 ${y1} C 380 ${y1}, 380 ${y2}, 610 ${y2} L610 ${y2+rh} C 380 ${y2+rh}, 380 ${y1+lh}, 150 ${y1+lh} Z"><title>${f.bin_id} → ${f.true_plasmid}: ${f.aligned_bp.toLocaleString()} bp (${f.status})</title></path>`});
 const nodes=bins.map(n=>`<rect class="nd" x="140" y="${L[n].y}" width="10" height="${L[n].h}"/><text x="134" y="${L[n].y+12}" text-anchor="end">${n}</text>`).join('')
  +truths.map(n=>`<rect class="nd" x="610" y="${R[n].y}" width="10" height="${R[n].h}"/><text x="626" y="${R[n].y+12}">${n}</text>`).join('');
 host.innerHTML=`<h3>Bin-to-truth flow: ${t}</h3><p class="muted">Ribbon width is aligned bases. Left is predicted bins, right is truth plasmids. Amber ribbons are assignments the scorer did not accept as a one-to-one match. Only observed assignments are drawn.</p>`
  +`<svg viewBox="0 0 ${W} ${H+20}" role="img" aria-label="Bin to truth assignment flow">${paths}${nodes}</svg>`;
 const splits=truths.filter(n=>new Set(flows.filter(f=>f.true_plasmid===n).map(f=>f.bin_id)).size>1);
 const merges=bins.filter(n=>new Set(flows.filter(f=>f.bin_id===n).map(f=>f.true_plasmid)).size>1);
 detail.textContent=`${flows.length} assignment(s), ${total.toLocaleString()} aligned bp. `
  +(splits.length?`Split across bins: ${splits.join(', ')}. `:'')+(merges.length?`Bins spanning several truth plasmids: ${merges.join(', ')}.`:'')
  +(!splits.length&&!merges.length?'Every assignment is one-to-one.':'');
 host.querySelectorAll('.lnk').forEach(p=>p.onclick=()=>{
  host.querySelectorAll('.lnk').forEach(x=>x.classList.remove('on'));p.classList.add('on');
  const f=flows[+p.dataset.i];detail.textContent=`${f.bin_id} → ${f.true_plasmid}: ${f.aligned_bp.toLocaleString()} aligned bp, status ${f.status}.`;
  if([...$('vq-plasmid').options].some(o=>o.value===f.true_plasmid)){$('vq-plasmid').value=f.true_plasmid;$('vq-plasmid').dispatchEvent(new Event('change'))}})}
['vq-sample','vq-tool'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(render,0)));
render();})();
</script>"""


def agreement_and_comparison_script():
    """Per-region tool agreement, and a baseline-versus-comparator view.

    Agreement counts how many methods cover each reference interval. It is a
    support count, not a correctness claim: methods sharing a bias agree with
    each other and with nothing else, which the caption states plainly.
    """
    return """<style>
#vq-agree{margin:14px 0}
#vq-agree svg{max-width:100%;height:auto}
#vq-agree .lgd{display:flex;gap:14px;flex-wrap:wrap;font:11px Arial,sans-serif;color:#5f6d6b;margin-top:6px}
#vq-agree .lgd i{display:inline-block;width:12px;height:12px;margin-right:5px;vertical-align:-2px}
#vq-compare{margin:14px 0}
#vq-compare table{width:100%;border-collapse:collapse;font:12.5px Arial,sans-serif}
#vq-compare th{background:#edf2ec;text-align:left;padding:7px;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
#vq-compare td{border-top:1px solid #e3e9e8;padding:6px 8px;font-variant-numeric:tabular-nums}
#vq-compare .up{color:#17805a;font-weight:600}
#vq-compare .down{color:#b23b30;font-weight:600}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const agree=document.createElement('div');agree.id='vq-agree';
const comp=document.createElement('div');comp.id='vq-compare';
($('vq-summary')||$('vq-tracks')).before(agree);($('vq-tracks')).after(comp);
function ctx(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value;
 return a&&p&&a.truth_plasmids[p]?{a,p,len:a.truth_plasmids[p].length}:null}
function renderAgreement(){const c=ctx();if(!c){agree.innerHTML='';return}
 const names=Object.keys(c.a.tools),M=names.length;
 // Sweep the interval endpoints so every change in support becomes a boundary.
 const cuts=new Set([0,c.len]);
 names.forEach(n=>c.a.tools[n].blocks.filter(b=>b.target===c.p).forEach(b=>{
  cuts.add(Math.max(0,b.target_start));cuts.add(Math.min(c.len,b.target_end))}));
 const edges=[...cuts].sort((x,y)=>x-y);
 const bands=[];
 for(let i=0;i<edges.length-1;i++){const s=edges[i],e=edges[i+1];if(e<=s)continue;
  const mid=(s+e)/2;
  const supporters=names.filter(n=>c.a.tools[n].blocks.some(b=>b.target===c.p&&b.target_start<=mid&&b.target_end>=mid));
  bands.push({s,e,n:supporters.length,who:supporters})}
 if(!bands.length){agree.innerHTML='';return}
 const W=1100,L=180,PW=880,x=v=>L+v/c.len*PW;
 const shade=n=>n===0?'#eef1ee':['#dbeadf','#a9d3ba','#6fb894','#2f9068','#12664a'][Math.min(4,Math.max(0,Math.round((n/M)*4)))];
 const rects=bands.map((b,i)=>`<rect class="agr" data-i="${i}" x="${x(b.s).toFixed(1)}" y="16" width="${Math.max(1,x(b.e)-x(b.s)).toFixed(1)}" height="18" fill="${shade(b.n)}"><title>${b.s.toLocaleString()}-${b.e.toLocaleString()}: ${b.n}/${M} methods</title></rect>`).join('');
 const covered=bands.filter(b=>b.n===M).reduce((s,b)=>s+(b.e-b.s),0);
 agree.innerHTML=`<h3 style="font:600 13px Arial,sans-serif;margin:0 0 6px">Method agreement across ${c.p}</h3>`
  +`<svg viewBox="0 0 ${W} 44" role="img" aria-label="Number of methods covering each reference interval"><text x="4" y="29" font-size="12">${M} methods</text>${rects}</svg>`
  +`<div class="lgd"><span><i style="background:${shade(0)}"></i>0 of ${M}</span><span><i style="background:${shade(M)}"></i>${M} of ${M}</span>`
  +`<span>${(covered/c.len*100).toFixed(1)}% of the plasmid is supported by every method</span></div>`
  +`<p class="muted" style="font:11px Arial,sans-serif;margin:6px 0 0">Agreement is shared support, not evidence of correctness: methods can share a bias. Select a band to list the supporting methods.</p>`
  +`<div id="vq-agree-detail" class="muted" style="font:12px Arial,sans-serif"></div>`;
 agree.querySelectorAll('.agr').forEach(r=>r.onclick=()=>{const b=bands[+r.dataset.i];
  $('vq-agree-detail').textContent=`${b.s.toLocaleString()}-${b.e.toLocaleString()}: ${b.n}/${M} — ${b.who.join(', ')||'no method covers this interval'}`})}
function renderComparison(){const tools=[...new Set(d.matrix.map(r=>r.tool))].sort();
 if(tools.length<2){comp.innerHTML='';return}
 if(!$('vq-base')){comp.innerHTML=`<h3 style="font:600 13px Arial,sans-serif;margin:0 0 6px">Method comparison</h3>`
  +`<div style="display:flex;gap:10px;flex-wrap:wrap;font:12px Arial,sans-serif;margin-bottom:8px">`
  +`<label>Baseline <select id="vq-base">${tools.map(t=>`<option>${t}</option>`).join('')}</select></label>`
  +`<label>Comparator <select id="vq-comp">${tools.map((t,i)=>`<option${i===1?' selected':''}>${t}</option>`).join('')}</select></label></div>`
  +`<div id="vq-compare-body"></div>`;
  $('vq-base').onchange=renderComparison;$('vq-comp').onchange=renderComparison}
 const a=$('vq-base').value,b=$('vq-comp').value;
 const rows=[];[...new Set(d.matrix.map(r=>r.sample))].sort().forEach(s=>{
  const ra=d.matrix.find(r=>r.sample===s&&r.tool===a),rb=d.matrix.find(r=>r.sample===s&&r.tool===b);
  if(!ra||!rb||ra.f1==null||rb.f1==null)return;
  rows.push({s,a:ra,b:rb,d:rb.f1-ra.f1})});
 if(!rows.length){$('vq-compare-body').innerHTML='<p class="muted">No sample has a scored result for both methods.</p>';return}
 const mean=rows.reduce((x,r)=>x+r.d,0)/rows.length;
 const fmt=v=>v==null?'not measured':v.toFixed(3);
 const dcell=v=>`<span class="${v>0?'up':v<0?'down':''}">${v>0?'+':''}${v.toFixed(3)}</span>`;
 $('vq-compare-body').innerHTML=`<table><thead><tr><th>Sample</th><th>${a} F1</th><th>${b} F1</th><th>&Delta; F1</th><th>&Delta; contamination</th><th>&Delta; runtime (min)</th></tr></thead><tbody>`
  +rows.map(r=>`<tr><td>${r.s}</td><td>${fmt(r.a.f1)}</td><td>${fmt(r.b.f1)}</td><td>${dcell(r.d)}</td>`
   +`<td>${r.a.contamination==null||r.b.contamination==null?'not measured':dcell(r.b.contamination-r.a.contamination)}</td>`
   +`<td>${r.a.runtime_min==null||r.b.runtime_min==null?'not measured':dcell(r.b.runtime_min-r.a.runtime_min)}</td></tr>`).join('')
  +`</tbody></table><p class="muted" style="font:11px Arial,sans-serif;margin:6px 0 0">`
  +`${b} minus ${a} on ${rows.length} shared sample(s); mean &Delta; F1 ${mean>0?'+':''}${mean.toFixed(3)}. `
  +`Wins ${rows.filter(r=>r.d>0).length} / ties ${rows.filter(r=>r.d===0).length} / losses ${rows.filter(r=>r.d<0).length}. `
  +`A difference on few samples is not evidence of superiority; see the paired comparison table for interval and permutation evidence.</p>`}
['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(renderAgreement,0)));
renderAgreement();renderComparison();})();
</script>"""


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
    return """<style>
/* One status palette, shared with the explorer above and the dashboard
   below it: green recovered, red wrong, amber uncertain, blue context. */
#pb-analyses{--pb-line:#d3ddd6;--pb-soft:#eef2ef;--pb-ink:#16211c;--pb-dim:#5d6b63;
  --pb-green:#17805a;--pb-amber:#a35c05;--pb-red:#b3261e;--pb-blue:#2563c9;
  font:14px/1.55 Arial,sans-serif;color:var(--pb-ink);margin:16px 0}
#pb-context{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:10px 16px;
  background:#fff;border:1px solid var(--pb-line);border-radius:10px;margin-bottom:12px}
#pb-context .controls{display:contents;margin:0}
#pb-context label{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--pb-dim)}
#pb-context select,#pb-context input{padding:5px 8px;border:1px solid var(--pb-line);
  border-radius:6px;background:#fff;font:13px Arial,sans-serif;color:var(--pb-ink)}
#pb-context select:focus-visible,#pb-context input:focus-visible{outline:2px solid var(--pb-green);outline-offset:1px}
#pb-context button,#pb-context .download-button{font:13px Arial,sans-serif;padding:6px 12px;
  border:1px solid var(--pb-line);background:#fff;border-radius:6px;cursor:pointer;color:var(--pb-ink);
  text-decoration:none;white-space:nowrap}
#pb-context button:hover,#pb-context .download-button:hover{background:var(--pb-soft);border-color:var(--pb-green)}
#pb-context .download-button{background:var(--pb-green);color:#fff!important;border-color:var(--pb-green);font-weight:600}
#pb-tabs{display:flex;gap:3px;padding:4px;background:#fff;border:1px solid var(--pb-line);
  border-radius:10px;overflow-x:auto;margin-bottom:12px}
#pb-tabs button{flex:0 0 auto;padding:9px 17px;border:0;background:transparent;color:var(--pb-dim);
  font:600 13.5px Arial,sans-serif;border-radius:7px;cursor:pointer;display:flex;align-items:center;gap:7px;
  white-space:nowrap;transition:background .15s,color .15s}
#pb-tabs button:hover{background:var(--pb-soft);color:var(--pb-ink)}
#pb-tabs button[aria-selected="true"]{background:var(--pb-green);color:#fff}
#pb-tabs button:focus-visible{outline:2px solid var(--pb-ink);outline-offset:-2px}
#pb-tabs .count{font:600 11px Arial,sans-serif;background:var(--pb-soft);color:var(--pb-dim);
  padding:1px 7px;border-radius:10px}
#pb-tabs button[aria-selected="true"] .count{background:rgba(255,255,255,.24);color:#fff}
.pb-tab[hidden]{display:none}
.pb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px;align-items:start}
.pb-card{background:#fff;border:1px solid var(--pb-line);border-radius:10px;overflow:hidden;
  display:flex;flex-direction:column;min-width:0}
.pb-card>header{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:10px 16px;background:#f7faf8;border-bottom:1px solid var(--pb-line)}
.pb-card>header h4{margin:0;font:600 14.5px Arial,sans-serif;color:var(--pb-ink)}
.pb-card>header .sub{font:12.5px Arial,sans-serif;color:var(--pb-dim)}
.pb-card>header button{font:12px Arial,sans-serif;padding:4px 10px;border:1px solid var(--pb-line);
  background:#fff;border-radius:5px;cursor:pointer;color:var(--pb-ink)}
.pb-card>header button:hover{background:var(--pb-soft);border-color:var(--pb-green)}
.pb-body{padding:14px 16px;overflow:auto;min-width:0}
.pb-card.expanded{position:fixed;inset:16px;z-index:60;margin:0}
.pb-card.expanded .pb-body{max-height:calc(100vh - 96px)}
#pb-scrim{position:fixed;inset:0;background:rgba(18,28,23,.5);z-index:55;display:none}
#pb-scrim.on{display:block}
#pb-analyses table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:0}
#pb-analyses th{text-align:left;font:600 11.5px Arial,sans-serif;letter-spacing:.06em;
  text-transform:uppercase;color:var(--pb-dim);padding:7px 9px;border-bottom:1px solid var(--pb-line);
  background:var(--pb-soft);white-space:nowrap}
#pb-analyses td{padding:7px 9px;border-bottom:1px solid #eef2ef;color:var(--pb-ink)}
#pb-analyses tbody tr:hover td{background:#f5faf6}
#pb-analyses h3,#pb-analyses h4:not(.pb-card>header h4){font:600 14px Arial,sans-serif;margin:0 0 8px}
#pb-analyses p{margin:0 0 10px;color:var(--pb-dim);font-size:13.5px}
#pb-analyses svg{max-width:100%;height:auto}
@media (max-width:760px){.pb-grid{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){#pb-tabs button{transition:none}}
</style><script>
(()=>{const $=id=>document.getElementById(id);
if(!$('vq-tracks'))return;
// Tab, title, hint, and the panels it owns. A panel with no data still gets its
// card: an empty analysis is a finding, not a reason to hide the heading.
const TABS=[
 ['recovery','Plasmid recovery',[['vq-summary','Truth plasmids','one row per truth plasmid for the selected method']]],
 ['agreement','Method agreement',[['vq-agree','Method agreement','how many methods support each reference interval']]],
 ['comparison','Method comparison',[['vq-compare','Method comparison','baseline against comparator on shared samples']]],
 ['dotplot','Dot plot',[['vq-dotplot','Dot plot','reference against predicted-record coordinates']]],
 ['context','Context and circular',[['vq-context','Context and circular view','curated features and circular truth']]],
 ['bins','Bin assignment',[['vq-sankey','Bin-to-truth flow','which predicted bin carries which truth plasmid'],
                           ['vq-flow','Bin assignments','scored bin membership']]],
 ['features','Proteins and structure',[['vq-proteins','Protein recovery','coordinate recovery of named coding sequences'],
                                       ['vq-structural','Structural diagnostics','alignment-derived discordance']]]];

const shell=document.createElement('div');shell.id='pb-analyses';
const anchor=$('vq-summary')||$('vq-agree')||$('vq-tracks');
anchor.parentElement.insertBefore(shell,anchor);

// The shared selection row becomes the context bar, still the same controls.
const context=document.createElement('div');context.id='pb-context';
const controls=document.querySelector('#cohort-evidence-explorer .controls');
if(controls)context.append(controls);
shell.append(context);

const tabbar=document.createElement('div');tabbar.id='pb-tabs';
tabbar.setAttribute('role','tablist');
tabbar.setAttribute('aria-label','Analyses that share the explorer selection');
shell.append(tabbar);
const scrim=document.createElement('div');scrim.id='pb-scrim';document.body.append(scrim);

function makeCard(id,title,hint){const el=$(id);if(!el)return null;
 const card=document.createElement('section');card.className='pb-card';
 card.innerHTML='<header><div><h4>'+title+'</h4><span class="sub">'+hint+'</span></div>'
  +'<button type="button" class="pb-expand" aria-expanded="false">Expand</button>'
  +'</header><div class="pb-body"></div>';
 card.querySelector('.pb-body').append(el);
 const button=card.querySelector('.pb-expand');
 button.addEventListener('click',()=>{const on=card.classList.toggle('expanded');
  scrim.classList.toggle('on',on);button.textContent=on?'Close':'Expand';
  button.setAttribute('aria-expanded',String(on));
  requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))});
 return card}

const panes=[];
TABS.forEach((entry,index)=>{
 const [key,title,members]=entry;
 const cards=members.map(m=>makeCard(m[0],m[1],m[2])).filter(Boolean);
 if(!cards.length)return;
 const pane=document.createElement('div');pane.className='pb-tab';pane.id='pb-tab-'+key;
 pane.setAttribute('role','tabpanel');
 // A panel has to name the tab that controls it, and vice versa, or a screen
 // reader announces seven unlabelled regions.
 pane.setAttribute('aria-labelledby','pb-tabbtn-'+key);
 pane.tabIndex=0;
 const grid=document.createElement('div');grid.className='pb-grid';
 cards.forEach(c=>grid.append(c));pane.append(grid);shell.append(pane);
 const button=document.createElement('button');button.type='button';
 button.setAttribute('role','tab');button.id='pb-tabbtn-'+key;
 button.innerHTML=title+(cards.length>1?' <span class="count">'+cards.length+'</span>':'');
 button.setAttribute('aria-controls','pb-tab-'+key);
 button.addEventListener('click',()=>select(key));
 tabbar.append(button);
 panes.push({key,pane,button})});

function select(key){panes.forEach(p=>{const on=p.key===key;
 p.pane.hidden=!on;p.button.setAttribute('aria-selected',String(on));
 // Roving tabindex: one stop for the whole strip, arrows move within it.
 p.button.setAttribute('tabindex',on?'0':'-1')});
 // A pane is laid out at zero width while hidden. Every panel here draws into
 // a viewBox SVG and rescales on its own, but any panel that measures its box
 // at draw time would need telling -- after layout has settled, not before.
 requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))}
if(panes.length)select(panes[0].key);

// Every control explains itself. These are read by people who did not build
// the pipeline, and a control whose effect is unclear will be mistrusted.
const HELP={
 'vq-sample':'Isolate to analyse. Drives the explorer above and every panel here.',
 'vq-tool':'Reconstruction method whose output these panels describe.',
 'vq-plasmid':'Truth plasmid these panels are measured against.',
 'vq-start':'Left edge of the reference interval to restrict the panels to.',
 'vq-end':'Right edge of the reference interval to restrict the panels to.',
 'vq-fit':'Show the whole plasmid again.',
 'vq-in':'Narrow the reference interval.',
 'vq-out':'Widen the reference interval.',
 'vq-download':'Download the full visualization payload for this sample as JSON.',
 'vq-svg':'Download the current track drawing as SVG.',
 'vq-png':'Download the current track drawing as PNG.',
 'vq-back':'Return to the previous selection.',
 'vq-base':'Baseline method. The comparison reports comparator minus baseline.',
 'vq-comp':'Comparator method, measured against the baseline on the samples both completed.',
 'vq-protein-category':'Limit the table to one annotation category.',
 'vq-protein-search':'Find a coding sequence by gene name or product.'};
function describe(){
 Object.keys(HELP).forEach(id=>{const el=$(id);if(!el)return;el.title=HELP[id];
  const label=el.closest('label');if(label)label.title=HELP[id]});
 // Some controls are built by other fragments after this runs and carry no id,
 // so they are described by what they sit next to rather than by name.
 const scope=document.getElementById('pb-explorer-view')||shell;
 scope.querySelectorAll('label').forEach(label=>{
  const text=(label.textContent||'').trim();
  const control=label.querySelector('select,input,button');
  if(!control||control.title)return;
  if(text.startsWith('Predicted record'))
   control.title=label.title='Which predicted record to plot against the reference. One coordinate system at a time.';
  else if(/ only$/.test(text)&&control.type==='checkbox')
   control.title=label.title='Include this method in the comparison.';
 });
 scope.querySelectorAll('button').forEach(b=>{
  if(b.title)return;
  if(b.textContent.trim()==='only')b.title='Show this method alone, hiding the others from the comparison.';
 });
}
describe();
// The panels rebuild their own controls whenever the selection changes, and
// some are built after this script runs. Watching the container describes them
// whenever they appear, instead of racing them with a timer.
if(window.MutationObserver){let queued=false;
 new MutationObserver(()=>{if(queued)return;queued=true;
  requestAnimationFrame(()=>{queued=false;describe()})})
 .observe(document.getElementById('pb-explorer-view')||shell,{childList:true,subtree:true})}

const TAB_HELP={
 recovery:'Per truth plasmid: how much of it this method recovered, from how many records, and whether any of those records also align elsewhere.',
 agreement:'How many methods independently support each reference interval. Shared support is not proof of correctness.',
 comparison:'One method minus another on the samples both completed.',
 dotplot:'Reference coordinate against one predicted record\u2019s own coordinate. Forward diagonals support collinearity.',
 context:'Curated features on the reference, and the circular truth view.',
 bins:'Which predicted bin carries which truth plasmid, and the scored membership behind it.',
 features:'Coordinate recovery of named coding sequences, and alignment-derived structural discordance.'};
panes.forEach(p=>{if(TAB_HELP[p.key]){p.button.title=TAB_HELP[p.key];p.pane.title=''}});
shell.querySelectorAll('.pb-expand').forEach(b=>{b.title='Open this panel full screen.'});



tabbar.addEventListener('keydown',e=>{
 const order=panes.map(p=>p.button);const at=order.indexOf(document.activeElement);
 if(at<0)return;
 let next=null;
 if(e.key==='ArrowRight')next=order[(at+1)%order.length];
 if(e.key==='ArrowLeft')next=order[(at-1+order.length)%order.length];
 if(e.key==='Home')next=order[0];
 if(e.key==='End')next=order[order.length-1];
 if(next){e.preventDefault();next.focus();next.click()}});

scrim.addEventListener('click',()=>{shell.querySelectorAll('.pb-card.expanded').forEach(c=>{
 c.classList.remove('expanded');const b=c.querySelector('.pb-expand');
 if(b){b.textContent='Expand';b.setAttribute('aria-expanded','false')}});
 scrim.classList.remove('on');
 requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&scrim.classList.contains('on'))scrim.click()});

// Replaced by the adopted explorer above: kept as anchors, not drawn twice.
// A [hidden] attribute loses to the display rules on these, so hide by style.
['vq-tracks','vq-detail'].forEach(id=>{const e=$(id);if(e)e.style.display='none'});
// The search, BED export, event stepping and plasmid stepping all exist in the
// explorer above. Selection history does not, so that one control stays.
['vq-q','vq-bed','vq-prev-ev','vq-next-ev','vq-prev-p','vq-next-p'].forEach(id=>{
 const e=$(id);if(!e)return;const owner=e.closest('label')||e;owner.style.display='none'});
const nav=$('vq-nav');
if(nav&&$('vq-back')){context.append(nav);nav.style.marginLeft='auto';
 const tag=document.createElement('span');
 tag.style.cssText='font:11px Arial,sans-serif;color:#5d6b63;margin-right:6px';
 tag.textContent='Selection history';nav.prepend(tag)}
else if(nav){nav.style.display='none'}
})();
</script>"""


def explorer_navigation_script():
    """Search, row management, drag navigation, and event-to-event jumping."""
    return """<style>
#vq-nav{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:12px 0}
#vq-nav .grp{display:flex;gap:6px;align-items:end}
#vq-rows{display:flex;flex-wrap:wrap;gap:10px;font:12px Arial,sans-serif;margin:8px 0}
#vq-rows label{display:flex;gap:4px;align-items:center;border:1px solid #d2dad8;padding:3px 7px;background:#fff}
#vq-rows label.solo{outline:2px solid #12403a}
#vq-tracks svg{cursor:grab}
#vq-tracks svg.dragging{cursor:grabbing}
#vq-hits{font:12px Arial,sans-serif;color:#5f6d6b}
#vq-hits ul{margin:4px 0 0;padding-left:18px}
#vq-hits button{font:11px Arial,sans-serif;margin-left:6px}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const nav=document.createElement('div');nav.id='vq-nav';
nav.innerHTML=`<label>Find <input id="vq-q" type="search" placeholder="gene, contig, or 1200-3400" size="26"></label>`
 +`<span class="grp"><button id="vq-bed" type="button" title="Download the visible interval as BED">Export BED</button></span>`
 +`<span class="grp"><button id="vq-prev-ev" type="button">\\u2190 Event</button><button id="vq-next-ev" type="button">Event \\u2192</button></span>`
 +`<span class="grp"><button id="vq-prev-p" type="button">\\u2190 Plasmid</button><button id="vq-next-p" type="button">Plasmid \\u2192</button></span>`
 +`<span class="grp"><button id="vq-back" type="button">Back</button></span>`;
$('vq-tracks').before(nav);
const rows=document.createElement('div');rows.id='vq-rows';nav.after(rows);
const hits=document.createElement('div');hits.id='vq-hits';rows.after(hits);
const hidden=new Set();let solo=null,history=[],cursor=null;
function ctx(){const a=d.visualizations[$('vq-sample').value];const p=$('vq-plasmid').value;
 return a&&p?{a,p,len:a.truth_plasmids[p]?.length||0}:null}
function setRange(lo,hi){const c=ctx();if(!c)return;
 lo=Math.max(0,Math.floor(lo));hi=Math.min(c.len,Math.ceil(hi));if(hi-lo<20)hi=Math.min(c.len,lo+20);
 history.push([$('vq-start').value,$('vq-end').value]);
 $('vq-start').value=lo;$('vq-end').value=hi;$('vq-start').dispatchEvent(new Event('change'))}
// --- row management -------------------------------------------------------
function renderRows(){const c=ctx();if(!c){rows.innerHTML='';return}
 const names=Object.keys(c.a.tools);
 rows.innerHTML='<strong style="font:12px Arial,sans-serif">Tool rows</strong>'+names.map(n=>
  `<label class="${solo===n?'solo':''}"><input type="checkbox" data-n="${n}" ${hidden.has(n)?'':'checked'}> ${n}`
  +` <button type="button" data-solo="${n}">${solo===n?'all':'only'}</button></label>`).join('');
 rows.querySelectorAll('input').forEach(i=>i.onchange=()=>{i.checked?hidden.delete(i.dataset.n):hidden.add(i.dataset.n);solo=null;apply()});
 rows.querySelectorAll('button[data-solo]').forEach(b=>b.onclick=()=>{
  const n=b.dataset.solo;if(solo===n){solo=null;hidden.clear()}else{solo=n;hidden.clear();Object.keys(c.a.tools).forEach(x=>{if(x!==n)hidden.add(x)})}
  renderRows();apply()})}
function apply(){
 // The base view draws one <text> label plus one lane per tool; hide by label.
 const svg=$('vq-tracks').querySelector('svg');if(!svg)return;
 svg.querySelectorAll('text').forEach(t=>{if(hidden.has(t.textContent.trim()))t.style.opacity=.25});
 svg.querySelectorAll('.vq-block').forEach(b=>{b.style.display=hidden.has(b.dataset.n)?'none':''})}
// --- search ---------------------------------------------------------------
function search(){const c=ctx();const q=$('vq-q').value.trim();if(!c||!q){hits.innerHTML='';return}
 const coord=q.match(/^(\\d[\\d,]*)\\s*[-:.]+\\s*(\\d[\\d,]*)$/);
 if(coord){setRange(+coord[1].replace(/,/g,''),+coord[2].replace(/,/g,''));hits.innerHTML='<em>Jumped to coordinate range.</em>';return}
 const needle=q.toLowerCase(),found=[];
 (c.a.amr_features||[]).concat(c.a.context_features||[]).forEach(f=>{
  if(f.sequence_id===c.p&&String(f.label||'').toLowerCase().includes(needle))
   found.push({what:(f.feature_type||'AMR')+': '+f.label,lo:f.start,hi:f.end})});
 Object.entries(c.a.tools).forEach(([n,t])=>t.blocks.forEach(b=>{
  if(b.target===c.p&&b.record_id.toLowerCase().includes(needle))
   found.push({what:n+' record '+b.record_id,lo:b.target_start,hi:b.target_end})}));
 hits.innerHTML=found.length?'<strong>'+found.length+' match(es)</strong><ul>'+found.slice(0,25).map((f,i)=>
   `<li>${f.what} — ${f.lo.toLocaleString()}\\u2013${f.hi.toLocaleString()}<button type="button" data-i="${i}">go</button></li>`).join('')+'</ul>'
  :'<em>No gene, feature, or record matched on this plasmid.</em>';
 hits.querySelectorAll('button[data-i]').forEach(b=>b.onclick=()=>{const f=found[+b.dataset.i];
  const pad=Math.max(50,(f.hi-f.lo));setRange(f.lo-pad,f.hi+pad)})}
$('vq-q').addEventListener('change',search);
$('vq-q').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();search()}});
// --- event jumping --------------------------------------------------------
function events(){const c=ctx();if(!c)return[];const list=[];
 Object.entries(c.a.tools).forEach(([n,t])=>{if(hidden.has(n))return;
  const bs=t.blocks.filter(b=>b.target===c.p).sort((x,y)=>x.target_start-y.target_start);
  bs.forEach((b,i)=>{
   if(b.strand==='-')list.push({at:b.target_start,why:n+': reverse-orientation block'});
   // A gap between consecutive blocks on the same reference is a breakpoint.
   if(i&&b.target_start>bs[i-1].target_end)list.push({at:bs[i-1].target_end,why:n+': breakpoint gap'});
   const a=b.local_alignment;
   if(a){let off=0;for(let k=0;k<a.reference.length;k++){if(a.reference[k]!=='-')off++;
     if(a.reference[k]!==a.prediction[k]){list.push({at:b.target_start+off,why:n+': mismatch or gap'});break}}}})});
 return list.sort((x,y)=>x.at-y.at)}
function jump(dir){const c=ctx();if(!c)return;const list=events();if(!list.length){hits.innerHTML='<em>No orientation, breakpoint, or mismatch event on this plasmid.</em>';return}
 // Walk from the last visited event, not the window midpoint: fitting the whole
 // plasmid would otherwise skip every event in the left half.
 const lo=Number($('vq-start').value),hi=Number($('vq-end').value);
 const from=cursor!=null?cursor:(dir>0?lo-1:hi+1);
 let next=dir>0?list.find(e=>e.at>from):[...list].reverse().find(e=>e.at<from);
 if(!next){next=dir>0?list[0]:list[list.length-1];
  hits.innerHTML='<em>Wrapped to the '+(dir>0?'first':'last')+' event. </em>'}
 else hits.innerHTML='';
 cursor=next.at;
 const span=Math.max(400,hi-lo);
 setRange(next.at-span/2,next.at+span/2);
 hits.innerHTML+='<em>'+next.why+' near '+next.at.toLocaleString()+'</em>'}
$('vq-next-ev').onclick=()=>jump(1);$('vq-prev-ev').onclick=()=>jump(-1);
function stepPlasmid(dir){const sel=$('vq-plasmid'),i=sel.selectedIndex+dir;
 if(i>=0&&i<sel.options.length){sel.selectedIndex=i;sel.dispatchEvent(new Event('change'))}}
$('vq-next-p').onclick=()=>stepPlasmid(1);$('vq-prev-p').onclick=()=>stepPlasmid(-1);
$('vq-back').onclick=()=>{const prev=history.pop();if(!prev)return;
 $('vq-start').value=prev[0];$('vq-end').value=prev[1];$('vq-start').dispatchEvent(new Event('change'))};
// --- drag to pan, drag ruler to select ------------------------------------
function bindDrag(){const svg=$('vq-tracks').querySelector('svg');if(!svg||svg.dataset.drag)return;svg.dataset.drag='1';
 const LEFT=180,W=880;let anchor=null;
 const at=e=>{const r=svg.getBoundingClientRect();const c=ctx();if(!c)return null;
  const x=(e.clientX-r.left)*(1100/r.width);const lo=Number($('vq-start').value),hi=Number($('vq-end').value);
  return lo+Math.min(1,Math.max(0,(x-LEFT)/W))*(hi-lo)};
 svg.addEventListener('pointerdown',e=>{const v=at(e);if(v===null)return;
  anchor={v,y:e.clientY,ruler:e.offsetY<26,moved:false};svg.setPointerCapture(e.pointerId);svg.classList.add('dragging')});
 svg.addEventListener('pointermove',e=>{if(!anchor)return;const v=at(e);if(v===null)return;
  anchor.moved=true;
  if(!anchor.ruler){const lo=Number($('vq-start').value),hi=Number($('vq-end').value),shift=anchor.v-v;
   if(Math.abs(shift)>(hi-lo)/200){$('vq-start').value=Math.round(lo+shift);$('vq-end').value=Math.round(hi+shift);
    $('vq-start').dispatchEvent(new Event('change'));anchor.v=v}}});
 svg.addEventListener('pointerup',e=>{if(!anchor){return}const v=at(e);svg.classList.remove('dragging');
  if(anchor.ruler&&anchor.moved&&v!==null&&Math.abs(v-anchor.v)>10)setRange(Math.min(anchor.v,v),Math.max(anchor.v,v));
  anchor=null});
 svg.addEventListener('pointercancel',()=>{anchor=null;svg.classList.remove('dragging')})}
function refresh(){renderRows();apply();bindDrag()}
['vq-sample','vq-plasmid'].forEach(id=>$(id)?.addEventListener('change',()=>{cursor=null}));
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(refresh,0)));
['vq-fit','vq-in','vq-out'].forEach(id=>$(id)?.addEventListener('click',()=>setTimeout(refresh,0)));
document.addEventListener('keydown',e=>{if(e.target?.matches?.('input,select,textarea'))return;
 if(e.key==='n'){jump(1)}else if(e.key==='p'){jump(-1)}});
// BED of the visible window. Reference coordinates are already 0-based
// half-open, which is exactly what BED expects, so nothing is converted.
$('vq-bed').onclick=()=>{const c=ctx();if(!c)return;
 const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||c.len;
 const lines=['track name="PlasBench '+c.p+'" description="visible predicted blocks"'];
 Object.entries(c.a.tools).forEach(([n,t])=>{if(hidden.has(n))return;
  t.blocks.filter(b=>b.target===c.p&&b.target_end>lo&&b.target_start<hi).forEach(b=>{
   lines.push([c.p,Math.max(lo,b.target_start),Math.min(hi,b.target_end),
               n+':'+b.record_id,b.mapq,b.strand].join('\\t'))})});
 const blob=new Blob([lines.join('\\n')+'\\n'],{type:'text/plain'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download=c.p+'_'+Math.round(lo)+'-'+Math.round(hi)+'.bed';a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),0)};
// Keyboard reach for the tracks, not only the matrix.
const tk=$('vq-tracks');
tk.setAttribute('tabindex','0');tk.setAttribute('role','group');
tk.setAttribute('aria-label','Predicted alignment tracks. Arrow keys pan, plus and minus zoom, Home fits the plasmid, n and p step between events.');
tk.addEventListener('keydown',e=>{const c=ctx();if(!c)return;
 const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||c.len,span=hi-lo;
 const K={ArrowLeft:()=>setRange(lo-span*0.25,hi-span*0.25),
          ArrowRight:()=>setRange(lo+span*0.25,hi+span*0.25),
          '+':()=>setRange(lo+span*0.25,hi-span*0.25),
          '=':()=>setRange(lo+span*0.25,hi-span*0.25),
          '-':()=>setRange(lo-span*0.5,hi+span*0.5),
          Home:()=>$('vq-fit').click(),
          n:()=>jump(1),p:()=>jump(-1)};
 if(K[e.key]){e.preventDefault();K[e.key]()}});
refresh();})();
</script>"""


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
    encoded = document.replace("</script", "<\\/script")
    # The report's own sample and plasmid controls drive the frame, so one
    # selection is followed everywhere instead of being re-picked inside it.
    return ("<div id='pb-explorer-view'><h3>Reconstruction evidence explorer</h3>"
            "<p class='lead'>Alignment blocks, structural calls, bin relationships and reference "
            "annotation for one truth plasmid at a time. Identity, mapping quality and every span are "
            "measured from this run. Read depth is not computed by projection scoring, so per-segment "
            "coverage reads “not measured” rather than zero, and the nucleotide view resolves only "
            "where a CIGAR-bounded local alignment exists.</p>"
            "<div class='panel' style='padding:0'><iframe id='pb-explorer' "
            "title='PlasBench reconstruction evidence explorer' "
            "style='width:100%;height:1180px;border:0;display:block'></iframe></div>"
            f"<script id='pb-explorer-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-explorer');"
            "const raw=document.getElementById('pb-explorer-doc').textContent;"
            "f.srcdoc=raw.split('<\\\\/script').join('</scr'+'ipt');"
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
    encoded = document.replace("</script", "<\\/script")
    return ("<section id='enterprise'><h2>Interactive cohort dashboard</h2>"
            "<p class='lead'>The adopted enterprise dashboard, driven entirely by this run's measured "
            "results. Values that were never measured render as “not measured” rather than as zero. "
            "It runs in an isolated frame so its own stylesheet cannot restyle this report.</p>"
            "<div class='panel' style='padding:0'><iframe id='pb-enterprise' title='PlasBench interactive cohort dashboard' "
            "style='width:100%;height:1240px;border:0;display:block'></iframe></div>"
            f"<script id='pb-enterprise-doc' type='text/template'>{encoded}</script>"
            "<script>(()=>{const f=document.getElementById('pb-enterprise');"
            "const raw=document.getElementById('pb-enterprise-doc').textContent;"
            "f.srcdoc=raw.split('<\\\\/script').join('</scr'+'ipt');})();</script>"
            + evidence_html + "</section>")


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
    return """<style>
.vq-block.vq-impure{stroke:#a53028;stroke-width:2;stroke-dasharray:3 2}
#vq-summary table{width:100%;border-collapse:collapse;font:13px Arial,sans-serif}
#vq-summary th{background:#edf2ec;text-align:left;padding:8px;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
#vq-summary td{border-top:1px solid #d2dad8;padding:7px 8px;white-space:nowrap}
#vq-summary tr.sel td{background:#eef5ee;font-weight:bold}
#vq-summary tbody tr{cursor:pointer}
</style><script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent);
const host=document.createElement('div');host.id='vq-summary';$('vq-tracks').before(host);
// Thresholds are display bands for triage, not acceptance criteria; they mirror
// the recovery threshold documented in the scoring method.
function classify(c,records,impure){if(impure&&c>=.9)return'Complete, contaminated record';
 if(c>=.99)return'Complete';if(c>=.9)return'Near complete';if(c>=.5)return records>2?'Partial, fragmented':'Partial';
 if(c>0)return'Minimal';return'Not recovered'}
function render(){const a=d.visualizations[$('vq-sample').value],t=$('vq-tool').value;
 if(!a||!a.tools[t]){host.innerHTML='';return}
 const tool=a.tools[t],circ=new Set(a.circular_truth_plasmids||[]);
 // A record that also aligns to the chromosome or to another truth plasmid is
 // evidence of contamination or a merge, even where this plasmid looks complete.
 const elsewhere={};tool.blocks.forEach(b=>{(elsewhere[b.record_id]??=new Set()).add(b.molecule_type==='CHROMOSOME'?'chromosome':b.target)});
 const rows=Object.entries(a.truth_plasmids).map(([id,info])=>{
  const rec=tool.plasmid_recovery[id]||{completeness:0};
  const records=[...new Set(tool.blocks.filter(b=>b.target===id).map(b=>b.record_id))];
  const impure=records.filter(r=>[...elsewhere[r]].some(x=>x!==id));
  return {id,len:info.length,circular:circ.has(id),c:rec.completeness||0,n:records.length,impure};});
 rows.sort((x,y)=>y.c-x.c);
 host.innerHTML='<h3>Truth plasmids for '+t+'</h3><p class="muted">One row per truth plasmid. “Impure records” are predicted records that also align to the chromosome or another truth plasmid; completeness alone cannot reveal them. Select a row to load its tracks.</p>'
  +'<div class="panel"><table><thead><tr><th>Truth plasmid</th><th>Length</th><th>Circular truth</th><th>Completeness</th><th>Contributing records</th><th>Impure records</th><th>Classification</th></tr></thead><tbody>'
  +rows.map(r=>`<tr data-p="${r.id}" class="${r.id===$('vq-plasmid').value?'sel':''}"><td>${r.id}</td><td>${r.len.toLocaleString()} bp</td><td>${r.circular?'yes':'not declared'}</td><td>${(r.c*100).toFixed(1)}%</td><td>${r.n}</td><td>${r.impure.length||'0'}</td><td>${classify(r.c,r.n,r.impure.length>0)}</td></tr>`).join('')
  +'</tbody></table></div>';
 const bad=rows.filter(r=>r.impure.length&&r.c>=.9);
 if(bad.length)host.insertAdjacentHTML('beforeend','<div class="vq-warn"><strong>High completeness with impure records:</strong> '+bad.map(r=>r.id).join(', ')+'. High recovery does not imply a clean reconstruction.</div>');
 // Contamination usually arrives as a whole chromosomal record called plasmid,
 // which no per-plasmid row can show. Report it against the tool instead.
 const chrRecords=[...new Set(tool.blocks.filter(b=>b.molecule_type==='CHROMOSOME').map(b=>b.record_id))];
 const chrBp=tool.chromosome_aligned_bp||0;
 if(chrRecords.length)host.insertAdjacentHTML('beforeend','<div class="vq-warn"><strong>Chromosomal contamination for '+t+':</strong> '
  +chrBp.toLocaleString()+' bp across '+chrRecords.length+' predicted record(s) — '+chrRecords.join(', ')
  +'. These are counted as false positives and are not attributable to any truth plasmid, so they do not appear in the rows above.</div>');
 const mean=rows.length?rows.reduce((s,r)=>s+r.c,0)/rows.length:0;
 if(!chrRecords.length&&!bad.length&&rows.length)host.insertAdjacentHTML('beforeend',
  '<p class="muted">No chromosomal or cross-plasmid record contamination among retained blocks (mean completeness '+(mean*100).toFixed(1)+'%).</p>');
 host.querySelectorAll('tbody tr').forEach(tr=>tr.onclick=()=>{$('vq-plasmid').value=tr.dataset.p;$('vq-plasmid').dispatchEvent(new Event('change'))});
 markTracks(tool,elsewhere)}
function markTracks(tool,elsewhere){const p=$('vq-plasmid').value;
 document.querySelectorAll('#vq-tracks .vq-block').forEach(el=>{
  const name=el.dataset.n;if(!name||!d.visualizations[$('vq-sample').value]?.tools[name])return;
  const lo=Number($('vq-start').value)||0,hi=Number($('vq-end').value)||Infinity;
  const list=d.visualizations[$('vq-sample').value].tools[name].blocks.filter(b=>b.target===p&&b.target_end>lo&&b.target_start<hi);
  const b=list[Number(el.dataset.i)];if(!b)return;
  const others=[...(elsewhere[b.record_id]||[])].filter(x=>x!==p);
  if(others.length){el.classList.add('vq-impure');
   const title=el.querySelector('title');if(title)title.textContent=b.record_id+' — also aligns to '+others.join(', ')}})}
['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id)?.addEventListener('change',()=>setTimeout(render,0)));
['vq-fit','vq-in','vq-out'].forEach(id=>$(id)?.addEventListener('click',()=>setTimeout(render,0)));
render();})();
</script>"""


def context_visual_script():
    """Render supplied contextual annotations and a truth-scoped circular map."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),host=document.createElement('div');host.id='vq-context';$('vq-dotplot').after(host);
function render(){let a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;if(!a||!p||!a.tools[t]){host.innerHTML='';return}let features=(a.context_features||[]).filter(f=>f.sequence_id===p),types={};features.forEach(f=>(types[f.feature_type]??=[]).push(f));let html='<h3>Context and circular-truth view</h3>';if(a.circular_truth_plasmids?.includes(p)){let len=a.truth_plasmids[p].length,intervals=a.tools[t].plasmid_recovery[p]?.covered_intervals||[],arc=(s,e)=>{let A=s/len*2*Math.PI-Math.PI/2,B=e/len*2*Math.PI-Math.PI/2,x1=120+80*Math.cos(A),y1=100+80*Math.sin(A),x2=120+80*Math.cos(B),y2=100+80*Math.sin(B),large=B-A>Math.PI?1:0;return `<path d="M${x1} ${y1} A80 80 0 ${large} 1 ${x2} ${y2}" fill="none" stroke="#16805a" stroke-width="14"/>`};html+='<p class="muted">Circular truth plasmid only. Green arcs are recovered reference intervals; this does not claim the predicted output is circular or closed.</p><svg viewBox="0 0 240 200" width="240"><circle cx="120" cy="100" r="80" fill="none" stroke="#e2e8e2" stroke-width="14"/>'+intervals.map(x=>arc(x[0],x[1])).join('')+'<text x="75" y="104" font-size="11">truth circular</text></svg>'}if(features.length){html+='<p><strong>Curated contextual features</strong></p><ul>'+Object.entries(types).map(([k,v])=>`<li>${k}: ${v.map(f=>`${f.label} (${f.start}-${f.end}; ${f.source} ${f.version})`).join(', ')}</li>`).join('')+'</ul>'}else html+='<p class="muted">No versioned replicon, MOB, insertion-sequence, or AMR-context feature table was supplied.</p>';host.innerHTML=html}['vq-sample','vq-tool','vq-plasmid'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));render()})();
</script>"""


def record_dotplot_script():
    """Use one predicted-record coordinate system per dot plot."""
    return """<script>
(()=>{const $=id=>document.getElementById(id),d=JSON.parse($('vq-data').textContent),select=document.createElement('select'),label=document.createElement('label');label.textContent='Predicted record ';label.append(select);$('vq-tool').closest('label').after(label);
function state(){const a=d.visualizations[$('vq-sample').value],p=$('vq-plasmid').value,t=$('vq-tool').value;return a&&a.tools[t]?{a,p,t}:null}
function render(){const x=state();if(!x||!x.p){select.innerHTML='';return}const records=[...new Set(x.a.tools[x.t].blocks.filter(b=>b.target===x.p).map(b=>b.record_id))].sort();select.innerHTML=records.map(r=>`<option value="${r}">${r}</option>`).join('');draw()}
function draw(){const x=state(),record=select.value;if(!x||!record)return;const blocks=x.a.tools[x.t].blocks.filter(b=>b.target===x.p&&b.record_id===record).map((b,i)=>Object.assign({__i:i},b)),query=Math.max(...blocks.map(b=>b.query_length),1),truth=x.a.truth_plasmids[x.p].length,sx=v=>30+v/truth*420,sy=v=>450-v/query*420;const lines=blocks.map(b=>`<line class="dpl" data-i="${b.__i}" x1="${sx(b.target_start)}" y1="${sy(b.query_start)}" x2="${sx(b.target_end)}" y2="${sy(b.query_end)}" stroke="${b.strand==='-'?'#7f5aa2':'#16805a'}" stroke-width="3" style="cursor:pointer"><title>${b.record_id} ${b.target_start.toLocaleString()}–${b.target_end.toLocaleString()} on ${b.target}, ${b.strand==='-'?'reverse':'forward'} strand, ${(100*b.matches/Math.max(1,b.block_length)).toFixed(1)}% identity, mapQ ${b.mapq}</title></line>`).join('');$('vq-dotplot').innerHTML=`<h3>Dot plot: ${record} vs ${x.p}</h3><p class="muted">One predicted-record coordinate system is shown at a time. Forward diagonals support collinearity; reverse diagonals show reverse orientation. This is a diagnostic, not structural validation.</p><svg viewBox="0 0 480 480" width="480" role="img" aria-label="Dot plot"><rect x="30" y="30" width="420" height="420" fill="#f7f8f5" stroke="#849387"/>${lines}<text x="180" y="475" font-size="11">truth plasmid coordinate</text><text x="2" y="20" font-size="11">predicted-record coordinate</text></svg>`}
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
 const refresh=()=>{const q=($('vq-protein-search').value||'').toLowerCase(),c=$('vq-protein-category').value,shown=truth.filter(f=>(!c||f.category===c)&&(!q||(`${label(f)} ${f.product||''} ${f.dbxref||''}`).toLowerCase().includes(q)));$('vq-protein-body').innerHTML=shown.map(f=>{const s=status(f,pred);return `<tr><td>${label(f)}</td><td>${f.product||'hypothetical protein'}</td><td>${f.category||'other'}</td><td>${f.start}-${f.end} (${f.strand})</td><td><span class="vq-protein-status ${s}">${s==='complete'?'coordinate-complete':s==='partial'?'coordinate-partial':'not projected'}</span></td><td>${f.source} ${f.version} · ${f.confidence}</td></tr>`}).join('')||'<tr><td colspan="6">No protein annotations match this filter. Enable standardized annotation to populate this view.</td></tr>'};$('vq-protein-category').addEventListener('change',refresh);$('vq-protein-search').addEventListener('input',refresh);refresh();overlay()}
 ['vq-sample','vq-tool','vq-plasmid','vq-start','vq-end'].forEach(id=>$(id).addEventListener('change',()=>setTimeout(render,0)));['vq-fit','vq-in','vq-out'].forEach(id=>$(id).addEventListener('click',()=>setTimeout(render,0)));render()})();
</script>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--tool-status", required=True)
    ap.add_argument("--leaderboard", required=True)
    ap.add_argument("--sample-sheet", help="Optional curated sample-sheet TSV for cohort filters.")
    ap.add_argument("--manifest", help="Optional run manifest used to show/filter tool versions.")
    ap.add_argument("--comparisons", help="Optional paired-comparison TSV from aggregation.")
    ap.add_argument("--score-failures", help="Optional score failure TSV from stage 5.")
    ap.add_argument("--recommendations", help="Optional coverage-gated operational recommendation TSV.")
    ap.add_argument("--recommendation-validation", help="Optional leave-one-study-out recommendation validation TSV.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    project = Path(args.project_root).resolve()
    out = Path(args.out).resolve()
    scores = read_tsv(args.scores)
    status = read_tsv(args.tool_status) if Path(args.tool_status).is_file() else []
    leaderboard = read_tsv(args.leaderboard)
    metadata = read_sample_metadata(args.sample_sheet)
    tool_versions = read_tool_versions(args.manifest)
    comparisons = read_tsv(args.comparisons) if args.comparisons and Path(args.comparisons).is_file() else []
    score_failures = read_tsv(args.score_failures) if args.score_failures and Path(args.score_failures).is_file() else []
    recommendations = read_tsv(args.recommendations) if args.recommendations and Path(args.recommendations).is_file() else []
    recommendation_validation = read_tsv(args.recommendation_validation) if args.recommendation_validation and Path(args.recommendation_validation).is_file() else []
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    tools = sorted({row["tool"] for row in scores} | {row["tool"] for row in status})
    samples = sorted({row["sample"] for row in scores} | {row["sample"] for row in status})
    organisms = sorted({row.get("organism") or "" for row in metadata.values()} - {""})
    technologies = sorted({row.get("truth_technology") or "" for row in metadata.values()} - {""})
    tiers = sorted({row.get("truth_quality_tier") or "" for row in metadata.values()} - {""})
    origins = sorted({row.get("sample_origin") or "" for row in metadata.values()} - {""})
    versions = sorted(set(tool_versions.values()))
    tracks = sorted({row.get("analysis_track") or "short_read" for row in scores})
    status_counts = Counter(row["status"] for row in status)
    best = leaderboard[0] if leaderboard else None
    score_by_sample = defaultdict(list)
    score_by_tool = defaultdict(list)
    for row in scores:
        score_by_sample[row["sample"]].append(row)
        score_by_tool[row["tool"]].append(row)

    leaderboard_rows = "".join(
        "<tr><td>{rank}</td><td>{tool}</td><td>{scored}</td><td>{completed}</td>"
        "<td>{failed}</td><td>{skipped}</td><td>{precision}</td><td>{recall}</td><td>{plasmid_recall}</td><td>{bin_f1}</td>"
        "<td><strong class='score {band}'>{f1}</strong><span class='f1-bar {band}'><i style='width:{f1_width}%'></i></span></td></tr>".format(
            rank=esc(row.get("rank", "-")), tool=esc(row["tool"]),
            scored=esc(row.get("n_samples", "0")), completed=esc(row.get("n_completed", "0")),
            failed=esc(row.get("n_failed", "0")), skipped=esc(row.get("n_skipped", "0")),
            precision=esc(row["mean_precision"]), recall=esc(row["mean_recall"]),
            plasmid_recall=esc(row.get("mean_plasmid_recall") or "not annotated"),
            bin_f1=esc(row.get("mean_bin_f1") or "not bin-scored"), f1=esc(row["mean_f1"]),
            f1_width=max(0, min(100, round(number(row["mean_f1"]) * 100))),
            band=score_band(number(row["mean_f1"])),
        ) for row in leaderboard
    ) or "<tr><td colspan='11'>No scored tools yet.</td></tr>"

    score_rows = "".join(score_row(row, metadata, tool_versions) for row in scores)
    score_rows = score_rows or "<tr><td colspan='13'>No score rows were produced.</td></tr>"

    bin_rows = []
    for row in scores:
        if not row.get("bin_f1"):
            continue
        sample, tool = row["sample"], row["tool"]
        matches = out.parent / sample / f"{tool}.bin_matches.tsv"
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

    recommendation_rows = "".join(
        "<tr><td>{scope}</td><td>{group}</td><td>{tool}</td><td>{state}</td><td>{n}</td><td>{coverage}</td>"
        "<td>{f1}</td><td>{plasmid}</td><td>{runtime}</td><td>{memory}</td><td>{reason}</td></tr>".format(
            scope=esc(row.get("scope", "-")), group=esc(row.get("group", "-")),
            tool=esc(row.get("tool", "-")),
            state="Eligible operational method" if row.get("recommendation") == "primary" else "Candidate only",
            n=esc(row.get("n_scored", "0")), coverage=esc(row.get("coverage", "-")),
            f1=esc(row.get("mean_f1", "-")), plasmid=esc(row.get("mean_plasmid_recall", "-")),
            runtime=esc(row.get("median_runtime_seconds") or "not recorded"),
            memory=esc(row.get("median_peak_rss_kb") or "not recorded"),
            reason=esc(row.get("reason", "-")),
        ) for row in recommendations if row.get("recommendation") == "primary"
    ) or "<tr><td colspan='11'>No coverage-gated recommendation was produced for this cohort or stratum.</td></tr>"

    validation_rows = "".join(
        "<tr><td>{study}</td><td>{held}</td><td>{tool}</td><td>{train}</td><td>{f1}</td><td>{status}</td><td>{note}</td></tr>".format(
            study=esc(row.get("held_out_study") or "-"), held=esc(row.get("held_out_samples") or "0"),
            tool=esc(row.get("selected_method_from_training") or "No selection"),
            train=esc(row.get("training_samples") or "0"), f1=esc(row.get("held_out_mean_f1") or "-"),
            status=esc(row.get("status") or "not assessed"), note=esc(row.get("note") or "-"))
        for row in recommendation_validation
    ) or "<tr><td colspan='7'>No leave-one-study-out validation file was available.</td></tr>"

    comparison_rows = "".join(
        "<tr><td>{a}</td><td>{b}</td><td>{n}</td><td>{difference}</td><td>{ci}</td><td>{p}</td><td>{holm}</td><td>{wins}/{ties}/{losses}</td></tr>".format(
            a=esc(row["tool_a"]), b=esc(row["tool_b"]), n=esc(row["paired_samples"]),
            difference=esc(row["mean_f1_difference"]),
            ci=esc((row.get("difference_ci_low") and row.get("difference_ci_high") and
                    f"{row['difference_ci_low']} to {row['difference_ci_high']}") or "not estimated (n < 5)"),
            p=esc(row.get("permutation_p_value") or "not estimated (n < 5)"),
            holm=esc(row.get("permutation_p_value_holm") or "not estimated (n < 5)"),
            wins=esc(row["wins_a"]), ties=esc(row["ties"]), losses=esc(row["wins_b"]),
        ) for row in comparisons
    ) or "<tr><td colspan='8'>No paired score rows are available.</td></tr>"
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
            "<tr><td>{tool}</td><td>{p}</td><td>{r}</td><td><strong>{f1}</strong></td><td>{fp:,}</td><td>{unmapped:,}</td></tr>".format(
                tool=esc(row["tool"]), p=esc(row["precision"]), r=esc(row["recall"]), f1=esc(row["f1"]),
                fp=int(number(row["FP_bp"])), unmapped=int(number(row["unmapped_pred_bp"])),
            ) for row in rows
        ) or "<tr><td colspan='6'>No completed tool was scored for this sample.</td></tr>"
        selection = out.parent / "selected_candidates" / sample / f"{sample}.selection_report.json"
        if not selection.is_file():
            selection = out.parent / sample / "selected_candidate" / "selection_report.json"
        selection_link = (f" <a href='{relative_link(selection, out)}' download>Download selected-candidate report</a>"
                          if selection.is_file() else "")
        selection_cards.append(selection_card(sample, out.parent, out))
        sample_sections.append(
            "<details class='sample'><summary><strong>{}</strong><span>{} scored tool(s)</span></summary>"
            "<p class='lead'>{} </p><table><thead><tr><th>Tool</th><th>Precision</th><th>Recall</th><th>F1</th><th>Chromosome FP bp</th><th>Unmapped bp</th>"
            "</tr></thead><tbody>{}</tbody></table></details>".format(
                esc(sample), len(rows), selection_link or "No selected-candidate report was produced.", body)
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

    roots = [("Results", out.parent), ("Logs", project / "logs"), ("Data", project / "data")]
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
    best_f1 = esc(best["mean_f1"]) if best else "-"
    insight_notes, insight_tone = interpretation(leaderboard, status_counts)
    cards = report_cards(leaderboard, scores)
    findings = guided_findings(leaderboard, cards, scores, status_counts)
    summary_html = summary_section(leaderboard, cards, findings, scores, status_counts, metadata)
    insight_html = "".join(f"<li>{esc(note)}</li>" for note in insight_notes)
    chart_html = performance_chart(leaderboard)
    glossary_cards = glossary_section()
    vendor_html = vendor_assets(args.project_root)
    visual_html = (visual_quality_section(scores, status, out.parent, out) + advanced_visual_script()
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
    explorer_html = evidence_explorer_section(args.project_root, scores, out.parent,
                                              vendor_html, visual_html)
    enterprise_html = enterprise_view_section(args.project_root, scores, status, leaderboard,
                                              metadata, out.parent, vendor_html, explorer_html)
    page = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PlasBench: Plasmid reconstruction benchmark</title>
{vendor_html}
<style>
:root{{--ink:#17231d;--muted:#627067;--line:#d9e1da;--paper:#f6f8f4;--card:#fff;--green:#0c6b4f;--lime:#dcefdc;--amber:#9a5b00;--red:#a53028;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}} header{{background:#183a2d;color:#fff;padding:48px max(24px,calc((100vw - 1320px)/2));border-bottom:6px solid #a8d29b}} h1,h2,h3,th,.nav,button,select,input,.metric,.status,.selection-card{{font-family:Arial,sans-serif}} h1{{font-size:clamp(28px,5vw,48px);margin:0 0 8px;letter-spacing:-.04em}} header p{{margin:0;color:#d9e7de}} main{{max-width:1320px;margin:auto;padding:28px 24px 64px}} .nav{{display:flex;gap:6px;margin:0 0 26px;padding:6px;background:#fff;border:1px solid var(--line);border-radius:10px;overflow-x:auto;position:sticky;top:0;z-index:30;box-shadow:0 1px 3px rgba(21,36,28,.07);scrollbar-width:thin}} .nav a{{flex:0 0 auto;color:var(--muted);border:0;background:transparent;padding:8px 14px;text-decoration:none;font:600 13px Arial,sans-serif;border-radius:7px;white-space:nowrap;transition:background .15s,color .15s}} .nav a:hover{{background:#eef4ef;color:var(--ink)}} .nav a:focus-visible{{outline:2px solid var(--ink);outline-offset:-2px}} .nav a[aria-current='true']{{background:var(--green);color:#fff}} @media(prefers-reduced-motion:reduce){{.nav a{{transition:none}}}} section{{scroll-margin-top:64px}} .metrics{{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:12px;margin-bottom:28px}} .metric{{background:var(--card);border-top:4px solid var(--green);padding:15px;box-shadow:0 1px 3px #15241c12}} .metric small{{color:var(--muted);display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em}} .metric strong{{font-size:27px;display:block;margin-top:4px}} section{{margin:38px 0}} h2{{font-size:21px;margin:0 0 5px}} h3{{margin:6px 0;font-size:17px}} .lead,.muted{{color:var(--muted)}} .panel{{background:var(--card);border:1px solid var(--line);overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:760px;font-family:Arial,sans-serif;font-size:13px}} th{{background:#edf2ec;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .sortable th{{cursor:pointer}} .sortable th:hover{{background:#dcebdc}} td{{border-top:1px solid var(--line);padding:9px 10px;white-space:nowrap}} tr:hover td{{background:#f5faf4}} .f1-bar{{display:block;width:100%;height:5px;background:#deeadf;margin-top:4px;min-width:64px}} .f1-bar i{{display:block;height:100%;background:var(--green)}} .f1-bar.medium i{{background:#c68221}} .f1-bar.low i{{background:#bd4b42}} .score.high{{color:#087250}} .score.medium{{color:#9a5b00}} .score.low{{color:#a53028}} .insight{{border-left:6px solid var(--green);background:#e7f1e7;padding:16px 20px}} .insight.caution{{border-color:var(--amber);background:#fbf2df}} .insight ul{{margin:6px 0 0;padding-left:20px}} .chart-card{{background:#fff;border:1px solid var(--line);padding:18px;overflow:auto}} .performance-chart{{display:block;min-width:650px;width:100%;height:auto}} .performance-chart .axis,.performance-chart .label{{font:12px Arial,sans-serif;fill:#536158}} .chart-legend,.legend{{display:flex;gap:16px;flex-wrap:wrap;font:12px Arial,sans-serif;margin:10px 0}} .chart-legend i,.legend i{{display:inline-block;width:10px;height:10px;margin-right:5px}} .metadata{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);font-family:Arial,sans-serif;font-size:13px}} .metadata div{{background:#fff;padding:12px}} .metadata small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.06em}} .controls{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}} select,input{{padding:7px;border:1px solid var(--line);background:#fff}} .count{{font:12px Arial,sans-serif;color:var(--muted);align-self:center}} .status,.selection-label{{display:inline-block;padding:2px 7px;border-radius:12px;font-size:11px;font-weight:bold}} .completed,.reused{{background:#dcefdc;color:#07573e}} .failed{{background:#f7ddda;color:var(--red)}} .skipped{{background:#f6ead1;color:var(--amber)}} .selection-card{{display:grid;grid-template-columns:1fr auto;gap:14px;background:#fff;border:1px solid var(--line);border-left:6px solid var(--amber);padding:18px;margin:12px 0}} .selection-card.confident{{border-left-color:var(--green)}} .selection-label{{background:#f6ead1;color:#765000}} .confident .selection-label{{background:#dcefdc;color:#07573e}} .selection-actions{{text-align:right;min-width:190px}} .download-button{{display:inline-block;background:var(--green);color:#fff!important;padding:8px 10px;text-decoration:none;font-weight:bold}} .selection-card details{{grid-column:1/-1;border-top:1px solid var(--line)}} .selection-card summary{{padding:10px 0;cursor:pointer;font-weight:bold}} .selection-card ul{{margin:0;padding-left:20px}} details.sample,.explorer{{background:var(--card);border:1px solid var(--line);margin:10px 0;padding:0 14px}} details summary{{cursor:pointer;padding:13px 0;font-family:Arial,sans-serif}} details summary span{{float:right;color:var(--muted);font-size:12px}} .file-tree{{list-style:none;padding-left:18px;margin:0 0 15px;font-family:Arial,sans-serif;font-size:13px}} .file-tree li{{padding:3px 0}} .file-tree details summary{{padding:3px 0}} .file-tree a{{color:var(--green);text-decoration:none;font-weight:600}} .file-tree .file span{{color:var(--muted);font-size:11px;margin-left:8px}} .method{{columns:2;column-gap:32px;background:#ebf2ea;padding:18px 22px}}  .sum-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:14px 0 26px}} .sum-stat{{background:#fff;border:1px solid var(--line);border-top:4px solid var(--green);padding:14px 16px}} .sum-stat small{{display:block;color:var(--muted);text-transform:uppercase;font-size:10.5px;letter-spacing:.08em}} .sum-stat strong{{display:block;font-size:24px;margin-top:5px;line-height:1.15}} .grade{{display:inline-block;min-width:30px;text-align:center;font-weight:bold;font-size:15px;padding:3px 9px;border-radius:5px;font-family:Arial,sans-serif}} .grade-a{{background:#dcefdc;color:#07573e;border:2px solid #17805a}} .grade-b{{background:#e4eef8;color:#17457e;border:2px solid #2563c9}} .grade-c{{background:#f6ead1;color:#765000;border:2px solid #a35c05}} .grade-d{{background:#f7ddda;color:#8c2018;border:2px solid #b3261e}} .grade-e{{background:#efe3e1;color:#5f1a14;border:2px solid #7a1b14}} .findings{{list-style:none;padding:0;margin:12px 0 0;display:grid;gap:10px}} .finding{{background:#fff;border:1px solid var(--line);border-left:5px solid var(--muted);padding:14px 18px}} .finding.good{{border-left-color:var(--green)}} .finding.caution{{border-left-color:var(--amber)}} .finding .flabel{{font:bold 11px Arial,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .finding p{{margin:5px 0 8px;font-size:14px}} .finding .goto{{font:bold 13px Arial,sans-serif;color:var(--green);text-decoration:none}} .finding .goto:hover{{text-decoration:underline}} .term-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} .term-card{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:14px 16px}} .term-card h3{{margin:0 0 6px;font-size:15px}} .term-card .what{{margin:0 0 8px;font-size:13.5px}} .term-card .why{{margin:0;font-size:13px;color:var(--muted)}} .method p{{margin-top:0;break-inside:avoid}} footer{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}} @media(max-width:700px){{main{{padding:20px 14px}}header{{padding:32px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metadata{{grid-template-columns:1fr}}.method{{columns:1}}.selection-card{{grid-template-columns:1fr}}.selection-actions{{text-align:left}}}}
</style></head><body>
<header><h1>PlasBench: Plasmid reconstruction benchmark</h1><p>Detailed run report · generated {esc(generated)} · offline HTML with direct artifact downloads</p></header>
<main><nav class='nav' aria-label='Report sections'><a href='#summary'>Summary</a><a href='#metadata'>Run metadata</a><a href='#insights'>Interpretation</a><a href='#chart'>Metric chart</a><a href='#leaderboard'>Method ranking</a><a href='#recommendations'>Recommendations</a><a href='#validation'>Study validation</a><a href='#selected'>Selected reconstructions</a><a href='#scores'>All scores</a><a href='#statistics'>Statistics</a><a href='#bin-diagnostics'>Bin diagnostics</a><a href='#health'>Run health</a><a href='#tools'>Tool drill-down</a><a href='#samples'>Sample drill-down</a><a href='#keys'>Keys and legend</a><a href='#files'>File explorer</a><a href='#method'>Method</a></nav>
<div class='metrics'><div class='metric'><small>Samples observed</small><strong>{len(samples)}</strong></div><div class='metric'><small>Tools observed</small><strong>{len(tools)}</strong></div><div class='metric'><small>Benchmark winner: mean F1</small><strong>{best_f1}</strong><small>{best_value} · method ranking only</small></div><div class='metric'><small>Execution issues</small><strong>{status_counts['failed'] + status_counts['skipped']}</strong><small>{status_counts['failed']} failed · {status_counts['skipped']} skipped</small></div></div>
{summary_html}
<section id='metadata'><h2>Run and output metadata</h2><div class='metadata'><div><small>Report generated</small>{esc(generated)}</div><div><small>Score observations</small>{len(scores)} sample-tool row(s)</div><div><small>Tracked artifacts</small>{artifact_count} file(s) · {esc(size_text(artifact_bytes))}</div><div><small>Execution states</small>{status_counts['completed']} completed · {status_counts['reused']} reused · {status_counts['failed']} failed · {status_counts['skipped']} skipped</div><div><small>Scoring inputs</small>scores.tsv, tool_status.tsv, benchmark.leaderboard.tsv</div><div><small>Reference scope</small>Complete assembly reference bases; plasmid is the positive class</div></div></section>
<section id='insights'><h2>Automated interpretation</h2><div class='insight {insight_tone}'><p class='lead'>Generated from the score and execution-status tables. Where at least five shared samples exist, the statistics section adds paired confidence intervals and permutation evidence with Holm adjustment.</p><ul>{insight_html}</ul></div></section>
<section id='chart'><h2>Performance profile</h2><p class='lead'>Mean precision, recall, and F1 by tool. Green is precision, amber is recall, and dark green is F1; bar length spans 0 to 1.</p><div class='chart-card'>{chart_html}</div></section>
<section id='leaderboard'><h2>Benchmark method ranking</h2><p class='lead'>This compares methods across this benchmark cohort. It is not, by itself, a claim that the top method has produced a biologically confirmed plasmid for every sample. Plasmid recall gives equal weight to each truth plasmid, limiting domination by a large replicon. Mean bin F1 is shown only for declared binning methods; “not applicable” is not a zero. Select a column heading to sort.</p><div class='panel'><table class='sortable'><thead><tr><th>Rank</th><th>Tool</th><th>Scored</th><th>Completed</th><th>Failed</th><th>Skipped</th><th>Mean precision</th><th>Mean base recall</th><th>Mean plasmid recall</th><th>Mean bin F1</th><th>Mean F1</th></tr></thead><tbody>{leaderboard_rows}</tbody></table></div></section>
<section id='recommendations'><h2>Operational method recommendations</h2><p class='lead'>These are coverage-gated, multi-objective method recommendations, not proof that any individual predicted sequence is correct. Accuracy is primary; failure rate, structural diagnostics, runtime, and memory are included as lower-weighted practical considerations. Each scored isolate also has a reusable <code>selected_candidate/</code> folder containing the chosen already-generated FASTA and a JSON explanation.</p><div class='panel'><table class='sortable'><thead><tr><th>Scope</th><th>Group</th><th>Primary method</th><th>State</th><th>Scored</th><th>Coverage</th><th>Mean F1</th><th>Mean plasmid recall</th><th>Median runtime s</th><th>Median peak RSS KiB</th><th>Decision note</th></tr></thead><tbody>{recommendation_rows}</tbody></table></div></section>
<section id='validation'><h2>Leave-one-study-out validation</h2><p class='lead'>For each source study, the method is selected using all other studies and then evaluated only on the held-out study. A withheld result means the cohort does not yet have enough independent study evidence; it is not a failed method.</p><div class='panel'><table class='sortable'><thead><tr><th>Held-out study</th><th>Held-out samples</th><th>Training-selected method</th><th>Training samples</th><th>Held-out mean F1</th><th>Status</th><th>Interpretation</th></tr></thead><tbody>{validation_rows}</tbody></table></div></section>
<section id='selected'><h2>Selected reconstructions</h2><p class='lead'>Each card translates its <code>selection_report.json</code> into a research-facing decision. Downloading the selected FASTA does not rerun any reconstruction; it retrieves the original output retained from the completed tool run.</p>{''.join(selection_cards) or "<p class='muted'>No sample-level selection reports were produced.</p>"}</section>
<section id='scores'><h2>All sample-tool scores</h2><p class='lead'>Filter by performance, tool provenance, or cohort metadata; export the exact visible subset. Unambiguous, ambiguous, and unmapped predicted bases are separate categories. AMR and circular-truth recovery are unavailable (-) unless curated truth annotations were supplied. Circular-truth recovery is not evidence that a predicted sequence is closed.</p><div class='controls'><label>Sample <select id='sample-filter'><option value=''>All samples</option>{''.join(f"<option>{esc(s)}</option>" for s in samples)}</select></label><label>Tool <select id='tool-filter'><option value=''>All tools</option>{''.join(f"<option>{esc(t)}</option>" for t in tools)}</select></label><label>Tool version <select id='version-filter'><option value=''>All versions</option><option>not recorded</option>{''.join(f"<option>{esc(v)}</option>" for v in versions)}</select></label><label>Organism <select id='organism-filter'><option value=''>All organisms</option>{''.join(f"<option>{esc(v)}</option>" for v in organisms)}</select></label><label>Origin <select id='origin-filter'><option value=''>All origins</option>{''.join(f"<option>{esc(v)}</option>" for v in origins)}</select></label><label>Truth technology <select id='tech-filter'><option value=''>All technologies</option>{''.join(f"<option>{esc(v)}</option>" for v in technologies)}</select></label><label>Truth tier <select id='tier-filter'><option value=''>All tiers</option>{''.join(f"<option>{esc(v)}</option>" for v in tiers)}</select></label><label>Plasmid size <select id='size-filter'><option value=''>All sizes</option><option value='small'>Small (&lt;10 kb)</option><option value='medium'>Medium (10–100 kb)</option><option value='large'>Large (≥100 kb)</option></select></label><label>Depth ≥ <input id='depth-min' type='number' min='0' step='any' placeholder='any'></label><label>Depth ≤ <input id='depth-max' type='number' min='0' step='any' placeholder='any'></label><label>F1 band <select id='band-filter'><option value=''>All bands</option><option value='high'>High (≥0.90)</option><option value='medium'>Medium (0.70–0.89)</option><option value='low'>Low (&lt;0.70)</option></select></label><button id='export-scores' type='button'>Download filtered CSV</button><span id='score-count' class='count'></span></div><div class='panel'><table id='score-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Tool version</th><th>Origin</th><th>Read depth ×</th><th>True plasmid bp</th><th>TP bp</th><th>FP bp</th><th>FN bp</th><th>Unambiguous predicted bp</th><th>Ambiguous predicted bp</th><th>Unmapped predicted bp</th><th>Precision</th><th>Recall</th><th>AMR recovery</th><th>Circular truth recovery</th><th>F1</th></tr></thead><tbody>{score_rows}</tbody></table></div></section>
<section id='statistics'><h2>Paired tool comparisons</h2><p class='lead'>Differences are tool A minus tool B on shared samples. Confidence intervals and two-sided sign-flip permutation p-values require at least five pairs. Holm values control family-wise error across comparisons and remain descriptive evidence, not a substitute for study design.</p><div class='panel'><table class='sortable'><thead><tr><th>Tool A</th><th>Tool B</th><th>Pairs</th><th>Mean F1 difference</th><th>95% bootstrap CI</th><th>Permutation p</th><th>Holm-adjusted p</th><th>A wins / ties / B wins</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><p class='lead'>Score-stage isolation events:</p><ul>{score_failure_html}</ul></section>
<section id='bin-diagnostics'><h2>Bin reconstruction diagnostics</h2><p class='lead'>Only tools with validated bin membership are shown. A split is one truth plasmid represented by multiple candidate bins; a merge is one candidate bin with high-completeness evidence for multiple truth plasmids. Repeat ambiguity is bin sequence with both plasmid and chromosome mapping alternatives. Contamination fraction is chromosome-aligned bp divided by all truth-mapped bin bp. Open each matches TSV for bin-to-truth assignments, unmatched bins, and missed plasmids.</p><div class='panel'><table class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Bin precision</th><th>Bin recall</th><th>Bin F1</th><th>Matched bins</th><th>Unmatched bins</th><th>Missed plasmids</th><th>Split events</th><th>Merge events</th><th>Contaminated bins</th><th>Repeat ambiguity bp</th><th>Contamination fraction</th><th>Record-level detail</th></tr></thead><tbody>{bin_diagnostics_html}</tbody></table></div></section>
<section id='health'><h2>Execution health</h2><p class='lead'>A failed or unavailable tool is excluded from F1 aggregation. Runtime is elapsed wall-clock seconds; peak RSS is shown when the host profiler provides it.</p><div class='controls'><label>Status <select id='status-filter'><option value=''>All states</option><option value='completed'>Completed</option><option value='reused'>Reused</option><option value='failed'>Failed</option><option value='skipped'>Skipped</option></select></label><span id='status-count' class='count'></span></div><div class='panel'><table id='status-table' class='sortable'><thead><tr><th>Sample</th><th>Tool</th><th>Status</th><th>Runtime s</th><th>Peak RSS KiB</th><th>Reason / log location</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
<section id='tools'><h2>Tool drill-down</h2><p class='lead'>Open a tool to inspect its score distribution across samples. Rows are initially ordered by F1.</p>{''.join(tool_sections) or "<p class='muted'>No tools were found.</p>"}</section>
<section id='samples'><h2>Sample drill-down</h2><p class='lead'>Open a sample to compare every completed tool side-by-side.</p>{''.join(sample_sections) or "<p class='muted'>No samples were found.</p>"}</section>
<section id='keys'><h2>Keys, legend, and metric definitions</h2><p class='lead'>Every term the report uses, what it measures, and why it matters. The same text appears as a tooltip wherever the term is used, so this page is a reference rather than the only place an explanation exists.</p><div class='legend'><span><i style='background:#087250'></i>High F1: &ge;0.90</span><span><i style='background:#c68221'></i>Medium F1: 0.70&ndash;0.89</span><span><i style='background:#bd4b42'></i>Low F1: &lt;0.70</span><span class='muted'>Bands are visual aids, not acceptance thresholds.</span></div><div class='term-grid'>{glossary_cards}</div></section>
<section id='files'><h2>Artifact explorer</h2><p class='lead'>All files created or consumed by this project are listed below. Select a filename to open or download it; directory branches can be expanded independently.</p>{''.join(explorers)}</section>
<section id='method'><h2>Scoring method and interpretation</h2><div class='method'><p><strong>Truth:</strong> sequences in each complete reference assembly are labelled plasmid or chromosome from the NCBI sequence report.</p><p><strong>Prediction:</strong> each tool’s standardized predicted-plasmid FASTA is aligned to the reference using minimap2.</p><p><strong>Metrics:</strong> covered plasmid reference bases are TP; covered chromosome reference bases are FP; uncovered plasmid bases are FN. Precision measures contamination control; recall measures plasmid completeness; F1 balances both.</p><p><strong>Run integrity:</strong> failed tool execution, failed adaptation, and mapping failure do not become zero-score observations. They appear in execution health and reduce the completed/scored counts shown in the leaderboard.</p></div></section>
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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote HTML report: {out}")


if __name__ == "__main__":
    main()
