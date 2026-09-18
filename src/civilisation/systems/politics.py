"""Politics: beliefs, grievance, emergent movements, strikes, elections, revolts.

Nobody scripts a party. Beliefs drift with material conditions and with friends;
grievance accumulates from hardship; charismatic, aggrieved people found
movements; movements recruit through the social graph; large movements become
parties and contest elections; the winner's platform sets policy, which changes
the economy, which changes beliefs. That loop is the whole point.
"""
from __future__ import annotations
import numpy as np
from ..models import Citizen, Movement, Policy
from ..names import MOVEMENT_ADJ, MOVEMENT_NOUN

FOUNDERS = {"economic": 0.15, "authority": 0.1}


def initial_beliefs(world, c: Citizen) -> dict:
    rng = world.rng
    alive = world.alive()
    wealthier = sum(1 for x in alive if x.money < c.money) / max(1, len(alive)) if alive else 0.5
    econ = (wealthier - 0.5) * 1.2 + (c.personality["conscientiousness"] - 0.5) * 0.5 - (c.personality["openness"] - 0.5) * 0.4
    auth = (c.personality["neuroticism"] - 0.5) * 0.8 - (c.personality["openness"] - 0.5) * 0.8 + (c.personality["conscientiousness"] - 0.5) * 0.3
    return {"economic": float(np.clip(econ + rng.gauss(0, 0.2), -1, 1)),
            "authority": float(np.clip(auth + rng.gauss(0, 0.2), -1, 1)),
            "trust": float(np.clip(0.6 + rng.gauss(0, 0.15), 0, 1))}


def _drift(world):
    """Weekly: material conditions and friends pull beliefs; hardship builds grievance."""
    alive = world.alive()
    adults = [c for c in alive if c.age_on(world.day) >= 18]
    if not adults:
        return
    money = np.array([c.money for c in adults])
    order = money.argsort().argsort() / max(1, len(adults) - 1)
    gini = world.gini
    pol = world.policy
    for c, pct in zip(adults, order):
        b = c.beliefs
        hardship = 0.0
        if c.employer_id is None and c.age_on(world.day) < 65:
            hardship += 0.05 + 0.01 * min(5, c.unemployed_days // 30)
        if c.hunger > 0.6:
            hardship += 0.08
        if world.food_price > 6 and c.money < 1500:
            hardship += 0.03
        if pct < 0.25 and gini > 0.4:
            hardship += 0.03
        if c.happiness < 0.45:
            hardship += 0.03
        if c.infected:
            hardship += 0.02
        if world.strike and c.employer_id is not None and c.id not in world.strike["members"]:
            hardship += 0.01
        relief = 0.015 if (c.employer_id is not None and c.happiness > 0.6) else 0.0
        if pol.welfare > 0 and c.employer_id is None:
            relief += 0.015
        c.grievance = float(np.clip(c.grievance + hardship * (0.6 + 0.8 * c.personality["neuroticism"]) - relief - 0.003, 0, 1))
        # beliefs regress toward an anchor set by material position and temperament, then get pushed by
        # hardship, the tax bill, and friends. Without the anchor the whole town drifts into one corner.
        P = c.personality
        anchor_e = (pct - 0.5) * 1.2 + (P["conscientiousness"] - 0.5) * 0.5 - (P["openness"] - 0.5) * 0.4
        anchor_a = (P["neuroticism"] - 0.5) * 0.8 - (P["openness"] - 0.5) * 0.8 - 0.4 * c.education + 0.4 * c.grievance
        b["economic"] += (anchor_e - b["economic"]) * 0.04 - 0.03 * hardship + 0.02 * (pol.tax_rate - 0.15) * (pct - 0.5) * 10
        b["authority"] += (anchor_a - b["authority"]) * 0.04
        b["trust"] = float(np.clip(b["trust"] - 0.03 * hardship + 0.01 * relief + 0.01 * (0.5 - b["trust"]), 0, 1))
        # social influence
        friends = [world.citizens[r.other_id] for r in c.relationships.values() if r.score >= 40 and world.citizens[r.other_id].alive]
        if friends:
            for k in ("economic", "authority"):
                mean = float(np.mean([f.beliefs.get(k, 0) for f in friends]))
                b[k] += (mean - b[k]) * 0.02 * (1 - P["conscientiousness"] * 0.5)
        b["economic"] = float(np.clip(b["economic"], -1, 1))
        b["authority"] = float(np.clip(b["authority"], -1, 1))
        if c.movement_id:
            m = world.movements.get(c.movement_id)
            if m and m.alive:
                for k in ("economic", "authority"):
                    b[k] += (m.platform[k] - b[k]) * 0.04
                c.happiness = min(1, c.happiness + 0.002)   # belonging


def _theme(world, c: Citizen) -> str:
    if c.hunger > 0.5 or world.food_price > 6:
        return "hunger"
    if c.employer_id is None:
        return "unemployment"
    if world.gini > 0.45:
        return "inequality"
    if world.pandemic:
        return "the sickness"
    return "hardship"


def try_found_movement(world, c: Citizen, force: bool = False) -> bool:
    rng = world.rng
    if c.movement_id is not None or not c.alive or c.age_on(world.day) < 18:
        return False
    friends = [world.citizens[r.other_id] for r in c.relationships.values() if r.score >= 35 and world.citizens[r.other_id].alive]
    angry_friends = [f for f in friends if f.grievance > 0.35 and f.movement_id is None]
    if not force:
        last = max((m.founded_day for m in world.movements.values()), default=-999)
        if world.day - last < 90:            # one uprising at a time, please
            return False
        if c.grievance < 0.5 or c.personality["extraversion"] < 0.55 or len(angry_friends) < 2:
            return False
        if rng.random() > 0.06 * len(angry_friends):
            return False
    theme = _theme(world, c)
    name = f"{rng.choice(MOVEMENT_ADJ)} {rng.choice(MOVEMENT_NOUN)}"
    while any(m.name == name for m in world.movements.values()):
        name = f"{rng.choice(MOVEMENT_ADJ)} {rng.choice(MOVEMENT_NOUN)}"
    platform = {"economic": float(np.clip(c.beliefs["economic"] - 0.2, -1, 1)),
                "authority": float(np.clip(c.beliefs["authority"], -1, 1))}
    m = Movement(id=world._next_mid, name=name, founder_id=c.id, founded_day=world.day, platform=platform,
                 members=[c.id], grievance_theme=theme)
    world._next_mid += 1
    world.movements[m.id] = m
    c.movement_id = m.id
    for f in angry_friends[:4]:
        f.movement_id = m.id
        m.members.append(f.id)
    c.reputation += 0.1
    c.remember(world.day, f"I founded the {name}. Enough is enough.", "pride", 0.9, tag="politics")
    world.emit("politics", f"{c.name} founded the {name}, a movement against {theme}. {len(m.members)} joined on the first day.",
               0.75, [c.id])
    return True


def _recruit(world):
    rng = world.rng
    live = [m for m in world.movements.values() if m.alive]
    if not live:
        return
    adults = world.adults()
    for c in adults:
        if c.movement_id is not None or c.grievance < 0.35:
            continue
        for r in c.relationships.values():
            if r.score < 30:
                continue
            f = world.citizens[r.other_id]
            if f.alive and f.movement_id is not None:
                m = world.movements[f.movement_id]
                if not m.alive:
                    continue
                dist = abs(m.platform["economic"] - c.beliefs["economic"]) + abs(m.platform["authority"] - c.beliefs["authority"])
                if rng.random() < 0.25 * c.grievance * max(0, 1 - dist / 2):
                    c.movement_id = m.id
                    m.members.append(c.id)
                    c.remember(world.day, f"{f.name} brought me into the {m.name}.", "hope", 0.5, [f.id], tag="politics")
                    break
    # leaving, dissolving, becoming a party
    n_adults = max(1, len(adults))
    for m in live:
        for cid in list(m.members):
            c = world.citizens[cid]
            if not c.alive:
                m.members.remove(cid)
            elif c.grievance < 0.1 and rng.random() < 0.05 and cid != m.founder_id:
                m.members.remove(cid)
                c.movement_id = None
        founder = world.citizens[m.founder_id]
        if len(m.members) < 3 and (not founder.alive or founder.grievance < 0.3):
            m.alive = False
            for cid in m.members:
                world.citizens[cid].movement_id = None
            world.emit("politics", f"The {m.name} quietly dissolved.", 0.5, [m.founder_id])
            continue
        if not m.is_party and len(m.members) >= max(8, 0.12 * n_adults):
            m.is_party = True
            m.name = m.name.replace("Movement", "Party").replace("Front", "Party") if "Party" not in m.name else m.name
            world.emit("politics", f"The {m.name} now counts {len(m.members)} members ({100*len(m.members)/n_adults:.0f}% of adults) "
                                   f"and declared itself a political party.", 0.8, [m.founder_id])
        # strikes
        avg_g = float(np.mean([world.citizens[i].grievance for i in m.members])) if m.members else 0
        # nobody strikes the fields when bread is dear, and a movement needs to recover between strikes
        workers = [i for i in m.members if world.citizens[i].employer_id is not None
                   and not (world.food_price > 4 and world.citizens[i].job == "farmer")]
        rested = world.day - getattr(m, "last_strike_day", -999) > 180
        if world.strike is None and rested and avg_g > 0.7 and len(workers) >= 4 and rng.random() < 0.3:
            m.last_strike_day = world.day
            world.strike = {"movement": m.id, "members": workers, "until": world.day + rng.randint(5, 14)}
            world.emit("politics", f"{len(workers)} members of the {m.name} went on strike over {m.grievance_theme}.", 0.85, [m.founder_id])
            for i in workers:
                world.citizens[i].remember(world.day, f"We downed tools. The {m.name} is on strike.", "pride", 0.6, tag="politics")


def _strike(world):
    if not world.strike:
        return
    if world.day >= world.strike["until"]:
        m = world.movements[world.strike["movement"]]
        # employers concede if they were losing money
        concede = world.rng.random() < 0.5
        for i in world.strike["members"]:
            c = world.citizens[i]
            if c.alive and c.employer_id:
                b = world.businesses[c.employer_id]
                if concede:
                    b.wage *= 1.12
                    c.grievance = max(0, c.grievance - 0.25)
                elif world.rng.random() < 0.15:
                    from . import economy
                    economy.leave_job(world, c, "fired")
                    world.emit("work", f"{c.name} was fired for striking.", 0.5, [c.id])
        world.emit("politics", f"The strike ended. {'Employers raised wages by 12%.' if concede else 'Employers refused to budge.'}", 0.7, [m.founder_id])
        world.strike = None


def apply_platform(world, platform: dict, ruling: str):
    e = platform["economic"]
    pol = world.policy
    pol.ruling_party = ruling
    pol.tax_rate = float(np.clip(0.16 - 0.14 * e, 0.04, 0.35))
    pol.welfare = 9.0 if e < -0.2 else (4.0 if e < 0.15 else 0.0)
    pol.pension = 8.0 if e < -0.1 else (3.0 if e < 0.3 else 0.0)
    pol.min_wage = world.config["base_wage"] * 0.8 if e < -0.3 else 0.0
    pol.public_education = e < 0.05
    pol.public_health = e < 0.2


def election(world, snap: bool = False):
    rng = world.rng
    adults = world.adults()
    if not adults:
        return
    parties = [m for m in world.movements.values() if m.alive and m.is_party]
    incumbent_name = world.policy.ruling_party
    incumbent_platform = next((m.platform for m in parties if m.name == incumbent_name), FOUNDERS)
    candidates = {"Founders' Council": FOUNDERS} if incumbent_name == "Founders' Council" or not parties else {}
    candidates[incumbent_name] = incumbent_platform
    for m in parties:
        candidates[m.name] = m.platform
    votes = {k: 0 for k in candidates}
    turnout = 0
    for c in adults:
        if rng.random() > 0.35 + 0.4 * c.beliefs["trust"] + 0.3 * c.grievance:
            continue
        turnout += 1
        best, best_d = None, 9
        for name, plat in candidates.items():
            d = abs(plat["economic"] - c.beliefs["economic"]) + abs(plat["authority"] - c.beliefs["authority"]) + rng.gauss(0, 0.25)
            if c.movement_id and world.movements[c.movement_id].name == name:
                d -= 0.5
            if name == incumbent_name:
                d += 0.6 * c.grievance - 0.3 * c.beliefs["trust"]
            if d < best_d:
                best, best_d = name, d
        votes[best] += 1
    winner = max(votes, key=votes.get)
    total = max(1, sum(votes.values()))
    bars = "  ".join(f"{k} {100*v/total:.0f}%" for k, v in sorted(votes.items(), key=lambda kv: -kv[1]))
    changed = winner != incumbent_name
    apply_platform(world, candidates[winner], winner)
    for m in parties:
        m.seats_won = votes.get(m.name, 0)
        for i in m.members:
            c = world.citizens[i]
            if m.name == winner:
                c.grievance = max(0, c.grievance - 0.3)
                c.beliefs["trust"] = min(1, c.beliefs["trust"] + 0.15)
                c.happiness = min(1, c.happiness + 0.1)
            else:
                c.grievance = min(1, c.grievance + 0.05)
    lead = next((m.founder_id for m in parties if m.name == winner), None)
    kind = "Snap election" if snap else f"Election of year {world.year}"
    world.emit("politics", f"{kind}: {winner} {'took power' if changed else 'held on'} with {100*votes[winner]/total:.0f}% "
                           f"(turnout {100*turnout/len(adults):.0f}%). {bars}. "
                           f"Policy now: tax {world.policy.tax_rate*100:.0f}%, welfare £{world.policy.welfare:.0f}/day, "
                           f"{'public' if world.policy.public_education else 'private'} schooling.", 0.9 if changed else 0.6,
               [lead] if lead else [])
    for c in adults:
        if rng.random() < 0.3:
            c.remember(world.day, f"Voted in the election. {winner} won.", "hope" if changed else "neutral", 0.4, tag="politics")
    world.next_election_day = world.day + world.config["election_period_days"]


def daily(world):
    if world.day % 7 == 0:
        _drift(world)
        adults = world.adults()
        for c in adults:
            try_found_movement(world, c)
        _recruit(world)
        # revolt: mass anger + no trust → snap election
        if adults and world.day > 365:
            g = float(np.mean([c.grievance for c in adults]))
            t = float(np.mean([c.beliefs["trust"] for c in adults]))
            if g > 0.7 and t < 0.35 and world.rng.random() < 0.25:
                world.emit("politics", f"Riots in the square: with grievance at {g*100:.0f}% and trust at {t*100:.0f}%, "
                                       f"the {world.policy.ruling_party} was forced to call a snap election.", 1.0,
                           [max(adults, key=lambda c: c.grievance).id])
                election(world, snap=True)
    _strike(world)
    if world.day >= world.next_election_day:
        election(world)
