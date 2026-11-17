#!/usr/bin/env python3
"""What drives per-plasmid reconstruction accuracy? A multivariable, study-clustered regression per tool.

`stratify_recovery.py` breaks recovery down one factor at a time, so plasmid size, repeat content, replicon family and species, which are
correlated, are confounded. This fits ONE model per tool and analysis track:

    completeness (share of a truth plasmid's bases recovered, 0 to 1)  ~  size + repeats + replicon family + resistance genes
                                                                          + species + read depth + recent/older arm

by ordinary least squares on the plasmids a tool was scored on. Numeric drivers are standardised (the effect is per one standard deviation),
binary and categorical drivers are differences against a stated reference. Plasmids of one study are not independent observations, so the intervals
are **cluster-robust** (CR1 standard errors, clusters are cluster_key, else BioProject, else sample) with a t distribution on studies - 1 degrees of
freedom, the usual small-sample choice; a percentile bootstrap that resamples whole studies is run beside it only for the sign check below. Each term
reports its 95 percent interval, its `sign_stability` (the share of bootstrap fits with the same sign) and a status: `supported` (the estimate is outside the interval widened for
the number of terms in the model, level 1 - 0.05/terms, and the sign is stable in at least 95 percent of fits) or `unclear`. `delta_r2_without` is how much of the explained variance the driver (all its terms) accounts for.

Inputs
  results/<sample>/<tool>.per_plasmid.tsv     completeness and length per truth plasmid (score_plasmids.py)
  results/benchmark.repeat_content.tsv        internal_repeat_fraction, chromosome_shared_fraction (optional)
  data/<sample>/truth_features.tsv            replicon labels (annotate_reference.py), truth_amr.tsv for resistance genes (optional)
  the sample sheet                            organism, cluster_key / bioproject, read_depth_x, selection_arm (optional)
Output
  <prefix>.tsv   one row per tool, track and term
  <prefix>.json  per tool: plasmids, studies, R2, the drivers that were left out and why, the size effect, warnings

Rules
  * Associations, not causes: the drivers are correlated (a large plasmid is more often repeat-rich), so read a term as "holding the others fixed".
    A pair of numeric drivers correlated above 0.8 is flagged.
  * A tool with fewer than --min-plasmids scored plasmids or --min-clusters studies, or too few plasmids for the number of terms, is reported as
    not estimable with the reason, never with a coefficient. A driver known for under 70 percent of a tool's plasmids, or a category with
    fewer than 5 plasmids, is left out and listed.
  * Descriptive: never alters a score, a ranking or a recommendation. Deterministic (fixed seed). Standard library only.
"""
import argparse
import csv
import glob
import json
import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stratify_recovery as sr  # noqa: E402

TAB, NL = chr(9), chr(10)
OUT_FIELDS = ["analysis_track", "tool", "driver", "term", "kind", "reference", "estimate", "ci_low", "ci_high", "sign_stability", "status",
              "delta_r2_without", "n_plasmids", "n_clusters", "r2"]
MIN_COVERAGE = 0.70
MIN_LEVEL = 5
TOP_SPECIES = 4
MIN_SPECIES_PLASMIDS = 20
SUPPORTED_STABILITY = 0.95


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


def fnum(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def solve(matrix, vector):
    """Solve matrix x = vector by Gaussian elimination with partial pivoting; None when singular."""
    n = len(vector)
    a = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                factor = a[r][col] / a[col][col]
                if factor:
                    for c in range(col, n + 1):
                        a[r][c] -= factor * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


def new_stats(p):
    return [[[0.0] * p for _ in range(p)], [0.0] * p, 0.0, 0]  # XtX, Xty, yty, n


def add_row(stats, x, y):
    xtx, xty = stats[0], stats[1]
    p = len(x)
    for i in range(p):
        xi = x[i]
        if xi:
            row = xtx[i]
            for j in range(p):
                row[j] += xi * x[j]
            xty[i] += xi * y
    stats[2] += y * y
    stats[3] += 1


def total_stats(parts, p):
    total = new_stats(p)
    for s in parts:
        for i in range(p):
            ti, si = total[0][i], s[0][i]
            for j in range(p):
                ti[j] += si[j]
            total[1][i] += s[1][i]
        total[2] += s[2]
        total[3] += s[3]
    return total


def fit(stats, ridge=1e-8):
    """Coefficients from sufficient statistics (a tiny ridge keeps a near-singular design solvable)."""
    p = len(stats[1])
    xtx = [row[:] for row in stats[0]]
    for i in range(1, p):  # not the intercept
        xtx[i][i] += ridge * max(1, stats[3])
    return solve(xtx, stats[1])


def r_squared(stats, beta, mean_y):
    """1 - SSE/SST from sufficient statistics."""
    p = len(beta)
    n = stats[3]
    sse = stats[2] - 2 * sum(beta[i] * stats[1][i] for i in range(p)) + sum(beta[i] * stats[0][i][j] * beta[j] for i in range(p) for j in range(p))
    sst = stats[2] - n * mean_y * mean_y
    return None if sst <= 1e-12 else max(0.0, 1 - sse / sst)


def _betacf(a, b, x):
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_cdf(t, df):
    """Student t distribution function."""
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return 1 - tail if t > 0 else tail


def t_ppf(q, df):
    """Quantile of the Student t distribution by bisection (q in (0.5, 1))."""
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < q and hi < 1e6:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def robust_se(per_cluster, cluster_ids, beta, full, p):
    """Cluster-robust (CR1) standard errors of the coefficients from per-cluster sufficient statistics; None when the design cannot be inverted."""
    xtx = [row[:] for row in full[0]]
    for i in range(1, p):
        xtx[i][i] += 1e-8 * max(1, full[3])
    bread = []
    for j in range(p):
        e = [1.0 if i == j else 0.0 for i in range(p)]
        col = solve(xtx, e)
        if col is None:
            return None
        bread.append(col)  # bread[j] is column j of the inverse (symmetric)
    meat = [[0.0] * p for _ in range(p)]
    for c in cluster_ids:
        st = per_cluster[c]
        score = [st[1][i] - sum(st[0][i][j] * beta[j] for j in range(p)) for i in range(p)]
        for i in range(p):
            for j in range(p):
                meat[i][j] += score[i] * score[j]
    k, n = len(cluster_ids), full[3]
    scale = (k / (k - 1.0)) * ((n - 1.0) / max(1.0, n - p))
    se = []
    for i in range(p):
        v = sum(bread[i][a] * meat[a][b] * bread[b][i] for a in range(p) for b in range(p)) * scale
        se.append(math.sqrt(max(v, 0.0)))
    return se


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def load_samples(path):
    out = {}
    for row in read_tsv(path) or []:
        if row.get("sample_id"):
            out[row["sample_id"]] = row
    return out


def replicon_family(labels):
    """Inc / Col / other / untyped from a plasmid's replicon labels."""
    if not labels:
        return "untyped"
    lowered = [str(x).lower() for x in labels]
    if any(x.startswith("inc") or x.startswith("rep") for x in lowered):
        return "inc"
    if any(x.startswith("col") for x in lowered):
        return "col"
    return "other"


def species_of(organism):
    parts = (organism or "").split()
    return " ".join(parts[:2]) if parts else ""


def collect(results_dir, data_dir, samples, repeat_rows):
    """One record per (track, tool, scored truth plasmid) with every driver value that could be determined."""
    repeats = {}
    for row in repeat_rows or []:
        if row.get("molecule_type") == "PLASMID":
            repeats[(row["sample"], row["sequence_id"])] = (fnum(row.get("internal_repeat_fraction")), fnum(row.get("chromosome_shared_fraction")))
    per_sample_count = defaultdict(set)
    records = []
    label_cache, amr_cache = {}, {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*", "*.per_plasmid.tsv"))):
        tool = os.path.basename(path)[:-len(".per_plasmid.tsv")]
        sample = os.path.basename(os.path.dirname(path))
        sample_dir = os.path.join(data_dir, sample)
        if sample not in label_cache:
            label_cache[sample] = sr.read_labels(os.path.join(sample_dir, "truth_features.tsv"))
            amr_cache[sample] = sr.read_curated_amr(sample_dir)
        meta = samples.get(sample, {})
        rows = read_tsv(path) or []
        for row in rows:
            completeness, length = fnum(row.get("completeness")), fnum(row.get("length"))
            if completeness is None or not length or length <= 0:
                continue
            seq = row["sequence_id"]
            per_sample_count[(tool, sample)].add(seq)
            labels = label_cache[sample]
            amr = amr_cache[sample]
            amr_value = None
            if amr is not None:
                amr_value = 1.0 if seq in amr else 0.0
            elif labels is not None:
                amr_value = 1.0 if "arg_carrying" in (labels.get(seq, {}).get("amr", set())) else None  # absence not measured without a curated table
            rep, shared = repeats.get((sample, seq), (None, None))
            depth = fnum(meta.get("read_depth_x"))
            records.append({
                "track": row.get("analysis_track") or "short_read", "tool": tool, "sample": sample, "seq": seq, "y": min(1.0, max(0.0, completeness)),
                "log_size": math.log10(length), "repeat": rep, "shared": shared,
                "replicon": None if labels is None else replicon_family(labels.get(seq, {}).get("replicon", set())),
                "amr": amr_value, "species": species_of(meta.get("organism")) or None,
                "log_depth": math.log10(depth) if depth and depth > 0 else None,
                "arm": meta.get("selection_arm") or None,
                "cluster": meta.get("cluster_key") or meta.get("bioproject") or sample})
    for rec in records:
        rec["n_in_isolate"] = float(len(per_sample_count[(rec["tool"], rec["sample"])]))
    return records


def build_design(recs, notes):
    """Choose the drivers a tool's plasmids support and return (term specs, rows of x), recording what is left out and why."""
    n = len(recs)
    terms = []  # (driver, term, kind, reference, getter)

    def coverage(getter):
        return sum(1 for r in recs if getter(r) is not None) / n

    numeric = [("size", "log10 plasmid length", lambda r: r["log_size"]), ("repeats", "internal repeat fraction", lambda r: r["repeat"]),
               ("chromosome_shared", "share shared with the chromosome", lambda r: r["shared"]), ("read_depth", "log10 read depth", lambda r: r["log_depth"]),
               ("plasmids_per_isolate", "plasmids in the isolate", lambda r: r["n_in_isolate"])]
    for driver, label, getter in numeric:
        cov = coverage(getter)
        values = [getter(r) for r in recs if getter(r) is not None]
        if cov < MIN_COVERAGE:
            notes["left_out"].append({"driver": driver, "reason": f"known for only {cov:.0%} of plasmids" if cov else "not available"})
            continue
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1))
        if sd < 1e-9:
            notes["left_out"].append({"driver": driver, "reason": "no variation"})
            continue
        terms.append((driver, label, "numeric (per SD)", "", (lambda g, m, s: (lambda r: None if g(r) is None else (g(r) - m) / s))(getter, mean, sd), mean))

    def categorical(driver, getter, levels, reference, label_fmt):
        cov = coverage(getter)
        if cov < MIN_COVERAGE:
            notes["left_out"].append({"driver": driver, "reason": f"known for only {cov:.0%} of plasmids" if cov else "not available"})
            return
        counts = defaultdict(int)
        for r in recs:
            if getter(r) is not None:
                counts[getter(r)] += 1
        every = list(levels) + ([reference] if reference not in levels else [])
        kept = [lv for lv in every if counts.get(lv, 0) >= MIN_LEVEL]
        dropped = [lv for lv in every if lv not in kept]
        if dropped:
            notes["left_out"].append({"driver": driver, "reason": "categories with fewer than 5 plasmids: " + ", ".join(dropped)})
        if len(kept) < 2:
            notes["left_out"].append({"driver": driver, "reason": "fewer than two categories with 5 or more plasmids"})
            return
        ref = reference if reference in kept else max(kept, key=lambda lv: counts[lv])
        if ref != reference:
            notes["warnings"].append(f"{driver}: the preferred reference '{reference}' has too few plasmids, so '{ref}' is the reference")
        for lv in kept:
            if lv != ref:
                terms.append((driver, label_fmt.format(lv), "difference", ref, (lambda g, l: (lambda r: None if g(r) is None else (1.0 if g(r) == l else 0.0)))(getter, lv), None))

    categorical("replicon_family", lambda r: r["replicon"], ["inc", "col", "other"], "untyped", "replicon {}")
    cov = coverage(lambda r: r["amr"])
    if cov >= MIN_COVERAGE and len({r["amr"] for r in recs if r["amr"] is not None}) == 2:
        categorical("resistance_gene", lambda r: None if r["amr"] is None else ("arg" if r["amr"] else "no_arg"), ["arg"], "no_arg", "carries a resistance gene")
    else:
        notes["left_out"].append({"driver": "resistance_gene", "reason": "no curated resistance truth for enough plasmids, or no variation"})
    sp_counts = defaultdict(int)
    for r in recs:
        if r["species"]:
            sp_counts[r["species"]] += 1
    top = [s for s, c in sorted(sp_counts.items(), key=lambda kv: -kv[1]) if c >= MIN_SPECIES_PLASMIDS][:TOP_SPECIES]
    if top:
        if len(sp_counts) <= TOP_SPECIES and len(top) == len(sp_counts):
            # few species and no "other": the most frequent is the reference
            ref = top[0]
            categorical("species", lambda r: r["species"], top[1:], ref, "species {}")
        else:
            categorical("species", lambda r: (r["species"] if r["species"] in top else ("other" if r["species"] else None)), top, "other", "species {}")
    else:
        notes["left_out"].append({"driver": "species", "reason": f"no species with {MIN_SPECIES_PLASMIDS} or more plasmids"})
    categorical("arm", lambda r: r["arm"], ["recent"], "older", "public {} (vs older)")
    return terms


def fit_tool(track, tool, recs, args):
    notes = {"left_out": [], "warnings": []}
    clusters = sorted({r["cluster"] for r in recs})
    result = {"analysis_track": track, "tool": tool, "n_plasmids": len(recs), "n_clusters": len(clusters), "status": "estimated", "reason": "", "left_out": notes["left_out"],
              "warnings": notes["warnings"], "terms": []}
    if len(recs) < args.min_plasmids:
        result.update(status="not_estimable", reason=f"only {len(recs)} scored plasmids (need {args.min_plasmids})")
        return result
    if len(clusters) < args.min_clusters:
        result.update(status="not_estimable", reason=f"only {len(clusters)} studies (need {args.min_clusters}) for a study-clustered interval")
        return result
    terms = build_design(recs, notes)
    # rows with every chosen driver known
    rows = []
    for r in recs:
        x = [1.0]
        ok = True
        for _, _, _, _, getter, _ in terms:
            v = getter(r)
            if v is None:
                ok = False
                break
            x.append(v)
        if ok:
            rows.append((r["cluster"], x, r["y"]))
    p = len(terms) + 1
    if len(rows) < max(args.min_plasmids, 10 * p):
        result.update(status="not_estimable", reason=f"{len(rows)} plasmids with every driver known is too few for {len(terms)} terms (need {10 * p})")
        return result
    if not terms:
        result.update(status="not_estimable", reason="no driver is available for these plasmids")
        return result
    n_clusters = len({c for c, _, _ in rows})
    if n_clusters < args.min_clusters:
        result.update(status="not_estimable", reason=f"only {n_clusters} studies among the plasmids with every driver known")
        return result
    result["n_plasmids"], result["n_clusters"] = len(rows), n_clusters
    # numeric correlation warnings
    numeric_idx = [i for i, t in enumerate(terms) if t[2].startswith("numeric")]
    for a in range(len(numeric_idx)):
        for b in range(a + 1, len(numeric_idx)):
            xs = [x[numeric_idx[a] + 1] for _, x, _ in rows]
            ys = [x[numeric_idx[b] + 1] for _, x, _ in rows]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sx = math.sqrt(sum((v - mx) ** 2 for v in xs))
            sy = math.sqrt(sum((v - my) ** 2 for v in ys))
            if sx and sy:
                corr = sum((u - mx) * (v - my) for u, v in zip(xs, ys)) / (sx * sy)
                if abs(corr) > 0.8:
                    notes["warnings"].append(f"{terms[numeric_idx[a]][0]} and {terms[numeric_idx[b]][0]} are correlated ({corr:.2f}); their separate effects are poorly identified")
    per_cluster = defaultdict(lambda: new_stats(p))
    for c, x, y in rows:
        add_row(per_cluster[c], x, y)
    cluster_ids = sorted(per_cluster)
    full = total_stats([per_cluster[c] for c in cluster_ids], p)
    beta = fit(full)
    if beta is None:
        result.update(status="not_estimable", reason="the design is singular (drivers are perfectly collinear)")
        return result
    mean_y = sum(y for _, _, y in rows) / len(rows)
    r2 = r_squared(full, beta, mean_y)
    result["r2"] = r2
    # drop-one-driver delta R2 (all terms of a driver together)
    drivers = []
    for t in terms:
        if t[0] not in drivers:
            drivers.append(t[0])
    delta = {}
    for d in drivers:
        keep = [0] + [i + 1 for i, t in enumerate(terms) if t[0] != d]
        sub = [[full[0][i][j] for j in keep] for i in keep]
        sub_stats = [sub, [full[1][i] for i in keep], full[2], full[3]]
        b = fit(sub_stats)
        r2_sub = None if b is None else r_squared(sub_stats, b, mean_y)
        delta[d] = None if r2 is None or r2_sub is None else r2 - r2_sub
    # cluster-robust (CR1) standard errors with a t distribution on (studies - 1) degrees of freedom, and a cluster bootstrap for sign stability
    se = robust_se(per_cluster, cluster_ids, beta, full, p)
    df = len(cluster_ids) - 1
    t95 = t_ppf(0.975, df)
    t_adj = t_ppf(1 - 0.025 / len(terms), df)  # level 1 - 0.05 / terms (Bonferroni) for the "supported" status
    rng = random.Random(args.seed)
    draws = [[] for _ in range(p)]
    for _ in range(args.bootstrap):
        picked = [rng.choice(cluster_ids) for _ in cluster_ids]
        bb = fit(total_stats([per_cluster[c] for c in picked], p))
        if bb is not None:
            for i in range(p):
                draws[i].append(bb[i])
    result["bootstrap_fits"] = len(draws[0])
    result["degrees_of_freedom"] = df
    for i, (driver, label, kind, reference, _g, _m) in enumerate(terms, start=1):
        entry = {"driver": driver, "term": label, "kind": kind, "reference": reference, "estimate": beta[i], "ci_low": None, "ci_high": None, "sign_stability": None,
                 "status": "unclear", "delta_r2_without": delta.get(driver)}
        if se is not None and se[i] > 0 and df >= 1:
            entry["ci_low"], entry["ci_high"] = beta[i] - t95 * se[i], beta[i] + t95 * se[i]
            same = sum(1 for v in draws[i] if (v > 0) == (beta[i] > 0)) / len(draws[i]) if draws[i] else None
            entry["sign_stability"] = same
            if abs(beta[i]) > t_adj * se[i] and (same is None or same >= SUPPORTED_STABILITY):
                entry["status"] = "supported"
        result["terms"].append(entry)
    result["intercept"] = beta[0]
    return result


def run(results_dir, data_dir, sample_sheet, repeat_path, out_prefix, args):
    samples = load_samples(sample_sheet)
    records = collect(results_dir, data_dir, samples, read_tsv(repeat_path))
    groups = defaultdict(list)
    for rec in records:
        groups[(rec["track"], rec["tool"])].append(rec)
    results = [fit_tool(track, tool, recs, args) for (track, tool), recs in sorted(groups.items())]
    rows = []
    for res in results:
        for t in res["terms"]:
            rows.append({"analysis_track": res["analysis_track"], "tool": res["tool"], **t, "n_plasmids": res["n_plasmids"], "n_clusters": res["n_clusters"], "r2": res.get("r2")})
    with open(out_prefix + ".tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        writer.writerow(OUT_FIELDS)
        for r in rows:
            writer.writerow(["" if r.get(c) is None else (f"{r[c]:.6g}" if isinstance(r[c], float) else r[c]) for c in OUT_FIELDS])
    summary = {"model": "completeness ~ size + repeats + replicon + resistance + species + read depth + arm (OLS; study-clustered bootstrap)", "bootstrap": args.bootstrap,
               "seed": args.seed, "min_plasmids": args.min_plasmids, "min_clusters": args.min_clusters, "tools": []}
    for res in results:
        size = next((t for t in res["terms"] if t["driver"] == "size"), None)
        summary["tools"].append({k: v for k, v in res.items() if k != "terms"} | {"size_effect": size})
    with open(out_prefix + ".json", "w", encoding="utf-8", newline="") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write(NL)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--repeat-content", help="default: <results-dir>/benchmark.repeat_content.tsv")
    ap.add_argument("--out-prefix", help="default: <results-dir>/benchmark.performance_drivers")
    ap.add_argument("--min-plasmids", type=int, default=30)
    ap.add_argument("--min-clusters", type=int, default=5)
    ap.add_argument("--bootstrap", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261117)
    args = ap.parse_args()
    prefix = args.out_prefix or os.path.join(args.results_dir, "benchmark.performance_drivers")
    results = run(args.results_dir, args.data_dir, args.sample_sheet, args.repeat_content or os.path.join(args.results_dir, "benchmark.repeat_content.tsv"), prefix, args)
    est = [r for r in results if r["status"] == "estimated"]
    print(f"performance drivers: {len(est)} of {len(results)} tool/track models estimated; wrote {prefix}.tsv and {prefix}.json")
    for r in results:
        if r["status"] != "estimated":
            print(f"  {r['tool']} ({r['analysis_track']}): not estimable: {r['reason']}")


if __name__ == "__main__":
    main()
