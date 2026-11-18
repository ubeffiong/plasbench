#!/usr/bin/env python3
"""Contig-level bin agreement in the spirit of PlasEval (BMC Bioinformatics 2024).

Reimplemented from the published definitions (no PlasEval code used).

Subcommands
  eval    best-match precision/recall/F1 of predicted bins vs truth plasmid bins
          (count-based and bp-weighted; best match is per bin, not one-to-one)
  dissim  normalised split/join/extra/missing dissimilarity for unique contigs
  matrix  tool-vs-tool and tool-vs-truth dissimilarity over a results/data tree

Conventions
  * Truth bins: contigs labelled PLASMID, grouped by the `plasmids` column of the
    labels TSV (comma list), falling back to best_plasmid, then to the contig id.
  * Contigs labelled AMBIGUOUS or CHIMERIC are excluded from both sides and counted.
  * A predicted record whose id is absent from the labels file means the tool
    emitted reassembled sequences: status not_applicable_not_assembly_contigs.
  * Dissimilarity: contig cost len^alpha. Extra = predicted contigs not truth
    plasmid contigs; missing = the converse. Over contigs on both sides, the
    intermediate bins are the non-empty cells P&T. A predicted bin cut into k
    cells costs sum(L(cell)^alpha) - max(L(cell)^alpha) (split); a truth bin
    assembled from k cells costs the same way (join). L(cell) is the summed bp.
    Normaliser = sum over both sides of sum_c len(c)^alpha.
  * Repeats (default `--repeats aware`): a contig that sits in more than one bin, on either side, forms a repeat
    family. As in PlasEval, its copies are paired (a maximal matching: min(k1, k2) pairs, the rest are extra or
    missing) and the pairing that gives the lowest total dissimilarity is found by branch and bound, using the
    fact that adding contigs never lowers the dissimilarity. Every copy counts in the normaliser. The search is
    capped (`--max-calls`); a capped search returns the best pairing found and says so (dissim_repeat_search =
    capped). `--repeats drop` keeps the first copy of each contig only (the earlier behaviour).
"""
import argparse
import csv
import os
import itertools
import math
import sys
from pathlib import Path

EXCLUDED_LABELS = ("AMBIGUOUS", "CHIMERIC")
NOT_ASSEMBLY = "not_applicable_not_assembly_contigs"


def _fmt(x):
    return "" if x is None else "%.6f" % x


def read_labels(path):
    """contig -> {length:int, label:str, plasmids:[str]}."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cid = row["contig"]
            pl = [p.strip() for p in (row.get("plasmids") or "").split(",") if p.strip()]
            if not pl:
                bp = (row.get("best_plasmid") or "").strip()
                if bp and bp not in ("NA", "-", "."):
                    pl = [bp]
            out[cid] = {"length": int(float(row["length"])), "label": row["label"].strip().upper(),
                        "plasmids": pl}
    return out


def read_bins(path):
    """bin_id -> list of unique sequence ids (first-seen order)."""
    # A dict per bin is an insertion-ordered hash set: O(1) duplicate checks instead of
    # a linear scan of the bin's list for every row (quadratic for large bins).
    members = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            members.setdefault(row["bin_id"], {})[row["sequence_id"]] = None
    return {bin_id: list(seen) for bin_id, seen in members.items()}


def lengths_of(labels):
    return {c: v["length"] for c, v in labels.items()}


def truth_bins(labels, min_length=0):
    """plasmid -> set(contigs) for PLASMID-labelled contigs of at least min_length."""
    out = {}
    for c, v in labels.items():
        if v["label"] != "PLASMID" or v["length"] < min_length:
            continue
        for p in (v["plasmids"] or [c]):
            out.setdefault(p, set()).add(c)
    return out


def is_assembly(bins, labels):
    """Same rule as contig_classification.py score: a tool whose predicted ids share nothing with the assembly contigs
    emits reassembled sequences (not applicable); one with at least one matching id is scored on the matching ids, and
    records that are not assembly contigs (a graph binner's synthetic records, say) are ignored. An empty prediction is
    scored: it predicts no plasmid contigs."""
    members = [s for ms in bins.values() for s in ms]
    return not members or any(s in labels for s in members)


def _filter_pred(bins, labels, min_length):
    out = {}
    for b, members in bins.items():
        keep = {s for s in members if s in labels and labels[s]["label"] not in EXCLUDED_LABELS
                and labels[s]["length"] >= min_length}
        if keep:
            out[b] = keep
    return out


def _harm(p, r):
    return None if p is None or r is None else (0.0 if p + r == 0 else 2 * p * r / (p + r))


def _overlaps(pred, truth, w):
    """(pred bin, truth bin) -> weighted overlap, only non-zero cells."""
    member = {}
    for pb, cs in pred.items():
        for c in cs:
            member.setdefault(c, []).append(pb)
    o = {}
    for tb, cs in truth.items():
        for c in cs:
            for pb in member.get(c, ()):
                o[(pb, tb)] = o.get((pb, tb), 0) + w(c)
    return o


def _side_scores(pred, truth, w):
    o = _overlaps(pred, truth, w)
    bp, bt = {}, {}
    for (pb, tb), v in o.items():
        bp[pb] = max(bp.get(pb, 0), v)
        bt[tb] = max(bt.get(tb, 0), v)
    lp = sum(sum(w(c) for c in cs) for cs in pred.values())
    lt = sum(sum(w(c) for c in cs) for cs in truth.values())
    prec = sum(bp.values()) / lp if pred and lp else None
    rec = sum(bt.values()) / lt if truth and lt else None
    if truth and lt and not pred:
        prec, rec = None, 0.0
    return prec, rec


def eval_bestmatch(pred_bins, labels, min_length=0):
    """Return dict with status, count/bp precision/recall/f1 and contigs_excluded."""
    res = {"status": "ok", "excluded": sum(
        1 for v in labels.values() if v["label"] in EXCLUDED_LABELS and v["length"] >= min_length)}
    for k in ("precision_count", "recall_count", "f1_count", "precision_bp", "recall_bp", "f1_bp"):
        res[k] = None
    if not is_assembly(pred_bins, labels):
        res["status"] = NOT_ASSEMBLY
        return res
    truth = truth_bins(labels, min_length)
    if not truth:
        res["status"] = "no_truth_plasmid_contigs"
        return res
    pred = _filter_pred(pred_bins, labels, min_length)
    if not pred:
        res["status"] = "no_predicted_bins"
    for tag, w in (("count", lambda c: 1), ("bp", lambda c: labels[c]["length"])):
        p, r = _side_scores(pred, truth, w)
        res["precision_" + tag], res["recall_" + tag], res["f1_" + tag] = p, r, _harm(p, r)
        if p is None and r == 0.0:
            res["f1_" + tag] = 0.0
    return res


def per_bin_rows(pred_bins, labels, min_length=0):
    """Per-bin best match (by count and by bp) against the opposite side."""
    truth = truth_bins(labels, min_length)
    pred = _filter_pred(pred_bins, labels, min_length)
    ws = {"count": lambda c: 1, "bp": lambda c: labels[c]["length"]}
    ov = {k: _overlaps(pred, truth, w) for k, w in ws.items()}
    # Index every overlap by the bin on each side once (hash map), instead of scanning
    # all overlaps for every bin: O(overlaps) rather than O(bins x overlaps).
    by_bin = {}
    for k, cells in ov.items():
        for (pb, tb), v in cells.items():
            by_bin.setdefault(("pred", k, pb), []).append((v, tb))
            by_bin.setdefault(("truth", k, tb), []).append((v, pb))
    rows = []
    for side, bins in (("pred", pred), ("truth", truth)):
        for b in sorted(bins):
            row = {"side": side, "bin_id": b, "size_count": len(bins[b]),
                   "size_bp": sum(labels[c]["length"] for c in bins[b])}
            for k in ("count", "bp"):
                cand = by_bin.get((side, k, b))
                size = row["size_" + k]
                if cand:
                    # Best = largest overlap, ties to the smallest id: a linear min() gives
                    # the same element as sorting and taking the first, without the sort.
                    v, other = min(cand, key=lambda t: (-t[0], t[1]))
                    row["best_match_" + k], row["overlap_" + k] = other, v
                    row["frac_" + k] = v / size if size else None
                else:
                    row["best_match_" + k], row["overlap_" + k], row["frac_" + k] = "", 0, 0.0
            rows.append(row)
    return rows


def _unique(bins, repeats):
    seen, out = set(), {}
    for b in sorted(bins):
        keep = set()
        for c in bins[b]:
            if c in seen:
                repeats[0] += 1
            else:
                seen.add(c)
                keep.add(c)
        if keep:
            out[b] = keep
    return out


def _bin_costs(matched, alpha):
    """(split cost, join cost) of matched contig copies [(predicted bin, truth bin, length)]: each bin is cut into
    the cells it shares with the other side, and pays the sum of the cells' length^alpha minus the largest."""
    cells = {}
    for pb, tb, n in matched:
        cells[(pb, tb)] = cells.get((pb, tb), 0) + n
    split, join = {}, {}
    for (pb, tb), v in cells.items():
        w = v ** alpha
        split.setdefault(pb, []).append(w)
        join.setdefault(tb, []).append(w)
    return (sum(sum(v) - max(v) for v in split.values()), sum(sum(v) - max(v) for v in join.values()))


def _matchings(ka, kb):
    """Every maximal matching of ka predicted copies with kb truth copies, as (predicted index, truth index) pairs."""
    if ka >= kb:
        for perm in itertools.permutations(range(ka), kb):
            yield [(perm[i], i) for i in range(kb)]
    else:
        for perm in itertools.permutations(range(kb), ka):
            yield [(i, perm[i]) for i in range(ka)]


MAX_FAMILIES = 400   # deeper than this the search is not attempted (recursion depth); the first pairing is used


class _Cells:
    """Split and join cost of a growing set of matched contig copies, kept incrementally.

    Each (predicted bin, truth bin) cell holds the bp of the copies matched into it. A predicted bin pays the sum of its cells'
    length^alpha minus the largest (its split cost); a truth bin pays the same over its cells (its join cost). Adding or removing
    copies changes only the bins they touch, so a search node costs a few bins, not the whole instance."""

    def __init__(self, alpha):
        self.alpha = alpha
        self.by_p, self.by_t = {}, {}
        self.split = self.join = 0.0

    def _cost(self, cells):
        if not cells:
            return 0.0
        w = [v ** self.alpha for v in cells.values()]
        return sum(w) - max(w)

    def apply(self, items, sign):
        before_p = {pb: self._cost(self.by_p.get(pb)) for pb, _, _ in items}
        before_t = {tb: self._cost(self.by_t.get(tb)) for _, tb, _ in items}
        for pb, tb, n in items:
            v = self.by_p.get(pb, {}).get(tb, 0) + sign * n
            if v:
                self.by_p.setdefault(pb, {})[tb] = v
                self.by_t.setdefault(tb, {})[pb] = v
            else:
                self.by_p[pb].pop(tb, None)
                self.by_t[tb].pop(pb, None)
        for pb, old in before_p.items():
            self.split += self._cost(self.by_p.get(pb)) - old
        for tb, old in before_t.items():
            self.join += self._cost(self.by_t.get(tb)) - old

    def total(self):
        return self.split + self.join


def dissimilarity_aware(pred_bins, truth, lengths, alpha=0.5, max_calls=200000):
    """Repeat-aware dissimilarity (PlasEval's definition). Returns the same dict as dissimilarity() plus
    repeat_families, search ('none', 'exact' or 'capped') and calls.

    The pairing of every repeat family that gives the lowest dissimilarity is found by branch and bound: adding contigs never
    lowers the dissimilarity, so a partial pairing already costing as much as the best complete one is dropped. At each level the
    cheapest pairing is tried first, so a good complete answer is found early and most of the tree is cut."""
    copies = ({}, {})
    for side, bins in enumerate((pred_bins, truth)):
        for b in sorted(bins):
            for c in sorted(set(bins[b])):
                copies[side].setdefault(c, []).append(b)
    extra = missing = norm = 0.0
    fixed, families = [], []
    for c in sorted(set(copies[0]) | set(copies[1])):
        pa, ta = copies[0].get(c, []), copies[1].get(c, [])
        w = lengths[c] ** alpha
        extra += max(len(pa) - len(ta), 0) * w
        missing += max(len(ta) - len(pa), 0) * w
        norm += (len(pa) + len(ta)) * w
        if pa and ta:
            if len(pa) == 1 and len(ta) == 1:
                fixed.append((pa[0], ta[0], lengths[c]))
            else:
                families.append((math.perm(max(len(pa), len(ta)), min(len(pa), len(ta))), c, pa, ta, lengths[c]))
    families.sort(key=lambda f: (f[0], f[1]))
    state = _Cells(alpha)
    state.apply(fixed, +1)
    # The first pairing of every family is the starting upper bound; the search can only improve on it.
    best_items = list(fixed)
    for _, _, pa, ta, n in families:
        best_items.extend((pa[i], ta[j], n) for i, j in next(_matchings(len(pa), len(ta))))
    best = sum(_bin_costs(best_items, alpha))
    calls, capped = 0, len(families) > MAX_FAMILIES
    chosen = []

    def search(level):
        nonlocal best, best_items, calls, capped
        _, _, pa, ta, n = families[level]
        options = []
        for m in _matchings(len(pa), len(ta)):
            if capped:
                return
            calls += 1
            if calls > max_calls:
                capped = True
                return
            added = [(pa[i], ta[j], n) for i, j in m]
            state.apply(added, +1)
            options.append((state.total(), added))     # a partial pairing is a lower bound for every completion
            state.apply(added, -1)
        options.sort(key=lambda o: o[0])
        for total, added in options:
            if capped or total >= best - 1e-9:
                continue
            state.apply(added, +1)
            chosen.append(added)
            if level + 1 == len(families):
                best = state.total()
                best_items = list(fixed) + [item for group in chosen for item in group]
            else:
                search(level + 1)
            chosen.pop()
            state.apply(added, -1)

    if families and not capped:
        search(0)
    split, join = _bin_costs(best_items, alpha)
    total = split + join + extra + missing
    return {"split": split, "join": join, "extra": extra, "missing": missing, "norm": norm,
            "dissim": 0.0 if norm == 0 else total / norm, "repeats_dropped": 0, "repeat_families": len(families),
            "search": "none" if not families else ("capped" if capped else "exact"), "calls": calls}


def dissimilarity(pred_bins, truth, lengths, alpha=0.5, repeats="aware", max_calls=200000):
    """Dissimilarity between two bin sets. Returns a dict. repeats='aware' pairs repeated contigs as PlasEval does;
    'drop' scores the first copy of each contig only."""
    if repeats == "aware":
        return dissimilarity_aware(pred_bins, truth, lengths, alpha, max_calls)
    rep = [0]
    P, T = _unique(pred_bins, rep), _unique(truth, rep)
    cp = {c: b for b, cs in P.items() for c in cs}
    ct = {c: b for b, cs in T.items() for c in cs}
    cost = lambda c: lengths[c] ** alpha
    extra = sum(cost(c) for c in cp if c not in ct)
    missing = sum(cost(c) for c in ct if c not in cp)
    norm = sum(cost(c) for c in cp) + sum(cost(c) for c in ct)
    cells = {}
    for c in cp:
        if c in ct:
            cells[(cp[c], ct[c])] = cells.get((cp[c], ct[c]), 0) + lengths[c]
    split, join = {}, {}
    for (pb, tb), v in cells.items():
        split.setdefault(pb, []).append(v ** alpha)
        join.setdefault(tb, []).append(v ** alpha)
    sc = sum(sum(v) - max(v) for v in split.values())
    jc = sum(sum(v) - max(v) for v in join.values())
    total = sc + jc + extra + missing
    return {"split": sc, "join": jc, "extra": extra, "missing": missing, "norm": norm,
            "dissim": 0.0 if norm == 0 else total / norm, "repeats_dropped": rep[0], "repeat_families": 0,
            "search": "dropped" if rep[0] else "none", "calls": 0}


def pairwise_dissimilarity(bins_a, bins_b, lengths, alpha=0.5, repeats="aware", max_calls=200000):
    """Dissimilarity between two tools' bin sets (restricted to contigs with a length)."""
    ra = {b: [c for c in cs if c in lengths] for b, cs in bins_a.items()}
    rb = {b: [c for c in cs if c in lengths] for b, cs in bins_b.items()}
    return dissimilarity(ra, rb, lengths, alpha, repeats, max_calls)["dissim"]


def dissim_row(pred_bins, labels, alpha=0.5, min_length=0, repeats="aware", max_calls=200000):
    row = {"status": "ok", "dissim": None, "split": None, "join": None, "extra": None,
           "missing": None, "norm": None, "repeats": 0, "families": 0, "search": "", "alpha0": None, "alpha1": None}
    if not is_assembly(pred_bins, labels):
        row["status"] = NOT_ASSEMBLY
        return row
    pred = _filter_pred(pred_bins, labels, min_length)
    truth = truth_bins(labels, min_length)
    lengths = lengths_of(labels)
    d = dissimilarity(pred, truth, lengths, alpha, repeats, max_calls)
    row.update(dissim=d["dissim"], split=d["split"], join=d["join"], extra=d["extra"],
               missing=d["missing"], norm=d["norm"], repeats=d["repeats_dropped"], families=d["repeat_families"],
               search=d["search"])
    # How much the verdict depends on the length exponent: no length weight, and full length weight.
    row["alpha0"] = dissimilarity(pred, truth, lengths, 0.0, repeats, max_calls)["dissim"]
    row["alpha1"] = dissimilarity(pred, truth, lengths, 1.0, repeats, max_calls)["dissim"]
    return row


def export_plaseval(prefix, pred_bins, labels, min_length=0):
    lengths = lengths_of(labels)
    pred = _filter_pred(pred_bins, labels, min_length)
    for name, bins in (("truth_bins", truth_bins(labels, min_length)), ("pred_bins", pred)):
        with open("%s.%s.tsv" % (prefix, name), "w", newline="", encoding="utf-8") as fh:
            fh.write("plasmid\tcontig\tcontig_len\n")
            for b in sorted(bins):
                for c in sorted(bins[b]):
                    fh.write("%s\t%s\t%d\n" % (b, c, lengths[c]))


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")


def cmd_eval(a):
    labels, bins = read_labels(a.labels), read_bins(a.bins)
    r = eval_bestmatch(bins, labels, a.min_length)
    hdr = ["sample", "tool", "bestmatch_status", "bestmatch_precision_count", "bestmatch_recall_count",
           "bestmatch_f1_count", "bestmatch_precision_bp", "bestmatch_recall_bp", "bestmatch_f1_bp",
           "bestmatch_contigs_excluded"]
    _write(a.out, hdr, [[a.sample, a.tool, r["status"]] + [_fmt(r[k]) for k in (
        "precision_count", "recall_count", "f1_count", "precision_bp", "recall_bp", "f1_bp")]
        + [r["excluded"]]])
    if a.per_bin_out:
        h = ["sample", "tool", "side", "bin_id", "size_count", "size_bp", "best_match_count",
             "overlap_count", "frac_count", "best_match_bp", "overlap_bp", "frac_bp"]
        rows = []
        if r["status"] != NOT_ASSEMBLY:
            for x in per_bin_rows(bins, labels, a.min_length):
                rows.append([a.sample, a.tool, x["side"], x["bin_id"], x["size_count"], x["size_bp"],
                             x["best_match_count"], x["overlap_count"], _fmt(x["frac_count"]),
                             x["best_match_bp"], x["overlap_bp"], _fmt(x["frac_bp"])])
        _write(a.per_bin_out, h, rows)
    return 0


def cmd_dissim(a):
    labels, bins = read_labels(a.labels), read_bins(a.bins)
    r = dissim_row(bins, labels, a.alpha, a.min_length, a.repeats, a.max_calls)
    hdr = ["sample", "tool", "dissim_status", "bin_dissimilarity", "dissim_split_cost", "dissim_join_cost",
           "dissim_extra_cost", "dissim_missing_cost", "dissim_norm", "dissim_repeats_dropped",
           "dissim_repeat_families", "dissim_repeat_search", "bin_dissimilarity_alpha0", "bin_dissimilarity_alpha1"]
    _write(a.out, hdr, [[a.sample, a.tool, r["status"]] + [_fmt(r[k]) for k in (
        "dissim", "split", "join", "extra", "missing", "norm")] + [r["repeats"], r["families"], r["search"]]
        + [_fmt(r["alpha0"]), _fmt(r["alpha1"])]])
    if a.export_prefix and r["status"] != NOT_ASSEMBLY:
        export_plaseval(a.export_prefix, bins, labels, a.min_length)
    return 0


def cmd_matrix(a):
    results, data = Path(a.results_dir), Path(a.data_dir)
    acc = {}
    for sdir in sorted(p for p in results.iterdir() if p.is_dir()):
        lp = data / sdir.name / "contig_labels.tsv"
        if not lp.is_file():
            continue
        labels = read_labels(lp)
        lengths = lengths_of(labels)
        tools = {}
        for f in sorted(sdir.glob("pred_*.bins.tsv")):
            b = read_bins(f)
            if is_assembly(b, labels):
                tools[f.name[len("pred_"):-len(".bins.tsv")]] = b
        truth = truth_bins(labels)
        for t, b in tools.items():
            d = dissimilarity(_filter_pred(b, labels, 0), truth, lengths, a.alpha, a.repeats, a.max_calls)["dissim"]
            acc.setdefault((t, "truth"), []).append(d)
        names = sorted(tools)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                acc.setdefault((x, y), []).append(pairwise_dissimilarity(tools[x], tools[y], lengths, a.alpha,
                                                                         a.repeats, a.max_calls))
    rows = [[x, y, len(v), _fmt(sum(v) / len(v) if v else None)] for (x, y), v in sorted(acc.items())]
    _write(a.out, ["tool_a", "tool_b", "n_samples", "mean_dissimilarity"], rows)
    return 0


def cmd_merge(a):
    """Add every <sample>/<tool>.bestmatch.tsv and <tool>.dissim.tsv row to scores.tsv (matched on sample and tool).
    Runs with no shards too: the columns are still added, blank, so a missing layer reads as not evaluated."""
    import glob
    import os
    shards = {}
    for suffix in (".bestmatch.tsv", ".dissim.tsv"):
        for path in glob.glob(os.path.join(a.results_dir, "*", "*" + suffix)):
            tool = os.path.basename(path)[:-len(suffix)]
            sample = os.path.basename(os.path.dirname(path))
            with open(path, newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle, delimiter=chr(9)), None)
            if row:
                shards.setdefault((sample, tool), {}).update(row)
    with open(a.scores, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=chr(9)))
    fields = list(rows[0]) if rows else []
    added = ["bestmatch_status", "bestmatch_precision_count", "bestmatch_recall_count", "bestmatch_f1_count",
             "bestmatch_precision_bp", "bestmatch_recall_bp", "bestmatch_f1_bp", "bestmatch_contigs_excluded",
             "dissim_status", "bin_dissimilarity", "dissim_split_cost", "dissim_join_cost", "dissim_extra_cost",
             "dissim_missing_cost", "dissim_norm", "dissim_repeats_dropped", "dissim_repeat_families",
             "dissim_repeat_search", "bin_dissimilarity_alpha0", "bin_dissimilarity_alpha1"]
    fields += [c for c in added if c not in fields]
    for row in rows:
        shard = shards.get((row["sample"], row["tool"]), {})
        for c in added:
            row[c] = shard.get(c, "")
    # Written beside the table and renamed over it, so a kill mid-write leaves the previous file intact (AU-049).
    tmp_path = str(a.scores) + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=chr(9), lineterminator=chr(10))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, a.scores)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("eval", cmd_eval), ("dissim", cmd_dissim)):
        p = sub.add_parser(name)
        for k in ("labels", "bins", "sample", "tool", "out"):
            p.add_argument("--" + k, required=True)
        p.add_argument("--min-length", type=int, default=0)
        if name == "eval":
            p.add_argument("--per-bin-out")
        else:
            p.add_argument("--alpha", type=float, default=0.5)
            p.add_argument("--repeats", choices=("aware", "drop"), default="aware")
            p.add_argument("--max-calls", type=int, default=200000)
            p.add_argument("--export-prefix")
        p.set_defaults(fn=fn)
    p = sub.add_parser("matrix")
    for k in ("results-dir", "data-dir", "out"):
        p.add_argument("--" + k, required=True)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--repeats", choices=("aware", "drop"), default="aware")
    p.add_argument("--max-calls", type=int, default=200000)
    p.set_defaults(fn=cmd_matrix)
    p = sub.add_parser("merge")
    p.add_argument("--scores", required=True)
    p.add_argument("--results-dir", required=True)
    p.set_defaults(fn=cmd_merge)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
