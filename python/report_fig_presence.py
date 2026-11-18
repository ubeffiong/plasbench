#!/usr/bin/env python3
"""
report_fig_presence.py -- a clustered presence/absence matrix of the truth plasmids and their features, with prevalence bars and a tool overlay.

  fig-presence   Rows are the truth plasmids, clustered on their feature profile (a dendrogram on the left); columns are features grouped in blocks:
                 AMR gene classes (or genes), replicon types, MOB (mobility) types, and any further feature type or protein class the annotation tables
                 hold (insertion sequences, virulence, ...). Only blocks the data contain are drawn. Annotation tracks beside the dendrogram: species,
                 source study, reference tier, size band, replicon. Bars above each block: the share of annotated plasmids that carry the feature, with n.
                 Blue = present; blank = annotated and absent; hatched = NOT ANNOTATED for that block (the annotation table of that sample is missing).
                 A tool selector overlays the REAL outcome of that tool on each plasmid: recovered (counted correct by CPRR), partly recovered (some
                 truth bases covered, not counted correct), missed (no truth base covered); no tool selected shows the truth only.

Where the data come from (per sample folder, data_dir first then results_dir): truth.tsv (plasmids, length), truth_amr.tsv (genes; the class comes from
config/amr_gene_classes.tsv), truth_features.tsv (replicon, mob, insertion_sequence, ...), truth_proteins.tsv (gene categories other than replicon / amr / mob),
truth_circular.tsv, samples.tsv / benchmark.* tables (species, study, tier), <tool>.per_plasmid.tsv and <tool>.cprr.tsv (the outcome overlay).
Nothing is invented: a feature appears only if an annotation table lists it; a plasmid whose sample has no table for a block is "not annotated" there.

Clustering (pure Python, deterministic; mirrored nowhere, the order is computed here and shipped): the profile of a plasmid is the set of features present in the
annotated blocks; the distance is the Jaccard distance (1 - |A and B| / |A or B|, 0 for two empty profiles); average linkage (UPGMA); identical profiles are merged first
(distance 0) and the clustering is run over the distinct profiles; ties are broken by the lower cluster index; the leaf order puts the cluster holding the lower first
member first. Over MAX_PROFILES distinct profiles the dendrogram is not drawn and rows are ordered by profile (the figure says so).

  build_payload(results_dir, data_dir, scores_path) -> (payload or None, reason)
  cluster(profiles) -> (order, merges)       leaves 0..n-1, merges [[a, b, height], ...] with new node ids n, n+1, ...
  prevalence / outcomes helpers the tests exercise
  inject(page, results_dir, data_dir, scores_path)   add the section `fig-presence` before Recommendations

Standard library only.
"""
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_common as rc  # noqa: E402
import report_fig_facets as ff  # noqa: E402

SID = "fig-presence"
TITLE = "Which features the truth plasmids carry, and which tools recovered them"
SECTIONS = [(SID, "Feature matrix")]
MAX_PROFILES = 300
MAX_FEATURES_PER_BLOCK = 30
NOT_REC = ff.NOT_REC
TRACKS = [("species", "Species"), ("study", "Source study"), ("tier", "Reference tier"), ("size", "Size band"), ("replicon", "Replicon")]
BLOCK_LABEL = {"replicon": "Replicon type", "mob": "Mobility (MOB type)", "amr_class": "AMR gene class", "amr_gene": "AMR gene", "insertion_sequence": "Insertion sequences"}
BLOCK_ORDER = ["replicon", "mob", "amr_class", "amr_gene"]
OUTCOME_CHAR = {"recovered": "r", "partial": "p", "missed": "m", None: "-"}
LEAD = ("Rows are the truth plasmids, clustered by the features they carry; columns are features in blocks. Blue is present, blank is annotated and absent, hatched is not "
        "annotated. Choose a tool to colour each plasmid by what that tool actually did with it. Click a plasmid or a feature for the details.")


# ------------------------------------------------------------------------------------------------ clustering
def jaccard(a, b):
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


def cluster(profiles):
    """Deterministic average-linkage (UPGMA) clustering of `profiles` (a list of sets) on Jaccard distance.

    Returns (order, merges). Identical profiles merge first at height 0. `order` is the leaf order (a list of indices into `profiles`); `merges` is a list of
    [a, b, height] where a and b are node ids (leaves are 0..n-1, merge k creates node n+k). Ties: lower pair of node ids first."""
    n = len(profiles)
    if n == 0:
        return [], []
    groups = {}
    for i, p in enumerate(profiles):
        groups.setdefault(frozenset(p), []).append(i)
    keys = sorted(groups, key=lambda k: groups[k][0])          # distinct profiles by the first member
    u = len(keys)
    members = {g: groups[k] for g, k in enumerate(keys)}      # cluster id -> member leaves
    dist = {}
    for a in range(u):
        for b in range(a + 1, u):
            dist[(a, b)] = jaccard(keys[a], keys[b])
    size = {g: 1 for g in range(u)}                            # profile groups under each cluster (the UPGMA weight is the number of profiles)
    active = list(range(u))
    merges_u = []                                               # over profile groups
    nxt = u
    while len(active) > 1:
        best, bp = None, None
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                key = (a, b) if a < b else (b, a)
                d = dist[key]
                if best is None or d < best - 1e-12 or (abs(d - best) <= 1e-12 and key < bp):
                    best, bp = d, key
        a, b = bp
        merges_u.append((a, b, best, nxt))
        for c in active:
            if c in (a, b):
                continue
            da = dist[(a, c) if a < c else (c, a)]
            db = dist[(b, c) if b < c else (c, b)]
            dist[(c, nxt) if c < nxt else (nxt, c)] = (da * size[a] + db * size[b]) / (size[a] + size[b])
        size[nxt] = size[a] + size[b]
        members[nxt] = members[a] + members[b]
        active = [c for c in active if c not in (a, b)] + [nxt]
        nxt += 1
    # expand to leaves: every profile group becomes a chain of zero-height merges over its members
    children = {}
    leaf_merges = []
    node_of = {}
    next_leaf_node = n
    for g in range(u):
        mem = groups[keys[g]]
        cur = mem[0]
        for m in mem[1:]:
            leaf_merges.append([cur, m, 0.0])
            cur = next_leaf_node
            next_leaf_node += 1
        node_of[g] = cur
    for a, b, h, new in merges_u:
        leaf_merges.append([node_of[a], node_of[b], round(h, 6)])
        node_of[new] = next_leaf_node
        next_leaf_node += 1
    nodes = {}
    for k, (a, b, h) in enumerate(leaf_merges):
        nodes[n + k] = (a, b)
    root = n + len(leaf_merges) - 1 if leaf_merges else 0

    def leaves(node):
        out, stack = [], [node]
        while stack:
            x = stack.pop()
            if x < n:
                out.append(x)
            else:
                a, b = nodes[x]
                stack.append(b)
                stack.append(a)
        return out
    order = leaves(root) if leaf_merges else [0]
    return order, leaf_merges


def profile_order(profiles):
    """Fallback order when there are too many distinct profiles: by number of features (desc), then the sorted feature ids; ties by index."""
    return sorted(range(len(profiles)), key=lambda i: (-len(profiles[i]), sorted(profiles[i]), i))


# ------------------------------------------------------------------------------------------------ features
def _block_title(kind):
    if kind in BLOCK_LABEL:
        return BLOCK_LABEL[kind]
    if kind.startswith("protein:"):
        return kind.split(":", 1)[1].replace("_", " ").capitalize() + " genes"
    return kind.replace("_", " ").capitalize()


def feature_blocks(pl):
    """[{k, l, ann: [row annotated?], feats: [(name, [rows])]}] in a fixed order: replicon, mob, AMR class, AMR gene, then the others by name."""
    rows = pl["rows"]
    kinds = {}
    for i, r in enumerate(rows):
        f = pl["feats"].get((r["sample"], r["id"])) or {}
        for name in f.get("replicon", ()):
            kinds.setdefault("replicon", {}).setdefault(name, []).append(i)
        for name in f.get("mob", ()):
            kinds.setdefault("mob", {}).setdefault(name, []).append(i)
        for name in f.get("amr_classes", ()):
            kinds.setdefault("amr_class", {}).setdefault(name, []).append(i)
        for name in f.get("amr_genes", ()):
            kinds.setdefault("amr_gene", {}).setdefault(name, []).append(i)
        for kind, names in (f.get("other") or {}).items():
            for name in names:
                kinds.setdefault(kind, {}).setdefault(name, []).append(i)

    def annotated(kind, r):
        if kind in ("amr_class", "amr_gene"):
            return bool(r["has_amr"])
        if kind.startswith("protein:"):
            return bool(pl["annotated"].get(r["sample"], {}).get("proteins"))
        return bool(r["has_features"])

    ordered = [k for k in BLOCK_ORDER if k in kinds] + sorted(k for k in kinds if k not in BLOCK_ORDER)
    out = []
    for kind in ordered:
        feats = sorted(kinds[kind].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        out.append({"k": kind, "l": _block_title(kind), "ann": [annotated(kind, r) for r in rows],
                    "feats": [(n, sorted(set(v))) for n, v in feats[:MAX_FEATURES_PER_BLOCK]], "omitted": max(0, len(feats) - MAX_FEATURES_PER_BLOCK)})
    return out


def prevalence(block, feature_rows):
    """(carriers, annotated, share) of one feature among the plasmids annotated for its block; share None when none is annotated."""
    n = sum(1 for a in block["ann"] if a)
    c = len([i for i in feature_rows if block["ann"][i]])
    return c, n, (c / n if n else None)


def outcome_string(pl, track_tool, rows):
    """One character per row: r recovered, p partly recovered, m missed, - no value for this tool."""
    per = pl["outcome"].get(track_tool) or {}
    out = []
    for r in rows:
        o = per.get((r["sample"], r["id"]))
        out.append(OUTCOME_CHAR[ff.plasmid_outcome(o["comp"], o["correct"]) if o else None])
    return "".join(out)


def build_payload(results_dir, data_dir, scores_path):
    scores = rc.read_tsv(scores_path)
    if scores is None:
        return None, "scores.tsv was not found."
    ctx = ff.sample_context(results_dir, data_dir, scores)
    tools = ff.tool_order(results_dir, scores)
    pl = ff.load_plasmids(results_dir, data_dir, ctx, tools)
    if not pl:
        return None, ("the per-sample truth tables (<sample>/truth.tsv with its truth_amr.tsv and truth_features.tsv) were not found in the data folder or "
                      "the results folder; the matrix is built from them, so rebuild the report with the run's data folder (--data-dir)")
    blocks = feature_blocks(pl)
    if not blocks:
        return None, "no annotation table lists a feature for these plasmids (truth_amr.tsv, truth_features.tsv and truth_proteins.tsv are empty or missing)"
    rows = pl["rows"]
    fidx = {}                       # (block index, feature index) -> global feature id
    profiles = [set() for _ in rows]
    gid = 0
    for bi, b in enumerate(blocks):
        for fi, (name, rws) in enumerate(b["feats"]):
            fidx[(bi, fi)] = gid
            for i in rws:
                if b["k"] != "amr_gene" and b["ann"][i]:       # AMR genes repeat the class block: cluster on the class level only
                    profiles[i].add(gid)
            gid += 1
    if len(set(frozenset(p) for p in profiles)) <= MAX_PROFILES:
        order, merges = cluster(profiles)
        clustered = True
    else:
        order, merges, clustered = profile_order(profiles), [], False
    tracks = []
    for key, label in TRACKS:
        vals = []
        per_row = []
        for r in rows:
            f = pl["feats"].get((r["sample"], r["id"])) or {}
            if key == "species":
                v = r["species"]
            elif key == "study":
                v = r["study"]
            elif key == "tier":
                v = r["tier"]
            elif key == "size":
                v = None if r["length"] is None else ff.size_band(r["length"])
            else:
                v = (" + ".join(sorted(f.get("replicon", ()))) or "no replicon annotated") if r["has_features"] else None
            per_row.append(v or NOT_REC)
        if all(v == NOT_REC for v in per_row):
            continue
        vals = ff.order_values(key if key in ff.ORDERS else "", per_row)
        tracks.append({"k": key, "l": label, "vals": vals, "r": [vals.index(v) for v in per_row]})
    tool_list, out = [], {}
    for t in tools:
        if t in pl["outcome"]:
            s = outcome_string(pl, t, rows)
            if set(s) != {"-"}:
                out[str(len(tool_list))] = s
                tool_list.append([t[0], t[1]])
    payload = {"v": 1, "rows": [[r["sample"], r["id"], r["length"], -1 if r["circular"] is None else int(r["circular"])] for r in rows],
               "tracks": tracks,
               "blocks": [{"k": b["k"], "l": b["l"], "na": [i for i, a in enumerate(b["ann"]) if not a], "omitted": b["omitted"],
                           "f": [[n, rws] for n, rws in b["feats"]]} for b in blocks],
               "order": order, "tree": merges, "clustered": clustered, "tools": tool_list, "out": out,
               "defaultAmr": "amr_class"}
    return payload, None


# ------------------------------------------------------------------------------------------------ static drawing
DW, TW, TG, FW, BGAP, BARH, LABH, RIGHT = 70, 9, 6, 8, 14, 46, 78, 12


def row_height(n):
    return max(3, min(12, 560 // max(1, n)))


def static_svg(payload, amr_mode="amr_class"):
    """The complete static figure: dendrogram, tracks, prevalence bars, matrix. Truth only (no tool overlay)."""
    rows = payload["rows"]
    n = len(rows)
    rh = row_height(n)
    blocks = [b for b in payload["blocks"] if b["k"] != ("amr_gene" if amr_mode == "amr_class" else "amr_class")]
    tracks = payload["tracks"]
    top = 20 + BARH + LABH
    x_tracks = DW + 6
    x_mat = x_tracks + len(tracks) * (TW + 1) + TG
    widths = [len(b["f"]) * FW for b in blocks]
    width = x_mat + sum(widths) + BGAP * len(blocks) + 12
    height = top + n * rh + 24
    pos = {r: k for k, r in enumerate(payload["order"])}
    o = [f"<svg class='fp-svg' viewBox='0 0 {width} {height}' role='img' aria-labelledby='fp-st-t fp-st-d' xmlns='http://www.w3.org/2000/svg' font-family='Arial,Helvetica,sans-serif'>",
         "<title id='fp-st-t'>Presence and absence of features on the truth plasmids</title>",
         f"<desc id='fp-st-d'>{n} truth plasmids in rows clustered by feature profile; {len(blocks)} blocks of features in columns. Blue is present, blank is absent, hatched is not annotated.</desc>",
         "<defs><pattern id='fp-hatch' width='4' height='4' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><rect width='4' height='4' fill='#e0e0e0'/>"
         "<line x1='0' y1='0' x2='0' y2='4' stroke='#777' stroke-width='1.2'/></pattern></defs>"]
    # dendrogram
    if payload["clustered"] and payload["tree"]:
        hmax = max(m[2] for m in payload["tree"]) or 1.0
        node = {i: (top + pos[i] * rh + rh / 2, 0.0) for i in range(n)}
        segs = []
        for k, (a, b, h) in enumerate(payload["tree"]):
            (ya, ha), (yb, hb) = node[a], node[b]
            x = DW - (h / hmax) * (DW - 4)
            xa, xb = DW - (ha / hmax) * (DW - 4), DW - (hb / hmax) * (DW - 4)
            segs.append(f"M{xa:.1f} {ya:.1f}H{x:.1f}V{yb:.1f}H{xb:.1f}")
            node[n + k] = ((ya + yb) / 2, h)
        o.append(f"<path d='{''.join(segs)}' fill='none' stroke='#555' stroke-width='.7'/>")
    # tracks
    for ti, t in enumerate(tracks):
        x = x_tracks + ti * (TW + 1)
        o.append(f"<text transform='translate({x + TW / 2},{top - 4}) rotate(-60)' font-size='8' fill='currentColor'>{rc.esc(t['l'])}</text>")
        for i in range(n):
            v = t["r"][i]
            colour = "#bbbbbb" if t["vals"][v] == NOT_REC else TRACK_COLOURS[v % len(TRACK_COLOURS)]
            o.append(f"<rect x='{x}' y='{top + pos[i] * rh}' width='{TW}' height='{rh}' fill='{colour}'><title>{rc.esc(t['l'])}: {rc.esc(t['vals'][v])}</title></rect>")
    # blocks
    x = x_mat
    for b, w in zip(blocks, widths):
        o.append(f"<text x='{x + w / 2}' y='11' font-size='10' font-weight='bold' text-anchor='middle' fill='currentColor'>{rc.esc(b['l'])}</text>")
        na = set(b["na"])
        for i in sorted(na):
            o.append(f"<rect x='{x}' y='{top + pos[i] * rh}' width='{w}' height='{rh}' fill='url(#fp-hatch)'><title>{rc.esc(rows[i][1])}: not annotated for {rc.esc(b['l'])}</title></rect>")
        annotated = n - len(na)
        for fi, (name, rws) in enumerate(b["f"]):
            fx = x + fi * FW
            carriers = [i for i in rws if i not in na]
            share = len(carriers) / annotated if annotated else None
            if share is not None:
                o.append(f"<rect x='{fx + 1}' y='{20 + BARH - share * BARH:.1f}' width='{FW - 2}' height='{share * BARH:.1f}' fill='#0072B2'>"
                         f"<title>{rc.esc(name)}: {len(carriers)} of {annotated} annotated plasmids ({share:.0%})</title></rect>")
            o.append(f"<text transform='translate({fx + FW / 2 + 3},{top - 3}) rotate(-90)' font-size='7.5' fill='currentColor'>{rc.esc(name)}</text>")
            for i in carriers:
                o.append(f"<rect x='{fx + .5}' y='{top + pos[i] * rh}' width='{FW - 1}' height='{max(1, rh - .6):.1f}' fill='#0072B2'/>")
        o.append(f"<line x1='{x}' x2='{x + w}' y1='{20 + BARH}' y2='{20 + BARH}' stroke='#777' stroke-width='.5'/>")
        x += w + BGAP
    o.append(f"<text x='{x_mat}' y='{height - 6}' font-size='9' fill='currentColor'>Bars: share of annotated plasmids carrying the feature (full height = 100%). Blue = present, blank = absent, hatched = not annotated.</text>")
    o.append("</svg>")
    return "".join(o)


TRACK_COLOURS = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#882255", "#117733", "#999933", "#44AA99"]


def table_html(payload):
    """The 'Table' fold: one row per plasmid with its annotation tracks and the features per block."""
    rows, body = payload["rows"], []
    blocks = payload["blocks"]
    for i in payload["order"]:
        cells = [rows[i][1], rows[i][0], f"{rows[i][2]:,}" if rows[i][2] else rc.missing("length not recorded")]
        for t in payload["tracks"]:
            cells.append(t["vals"][t["r"][i]])
        for b in blocks:
            if b["k"] == "amr_gene":
                continue
            if i in b["na"]:
                cells.append(rc.missing("not annotated", "not annotated"))
            else:
                names = [n for n, rws in b["f"] if i in rws]
                cells.append(", ".join(names) if names else "none")
        body.append(cells)
    heads = ["Plasmid", "Sample", "Length (bp)"] + [t["l"] for t in payload["tracks"]] + [b["l"] for b in blocks if b["k"] != "amr_gene"]
    return rc.panel(heads, body, empty="No plasmids.")


# ------------------------------------------------------------------------------------------------ section
def build_section(results_dir, data_dir, scores_path):
    data, reason = build_payload(results_dir, data_dir, scores_path)
    if data is None:
        return rc.section(SID, TITLE, LEAD, rc.not_run(f"Not available in this run: {reason}"), group="Figures")
    svg = static_svg(data)
    ordered = "clustered on the Jaccard distance of the feature profile (average linkage)" if data["clustered"] else \
        f"ordered by feature profile (more than {MAX_PROFILES} distinct profiles, so no dendrogram)"
    cap = (f"<figure class='rpt-figure fp-fig'>{svg}<figcaption>{len(data['rows'])} truth plasmids, {ordered}. "
           f"{'Showing AMR gene classes; the live figure can switch to genes. ' if any(b['k'] == 'amr_gene' for b in data['blocks']) else ''}"
           "Truth only: choose a tool in the live figure to overlay its outcome per plasmid.</figcaption></figure>")
    omitted = sum(b["omitted"] for b in data["blocks"])
    if omitted:
        cap += f"<p class='fp-note'>{omitted} less common features are not drawn (at most {MAX_FEATURES_PER_BLOCK} per block, the most prevalent first).</p>"
    fold = f"<details class='rpt-collapsible fp-table' data-closed><summary>Table: every plasmid with its features</summary>{table_html(data)}</details>"
    body = (ff.json_script("fp-data", data) + ff.asset("fig_presence_style.html") + ff.asset("fig_presence_core.html") + ff.asset("fig_presence_ui.html") +
            f"<div class='fp-root' id='fp-root'><div class='fp-static'>{cap}</div></div>{fold}")
    return rc.section(SID, TITLE, LEAD, body, group="Figures")


def inject(page, results_dir, data_dir, scores_path):
    return rc.inject_sections(rc.add_style(page), str(build_section(results_dir, data_dir, scores_path)), SECTIONS)
