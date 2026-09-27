"""The secret societies. Each village has a hidden circle of people who can work its element.

Nobody is born a mage. Power comes from years of practice (the `practise` act, goals like
"master the old arts"), gated by temperament, and from rare awakenings in extremity — grief,
fury, a village burning. Or god can grant it. Stewards cannot: a visitor's person earns it
or never has it.

Mages keep themselves secret (their events are marked secret: only god sees them) until war
or conquest draws them out. In battle they are worth many soldiers, and they reveal
themselves doing it. When their village is occupied or falls, the circle plots; if they grow
strong enough they rise — driving out the garrison, or leading the scattered survivors home
to rebuild the ruins. That is the only way back.
"""
from __future__ import annotations
import numpy as np

SPELLS = {"fire": ("fireball", "called down fire on"), "water": ("wave", "drowned the ranks of"),
          "earth": ("quake", "split the ground under"), "air": ("tornado", "flung a whirlwind at"),
          "sky": ("lightning", "struck with lightning")}


def is_mage(c) -> bool:
    return bool(c.magic and c.magic.get("awakened"))


def _lore(c) -> dict:
    if c.magic is None:
        c.magic = {"element": None, "power": 0.0, "practice": 0.0, "revealed": False, "awakened": False}
    return c.magic


def awaken(world, c, element: str = None, power: float = 0.25, why: str = "", granted: bool = False):
    m = _lore(c)
    m["element"] = element or world.villages[c.origin].element
    m["awakened"] = True
    m["power"] = max(m.get("power", 0.0), float(np.clip(power, 0.05, 1.0)))
    if c.goal == "master the old arts":
        c.goal_progress = m["power"]
    how = "God touched" if granted else "The old power woke in"
    with world.at(c.village):
        world.emit("magic", f"{how} {c.name}{': ' + why if why else ''}. They can call on the {m['element']} now.", 0.7, [c.id],
                   kind="awakening", secret=True)


def seed_society(world):
    """At founding: a few in each village already carry the old knowledge, and know each other."""
    rng = world.rng
    v = world.village
    adults = [c for c in world.alive() if c.age_on(world.day) >= 20]
    n = max(1, int(round(len(adults) * rng.uniform(0.03, 0.05))))
    pool = sorted(adults, key=lambda c: -(c.personality["openness"] + 0.5 * c.personality["conscientiousness"] + 0.4 * rng.random()))
    for c in pool[:n]:
        c.magic = {"element": v.element, "power": rng.uniform(0.2, 0.55), "practice": rng.uniform(0.3, 0.7), "revealed": False, "awakened": True}
        for o in pool[:n]:
            if o.id != c.id:
                c.rel(o.id).score = max(c.rel(o.id).score, 45)
    world.emit("magic", f"The {v.element} circle of {v.name} met in secret: {', '.join(c.name for c in pool[:n])}.", 0.4,
               [c.id for c in pool[:n]][:3], kind="society", secret=True)


def practise(world, c, effort: float = 1.0):
    """Hours of the old forms. Most never get anywhere. A few feel something answer."""
    m = _lore(c)
    p = c.personality
    gift = 0.3 + 0.5 * p["openness"] + 0.2 * p["conscientiousness"]
    m["practice"] = float(min(1.0, m.get("practice", 0.0) + 0.006 * effort * gift))
    if m.get("awakened"):
        m["power"] = float(min(1.0, m["power"] + 0.002 * effort * gift * (1.2 - m["power"])))
        if c.goal == "master the old arts":
            c.goal_progress = m["power"]
    elif m["practice"] > 0.45 and world.rng.random() < 0.02 * gift * m["practice"]:
        awaken(world, c, power=0.1 + 0.2 * m["practice"], why="after years at the old forms")


def war_power(world, idx: int, reveal: bool = False) -> float:
    """What the village's mages add in battle. Using it reveals them."""
    v = world.villages[idx]
    mages = [c for c in world.citizens.values() if c.alive and c.village == idx and is_mage(c) and world.free(c)]
    total = sum(mage_worth(c) for c in mages)
    if reveal and mages:
        spell, verb = SPELLS.get(v.element, ("magic", "struck"))
        for c in mages:
            if not c.magic.get("revealed"):
                c.magic["revealed"] = True
                enemy = next((w for w in world.wars if w.get("active") and idx in (w["a"], w["b"])), None)
                foe = world.villages[enemy["b"] if enemy and enemy["a"] == idx else (enemy["a"] if enemy else idx)].name
                with world.at(idx):
                    x, y = enemy["front"] if enemy else c.pos
                    world.add_fx(spell, x, y, days=3, element=v.element)
                    world.emit("magic", f"{c.name} of {v.name} revealed themselves as a {v.element} mage and {verb} the {foe} line.",
                               0.9, [c.id], kind="mage_revealed", tone="good")
    return total


def daily(world):
    rng = world.rng
    for c in world.citizens.values():
        if not c.alive or not c.magic:
            continue
        if is_mage(c) and rng.random() < 0.02:
            practise(world, c, 0.5)            # the circle keeps its members sharp
    if world.day % 7:
        return
    for v in world.villages:
        with world.at(v.idx):
            people = world.alive()
            # the circle recruits: a mage brings in someone they trust and who has the gift
            for c in [x for x in people if is_mage(x)]:
                if rng.random() < 0.02:
                    cands = [world.citizens[r.other_id] for r in c.relationships.values() if r.score > 50 and r.other_id in world.citizens]
                    cands = [x for x in cands if x.alive and not is_mage(x) and x.personality["openness"] > 0.6 and x.village == v.idx]
                    if cands:
                        pupil = rng.choice(cands)
                        lore = _lore(pupil)
                        lore["practice"] = max(lore["practice"], 0.3)
                        if pupil.goal not in ("master the old arts",) and rng.random() < 0.5:
                            pupil.goal, pupil.goal_progress = "master the old arts", 0.0
                        world.emit("magic", f"{c.name} took {pupil.name} into the {v.element} circle.", 0.4, [pupil.id, c.id],
                                   kind="society", secret=True)
            # extremity wakes it
            for c in people:
                if c.personality["openness"] > 0.7 and (c.feel("grief") > 0.85 or c.feel("anger") > 0.9) and rng.random() < 0.01:
                    awaken(world, c, power=rng.uniform(0.1, 0.35), why="in the depths of " + ("grief" if c.feel("grief") > 0.85 else "rage"))
    _resurrections(world)


def mage_worth(c) -> float:
    """What one mage adds to their village's strength in battle (a healthy guard is worth about 2)."""
    return 8.0 * c.magic["power"] ** 1.3 if is_mage(c) else 0.0


def rise_odds(world, v) -> float:
    """Weekly chance that an occupied village's mages drive the garrison out (0 if they are too weak to try)."""
    if v.occupier is None:
        return 0.0
    own = [c for c in world.citizens.values() if c.alive and c.origin == v.idx and is_mage(c) and world.free(c)]
    power = sum(c.magic["power"] for c in own)
    if power <= 0.3:
        return 0.0
    garrison = max(1.0, 0.3 * sum(1 for c in world.citizens.values() if c.alive and c.village == v.occupier and c.role == "guard"))
    return min(0.5, 0.04 * (power * 6 + v.morale * 3) / garrison)


def return_odds(world, v) -> float:
    """Weekly chance that a ruined village's scattered mages lead its people home."""
    if not v.fallen:
        return 0.0
    own = [c for c in world.citizens.values() if c.alive and c.origin == v.idx and is_mage(c) and world.free(c)]
    return 0.05 * sum(c.magic["power"] for c in own) if own else 0.0


def circle(world, idx: int) -> dict:
    """Everything about one village's secret circle: its mages (born there, wherever they live now), its apprentices,
    its strength in battle, and its chances of freeing or rebuilding the village."""
    v = world.villages[idx]
    mages = sorted([c for c in world.citizens.values() if c.alive and c.origin == idx and is_mage(c)], key=lambda c: -c.magic["power"])
    pupils = sorted([c for c in world.citizens.values() if c.alive and c.origin == idx and not is_mage(c)
                     and ((c.magic and c.magic.get("practice", 0) >= 0.1) or c.goal == "master the old arts")],
                    key=lambda c: -((c.magic or {}).get("practice", 0)))
    here = [c for c in mages if c.village == idx and world.free(c)]
    return {"village": v, "mages": mages, "apprentices": pupils, "battle": sum(mage_worth(c) for c in here),
            "rise": rise_odds(world, v), "return": return_odds(world, v)}


def _resurrections(world):
    """Occupied villages rise when their mages are strong enough; fallen ones are rebuilt by their scattered mages."""
    rng = world.rng
    for v in world.villages:
        own = [c for c in world.citizens.values() if c.alive and c.origin == v.idx and is_mage(c) and world.free(c)]
        power = sum(c.magic["power"] for c in own)
        if v.occupier is not None:
            occ = world.villages[v.occupier]
            p = rise_odds(world, v)
            if p > 0 and rng.random() < p:
                spell, _ = SPELLS[v.element]
                v.occupier, v.occupied_since = None, None
                v.policy.ruling_party = f"The {v.element.title()} Circle"
                v.policy.platform = {"economic": 0.0, "authority": 0.3}
                v.policy.laws = [x for x in v.policy.laws if x != "curfew"]
                v.morale = 0.9
                occ.tension[v.idx] = 0.8
                v.tension[occ.idx] = 0.9
                with world.at(v.idx):
                    for c in own:
                        c.magic["revealed"] = True
                        if c.village == v.idx:
                            c.role = "councillor"
                    world.add_fx(spell, *v.centre, days=5, element=v.element)
                    world.emit("war", f"The {v.element} mages of {v.name} rose in the night — {', '.join(c.name for c in own[:3])} — "
                                      f"and drove out the {occ.name} garrison. {v.name} is free.", 1.0,
                               [c.id for c in world.alive()][:3], kind="liberated", tone="good")
                    from . import war
                    war.assign_roles(world)
        elif v.fallen and own and rng.random() < return_odds(world, v):
            # the circle leads the diaspora home
            from .crime import relocate
            from .. import terrain
            leader = max(own, key=lambda c: c.magic["power"])
            v.fallen, v.fallen_day = False, None
            v.food = max(v.food, 200.0)
            v.treasury = max(v.treasury, 500.0)
            exiles = [c for c in world.citizens.values() if c.alive and c.origin == v.idx and c.village != v.idx]
            followers = own + [c for c in exiles if c not in own and rng.random() < 0.5]
            for c in followers:
                relocate(world, c, v.idx, reason="the return")
            cx, cy = v.centre
            for dx in range(-3, 4):
                for dy in range(-2, 3):
                    if world.grid[cy + dy, cx + dx] == terrain.RUIN:
                        world.set_tile(cx + dx, cy + dy, terrain.TOWN)
            with world.at(v.idx):
                world.add_fx(SPELLS[v.element][0], cx, cy, days=5, element=v.element)
                world.emit("war", f"{leader.name}, a {v.element} mage, led {len(followers)} of {v.name}'s scattered people home "
                                  f"and raised the village from its ruins.", 1.0, [leader.id], kind="liberated", tone="good", village=-1)
                from . import war
                war.assign_roles(world)
                if not world.open_businesses():
                    for kind in ("farm", "farm", "market"):
                        world.found_business(rng.choice(followers), kind)
