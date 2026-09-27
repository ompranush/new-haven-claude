"""Crime and justice. Nothing here stops anyone doing anything — it decides what happens *after*.

`commit()` records an offence, tells the victim (who reacts through the behaviour engine),
lets witnesses talk, and gives the village's police a chance to catch the offender. What a
caught offender gets depends on the government: a strict (high-authority) village jails long,
exiles and hangs; a lenient one fines. Police are people too: the corruptible ones take bribes.
"""
from __future__ import annotations
import numpy as np

# base chance the police solve it, and how bad it is (0..1)
CRIMES = {
    "theft":      dict(solve=0.30, sev=0.25, word="stole from"),
    "burglary":   dict(solve=0.25, sev=0.35, word="burgled"),
    "fraud":      dict(solve=0.20, sev=0.30, word="swindled"),
    "embezzlement": dict(solve=0.25, sev=0.45, word="embezzled from"),
    "extortion":  dict(solve=0.30, sev=0.45, word="extorted"),
    "vandalism":  dict(solve=0.25, sev=0.20, word="vandalised"),
    "assault":    dict(solve=0.45, sev=0.50, word="attacked"),
    "arson":      dict(solve=0.35, sev=0.75, word="set fire to"),
    "poisoning":  dict(solve=0.30, sev=0.90, word="poisoned"),
    "murder":     dict(solve=0.55, sev=1.00, word="murdered"),
    "smuggling":  dict(solve=0.20, sev=0.25, word="smuggled"),
    "looting":    dict(solve=0.20, sev=0.35, word="looted"),
    "treason":    dict(solve=0.35, sev=0.95, word="betrayed"),
    "rioting":    dict(solve=0.35, sev=0.40, word="rioted against"),
    "desertion":  dict(solve=0.50, sev=0.55, word="deserted"),
}


def police_strength(world) -> float:
    """0..1-ish: how likely the focused village's watch is to solve a case."""
    alive = world.alive()
    police = [c for c in alive if c.role == "police" and world.free(c)]
    if not alive:
        return 0.0
    per_capita = len(police) / max(1.0, len(alive) / 25.0)             # one officer per 25 people is "normal"
    skill = float(np.mean([0.5 + c.skill for c in police])) if police else 0.0
    trust = float(np.mean([c.beliefs.get("trust", 0.5) for c in alive]))
    curfew = 1.3 if "curfew" in world.policy.laws else 1.0
    occupied = 0.7 if world.village.occupier is not None else 1.0
    return float(np.clip(per_capita * skill * (0.6 + 0.6 * trust) * curfew * occupied, 0.05, 1.6))


def commit(world, offender, kind: str, victim=None, text: str = "", importance: float = 0.5, business=None,
           witnesses: int = 0, fx: str = "") -> bool:
    """Record an offence and run the law on it. Returns True if the offender was caught."""
    spec = CRIMES.get(kind, CRIMES["theft"])
    v = world.village
    v.crime_today += 1
    v.crimes_year += 1
    offender.crimes += 1
    if kind == "murder":
        v.murders_year += 1
    actors = ([victim.id] if victim is not None else []) + [offender.id]
    if business is not None and business.owner_id and (victim is None or business.owner_id != victim.id):
        actors.append(business.owner_id)
    ev = world.emit("crime", text or f"{offender.name} {spec['word']} {victim.name if victim else 'someone'}.",
                    importance, actors, tone="bad", kind=f"crime_{kind}")
    if fx:
        world.add_fx(fx, *(offender.pos if victim is None else victim.pos), days=3)
    # the law
    p = spec["solve"] * police_strength(world) * (1.0 + 0.35 * witnesses)
    p *= 1.0 - 0.5 * offender.personality["conscientiousness"] * offender.skill       # careful, capable criminals are harder to catch
    if world.rng.random() < min(0.95, p):
        arrest(world, offender, kind, victim)
        return True
    if victim is not None and kind in ("murder", "assault", "arson", "poisoning") and world.rng.random() < 0.35:
        # the victim's people know who did it, even if the watch can't prove it
        kin = [world.citizens[k] for k in (victim.children + ([victim.spouse_id] if victim.spouse_id else []) + victim.parent_ids)
               if k in world.citizens and world.citizens[k].alive and k != offender.id]
        for k in kin[:3]:
            k.rel(offender.id).score = max(-100, k.rel(offender.id).score - 45)
            k.remember(world.day, f"Everyone knows it was {offender.name}. The watch did nothing.", "anger", 0.85, [offender.id], tag="crime")
            k.emotions["anger"] = min(1.0, k.feel("anger") + 0.4)
    return False


def arrest(world, c, kind: str, victim=None):
    """Caught. A crooked officer might look the other way for a price."""
    rng = world.rng
    v = world.village
    spec = CRIMES.get(kind, CRIMES["theft"])
    police = [p for p in world.alive() if p.role == "police" and world.free(p)]
    officer = rng.choice(police) if police else None
    if officer is not None and c.money > 150:
        greed = (1 - officer.personality["conscientiousness"]) * (1 - officer.personality["agreeableness"])
        if rng.random() < greed * 1.6 * (1 - 0.6 * spec["sev"]):
            bribe = min(c.money * 0.4, 150 + 600 * spec["sev"])
            c.money -= bribe
            officer.money += bribe
            officer.crimes += 1
            world.emit("crime", f"{officer.name} of the watch took £{bribe:.0f} to let {c.name} walk away from a charge of {kind}.",
                       0.45, [c.id, officer.id], tone="good", kind="bribe_taken", secret=True)
            return
    v.arrests_year += 1
    c.convictions += 1
    authority = world.policy.platform.get("authority", 0.0)
    harsh = float(np.clip(0.5 + 0.5 * authority, 0.1, 1.0))
    sev = spec["sev"] * (1 + 0.25 * (c.convictions - 1))
    if kind in ("murder", "treason") and harsh > 0.6 and rng.random() < harsh - 0.35:
        from . import lifecycle
        world.emit("justice", f"{c.name} was hanged in {v.name} for {kind}.", 0.85, [c.id] + ([victim.id] if victim else []),
                   tone="bad", kind="executed")
        lifecycle.die(world, c, "execution")
        return
    if sev > 0.6 and harsh > 0.45 and rng.random() < 0.4:
        exile(world, c, f"for {kind}")
        return
    days = int(10 + 400 * sev * harsh * rng.uniform(0.6, 1.4))
    fine = min(c.money, 80 + 500 * sev)
    c.money -= fine
    world.treasury += fine
    c.jailed_until = world.day + days
    c.reputation = float(np.clip(c.reputation - 0.15 - 0.3 * sev, -1, 1))
    if c.employer_id is not None and days > 20:
        from . import economy
        economy.leave_job(world, c, "jailed")
    if c.role:
        world.emit("politics", f"{c.name} was stripped of office as {c.role}.", 0.5, [c.id], tone="bad")
        c.role = ""
    world.emit("justice", f"{c.name} was arrested for {kind}: fined £{fine:.0f} and jailed for {days} days.", 0.5 + 0.3 * sev,
               [c.id] + ([victim.id] if victim else []), tone="bad", kind="jailed")


def exile(world, c, why: str = ""):
    """Thrown out. They go to whichever village will have them — or into the wild, where they die."""
    rng = world.rng
    home = c.village
    options = [o for o in world.villages if o.idx != home and not o.fallen]
    world.emit("justice", f"{c.name} was exiled from {world.villages[home].name} {why}.".replace("  ", " "), 0.65, [c.id],
               tone="bad", kind="exiled")
    if not options:
        from . import lifecycle
        lifecycle.die(world, c, "exile in the wilds")
        return
    dest = min(options, key=lambda o: o.tension.get(home, 0.5) * -1 + rng.random())      # enemies of your enemy take you in
    relocate(world, c, dest.idx, reason="exile")
    c.exiled_from = home


def relocate(world, c, dest: int, reason: str = "moved"):
    """Move someone (and their dependent children) to another village."""
    from . import economy
    if c.employer_id is not None:
        economy.leave_job(world, c, reason)
    if c.movement_id:
        m = world.movements.get(c.movement_id)
        if m and c.id in m.members:
            m.members.remove(c.id)
        c.movement_id = None
    c.role = ""
    party = [c] + [world.citizens[k] for k in c.children if k in world.citizens and world.citizens[k].alive
                   and world.citizens[k].age_on(world.day) < 18 and world.citizens[k].village == c.village]
    with world.at(dest):
        home = world._random_home()
        for p in party:
            p.village = dest
            p.home = home
            p.pos = home
        economy.hire_anyone(world, c)
        world.emit("society", f"{c.name} arrived in {world.villages[dest].name} ({reason}).", 0.35, [c.id], kind="arrived")


def release_due(world):
    for c in world.alive():
        if c.jailed_until == world.day:
            c.remember(world.day, "They let me out. The light hurts.", "hope", 0.5, tag="crime")
            world.emit("justice", f"{c.name} walked out of the cells.", 0.3, [c.id], kind="released")
