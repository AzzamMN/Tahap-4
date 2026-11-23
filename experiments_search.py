"""Eksperimen headless: pathfinding (UCS / A*) + generator level (CSP + local search).

Tanpa browser: bagian CORE dan CSP ENGINE dari main.py di-exec langsung.
Jalankan:  python3 experiments_search.py

Menyimpan hasil ke hasil_search.json dan mencetak ringkasan yang dipakai di Laporan Tahap 4.
"""
import pathlib
import sys
import time
import math
import heapq
import itertools
import random
import json
from collections import deque

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
src = (here / "main.py").read_text()
exec(src.split("# ==== CORE BEGIN ====")[1].split("# ==== CORE END ====")[0], globals())
exec(src.split("# ==== CSP ENGINE BEGIN ====")[1].split("# ==== CSP ENGINE END ====")[0], globals())

N_SEED = 60
out = {}

# ---------------------------------------------------------------- 1. Pathfinding
print("=" * 72)
print(f"1. PATHFINDING  (UCS vs A* Manhattan vs A* Euclidean, {N_SEED} seed)")
print("=" * 72)
grid = GridMap(MAP_DATA)
algos = ["ucs", "astar_manhattan", "astar_euclidean"]
HEUR = {"ucs": h_zero, "astar_manhattan": h_manhattan, "astar_euclidean": h_euclidean}
agg = {a: dict(node=0, cost=0, ms=0.0, found=0, trials=0) for a in algos}
for seed in range(N_SEED):
    rng = random.Random(seed)
    lv = LevelCSP(grid, seed).generate("hybrid")
    if not lv:
        continue
    K, D = lv["K"], lv["D"]
    for a in algos:
        t0 = time.perf_counter()
        r = Pathfinding.search(grid, K, D, HEUR[a])
        ms = (time.perf_counter() - t0) * 1000
        d = agg[a]
        d["node"] += r["expanded"]
        d["cost"] += r["cost"]
        d["ms"] += ms
        d["found"] += 1 if r["path"] else 0
        d["trials"] += 1
out["pathfinding"] = {}
print(f"  {'algoritma':<20} {'node rata2':>12} {'cost rata2':>12} {'ms rata2':>10} {'ditemukan':>10}")
for a in algos:
    d = agg[a]
    n = max(1, d["trials"])
    out["pathfinding"][a] = dict(node_rata2=round(d["node"] / n, 1), cost_rata2=round(d["cost"] / n, 1),
                                 ms_rata2=round(d["ms"] / n, 3), ditemukan=f'{d["found"]}/{d["trials"]}')
    print(f"  {a:<20} {d['node']/n:>12.1f} {d['cost']/n:>12.1f} {d['ms']/n:>10.3f} "
          f"{str(d['found'])+'/'+str(d['trials']):>10}")

# Penghematan A* terhadap UCS
uc = out["pathfinding"]["ucs"]
for a in ["astar_manhattan", "astar_euclidean"]:
    p = out["pathfinding"][a]
    out["pathfinding"][a]["hemat_node_vs_ucs_persen"] = round((1 - p["node_rata2"] / uc["node_rata2"]) * 100, 1)
    print(f"  hemat node {a} vs UCS: {out['pathfinding'][a]['hemat_node_vs_ucs_persen']}%")

# ---------------------------------------------------------------- 2. Generator level
print()
print("=" * 72)
print(f"2. GENERATOR LEVEL  (CSP / local search / hybrid, {N_SEED} seed)")
print("=" * 72)
out["generator"] = {}
for mode in ["csp", "ls", "hybrid"]:
    rows = []
    for seed in range(N_SEED):
        t0 = time.perf_counter()
        lv = LevelCSP(grid, seed).generate(mode)
        ms = (time.perf_counter() - t0) * 1000
        if not lv:
            rows.append(None)
            continue
        rows.append(dict(seed=seed, score=lv["score"], route=lv["route"], ms=ms,
                         assign=lv["stats"]["assign"], backtracks=lv["stats"]["backtracks"],
                         revisions=lv["stats"]["revisions"], ls_steps=lv["stats"]["ls_steps"],
                         dom_before=lv["stats"]["dom_before"], dom_after=lv["stats"]["dom_after"]))
    ok = [r for r in rows if r]
    if not ok:
        continue
    n = len(ok)
    out["generator"][mode] = dict(
        berhasil=f"{n}/{N_SEED}",
        skor_rata2=round(sum(r["score"] for r in ok) / n, 2),
        skor_terbaik=round(max(r["score"] for r in ok), 2),
        rute_rata2=round(sum(r["route"] for r in ok) / n, 1),
        ms_rata2=round(sum(r["ms"] for r in ok) / n, 2),
        assign_rata2=round(sum(r["assign"] for r in ok) / n, 1),
        backtrack_rata2=round(sum(r["backtracks"] for r in ok) / n, 1),
        revisi_ac3_rata2=round(sum(r["revisions"] for r in ok) / n, 1),
        langkah_ls_rata2=round(sum(r["ls_steps"] for r in ok) / n, 1),
        domain_before_rata2=round(sum(r["dom_before"] for r in ok) / n, 1),
        domain_after_rata2=round(sum(r["dom_after"] for r in ok) / n, 1))
    g = out["generator"][mode]
    print(f"  mode={mode:<7} berhasil={g['berhasil']:<8} skor_rata2={g['skor_rata2']:>7} "
          f"rute_rata2={g['rute_rata2']:>6} ms_rata2={g['ms_rata2']:>8}")
    print(f"            assign={g['assign_rata2']}  backtrack={g['backtrack_rata2']}  "
          f"revisi_ac3={g['revisi_ac3_rata2']}  langkah_ls={g['langkah_ls_rata2']}")

# Dampak AC-3 dan MRV/LCV pada generator CSP
print()
print("  Dampak komponen CSP (mode=csp, 30 seed):")
out["dampak_csp"] = {}
for label, kw in [("lengkap (MRV+LCV+AC3)", dict(mrv=True, lcv=True, ac3=True)),
                  ("tanpa AC-3", dict(mrv=True, lcv=True, ac3=False)),
                  ("tanpa MRV", dict(mrv=False, lcv=True, ac3=True)),
                  ("tanpa LCV", dict(mrv=True, lcv=False, ac3=True))]:
    rows = []
    for seed in range(30):
        t0 = time.perf_counter()
        lv = LevelCSP(grid, seed, **kw).generate("csp")
        ms = (time.perf_counter() - t0) * 1000
        if lv:
            rows.append(dict(ms=ms, assign=lv["stats"]["assign"], backtracks=lv["stats"]["backtracks"],
                             dom_before=lv["stats"]["dom_before"], dom_after=lv["stats"]["dom_after"]))
    n = max(1, len(rows))
    d = dict(berhasil=f"{len(rows)}/30",
             ms_rata2=round(sum(r["ms"] for r in rows) / n, 2),
             assign_rata2=round(sum(r["assign"] for r in rows) / n, 1),
             backtrack_rata2=round(sum(r["backtracks"] for r in rows) / n, 1),
             domain_after_rata2=round(sum(r["dom_after"] for r in rows) / n, 1))
    out["dampak_csp"][label] = d
    print(f"    {label:<22} berhasil={d['berhasil']:<6} ms={d['ms_rata2']:>8} "
          f"assign={d['assign_rata2']:>6} backtrack={d['backtrack_rata2']:>6} "
          f"domain_after={d['domain_after_rata2']:>8}")

json.dump(out, open(here / "hasil_search.json", "w"), indent=1)
print()
print("Tersimpan:", here / "hasil_search.json")
