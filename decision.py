"""Decision under uncertainty (terpisah dari game).
 - outcomes(): model hasil stokastik tiap aksi (cabang: peluang, HP, ramuan, ...)
 - MEU  : expected utility satu langkah (miopik)
 - MDP  : value iteration pada MDP pertarungan (state = bucket HP pelaku x HP lawan) -> utilitas jangka panjang."""
import math
import time
from collections import namedtuple

B = 5                                   # jumlah bucket HP (1..5), 0 = mati
R_WIN, R_ESC, STEP = 50, -10, -1
HEAL, HEAL_DEVOUR, STEAL_FAIL_DMG, DEVOUR_HIT = 30, 25, 6, 90
ACTIONS = ("strike", "guard", "flee")
Br = namedtuple("Br", "p mh mp fh fp bonus retal esc")


def bucket(hp, mx):
    return 0 if hp <= 0 else max(1, math.ceil(B * hp / mx))


# --------------------------- value iteration generik ---------------------------
def value_iteration(states, actions, trans, gamma=0.95, eps=1e-3, max_iter=300):
    V, deltas = {s: 0.0 for s in states}, []
    q = lambda s, a, V_: sum(p * (r + gamma * V_.get(s2, 0.0)) for p, s2, r in trans(s, a))
    for _ in range(max_iter):
        newV = {s: max(q(s, a, V) for a in actions(s)) for s in states}
        d = max(abs(newV[s] - V[s]) for s in states)
        V = newV
        deltas.append(d)
        if d < eps:
            break
    policy = {s: max(actions(s), key=lambda a: q(s, a, V)) for s in states}
    return V, policy, deltas


_CACHE = {}


def combat_mdp(bf, ph, bm, pr, pe, lose, gamma=0.95):
    """MDP pertarungan satu lawan satu. bf: bucket HP lawan yang hilang bila serangan kena (peluang ph);
    bm/pr: bucket HP pelaku yang hilang bila lawan membalas (peluang pr); pe: peluang kabur berhasil."""
    key = (bf, ph, bm, pr, pe, lose, gamma)
    if key in _CACHE:
        return _CACHE[key]
    t0 = time.perf_counter()
    states = [(a, f) for a in range(1, B + 1) for f in range(1, B + 1)] + ["WIN", "LOSE", "ESC"]

    def retaliate(p, a, f, rp):
        out = [(p * rp, (a - bm, f), STEP), (p * (1 - rp), (a, f), STEP)]
        return [(q, ("LOSE" if s[0] <= 0 else s), (r + lose if s[0] <= 0 else r)) for q, s, r in out if q > 0]

    def trans(s, a):
        if isinstance(s, str):
            return [(1.0, s, 0)]
        me, fo = s
        if a == "strike":
            out = [(ph, "WIN", R_WIN + STEP)] if fo - bf <= 0 else retaliate(ph, me, fo - bf, pr)
            return out + retaliate(1 - ph, me, fo, pr)
        if a == "guard":
            return retaliate(1.0, me, fo, pr / 2)
        return [(pe, "ESC", R_ESC + STEP)] + retaliate(1 - pe, me, fo, pr)

    V, pol, deltas = value_iteration(states, lambda s: ACTIONS if not isinstance(s, str) else ("strike",), trans, gamma)
    res = {"V": V, "policy": pol, "deltas": deltas, "iters": len(deltas), "ms": (time.perf_counter() - t0) * 1000,
           "gamma": gamma, "params": dict(bf=bf, ph=ph, bm=bm, pr=pr, pe=pe, lose=lose)}
    _CACHE[key] = res
    return res


# --------------------------- model hasil aksi ---------------------------
def outcomes(act, me, foe, retal):
    """me/foe: dict(hp,maxhp,pot,melee,spell,steal_p,flee_p). retal: (dmg,hit%) lawan membalas atau None."""
    mh, mp = me["hp"], me["pot"]
    fh, fp = (foe["hp"], foe["pot"]) if foe else (0, 0)
    if act in ("attack", "cast"):
        d, h = me["melee"] if act == "attack" else me["spell"]
        h /= 100
        base = [Br(h, mh, mp, max(0, fh - d), fp, 0, True, False), Br(1 - h, mh, mp, fh, fp, 0, True, False)]
    elif act == "devour":
        h = DEVOUR_HIT / 100
        base = [Br(h, min(me["maxhp"], mh + HEAL_DEVOUR), mp, 0, fp, 12, True, False),
                Br(1 - h, mh, mp, fh, fp, 0, True, False)]
    elif act == "steal":
        h = me["steal_p"] / 100
        base = [Br(h, mh, mp + 1, fh, max(0, fp - 1), 0, True, False),
                Br(1 - h, max(0, mh - STEAL_FAIL_DMG), mp, fh, fp, 0, True, False)]
    elif act == "gift":
        appease = bool(foe and foe.get("appease"))
        base = [Br(1.0, mh, mp - 1, min(foe["maxhp"], fh + HEAL), fp, 15 if appease else 4, not appease, False)]
    elif act == "drink":
        base = [Br(1.0, min(me["maxhp"], mh + HEAL), mp - 1, fh, fp, 0, True, False)]
    elif act == "flee":
        e = me["flee_p"] / 100
        base = [Br(e, mh, mp, fh, fp, 0, False, True), Br(1 - e, mh, mp, fh, fp, 0, True, False)]
    else:                                                        # continue: ikuti rencana / kejar ksatria
        base = [Br(1.0, mh, mp, fh, fp, 0, True, False)]
    out = []
    for b in base:
        if retal and b.retal and b.fh > 0 and b.mh > 0:
            d, h = retal[0], retal[1] / 100
            out += [b._replace(p=b.p * h, mh=max(0, b.mh - d)), b._replace(p=b.p * (1 - h))]
        else:
            out.append(b)
    return [b for b in out if b.p > 0]


def utility(b, me, foe, rel, mode, gamma, strike, retal):
    """Utilitas satu cabang hasil. mode 'meu' = miopik (fungsi linear HP); 'mdp' = nilai V* dari MDP."""
    w_hp = me["caution"] / 50
    pot = me["greed"] * b.mp
    if b.mh <= 0:
        return -80 * w_hp + pot
    if foe is None or rel not in ("enemy", "predator"):
        base = w_hp * 10 * b.mh / me["maxhp"] + (2 * b.fh / foe["maxhp"] if foe else 0)
        return base + pot + b.bonus
    if mode == "mdp" and strike and retal:
        m = combat_mdp(max(1, round(B * strike[0] / foe["maxhp"])), strike[1] / 100,
                       max(1, round(B * retal[0] / me["maxhp"])), retal[1] / 100, me["flee_p"] / 100,
                       -100 * w_hp, gamma)
        s = "ESC" if b.esc else ("WIN" if b.fh <= 0 else (bucket(b.mh, me["maxhp"]), bucket(b.fh, foe["maxhp"])))
        v = {"ESC": R_ESC, "WIN": R_WIN}.get(s) if isinstance(s, str) else m["V"][s]
        return v / 5 + pot + b.bonus
    if b.esc:
        return w_hp * 10 * b.mh / me["maxhp"] - 2 + pot
    u = w_hp * 10 * b.mh / me["maxhp"] - 6 * b.fh / foe["maxhp"] + (20 if b.fh <= 0 else 0)
    return u + pot + b.bonus


def expected_utility(act, me, foe, rel, retal, strike, mode="meu", gamma=0.95):
    brs = outcomes(act, me, foe, retal)
    eu = sum(b.p * utility(b, me, foe, rel, mode, gamma, strike, retal) for b in brs)
    psucc = sum(b.p for b in brs if (b.fh < (foe["hp"] if foe else 0)) or b.mp > me["pot"] or b.esc or b.mh > me["hp"])
    return eu, psucc
