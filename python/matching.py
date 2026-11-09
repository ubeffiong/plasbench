#!/usr/bin/env python3
"""matching.py -- maximum-weight one-to-one matching (rectangular Hungarian).

The single solver behind score_bins.maximum_weight (isolate bins vs truth plasmids)
and metagenomics.hungarian_max (community bins vs truth plasmids).

Earlier versions padded the problem to a square of side max(rows, columns) and ran
an O(n^3) Hungarian on it. A tool that emits one bin per contig (the trivial
baselines do) has hundreds of bins against a handful of plasmids, which made
matching take seconds to minutes per sample (performance audit: 2.07 s at 200 x 20).

This solver:
* drops every row and column with no positive weight (they can never be matched);
* puts the smaller side on the rows and runs the rectangular Hungarian, which is
  O(r^2 c) time and O(r c) space for r <= c.

The optimum (the total matched weight) is the same as before. When several
matchings share that optimum, the one returned is deterministic for a given input
order but may pair a different bin than the square solver did; callers pass sorted
ids, so results are reproducible run to run.

Standard library only.
"""

INF = float("inf")


def _hungarian_min(cost):
    """Minimum-cost assignment of every row of an n x m matrix (n <= m) to a distinct column.

    Returns col_of_row (list of length n). e-maxx potentials formulation.
    """
    n, m = len(cost), len(cost[0])
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            row, ui0 = cost[i0 - 1], u[i0]
            for j in range(1, m + 1):
                if not used[j]:
                    current = row[j - 1] - ui0 - v[j]
                    if current < minv[j]:
                        minv[j], way[j] = current, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if not p[j0]:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if not j0:
                break
    col_of_row = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            col_of_row[p[j] - 1] = j - 1
    return col_of_row


def max_weight_matching(weights, rows, cols):
    """Maximum-weight one-to-one matching.

    weights: {(row_id, col_id): weight}; missing pairs weigh 0.
    rows, cols: the candidate ids, in the order that decides ties.
    Returns [(row_id, col_id, weight)] for matched pairs with weight > 0, in column
    order (the order the square solver produced them, which callers write out).
    """
    # Rows and columns with a positive edge, found in one pass over the edges (hash sets,
    # O(edges)) rather than by probing every row x column pair (O(rows x columns)).
    # Order is kept from `rows` / `cols`, so ties resolve exactly as before.
    row_ids, col_ids = set(rows), set(cols)
    positive = [(r, c) for (r, c), w in weights.items() if w > 0 and r in row_ids and c in col_ids]
    rows_hit, cols_hit = {r for r, _ in positive}, {c for _, c in positive}
    live_rows = [r for r in rows if r in rows_hit]
    live_cols = [c for c in cols if c in cols_hit]
    if not live_rows or not live_cols:
        return []
    transpose = len(live_rows) > len(live_cols)
    small, large = (live_cols, live_rows) if transpose else (live_rows, live_cols)

    def weight(a, b):
        return weights.get((b, a), 0) if transpose else weights.get((a, b), 0)

    high = max(weights[edge] for edge in positive)   # the largest weight is always a positive edge
    cost = [[high - weight(a, b) for b in large] for a in small]
    matched = []
    for a, j in zip(small, _hungarian_min(cost)):
        b = large[j]
        r, c = (b, a) if transpose else (a, b)
        w = weights.get((r, c), 0)
        if w > 0:
            matched.append((r, c, w))
    order = {c: i for i, c in enumerate(cols)}
    matched.sort(key=lambda item: order[item[1]])
    return matched
