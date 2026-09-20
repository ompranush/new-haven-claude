"""Social life: where people go, who they meet, what happens, what they remember.

Interactions are cheap arithmetic. Only *incidents* (insults, gifts, betrayals,
marriages) produce events and memories, and only the important ones reach the brain.
"""
from __future__ import annotations
import numpy as np
from ..models import (Citizen, REL_SPOUSE, REL_FAMILY, REL_FRIEND, REL_COLLEAGUE,
                      REL_ACQUAINTANCE, REL_RIVAL, REL_ENEMY)


def compatibility(a: Citizen, b: Citizen) -> float:
    return 1 - float(np.mean([abs(a.personality[k] - b.personality[k]) for k in a.personality]))


def _rekind(r, other_r):
    if r.kind in (REL_SPOUSE, REL_FAMILY):
        return
    s = r.score
    if s >= 45:
        r.kind = REL_FRIEND
    elif s <= -55:
        r.kind = REL_ENEMY
    elif s <= -25:
        r.kind = REL_RIVAL
    elif r.kind in (REL_FRIEND, REL_RIVAL, REL_ENEMY):
        r.kind = REL_ACQUAINTANCE


def adjust(world, a: Citizen, b: Citizen, delta: float):
    """Symmetric-ish relationship change; b feels ~70% of what a feels."""
    ra, rb = a.rel(b.id), b.rel(a.id)
    # diminishing returns near the extremes: it is hard to love or hate someone more than you already do
    def damp(score, d):
        same_dir = (d > 0 and score > 0) or (d < 0 and score < 0)
        return d * (1 - abs(score) / 105) if same_dir else d
    ra.score = float(np.clip(ra.score + damp(ra.score, delta), -100, 100))
    rb.score = float(np.clip(rb.score + damp(rb.score, delta * 0.7), -100, 100))
    ra.last_interaction = rb.last_interaction = world.day
    ra.interactions += 1
    rb.interactions += 1
    _rekind(ra, rb)
    _rekind(rb, ra)


def _move(world, c: Citizen):
    """Daytime location. Rendering only — but proximity feeds who meets whom."""
    rng = world.rng
    if c.infected and c.health < 0.5:
        c.pos = c.home
        return
    if c.employer_id is not None and (not world.strike or c.id not in world.strike["members"]):
        b = world.businesses[c.employer_id]
        c.pos = (b.x + rng.randint(-1, 1), b.y + rng.randint(-1, 1))
    elif c.age_on(world.day) < 18:
        school = next((b for b in world.open_businesses() if b.kind == "school"), None)
        c.pos = (school.x + rng.randint(-1, 1), school.y + rng.randint(-1, 1)) if school and rng.random() < 0.7 else c.home
    else:
        taverns = [b for b in world.open_businesses() if b.kind in ("tavern", "market")]
        if taverns and rng.random() < 0.3 + 0.4 * c.personality["extraversion"]:
            t = rng.choice(taverns)
            c.pos = (t.x + rng.randint(-2, 2), t.y + rng.randint(-2, 2))
        else:
            c.pos = (c.home[0] + rng.randint(-2, 2), c.home[1] + rng.randint(-2, 2))
    c.pos = (int(np.clip(c.pos[0], 0, world.width - 1)), int(np.clip(c.pos[1], 0, world.height - 1)))


def _pick_partner(world, c: Citizen, alive_ids, by_pos):
    rng = world.rng
    roll = rng.random()
    if roll < 0.35 and c.employer_id is not None:
        col = [e for e in world.businesses[c.employer_id].employees if e != c.id]
        if col:
            return world.citizens[rng.choice(col)]
    if roll < 0.6 and c.relationships:
        rels = [r for r in c.relationships.values() if r.other_id in alive_ids]
        if rels:
            weights = [max(1.0, 20 + r.score) for r in rels]
            return world.citizens[rng.choices(rels, weights=weights)[0].other_id]
    if roll < 0.85:
        near = by_pos.get((c.pos[0] // 6, c.pos[1] // 6), [])
        near = [n for n in near if n != c.id]
        if near:
            return world.citizens[rng.choice(near)]
    other = rng.choice(alive_ids)
    return world.citizens[other] if other != c.id else None


def interact(world, a: Citizen, b: Citizen):
    rng = world.rng
    comp = compatibility(a, b)
    ra = a.rel(b.id)
    mood = (a.happiness + b.happiness) / 2
    p_pos = 0.5 + 0.6 * (comp - 0.5) + 0.3 * (mood - 0.5) + 0.15 * (a.personality["agreeableness"] + b.personality["agreeableness"] - 1)
    p_pos += 0.002 * ra.score        # history breeds more of the same
    if a.movement_id and b.movement_id and a.movement_id != b.movement_id:
        p_pos -= 0.2
    if rng.random() < p_pos:
        adjust(world, a, b, rng.uniform(1.5, 5))
        a.happiness = min(1, a.happiness + 0.003)
        b.happiness = min(1, b.happiness + 0.002)
        # generosity incident
        if b.money < 60 and a.money > 600 and a.personality["agreeableness"] > 0.65 and rng.random() < 0.08:
            gift = min(120, a.money * 0.08)
            a.money -= gift
            b.money += gift
            adjust(world, b, a, 18)
            world.emit("social", f"{a.name} helped {b.name} with £{gift:.0f} when they had nothing.", 0.45, [b.id, a.id], tone="good")
    else:
        adjust(world, a, b, -rng.uniform(1.5, 5))
        a.happiness = max(0, a.happiness - 0.004)
        # insult incident
        p_insult = 0.05 * (1 - a.personality["agreeableness"]) * (0.5 + a.personality["neuroticism"]) * (1.5 - mood)
        if rng.random() < p_insult:
            public = rng.random() < 0.4
            adjust(world, b, a, -rng.uniform(10, 22))
            from ..personality import insult_text
            world.emit("social", insult_text(world, a, b, public), 0.45 if public else 0.35, [b.id, a.id], tone="bad")
            if public:
                a.reputation -= 0.05
    # grievance is contagious
    if ra.score > 20 and abs(a.grievance - b.grievance) > 0.2:
        m = (a.grievance + b.grievance) / 2
        a.grievance += (m - a.grievance) * 0.08
        b.grievance += (m - b.grievance) * 0.08
    # pandemic transmission
    if world.pandemic:
        from . import disasters
        disasters.try_transmit(world, a, b)


def _romance(world, a: Citizen, b: Citizen):
    rng = world.rng
    if a.spouse_id or b.spouse_id or a.id == b.id:
        return
    if a.age_on(world.day) < 20 or b.age_on(world.day) < 20:
        return
    if b.id in a.parent_ids or a.id in b.parent_ids or (a.parent_ids and set(a.parent_ids) & set(b.parent_ids)):
        return
    if a.rel(b.id).score >= 55 and compatibility(a, b) > 0.6 and rng.random() < 0.03:
        a.spouse_id, b.spouse_id = b.id, a.id
        a.rel(b.id).kind = b.rel(a.id).kind = REL_SPOUSE
        a.rel(b.id).score = b.rel(a.id).score = max(a.rel(b.id).score, 75)
        b.home = a.home
        for x in (a, b):
            x.happiness = min(1, x.happiness + 0.15)
            if x.goal == "find a partner":
                x.goal_progress = 1.0
        first = not any(x.spouse_id for x in world.alive() if x.id not in (a.id, b.id))
        world.emit("society", f"{a.name} and {b.name} got married" + (" — the first wedding in the town's history." if first else "."),
                   0.7 if first else 0.5, [a.id, b.id])
        for f in _friends(world, a)[:3] + _friends(world, b)[:3]:
            f.remember(world.day, f"Danced at {a.name} and {b.name}'s wedding.", "joy", 0.35, [a.id, b.id], tag="social")


def _friends(world, c: Citizen):
    return [world.citizens[r.other_id] for r in c.relationships.values() if r.score >= 45 and world.citizens[r.other_id].alive]


def gossip(world, c: Citizen):
    """Share the most vivid recent memory with a friend. Reputations move."""
    rng = world.rng
    friends = _friends(world, c)
    if not friends or not c.memories:
        return
    recent = [m for m in c.memories if world.day - m.day < 30 and m.importance >= 0.4 and m.about]
    if not recent:
        return
    m = max(recent, key=lambda x: x.importance)
    f = rng.choice(friends)
    if any(x.text.startswith("Heard from") and x.day == m.day for x in f.memories):
        return
    f.remember(world.day, f"Heard from {c.name}: {m.text}", m.emotion, m.importance * 0.5, m.about, tag="rumour")
    for subject in m.about:
        s = world.citizens.get(subject)
        if s and s.alive and subject != f.id:
            sign = -1 if m.emotion in ("anger", "fear", "shame") else 1
            f.rel(subject).score = float(np.clip(f.rel(subject).score + sign * 4, -100, 100))
            s.reputation = float(np.clip(s.reputation + sign * 0.01, -1, 1))


def daily(world):
    rng = world.rng
    alive = world.alive()
    if len(alive) < 2:
        return
    for c in alive:
        _move(world, c)
    by_pos = {}
    for c in alive:
        by_pos.setdefault((c.pos[0] // 6, c.pos[1] // 6), []).append(c.id)
    alive_ids = [c.id for c in alive]
    for a in alive:
        if a.age_on(world.day) < 14:
            continue
        n = 1 + (1 if rng.random() < a.personality["extraversion"] else 0)
        if a.infected and a.health < 0.5:
            n = 1 if rng.random() < 0.3 else 0
        for _ in range(n):
            b = _pick_partner(world, a, alive_ids, by_pos)
            if b is None or b.id == a.id or not b.alive:
                continue
            interact(world, a, b)
            _romance(world, a, b)
        if rng.random() < 0.15:
            gossip(world, a)
        # spouses top each other up; long neglect erodes
        if a.spouse_id:
            sp = world.citizens[a.spouse_id]
            if sp.alive and rng.random() < 0.5:
                adjust(world, a, sp, rng.uniform(-1, 2.5))
        # loneliness
        if not any(r.score >= 30 for r in a.relationships.values()):
            a.happiness = max(0, a.happiness - 0.004)
    # relationship memory fades
    if world.day % 30 == 0:
        for c in alive:
            for r in c.relationships.values():
                if r.kind not in (REL_SPOUSE, REL_FAMILY) and world.day - r.last_interaction > 90:
                    r.score *= 0.93
            for m in c.memories:
                m.importance *= 0.985 if m.emotion in ("anger", "grief") else 0.97
