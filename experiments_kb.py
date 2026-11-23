"""Eksperimen headless: basis pengetahuan (KB) + automated planning (STRIPS).

Tanpa browser: engine KB dimuat dari kb.txt, planner dari planner.py.
Jalankan:  python3 experiments_kb.py

Menyimpan hasil ke hasil_kb.json. Dipakai untuk tabel ablations pada Laporan Tahap 4.
"""
import pathlib
import sys
import time
import random
import json
import math
import re
import heapq
import itertools
from collections import namedtuple, defaultdict

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
src = (here / "main.py").read_text()
exec(src.split("# ==== CORE BEGIN ====")[1].split("# ==== CORE END ====")[0], globals())
exec(src.split("# ==== CSP ENGINE BEGIN ====")[1].split("# ==== CSP ENGINE END ====")[0], globals())
from kb_engine import KB, fmt
from planner import Op, plan, HEURISTICS as PLAN_ALGOS

out = {}
kb = KB.from_file(str(here / "kb.txt"))
grid = GridMap(MAP_DATA)

# ---------------------------------------------------------------- 1. Baseline KB
print("=" * 72)
print("1. BASELINE KNOWLEDGE BASE")
print("=" * 72)
static_facts = list(kb.static)
out["baseline"] = dict(aturan=len(kb.rules), fakta_statis=len(kb.static))
print(f"  aturan={len(kb.rules)}  fakta statis={len(kb.static)}")
print("  kategori aturan:")
kat = defaultdict(list)
for r in kb.rules:
    m = re.match(r"^([A-Za-z]+)", r.id)
    pre = m.group(1) if m else r.id
    kat[pre].append(r.id)
for k, v in sorted(kat.items()):
    print(f"    {k:<6} ({len(v):>2}): {', '.join(v)}")
out["baseline"]["kategori"] = {k: v for k, v in kat.items()}

# ---------------------------------------------------------------- 2. Skala inferensi
print()
print("=" * 72)
print("2. SKALA INFERENSI: pertumbuhan fakta dinamis")
print("=" * 72)
names = ["naga", "goblin", "mage"]
# Bangun daftar fakta dinamis terurut dari yang paling sederhana ke paling kompleks,
# agar penambahan fakta menaikkanderived fact secara bertahap.
pool = []
for nm in names:
    pool.append(("alive", nm))
for nm in names:
    pool.append(("hp_level", nm, "mid"))
for nm in names:
    for o in names:
        if nm != o:
            pool.append(("near", nm, o))
for nm in names:
    for o in names:
        if nm != o:
            pool.append(("in_range", nm, o))
for nm in names:
    for o in names:
        if nm != o:
            pool.append(("adjacent", nm, o))
rows = []
for n_dyn in [0, 3, 6, 9, 12, 15, 18, 21, 24, 27]:
    dyn = pool[:n_dyn]
    t0 = time.perf_counter()
    inf = kb.infer(dyn)
    ms = (time.perf_counter() - t0) * 1000
    st = inf.stats()
    rows.append(dict(fakta_dinamis=len(dyn), fakta=st["facts"], turunan=st["derived"],
                     turunan_dinamis=st["derived_dyn"], ronde=st["rounds"], ms=round(ms, 3)))
    print(f"  dinamis={len(dyn):>3}  fakta={st['facts']:>3}  turunan={st['derived']:>3} "
          f"(dinamis {st['derived_dyn']:>2})  ronde={st['rounds']}  {ms:7.3f} ms")
out["skala_inferensi"] = rows

# ---------------------------------------------------------------- 3. Ablations aturan
print()
print("=" * 72)
print("3. ABLATIONS ATURAN:目标任务 yang hilang bila kelompok aturan dihapus")
print("=" * 72)
out["ablations"] = {}
GROUPS = {
    "tanpa R1-R6 (relasi turunan)": lambda r: r.id.startswith(("R1", "R2", "R3", "R4", "R5", "R6")) and not r.id.startswith(("R7", "R8")),
    "tanpa R7-R8 (ancaman)": lambda r: r.id.startswith(("R7", "R8")),
    "tanpa C1-C3 (kemampuan)": lambda r: r.id.startswith("C"),
    "tanpa A1-A9 (aksi)": lambda r: r.id.startswith("A"),
    "tanpa G1-G5 (tujuan)": lambda r: r.id.startswith("G"),
}
dyn = [("alive", n) for n in names] + [("hp_level", n, "mid") for n in names]
for n in names:
    for o in names:
        if n != o:
            dyn += [("near", n, o), ("in_range", n, o)]
            if n == "goblin" and o == "mage":
                dyn += [("adjacent", n, o)]
for label, pred in GROUPS.items():
    # bangun KB baru dengan aturan yang disaring
    k = KB("")
    k.static = set(kb.static)
    k.rules = [r for r in kb.rules if not pred(r)]
    inf = k.infer(dyn)
    st = inf.stats()
    out["ablations"][label] = dict(aturan_tersisa=len(k.rules), fakta=st["facts"], turunan=st["derived"],
                                   ronde=st["rounds"], ms=round(st["ms"], 3))
    print(f"  {label:<32} aturan={len(k.rules):>2}  fakta={st['facts']:>3}  "
          f"turunan={st['derived']:>3}  ronde={st['rounds']}  {st['ms']:6.3f} ms")

# ---------------------------------------------------------------- 4. Prioritas konflik
print()
print("=" * 72)
print("4. RESOLUSI KONFLIK: prioritas antar aturan (p=) pada aksi yang sama")
print("=" * 72)
out["konflik"] = {}
for nm in names:
    inf = kb.infer(dyn)
    acts = inf.query("act", nm, None, None)
    rows = []
    for a in sorted(acts, key=lambda x: -inf.prio(x)):
        rows.append(dict(aksi=fmt(a), aturan=inf.rule_ids(a), prioritas=inf.prio(a)))
    out["konflik"][nm] = rows
    print(f"  {nm}:")
    for r in rows:
        print(f"    {r['aksi']:<28} p={r['prioritas']:<3} aturan={', '.join(r['aturan'])}")

# ---------------------------------------------------------------- 5. Jejak penurunan
print()
print("=" * 72)
print("5. JEJAK PENURUNAN (explain) untuk satu fakta turunan")
print("=" * 72)
inf = kb.infer(dyn)
sample = None
for a in inf.query("act", "goblin", None, None):
    sample = a
    break
if sample:
    trace = inf.explain(sample)
    out["jejak_penurunan"] = trace
    for line in trace:
        print("  " + line)

# ---------------------------------------------------------------- 6. Perbandingan planner
print()
print("=" * 72)
print("6. AUTOMATED PLANNING: UCS vs A* goal-count vs A* h_max")
print("=" * 72)
out["planner"] = {}
N_PLAN = 200
agg = {a: dict(n=0, found=0, expanded=0, cost=0, ms=0.0) for a in PLAN_ALGOS}
rng = random.Random(11)
for i in range(N_PLAN):
    potions = [(rng.randrange(2, 18), rng.randrange(2, 17)) for _ in range(3)]
    nodes = {"me": (1, 1), "p0": potions[0], "p1": potions[1], "p2": potions[2]}
    kinds = {k: "cell" for k in nodes}
    init = {("potion_at", f"p{j}") for j in range(3)}
    ops = []
    for j in range(3):
        ops.append(Op("pickup", (f"p{j}",), frozenset({("at", "me", f"p{j}"), ("potion_at", f"p{j}")}),
                      frozenset({("holding", "me")}), frozenset({("potion_at", f"p{j}")}), 1))
    # cost antar node memakai jarak Manhattan (proxy biaya lintasan)
    def dc(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])
    ops = []
    for j in range(3):
        ops.append(Op("pickup", (f"p{j}",), frozenset({("at", "me", f"p{j}"), ("potion_at", f"p{j}")}),
                      frozenset({("holding", "me")}), frozenset({("potion_at", f"p{j}")}), 1))
    for a in nodes:
        for b in nodes:
            if a != b and b != "me":
                ops.append(Op("move", (a, b), frozenset({("at", "me", a)}), frozenset({("at", "me", b)}),
                              frozenset({("at", "me", a)}), dc(nodes[a], nodes[b])))
    init.add(("at", "me", "me"))
    goals = {("holding", "me")}
    for algo in PLAN_ALGOS:
        r = plan(init, goals, ops, algo)
        d = agg[algo]
        d["n"] += 1
        d["found"] += 1 if r["found"] else 0
        d["expanded"] += r["expanded"]
        d["cost"] += r["cost"]
        d["ms"] += r["ms"]
for a, d in agg.items():
    n = max(1, d["n"])
    out["planner"][a] = dict(masalah=d["n"], ditemukan=d["found"],
                             node_rata2=round(d["expanded"] / n, 2),
                             biaya_rata2=round(d["cost"] / n, 2),
                             ms_rata2=round(d["ms"] / n, 4))
    print(f"  {a:<18} masalah={d['n']}  ditemukan={d['found']}  node_rata2={d['expanded']/n:>6.2f}  "
          f"biaya_rata2={d['cost']/n:>6.2f}  ms_rata2={d['ms']/n:>8.4f}")

# ---------------------------------------------------------------- 7. Goal planning nyata
print()
print("=" * 72)
print("7. RENCANA REAL dari KB: goal -> urutan aksi STRIPS")
print("=" * 72)
out["rencana"] = {}
inf = kb.infer(dyn)
for nm in names:
    goals = inf.query("goal", nm, None, None)
    out["rencana"][nm] = [fmt(g) for g in goals]
    print(f"  {nm}: {[fmt(g) for g in goals] or 'tidak ada tujuan dari KB'}")

json.dump(out, open(here / "hasil_kb.json", "w"), indent=1)
print()
print("Tersimpan:", here / "hasil_kb.json")
