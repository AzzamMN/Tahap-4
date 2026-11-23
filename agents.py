"""Dunia NPC: persepsi -> KB (inferensi) -> keputusan (priority / MEU / MDP) -> planning (STRIPS) -> aksi.
Tanpa DOM (bisa diuji headless). Memakai kb_engine, planner, decision; Pathfinding & grid disuntik dari main.py."""
import heapq
import random
from planner import Op, plan as run_plan, op_label, HEURISTICS as PLAN_ALGOS
import decision

NAMES = {"naga": "Naga", "goblin": "Goblin", "mage": "Penyihir"}
HUNGRY_AT, RESPAWN, NAGA_MIN_HP, POTION_CAP = 14, 12, 5, 2
RANGE_NEAR, RANGE_SPELL, RANGE_ADJ = 6, 3, 1
STEAL_COST, MODES = 5, ("priority", "meu", "mdp")


def manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def level_of(hp, mx):
    r = hp / mx
    return "low" if r <= 0.35 else "mid" if r <= 0.7 else "high"


class NPC:
    def __init__(self, name, kb):
        self.name = name
        v = lambda pred, i=1: (kb.static_query(pred, name, *([None] * i)) or [None])[0]
        self.maxhp = v("maxhp", 1)[2]
        mel, spl, st = v("melee", 2), v("spell", 2), v("steal_chance", 1)
        self.melee = mel[2:4] if mel else None
        self.spell = spl[2:4] if spl else None
        self.steal_p = st[2] if st else 0
        self.flee_p, self.greed = v("flee_chance", 1)[2], v("greed", 1)[2]
        self.caution, self.speed = v("caution", 1)[2], v("speed", 1)[2]
        self.pos = self.home = (0, 0)
        self.hp, self.pot, self.hunger, self.alive, self.respawn_in = self.maxhp, 0, 0, True, 0

    @property
    def hungry(self):
        return self.hunger >= HUNGRY_AT


class WorldSim:
    ORDER = ("goblin", "mage", "naga")

    def __init__(self, grid, kb, path_fn, seed=0):
        self.grid, self.kb, self.path_fn, self.rng = grid, kb, path_fn, random.Random(seed)
        self.npcs = {a[1]: NPC(a[1], kb) for a in sorted(kb.static_query("npc", None))}
        self.mode, self.algo, self.gamma = "priority", "astar_hmax", 0.95
        self.dcache, self.tick, self.log, self.last = {}, 0, [], None
        self.potions, self.knight, self.stats = [], (0, 0), {}

    # ------------------------------------------------------------------ util
    def dist(self, src):
        if src in self.dcache:
            return self.dcache[src]
        d, h = {src: 0}, [(0, src)]
        while h:
            g, cur = heapq.heappop(h)
            if g > d[cur]:
                continue
            for n, c in self.grid.neighbors(cur):
                if g + c < d.get(n, 1e9):
                    d[n] = g + c
                    heapq.heappush(h, (g + c, n))
        self.dcache[src] = d
        return d

    def say(self, msg):
        self.log = (self.log + [f"[{self.tick}] {msg}"])[-14:]

    def occupied(self, pos, ignore=None):
        return pos == self.knight or any(n.alive and n.name != ignore and n.pos == pos for n in self.npcs.values())

    # ------------------------------------------------------------------ reset
    def reset(self, level, potions, seed=0):
        self.rng, self.tick, self.log, self.last, self.potions = random.Random(seed), 0, [], None, potions
        self.stats = {k: 0 for k in ("steal", "steal_fail", "gift", "devour", "cast", "attack", "drink", "flee", "pickup", "kills")}
        K, D = level["K"], level["D"]
        self.knight = K
        reach = sorted(c for c in self.dist(K) if self.grid.tile(c) == ".")
        def pick(rules):
            for slack in range(0, 6):
                pool = [c for c in reach if all(f(c, slack) for f in rules) and c not in (K, D) and c not in potions]
                if pool:
                    return self.rng.choice(pool)
            return self.rng.choice(reach)
        m = pick([lambda c, s: manh(c, K) >= 7 - s, lambda c, s: manh(c, D) >= 6 - s])
        g = pick([lambda c, s: 4 - s <= manh(c, D) <= 9 + s, lambda c, s: manh(c, K) >= 6 - s, lambda c, s: manh(c, m) >= 5 - s])
        for n, pos in (("naga", D), ("goblin", g), ("mage", m)):
            o = self.npcs[n]
            o.pos = o.home = pos
            o.hp, o.alive, o.respawn_in, o.hunger = o.maxhp, True, 0, 0
            o.pot = 1 if n == "mage" else 0
        self.npcs["naga"].hunger = self.rng.randint(5, 10)

    # ------------------------------------------------------------------ persepsi -> fakta dinamis
    def facts(self):
        out, al = [], [n for n in self.npcs.values() if n.alive]
        for n in al:
            out += [("alive", n.name), ("hp_level", n.name, level_of(n.hp, n.maxhp)),
                    ("has_potion", n.name) if n.pot > 0 else ("no_potion", n.name)]
            if n.hungry:
                out.append(("hungry", n.name))
            for o in al:
                if o is n:
                    continue
                d = manh(n.pos, o.pos)
                for pred, lim in (("adjacent", RANGE_ADJ), ("in_range", RANGE_SPELL), ("near", RANGE_NEAR)):
                    if d <= lim:
                        out.append((pred, n.name, o.name))
        return out

    # ------------------------------------------------------------------ keputusan
    def actor(self, o):
        return dict(name=o.name, hp=o.hp, maxhp=o.maxhp, pot=o.pot, melee=o.melee, spell=o.spell, steal_p=o.steal_p,
                    flee_p=o.flee_p, greed=o.greed, caution=o.caution)

    def retal(self, inf, me, foe):
        """Serangan balasan `foe` terhadap `me` pada jarak sekarang (bila foe memusuhi me)."""
        hostile = inf.holds(("enemy", foe.name, me.name)) or (inf.holds(("predator", foe.name, me.name)) and foe.hungry)
        if not hostile:
            return None
        d = manh(me.pos, foe.pos)
        if d <= RANGE_ADJ and foe.hungry and inf.holds(("predator", foe.name, me.name)):
            return (999, decision.DEVOUR_HIT)                 # diterkam predator lapar = fatal
        if d <= RANGE_ADJ and foe.melee:
            return foe.melee
        if d <= RANGE_SPELL and foe.spell:
            return foe.spell
        return None

    def primary_foe(self, inf, me):
        best, score = None, 0
        for o in self.npcs.values():
            if o is me or not o.alive:
                continue
            r = self.retal(inf, me, o)
            if r and r[0] * r[1] > score:
                best, score = o, r[0] * r[1]
        return best

    @staticmethod
    def rel(inf, x, y):
        if inf.holds(("enemy", x, y)) or inf.holds(("predator", x, y)) or inf.holds(("predator", y, x)):
            return "enemy"
        return "friend" if inf.holds(("friend", x, y)) else "neutral"

    def decide(self, inf, me):
        cands = [(a[2], a[3], inf.prio(a), inf.rule_ids(a)) for a in inf.query("act", me.name, None, None)]
        rows = []
        for act, y, prio, rules in cands:
            row = dict(act=act, tgt=None if y == me.name else y, prio=prio, rules=rules, eu=None, p=None)
            if self.mode != "priority":
                foe_o = self.npcs[y] if y != me.name else self.primary_foe(inf, me)
                foe = self.actor(foe_o) if foe_o else None
                if foe and act == "gift":
                    foe["appease"] = inf.holds(("predator", y, me.name)) and foe_o.hungry
                strike = {"attack": me.melee, "devour": me.melee, "cast": me.spell}.get(act) or max(
                    (s for s in (me.melee, me.spell) if s), key=lambda s: s[0] * s[1], default=None)
                row["eu"], row["p"] = decision.expected_utility(
                    act, self.actor(me), foe, self.rel(inf, me.name, foe_o.name) if foe_o else None,
                    self.retal(inf, me, foe_o) if foe_o else None, strike, self.mode, self.gamma)
            rows.append(row)
        if self.mode == "priority":
            rows.sort(key=lambda r: -r["prio"])
            if rows:
                rows[0]["chosen"] = True
            return rows
        foe_o = self.primary_foe(inf, me)
        base = dict(act="continue", tgt=None, prio=-1, rules=[], p=None)
        base["eu"], _ = decision.expected_utility(
            "continue", self.actor(me), self.actor(foe_o) if foe_o else None,
            self.rel(inf, me.name, foe_o.name) if foe_o else None, self.retal(inf, me, foe_o) if foe_o else None, None, self.mode, self.gamma)
        rows.append(base)
        rows.sort(key=lambda r: (-round(r["eu"], 4), -r["prio"]))
        rows[0]["chosen"] = True
        return rows

    # ------------------------------------------------------------------ planning
    def hide_cell(self, me, thr):
        dm, dt = self.dist(me.pos), self.dist(thr.pos)
        pool = [c for c in dm if dm[c] <= 14 and not self.occupied(c, me.name)]
        return max(pool, key=lambda c: (dt.get(c, 0) - 0.3 * dm[c], c)) if pool else me.pos

    def build_plan(self, inf, me, goal):
        kind, tgt = goal[2], goal[3]
        nodes, kinds = {"me": me.pos}, {"me": "cell"}
        ops, X = [], me.name
        init, goalset = set(), set()
        def op(name, args, pre, add, dele, cost):
            ops.append(Op(name, tuple(args), frozenset(pre), frozenset(add), frozenset(dele), cost))
        if kind in ("loot", "collect"):
            goalset = {("holding", X)}
            for i, p in enumerate(self.potions):
                nodes[f"p{i}"], kinds[f"p{i}"] = p, "cell"
                init.add(("potion_at", f"p{i}"))
                op("pickup", (f"p{i}",), {("at", X, f"p{i}"), ("potion_at", f"p{i}")}, {("holding", X)}, {("potion_at", f"p{i}")}, 1)
            for a in inf.query("can", X, "steal", None):
                y = self.npcs[a[3]]
                if y.alive and y.pot > 0:
                    nodes[y.name], kinds[y.name] = y.pos, "entity"
                    init.add(("holds", y.name))
                    op("steal", (y.name,), {("at", X, y.name), ("holds", y.name)}, {("holding", X)}, {("holds", y.name)}, STEAL_COST)
        elif kind == "tribute":
            y = self.npcs[tgt]
            nodes[tgt], kinds[tgt] = y.pos, "entity"
            init.add(("holding", X))
            goalset = {("gifted", tgt)}
            op("give", (tgt,), {("at", X, tgt), ("holding", X)}, {("gifted", tgt)}, {("holding", X)}, 1)
        elif kind == "hunt":
            y = self.npcs[tgt]
            nodes[tgt], kinds[tgt] = y.pos, "entity"
            init.add(("alive", tgt))
            goalset = {("devoured", tgt)}
            op("devour", (tgt,), {("at", X, tgt), ("alive", tgt)}, {("devoured", tgt)}, {("alive", tgt)}, 1)
        elif kind == "shelter":
            nodes["hide"], kinds["hide"] = self.hide_cell(me, self.npcs[tgt]), "cell"
            goalset = {("at", X, "hide")}
        arrived = [n for n in nodes if n != "me" and (nodes[n] == me.pos if kinds[n] == "cell" else manh(nodes[n], me.pos) <= 1)]
        init.add(("at", X, arrived[0] if arrived else "me"))
        for a in nodes:
            for b in nodes:
                if a != b and b != "me":
                    c = self.dist(nodes[a]).get(nodes[b])
                    if c is not None:
                        op("move", (a, b), {("at", X, a)}, {("at", X, b)}, {("at", X, a)}, c)
        results = {k: run_plan(init, goalset, ops, k) for k in PLAN_ALGOS}
        res = results[self.algo]
        line, cur = [me.pos], None
        for o in res["plan"]:
            if o.name == "move":
                line.append(nodes[o.args[1]])
        return dict(goal=(kind, tgt), nodes=nodes, kinds=kinds, results=results, res=res, line=line,
                    labels=[op_label(o) for o in res["plan"]])

    def goal_of(self, inf, me):
        gs = inf.query("goal", me.name, None, None)
        return max(gs, key=lambda a: inf.prio(a)) if gs else None

    # ------------------------------------------------------------------ eksekusi aksi
    def hurt(self, y, dmg, why):
        y.hp -= dmg
        if y.name == "naga":
            y.hp = max(NAGA_MIN_HP, y.hp)
        elif y.hp <= 0:
            y.hp, y.alive, y.respawn_in = 0, False, RESPAWN
            if y.pot > 0:
                self.potions.append(y.pos)
                y.pot = 0
            self.stats["kills"] += 1
            self.say(f"{NAMES[y.name]} tewas ({why}).")

    def valid(self, x, act, y):
        t = None if y == x.name else self.npcs[y]
        if t and not t.alive:
            return False
        d = manh(x.pos, t.pos) if t else 0
        return {"attack": d <= 1, "steal": d <= 1 and t and t.pot > 0, "gift": d <= 1 and x.pot > 0,
                "devour": d <= 1 and x.hungry, "cast": d <= RANGE_SPELL, "drink": x.pot > 0 and x.hp < x.maxhp,
                "flee": t is not None}.get(act, False)

    def do(self, x, act, y):
        t, nx, ny = (None if y == x.name else self.npcs[y]), NAMES[x.name], NAMES.get(y, y)
        roll = lambda p: self.rng.random() * 100 < p
        self.stats[act] = self.stats.get(act, 0) + 1
        if act in ("attack", "cast"):
            d, h = x.melee if act == "attack" else x.spell
            if roll(h):
                self.hurt(t, d, nx)
                self.say(f"{nx} {act} {ny}: -{d} HP ({t.hp}/{t.maxhp}).")
            else:
                self.say(f"{nx} {act} {ny}: meleset.")
        elif act == "devour":
            if roll(decision.DEVOUR_HIT):
                self.hurt(t, 999, nx)
                x.hunger, x.hp = 0, min(x.maxhp, x.hp + decision.HEAL_DEVOUR)
                self.say(f"{nx} memangsa {ny}!")
            else:
                self.say(f"{nx} gagal menerkam {ny}.")
        elif act == "steal":
            if roll(x.steal_p):
                x.pot, t.pot = x.pot + 1, t.pot - 1
                self.say(f"{nx} berhasil mencuri ramuan {ny}!")
            else:
                self.stats["steal_fail"] += 1
                self.hurt(x, decision.STEAL_FAIL_DMG, ny)
                self.say(f"{nx} ketahuan {ny} saat mencuri (-{decision.STEAL_FAIL_DMG} HP).")
        elif act == "gift":
            x.pot -= 1
            t.hp = min(t.maxhp, t.hp + decision.HEAL)
            if t.hungry:
                t.hunger = 0
            self.say(f"{nx} memberi upeti ramuan ke {ny} (+{decision.HEAL} HP, lapar reda).")
        elif act == "drink":
            x.pot -= 1
            x.hp = min(x.maxhp, x.hp + decision.HEAL)
            self.say(f"{nx} meminum ramuan (+{decision.HEAL} HP).")
        elif act == "flee":
            if roll(x.flee_p):
                opts = [n for n, _ in self.grid.neighbors(x.pos) if not self.occupied(n, x.name)]
                if opts:
                    best = max(opts, key=lambda c: (manh(c, t.pos), -self.grid.cost(c)))
                    if manh(best, t.pos) > manh(x.pos, t.pos):
                        x.pos = best
                        self.say(f"{nx} kabur dari {ny}.")
                        return
            self.say(f"{nx} gagal kabur dari {ny}.")

    def step_to(self, x, target, entity=False):
        if (entity and manh(x.pos, target) <= 1) or x.pos == target:
            return
        path = self.path_fn(x.pos, target)["path"]
        if path and len(path) > 1 and not self.occupied(path[1], x.name):
            x.pos = path[1]

    def follow(self, x, pl, chase_next):
        if pl and pl["res"]["found"] and pl["res"]["plan"]:
            o = pl["res"]["plan"][0]
            if o.name == "move":
                if self.tick % x.speed == 0:
                    dest = o.args[1]
                    self.step_to(x, pl["nodes"][dest], pl["kinds"][dest] == "entity")
            elif o.name == "pickup":
                p = pl["nodes"][o.args[0]]
                if p == x.pos and p in self.potions and x.pot < POTION_CAP:
                    self.potions.remove(p)
                    x.pot += 1
                    self.stats["pickup"] += 1
                    self.say(f"{NAMES[x.name]} mengambil ramuan.")
            return
        if x.name == "naga" and chase_next and not self.occupied(chase_next, "naga"):
            x.pos = chase_next

    # ------------------------------------------------------------------ satu giliran dunia
    def step(self, knight, chase_next=None):
        self.tick += 1
        self.knight = knight
        for n in self.npcs.values():
            if not n.alive:
                n.respawn_in -= 1
                if n.respawn_in <= 0 and not self.occupied(n.home):
                    n.alive, n.hp, n.pos, n.pot = True, n.maxhp, n.home, 1 if n.name == "mage" else 0
                    self.say(f"{NAMES[n.name]} muncul kembali.")
        self.npcs["naga"].hunger += 1
        dyn = self.facts()
        inf = self.kb.infer(dyn)
        dec, plans = {}, {}
        for n in self.ORDER:
            x = self.npcs[n]
            if x.alive:
                dec[n] = self.decide(inf, x)
                g = self.goal_of(inf, x)
                plans[n] = self.build_plan(inf, x, g) if g else None
        self.last = dict(inf=inf, dec=dec, plans=plans, facts=dyn, tick=self.tick)
        for n in self.ORDER:
            x = self.npcs[n]
            if not x.alive:
                continue
            ch = next((r for r in dec[n] if r.get("chosen")), None)
            if ch and ch["act"] != "continue" and self.valid(x, ch["act"], ch["tgt"] or x.name):
                self.do(x, ch["act"], ch["tgt"] or x.name)
            else:
                self.follow(x, plans.get(n), chase_next if n == "naga" else None)
        return self.observe()        # tampilan = persepsi/niat NPC pada keadaan SETELAH bergerak (konsisten dengan layar)

    def observe(self, knight=None):
        """Inferensi tanpa menggerakkan dunia (untuk tampilan awal setelah reset)."""
        self.knight = knight or self.knight
        dyn = self.facts()
        inf = self.kb.infer(dyn)
        dec, plans = {}, {}
        for n in self.ORDER:
            x = self.npcs[n]
            if x.alive:
                dec[n] = self.decide(inf, x)
                g = self.goal_of(inf, x)
                plans[n] = self.build_plan(inf, x, g) if g else None
        self.last = dict(inf=inf, dec=dec, plans=plans, facts=dyn, tick=self.tick)
        return self.last

    # ------------------------------------------------------------------ MDP untuk tampilan
    def pair_mdp(self, a, b):
        x, y = self.npcs[a], self.npcs[b]
        st = max((s for s in (x.melee, x.spell) if s), key=lambda s: s[0] * s[1])
        rt = max((s for s in (y.melee, y.spell) if s), key=lambda s: s[0] * s[1])
        w = x.caution / 50
        m = decision.combat_mdp(max(1, round(5 * st[0] / y.maxhp)), st[1] / 100, max(1, round(5 * rt[0] / x.maxhp)),
                                rt[1] / 100, x.flee_p / 100, -100 * w, self.gamma)
        cur = (decision.bucket(x.hp, x.maxhp), decision.bucket(y.hp, y.maxhp)) if x.alive and y.alive else None
        return dict(m, cur=cur)
