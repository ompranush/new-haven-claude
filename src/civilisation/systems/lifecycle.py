"""Lifecycle: needs, health, education, births, coming of age, deaths, inheritance."""
from __future__ import annotations
import math
import numpy as np
from ..models import Citizen, TRAITS, REL_FAMILY, REL_SPOUSE
from . import politics

ADULT_GOALS = ["earn money", "find a partner", "start a business", "help family", "learn a skill",
               "become respected", "have children", "see the world change"]


def _hazard(age: int, health: float, longevity: float) -> float:
    """Daily probability of dying. Gompertz curve scaled by health and the longevity knob."""
    yearly = 0.00025 * math.exp(0.085 * age / longevity) + 0.0008
    return yearly / 365 * (2.2 - 1.2 * health)


def daily(world):
    rng = world.rng
    cfg = world.config
    pol = world.policy
    school = next((b for b in world.open_businesses() if b.kind == "school"), None)
    clinic = next((b for b in world.open_businesses() if b.kind == "clinic"), None)
    school_quality = 0.0
    if school:
        school_quality = 0.5 + 0.5 * float(np.mean([world.citizens[e].skill for e in school.employees])) if school.employees else 0.3

    for c in world.alive():
        age = c.age_on(world.day)
        # --- health
        if c.hunger > 0.8:
            c.health -= 0.012
            c.happiness = max(0, c.happiness - 0.02)
        elif c.health < 1.0:
            recover = 0.0015 + (0.002 if clinic and (pol.public_health or c.money > 200) else 0)
            c.health = min(1.0, c.health + recover)
        if age > 60:
            c.health -= 0.00015 * (age - 60)
        c.health = float(np.clip(c.health, 0, 1))
        # --- mood baseline: drift toward a personality-determined set point
        setpoint = (0.42 + 0.25 * (c.personality["extraversion"] - c.personality["neuroticism"])
                    + 0.12 * min(1, c.money / 3000) + (0.06 if c.employer_id is not None else -0.04))
        c.happiness += (setpoint - c.happiness) * 0.03
        # --- children & education
        if 5 <= age < 18:
            if school and school_quality > 0:
                can_pay = pol.public_education or rng.random() < cfg["education_access"]
                if can_pay:
                    if not pol.public_education and c.parent_ids:
                        p = world.citizens.get(c.parent_ids[0])
                        if p and p.alive and p.money > 2:
                            p.money -= 2
                            school.cash += 2
                            school.revenue_today += 2
                    c.education = min(1.0, c.education + 0.00035 * school_quality)
            c.skill = min(1.0, 0.15 + c.education * 0.5)
        elif age >= 18 and c.job == "child":
            come_of_age(world, c)
        # --- goals nudge behaviour
        if c.goal == "earn money":
            c.goal_progress = min(1.0, c.money / 6000)
        elif c.goal == "learn a skill":
            c.goal_progress = c.skill
        elif c.goal == "become respected":
            c.goal_progress = float(np.clip((c.reputation + 1) / 2, 0, 1))
        elif c.goal == "have children":
            c.goal_progress = min(1.0, len(c.children) / 2)
        if c.goal_progress >= 1.0 and rng.random() < 0.05:
            c.remember(world.day, f"I finally did it: {c.goal}.", "pride", 0.5, tag="life")
            c.happiness = min(1, c.happiness + 0.1)
            c.goal = rng.choice([g for g in ADULT_GOALS if g != c.goal])
            c.goal_progress = 0.0
        # --- death
        p = _hazard(age, c.health, cfg["longevity"])
        if c.health <= 0.02:
            p = 0.5
        if rng.random() < p:
            cause = "starvation" if c.hunger > 0.8 else ("illness" if c.infected else ("old age" if age > 70 else "sickness"))
            die(world, c, cause)

    births(world)


def come_of_age(world, c: Citizen):
    rng = world.rng
    c.job = "unemployed"
    c.goal = rng.choice(ADULT_GOALS)
    c.beliefs = politics.initial_beliefs(world, c)
    if c.parent_ids:
        # children start with beliefs pulled toward their parents
        for p in c.parent_ids:
            par = world.citizens.get(p)
            if par:
                for k in c.beliefs:
                    c.beliefs[k] = c.beliefs[k] * 0.5 + par.beliefs.get(k, c.beliefs[k]) * 0.5
    c.happiness = 0.7
    world.emit("life", f"{c.name} came of age (education {c.education*100:.0f}%).", 0.25, [c.id])
    c.remember(world.day, "Eighteen. The town looks smaller than it used to.", "hope", 0.4, tag="life")


def births(world):
    rng = world.rng
    cfg = world.config
    alive = world.alive()
    if len(alive) >= cfg["max_population"]:
        return
    crowd = 1 - len(alive) / cfg["max_population"]
    for c in alive:
        if c.sex != "F" or not c.spouse_id:
            continue
        sp = world.citizens.get(c.spouse_id)
        if not sp or not sp.alive:
            continue
        age = c.age_on(world.day)
        if not (20 <= age <= 42):
            continue
        recent = any(k for k in c.children if world.day - world.citizens[k].born_day < 400)
        if recent:
            continue
        p = 0.0016 * cfg["fertility"] * crowd * (0.5 + c.happiness) * (0.6 if c.money + sp.money < 300 else 1.0)
        p *= max(0.3, 1 - 0.12 * len(c.children))
        if world.food < len(alive) * 2:
            p *= 0.4
        if rng.random() < p:
            baby = make_child(world, c, sp)
            first = not any(x.generation > 0 for x in world.citizens.values() if x.id != baby.id)
            world.emit("life", f"{baby.name} was born to {c.name} and {sp.name}" + (" — the first child born in the town." if first else "."),
                       0.65 if first else 0.45, [c.id, sp.id])


def make_child(world, a: Citizen, b: Citizen) -> Citizen:
    rng = world.rng
    sex = rng.choice("FM")
    surname = b.surname if b.sex == "M" else a.surname
    p = {}
    for k in TRAITS:
        w = rng.random()
        p[k] = float(np.clip(a.personality[k] * w + b.personality[k] * (1 - w) + rng.gauss(0, 0.08), 0.02, 0.98))
    child = Citizen(id=world._new_id(), name=world.new_name(sex, surname), sex=sex, born_day=world.day, personality=p,
                    money=0.0, job="child", home=a.home, pos=a.home, happiness=0.75, health=0.97,
                    education=0.05, skill=0.1, goal="grow up", parent_ids=[a.id, b.id],
                    generation=max(a.generation, b.generation) + 1, surname=surname)
    child.beliefs = {"economic": 0.0, "authority": 0.0, "trust": 0.6}
    world.citizens[child.id] = child
    for par in (a, b):
        par.children.append(child.id)
        par.rel(child.id).kind = REL_FAMILY
        par.rel(child.id).score = 80
        child.rel(par.id).kind = REL_FAMILY
        child.rel(par.id).score = 80
        par.happiness = min(1, par.happiness + 0.12)
    for sib in a.children:
        if sib != child.id:
            child.rel(sib).kind = world.citizens[sib].rel(child.id).kind = REL_FAMILY
            child.rel(sib).score = world.citizens[sib].rel(child.id).score = 50
    return child


def die(world, c: Citizen, cause: str):
    c.alive = False
    c.died_day = world.day
    c.cause_of_death = cause
    age = c.age_on(world.day)
    from . import economy
    if c.employer_id is not None:
        economy.leave_job(world, c, "died")
    # businesses they owned pass to spouse/child or close
    for b in world.businesses.values():
        if b.alive and b.owner_id == c.id:
            heir = None
            if c.spouse_id and world.citizens[c.spouse_id].alive:
                heir = c.spouse_id
            else:
                kids = [k for k in c.children if world.citizens[k].alive and world.citizens[k].age_on(world.day) >= 18]
                heir = kids[0] if kids else None
            if heir:
                b.owner_id = heir
                world.emit("economy", f"{world.citizens[heir].name} inherited {b.name}.", 0.35, [heir])
            else:
                b.owner_id = None
    # inheritance
    heirs = []
    if c.spouse_id and world.citizens[c.spouse_id].alive:
        heirs.append(world.citizens[c.spouse_id])
    heirs += [world.citizens[k] for k in c.children if world.citizens[k].alive]
    if heirs and c.money > 0:
        share = c.money / len(heirs)
        for h in heirs:
            h.money += share
    elif c.money > 0:
        world.treasury += c.money
    c.money = 0.0
    if c.movement_id:
        m = world.movements.get(c.movement_id)
        if m and c.id in m.members:
            m.members.remove(c.id)
    mourners = []
    if c.spouse_id and world.citizens[c.spouse_id].alive:
        sp = world.citizens[c.spouse_id]
        sp.spouse_id = None
        mourners.append(sp.id)
    mourners += [k for k in c.children if world.citizens[k].alive]
    mourners += [r.other_id for r in c.relationships.values() if r.score >= 50 and world.citizens[r.other_id].alive][:3]
    importance = 0.6 if cause in ("starvation", "illness", "flood", "raid") else (0.5 if age < 50 else 0.4)
    if age < 18:
        importance = 0.7
    world.emit("life", f"{c.name} died of {cause} at {age}.", importance, mourners[:3])
    for mid in mourners:
        m = world.citizens[mid]
        m.happiness = max(0, m.happiness - 0.1)
