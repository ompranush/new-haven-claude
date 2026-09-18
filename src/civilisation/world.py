"""The World: owns all state, runs the systems in order, records history.

Design rule: the world is deterministic given (seed, config, injected events).
No LLM is needed. A Brain object is consulted only for events whose importance
crosses a threshold; the default brain is rules-based and free.
"""
from __future__ import annotations

import math
import pickle
import random
from dataclasses import asdict, replace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import terrain
from .models import (Business, Citizen, Movement, Policy, WorldEvent, TRAITS,
                     REL_SPOUSE, REL_FAMILY)
from .names import FIRST_F, FIRST_M, LAST, BUSINESS_NAMES
from .systems import economy, social, lifecycle, politics, disasters
from .brains import RulesBrain, Brain

DEFAULT_CONFIG = dict(
    startup_cost=1000.0,        # cash needed to found a business
    base_wage=30.0,
    longevity=1.0,              # >1 = people live longer
    fertility=1.0,              # >1 = more births
    education_access=0.5,       # 0..1 share of children who can afford school without public education
    initial_inequality=1.6,     # Pareto shape; lower = more unequal
    random_shocks=True,         # random droughts, floods etc.
    brain_threshold=0.4,        # events at/above this importance are sent to the brain
    chronicle_threshold=0.55,   # events at/above this importance are kept forever
    election_period_days=4 * 365,
    max_population=1500,
    demand_multiplier=1.0,
)


class World:
    def __init__(self, seed: int = 42, population: int = 100, width: int = 64, height: int = 40,
                 brain: Optional[Brain] = None, config: Optional[dict] = None, name: str = "New Haven"):
        self.name = name
        self.seed = seed
        self.rng = random.Random(seed)
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.day = 0
        self.width, self.height = width, height
        self.grid = terrain.generate(self.rng, width, height)
        self.citizens: Dict[int, Citizen] = {}
        self.businesses: Dict[int, Business] = {}
        self.movements: Dict[int, Movement] = {}
        self.events: List[WorldEvent] = []        # rolling window of everything
        self.chronicle: List[WorldEvent] = []     # important events, kept forever
        self.history: List[dict] = []
        self.policy = Policy()
        self.treasury = 2000.0
        self.food = population * 10.0
        self.food_price = 3.0
        self.tech = 1.0
        self.gdp_today = 0.0
        self.gdp_year = 0.0
        self.unemployment = 0.0
        self.gini = 0.0
        self.pandemic: Optional[dict] = None
        self.recession_days = 0
        self.strike: Optional[dict] = None
        self.next_election_day = self.config["election_period_days"]
        self.brain: Brain = brain or RulesBrain()
        self.brain_calls = 0
        self._next_cid = 1
        self._next_bid = 1
        self._next_mid = 1
        self._seed_population(population)
        self._seed_businesses()
        self.emit("founding", f"{population} settlers founded {self.name} on the banks of the river.", 1.0)
        self.record_metrics()

    # ------------------------------------------------------------------ setup
    def _new_id(self) -> int:
        i = self._next_cid
        self._next_cid += 1
        return i

    def new_name(self, sex: str, surname: Optional[str] = None) -> str:
        first = self.rng.choice(FIRST_F if sex == "F" else FIRST_M)
        return f"{first} {surname or self.rng.choice(LAST)}"

    def _random_home(self):
        tiles = terrain.find_tiles(self.grid, terrain.TOWN) + terrain.find_tiles(self.grid, terrain.GRASS)
        return self.rng.choice(tiles)

    def _seed_population(self, n: int):
        shape = self.config["initial_inequality"]
        for _ in range(n):
            sex = self.rng.choice("FM")
            age = self.rng.randint(18, 62)
            wealth = 300 + 900 * self.rng.paretovariate(shape)
            p = {k: float(np.clip(self.rng.gauss(0.5, 0.18), 0.02, 0.98)) for k in TRAITS}
            home = self._random_home()
            c = Citizen(id=self._new_id(), name=self.new_name(sex), sex=sex, born_day=-age * 365 - self.rng.randint(0, 364),
                        personality=p, money=wealth, home=home, pos=home,
                        education=float(np.clip(self.rng.gauss(0.4, 0.2), 0.05, 1)),
                        skill=float(np.clip(self.rng.gauss(0.4, 0.15), 0.05, 1)),
                        goal=self.rng.choice(lifecycle.ADULT_GOALS))
            c.surname = c.name.split()[-1]
            c.beliefs = politics.initial_beliefs(self, c)
            self.citizens[c.id] = c

    def _seed_businesses(self):
        adults = list(self.citizens.values())
        kinds = ["farm", "farm", "farm", "bakery", "workshop", "market", "mine", "tavern", "school", "clinic"]
        for kind in kinds:
            owner = max(self.rng.sample(adults, 5), key=lambda c: c.money)
            b = self.found_business(owner, kind, initial=True)
        # assign jobs
        for c in adults:
            if c.employer_id is None and self.rng.random() < 0.82:
                economy.hire_anyone(self, c)

    def found_business(self, owner: Citizen, kind: str, initial: bool = False) -> Business:
        spot = economy.pick_site(self, kind)
        name = f"{self.rng.choice(BUSINESS_NAMES[kind])} {kind.title()}"
        b = Business(id=self._next_bid, name=name, kind=kind, x=spot[0], y=spot[1], owner_id=owner.id,
                     founded_day=self.day, cash=2500.0 if initial else self.config["startup_cost"] * 0.8,
                     wage=self.config["base_wage"] * self.rng.uniform(0.8, 1.2))
        self._next_bid += 1
        self.businesses[b.id] = b
        if owner.employer_id is None:
            owner.employer_id = b.id
            owner.job = economy.JOB_FOR_KIND[kind]
            b.employees.append(owner.id)
        return b

    # ------------------------------------------------------------------ events
    def emit(self, category: str, text: str, importance: float = 0.2, actors: Optional[List[int]] = None) -> WorldEvent:
        ev = WorldEvent(self.day, category, text, float(importance), list(actors or []))
        self.events.append(ev)
        if len(self.events) > 3000:
            self.events = self.events[-3000:]
        if importance >= self.config["chronicle_threshold"]:
            self.chronicle.append(ev)
        if importance >= self.config["brain_threshold"] and ev.actors:
            self._consult_brain(ev)
        return ev

    def _consult_brain(self, ev: WorldEvent):
        for cid in ev.actors[:3]:
            c = self.citizens.get(cid)
            if not c or not c.alive:
                continue
            reaction = self.brain.react(self, c, ev)
            if reaction is None:
                continue
            self.brain_calls += 1
            ev.brain = reaction.source
            reaction.apply(self, c, ev)

    # ------------------------------------------------------------------ stepping
    def step(self, days: int = 1):
        for _ in range(days):
            self.day += 1
            self.gdp_today = 0.0
            lifecycle.daily(self)
            economy.daily(self)
            social.daily(self)
            politics.daily(self)
            disasters.daily(self)
            self.gdp_year += self.gdp_today
            if self.day % 7 == 0:
                self.record_metrics()
            if self.day % 365 == 0:
                self._year_end()

    def _year_end(self):
        alive = self.alive()
        if not alive:
            self.emit("collapse", f"Year {self.year}: {self.name} is empty. The civilisation has ended.", 1.0)
            return
        self.emit("year", f"Year {self.year} ends. Population {len(alive)}, GDP £{self.gdp_year:,.0f}, "
                          f"unemployment {self.unemployment*100:.0f}%, inequality (Gini) {self.gini:.2f}.", 0.35)
        self.gdp_year = 0.0

    def inject(self, name: str, **kwargs):
        """God mode. See disasters.INJECTABLE for names."""
        return disasters.inject(self, name, **kwargs)

    # ------------------------------------------------------------------ queries
    @property
    def year(self) -> int:
        return self.day // 365 + 1

    def alive(self) -> List[Citizen]:
        return [c for c in self.citizens.values() if c.alive]

    def adults(self) -> List[Citizen]:
        return [c for c in self.citizens.values() if c.alive and c.age_on(self.day) >= 18]

    def open_businesses(self) -> List[Business]:
        return [b for b in self.businesses.values() if b.alive]

    def record_metrics(self):
        alive = self.alive()
        money = np.array([c.money for c in alive]) if alive else np.array([0.0])
        self.gini = gini(money)
        adults = [c for c in alive if c.age_on(self.day) >= 18]
        workers = [c for c in adults if c.age_on(self.day) < 65]
        employed = [c for c in workers if c.employer_id is not None]
        self.unemployment = 1 - len(employed) / max(1, len(workers))
        row = {
            "day": self.day, "year": self.year, "population": len(alive),
            "avg_wealth": round(float(money.mean()), 2), "median_wealth": round(float(np.median(money)), 2),
            "happiness": round(float(np.mean([c.happiness for c in alive])) * 100, 1) if alive else 0,
            "health": round(float(np.mean([c.health for c in alive])) * 100, 1) if alive else 0,
            "unemployment": round(self.unemployment * 100, 1), "food": round(self.food, 1),
            "food_price": round(self.food_price, 2), "gini": round(self.gini, 3),
            "gdp_day": round(self.gdp_today, 1), "businesses": len(self.open_businesses()),
            "treasury": round(self.treasury, 1), "grievance": round(float(np.mean([c.grievance for c in alive])) * 100, 1) if alive else 0,
            "avg_education": round(float(np.mean([c.education for c in alive])) * 100, 1) if alive else 0,
            "tech": round(self.tech, 3), "movements": sum(1 for m in self.movements.values() if m.alive),
            "infected": sum(1 for c in alive if c.infected), "tax_rate": self.policy.tax_rate,
            "brain_calls": self.brain_calls,
        }
        self.history.append(row)

    def metrics_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.history)

    def citizens_df(self) -> pd.DataFrame:
        rows = []
        for c in self.citizens.values():
            if not c.alive:
                continue
            emp = self.businesses.get(c.employer_id) if c.employer_id else None
            rows.append({"id": c.id, "name": c.name, "age": c.age_on(self.day), "sex": c.sex, "job": c.job,
                         "employer": emp.name if emp else "", "money": round(c.money), "happiness": round(c.happiness * 100),
                         "health": round(c.health * 100), "education": round(c.education * 100), "grievance": round(c.grievance * 100),
                         "goal": c.goal, "gen": c.generation, "x": c.pos[0], "y": c.pos[1],
                         "friends": sum(1 for r in c.relationships.values() if r.score >= 40),
                         "enemies": sum(1 for r in c.relationships.values() if r.score <= -40),
                         "movement": self.movements[c.movement_id].name if c.movement_id else "",
                         "economic": round(c.beliefs.get("economic", 0), 2), "infected": c.infected})
        return pd.DataFrame(rows)

    def events_df(self, n: int = 200) -> pd.DataFrame:
        return pd.DataFrame([asdict(e) for e in reversed(self.events[-n:])])

    def biography(self, cid: int) -> str:
        c = self.citizens[cid]
        age = c.age_on(self.day)
        emp = self.businesses.get(c.employer_id) if c.employer_id else None
        lines = [f"**{c.name}** — {'alive' if c.alive else f'died day {c.died_day} ({c.cause_of_death})'}, "
                 f"age {age}, {c.job}{' at ' + emp.name if emp else ''}, generation {c.generation}",
                 f"Money £{c.money:,.0f} · happiness {c.happiness*100:.0f}% · health {c.health*100:.0f}% · "
                 f"education {c.education*100:.0f}% · grievance {c.grievance*100:.0f}%",
                 "Personality: " + ", ".join(f"{k[:5]} {v:.2f}" for k, v in c.personality.items()),
                 f"Beliefs: economic {c.beliefs.get('economic',0):+.2f} (−left/+right), authority {c.beliefs.get('authority',0):+.2f}, trust {c.beliefs.get('trust',0):.2f}",
                 f"Goal: {c.goal} ({c.goal_progress*100:.0f}%)"]
        if c.spouse_id:
            lines.append(f"Spouse: {self.citizens[c.spouse_id].name}")
        if c.parent_ids:
            lines.append("Parents: " + ", ".join(self.citizens[p].name for p in c.parent_ids))
        if c.children:
            lines.append("Children: " + ", ".join(self.citizens[k].name for k in c.children))
        if c.movement_id:
            lines.append(f"Member of {self.movements[c.movement_id].name}")
        rels = sorted(c.relationships.values(), key=lambda r: -abs(r.score))[:8]
        if rels:
            lines.append("\n**Relationships**")
            for r in rels:
                o = self.citizens[r.other_id]
                heart = "❤️" if r.score > 0 else "💢"
                lines.append(f"- {o.name} ({r.kind}) {heart} {r.score:+.0f}")
        if c.memories:
            lines.append("\n**Memories**")
            for m in sorted(c.memories, key=lambda m: -m.importance)[:10]:
                lines.append(f"- Day {m.day}: {m.text} _({m.emotion}, {m.importance:.1f})_")
        return "  \n".join(lines)

    def social_graph(self):
        import networkx as nx
        g = nx.Graph()
        for c in self.alive():
            g.add_node(c.id, name=c.name, movement=c.movement_id, wealth=c.money)
        for c in self.alive():
            for r in c.relationships.values():
                if abs(r.score) >= 30 and r.other_id in g and c.id < r.other_id:
                    g.add_edge(c.id, r.other_id, weight=r.score, kind=r.kind)
        return g

    # ------------------------------------------------------------------ persistence
    def save(self, path: str):
        brain = self.brain
        self.brain = None
        try:
            with open(path, "wb") as f:
                pickle.dump(self, f)
        finally:
            self.brain = brain

    @staticmethod
    def load(path: str, brain: Optional[Brain] = None) -> "World":
        with open(path, "rb") as f:
            w = pickle.load(f)
        w.brain = brain or RulesBrain()
        return w


def gini(x: np.ndarray) -> float:
    x = np.sort(np.clip(np.asarray(x, dtype=float), 0, None))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    cum = np.cumsum(x)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)
