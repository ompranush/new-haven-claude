"""The river: one channel, five villages, never enough.

Flow rises in the Sky mountains and runs down through Air, Earth and Fire to the Water
village's lake. Each village takes what it needs *plus* whatever its dams and canals
divert, and passes the rest on. A greedy or frightened council upstream starves every
field downstream — and every village downstream knows exactly whom to blame.
"""
from __future__ import annotations
import math
import numpy as np
from .. import terrain

NEED_PER_PERSON = 1.2 / 300          # in an average year the river carries a little less than the valley needs


def daily(world):
    rng = world.rng
    # the sky decides: seasons, and slow wet and dry spells
    world.rain = float(np.clip(getattr(world, "rain", 1.0) + rng.gauss(0, 0.02) + (1.0 - getattr(world, "rain", 1.0)) * 0.01, 0.35, 1.5))
    if rng.random() < 0.0008:                                     # a dry year sets in over the whole valley
        world.rain = max(0.35, world.rain - rng.uniform(0.3, 0.5))
        world.emit("environment", "The snows failed on the Sky mountains. The river is falling everywhere.", 0.8, [], village=-1, kind="drought_realm")
    season = 1.0 + 0.35 * math.sin(2 * math.pi * (world.day % 365) / 365)
    flow = 1.05 * season * world.rain
    for v in world.villages:                      # upstream first
        n = sum(1 for c in world.citizens.values() if c.alive and c.village == v.idx)
        need = max(0.02, n * NEED_PER_PERSON)
        v.water_in = flow
        if v.fallen or n == 0:
            v.water_take, v.water_met = 0.0, 1.0
            continue
        take = min(flow, need * (0.9 + 0.1 * rng.random()) + v.diversion * flow)
        if v.drought_days > 0:
            take *= 0.7
        lake = 0.2 if v.element == "water" else 0.0               # the lake keeps something back for its village
        v.water_take = take
        v.water_met = float(np.clip(take / need + lake, 0, 1.6))
        flow = max(0.0, flow - take * 0.85)                        # a little seeps back into the channel
        _dam(world, v)
    world.river_out = flow
    if world.day % 7 == 0:
        _consequences(world)


def farm_factor(v) -> float:
    """How well the fields do on the water this village gets."""
    return float(np.clip(0.25 + 0.75 * v.water_met, 0.25, 1.2))


def _dam(world, v):
    """Dams appear on the map when a village diverts hard, and come down when it stops."""
    if v.diversion >= 0.25 and v.dam is None:
        river = [p for p in world.river_path if terrain.region_of([v.region], *p) == 0]
        if river:
            x, y = river[len(river) // 2]
            v.dam = (x, y)
            with world.at(v.idx):
                world.set_tile(x, y, terrain.DAM)
                world.add_fx("construction", x, y, days=5)
                world.emit("river", f"{v.name} dammed the river. Less water will reach the villages below.", 0.7, [], kind="dam_built", tone="bad")
    elif v.diversion < 0.15 and v.dam is not None:
        x, y = v.dam
        with world.at(v.idx):
            world.set_tile(x, y, terrain.WATER)
            world.emit("river", f"{v.name}'s dam came down. The river runs free again.", 0.6, [], kind="dam_removed", tone="good")
        v.dam = None


def _consequences(world):
    """Weekly: thirst hurts, and the thirsty remember who took their water."""
    for v in world.villages:
        if v.fallen:
            continue
        short = max(0.0, 0.8 - v.water_met)
        if short <= 0:
            continue
        with world.at(v.idx):
            for c in world.alive():
                c.health = max(0.0, c.health - 0.02 * short)
                c.grievance = min(1.0, c.grievance + 0.03 * short)
                c.happiness = max(0.0, c.happiness - 0.02 * short)
            # blame flows uphill, in proportion to what each village above took beyond its need
            for up in world.villages[:v.idx]:
                if up.fallen:
                    continue
                blame = short * (0.3 + 3 * up.diversion)
                v.tension[up.idx] = float(min(1.0, v.tension.get(up.idx, 0) + 0.025 * blame))
                v.grudges[up.idx] = float(min(1.0, v.grudges.get(up.idx, 0) + 0.01 * blame))
            if short > 0.35 and world.rng.random() < 0.3:
                worst = max(world.villages[:v.idx], key=lambda u: u.diversion, default=None)
                who = f" {worst.name}'s dams hold back the water." if worst is not None and worst.diversion > 0.15 else ""
                world.emit("river", f"The river is a trickle in {v.name}; the fields are cracking.{who}", 0.6,
                           [c.id for c in world.alive()[:2]], kind="water_cut", tone="bad")
