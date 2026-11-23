"""Eksperimen headless: battle engine turn-based (minimax / alpha-beta / expectimax).

Tanpa browser: bagian CORE dan BATTLE ENGINE dari main.py di-exec langsung.
Jalankan:  python3 experiments_battle.py

Menyimpan hasil ke hasil_battle.json dan mencetak ringkasan yang dipakai di Laporan Tahap 4.
"""
import pathlib
import sys
import time
import random
import json
import math
import heapq
import itertools
from collections import namedtuple

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
src = (here / "main.py").read_text()
exec(src.split("# ==== CORE BEGIN ====")[1].split("# ==== CORE END ====")[0], globals())
exec(src.split("# ==== BATTLE ENGINE BEGIN ====")[1].split("# ==== BATTLE ENGINE END ====")[0], globals())

TRIALS = 300
DEPTHS = [2, 4, 6, 8]
out = {"konfigurasi": {"trials": TRIALS, "depths": DEPTHS,
                       "hp": MAX_HP, "atk": ATK_DMG, "heal": HEAL, "potion_awal": START_POTIONS}}

# ---------------------------------------------------------------- 1. Benchmark search
print("=" * 72)
print("1. BENCHMARK SEARCH  (root = giliran NPC / MAX, eval = balanced)")
print("=" * 72)
st = new_battle()._replace(turn="N")
out["benchmark"] = {}
for algo in ["minimax", "alphabeta", "expectimax"]:
    out["benchmark"][algo] = {}
    for d in DEPTHS:
        t0 = time.perf_counter()
        r = search(st, d, algo=algo, eval_name="balanced")
        ms = (time.perf_counter() - t0) * 1000
        out["benchmark"][algo][str(d)] = dict(node=r["nodes"], cutoffs=r["cutoffs"],
                                             ms=round(ms, 3), aksi=r["action"])
        print(f"  {algo:<11} depth={d}  node={r['nodes']:>7}  cutoff={r['cutoffs']:>6}  "
              f"{ms:9.3f} ms  aksi={r['action']}")

# ---------------------------------------------------------------- 2. Alpha-beta vs minimax
print()
print("=" * 72)
print("2. KONSISTENSI: apakah alpha-beta memilih aksi yang sama dengan minimax?")
print("=" * 72)
out["konsistensi"] = {}
for d in DEPTHS:
    a = search(st, d, algo="minimax", eval_name="balanced")["action"]
    b = search(st, d, algo="alphabeta", eval_name="balanced")["action"]
    same = a == b
    out["konsistensi"][str(d)] = dict(minimax=a, alphabeta=b, sama=same)
    print(f"  depth={d}  minimax={a:<8} alphabeta={b:<8} sama={same}")

# ---------------------------------------------------------------- 3. Efektivitas pruning
print()
print("=" * 72)
print("3. HEMAT NODE oleh alpha-beta (node minimax sebagai baseline)")
print("=" * 72)
out["hemat_node"] = {}
for d in DEPTHS:
    n_min = out["benchmark"]["minimax"][str(d)]["node"]
    n_ab = out["benchmark"]["alphabeta"][str(d)]["node"]
    pct = (1 - n_ab / n_min) * 100 if n_min else 0.0
    out["hemat_node"][str(d)] = dict(minimax=n_min, alphabeta=n_ab, persen_hemat=round(pct, 1))
    print(f"  depth={d}  minimax={n_min:>7}  alphabeta={n_ab:>7}  hemat={pct:5.1f}%")

# ---------------------------------------------------------------- 4. Win rate
print()
print("=" * 72)
print(f"4. WIN RATE: player acak vs NPC alpha-beta (depth=4, {TRIALS} trial)")
print("=" * 72)
wins = {"player": 0, "naga": 0, "draw": 0}
turns = []
random.seed(7)
for _ in range(TRIALS):
    stt = new_battle()
    n_turn = 0
    for _ in range(120):
        if is_terminal(stt):
            break
        if stt.turn == "P":
            acts = legal_actions(stt)
            if not acts:
                break
            act = random.choice(acts)
        else:
            act = search(stt, 4, algo="alphabeta", eval_name="balanced")["action"]
        stt = apply_action(stt, act)
        n_turn += 1
    turns.append(n_turn)
    if stt.nhp <= 0:
        wins["player"] += 1
    elif stt.php <= 0:
        wins["naga"] += 1
    else:
        wins["draw"] += 1
out["win_rate"] = dict(player=wins["player"], naga=wins["naga"], draw=wins["draw"],
                       giliran_rata2=round(sum(turns) / len(turns), 1))
print(f"  player menang={wins['player']}  naga menang={wins['naga']}  draw={wins['draw']}  "
      f"(rata-rata {sum(turns)/len(turns):.1f} giliran)")

# ---------------------------------------------------------------- 5. Early stop
print()
print("=" * 72)
print("5. EARLY STOP: budget node (alpha-beta, depth=8)")
print("=" * 72)
out["early_stop"] = {}
for lim in [25, 100, 250, 1000, None]:
    r = search(st, 8, algo="alphabeta", eval_name="balanced", node_limit=lim)
    key = str(lim)
    out["early_stop"][key] = dict(node=r["nodes"], stopped=r["stopped"], aksi=r["action"])
    print(f"  budget={str(lim):>5}  node={r['nodes']:>6}  early_stop={str(r['stopped']):<5} aksi={r['action']}")

# ---------------------------------------------------------------- 6. Fungsi evaluasi
print()
print("=" * 72)
print("6. PENGARUH FUNGSI EVALUASI (alpha-beta, depth=4)")
print("=" * 72)
out["fungsi_eval"] = {}
for ev in ["zero", "hp", "balanced", "aggressive", "defensive"]:
    r = search(st, 4, algo="alphabeta", eval_name=ev)
    out["fungsi_eval"][ev] = dict(aksi=r["action"], nilai=round(r["value"], 2), node=r["nodes"])
    print(f"  eval={ev:<11} aksi={r['action']:<8} nilai={r['value']:>8.2f}  node={r['nodes']}")

# ---------------------------------------------------------------- 7. Kedalaman vs kualitas
print()
print("=" * 72)
print("7. KEDALAMAN vs KUALITAS (alpha-beta, semua fungsi eval)")
print("=" * 72)
out["kedalaman_kualitas"] = {}
for ev in ["zero", "balanced", "defensive"]:
    row = {}
    for d in DEPTHS:
        r = search(st, d, algo="alphabeta", eval_name=ev)
        row[str(d)] = dict(aksi=r["action"], node=r["nodes"], nilai=round(r["value"], 2))
    out["kedalaman_kualitas"][ev] = row
    print(f"  eval={ev}")
    for d in DEPTHS:
        print(f"      depth={d}  aksi={row[str(d)]['aksi']:<8} node={row[str(d)]['node']:>6} "
              f"nilai={row[str(d)]['nilai']:>8.2f}")

json.dump(out, open(here / "hasil_battle.json", "w"), indent=1)
print()
print("Tersimpan:", here / "hasil_battle.json")
