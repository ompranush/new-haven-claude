"""Free-text god mode.

A natural-language decree ("a travelling circus arrives", "gold is found in the
hills", "double the taxes") is turned into a *plan*: a narration plus a list of
effects in a small, safe DSL. Claude writes the plan (see llm.interpret); this
module executes it. Nothing here calls a model, so plans can also be hand-written
or replayed deterministically.
"""
from __future__ import annotations
import random
from typing import List
import numpy as np

from .systems.disasters import INJECTABLE, inject
from .systems import economy, lifecycle, politics
from .systems.politics import LAW_TEXT
from .models import Citizen

TARGETS = ("all", "adults", "children", "poorest:N", "richest:N", "random:N", "job:<job>", "name:<full name>",
           "unemployed", "hungry", "sick", "movement:<name>", "owners", "elders", "young")

OPS = {
    "inject": "Run a built-in shock. params: {name: one of %s, kwargs?: {}}" % "|".join(INJECTABLE),
    "food": "Change the granary. params: {delta: units (+/-)} — a person eats 1 unit/day.",
    "money": "Give or take money. params: {target, delta?: £ per person, multiplier?: e.g. 0.5}",
    "mood": "Shift feelings. params: {target, happiness?: -1..1, health?: -1..1, grievance?: -1..1, trust?: -1..1, economic?: -1..1, authority?: -1..1}",
    "kill": "People die. params: {target, count?: N (default all in target), cause: short phrase}",
    "policy": "Set a policy field. params: {field: tax_rate|welfare|pension|min_wage|public_education|public_health, value}",
    "law": "Enact or repeal an emergency law. params: {name: %s, enact: true|false}" % "|".join(LAW_TEXT),
    "business": "Open or close businesses. params: {action: open|close, kind?: farm|bakery|workshop|market|mine|tavern|school|clinic, name?: existing business name, owner?: target}",
    "citizens": "New people arrive. params: {count: N, wealth?: £ each, job?: job name, note?: who they are}",
    "tech": "Change technology level. params: {multiplier: e.g. 1.1}",
    "relationship": "Change how two named people feel about each other. params: {a: full name, b: full name, delta: -100..100}",
    "movement": "Found a political movement. params: {founder: full name, name: movement name, economic: -1..1, authority: -1..1, theme: what it is against}",
    "memory": "Give people a memory of this. params: {target, text: first-person line, emotion: joy|grief|anger|fear|pride|shame|hope|neutral, importance: 0..1}",
    "government": "Replace the government outright. params: {name: party name, economic: -1..1, authority: -1..1}",
    "pandemic": "Start a named sickness. params: {name?: str}",
    "weather": "Seasonal change. params: {kind: drought|rains, days?: N}",
    "strike": "Start or end a strike. params: {action: start|end, movement?: name, days?: N, outcome?: won|lost (for end)}",
    "end": "End an ongoing situation. params: {what: strike|pandemic|drought|recession|boom|curfew|quarantine|rationing|public_works|tax_holiday|poor_relief|movement, name?: movement name}",
}


def describe_world(world) -> str:
    alive = world.alive()
    bs = world.open_businesses()
    movs = [m for m in world.movements.values() if m.alive]
    rich = sorted(alive, key=lambda c: -c.money)[:3]
    notable = sorted(alive, key=lambda c: -abs(c.reputation))[:4]
    from .eras import context_line
    lines = [
        context_line(world),
        f"{world.name}, day {world.day} (year {world.year}). Population {len(alive)}, unemployment {world.unemployment*100:.0f}%, "
        f"bread £{world.food_price:.1f}, granary {world.food:.0f} units, treasury £{world.treasury:,.0f}, tech {world.tech:.2f}, Gini {world.gini:.2f}.",
        f"Government: {world.policy.ruling_party} (economic {world.policy.platform['economic']:+.2f}, authority {world.policy.platform['authority']:+.2f}), "
        f"tax {world.policy.tax_rate*100:.0f}%, welfare £{world.policy.welfare:.0f}, laws: {', '.join(world.policy.laws) or 'none'}, approval {world.policy.approval*100:.0f}%.",
        "Businesses: " + "; ".join(f"{b.name} ({b.kind}, {len(b.employees)} staff, £{b.cash:,.0f})" for b in bs[:16]),
        "Richest: " + ", ".join(f"{c.name} £{c.money:,.0f}" for c in rich),
        "Notable: " + ", ".join(f"{c.name} ({c.job}, rep {c.reputation:+.2f})" for c in notable),
        "Movements: " + ("; ".join(f"{m.name} ({len(m.members)} members, against {m.grievance_theme})" for m in movs) or "none"),
        "Jobs present: " + ", ".join(sorted({c.job for c in alive})),
    ]
    if world.pandemic:
        lines.append(f"Pandemic: {world.pandemic['name']} ({world.pandemic['deaths']} dead so far).")
    if world.drought_days:
        lines.append(f"Drought: {world.drought_days} days left.")
    if world.recession_days:
        lines.append(f"Recession: {world.recession_days} days left.")
    if world.strike:
        m = world.movements.get(world.strike["movement"])
        lines.append(f"STRIKE in progress: {len(world.strike['members'])} members of the {m.name if m else 'movement'} are on strike until day {world.strike['until']}.")
    return "\n".join(lines)


def select(world, target: str, rng: random.Random) -> List[Citizen]:
    alive = world.alive()
    t = (target or "all").strip()
    key, _, arg = t.partition(":")
    key = key.lower()
    if key == "all":
        return alive
    if key == "adults":
        return [c for c in alive if c.age_on(world.day) >= 18]
    if key == "children":
        return [c for c in alive if c.age_on(world.day) < 18]
    if key == "elders":
        return [c for c in alive if c.age_on(world.day) >= 60]
    if key == "young":
        return [c for c in alive if 18 <= c.age_on(world.day) < 30]
    if key == "unemployed":
        return [c for c in alive if c.employer_id is None and 18 <= c.age_on(world.day) < 65]
    if key == "hungry":
        return [c for c in alive if c.hunger > 0.4]
    if key == "sick":
        return [c for c in alive if c.infected or c.health < 0.5]
    if key == "owners":
        ids = {b.owner_id for b in world.open_businesses()}
        return [c for c in alive if c.id in ids]
    n = int(arg) if arg.isdigit() else 5
    if key == "poorest":
        return sorted(alive, key=lambda c: c.money)[:n]
    if key == "richest":
        return sorted(alive, key=lambda c: -c.money)[:n]
    if key == "random":
        return rng.sample(alive, min(n, len(alive)))
    if key == "job":
        return [c for c in alive if c.job == arg.strip().lower()]
    if key == "movement":
        m = _movement_by_name(world, arg)
        return [world.citizens[i] for i in m.members if world.citizens[i].alive] if m else []
    if key == "name":
        c = _citizen_by_name(world, arg)
        return [c] if c else []
    return alive


def _end_strike(world, outcome):
    if not world.strike:
        return "nobody was on strike"
    m = world.movements.get(world.strike["movement"])
    n = len(world.strike["members"])
    if outcome == "won":
        for i in world.strike["members"]:
            c = world.citizens[i]
            if c.alive and c.employer_id:
                world.businesses[c.employer_id].wage *= 1.12
                c.grievance = max(0, c.grievance - 0.25)
    world.strike = None
    return f"strike of {n} {m.name if m else ''} members ended{' — they won' if outcome == 'won' else (' — they lost' if outcome == 'lost' else '')}"


def _citizen_by_name(world, name):
    name = name.strip().lower()
    for c in world.alive():
        if c.name.lower() == name:
            return c
    for c in world.alive():
        if name in c.name.lower():
            return c
    return None


def _movement_by_name(world, name):
    name = name.strip().lower()
    for m in world.movements.values():
        if m.alive and (m.name.lower() == name or name in m.name.lower()):
            return m
    return None


def _business_by_name(world, name):
    name = (name or "").strip().lower()
    for b in world.open_businesses():
        if b.name.lower() == name or (name and name in b.name.lower()):
            return b
    return None


def apply_plan(world, plan: dict, source: str = "llm") -> List[str]:
    """Execute a plan. Returns human-readable lines describing what was done."""
    rng = world.rng
    done = []
    narration = plan.get("narration", "").strip() or "Something happened."
    importance = float(np.clip(plan.get("importance", 0.8), 0.5, 1.0))
    affected = set()
    for eff in plan.get("effects", []):
        op = eff.get("op")
        p = eff.get("params", {}) or {}
        try:
            if op == "inject":
                name = p.get("name")
                if name in INJECTABLE:
                    inject(world, name, **(p.get("kwargs") or {}))
                    done.append(f"shock: {name}")
            elif op == "food":
                d = float(p.get("delta", 0))
                world.food = max(0.0, world.food + d)
                done.append(f"granary {d:+.0f}")
            elif op == "money":
                cs = select(world, p.get("target", "all"), rng)
                d, m = float(p.get("delta", 0) or 0), p.get("multiplier")
                for c in cs:
                    c.money = max(0.0, c.money * float(m) if m is not None else c.money + d)
                affected.update(c.id for c in cs)
                done.append(f"money for {len(cs)} people ({'×' + str(m) if m is not None else f'£{d:+.0f}'})")
            elif op == "mood":
                cs = select(world, p.get("target", "all"), rng)
                for c in cs:
                    c.happiness = float(np.clip(c.happiness + float(p.get("happiness", 0) or 0), 0, 1))
                    c.health = float(np.clip(c.health + float(p.get("health", 0) or 0), 0, 1))
                    c.grievance = float(np.clip(c.grievance + float(p.get("grievance", 0) or 0), 0, 1))
                    c.beliefs["trust"] = float(np.clip(c.beliefs.get("trust", 0.5) + float(p.get("trust", 0) or 0), 0, 1))
                    for k in ("economic", "authority"):
                        if k in c.beliefs:
                            c.beliefs[k] = float(np.clip(c.beliefs[k] + float(p.get(k, 0) or 0), -1, 1))
                affected.update(c.id for c in cs)
                done.append(f"mood of {len(cs)} people shifted")
            elif op == "kill":
                cs = select(world, p.get("target", "random:1"), rng)
                n = int(p.get("count", len(cs)))
                for c in cs[:n]:
                    lifecycle.die(world, c, p.get("cause", "misfortune"))
                done.append(f"{min(n, len(cs))} died of {p.get('cause', 'misfortune')}")
            elif op == "policy":
                f, v = p.get("field"), p.get("value")
                pol = world.policy
                if f in ("tax_rate",):
                    pol.tax_rate = float(np.clip(float(v), 0, 0.8))
                elif f in ("welfare", "pension", "min_wage"):
                    setattr(pol, f, max(0.0, float(v)))
                elif f in ("public_education", "public_health"):
                    setattr(pol, f, bool(v))
                done.append(f"policy {f} = {v}")
            elif op == "law":
                name = p.get("name")
                if name in LAW_TEXT:
                    if p.get("enact", True):
                        if name not in world.policy.laws:
                            world.policy.laws.append(name)
                    elif name in world.policy.laws:
                        world.policy.laws.remove(name)
                    done.append(f"law {name} {'enacted' if p.get('enact', True) else 'repealed'}")
            elif op == "business":
                if p.get("action") == "close":
                    b = _business_by_name(world, p.get("name")) or next((b for b in world.open_businesses() if b.kind == p.get("kind")), None)
                    if b:
                        economy.bankrupt(world, b)
                        done.append(f"closed {b.name}")
                else:
                    kind = p.get("kind") if p.get("kind") in economy.JOB_FOR_KIND else "workshop"
                    owners = select(world, p.get("owner", "richest:1"), rng) or world.adults()
                    if owners:
                        owner = owners[0]
                        if owner.employer_id is not None:
                            economy.leave_job(world, owner)
                        b = world.found_business(owner, kind)
                        b.cash = 2500.0
                        affected.add(owner.id)
                        done.append(f"opened {b.name} ({owner.name})")
            elif op == "citizens":
                n = int(np.clip(int(p.get("count", 5)), 1, 200))
                before = set(world.citizens)
                inject(world, "immigration", n=n)
                new = [c for i, c in world.citizens.items() if i not in before]
                for c in new:
                    if p.get("wealth") is not None:
                        c.money = float(p["wealth"])
                    if p.get("job") in economy.JOB_FOR_KIND.values():
                        c.job = p["job"]
                    if p.get("note"):
                        c.remember(world.day, p["note"], "hope", 0.6, tag="life")
                affected.update(c.id for c in new)
                done.append(f"{n} newcomers")
            elif op == "tech":
                world.tech = float(np.clip(world.tech * float(p.get("multiplier", 1.0)), 0.2, 20))
                done.append(f"tech ×{float(p.get('multiplier', 1.0)):.2f}")
            elif op == "relationship":
                a, b = _citizen_by_name(world, p.get("a", "")), _citizen_by_name(world, p.get("b", ""))
                if a and b and a is not b:
                    from .systems import social
                    social.adjust(world, a, b, float(np.clip(float(p.get("delta", 0)), -100, 100)))
                    affected.update([a.id, b.id])
                    done.append(f"{a.name}–{b.name} {float(p.get('delta', 0)):+.0f}")
            elif op == "movement":
                f = _citizen_by_name(world, p.get("founder", "")) or max(world.adults(), key=lambda c: c.grievance)
                if f.movement_id is None:
                    from .models import Movement
                    m = Movement(id=world._next_mid, name=p.get("name") or "New Movement", founder_id=f.id, founded_day=world.day,
                                 platform={"economic": float(np.clip(float(p.get("economic", 0)), -1, 1)), "authority": float(np.clip(float(p.get("authority", 0)), -1, 1))},
                                 members=[f.id], grievance_theme=p.get("theme", "hardship"))
                    world._next_mid += 1
                    world.movements[m.id] = m
                    f.movement_id = m.id
                    f.grievance = max(f.grievance, 0.6)
                    affected.add(f.id)
                    done.append(f"{f.name} founded the {m.name}")
            elif op == "memory":
                cs = select(world, p.get("target", "all"), rng)
                for c in cs:
                    c.remember(world.day, p.get("text", narration), p.get("emotion", "neutral"), float(np.clip(float(p.get("importance", 0.6)), 0, 1)), tag="decree")
                done.append(f"memory for {len(cs)} people")
            elif op == "government":
                politics.apply_platform(world, {"economic": float(np.clip(float(p.get("economic", 0)), -1, 1)), "authority": float(np.clip(float(p.get("authority", 0)), -1, 1))},
                                        p.get("name") or "The New Order")
                world.next_election_day = world.day + world.config["election_period_days"]
                done.append(f"government: {world.policy.ruling_party}")
            elif op == "pandemic":
                inject(world, "pandemic", name=p.get("name", "the Stranger's Fever"))
                done.append("pandemic started")
            elif op == "weather":
                if p.get("kind") == "drought":
                    world.drought_days = int(p.get("days", 90))
                    done.append(f"drought for {world.drought_days} days")
                else:
                    world.drought_days = 0
                    world.food += len(world.alive()) * 10
                    done.append("rains came")
            elif op == "strike":
                if p.get("action", "end") == "end":
                    done.append(_end_strike(world, p.get("outcome")))
                else:
                    m = _movement_by_name(world, p.get("movement", "")) or next((m for m in world.movements.values() if m.alive), None)
                    if m and world.strike is None:
                        workers = [i for i in m.members if world.citizens[i].alive and world.citizens[i].employer_id is not None]
                        if workers:
                            world.strike = {"movement": m.id, "members": workers, "until": world.day + int(p.get("days", 7))}
                            done.append(f"{len(workers)} members of the {m.name} downed tools")
            elif op == "end":
                what = p.get("what", "")
                if what == "strike":
                    done.append(_end_strike(world, None))
                elif what == "pandemic" and world.pandemic:
                    for c in world.alive():
                        if c.infected:
                            c.infected, c.immune = False, True
                    world.pandemic = None
                    done.append("the sickness passed")
                elif what == "drought":
                    world.drought_days = 0
                    done.append("drought ended")
                elif what == "recession":
                    world.recession_days = 0
                    done.append("recession ended")
                elif what == "boom":
                    world.boom_days = 0
                    done.append("boom ended")
                elif what in LAW_TEXT:
                    if what in world.policy.laws:
                        world.policy.laws.remove(what)
                    done.append(f"{what} lifted")
                elif what == "movement":
                    m = _movement_by_name(world, p.get("name", ""))
                    if m:
                        m.alive = False
                        for i in m.members:
                            world.citizens[i].movement_id = None
                        done.append(f"the {m.name} dissolved")
                else:
                    done.append(f"nothing to end for '{what}'")
            else:
                done.append(f"unknown op '{op}' ignored")
        except Exception as e:  # a bad effect must never take the world down
            done.append(f"skipped {op}: {e}")
    actors = list(affected)[:3] or ([max(world.alive(), key=lambda c: c.reputation).id] if world.alive() else [])
    ev = world.emit("decree", narration, importance, actors)
    ev.brain = source
    return done


# ---- hand-written plans for a few phrases, so the text box does something even with no key
FALLBACK = {
    "circus": {"narration": "A travelling circus pitched its tents in the square. For a week nobody talked about anything else.",
               "importance": 0.6, "effects": [{"op": "mood", "params": {"target": "all", "happiness": 0.12, "grievance": -0.05}},
                                              {"op": "memory", "params": {"target": "random:20", "text": "The circus came. I laughed until I cried.", "emotion": "joy", "importance": 0.5}}]},
    "gold": {"narration": "Gold was found in the hills. Within a month there were two new mines and a lot of new arguments.",
             "importance": 0.85, "effects": [{"op": "business", "params": {"action": "open", "kind": "mine", "owner": "richest:1"}},
                                             {"op": "business", "params": {"action": "open", "kind": "mine", "owner": "random:1"}},
                                             {"op": "citizens", "params": {"count": 12, "wealth": 100, "note": "I came for the gold."}},
                                             {"op": "mood", "params": {"target": "all", "economic": 0.1}}]},
}


def fallback_plan(text: str):
    t = text.lower()
    for k, plan in FALLBACK.items():
        if k in t:
            return plan
    return None
