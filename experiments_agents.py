"""Eksperimen headless: KB + decision under uncertainty + automated planning (tanpa PyScript/browser).
Jalankan:  python3 experiments_agents.py   (main.py, kb.txt, kb_engine.py, planner.py, decision.py, agents.py satu folder)"""
import math, time, heapq, itertools, statistics, json, pathlib, sys

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
src = (here / "main.py").read_text()
exec(src.split("# ==== CORE BEGIN ====")[1].split("# ==== CORE END ====")[0], globals())
exec(src.split("# ==== CSP ENGINE BEGIN ====")[1].split("# ==== CSP ENGINE END ====")[0], globals())
from kb_engine import KB
from agents import WorldSim, MODES
from planner import HEURISTICS as PLAN_ALGOS

grid, kb, N, T = GridMap(MAP_DATA), KB.from_file(str(here / "kb.txt")), 30, 80
path_fn = lambda a, b: Pathfinding.search(grid, a, b, h_manhattan)
out = {"decision_modes": {}, "planners": {}, "mdp_gamma": {}, "kb": {}}
plans = {a: dict(n=0, expanded=0, cost=0, ms=0, found=0) for a in PLAN_ALGOS}
opt_cost = []

for mode in MODES:
    agg, infer_ms, naga_hp, goblin_alive, mage_alive = {}, [], [], [], []
    for seed in range(N):
        lv = LevelCSP(grid, seed).generate("hybrid")
        sim = WorldSim(grid, kb, path_fn, seed)
        sim.mode = mode
        sim.reset(lv, list(lv["P"]), seed)
        for t in range(T):
            L = sim.step(lv["K"], None)                    # ksatria diam: yang diamati hanya interaksi antar-NPC
            infer_ms.append(L["inf"].ms)
            if mode == "priority":
                for pl in L["plans"].values():
                    if pl:
                        for a, r in pl["results"].items():
                            d = plans[a]
                            d["n"] += 1; d["expanded"] += r["expanded"]; d["ms"] += r["ms"]; d["found"] += r["found"]; d["cost"] += r["cost"]
        for k, v in sim.stats.items():
            agg[k] = agg.get(k, 0) + v
        naga_hp.append(sim.npcs["naga"].hp)
        goblin_alive.append(sim.npcs["goblin"].alive)
        mage_alive.append(sim.npcs["mage"].alive)
    steal_try = agg["steal"] + agg["steal_fail"]
    out["decision_modes"][mode] = dict(
        steal_berhasil=round(agg["steal"] / N, 2), steal_gagal=round(agg["steal_fail"] / N, 2),
        upeti=round(agg["gift"] / N, 2), mangsa=round(agg["devour"] / N, 2), sihir=round(agg["cast"] / N, 2),
        kabur=round(agg["flee"] / N, 1), korban=round(agg["kills"] / N, 2), ramuan_diambil=round(agg["pickup"] / N, 2),
        hp_naga_akhir=round(statistics.mean(naga_hp), 1), goblin_hidup=f"{sum(goblin_alive)}/{N}",
        infer_ms=round(statistics.mean(infer_ms), 2))
for a, d in plans.items():
    out["planners"][a] = dict(masalah=d["n"], ditemukan=d["found"], node_rata2=round(d["expanded"] / d["n"], 2),
                              biaya_rata2=round(d["cost"] / max(1, d["found"]), 2), ms_rata2=round(d["ms"] / d["n"], 3))
sim.mode = "priority"
for g in (0.5, 0.8, 0.9, 0.95, 0.99):
    sim.gamma = g
    row = {}
    for pair in (("mage", "naga"), ("naga", "mage"), ("goblin", "mage")):
        m = sim.pair_mdp(*pair)
        flee = sum(1 for s, a in m["policy"].items() if not isinstance(s, str) and a == "flee")
        row["-".join(pair)] = dict(iterasi=m["iters"], flee_dari_25=flee, V_5_5=round(m["V"][(5, 5)], 1))
    out["mdp_gamma"][str(g)] = row
st = kb.infer(sim.facts()).stats()
out["kb"] = dict(aturan=len(kb.rules), fakta_statis=len(kb.static), **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in st.items()})
json.dump(out, open(here / "hasil_agents.json", "w"), indent=1)
for k, v in out.items():
    print(k)
    if k == "kb": print("  ", v); continue
    for n, d in v.items(): print(f"  {n:<16}", d)
