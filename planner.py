"""Automated planning (STRIPS, forward state-space search). Terpisah dari game.
Operator = (pre, add, del, cost). Algoritma: UCS (buta), A* goal-count, A* h_max (relaksasi delete-list)."""
import heapq
import itertools
import time
from collections import namedtuple

INF = float("inf")
Op = namedtuple("Op", "name args pre add dele cost")

ALGO_LABELS = {"ucs": "UCS (tanpa heuristik)", "astar_goalcount": "A* goal-count", "astar_hmax": "A* h_max"}


def op_label(op):
    return f"{op.name}({','.join(str(a) for a in op.args)})"


def h_zero(state, goal, ops):
    return 0


def h_goalcount(state, goal, ops):
    """Jumlah atom tujuan yang belum terpenuhi (tidak selalu admissible)."""
    return len(goal - state)


def h_max(state, goal, ops):
    """h_max: biaya terkecil mencapai tiap atom pada problem relaksasi (tanpa delete); admissible."""
    cost = {a: 0 for a in state}
    changed = True
    while changed:
        changed = False
        for op in ops:
            if all(p in cost for p in op.pre):
                c = max((cost[p] for p in op.pre), default=0) + op.cost
                for a in op.add:
                    if c < cost.get(a, INF):
                        cost[a], changed = c, True
    return max((cost.get(g, INF) for g in goal), default=0)


HEURISTICS = {"ucs": h_zero, "astar_goalcount": h_goalcount, "astar_hmax": h_max}


def plan(init, goal, ops, algo="astar_hmax", max_expand=4000):
    t0 = time.perf_counter()
    h = HEURISTICS[algo]
    init, goal = frozenset(init), frozenset(goal)
    cnt = itertools.count()
    heap = [(h(init, goal, ops), next(cnt), 0, init)]
    best, parent = {init: 0}, {}
    expanded = generated = 0
    res = {"found": False, "plan": [], "cost": 0, "algo": algo}
    while heap and expanded < max_expand:
        _, _, g, s = heapq.heappop(heap)
        if g > best.get(s, INF):
            continue
        expanded += 1
        if goal <= s:
            steps = []
            while s in parent:
                s, op = parent[s]
                steps.append(op)
            res.update(found=True, plan=steps[::-1], cost=g)
            break
        for op in ops:
            if op.pre <= s:
                s2 = (s - op.dele) | op.add
                g2 = g + op.cost
                if g2 < best.get(s2, INF):
                    best[s2], parent[s2] = g2, (s, op)
                    generated += 1
                    h2 = h(s2, goal, ops)
                    if h2 < INF:
                        heapq.heappush(heap, (g2 + h2, next(cnt), g2, s2))
    res.update(expanded=expanded, generated=generated, ms=(time.perf_counter() - t0) * 1000)
    return res
