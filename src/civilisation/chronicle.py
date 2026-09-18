"""The documentary: turn a world's history into a story, with no LLM.

"What happened?" → eras, turning points, dynasties, the people who mattered.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import List
import numpy as np


def _era_name(row_start: dict, row_end: dict, events) -> str:
    cats = Counter(e.category for e in events)
    dpop = row_end["population"] - row_start["population"]
    dw = row_end["median_wealth"] - row_start["median_wealth"]
    if any(e.category == "politics" and "took power" in e.text for e in events):
        return "The Turning"
    if any("Riots" in e.text for e in events):
        return "The Unrest"
    if dpop < -8 or any("Famine" in e.text for e in events):
        return "The Dying"
    if cats["politics"] >= 4:
        return "The Age of Movements"
    if cats["disaster"] >= 5:
        return "The Hard Years"
    if dw > 800:
        return "The Prosperity"
    if dw < -600:
        return "The Squeeze"
    if cats["discovery"]:
        return "The Enlightenment"
    if dpop > 15:
        return "The Boom"
    return "The Quiet Years"


def eras(world, years_per_era: int = 5) -> List[dict]:
    hist = world.history
    if not hist:
        return []
    out = []
    span = years_per_era * 365
    start = 0
    while start < world.day:
        end = min(world.day, start + span)
        rows = [r for r in hist if start <= r["day"] <= end]
        evs = [e for e in world.chronicle if start < e.day <= end]
        if rows:
            out.append({"start": start, "end": end, "name": _era_name(rows[0], rows[-1], evs),
                        "events": evs, "pop": rows[-1]["population"], "gini": rows[-1]["gini"]})
        start = end
    return out


def turning_points(world, n: int = 25):
    """The most important events, spaced out so one bad month doesn't take every slot."""
    evs = sorted(world.chronicle, key=lambda e: -e.importance)
    chosen, taken = [], []
    for e in evs:
        if e.category in ("year",):
            continue
        if any(abs(e.day - d) < 20 and e.category == c for d, c in taken):
            continue
        chosen.append(e)
        taken.append((e.day, e.category))
        if len(chosen) >= n:
            break
    return sorted(chosen, key=lambda e: e.day)


def dynasties(world, top: int = 5):
    fam = defaultdict(lambda: {"alive": 0, "wealth": 0.0, "businesses": 0, "generations": set()})
    for c in world.citizens.values():
        f = fam[c.surname]
        f["generations"].add(c.generation)
        if c.alive:
            f["alive"] += 1
            f["wealth"] += c.money
    for b in world.open_businesses():
        if b.owner_id and b.owner_id in world.citizens:
            fam[world.citizens[b.owner_id].surname]["businesses"] += 1
    rows = [{"family": k, **v, "generations": len(v["generations"])} for k, v in fam.items() if v["alive"] > 0]
    return sorted(rows, key=lambda r: -r["wealth"])[:top]


def notable_people(world, n: int = 6):
    scored = []
    for c in world.citizens.values():
        score = abs(c.reputation) * 3 + sum(1 for e in world.chronicle if c.id in e.actors) + len(c.children) * 0.3
        if any(m.founder_id == c.id for m in world.movements.values()):
            score += 4
        scored.append((score, c))
    scored.sort(key=lambda t: -t[0])
    return [c for _, c in scored[:n]]


def chronicle_text(world) -> str:
    """Markdown documentary. Deterministic; the LLM narrator (llm.narrate) can polish it."""
    h = world.metrics_df()
    first, last = world.history[0], world.history[-1]
    lines = [f"# The Chronicle of {world.name}", "",
             f"*{world.year - 1} years, {world.day:,} days, seed {world.seed}.* "
             f"Population {first['population']} → {last['population']}. "
             f"Median wealth £{first['median_wealth']:,.0f} → £{last['median_wealth']:,.0f}. "
             f"Inequality {first['gini']:.2f} → {last['gini']:.2f}. "
             f"{len(world.citizens) - len(world.alive())} people have died; {sum(1 for c in world.citizens.values() if c.generation > 0)} were born here.", ""]
    if len(h) > 2:
        peak = h.loc[h.population.idxmax()]
        low = h.loc[h.happiness.idxmin()]
        lines.append(f"The population peaked at {int(peak.population)} in year {int(peak.year)}. "
                     f"The unhappiest week was in year {int(low.year)} (happiness {low.happiness:.0f}%, unemployment {low.unemployment:.0f}%).")
        lines.append("")
    lines += ["## Eras", ""]
    for e in eras(world):
        yr0, yr1 = e["start"] // 365 + 1, max(e["start"] // 365 + 1, (e["end"] - 1) // 365 + 1)
        cats = Counter(x.category for x in e["events"])
        summary = ", ".join(f"{v} {k}" for k, v in cats.most_common(3)) or "nothing of note"
        lines.append(f"- **Years {yr0}–{yr1}: {e['name']}** — {summary}; population {e['pop']}, Gini {e['gini']:.2f}")
    lines += ["", "## Turning points", ""]
    for e in turning_points(world):
        yr = e.day // 365 + 1
        lines.append(f"- **Day {e.day:,}** (year {yr}) · {e.text}")
    people = notable_people(world)
    if people:
        lines += ["", "## People who mattered", ""]
        for c in people:
            status = f"alive, {c.age_on(world.day)}" if c.alive else f"died day {c.died_day} of {c.cause_of_death}"
            best = max(c.memories, key=lambda m: m.importance).text if c.memories else "—"
            lines.append(f"- **{c.name}** ({c.job}, {status}, gen {c.generation}) — most vivid memory: *{best}*")
    dyn = dynasties(world)
    if dyn:
        lines += ["", "## Dynasties", ""]
        for d in dyn:
            lines.append(f"- The **{d['family']}** family: {d['alive']} living, £{d['wealth']:,.0f}, {d['businesses']} businesses, {d['generations']} generations")
    movs = [m for m in world.movements.values()]
    if movs:
        lines += ["", "## Movements", ""]
        for m in movs:
            f = world.citizens[m.founder_id]
            lines.append(f"- **{m.name}** — founded day {m.founded_day} by {f.name} against {m.grievance_theme}; "
                         f"{'party' if m.is_party else 'movement'}, {len(m.members)} members, {'active' if m.alive else 'dissolved'}, "
                         f"platform economic {m.platform['economic']:+.2f}")
    lines += ["", f"*Ruling today: {world.policy.ruling_party}. Tax {world.policy.tax_rate*100:.0f}%, welfare £{world.policy.welfare:.0f}/day, "
              f"{'public' if world.policy.public_education else 'private'} schools. Brain calls: {world.brain_calls}.*"]
    return "\n".join(lines)
