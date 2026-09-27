"""Offices, borders and war.

Every village has a council (who decide), a watch (police) and a border force (guards),
all paid a stipend from the treasury. Councils decide weekly — through the same kind of
six-way loaded roll people use — how much of the river to take, whether to raid, parley,
pay off or declare war on a neighbour. Tension comes from the river, raids, border brawls,
old grudges and betrayal.

War is fought in battles at the border between two villages. The dead are real people.
A beaten village makes peace on the winner's terms — water rights and tribute — or, if it
collapses, is occupied: its council replaced by a governor, its treasury bled. An empty
village falls to ruin. Only its secret mages can bring it back (systems/magic.py).
"""
from __future__ import annotations
import numpy as np

COUNCIL_SIZE = 5


def _adults(world):
    return [c for c in world.alive() if c.age_on(world.day) >= 18 and world.free(c)]


def assign_roles(world):
    """At founding (and whenever offices empty): councillors, watch, border force."""
    rng = world.rng
    adults = [c for c in _adults(world) if c.age_on(world.day) < 70]
    if not adults:
        return
    have = lambda r: [c for c in adults if c.role == r]
    need_council = COUNCIL_SIZE - len(have("councillor"))
    if need_council > 0:
        pool = sorted([c for c in adults if not c.role], key=lambda c: -(c.reputation + c.money / 5000 + 0.3 * c.personality["extraversion"]
                                                                         + 0.2 * rng.random()))
        for c in pool[:need_council]:
            c.role = "councillor"
    v = world.village
    at_war = any(w.get("active") and v.idx in (w["a"], w["b"]) for w in world.wars)
    tense = max(v.tension.values(), default=0) > 0.5
    police_target = max(1, len(adults) // 22)
    guard_target = max(2, len(adults) // (4 if at_war else (7 if tense else 11)))
    for role, target, key in (("police", police_target, lambda c: c.personality["conscientiousness"] + 0.3 * c.skill),
                              ("guard", guard_target, lambda c: 0.5 * c.personality["extraversion"] + 0.5 * (1 - c.personality["neuroticism"])
                               + (0.3 if c.age_on(world.day) < 40 else 0))):
        short = target - len(have(role))
        if short <= 0:
            continue
        pool = [c for c in adults if not c.role and 18 <= c.age_on(world.day) <= 55]
        pool.sort(key=lambda c: -(key(c) + 0.4 * rng.random()))
        for c in pool[:short]:
            c.role = role


def reseat_council(world, party_name: str = ""):
    """After an election the winners take the council."""
    adults = _adults(world)
    for c in adults:
        if c.role == "councillor":
            c.role = ""
    party = next((m for m in world.movements_here() if m.alive and m.name == party_name), None)
    seats = []
    if party:
        seats = sorted([world.citizens[i] for i in party.members if i in world.citizens and world.citizens[i].alive
                        and world.free(world.citizens[i])], key=lambda c: -c.reputation)[:COUNCIL_SIZE]
    rest = sorted([c for c in adults if c not in seats and c.role == ""], key=lambda c: -c.reputation)
    for c in (seats + rest)[:COUNCIL_SIZE]:
        c.role = "councillor"


def council(world):
    return [c for c in world.alive() if c.role == "councillor"]


def temper(world) -> dict:
    """What the council is like, collectively."""
    cs = council(world)
    if not cs:
        return {"aggression": 0.5, "greed": 0.5, "caution": 0.5}
    P = lambda k: float(np.mean([c.personality[k] for c in cs]))
    auth = world.policy.platform.get("authority", 0.0)
    return {"aggression": float(np.clip(0.5 * (1 - P("agreeableness")) + 0.25 * P("extraversion") + 0.25 * max(0, auth), 0, 1)),
            "greed": float(np.clip(0.6 * (1 - P("agreeableness")) + 0.4 * P("conscientiousness"), 0, 1)),
            "caution": float(np.clip(0.6 * P("neuroticism") + 0.4 * P("conscientiousness"), 0, 1))}


def strength(world, idx: int, reveal: bool = False) -> float:
    """Fighting strength: guards (and in war, everyone of age who will fight), health, morale, tools, magic."""
    from . import magic
    v = world.villages[idx]
    with world.at(idx):
        fighters = [c for c in world.alive() if world.free(c) and c.age_on(world.day) >= 16 and
                    (c.role == "guard" or (c.role == "" and c.age_on(world.day) <= 55 and _at_war(world, idx) and c.personality["neuroticism"] < 0.7))]
        base = sum((0.4 + c.health) * (1.4 if c.role == "guard" else 0.7) for c in fighters)
        base *= (0.5 + v.morale) * (0.9 + 0.1 * v.tech)
        if v.occupier is not None:
            base *= 0.3
        return base + magic.war_power(world, idx, reveal=reveal)


def _at_war(world, idx):
    return any(w.get("active") and idx in (w["a"], w["b"]) for w in world.wars)


def war_between(world, a, b):
    return next((w for w in world.wars if w.get("active") and {w["a"], w["b"]} == {a, b}), None)


def border(world, a: int, b: int):
    """A point on the border between two villages (where the fighting happens)."""
    ra, rb = world.villages[a].region, world.villages[b].region
    ca, cb = world.villages[a].centre, world.villages[b].centre
    x = int(np.clip((ca[0] + cb[0]) / 2, min(ra[0], rb[0]), max(ra[2], rb[2]) - 1))
    y = int(np.clip((ca[1] + cb[1]) / 2, min(ra[1], rb[1]), max(ra[3], rb[3]) - 1))
    return x, y


# ---------------------------------------------------------------- inside a village, every day
def village_daily(world):
    v = world.village
    alive = world.alive()
    if not alive:
        if not v.fallen:
            v.fallen, v.fallen_day = True, world.day
            v.occupier = None
            world.emit("war", f"{v.name} is empty. The {v.element} village has fallen into ruin.", 1.0, [], kind="fallen", tone="bad", village=-1)
            from .. import terrain
            cx, cy = v.centre
            for dx in range(-3, 4):
                for dy in range(-2, 3):
                    if world.rng.random() < 0.5:
                        world.set_tile(cx + dx, cy + dy, terrain.RUIN)
        return
    # stipends: the watch, the guard and the council are paid — or they aren't
    officers = [c for c in alive if c.role]
    pay = v.stipend * len(officers)
    if world.treasury >= pay:
        world.treasury -= pay
        for c in officers:
            c.money += v.stipend
    elif world.day % 7 == 0:
        for c in officers:
            c.grievance = min(1.0, c.grievance + 0.03)
            if c.role in ("guard", "police") and world.rng.random() < 0.08 * (1 - c.personality["conscientiousness"]):
                world.emit("politics", f"{c.name} walked off the {'watch' if c.role == 'police' else 'border'} — no pay for weeks.", 0.4,
                           [c.id], kind="quit", tone="bad")
                c.role = ""
    if world.day % 30 == 0:
        assign_roles(world)
    v.morale = float(v.morale + (0.6 - v.morale) * 0.01)        # morale recovers, slowly
    # tribute to an occupier
    if v.occupier is not None and world.day % 7 == 0 and world.treasury > 0:
        take = world.treasury * 0.3
        world.treasury -= take
        world.villages[v.occupier].treasury += take
        for c in alive:
            c.grievance = min(1.0, c.grievance + 0.02)
    if world.day % 7 == 0:
        _council_decides(world)
        if len(alive) < 25 and v.occupier is None and world.rng.random() < 0.04:
            from . import disasters
            n = world.rng.randint(4, 9)
            disasters.inject(world, "immigration", n=n)          # "a caravan of newcomers arrived" — land for the taking


def _council_decides(world):
    """Weekly: the council of the focused village rolls on what to do about its neighbours and the river."""
    rng = world.rng
    v = world.village
    if v.occupier is not None or not council(world):
        return
    t = temper(world)
    thirsty = v.water_met < 0.85
    # --- the river: take more when thirsty (or greedy), give back when it is buying trouble
    downstream = [o for o in world.villages[v.idx + 1:] if not o.fallen]
    anger_below = max((o.tension.get(v.idx, 0) for o in downstream), default=0)
    if thirsty or (t["greed"] > 0.55 and rng.random() < 0.15 * t["greed"]):
        if v.diversion < 0.55 and downstream and rng.random() < 0.3 + 0.4 * t["greed"]:
            v.diversion = min(0.6, v.diversion + rng.uniform(0.03, 0.1))
            if v.diversion > 0.2 and rng.random() < 0.3:
                world.emit("river", f"The council of {v.name} voted to take more of the river ({v.diversion*100:.0f}% of the flow).", 0.55,
                           [c.id for c in council(world)[:1]], kind="diversion_up")
    elif anger_below > 0.5 and t["caution"] > 0.45 and v.diversion > 0.08 and rng.random() < 0.25 * t["caution"]:
        v.diversion = max(0.05, v.diversion - 0.08)
        world.emit("river", f"Fearing war, {v.name} opened its sluices to the villages below.", 0.55, [], kind="diversion_down", tone="good")
    # --- neighbours
    for o in world.villages:
        if o.idx == v.idx or o.fallen:
            continue
        ten = v.tension.get(o.idx, 0.0)
        v.tension[o.idx] = max(0.0, ten * 0.985 - 0.002 + 0.25 * v.grudges.get(o.idx, 0) * 0.02)
        v.grudges[o.idx] = max(0.0, v.grudges.get(o.idx, 0) * 0.998)
        if war_between(world, v.idx, o.idx) or ten < 0.25:
            continue
        last = max((x.get("end", x["start"]) for x in world.wars if {x["a"], x["b"]} == {v.idx, o.idx}), default=-9999)
        truce = world.day - last < 420                      # nobody goes straight back to war
        mine, theirs = strength(world, v.idx), strength(world, o.idx)
        ratio = mine / max(1.0, theirs)
        options = {
            "wait":       0.9 + t["caution"],
            "parley":     0.6 + t["caution"] * 0.8 + (0.3 if ratio < 0.8 else 0),
            "threaten":   0.4 + t["aggression"],
            "raid":       (0.1 + 0.7 * t["aggression"]) * (1.0 if o.idx < v.idx and thirsty else 0.4) * (1.2 if ratio > 1 else 0.6),
            "war":        0.0 if truce or v.morale < 0.45 else max(0.0, ten - 0.6) * 0.45 * (0.3 + t["aggression"]) * min(2.0, ratio) ** 1.5,
            "tribute":    0.15 + (0.6 if ratio < 0.5 else 0) * t["caution"],
        }
        pick = rng.choices(list(options), weights=[max(1e-3, w) * rng.uniform(0.7, 1.3) for w in options.values()])[0]
        if pick == "parley" and rng.random() < 0.35:
            with world.at(o.idx):
                ot = temper(world)
            if rng.random() < 0.3 + 0.5 * (1 - ot["aggression"]):
                v.tension[o.idx] = max(0.0, ten - 0.2)
                o.tension[v.idx] = max(0.0, o.tension.get(v.idx, 0) - 0.2)
                up, down = (v, o) if v.idx < o.idx else (o, v)
                if up.diversion > 0.15:
                    up.diversion = max(0.05, up.diversion - 0.1)
                world.emit("diplomacy", f"Envoys of {v.name} and {o.name} met at the border and agreed a truce over the river.", 0.6, [],
                           kind="treaty", tone="good", village=-1)
            else:
                v.tension[o.idx] = min(1.0, ten + 0.05)
                world.emit("diplomacy", f"{o.name} sent {v.name}'s envoys home with nothing.", 0.5, [], kind="foreign_insult", tone="bad")
        elif pick == "threaten":
            o.tension[v.idx] = min(1.0, o.tension.get(v.idx, 0) + 0.06)
            if rng.random() < 0.3:
                world.emit("diplomacy", f"{v.name} warned {o.name}: give up the water or face the consequences.", 0.5, [], kind="ultimatum", village=-1)
        elif pick == "raid":
            leader = max(council(world) + [c for c in world.alive() if c.role == "guard"], key=lambda c: c.personality["extraversion"], default=None)
            border_raid(world, v, leader, target=o)
        elif pick == "war":
            declare(world, v.idx, o.idx, "the river" if (o.idx < v.idx and thirsty) else "old wrongs")
        elif pick == "tribute" and world.treasury > 800:
            gift = world.treasury * 0.15
            world.treasury -= gift
            o.treasury += gift
            o.tension[v.idx] = max(0.0, o.tension.get(v.idx, 0) - 0.15)
            world.emit("diplomacy", f"{v.name} paid {o.name} £{gift:,.0f} to keep the peace.", 0.5, [], kind="tribute_paid", village=-1)


def border_raid(world, v, leader=None, target=None):
    """A night raid across the border: take grain, burn a barn, and bring home grudges."""
    rng = world.rng
    if target is None:
        up = [o for o in world.villages if o.idx != v.idx and not o.fallen]
        if not up:
            return
        target = max(up, key=lambda o: v.tension.get(o.idx, 0) + (o.diversion if o.idx < v.idx else 0))
    raiders = [c for c in world.alive() if c.role == "guard" and world.free(c)][:6]
    if leader is not None and leader not in raiders:
        raiders.append(leader)
    if not raiders:
        return
    x, y = border(world, v.idx, target.idx)
    with world.at(target.idx):
        loot = min(target.food * 0.15, 120)
        target.food -= loot
        defenders = [c for c in world.alive() if c.role == "guard" and world.free(c)]
        hurt = []
        for c in rng.sample(defenders, min(2, len(defenders))):
            c.health -= rng.uniform(0.05, 0.3)
            if c.health <= 0.02:
                from . import lifecycle
                lifecycle.die(world, c, f"a raid from {v.name}")
            hurt.append(c)
        target.tension[v.idx] = min(1.0, target.tension.get(v.idx, 0) + 0.2)
        target.grudges[v.idx] = min(1.0, target.grudges.get(v.idx, 0) + 0.1)
        world.add_fx("raid", x, y, days=2)
        world.emit("war", f"Raiders from {v.name} crossed into {target.name} at night and carried off {loot:.0f} sacks of grain.", 0.7,
                   [c.id for c in hurt[:2]], kind="foreign_insult", tone="bad")
    v.food += loot
    for c in raiders:
        if rng.random() < 0.08:
            c.health -= rng.uniform(0.1, 0.4)
            if c.health <= 0.02:
                from . import lifecycle
                lifecycle.die(world, c, f"a raid on {target.name}")


def declare(world, a: int, b: int, reason: str = ""):
    if war_between(world, a, b):
        return
    va, vb = world.villages[a], world.villages[b]
    war = {"id": len(world.wars) + 1, "a": a, "b": b, "start": world.day, "active": True, "reason": reason,
           "dead": {a: 0, b: 0}, "battles": 0, "front": border(world, a, b)}
    world.wars.append(war)
    world.add_fx("battle", *war["front"], days=3, sides=[a, b], war=war["id"])
    world.emit("war", f"{va.name} declared war on {vb.name} over {reason}.", 1.0, [], kind="war_declared_realm", tone="bad", village=-1)
    for idx in (a, b):
        with world.at(idx):
            assign_roles(world)
            people = world.alive()
            world.emit("war", f"{world.villages[idx].name} is at war with {world.villages[b if idx == a else a].name}.", 0.75,
                       [c.id for c in people if c.role == "guard"][:3], kind="war_declared", tone="bad")


def daily(world):
    """The realm, every day: battles on the fronts, occupations, peace."""
    rng = world.rng
    for w in world.wars:
        if not w.get("active"):
            continue
        a, b = w["a"], w["b"]
        va, vb = world.villages[a], world.villages[b]
        if va.fallen or vb.fallen:
            _end(world, w, winner=b if va.fallen else a, terms="fall")
            continue
        if not any(f["type"] == "battle" and f.get("war") == w["id"] for f in world.fx if f["until"] > world.day):
            with world.at(a):                          # the camps and the skirmish line, for as long as the war lasts
                world.add_fx("battle", *w["front"], days=3, sides=[a, b], war=w["id"])
        if (world.day - w["start"]) % 9 != 4:          # armies march, dig in, skirmish; pitched battles are rarer
            continue
        w["battles"] += 1
        sa, sb = strength(world, a, reveal=True), strength(world, b, reveal=True) * 1.15    # defenders know the ground
        roll = rng.random() * (sa + sb)
        winner, loser = (a, b) if roll < sa else (b, a)
        x, y = w["front"]
        with world.at(winner):
            world.add_fx("clash", x + rng.uniform(-2, 2), y + rng.uniform(-2, 2), days=2)
        from .. import terrain
        if rng.random() < 0.4:
            world.set_tile(x + rng.randint(-3, 3), y + rng.randint(-3, 3), terrain.ASH)       # the ground remembers
        for side, share in ((loser, rng.uniform(0.015, 0.05)), (winner, rng.uniform(0.0, 0.02))):
            with world.at(side):
                fighters = [c for c in world.alive() if c.role == "guard" and world.free(c)] or \
                           [c for c in world.alive() if 18 <= c.age_on(world.day) <= 50]
                k = max(1 if side == loser else 0, int(round(len(fighters) * share)))
                dead = rng.sample(fighters, min(k, len(fighters)))
                from . import lifecycle
                enemy = world.villages[b if side == a else a].name
                for c in dead:
                    lifecycle.die(world, c, f"battle against {enemy}")
                w["dead"][side] += len(dead)
                world.villages[side].morale = float(np.clip(world.villages[side].morale + (-0.12 if side == loser else 0.03), 0, 1))
                if side == loser and dead:
                    world.emit("war", f"{world.villages[side].name} lost a battle against {enemy}: {', '.join(c.name for c in dead[:3])}"
                                      f"{' and others' if len(dead) > 3 else ''} fell.", 0.8,
                               [r.other_id for c in dead for r in c.relationships.values() if r.score > 50][:3], kind="battle_lost", tone="bad")
        # does it end?
        for side, other in ((a, b), (b, a)):
            vs = world.villages[side]
            with world.at(side):
                left = len(world.alive())
            if vs.morale < 0.18 or left < 6:
                _end(world, w, winner=other, terms="collapse" if left < 15 or vs.morale < 0.08 else "surrender")
                break
        else:
            if world.day - w["start"] > 90 and va.morale < 0.35 and vb.morale < 0.35 and rng.random() < 0.25:
                _end(world, w, winner=None, terms="exhaustion")


def _end(world, w, winner, terms):
    w["active"] = False
    w["end"] = world.day
    w["winner"] = winner
    a, b = w["a"], w["b"]
    if winner is None:
        world.emit("war", f"Exhausted, {world.villages[a].name} and {world.villages[b].name} laid down their arms. "
                          f"{w['dead'][a] + w['dead'][b]} dead for nothing.", 0.9, [], kind="peace", village=-1)
        for idx in (a, b):
            world.villages[idx].tension[b if idx == a else a] = 0.3
        return
    loser = b if winner == a else a
    vw, vl = world.villages[winner], world.villages[loser]
    vw.wars_won += 1
    vl.wars_lost += 1
    vw.morale = min(1.0, vw.morale + 0.2)
    if terms == "fall":
        world.emit("war", f"The war is over: {vl.name} is no more.", 1.0, [], kind="victory", village=-1)
        return
    if terms == "collapse" and not vl.fallen:
        vl.occupier, vl.occupied_since = winner, world.day
        vl.policy.ruling_party = f"{vw.name} Governorship"
        vl.policy.platform = {"economic": 0.4, "authority": 0.9}
        vl.policy.laws = sorted(set(vl.policy.laws) | {"curfew"})
        with world.at(loser):
            for c in world.alive():
                if c.role in ("councillor", "guard"):
                    c.role = ""
            world.emit("war", f"{vw.name} occupied {vl.name}. A governor sits in the council house; the {vl.element} banner is burned.", 1.0,
                       [c.id for c in world.alive()][:3], kind="occupied", tone="bad")
        # the water belongs to the victor now
        if loser < winner:
            vl.diversion = 0.02
        else:
            vw.diversion = min(0.6, vw.diversion + 0.15)
        return
    # surrender: a treaty on the winner's terms
    tribute = vl.treasury * 0.4
    vl.treasury -= tribute
    vw.treasury += tribute
    grain = vl.food * 0.3
    vl.food -= grain
    vw.food += grain
    if loser < winner:
        vl.diversion = max(0.02, vl.diversion - 0.25)       # the upstream loser must let the water through
    else:
        vw.diversion = min(0.6, vw.diversion + 0.1)
    vl.grudges[winner] = min(1.0, vl.grudges.get(winner, 0) + 0.4)
    vl.tension[winner] = 0.35
    vw.tension[loser] = 0.2
    world.emit("war", f"{vl.name} surrendered to {vw.name}: £{tribute:,.0f} and {grain:.0f} sacks of grain in tribute, and the river on "
                      f"{vw.name}'s terms. {w['dead'][a] + w['dead'][b]} died.", 1.0, [], kind="victory", village=-1)
