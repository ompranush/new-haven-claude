"""Shocks: random or injected. `world.inject(name)` is god mode.

The pandemic is not a global health decrement: it spreads person-to-person
through the same interactions that build friendships, so social hubs get sick
first and lonely people are safest.
"""
from __future__ import annotations
import numpy as np
from ..models import Citizen
from .. import terrain

INJECTABLE = {
    "drought": "Harvest fails: food reserves halve, prices spike.",
    "flood": "The river bursts its banks: riverside businesses lose cash, some people die.",
    "pandemic": "A sickness arrives with one traveller and spreads through social contact.",
    "recession": "Demand collapses for 120 days.",
    "boom": "A bumper harvest and strong demand for a season.",
    "breakthrough": "A technological leap raises productivity everywhere by 15%.",
    "automation": "Machines replace 30% of workers in workshops, mines and markets.",
    "raid": "Bandits raid the town: treasury and businesses are robbed, people are hurt.",
    "meteor_strike": "A rock from the sky obliterates one building outright.",
    "immigration": "A caravan of 20 newcomers arrives looking for work.",
}


def inject(world, name: str, **kw):
    rng = world.rng
    alive = world.alive()
    if not alive:
        return
    if name == "drought":
        world.food *= 0.5
        for b in world.open_businesses():
            if b.kind == "farm":
                b.inventory = 0
        for c in alive:
            c.happiness = max(0, c.happiness - 0.06)
        world.emit("disaster", "A severe drought withered the fields. Food reserves halved and the price of bread doubled.", 0.8,
                   [max(alive, key=lambda c: c.reputation).id] if alive else [])
    elif name == "flood":
        victims = []
        for b in world.open_businesses():
            if _near_water(world, b.x, b.y, 3):
                b.cash -= 800
                b.loss_days += 5
        for c in alive:
            if _near_water(world, *c.home, 2) and rng.random() < 0.06:
                victims.append(c)
        for c in victims:
            from . import lifecycle
            lifecycle.die(world, c, "flood")
        world.emit("disaster", f"The river burst its banks. Riverside businesses were wrecked and {len(victims)} people drowned.", 0.85,
                   [v.id for v in victims[:2]] or ([rng.choice(alive).id] if alive else []))
    elif name == "pandemic":
        if world.pandemic:
            return
        pool = [c for c in alive if not c.immune] or alive
        sociable = max(pool, key=lambda c: len(c.relationships) * (1 + c.personality["extraversion"]))
        _infect(world, sociable)
        world.pandemic = {"start": world.day, "deaths": 0, "cases": 1, "peak": 1, "name": kw.get("name", rng.choice(["the Grey Cough", "River Fever", "the Sweats", "the Autumn Sickness"]))}
        world.emit("disaster", f"{sociable.name} fell ill with something nobody recognises. They call it {world.pandemic['name']}.", 0.7, [sociable.id])
    elif name == "recession":
        world.recession_days = kw.get("days", 120)
        world.emit("economy", "Trade routes dried up. Demand for goods collapsed across the town.", 0.75,
                   [b.owner_id for b in world.open_businesses() if b.owner_id][:1])
    elif name == "boom":
        world.food += len(alive) * 15
        world.config["demand_multiplier"] = 1.5
        world.emit("economy", "A bumper harvest and merchants from afar: a boom season begins.", 0.6)
    elif name == "breakthrough":
        world.tech *= 1.15
        inventor = max(alive, key=lambda c: c.education * c.personality["openness"])
        world.emit("discovery", f"{inventor.name} devised a new technique that raised productivity across the town by 15%.", 0.8, [inventor.id])
        inventor.reputation += 0.3
        inventor.money += 500
    elif name == "automation":
        lost = []
        share = kw.get("share", 0.3)
        from . import economy
        for b in world.open_businesses():
            if b.kind in ("workshop", "mine", "market", "bakery"):
                b.productivity *= 1.6
                cut = [e for e in b.employees if e != b.owner_id]
                rng.shuffle(cut)
                for e in cut[:int(round(len(cut) * share))]:
                    c = world.citizens[e]
                    economy.leave_job(world, c, "automated")
                    c.remember(world.day, f"A machine now does what I did at {b.name}.", "fear", 0.7, tag="work")
                    lost.append(c)
        world.emit("economy", f"Machines arrived. {len(lost)} workers were replaced overnight; the businesses that kept them are far more productive.",
                   0.9, [c.id for c in lost[:3]])
    elif name == "raid":
        stolen = world.treasury * 0.5
        world.treasury -= stolen
        for b in world.open_businesses():
            b.cash *= 0.7
        adults = [c for c in alive if c.age_on(world.day) >= 16] or alive
        hurt = rng.sample(adults, min(6, len(adults)))
        dead = []
        for c in hurt:
            c.health -= 0.4
            if c.health <= 0.05:
                from . import lifecycle
                lifecycle.die(world, c, "raid")
                dead.append(c)
        world.emit("disaster", f"Bandits raided the town at night, stealing £{stolen:,.0f} from the treasury. {len(hurt)} were hurt, {len(dead)} killed.", 0.85,
                   [c.id for c in hurt[:3]])
        for c in alive:
            if c.alive:
                c.beliefs["authority"] = min(1, c.beliefs["authority"] + 0.1)
    elif name == "meteor_strike":
        from . import economy
        b = rng.choice(world.open_businesses())
        for e in list(b.employees):
            c = world.citizens[e]
            if rng.random() < 0.3:
                from . import lifecycle
                lifecycle.die(world, c, "meteor")
        economy.bankrupt(world, b)
        world.emit("disaster", f"A rock fell from the sky and flattened {b.name}.", 0.9)
    elif name == "immigration":
        from .. import world as W
        n = kw.get("n", 20)
        for _ in range(n):
            sex = rng.choice("FM")
            age = rng.randint(18, 45)
            c = Citizen(id=world._new_id(), name=world.new_name(sex), sex=sex, born_day=world.day - age * 365,
                        personality={k: float(np.clip(rng.gauss(0.5, 0.18), 0.02, 0.98)) for k in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")},
                        money=rng.uniform(50, 400), home=world._random_home(), education=rng.uniform(0.2, 0.8), skill=rng.uniform(0.2, 0.7), goal="earn money")
            c.pos = c.home
            c.surname = c.name.split()[-1]
            from . import politics
            c.beliefs = politics.initial_beliefs(world, c)
            world.citizens[c.id] = c
        world.emit("society", f"A caravan of {n} newcomers arrived, looking for work and somewhere to sleep.", 0.6)
    else:
        raise ValueError(f"Unknown injection {name!r}. Options: {', '.join(INJECTABLE)}")


def _near_water(world, x, y, r):
    y0, y1 = max(0, y - r), min(world.height, y + r + 1)
    x0, x1 = max(0, x - r), min(world.width, x + r + 1)
    return bool((world.grid[y0:y1, x0:x1] == terrain.WATER).any())


def _infect(world, c: Citizen):
    c.infected = True
    c.infected_day = world.day
    if world.pandemic:
        world.pandemic["cases"] += 1


def try_transmit(world, a: Citizen, b: Citizen):
    if a.infected == b.infected:
        return
    src, dst = (a, b) if a.infected else (b, a)
    if dst.immune or dst.infected:
        return
    if world.rng.random() < 0.12:
        _infect(world, dst)


def _pandemic_tick(world):
    p = world.pandemic
    rng = world.rng
    clinic = any(b.kind == "clinic" for b in world.open_businesses())
    infected = [c for c in world.alive() if c.infected]
    p["peak"] = max(p["peak"], len(infected))
    for c in infected:
        c.health -= 0.02
        if rng.random() < 0.006 * (1.5 - c.health) * (0.6 if clinic else 1.0) * (1.5 if c.age_on(world.day) > 60 else 1.0):
            from . import lifecycle
            lifecycle.die(world, c, "illness")
            p["deaths"] += 1
        elif world.day - c.infected_day > 14:
            c.infected = False
            c.immune = True
            c.remember(world.day, f"Recovered from {p['name']}.", "hope", 0.4, tag="disaster")
    if not infected and world.day - p["start"] > 20:
        world.emit("disaster", f"{p['name']} burned out after {world.day - p['start']} days: {p['cases']} fell ill, {p['deaths']} died.", 0.8)
        world.pandemic = None
    elif (world.day - p["start"]) % 30 == 0:
        world.emit("disaster", f"{p['name']}: {len(infected)} currently sick, {p['deaths']} dead so far.", 0.45)


def daily(world):
    rng = world.rng
    if world.pandemic:
        _pandemic_tick(world)
    if world.day % 30 == 0:
        starved = [c for c in world.citizens.values() if c.cause_of_death == "starvation" and c.died_day and world.day - c.died_day < 30]
        if len(starved) >= 3:
            world.emit("disaster", f"Famine: {len(starved)} people starved to death this month with bread at £{world.food_price:.0f}.",
                       0.85, [c.id for c in world.alive() if c.hunger > 0.6][:3])
    if world.recession_days > 0:
        world.recession_days -= 1
        if world.recession_days == 0:
            world.emit("economy", "Trade slowly recovered; the recession is over.", 0.5)
    if world.config["demand_multiplier"] > 1.0 and rng.random() < 0.01:
        world.config["demand_multiplier"] = 1.0
    if not world.config["random_shocks"]:
        return
    roll = rng.random()
    if roll < 0.0006:
        inject(world, "drought")
    elif roll < 0.0009:
        inject(world, "flood")
    elif roll < 0.0011 and not world.pandemic and world.day > 200:
        inject(world, "pandemic")
    elif roll < 0.0014 and world.recession_days == 0:
        inject(world, "recession")
    elif roll < 0.0020:
        inject(world, "boom")
    elif roll < 0.0022:
        inject(world, "raid")
    # discoveries come from educated, open people working in workshops
    if rng.random() < 0.002:
        inventors = [c for c in world.alive() if c.education > 0.75 and c.personality["openness"] > 0.7 and c.job in ("craftsperson", "teacher", "doctor", "miner")]
        if inventors:
            world.tech *= 1.05
            c = rng.choice(inventors)
            thing = rng.choice(["a better plough", "a water wheel", "a printing press", "a way to smelt iron", "a cure for river fever",
                                "double-entry bookkeeping", "a windmill", "concrete", "the steam engine", "electricity"])
            c.reputation += 0.25
            c.money += 400
            world.emit("discovery", f"{c.name} discovered {thing}. Productivity rose 5%.", 0.75, [c.id])
            c.remember(world.day, f"I discovered {thing}. They'll remember my name.", "pride", 0.9, tag="discovery")
