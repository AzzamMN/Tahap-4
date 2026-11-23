"""Mesin inferensi KB: forward chaining (klausa Horn + variabel), ronde sinkron, dengan jejak penurunan.
Terpisah dari game: KB.from_file("kb.txt").infer(fakta_dinamis) -> Inference (ronde, penjelasan, query)."""
import re
import time
from collections import defaultdict

BUILTINS = {"neq"}


def is_var(t):
    return isinstance(t, str) and (t[0].isupper() or t[0] == "_")


def parse_atom(s):
    m = re.fullmatch(r"\s*([a-z_]\w*)\s*\(([^()]*)\)\s*", s)
    if not m:
        raise ValueError(f"atom tidak valid: {s!r}")
    args = []
    for t in m.group(2).split(","):
        t = t.strip()
        args.append(int(t) if re.fullmatch(r"-?\d+", t) else t)
    return (m.group(1),) + tuple(args)


def fmt(atom):
    return f"{atom[0]}({','.join(str(a) for a in atom[1:])})"


class Rule:
    def __init__(self, rid, prio, head, body, text):
        self.id, self.prio, self.head, self.text = rid, prio, head, text
        self.body = [l for l in body if l[0] not in BUILTINS] + [l for l in body if l[0] in BUILTINS]  # builtin di akhir


class Rec:
    """Catatan penurunan satu fakta."""
    __slots__ = ("rule", "premises", "round", "dyn")

    def __init__(self, rule, premises, rnd, dyn):
        self.rule, self.premises, self.round, self.dyn = rule, premises, rnd, dyn


def _match(lit, fact, subst):
    if len(lit) != len(fact):
        return None
    s = dict(subst)
    for t, v in zip(lit[1:], fact[1:]):
        if is_var(t):
            cur = s.get(t)
            if cur is None:
                s[t] = v
            elif cur != v:
                return None
        elif t != v:
            return None
    return s


def _ground(lit, s):
    return (lit[0],) + tuple(s[t] if is_var(t) else t for t in lit[1:])


class KB:
    def __init__(self, text):
        self.static, self.rules = set(), []
        body = re.sub(r"#[^\n]*", "", text)
        for stmt in re.split(r"\.(?=\s|$)", body):
            stmt = stmt.strip()
            if not stmt:
                continue
            m = re.match(r"\[(\w+)(?:\s+p=(\d+))?\]\s*(?:p=(\d+)\s*)?(.*)$", stmt, re.S)
            if m:
                rid, p1, p2, rest = m.group(1), m.group(2), m.group(3), m.group(4)
                head, body_s = rest.split(":-")
                lits = [parse_atom(x) for x in re.findall(r"[a-z_]\w*\s*\([^()]*\)", body_s)]
                text_r = " ".join(f"{head.strip()} :- {', '.join(fmt(l) for l in lits)}".split())
                self.rules.append(Rule(rid, int(p1 or p2 or 0), parse_atom(head), lits, text_r))
            else:
                self.static.add(parse_atom(stmt))

    @classmethod
    def from_file(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(f.read())

    def static_query(self, pred, *args):
        return [a for a in self.static if a[0] == pred and _fits(a, args)]

    # ---- join body ----
    def _join(self, body, i, subst, prem, idx):
        if i == len(body):
            yield subst, prem
            return
        lit = body[i]
        if lit[0] == "neq":
            a, b = (subst[t] if is_var(t) else t for t in lit[1:3])
            if a != b:
                yield from self._join(body, i + 1, subst, prem, idx)
            return
        for fact in idx.get(lit[0], ()):
            s = _match(lit, fact, subst)
            if s is not None:
                yield from self._join(body, i + 1, s, prem + [fact], idx)

    def infer(self, dynamic=()):
        t0 = time.perf_counter()
        facts, idx = {}, defaultdict(list)
        for a in self.static:
            facts[a] = Rec(None, (), 0, False)
            idx[a[0]].append(a)
        for a in dynamic:
            if a not in facts:
                facts[a] = Rec(None, (), 0, True)
                idx[a[0]].append(a)
        rounds, r = [], 0
        while True:                                   # ronde sinkron: hanya memakai fakta awal ronde
            r += 1
            new = {}
            for rule in self.rules:
                for s, prem in self._join(rule.body, 0, {}, [], idx):
                    h = _ground(rule.head, s)
                    if h not in facts and h not in new:
                        new[h] = Rec(rule, tuple(prem), r, any(facts[p].dyn for p in prem))
            if not new:
                break
            for a, rec in new.items():
                facts[a] = rec
                idx[a[0]].append(a)
            rounds.append(list(new))
        support, firings = defaultdict(list), 0        # semua dukungan (aturan lain) untuk resolusi konflik
        for rule in self.rules:
            for s, prem in self._join(rule.body, 0, {}, [], idx):
                support[_ground(rule.head, s)].append((rule, tuple(prem)))
                firings += 1
        return Inference(facts, rounds, support, firings, (time.perf_counter() - t0) * 1000, idx)


def _fits(atom, args):
    return len(atom) == len(args) + 1 and all(a is None or a == b for a, b in zip(args, atom[1:]))


class Inference:
    def __init__(self, facts, rounds, support, firings, ms, idx):
        self.facts, self.rounds, self.support, self.firings, self.ms, self._idx = facts, rounds, support, firings, ms, idx

    def query(self, pred, *args):
        return [a for a in self._idx.get(pred, ()) if _fits(a, args)]

    def holds(self, atom):
        return atom in self.facts

    def prio(self, atom):
        return max((r.prio for r, _ in self.support.get(atom, ())), default=0)

    def rule_ids(self, atom):
        return [r.id for r, _ in sorted(self.support.get(atom, ()), key=lambda t: -t[0].prio)]

    def explain(self, atom, depth=4, _lvl=0):
        rec = self.facts[atom]
        tag = "[fakta" + (" dinamis]" if rec.dyn else "]") if rec.rule is None else f"<= {rec.rule.id}" + (f" p={rec.rule.prio}" if rec.rule.prio else "")
        lines = ["  " * _lvl + f"{fmt(atom)}  {tag}"]
        if rec.rule is not None:
            if _lvl >= depth:
                lines[0] += "  ..."
            else:
                for p in rec.premises:
                    lines += self.explain(p, depth, _lvl + 1)
        return lines

    def stats(self):
        n_dyn = sum(1 for r in self.facts.values() if r.rule is not None and r.dyn)
        return {"facts": len(self.facts), "derived": sum(len(x) for x in self.rounds), "derived_dyn": n_dyn,
                "rounds": len(self.rounds), "firings": self.firings, "ms": self.ms}
