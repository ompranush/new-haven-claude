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
    "end": "End an ongoing situation. params: {what: strike|pandemic|drought|recession|boom|curfew|quarantine|rationing|public_works|tax_holiday|poor_relief|movement|war, name?: movement name}",
    "act": "Make people DO something, whatever it is — they cannot refuse a god. params: {target, act: one of the behaviour acts (kill, brawl, steal, burgle, arson, poison, court, propose, emigrate, riot, enlist, desert, pray, study, gift, celebrate, hunt, ...), who?: full name of the other person}",
    "war": "Two villages go to war. params: {a: village, b: village, reason?: str}",
    "peace": "End a war. params: {a: village, b: village}",
    "river": "Set how much of the river a village takes. params: {village, diversion: 0..0.6}",
    "magic": "Grant (or strip) magical power. params: {target, power?: 0..1, strip?: true}",
    "spectacle": "A visible wonder or catastrophe the world shows and feels. params: {kind: meteor_shower|wildfire|earthquake|lightning_storm|flood|tornado|aurora|eclipse, severity?: 0..1}",
    "occupy": "One village occupies another. params: {village, by: village}",
    "liberate": "Free an occupied village. params: {village}",
    "animals": "Animals appear. params: {species: dog|cat|horse|cow|sheep|goat|elephant|deer|bird|wolf|bear|tiger|lion, count: N, wild?: bool}",
    "migrate": "People move between villages. params: {target, to: village}",
    "feeling": "Set what people feel. params: {target, emotion: anger|fear|grief|joy|shame|pride|envy|hope|love, level: 0..1}",
    "role": "Put people in office. params: {target, role: councillor|police|guard|none}",
}
VILLAGE_HELP = "Every effect may carry \"village\": sky|air|earth|fire|water|all (default: the village being watched)."


def describe_world(world) -> str:
    alive = world.alive()
    bs = world.open_businesses()
    movs = [m for m in world.movements_here() if m.alive]
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
    """This village first, then anywhere in the realm."""
    name = (name or "").strip().lower()
    if not name:
        return None
    for pool in (world.alive(), world.alive_all()):
        for c in pool:
            if c.name.lower() == name:
                return c
        for c in pool:
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


def village_index(world, name) -> List[int]:
    """'fire' / 'Emberhold' / 'all' / 3 → village indices."""
    if name is None or name == "":
        return [world.focus]
    if isinstance(name, int):
        return [name % len(world.villages)]
    n = str(name).strip().lower()
    if n in ("all", "every", "everywhere", "realm", "*"):
        return [v.idx for v in world.villages if not v.fallen]
    for v in world.villages:
        if n in (v.element, v.name.lower()) or v.element in n or v.name.lower() in n:
            return [v.idx]
    return [world.focus]


def apply_plan(world, plan: dict, source: str = "llm") -> List[str]:
    """Execute a plan. Returns human-readable lines describing what was done."""
    done = []
    narration = plan.get("narration", "").strip() or "Something happened."
    importance = float(np.clip(plan.get("importance", 0.8), 0.5, 1.0))
    affected = set()
    home = plan.get("village")
    for eff in plan.get("effects", []):
        p = eff.get("params", {}) or {}
        for idx in village_index(world, p.get("village", eff.get("village", home))):
            with world.at(idx):
                _apply_effect(world, eff, done, affected, source, narration)
    for idx in village_index(world, home):
        with world.at(idx):
            here = [a for a in affected if a in world.citizens and world.citizens[a].village == idx]
            actors = here[:3] or ([max(world.alive(), key=lambda c: c.reputation).id] if world.alive() else [])
            ev = world.emit("decree", narration, importance, actors, kind="decree")
            ev.brain = source
    return done


def _apply_effect(world, eff, done, affected, source, narration=""):
    rng = world.rng
    op = eff.get("op")
    p = eff.get("params", {}) or {}
    if True:
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
                                 members=[f.id], grievance_theme=p.get("theme", "hardship"), village=f.village)
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
                    m = _movement_by_name(world, p.get("movement", "")) or next((m for m in world.movements_here() if m.alive), None)
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
            elif op in EXTRA_OPS:
                EXTRA_OPS[op](world, p, done, affected)
            else:
                done.append(f"unknown op '{op}' ignored")
        except Exception as e:  # a bad effect must never take the world down
            done.append(f"skipped {op}: {e}")


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




# ---------------------------------------------------------------- the realm's ops: war, rivers, magic, wonders, compulsion
def _op_act(world, p, done, affected):
    """Compulsion: a god says do it, and it is done."""
    from . import behaviour
    from .models import WorldEvent
    key = str(p.get("act", "")).strip().lower().replace(" ", "_")
    key = {"murder": "kill", "attack": "brawl", "fight": "brawl", "beat": "brawl", "rob": "steal", "burn": "arson", "marry": "propose",
           "leave": "emigrate", "flee": "flee", "riot": "incite_riot", "join_army": "enlist", "love": "court", "practise": "practice_arts",
           "practice": "practice_arts", "pray": "pray", "insult": "mock_publicly", "cheat": "swindle"}.get(key, key)
    act = behaviour.ACTS.get(key)
    if act is None:
        done.append(f"no such act '{key}'")
        return
    other = _citizen_by_name(world, p.get("who", "")) if p.get("who") else None
    people = select(world, p.get("target", "random:1"), world.rng)
    for c in people[:40]:
        ev = WorldEvent(world.day, "decree", f"The gods moved {c.name}", 0.8, [c.id] + ([other.id] if other else []), kind="decree",
                        village=c.village)
        if other:
            ev.culprit = other.id
        ctx = behaviour.Ctx(world, c, ev, "decree", "anger" if act.violent else "hope", 0.95, other if other and other.id != c.id else None)
        if ctx.other is None and act.needs is not None:
            pool = [x for x in world.alive() if x.id != c.id]
            ctx.other = min(pool, key=lambda x: c.rel(x.id).score) if pool else None
        try:
            act.do(ctx)
            line = world.rng.choice(act.lines).format(o=ctx.other.name.split()[0] if ctx.other else "them",
                                                      el=world.villages[c.village].element, dest=ctx.note or "somewhere else")
            c.remember(world.day, line + " I don't know what came over me.", "fear" if act.violent else "hope", 0.8, tag="decree")
            world.think(c, line, "god", "fear" if act.violent else "hope")
            affected.add(c.id)
        except Exception as e:
            done.append(f"{c.name} could not {key}: {e}")
    done.append(f"{len(people[:40])} compelled to {key.replace('_', ' ')}" + (f" ({other.name})" if other else ""))


def _two(world, p):
    a = village_index(world, p.get("a"))[0]
    b = village_index(world, p.get("b"))[0]
    if a == b:
        b = next((v.idx for v in world.villages if v.idx != a and not v.fallen), a)
    return a, b


def _op_war(world, p, done, affected):
    from .systems import war
    a, b = _two(world, p)
    war.declare(world, a, b, p.get("reason") or "the will of the gods")
    world.villages[a].tension[b] = world.villages[b].tension[a] = 0.9
    done.append(f"war: {world.villages[a].name} vs {world.villages[b].name}")


def _op_peace(world, p, done, affected):
    from .systems import war
    a, b = _two(world, p)
    w = war.war_between(world, a, b)
    if w:
        war._end(world, w, None, "exhaustion")
    for x, y in ((a, b), (b, a)):
        world.villages[x].tension[y] = 0.1
    done.append(f"peace between {world.villages[a].name} and {world.villages[b].name}")


def _op_river(world, p, done, affected):
    v = world.village
    v.diversion = float(np.clip(float(p.get("diversion", 0.1)), 0.0, 0.6))
    done.append(f"{v.name} now takes {v.diversion*100:.0f}% of the river")


def _op_magic(world, p, done, affected):
    from .systems import magic
    people = select(world, p.get("target", "random:1"), world.rng)
    for c in people[:30]:
        if p.get("strip"):
            c.magic = None
        else:
            magic.awaken(world, c, element=p.get("element") or world.villages[c.village].element,
                         power=float(p.get("power", 0.6)), why="a gift from the gods", granted=True)
        affected.add(c.id)
    done.append(f"{'stripped' if p.get('strip') else 'granted'} magic: {len(people[:30])} people")


def _op_occupy(world, p, done, affected):
    by = village_index(world, p.get("by"))[0]
    v = world.village
    if by == v.idx:
        done.append("a village cannot occupy itself")
        return
    v.occupier, v.occupied_since = by, world.day
    v.policy.ruling_party = f"{world.villages[by].name} Governorship"
    world.emit("war", f"{world.villages[by].name} took {v.name}.", 0.9, [c.id for c in world.alive()][:3], kind="occupied", tone="bad")
    done.append(f"{v.name} occupied by {world.villages[by].name}")


def _op_liberate(world, p, done, affected):
    v = world.village
    if v.occupier is None:
        done.append(f"{v.name} was free already")
        return
    v.occupier = None
    v.policy.ruling_party = f"The Free {v.element.title()} Council"
    world.emit("war", f"{v.name} is free.", 0.9, [c.id for c in world.alive()][:3], kind="liberated", tone="good")
    done.append(f"{v.name} liberated")


def _op_animals(world, p, done, affected):
    from .systems import animals
    sp = str(p.get("species", "deer")).lower().rstrip("s")
    sp = {"cattle": "cow", "calf": "cow", "ox": "cow", "lamb": "sheep", "hound": "dog", "puppy": "dog", "kitten": "cat",
          "pony": "horse", "eagle": "bird", "hawk": "bird", "crow": "bird"}.get(sp, sp)
    if sp not in animals.SPECIES:
        done.append(f"no such animal '{sp}'")
        return
    n = int(np.clip(int(p.get("count", 3)), 1, 40))
    people = world.alive()
    for _ in range(n):
        tame = not p.get("wild", animals.SPECIES[sp]["wild"])
        animals.new_animal(world, sp, world.focus, owner=world.rng.choice(people) if (tame and people) else None)
    plural = {"wolf": "wolves", "sheep": "sheep", "deer": "deer"}.get(sp, sp + "s")
    done.append(f"{n} {plural if n > 1 else sp} appeared in {world.name}")


def _op_migrate(world, p, done, affected):
    from .systems.crime import relocate
    to = village_index(world, p.get("to"))[0]
    people = select(world, p.get("target", "random:5"), world.rng)
    for c in people:
        relocate(world, c, to, reason="the gods sent them")
    done.append(f"{len(people)} moved to {world.villages[to].name}")


def _op_feeling(world, p, done, affected):
    e = p.get("emotion", "joy")
    lvl = float(np.clip(float(p.get("level", 0.7)), 0, 1))
    people = select(world, p.get("target", "all"), world.rng)
    for c in people:
        c.emotions[e] = lvl
        affected.add(c.id)
    done.append(f"{len(people)} people now feel {e} at {lvl:.1f}")


def _op_role(world, p, done, affected):
    r = p.get("role", "none")
    people = select(world, p.get("target", "random:1"), world.rng)
    for c in people:
        c.role = "" if r in ("none", "") else r
        affected.add(c.id)
    done.append(f"{len(people)} made {r}")


def _op_spectacle(world, p, done, affected):
    spectacle(world, str(p.get("kind", "meteor_shower")), float(p.get("severity", 0.6)), done, affected)


def spectacle(world, kind: str, sev: float, done, affected):
    """Wonders and catastrophes: the renderer shows them, the land keeps the scars, the people feel them."""
    from . import terrain
    from .systems import lifecycle
    rng = world.rng
    v = world.village
    x0, y0, x1, y1 = v.region
    cx, cy = v.centre
    sev = float(np.clip(sev, 0.1, 1.0))
    dead, wrecked = [], []

    def hit(x, y, r, kill_p):
        for b in world.open_businesses():
            if abs(b.x - x) <= r and abs(b.y - y) <= r and rng.random() < 0.6:
                economy.bankrupt(world, b)
                world.set_tile(b.x, b.y, terrain.RUIN)
                wrecked.append(b.name)
        for c in world.alive():
            if abs(c.pos[0] - x) <= r and abs(c.pos[1] - y) <= r and rng.random() < kill_p:
                lifecycle.die(world, c, kind.replace("_", " "))
                dead.append(c.name)

    if kind in ("meteor_shower", "meteor", "meteors"):
        n = 3 + int(8 * sev)
        for i in range(n):
            x, y = rng.randint(x0 + 2, x1 - 3), rng.randint(y0 + 2, y1 - 3)
            if i < 2 + int(3 * sev):                     # most burn up; some land near people
                x, y = cx + rng.randint(-6, 6), cy + rng.randint(-5, 5)
            world.add_fx("meteor", x, y, days=3, delay=i * 0.4)
            world.set_tile(x, y, terrain.ASH)
            hit(x, y, 0, 0.35 * sev)
        text = f"Stars fell on {v.name}: {n} burning stones tore out of the sky"
    elif kind in ("wildfire", "fire"):
        fx, fy = cx + rng.randint(-8, 8), cy + rng.randint(-6, 6)
        r = 3 + int(5 * sev)
        for yy in range(fy - r, fy + r + 1):
            for xx in range(fx - r, fx + r + 1):
                if 0 <= xx < world.width and 0 <= yy < world.height and world.grid[yy, xx] in (terrain.FOREST, terrain.FARMLAND, terrain.GRASS) \
                        and rng.random() < 0.6 and terrain.region_of([v.region], xx, yy) == 0:
                    world.set_tile(xx, yy, terrain.ASH)
        for i in range(6):
            world.add_fx("fire", fx + rng.randint(-r, r), fy + rng.randint(-r, r), days=4)
        hit(fx, fy, r // 2, 0.12 * sev)
        text = f"A wildfire swept through {v.name}"
    elif kind in ("earthquake", "quake"):
        world.add_fx("quake", cx, cy, days=2, radius=10)
        for _ in range(3 + int(6 * sev)):
            x, y = cx + rng.randint(-8, 8), cy + rng.randint(-6, 6)
            hit(x, y, 0, 0.2 * sev)
            if rng.random() < 0.5:
                world.set_tile(x, y, terrain.RUIN if world.grid[y, x] == terrain.TOWN else terrain.ROCK)
        text = f"The earth split under {v.name}"
    elif kind in ("lightning_storm", "lightning", "storm"):
        for i in range(8):
            x, y = cx + rng.randint(-10, 10), cy + rng.randint(-8, 8)
            world.add_fx("lightning", x, y, days=2, delay=i * 0.3)
            hit(x, y, 0, 0.15 * sev)
        text = f"A storm of lightning broke over {v.name}"
    elif kind in ("tornado", "whirlwind"):
        world.add_fx("tornado", cx - 6, cy, days=3, dx=12)
        for i in range(6):
            hit(cx - 6 + 2 * i, cy + rng.randint(-1, 1), 0, 0.15 * sev)
        text = f"A whirlwind tore across {v.name}"
    elif kind in ("flood",):
        from .systems.disasters import inject
        world.add_fx("flood", cx, cy, days=4, radius=8)
        inject(world, "flood")
        text = f"The river rose over {v.name}"
    else:   # aurora, eclipse, omen — a wonder
        world.add_fx(kind, cx, cy, days=3)
        for c in world.alive():
            c.emotions["hope" if kind == "aurora" else "fear"] = min(1.0, c.feel("hope" if kind == "aurora" else "fear") + 0.4)
        text = f"{'Lights danced over' if kind == 'aurora' else 'Darkness fell at noon on'} {v.name}"
    for c in world.alive():
        c.emotions["fear"] = min(1.0, c.feel("fear") + 0.3 * sev)
    msg = text + (f"; {', '.join(wrecked[:3])} destroyed" if wrecked else "") + (f"; {len(dead)} dead" if dead else "") + "."
    ev = world.emit("disaster", msg, 0.9, [c.id for c in world.alive()][:3], kind="disaster", tone="bad" if (dead or wrecked) else "")
    done.append(msg)


EXTRA_OPS = {"act": _op_act, "war": _op_war, "peace": _op_peace, "river": _op_river, "magic": _op_magic, "occupy": _op_occupy,
             "liberate": _op_liberate, "animals": _op_animals, "migrate": _op_migrate, "feeling": _op_feeling, "role": _op_role,
             "spectacle": _op_spectacle}


# ---------------------------------------------------------------- decrees without a model
def _villages_in(world, t):
    """Villages named in the text, in the order they are mentioned ('earthquake' is not Earth)."""
    import re
    hits = []
    for v in world.villages:
        m = re.search(rf"\b({v.element}|{v.name.lower()})\b", t)
        if m:
            hits.append((m.start(), v.element))
    return [e for _, e in sorted(hits)]


def _names_in(world, t):
    out = []
    people = world.alive_all()
    for c in people:
        if c.name.lower() in t:
            out.append(c)
    if not out:
        firsts = {}
        for c in people:
            firsts.setdefault(c.name.split()[0].lower(), c)
        for w_ in t.replace(",", " ").replace(".", " ").split():
            if w_ in firsts and firsts[w_] not in out:
                out.append(firsts[w_])
    return out


RULE_WORDS = [   # (words, builder(world, text, villages, names) -> effects)
    (("meteor", "shooting star", "stars fall", "falling star"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "meteor_shower", "severity": 0.7}}]),
    (("wildfire", "forest fire", "fire breaks", "burns", "blaze", "inferno"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "wildfire", "severity": 0.7}}]),
    (("earthquake", "quake", "ground shakes", "earth splits"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "earthquake", "severity": 0.7}}]),
    (("lightning", "thunder", "storm"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "lightning_storm", "severity": 0.6}}]),
    (("tornado", "whirlwind", "hurricane", "cyclone"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "tornado", "severity": 0.7}}]),
    (("aurora", "northern lights", "lights in the sky"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "aurora"}}]),
    (("eclipse", "sun goes dark", "darkness"), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "eclipse"}}]),
    (("flood",), lambda w, t, vs, ns: [{"op": "spectacle", "params": {"kind": "flood"}}]),
    (("plague", "pandemic", "sickness", "disease", "fever"), lambda w, t, vs, ns: [{"op": "pandemic", "params": {}}]),
    (("drought", "no rain", "dry"), lambda w, t, vs, ns: [{"op": "weather", "params": {"kind": "drought", "days": 120}}]),
    (("rain", "rains"), lambda w, t, vs, ns: [{"op": "weather", "params": {"kind": "rains"}}]),
    (("famine", "harvest fails", "crops fail"), lambda w, t, vs, ns: [{"op": "food", "params": {"delta": -w.food * 0.8}}]),
    (("feast", "bumper harvest", "plenty"), lambda w, t, vs, ns: [{"op": "food", "params": {"delta": 400}}, {"op": "mood", "params": {"target": "all", "happiness": 0.1}}]),
    (("gold", "treasure", "silver", "ore"), lambda w, t, vs, ns: [{"op": "business", "params": {"action": "open", "kind": "mine", "owner": "random:1"}},
                                                             {"op": "money", "params": {"target": "random:5", "delta": 600}}]),
    (("peace", "truce", "ceasefire"), lambda w, t, vs, ns: [{"op": "peace", "params": {"a": (vs + [None, None])[0], "b": (vs + [None, None])[1]}}]),
    (("war", "attack", "invade", "invasion"), lambda w, t, vs, ns: [] if ns and not vs else [{"op": "war", "params": {"a": (vs + [None, None])[0], "b": (vs + [None, None])[1]}}]),
    (("dam",), lambda w, t, vs, ns: [{"op": "river", "params": {"village": (vs or [None])[0], "diversion": 0.02 if any(k in t for k in ("break", "destroy", "open", "remove")) else 0.45}}]),
    (("magic", "mage", "power", "wizard", "sorcer", "witch"), lambda w, t, vs, ns: [{"op": "magic", "params": {"target": f"name:{c.name}", "strip": any(k in t for k in ("strip", "lose", "take away"))}} for c in ns] or
     [{"op": "magic", "params": {"target": "random:1"}}]),
    (("occupy", "conquer", "captured", "falls to"), lambda w, t, vs, ns: [{"op": "occupy", "params": {"village": (vs + [None, None])[1], "by": (vs + [None])[0]}}]),
    (("liberat", "freed", "free the"), lambda w, t, vs, ns: [{"op": "liberate", "params": {"village": (vs or [None])[0]}}]),
    (("wolves", "wolf", "tiger", "lion", "bear", "elephant", "deer", "horse", "cow", "cattle", "sheep", "goat", "dog", "cat", "bird", "eagle"),
     lambda w, t, vs, ns: [{"op": "animals", "params": {"species": next(k for k in ("wolves", "wolf", "tiger", "lion", "bear", "elephant", "deer", "horse", "cow", "cattle", "sheep", "goat", "dog", "cat", "bird", "eagle") if k in t).replace("wolves", "wolf"), "count": 4}}]),
    (("kill", "murder", "assassinate"), lambda w, t, vs, ns: [{"op": "act", "params": {"target": f"name:{ns[0].name}", "act": "kill", "who": ns[1].name}}] if len(ns) >= 2 else
     ([{"op": "kill", "params": {"target": f"name:{ns[0].name}", "cause": "the will of the gods"}}] if ns else [{"op": "kill", "params": {"target": "random:3", "cause": "the will of the gods"}}])),
    (("fight", "beat", "attack", "punch"), lambda w, t, vs, ns: [{"op": "act", "params": {"target": f"name:{ns[0].name}", "act": "brawl", "who": ns[1].name}}] if len(ns) >= 2 else []),
    (("steal", "rob"), lambda w, t, vs, ns: [{"op": "act", "params": {"target": f"name:{ns[0].name}" if ns else "random:3", "act": "steal", "who": ns[1].name if len(ns) > 1 else None}}]),
    (("marry", "falls in love", "fall in love"), lambda w, t, vs, ns: [{"op": "relationship", "params": {"a": ns[0].name, "b": ns[1].name, "delta": 80}},
                                                                   {"op": "act", "params": {"target": f"name:{ns[0].name}", "act": "propose", "who": ns[1].name}}] if len(ns) >= 2 else []),
    (("riot", "revolt", "uprising", "rebellion"), lambda w, t, vs, ns: [{"op": "act", "params": {"target": f"name:{ns[0].name}" if ns else "random:1", "act": "incite_riot"}},
                                                                       {"op": "mood", "params": {"target": "all", "grievance": 0.3}}]),
    (("rich", "wealth", "money", "gold coins"), lambda w, t, vs, ns: [{"op": "money", "params": {"target": f"name:{c.name}", "delta": 3000}} for c in ns] or [{"op": "money", "params": {"target": "all", "delta": 200}}]),
    (("poor", "bankrupt", "ruin"), lambda w, t, vs, ns: [{"op": "money", "params": {"target": f"name:{c.name}", "multiplier": 0.05}} for c in ns] or [{"op": "money", "params": {"target": "richest:5", "multiplier": 0.2}}]),
    (("happy", "joy", "festival", "circus", "celebrat"), lambda w, t, vs, ns: [{"op": "mood", "params": {"target": "all", "happiness": 0.15, "grievance": -0.08}},
                                                                            {"op": "feeling", "params": {"target": "all", "emotion": "joy", "level": 0.6}}]),
    (("angry", "rage", "fury", "hate"), lambda w, t, vs, ns: [{"op": "feeling", "params": {"target": f"name:{c.name}", "emotion": "anger", "level": 0.95}} for c in ns] or
     [{"op": "feeling", "params": {"target": "all", "emotion": "anger", "level": 0.7}}]),
    (("tax",), lambda w, t, vs, ns: [{"op": "policy", "params": {"field": "tax_rate", "value": 0.02 if any(k in t for k in ("cut", "abolish", "lower", "no tax")) else 0.35}}]),
    (("newcomers", "immigrants", "refugees", "caravan", "settlers"), lambda w, t, vs, ns: [{"op": "citizens", "params": {"count": 12}}]),
    (("leave", "exile", "banish"), lambda w, t, vs, ns: [{"op": "migrate", "params": {"target": f"name:{c.name}", "to": (vs or ["sky"])[-1]}} for c in ns]),
]


def rules_plan(world, text: str):
    """Read a decree with keywords when no model is available (or a model refused). Always does *something*."""
    t = " " + text.lower() + " "
    vs = _villages_in(world, t)
    ns = _names_in(world, t)
    effects = []
    for words, build in RULE_WORDS:
        if any(w_ in t for w_ in words):
            try:
                effects += build(world, t, vs, ns)
            except Exception:
                pass
    if not effects:
        effects = [{"op": "mood", "params": {"target": "all", "grievance": 0.05}}]
    effects.append({"op": "memory", "params": {"target": "random:12", "text": f"I will never forget the day the gods decreed: {text.strip()[:120]}",
                                                "emotion": "fear", "importance": 0.6}})
    home = vs[0] if (len(vs) == 1 and not any(e["op"] in ("war", "peace", "occupy") for e in effects)) else None
    return {"narration": text.strip()[:300].rstrip(".") + ".", "importance": 0.85, "effects": effects, "village": home}


def fallback_plan(text: str, world=None):
    t = text.lower()
    for k, plan in FALLBACK.items():
        if k in t:
            return plan
    return rules_plan(world, text) if world is not None else None
