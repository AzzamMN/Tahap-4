import heapq
import math
import time
import itertools
from pyscript import document, window
from pyodide.ffi import create_proxy, to_js
from kb_engine import KB, fmt as fmt_atom      # KB + mesin inferensi (terpisah: kb.txt, kb_engine.py)
from agents import WorldSim, NAMES, MODES        # dunia NPC: KB -> keputusan -> planning (agents.py, planner.py, decision.py)
from planner import ALGO_LABELS as PLAN_LABELS

# ==== CORE BEGIN ====
# =====================================================================
# DATA PETA & KONFIGURASI (Disatukan agar bebas masalah cache Pyodide)
# =====================================================================
MAP_DATA = [
    "....................",
    "..####..............",
    "..#..#....^^^^......",
    "..#..#....^^^^......",
    "..#..#..............",
    "....................",
    "~~~~~~~~~=~~~~~~~~~~",
    "....................",
    "..........####......",
    "..........#..#......",
    "..........####......",
    "....................",
    "..^^^^..............",
    "..^^^^..............",
    "....................",
    "~~~~~~~~~~~~~~=~~~~~",
    "....................",
    "....................",
    "....................",
]

TILE = 32  # ukuran tiap sel grid dalam pixel

TILE_COLORS = {
    ".": "#3f6b34",
    "^": "#8a6d3b",
    "#": "#2b2f33",
    "~": "#235d82",
    "=": "#a9744a",
}

ALGO_LABELS = {
    "ucs": "UCS (Uniform Cost Search)",
    "astar_manhattan": "A* — Manhattan Distance",
    "astar_euclidean": "A* — Euclidean Distance",
}


# =====================================================================
# 1. CLASS NODE
# =====================================================================
class Node:
    __slots__ = ("pos", "g", "h", "parent")

    def __init__(self, pos, g, h, parent=None):
        self.pos = pos      # (x, y)
        self.g = g          # cost akumulatif dari start ke node ini
        self.h = h          # estimasi heuristik ke goal
        self.parent = parent

    @property
    def f(self):
        return self.g + self.h


# =====================================================================
# 2. CLASS GRIDMAP
# =====================================================================
class GridMap:
    COST = {".": 1, "^": 3, "=": 1}
    BLOCKED = {"#", "~"}

    def __init__(self, rows):
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0])

    def in_bounds(self, pos):
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, pos):
        x, y = pos
        return self.rows[y][x]

    def walkable(self, pos):
        return self.in_bounds(pos) and self.tile(pos) not in self.BLOCKED

    def cost(self, pos):
        return self.COST.get(self.tile(pos), 1)

    def neighbors(self, pos):
        x, y = pos
        result = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            npos = (x + dx, y + dy)
            if self.walkable(npos):
                result.append((npos, self.cost(npos)))
        return result


# =====================================================================
# 3. FUNGSI HEURISTIK
# =====================================================================
def h_zero(a, b):
    return 0


def h_manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def h_euclidean(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


HEURISTICS = {
    "ucs": h_zero,
    "astar_manhattan": h_manhattan,
    "astar_euclidean": h_euclidean,
}


# =====================================================================
# 4. CLASS PATHFINDING
# =====================================================================
class Pathfinding:

    @staticmethod
    def search(grid, start, goal, heuristic_fn):
        t0 = time.perf_counter()
        counter = itertools.count()

        start_node = Node(start, g=0, h=heuristic_fn(start, goal))
        open_heap = [(start_node.f, next(counter), start_node)]
        open_lookup = {start: start_node}
        closed_set = set()
        expanded = 0

        while open_heap:
            f, _, current = heapq.heappop(open_heap)

            if current.pos in closed_set:
                continue

            closed_set.add(current.pos)
            expanded += 1

            if current.pos == goal:
                path = Pathfinding._reconstruct(current)
                exec_ms = (time.perf_counter() - t0) * 1000
                open_positions = {
                    node.pos for _, _, node in open_heap if node.pos not in closed_set
                }
                return {
                    "path": path,
                    "closed": closed_set,
                    "open": open_positions,
                    "cost": current.g,
                    "expanded": expanded,
                    "time_ms": exec_ms,
                }

            for npos, move_cost in grid.neighbors(current.pos):
                if npos in closed_set:
                    continue
                tentative_g = current.g + move_cost
                existing = open_lookup.get(npos)
                if existing is None or tentative_g < existing.g:
                    h = heuristic_fn(npos, goal)
                    node = Node(npos, tentative_g, h, current)
                    open_lookup[npos] = node
                    heapq.heappush(open_heap, (node.f, next(counter), node))

        exec_ms = (time.perf_counter() - t0) * 1000
        return {
            "path": None,
            "closed": closed_set,
            "open": set(),
            "cost": 0,
            "expanded": expanded,
            "time_ms": exec_ms,
        }

    @staticmethod
    def _reconstruct(node):
        path = []
        while node is not None:
            path.append(node.pos)
            node = node.parent
        path.reverse()
        return path


# ==== CORE END ====

# =====================================================================
# 5. BATTLE ENGINE (turn-based: Minimax / Alpha-Beta / Expectimax)
# ==== BATTLE ENGINE BEGIN ====
# =====================================================================
from collections import namedtuple

MAX_HP = 100
ATK_DMG = 20          # damage attack normal
HEAL = 30             # heal potion
START_POTIONS = 2
WIN_SCORE = 1000
INF = math.inf

# php/nhp = HP player/NPC, ppot/npot = sisa potion, psh/nsh = shield aktif,
# turn = "P" (giliran player) atau "N" (giliran NPC = pemain MAX)
State = namedtuple("State", "php nhp ppot npot psh nsh turn")
ACTIONS = ("attack", "defend", "potion")
ORDERS = {
    "default": ("attack", "defend", "potion"),
    "reverse": ("potion", "defend", "attack"),
    "defend_first": ("defend", "potion", "attack"),
    "heuristic": "heuristic",   # urut berdasarkan evaluasi statis anak (best-first)
}


def new_battle():
    return State(MAX_HP, MAX_HP, START_POTIONS, START_POTIONS, False, False, "P")


def mirror(s):
    """Tukar peran Player <-> NPC (dipakai agar Player bisa dimainkan oleh minimax)."""
    return State(s.nhp, s.php, s.npot, s.ppot, s.nsh, s.psh, "N" if s.turn == "P" else "P")


def legal_actions(s):
    hp, pot, sh = (s.php, s.ppot, s.psh) if s.turn == "P" else (s.nhp, s.npot, s.nsh)
    acts = ["attack"]
    if not sh:
        acts.append("defend")
    if pot > 0 and hp < MAX_HP:
        acts.append("potion")
    return acts


def apply_action(s, a):
    if s.turn == "P":
        if a == "attack":
            dmg = ATK_DMG // 2 if s.nsh else ATK_DMG
            return s._replace(nhp=max(0, s.nhp - dmg), nsh=False, turn="N")
        if a == "defend":
            return s._replace(psh=True, turn="N")
        return s._replace(php=min(MAX_HP, s.php + HEAL), ppot=s.ppot - 1, turn="N")
    if a == "attack":
        dmg = ATK_DMG // 2 if s.psh else ATK_DMG
        return s._replace(php=max(0, s.php - dmg), psh=False, turn="P")
    if a == "defend":
        return s._replace(nsh=True, turn="P")
    return s._replace(nhp=min(MAX_HP, s.nhp + HEAL), npot=s.npot - 1, turn="P")


def is_terminal(s):
    return s.php <= 0 or s.nhp <= 0


def utility(s, d):
    """Utility dari sudut pandang NPC. d = sisa kedalaman -> menang lebih cepat lebih baik."""
    return (WIN_SCORE + d) if s.php <= 0 else -(WIN_SCORE + d)


# ---- Fungsi evaluasi (sudut pandang NPC; makin besar makin baik bagi NPC) ----
def eval_zero(s):
    return 0


def eval_hp(s):
    return s.nhp - s.php


def eval_balanced(s):
    return (s.nhp - s.php) + 12 * (s.npot - s.ppot) + 8 * (int(s.nsh) - int(s.psh))


def eval_aggressive(s):
    return 0.5 * s.nhp - 2.0 * s.php


def eval_defensive(s):
    return 2.0 * s.nhp - 0.5 * s.php + 12 * s.npot + 8 * int(s.nsh)


EVALS = {
    "zero": eval_zero, "hp": eval_hp, "balanced": eval_balanced,
    "aggressive": eval_aggressive, "defensive": eval_defensive,
}


def _ordered(s, order, ef):
    acts = legal_actions(s)
    if order == "heuristic":
        return sorted(acts, key=lambda a: ef(apply_action(s, a)), reverse=(s.turn == "N"))
    seq = ORDERS[order] if isinstance(order, str) else order
    return [a for a in seq if a in acts]


def search(state, depth, algo="alphabeta", eval_name="balanced", order="default", node_limit=None):
    """Root = giliran NPC (MAX). algo: minimax | alphabeta | expectimax.
    node_limit -> early stop: setelah budget node habis, node dipotong dan dinilai dengan eval."""
    t0 = time.perf_counter()
    ef = EVALS[eval_name]
    st = {"nodes": 1, "cutoffs": 0, "stopped": False}

    def value(s, d, alpha, beta):
        st["nodes"] += 1
        if is_terminal(s):
            return utility(s, d)
        if d == 0:
            return ef(s)
        if node_limit and st["nodes"] >= node_limit:
            st["stopped"] = True
            return ef(s)
        acts = _ordered(s, order, ef)
        if s.turn == "N":                       # MAX
            best = -INF
            for a in acts:
                v = value(apply_action(s, a), d - 1, alpha, beta)
                best = max(best, v)
                if algo == "alphabeta":
                    alpha = max(alpha, best)
                    if alpha >= beta:
                        st["cutoffs"] += 1
                        break
            return best
        if algo == "expectimax":                # CHANCE: lawan diasumsikan acak uniform
            return sum(value(apply_action(s, a), d - 1, alpha, beta) for a in acts) / len(acts)
        best = INF                              # MIN
        for a in acts:
            v = value(apply_action(s, a), d - 1, alpha, beta)
            best = min(best, v)
            if algo == "alphabeta":
                beta = min(beta, best)
                if alpha >= beta:
                    st["cutoffs"] += 1
                    break
        return best

    scores, best_a, best_v, alpha = {}, None, -INF, -INF
    for a in _ordered(state, order, ef):
        a0 = alpha
        v = value(apply_action(state, a), depth - 1, alpha, INF)
        exact = not (algo == "alphabeta" and best_a is not None and v <= a0)
        scores[a] = (v, exact)          # exact False -> v hanyalah batas atas (<=)
        if v > best_v:
            best_v, best_a = v, a
        if algo == "alphabeta":
            alpha = max(alpha, best_v)
    return {"action": best_a, "value": best_v, "scores": scores, "nodes": st["nodes"],
            "cutoffs": st["cutoffs"], "stopped": st["stopped"],
            "time_ms": (time.perf_counter() - t0) * 1000}
# ==== BATTLE ENGINE END ====


# ==== CSP ENGINE BEGIN ====
# =====================================================================
# 6. LEVEL GENERATOR: CSP (Backtracking + MRV + LCV + AC-3) + LOCAL SEARCH
# Variabel : K (ksatria), D (naga), P1..Pn (ramuan). Domain: sel walkable.
# Kendala  : unary (jenis tile), all-different, jarak minimum antar-pasangan,
#            dan "satu komponen terhubung" (agar tidak muncul di kantong tertutup).
# =====================================================================
import random
from collections import deque

MIN_DIST = {("D", "K"): 18, ("K", "P"): 3, ("D", "P"): 4, ("P", "P"): 6}   # kunci terurut; jarak Manhattan minimum


def manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class LevelCSP:
    def __init__(self, grid, seed=None, n_potions=3, mrv=True, lcv=True, ac3=True, lcv_sample=40):
        self.grid, self.mrv, self.lcv, self.use_ac3, self.lcv_sample = grid, mrv, lcv, ac3, lcv_sample
        self.rng = random.Random(seed)
        self.vars = ["K", "D"] + [f"P{i + 1}" for i in range(n_potions)]
        self.cells = [(x, y) for y in range(grid.height) for x in range(grid.width) if grid.walkable((x, y))]
        self.comp = self._components()
        self.base = {v: [c for c in self.cells if self.unary(v, c)] for v in self.vars}
        self.base_set = {v: set(d) for v, d in self.base.items()}
        self._dist = {}
        self.stats = {}

    # ---------- kendala ----------
    def _components(self):
        comp, cid = {}, 0
        for s in self.cells:
            if s in comp:
                continue
            comp[s], q = cid, deque([s])
            while q:
                cur = q.popleft()
                for n, _ in self.grid.neighbors(cur):
                    if n not in comp:
                        comp[n] = cid
                        q.append(n)
            cid += 1
        return comp

    def unary(self, v, c):
        t = self.grid.tile(c)
        return t == "." if v in ("K", "D") else t in (".", "^")

    def ok(self, a, x, b, y):
        """Kendala biner antara variabel a=x dan b=y."""
        if x == y or self.comp[x] != self.comp[y]:
            return False
        return manh(x, y) >= MIN_DIST[tuple(sorted((a[0], b[0])))]

    def consistent(self, v, x, asg):
        return all(self.ok(v, x, w, y) for w, y in asg.items() if w != v)

    # ---------- AC-3 ----------
    def revise(self, doms, a, b):
        self.stats["revisions"] += 1
        keep = [x for x in doms[a] if any(self.ok(a, x, b, y) for y in doms[b])]
        changed = len(keep) != len(doms[a])
        doms[a] = keep
        return changed

    def ac3(self, doms, arcs=None):
        q = deque(arcs if arcs is not None else [(a, b) for a in self.vars for b in self.vars if a != b])
        while q:
            a, b = q.popleft()
            if self.revise(doms, a, b):
                if not doms[a]:
                    return False
                q.extend((c, a) for c in self.vars if c not in (a, b))
        return True

    # ---------- backtracking: MRV + LCV + MAC ----------
    def pick_var(self, un, doms):
        if not self.mrv:
            return un[0]
        return min(un, key=lambda u: (len(doms[u]), -sum(1 for w in un if w != u)))   # MRV, tie: degree

    def order_values(self, v, un, doms):
        if not self.lcv:
            return list(doms[v])
        d = doms[v]
        cands = d if len(d) <= self.lcv_sample else self.rng.sample(d, self.lcv_sample)
        others = [u for u in un if u != v]
        # LCV: nilai yang paling sedikit membuang nilai di domain variabel lain
        return sorted(cands, key=lambda x: sum(1 for u in others for y in doms[u] if not self.ok(v, x, u, y)))

    def backtrack(self, asg, doms):
        if len(asg) == len(self.vars):
            return dict(asg)
        un = [v for v in self.vars if v not in asg]
        v = self.pick_var(un, doms)
        for x in self.order_values(v, un, doms):
            self.stats["assign"] += 1
            if not self.consistent(v, x, asg):
                self.stats["backtracks"] += 1
                continue
            nd = {u: list(d) for u, d in doms.items()}
            nd[v] = [x]
            if self.use_ac3 and not self.ac3(nd, [(u, v) for u in un if u != v]):
                self.stats["backtracks"] += 1
                continue
            asg[v] = x
            r = self.backtrack(asg, nd)
            if r:
                return r
            del asg[v]
            self.stats["backtracks"] += 1
        return None

    def solve_csp(self):
        doms = {v: list(d) for v, d in self.base.items()}
        for d in doms.values():
            self.rng.shuffle(d)
        self.stats["dom_before"] = sum(len(d) for d in doms.values())
        if self.use_ac3 and not self.ac3(doms):
            return None
        self.stats["dom_after"] = sum(len(d) for d in doms.values())
        return self.backtrack({}, doms)

    # ---------- local search ----------
    def conflicts(self, v, x, asg):
        return sum(1 for w, y in asg.items() if w != v and not self.ok(v, x, w, y))

    def min_conflicts(self, max_steps=300):
        """Local search murni untuk CSP: mulai dari penugasan acak, perbaiki variabel yang konflik."""
        asg = {v: self.rng.choice(self.base[v]) for v in self.vars}
        for _ in range(max_steps):
            bad = [v for v in self.vars if self.conflicts(v, asg[v], asg) > 0]
            if not bad:
                return asg
            v = self.rng.choice(bad)
            self.stats["ls_steps"] += 1
            pool = self.rng.sample(self.base[v], min(80, len(self.base[v])))
            asg[v] = min(pool, key=lambda x: self.conflicts(v, x, asg))
        return None

    def dist(self, src):
        """Dijkstra dari src (cost = cost masuk sel), di-cache."""
        if src in self._dist:
            return self._dist[src]
        d, h = {src: 0}, [(0, src)]
        while h:
            g, cur = heapq.heappop(h)
            if g > d[cur]:
                continue
            for n, c in self.grid.neighbors(cur):
                if g + c < d.get(n, 1e9):
                    d[n] = g + c
                    heapq.heappush(h, (g + c, n))
        self._dist[src] = d
        return d

    def objective(self, asg):
        """Makin besar makin baik: rute ksatria->naga panjang, ramuan dekat rute (detour kecil), ramuan menyebar."""
        K, D = asg["K"], asg["D"]
        dk, dd = self.dist(K), self.dist(D)
        route = dk[D]
        ps = [asg[v] for v in self.vars if v[0] == "P"]
        detour = sum(dk[p] + dd[p] - route for p in ps)
        spread = min(manh(a, b) for i, a in enumerate(ps) for b in ps[i + 1:]) if len(ps) > 1 else 0
        return route - 1.5 * detour + 2 * spread

    def anneal(self, asg, iters=300, T0=8.0):
        """Simulated annealing yang hanya menerima langkah FEASIBLE (kendala CSP tetap terpenuhi)."""
        cur, fc = dict(asg), self.objective(asg)
        best, fb = dict(cur), fc
        for i in range(iters):
            T = T0 * (1 - i / iters) + 0.05
            v = self.rng.choice(self.vars)
            old = cur[v]
            new = (old[0] + self.rng.randint(-4, 4), old[1] + self.rng.randint(-4, 4))
            if new == old or new not in self.base_set[v]:
                continue
            cur[v] = new
            self.stats["ls_steps"] += 1
            if self.consistent(v, new, cur):
                fn = self.objective(cur)
                if fn >= fc or self.rng.random() < math.exp((fn - fc) / T):
                    fc = fn
                    if fc > fb:
                        best, fb = dict(cur), fc
                    continue
            cur[v] = old
        return best

    # ---------- API ----------
    def generate(self, mode="hybrid"):
        """mode: csp | ls | hybrid (CSP -> simulated annealing)."""
        t0 = time.perf_counter()
        self.stats = {"assign": 0, "backtracks": 0, "revisions": 0, "ls_steps": 0, "dom_before": 0, "dom_after": 0}
        asg = None
        if mode == "ls":
            for _ in range(20):                       # random restart
                asg = self.min_conflicts()
                if asg:
                    break
        if asg is None:                               # csp / hybrid (atau fallback dari ls)
            asg = self.solve_csp()
            if asg and mode == "hybrid":
                asg = self.anneal(asg)
        if asg is None:
            return None
        return {"K": asg["K"], "D": asg["D"], "P": [asg[v] for v in self.vars if v[0] == "P"],
                "score": self.objective(asg), "route": self.dist(asg["K"])[asg["D"]],
                "stats": dict(self.stats), "ms": (time.perf_counter() - t0) * 1000, "mode": mode}
# ==== CSP ENGINE END ====



# ---- data sprite pixel 16x16 ----
KNIGHT = [
"......rr........",
".....rrr........",
"....kkkkkkk.....",
"...kSSSSsssk....",
"...ksskkkssk....",
"...ksssssssk....",
"....kdsssdk.....",
"..kkbbbbbbbkk...",
".kggkbbbbbbk.kS.",
".kgBkbbbbbbk.kS.",
".kggkbbbbbbk.kS.",
"..kkkbbbbbbkkgg.",
"....kBBkkBBk....",
"....kdsk.kdsk...",
"....kwwk.kwwk...",
"....kkkk.kkkk...",
]
KNIGHT_PAL = dict(k="#1b1b2f", s="#aab4c4", S="#e4ecf5", d="#6c7a8f", r="#e03c4b",
                  b="#3f6fd8", B="#2a4a99", g="#f2c14e", w="#7a4b24")
DRAGON = [
"...kk......k.k..",
"..kRRk....kykyk.",
".kRRRRk..kgggggk",
".kRRRRRkkgggyGgk",
".kRRRRkggggggggk",
"..kkkkGggggkkwwk"[:16],
"...kGGGggggggkk.",
"..kGGGgggggllk..",
".kGGGgggglllllk.",
"kGGgggggllllllk.",
"kGGgggggllllllk.",
".kGGggggggggkk..",
"..kGGgk..kgGGk..",
"..kwGgk..kgGwk..",
"..kkkkk..kkkkk..",
"................",
]
DRAGON_PAL = dict(k="#1a1024", g="#43a94f", G="#2b7a3b", l="#b9e07a", y="#ffd84a",
                  r="#a02a2a", R="#e0453a", w="#f4f4f4")
POTION = [
"................",
"................",
"......kccck.....",
".......kgk......",
".......kgk......",
"......kgggk.....",
".....kghrrrk....",
"....kghrrrrrk...",
"....kgrrrrrRk...",
"....krrrrrrRk...",
"....krrrrrRRk...",
".....kRRRRRk....",
"......kkkkk.....",
"................",
"................",
"................",
]
POTION_PAL = dict(k="#2a1a1a", c="#b07a42", g="#cfe8ff", h="#ffffff", r="#e8404f", R="#a82a3a")
GOBLIN = [
"................",
"................",
"..kk........kk..",
".kpgkkkkkkkkgpk.",
".kkggggggggggkk.",
"..kgeeggggeegk..",
"..kggggggggggk..",
"...kgwkggkwgk...",
"....kkggggkk....",
"...kbbbbbbbbk.s.",
"..kgkbbyybbkgk.s",
"..kgkbbbbbbkgks.",
"...kkBBBBBBkk...",
"....kgGk.kGgk...",
"....kgGk.kGgk...",
"....kkkk.kkkk...",
]
GOBLIN_PAL = dict(k="#1a1024", g="#7fc04a", G="#4f8a2e", e="#ffe14a", w="#ffffff", p="#d98ca0",
                  b="#9a6a35", B="#5e3d1c", y="#f2c14e", s="#cfd6e0")
MAGE = [
".......kk...kook",
"......khhk..kook",
"......khhk....t.",
".....khhhhk...t.",
"....khhyyhhk..t.",
"..kkkhhhhhhkkkt.",
"...kffffffffk.t.",
"...kfkffffkfk.t.",
"...kffffffffk.t.",
"...kWWWWWWWWk.t.",
"..kkWWWWWWWWkkt.",
"..krrrWWWWrrrkt.",
"..krrrrrrrrrrkt.",
"..kRRrrrrrrRRkt.",
"..kRRRRRRRRRRkt.",
"...kkkkkkkkkk.t.",
]
MAGE_PAL = dict(k="#1a1024", h="#7b4fd0", y="#f2c14e", f="#f0c8a0", W="#e8e8f2", r="#4a62c8", R="#2d3a8a",
                t="#8a5a2b", o="#6fe8ff")


# =====================================================================
# 7. TAMPILAN PIXEL ART (sprite 16x16 dibuat di canvas offscreen, diskalakan 2x tanpa blur)
# =====================================================================
def _cv(w=16, h=16):
    c = document.createElement("canvas")
    c.width, c.height = w, h
    return c, c.getContext("2d")


def _from_rows(rows, pal):
    c, x = _cv()
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch in pal:
                x.fillStyle = pal[ch]
                x.fillRect(i, j, 1, 1)
    return c


def _speckle(x, rng, col, n):
    x.fillStyle = col
    for _ in range(n):
        x.fillRect(rng.randint(0, 15), rng.randint(0, 15), 1, 1)


def _water(x, rng, frame):
    x.fillStyle = "#2f6fb0"
    x.fillRect(0, 0, 16, 16)
    _speckle(x, rng, "#265c96", 10)
    x.fillStyle = "#6fb2e8"
    for _ in range(4):
        wx, wy = rng.randint(0, 11), rng.randint(0, 15)
        x.fillRect((wx + 4 * frame) % 13, wy, 3, 1)


def make_tile(kind, var=0, frame=0):
    c, x = _cv()
    rng = random.Random(f"{kind}{var}")
    if kind == ".":
        x.fillStyle = "#4a8a3a"
        x.fillRect(0, 0, 16, 16)
        _speckle(x, rng, "#3f7a33", 14)
        _speckle(x, rng, "#63a84b", 8)
        x.fillStyle = "#2f6a2a"
        for _ in range(2):
            tx, ty = rng.randint(1, 12), rng.randint(2, 13)
            x.fillRect(tx, ty, 1, 2); x.fillRect(tx + 2, ty, 1, 2); x.fillRect(tx + 1, ty + 1, 1, 1)
    elif kind == "^":                                   # lumpur + semak (cost 3)
        x.fillStyle = "#7a5a32"
        x.fillRect(0, 0, 16, 16)
        _speckle(x, rng, "#5e4426", 22)
        _speckle(x, rng, "#94703f", 8)
        for bx, by in ((2, 3), (8, 9)):
            x.fillStyle = "#2f6a2a"
            x.fillRect(bx, by, 6, 4); x.fillRect(bx + 1, by - 1, 4, 1)
            x.fillStyle = "#58a846"
            x.fillRect(bx + 1, by, 2, 1); x.fillRect(bx + 3, by + 1, 2, 1)
    elif kind == "#":                                   # tembok batu
        x.fillStyle = "#6b7280"
        x.fillRect(0, 0, 16, 16)
        for r in range(4):
            y = r * 4
            x.fillStyle = "#8a92a0"; x.fillRect(0, y, 16, 1)
            x.fillStyle = "#3b4048"; x.fillRect(0, y + 3, 16, 1)
            for xo in ((0, 8) if r % 2 == 0 else (4, 12)):
                x.fillRect(xo, y, 1, 3)
        _speckle(x, rng, "#4f7a3a", 3)
    elif kind == "~":
        _water(x, rng, frame)
    elif kind == "=":                                   # jembatan kayu
        _water(x, rng, 0)
        x.fillStyle = "#a9744a"; x.fillRect(2, 0, 12, 16)
        x.fillStyle = "#7a5230"
        for y in (3, 7, 11, 15):
            x.fillRect(2, y, 12, 1)
        x.fillStyle = "#c58f5e"
        for y in (0, 4, 8, 12):
            x.fillRect(3, y, 5, 1)
        x.fillStyle = "#5a3a1e"; x.fillRect(1, 0, 1, 16); x.fillRect(14, 0, 1, 16)
    return c


# =====================================================================
# 8. CLASS GAME
# =====================================================================
BATTLE_DIST = 2   # jarak Manhattan NPC-Player untuk memicu mode battle
ALGO_NAMES = {"minimax": "Minimax", "alphabeta": "Alpha-Beta",
              "alphabeta_early": "Alpha-Beta + Early Stop", "expectimax": "Expectimax"}
ACT_ID = {"attack": "btnAttack", "defend": "btnDefend", "potion": "btnPotion"}
MODE_LABELS = {"priority": "Prioritas aturan KB", "meu": "MEU (expected utility 1 langkah)", "mdp": "MDP (value iteration)"}
REL_COL = {"enemy": "rgba(255,90,90,0.9)", "friend": "rgba(90,230,120,0.9)", "predator": "rgba(255,160,40,0.95)"}
NPC_COL = {"goblin": "#ffe14a", "mage": "#c58cff", "naga": "#ff9a3c"}
SPRITE_OF = {"naga": "D", "goblin": "G", "mage": "M"}
POLICY_TXT = {"strike": "S", "guard": "G", "flee": "F"}


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


MODE_NAMES = {"csp": "CSP saja", "ls": "Local search (min-conflicts)", "hybrid": "Gabungan CSP + simulated annealing"}


class Game:
    KEY_MAP = {
        "ArrowUp": (0, -1), "w": (0, -1), "W": (0, -1),
        "ArrowDown": (0, 1), "s": (0, 1), "S": (0, 1),
        "ArrowLeft": (-1, 0), "a": (-1, 0), "A": (-1, 0),
        "ArrowRight": (1, 0), "d": (1, 0), "D": (1, 0),
        " ": (0, 0), ".": (0, 0),                                  # tunggu satu giliran
    }
    BATTLE_KEYS = {"1": "attack", "2": "defend", "3": "potion"}

    def __init__(self):
        self.grid = GridMap(MAP_DATA)
        self.level = {"K": (17, 2), "D": (2, 18), "P": []}      # cadangan jika generator gagal
        self.algo = "astar_manhattan"
        self.last_result = None
        self.game_over, self.mode, self.bs, self.debug, self.log = False, "explore", None, None, []
        self.potions, self.bonus, self.face_p, self.frame = [], 0, 1, 0
        self.tiles = {}
        self.sprites = {"K": _from_rows(KNIGHT, KNIGHT_PAL), "D": _from_rows(DRAGON, DRAGON_PAL),
                        "P": _from_rows(POTION, POTION_PAL), "G": _from_rows(GOBLIN, GOBLIN_PAL),
                        "M": _from_rows(MAGE, MAGE_PAL)}
        self.kb = KB.from_file("kb.txt")
        self.sim = WorldSim(self.grid, self.kb, lambda a, b: Pathfinding.search(self.grid, a, b, HEURISTICS[self.algo]))
        self.kb_shown, self.level_seed = 1, 0

        el = document.getElementById
        self.el = el
        self.canvas = el("gameCanvas")
        self.ctx = self.canvas.getContext("2d")
        self.stat_expanded, self.stat_cost = el("statExpanded"), el("statCost")
        self.stat_time, self.stat_status, self.stat_pot = el("statTime"), el("statStatus"), el("statPot")

        self._proxies = []
        self._bind_events()
        self.generate_level()
        self._on_tick = create_proxy(self.tick)
        window.setInterval(self._on_tick, 450)                  # animasi idle 2 frame

    def _on(self, target, evt, fn):
        p = create_proxy(fn)
        self._proxies.append(p)
        target.addEventListener(evt, p)

    def _bind_events(self):
        self._on(document, "keydown", self.on_keydown)
        self._on(self.el("algoSelect"), "change", self.on_algo_change)
        self._on(self.el("resetBtn"), "click", self.on_reset)
        self._on(self.el("genBtn"), "click", self.generate_level)
        for act, bid in ACT_ID.items():
            self._on(self.el(bid), "click", lambda e, a=act: self.do_player_action(a))
        self._on(self.el("dbgToggle"), "change", lambda e: self.render())
        self._on(self.el("ovToggle"), "change", lambda e: self.render())
        for i in ("kbToggle", "planToggle", "kbAnim", "mdpPair"):
            self._on(self.el(i), "change", lambda e: self.refresh_world())
        for i in ("decMode", "planAlgo", "mdpGamma"):
            self._on(self.el(i), "change", self.on_world_setting)
        self._on(self.el("waitBtn"), "click", lambda e: self.world_turn())

    def tick(self, *args):
        self.frame ^= 1
        L = self.sim.last
        if L and self.mode == "explore" and self.kb_shown < len(L["inf"].rounds):
            self.kb_shown += 1                                  # animasi: satu ronde inferensi per tick
        self.draw_scene()

    # ---------------- generator level (CSP + local search) ----------------
    def generate_level(self, event=None):
        val, chk = (lambda i: self.el(i).value), (lambda i: self.el(i).checked)
        s = val("genSeed").strip()
        seed = int(s) if s.isdigit() else random.randrange(1, 10 ** 6)
        self.level_seed = seed
        gen = LevelCSP(self.grid, seed, mrv=chk("genMrv"), lcv=chk("genLcv"), ac3=chk("genAc3"))
        res = gen.generate(val("genMode"))
        if res is None:
            self.el("genStats").innerHTML = "<p>Generator gagal menemukan solusi. Level lama dipertahankan.</p>"
            return
        self.level = res
        st = res["stats"]
        rows = [("Mode", MODE_NAMES[res["mode"]]), ("Seed", seed),
                ("Skor objektif", f"{res['score']:.1f}"), ("Biaya rute ksatria-naga", res["route"]),
                ("Assignment / backtrack", f"{st['assign']} / {st['backtracks']}"),
                ("Revisi AC-3", st["revisions"]),
                ("Domain sebelum - sesudah AC-3", f"{st['dom_before']} - {st['dom_after']}"),
                ("Langkah local search", st["ls_steps"]), ("Waktu", f"{res['ms']:.1f} ms")]
        self.el("genStats").innerHTML = "".join(
            f"<div class='stat-row'><span>{k}</span><span>{v}</span></div>" for k, v in rows)
        self.on_reset()

    # ---------------- eksplorasi ----------------
    def on_algo_change(self, event):
        self.algo = event.target.value
        self.recompute_npc_path()
        self.render()

    def on_reset(self, event=None):
        L = self.level
        self.player, self.npc, self.potions, self.bonus = L["K"], L["D"], list(L["P"]), 0
        self.game_over, self.mode, self.bs, self.debug, self.log = False, "explore", None, None, []
        self.el("battleSection").classList.add("hidden")
        self.sim.reset(L, self.potions, self.level_seed)
        self.npc = self.sim.npcs["naga"].pos
        self.on_world_setting()
        self.recompute_npc_path()
        self.render()

    def on_keydown(self, event):
        key = event.key
        if getattr(event.target, "tagName", "") == "INPUT" and getattr(event.target, "type", "") == "text":
            return                                                  # sedang mengetik seed
        if self.mode == "battle":
            if key in self.BATTLE_KEYS:
                event.preventDefault()
                self.do_player_action(self.BATTLE_KEYS[key])
            return
        if self.game_over or key not in self.KEY_MAP:
            return
        event.preventDefault()
        dx, dy = self.KEY_MAP[key]
        if dx:
            self.face_p = dx
        target = (self.player[0] + dx, self.player[1] + dy)
        if self.grid.walkable(target):
            self.player = target
            if target in self.potions:                          # kumpulkan ramuan
                self.potions.remove(target)
                self.bonus += 1
        self.world_turn()

    def world_turn(self):
        """Satu giliran dunia: NPC mempersepsi -> inferensi KB -> memutuskan -> merencanakan -> bertindak."""
        if self.mode == "battle" or self.game_over:
            return
        r = self.last_result
        chase = r["path"][1] if r and r["path"] and len(r["path"]) > 1 else None
        self.sim.step(self.player, chase)
        self.npc = self.sim.npcs["naga"].pos
        self.kb_shown = 1
        if h_manhattan(self.npc, self.player) <= BATTLE_DIST:
            self.start_battle()
        else:
            self.recompute_npc_path()
        self.render()

    def on_world_setting(self, event=None):
        v = lambda i: self.el(i).value
        self.sim.mode, self.sim.algo, self.sim.gamma = v("decMode"), v("planAlgo"), float(v("mdpGamma"))
        self.sim.observe(self.player)
        self.kb_shown = 1
        self.render()

    def refresh_world(self):
        self.render()

    def recompute_npc_path(self):
        self.last_result = Pathfinding.search(self.grid, self.npc, self.player, HEURISTICS[self.algo])

    def step_npc(self):
        r = self.last_result
        if r and r["path"] and len(r["path"]) > 1:
            self.npc = r["path"][1]

    # ---------------- battle ----------------
    def start_battle(self):
        self.mode, self.debug = "battle", None
        nhp = self.sim.npcs["naga"].hp                                      # luka dari penyihir terbawa ke battle
        self.bs = new_battle()._replace(ppot=START_POTIONS + self.bonus, nhp=nhp)   # ramuan yang dikumpulkan dibawa ke battle
        self.log = [f"Battle dimulai! Ksatria membawa {self.bs.ppot} ramuan, HP naga {nhp}. Pilih Attack / Defend / Potion (1-2-3)."]
        self.el("battleSection").classList.remove("hidden")

    def add_log(self, msg):
        self.log = (self.log + [msg])[-7:]

    def do_player_action(self, action):
        if self.mode != "battle" or self.game_over or self.bs.turn != "P":
            return
        if action not in legal_actions(self.bs):
            self.add_log("Aksi tidak legal (sudah shield / potion habis / HP penuh).")
            self.render()
            return
        old = self.bs
        self.bs = apply_action(old, action)
        self.add_log(f"Ksatria: {action} -> {self._delta(old, self.bs)}")
        if is_terminal(self.bs):
            self.end_battle()
        else:
            self.npc_turn()
        self.render()

    def npc_turn(self):
        v = lambda i: self.el(i).value
        depth, ev, order = int(v("battleDepth")), v("battleEval"), v("battleOrder")
        limit, sel = int(v("battleLimit")), v("battleAlgo")
        cfgs = {"minimax": ("minimax", None), "alphabeta": ("alphabeta", None),
                "alphabeta_early": ("alphabeta", limit), "expectimax": ("expectimax", None)}
        results = {n: search(self.bs, depth, a, ev, order, lim) for n, (a, lim) in cfgs.items()}
        main = results[sel]
        self.debug = {"sel": sel, "results": results, "depth": depth, "eval": ev, "order": order}
        old = self.bs
        self.bs = apply_action(old, main["action"])
        self.add_log(f"Naga ({ALGO_NAMES[sel]}, d={depth}): {main['action']} -> {self._delta(old, self.bs)}")
        if is_terminal(self.bs):
            self.end_battle()

    @staticmethod
    def _delta(a, b):
        return f"HP ksatria {a.php}->{b.php}, HP naga {a.nhp}->{b.nhp}"

    def end_battle(self):
        self.game_over = True
        self.add_log("NAGA MENANG!" if self.bs.php <= 0 else "KSATRIA MENANG!")

    # ---------------- render ----------------
    def render(self):
        self.draw_scene()
        if self.mode == "battle":
            self._update_battle_panel()
        self._update_world_panel()
        self._update_stats()

    def tile_img(self, ch, x, y):
        frame = self.frame if ch == "~" else 0
        key = (ch, (x * 5 + y * 3) % 3, frame)
        if key not in self.tiles:
            self.tiles[key] = make_tile(*key)
        return self.tiles[key]

    def draw_scene(self):
        ctx = self.ctx
        ctx.imageSmoothingEnabled = False
        ctx.clearRect(0, 0, self.canvas.width, self.canvas.height)
        for y in range(self.grid.height):
            for x in range(self.grid.width):
                ctx.drawImage(self.tile_img(self.grid.tile((x, y)), x, y), x * TILE, y * TILE, TILE, TILE)

        r = self.last_result
        if r and self.mode == "explore" and self.el("ovToggle").checked:
            for color, cells in (("rgba(255,60,60,0.38)", r["closed"]),
                                 ("rgba(255,220,60,0.40)", r["open"]),
                                 ("rgba(60,255,120,0.6)", r["path"] or [])):
                ctx.fillStyle = color
                for (x, y) in cells:
                    ctx.fillRect(x * TILE, y * TILE, TILE, TILE)

        bob = 2 * self.frame
        for p in self.potions:
            self._draw_sprite("P", p, 1, bob, 1.0)
        ents = [("D", self.npc), ("K", self.player)] + [(SPRITE_OF[n], o.pos) for n, o in self.sim.npcs.items()
                                                        if n != "naga" and o.alive]
        for who, pos in sorted(ents, key=lambda t: t[1][1]):
            if who == "K":
                self._draw_sprite("K", pos, self.face_p, bob, 1.0)
            elif who == "D":                                    # naga menghadap ksatria, digambar 1.5x
                self._draw_sprite("D", pos, 1 if self.player[0] >= pos[0] else -1, bob, 1.5)
            else:
                self._draw_sprite(who, pos, 1 if self.player[0] >= pos[0] else -1, bob, 1.0)
        if self.mode == "explore":
            for n, o in self.sim.npcs.items():                  # bar HP dunia (HP naga dibawa ke battle)
                if o.alive:
                    self._draw_hp(o.pos, 100 * o.hp / o.maxhp, 22 if n == "naga" else 6)
            if self.el("kbToggle").checked:
                self._draw_kb_overlay()
        if self.mode == "battle":
            self._draw_hp(self.npc, self.bs.nhp, 18 + 4)
            self._draw_hp(self.player, self.bs.php, 6)
            if self.el("dbgToggle").checked:
                self._draw_debug()
            if self.game_over:
                self._draw_banner("NAGA MENANG" if self.bs.php <= 0 else "KSATRIA MENANG")

    # ---------------- overlay inferensi KB (canvas) ----------------
    @staticmethod
    def _ctr(pos):
        return pos[0] * TILE + TILE / 2, pos[1] * TILE + TILE / 2

    def _tag(self, x, y, text, color):
        ctx = self.ctx
        ctx.font = "11px monospace"
        w = ctx.measureText(text).width + 6
        ctx.fillStyle = "rgba(8,12,12,0.85)"
        ctx.fillRect(x - w / 2, y - 8, w, 13)
        ctx.fillStyle = color
        ctx.textAlign = "center"
        ctx.fillText(text, x, y + 2)
        ctx.textAlign = "left"

    def _arrow(self, a, b, color, width=2, dash=(), label=None, head=True, shrink=12):
        ctx = self.ctx
        (x1, y1), (x2, y2) = self._ctr(a), self._ctr(b)
        L = math.hypot(x2 - x1, y2 - y1) or 1
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        x1, y1, x2, y2 = x1 + ux * shrink, y1 + uy * shrink, x2 - ux * shrink, y2 - uy * shrink
        ctx.strokeStyle = ctx.fillStyle = color
        ctx.lineWidth = width
        ctx.setLineDash(to_js(list(dash)))
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
        ctx.setLineDash(to_js([]))
        if head:
            ctx.beginPath()
            ctx.moveTo(x2, y2)
            ctx.lineTo(x2 - ux * 8 + uy * 4, y2 - uy * 8 - ux * 4)
            ctx.lineTo(x2 - ux * 8 - uy * 4, y2 - uy * 8 + ux * 4)
            ctx.fill()
        if label:
            self._tag((x1 + x2) / 2, (y1 + y2) / 2, label, color)

    def _draw_kb_overlay(self):
        """Menampilkan inferensi ronde demi ronde: relasi -> ancaman -> aksi -> keputusan -> rencana."""
        L = self.sim.last
        if not L:
            return
        inf, sim, ctx = L["inf"], self.sim, self.ctx
        n = len(inf.rounds)
        shown = self.kb_shown if self.el("kbAnim").checked else n
        done = shown >= n
        pos = {k: o.pos for k, o in sim.npcs.items() if o.alive}
        vis = lambda a: inf.facts[a].round <= shown
        names = sorted(pos)
        for i, x in enumerate(names):                                   # relasi turunan (ronde 1)
            for y in names[i + 1:]:
                if not inf.holds(("near", x, y)):
                    continue
                for rel in ("enemy", "friend"):
                    if inf.holds((rel, x, y)) and vis((rel, x, y)):
                        self._arrow(pos[x], pos[y], REL_COL[rel], 1, (4, 4), None, False)
                for p, q in ((x, y), (y, x)):
                    if inf.holds(("predator", p, q)) and vis(("predator", p, q)):
                        self._arrow(pos[p], pos[q], REL_COL["predator"], 1, (2, 3), "pemangsa", True, 16)
        for a in inf.query("threat", None, None):                       # ancaman: Y -> X
            if vis(a) and a[1] in pos and a[2] in pos:
                self._arrow(pos[a[2]], pos[a[1]], "rgba(255,60,60,0.95)", 3, (), "ancaman", True, 14)
        chosen = {k: next((r for r in rows if r.get("chosen")), None) for k, rows in L["dec"].items()}
        for a in inf.query("act", None, None, None):                    # aksi yang diizinkan KB
            if not vis(a):
                continue
            x, act, y = a[1], a[2], a[3]
            if x not in pos or y not in pos:
                continue
            ch = chosen.get(x)
            is_ch = bool(ch and ch["act"] == act and (ch["tgt"] or x) == y)
            if done and not is_ch:
                continue
            col, w = ("#ffe14a", 3) if (is_ch and done) else ("rgba(120,220,255,0.85)", 1)
            if x == y:
                px, py = self._ctr(pos[x])
                self._tag(px, py - 34, act, col)
            else:
                self._arrow(pos[x], pos[y], col, w, () if w > 1 else (3, 3), act, True, 14)
        if done and self.el("planToggle").checked:                      # rencana (planner)
            for k, pl in L["plans"].items():
                if pl and pl["res"]["found"] and len(pl["line"]) > 1:
                    for p, q in zip(pl["line"], pl["line"][1:]):
                        self._arrow(p, q, NPC_COL[k], 2, (6, 4), None, True, 6)
                    ex, ey = self._ctr(pl["line"][-1])
                    self._tag(ex, ey - 12, f"{NAMES[k]}: {pl['goal'][0]}", NPC_COL[k])
        lines = [f"KB  ronde {min(shown, n)}/{n}  |  {inf.stats()['facts']} fakta, {inf.stats()['derived']} turunan"]
        if not done:
            cur = [a for a in inf.rounds[min(shown, n) - 1] if inf.facts[a].dyn][:6] if n else []
            lines += [f"{inf.facts[a].rule.id:<4}{fmt_atom(a)}" for a in cur]
        else:
            for k, row in chosen.items():
                if row:
                    sc = f"EU={row['eu']:.1f}" if row["eu"] is not None else f"p={row['prio']}"
                    lines.append(f"{NAMES[k]:<9}-> {row['act']}{'(' + row['tgt'] + ')' if row['tgt'] else ''}  {sc}")
        h = 8 + 15 * len(lines)
        ctx.fillStyle = "rgba(0,0,0,0.78)"
        ctx.fillRect(6, self.canvas.height - h - 6, 430, h)
        ctx.font = "12px monospace"
        ctx.fillStyle = "#e6edf3"
        for i, ln in enumerate(lines):
            ctx.fillText(ln, 12, self.canvas.height - h + 8 + 15 * i)

    # ---------------- panel: KB, keputusan, planning, MDP ----------------
    def _update_world_panel(self):
        L, el, sim = self.sim.last, self.el, self.sim
        if not L:
            return
        inf = L["inf"]
        st = inf.stats()
        el("kbStats").innerHTML = "".join(f"<div class='stat-row'><span>{k}</span><span>{v}</span></div>" for k, v in (
            ("Fakta (statis + dinamis)", st["facts"]), ("Fakta turunan", f"{st['derived']} ({st['derived_dyn']} dinamis)"),
            ("Ronde inferensi", st["rounds"]), ("Aturan terpicu", st["firings"]), ("Waktu inferensi", f"{st['ms']:.2f} ms")))
        lines = []
        for i, rd in enumerate(inf.rounds, 1):
            dyn = [a for a in rd if inf.facts[a].dyn]
            lines.append(f"Ronde {i}: {len(rd)} fakta baru ({len(dyn)} bergantung kondisi saat ini)")
            lines += [f"  {inf.facts[a].rule.id:<4} {fmt_atom(a)}" for a in dyn]
        lines.append("")
        lines.append("Penjelasan keputusan (rantai penurunan):")
        for k, rows in L["dec"].items():
            ch = next((r for r in rows if r.get("chosen")), None)
            if ch and ch["act"] != "continue":
                lines += [f"* {NAMES[k]}"] + ["  " + t for t in inf.explain(("act", k, ch["act"], ch["tgt"] or k), 3)]
            else:
                lines.append(f"* {NAMES[k]}: tidak ada aksi interaksi -> {'ikuti rencana' if L['plans'].get(k) else 'perilaku dasar'}")
        el("kbTrace").innerText = "\n".join(lines)

        out = [f"<small>Mode keputusan: {MODE_LABELS[sim.mode]}</small>"]
        for k, rows in L["dec"].items():
            body = ""
            for r in rows:
                nm = "lanjut rencana" if r["act"] == "continue" else r["act"] + (f" &rarr; {NAMES[r['tgt']]}" if r["tgt"] else "")
                eu = "-" if r["eu"] is None else f"{r['eu']:.1f}"
                body += (f"<tr class='{'act' if r.get('chosen') else ''}'><td>{nm}</td><td>{'/'.join(r['rules'])} p{r['prio']}</td>"
                         f"<td>{eu}</td></tr>")
            if not body:
                body = "<tr><td colspan='3'>tidak ada aksi KB yang berlaku</td></tr>"
            out.append(f"<table><tr><th colspan='3'>{NAMES[k]}</th></tr><tr><th>Aksi</th><th>Aturan</th><th>EU</th></tr>{body}</table>")
        el("decTable").innerHTML = "".join(out)

        out = []
        for k in sim.ORDER:
            o = sim.npcs[k]
            pl = L["plans"].get(k)
            if not o.alive:
                out.append(f"<p><b>{NAMES[k]}</b>: mati, bangkit dalam {o.respawn_in} giliran</p>")
            elif not pl:
                out.append(f"<p><b>{NAMES[k]}</b>: tidak ada tujuan dari KB" + (" (mengejar ksatria dengan A*)" if k == "naga" else "") + "</p>")
            else:
                r = pl["res"]
                seq = " &rarr; ".join(esc(x) for x in pl["labels"]) if r["found"] else "tidak ada rencana"
                cmp_rows = "".join(f"<tr class='{'act' if a == sim.algo else ''}'><td>{PLAN_LABELS[a]}</td><td>{x['expanded']}</td>"
                                   f"<td>{x['cost'] if x['found'] else '-'}</td><td>{x['ms']:.2f}</td></tr>" for a, x in pl["results"].items())
                out.append(f"<p><b>{NAMES[k]}</b> - tujuan <i>{pl['goal'][0]}</i>{'' if pl['goal'][1] == 'none' else ' (' + pl['goal'][1] + ')'}"
                           f"<br>{seq}</p><table><tr><th>Planner</th><th>Node</th><th>Biaya</th><th>ms</th></tr>{cmp_rows}</table>")
        el("planTable").innerHTML = "".join(out)

        a, b = el("mdpPair").value.split("-")
        m = sim.pair_mdp(a, b)
        cur, pol = m["cur"], m["policy"]
        grid = "<tr><th></th>" + "".join(f"<th>{f}</th>" for f in range(1, 6)) + "</tr>"
        for me in range(5, 0, -1):
            grid += f"<tr><th>{me}</th>" + "".join(
                f"<td class='pol-{pol[(me, f)]}{' cur' if cur == (me, f) else ''}'>{POLICY_TXT[pol[(me, f)]]}</td>" for f in range(1, 6)) + "</tr>"
        v = f"{m['V'][cur]:.1f}" if cur else "-"
        el("mdpBox").innerHTML = (
            f"<table class='mdp'>{grid}</table><small>{NAMES[a]} lawan {NAMES[b]} | baris = bucket HP {NAMES[a]}, kolom = bucket HP {NAMES[b]}"
            f"<br>S strike, G guard, F flee | kotak terang = keadaan sekarang</small>"
            f"<div class='stat-row'><span>Value iteration</span><span>{m['iters']} iterasi, {m['ms']:.1f} ms</span></div>"
            f"<div class='stat-row'><span>&gamma; / delta akhir</span><span>{m['gamma']} / {m['deltas'][-1]:.4f}</span></div>"
            f"<div class='stat-row'><span>V* keadaan sekarang</span><span>{v}</span></div>")
        s = sim.stats
        el("worldLog").innerHTML = ("<br>".join(esc(x) for x in sim.log[-8:]) or "Belum ada kejadian.") + (
            f"<br><small>curi {s['steal']} (gagal {s['steal_fail']}), upeti {s['gift']}, mangsa {s['devour']}, "
            f"sihir {s['cast']}, kabur {s['flee']}, korban {s['kills']}</small>")

    def _draw_sprite(self, who, pos, face, bob, scale):
        ctx, size = self.ctx, TILE * scale
        x0 = pos[0] * TILE - (size - TILE) / 2
        y0 = pos[1] * TILE - (size - TILE) - (bob if who != "P" else bob // 2)
        ctx.fillStyle = "rgba(0,0,0,0.30)"                      # bayangan di kaki
        ctx.beginPath()
        ctx.ellipse(pos[0] * TILE + TILE / 2, pos[1] * TILE + TILE - 3, size * 0.32, 4, 0, 0, 2 * math.pi)
        ctx.fill()
        ctx.save()
        if face < 0:
            ctx.translate(x0 + size, y0)
            ctx.scale(-1, 1)
            ctx.drawImage(self.sprites[who], 0, 0, size, size)
        else:
            ctx.drawImage(self.sprites[who], x0, y0, size, size)
        ctx.restore()

    def _draw_hp(self, pos, hp, lift):
        x, y = pos[0] * TILE, pos[1] * TILE - lift
        self.ctx.fillStyle = "#000"
        self.ctx.fillRect(x - 1, y - 1, TILE + 2, 7)
        self.ctx.fillStyle = "#4cd964" if hp > 40 else "#ff9500" if hp > 20 else "#ff3b30"
        self.ctx.fillRect(x, y, TILE * hp / MAX_HP, 5)

    def _draw_banner(self, text):
        ctx = self.ctx
        ctx.fillStyle = "rgba(10,12,16,0.82)"
        ctx.fillRect(0, 270, self.canvas.width, 80)
        ctx.font = "20px 'Press Start 2P', monospace"
        ctx.textAlign = "center"
        ctx.fillStyle = "#f2c14e"
        ctx.fillText(text, self.canvas.width / 2, 318)
        ctx.textAlign = "left"

    def _draw_debug(self):
        d = self.debug
        if not d:
            return
        ctx, main = self.ctx, d["results"][d["sel"]]
        lines = [f"NAGA DEBUG  {ALGO_NAMES[d['sel']]}  depth={d['depth']}",
                 f"eval={d['eval']}  order={d['order']}", "-- skor aksi --"]
        for a, (val, exact) in main["scores"].items():
            lines.append(f"{'>' if a == main['action'] else ' '} {a:<7} {'' if exact else '<='}{val:.1f}")
        lines.append("-- node count --")
        for n, res in d["results"].items():
            lines.append(f"{ALGO_NAMES[n]:<24}{res['nodes']:>6}")
        h = 8 + 15 * len(lines)
        ctx.fillStyle = "rgba(0,0,0,0.78)"
        ctx.fillRect(6, 6, 330, h)
        ctx.font = "12px monospace"
        ctx.fillStyle = "#e6edf3"
        for i, ln in enumerate(lines):
            ctx.fillText(ln, 12, 22 + 15 * i)

    def _update_battle_panel(self):
        s, el = self.bs, self.el
        el("playerHpBar").style.width = f"{s.php}%"
        el("npcHpBar").style.width = f"{s.nhp}%"
        el("playerHpTxt").innerText = f"{s.php}/{MAX_HP} | potion {s.ppot} | shield {'ON' if s.psh else '-'}"
        el("npcHpTxt").innerText = f"{s.nhp}/{MAX_HP} | potion {s.npot} | shield {'ON' if s.nsh else '-'}"
        el("battleLog").innerHTML = "<br>".join(self.log)
        legal = legal_actions(s) if (not self.game_over and s.turn == "P") else []
        for act, bid in ACT_ID.items():
            el(bid).disabled = act not in legal
        d = self.debug
        if not d:
            el("debugTable").innerHTML = ""
            return
        main = d["results"][d["sel"]]
        rows = "".join(
            f"<tr><td>{'&#10003; ' if a == main['action'] else ''}{a}</td>"
            f"<td>{'' if ex else '&le; '}{v:.1f}</td></tr>" for a, (v, ex) in main["scores"].items())
        cmp_rows = "".join(
            f"<tr class=\"{'act' if n == d['sel'] else ''}\"><td>{ALGO_NAMES[n]}</td><td>{r['nodes']}</td>"
            f"<td>{r['cutoffs']}</td><td>{r['time_ms']:.2f}</td><td>{r['action']}{' *' if r['stopped'] else ''}</td></tr>"
            for n, r in d["results"].items())
        el("debugTable").innerHTML = (
            "<table><tr><th>Aksi naga</th><th>Skor</th></tr>" + rows + "</table>"
            "<table><tr><th>Algoritma</th><th>Node</th><th>Cut</th><th>ms</th><th>Pilih</th></tr>"
            + cmp_rows + "</table><small>&le; = batas atas (dipangkas alpha-beta); * = early stop aktif</small>")

    def _update_stats(self):
        r = self.last_result
        if r:
            self.stat_expanded.innerText = str(r["expanded"])
            self.stat_cost.innerText = str(r["cost"]) if r["path"] else "tidak ditemukan"
            self.stat_time.innerText = f'{r["time_ms"]:.3f}'
        self.stat_pot.innerText = f"{self.bonus} / {len(self.level['P'])}"
        if self.mode == "battle":
            self.stat_status.innerText = ("Battle selesai. Klik \"Reset Permainan\"." if self.game_over
                                          else "MODE BATTLE - giliran Anda (1=Attack, 2=Defend, 3=Potion)")
        else:
            self.stat_status.innerText = f"Algoritma naga: {ALGO_LABELS[self.algo]}"


# Jalankan Game
game = Game()
