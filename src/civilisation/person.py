"""Steward controls: what a sponsor can make *their own* citizen do.

Interventions, not puppetry — the person keeps living their daily life; the steward
nudges goals, work, home, relationships, politics and money, or gives free-text
instructions that their own model turns into these ops. Every op is an event the
town notices, and the citizen remembers it in their own words.
"""
from __future__ import annotations
import json
import random
from typing import Optional

import numpy as np

from .systems import economy, social, politics
from .systems.lifecycle import ADULT_GOALS
from .models import Movement

PERSON_OPS = {
    "goal": "Change what they are striving for. params: {goal: one of %s}" % "|".join(ADULT_GOALS),
    "work": "Change their work. params: {action: apply|quit|found, business?: existing business name (apply), kind?: farm|bakery|workshop|market|mine|tavern|school|clinic (found)}",
    "move": "Move house. params: {near?: full name of someone to live near}",
    "visit": "Spend time with someone to build the relationship. params: {who: full name}",
    "confront": "Have it out with someone (relationship drops, grievance eases). params: {who: full name}",
    "propose": "Propose marriage (needs a warm relationship, both single). params: {who: full name}",
    "give": "Give money to someone. params: {who: full name|poorest, amount: £}",
    "movement": "Politics. params: {action: join|leave|found, name?: movement name (join/found), theme?: what it is against (found)}",
    "persuade": "Argue politics with someone, nudging their beliefs toward yours. params: {who: full name}",
    "note": "Remember something / resolve something (a diary line in their voice). params: {text: first-person line, emotion?: joy|grief|anger|fear|pride|shame|hope|neutral}",
}


def describe_person_options(world, c) -> str:
    bs = [f"{b.name} ({b.kind}, {len(b.employees)} staff, wage £{b.wage:.0f})" for b in world.open_businesses()]
    rels = sorted(c.relationships.values(), key=lambda r: -abs(r.score))[:8]
    movs = [f"{m.name} (against {m.grievance_theme})" for m in world.movements.values() if m.alive]
    return ("Businesses: " + "; ".join(bs) + "\nPeople they know: " + "; ".join(f"{world.citizens[r.other_id].name} ({r.kind} {r.score:+.0f})" for r in rels)
            + "\nMovements: " + ("; ".join(movs) or "none") + f"\nTheir money: £{c.money:,.0f}. Startup cost £{world.config['startup_cost']:,.0f}.")


def _by_name(world, name):
    from .commands import _citizen_by_name
    return _citizen_by_name(world, name or "")


def apply_person_plan(world, c, plan: dict, source: str = "steward") -> list[str]:
    """Execute a steward's plan for citizen c. Returns human-readable lines."""
    rng = world.rng
    done = []
    with world.lock:
        for eff in plan.get("effects", []):
            op, p = eff.get("op"), eff.get("params", {}) or {}
            try:
                if op == "goal":
                    g = p.get("goal")
                    if g in ADULT_GOALS:
                        c.goal, c.goal_progress = g, 0.0
                        done.append(f"new goal: {g}")
                elif op == "work":
                    act = p.get("action", "apply")
                    if act == "quit" and c.employer_id is not None:
                        b = world.businesses[c.employer_id]
                        economy.leave_job(world, c, "quit")
                        world.emit("work", f"{c.name} quit {b.name}.", 0.35, [c.id])
                        done.append(f"quit {b.name}")
                    elif act == "apply":
                        from .commands import _business_by_name
                        b = _business_by_name(world, p.get("business")) if p.get("business") else None
                        cands = [b] if b else [x for x in world.open_businesses() if economy.needs_staff(x, world.food_price, world)]
                        cands = [x for x in cands if x and len(x.employees) < economy.MAX_EMPLOYEES and x.id != c.employer_id]
                        if cands:
                            target = cands[0] if b else max(cands, key=lambda x: x.wage)
                            # a known name helps; so does skill
                            owner = world.citizens.get(target.owner_id)
                            chance = 0.55 + 0.3 * c.skill + (0.15 if owner and c.rel(owner.id).score > 20 else 0)
                            if rng.random() < chance:
                                if c.employer_id is not None:
                                    economy.leave_job(world, c, "switched")
                                economy.hire(world, c, target)
                                world.emit("work", f"{c.name} was taken on at {target.name}.", 0.35, [c.id], tone="good")
                                done.append(f"hired at {target.name}")
                            else:
                                world.emit("work", f"{c.name} asked for work at {target.name} and was turned away.", 0.35, [c.id], tone="bad")
                                done.append(f"turned away at {target.name}")
                        else:
                            done.append("nobody is hiring right now")
                    elif act == "found":
                        cost = world.config["startup_cost"]
                        kind = p.get("kind") if p.get("kind") in economy.JOB_FOR_KIND else "workshop"
                        if c.money >= cost * 1.1:
                            c.money -= cost
                            if c.employer_id is not None:
                                economy.leave_job(world, c)
                            b = world.found_business(c, kind)
                            world.emit("economy", f"{c.name} founded {b.name}.", 0.55, [c.id], tone="good")
                            done.append(f"founded {b.name}")
                        else:
                            done.append(f"needs £{cost*1.1:,.0f} to start a business (has £{c.money:,.0f})")
                elif op == "move":
                    near = _by_name(world, p.get("near"))
                    if near:
                        c.home = (int(np.clip(near.home[0] + rng.randint(-2, 2), 0, world.width - 1)), int(np.clip(near.home[1] + rng.randint(-2, 2), 0, world.height - 1)))
                    else:
                        c.home = world._random_home()
                    c.pos = c.home
                    done.append("moved house" + (f" near {near.name}" if near else ""))
                elif op in ("visit", "confront", "persuade", "propose"):
                    o = _by_name(world, p.get("who"))
                    if not o or o.id == c.id:
                        done.append(f"nobody called '{p.get('who')}'")
                        continue
                    if op == "visit":
                        comp = social.compatibility(c, o)
                        d = rng.uniform(4, 12) * (0.6 + comp)
                        social.adjust(world, c, o, d)
                        world.emit("social", f"{c.name} spent the evening with {o.name}.", 0.3, [c.id, o.id], tone="good")
                        done.append(f"visited {o.name} ({d:+.0f})")
                    elif op == "confront":
                        social.adjust(world, c, o, -rng.uniform(8, 18))
                        c.grievance = max(0, c.grievance - 0.05)
                        world.emit("social", f"{c.name} confronted {o.name} in the street.", 0.45, [o.id, c.id], tone="bad")
                        done.append(f"confronted {o.name}")
                    elif op == "persuade":
                        for k in ("economic", "authority"):
                            o.beliefs[k] += (c.beliefs[k] - o.beliefs[k]) * 0.15 * (0.5 + c.personality["extraversion"])
                        world.emit("politics", f"{c.name} talked politics with {o.name} until late.", 0.3, [o.id, c.id])
                        done.append(f"argued politics with {o.name}")
                    elif op == "propose":
                        if c.spouse_id or o.spouse_id:
                            done.append("one of them is already married")
                        elif c.rel(o.id).score < 40:
                            world.emit("society", f"{c.name} proposed to {o.name} and was gently refused.", 0.4, [c.id, o.id], tone="bad")
                            done.append(f"{o.name} said no (relationship {c.rel(o.id).score:+.0f}; needs +40)")
                        else:
                            c.spouse_id, o.spouse_id = o.id, c.id
                            c.rel(o.id).kind = o.rel(c.id).kind = "spouse"
                            c.rel(o.id).score = o.rel(c.id).score = max(c.rel(o.id).score, 75)
                            o.home = c.home
                            world.emit("society", f"{c.name} and {o.name} got married.", 0.55, [c.id, o.id], tone="good")
                            done.append(f"married {o.name}")
                elif op == "give":
                    o = _by_name(world, p.get("who")) if p.get("who") != "poorest" else min(world.alive(), key=lambda x: x.money)
                    amt = float(np.clip(float(p.get("amount", 50)), 1, c.money))
                    if o and o.id != c.id and amt > 0:
                        c.money -= amt
                        o.money += amt
                        social.adjust(world, o, c, min(25, amt / 10))
                        world.emit("social", f"{c.name} gave £{amt:.0f} to {o.name}.", 0.35, [o.id, c.id], tone="good")
                        done.append(f"gave £{amt:.0f} to {o.name}")
                elif op == "movement":
                    act = p.get("action", "join")
                    from .commands import _movement_by_name
                    if act == "leave" and c.movement_id:
                        m = world.movements[c.movement_id]
                        if c.id in m.members:
                            m.members.remove(c.id)
                        c.movement_id = None
                        done.append(f"left the {m.name}")
                    elif act == "join":
                        m = _movement_by_name(world, p.get("name", "")) or max((m for m in world.movements.values() if m.alive), key=lambda m: len(m.members), default=None)
                        if m and c.movement_id != m.id:
                            if c.movement_id:
                                old = world.movements[c.movement_id]
                                if c.id in old.members:
                                    old.members.remove(c.id)
                            c.movement_id = m.id
                            m.members.append(c.id)
                            world.emit("politics", f"{c.name} joined the {m.name}.", 0.4, [c.id])
                            done.append(f"joined the {m.name}")
                        else:
                            done.append("no movement to join")
                    elif act == "found" and c.movement_id is None:
                        m = Movement(id=world._next_mid, name=p.get("name") or f"{c.surname} Circle", founder_id=c.id, founded_day=world.day,
                                     platform={"economic": float(np.clip(c.beliefs["economic"] - 0.1, -1, 1)), "authority": c.beliefs["authority"]},
                                     members=[c.id], grievance_theme=p.get("theme", "hardship"))
                        world._next_mid += 1
                        world.movements[m.id] = m
                        c.movement_id = m.id
                        c.grievance = max(c.grievance, 0.5)
                        world.emit("politics", f"{c.name} founded the {m.name}, a movement against {m.grievance_theme}.", 0.7, [c.id])
                        done.append(f"founded the {m.name}")
                elif op == "note":
                    c.remember(world.day, p.get("text", ""), p.get("emotion", "neutral"), 0.6, tag="steward")
                    world.think(c, p.get("text", ""), source, p.get("emotion", "neutral"))
                    done.append("noted")
                else:
                    done.append(f"unknown op '{op}' ignored")
            except Exception as e:
                done.append(f"skipped {op}: {e}")
    return done


PERSON_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"},
                   "effects": {"type": "array", "items": {"type": "object", "properties": {"op": {"type": "string"}, "params_json": {"type": "string"}},
                                                          "required": ["op", "params_json"], "additionalProperties": False}}},
    "required": ["reply", "effects"], "additionalProperties": False,
}


def interpret_person(world, c, text: str, backend) -> dict:
    """The steward's instruction → the person's reply (in character) + ops. Uses the steward's own backend."""
    from .llm import describe_citizen
    ops = "\n".join(f"- {k}: {v}" for k, v in PERSON_OPS.items())
    system = (f"You are {c.name}, a person living in a simulated town, and the message comes from the one who watches over you. "
              "Answer in the first person, in your own voice, briefly (one or two sentences) — you may push back if it goes against your nature, "
              "but generally do what is asked, translated into the actions available. Use several actions if the instruction implies them. "
              "Each effect has an op and params_json (the op's params as a JSON object encoded as a string).\n\n"
              f"Actions:\n{ops}")
    user = f"WHO YOU ARE\n{describe_citizen(world, c)}\n\nWHAT IS AROUND YOU\n{describe_person_options(world, c)}\n\nTHE INSTRUCTION: {text}"
    data, _ = backend.json_call(system, user, PERSON_SCHEMA, max_tokens=1024, effort="low")
    effects = []
    for eff in data.get("effects", []):
        raw = eff.get("params_json", "{}")
        try:
            params = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            params = {}
        effects.append({"op": eff.get("op"), "params": params if isinstance(params, dict) else {}})
    return {"reply": data.get("reply", ""), "effects": effects}


def rules_interpret_person(world, c, text: str) -> Optional[dict]:
    """A few verbs work without a model."""
    t = text.lower()
    eff = []
    if "quit" in t:
        eff.append({"op": "work", "params": {"action": "quit"}})
    elif "job" in t or "work" in t or "apply" in t:
        eff.append({"op": "work", "params": {"action": "apply"}})
    if "start a" in t or "open a" in t or "found a" in t:
        for k in economy.JOB_FOR_KIND:
            if k in t:
                eff.append({"op": "work", "params": {"action": "found", "kind": k}})
                break
    if "move" in t:
        eff.append({"op": "move", "params": {}})
    if "join" in t:
        eff.append({"op": "movement", "params": {"action": "join"}})
    for g in ADULT_GOALS:
        if g in t:
            eff.append({"op": "goal", "params": {"goal": g}})
    return {"reply": "Understood.", "effects": eff} if eff else None
