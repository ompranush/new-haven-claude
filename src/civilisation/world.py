"""The World: owns all state, runs the systems in order, records history.

Design rule: the world is deterministic given (seed, config, injected events).
No LLM is needed. A Brain object is consulted only for events whose importance
crosses a threshold; the default brain is rules-based and free.
"""
from __future__ import annotations

import math
import pickle
import random
import threading
from dataclasses import asdict, replace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from contextlib import contextmanager

from . import terrain
from .models import (Business, Citizen, Movement, Policy, WorldEvent, TRAITS,
                     REL_SPOUSE, REL_FAMILY)
from .realm import Village, ELEMENTS, VFIELDS
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
    election_period_days=2 * 365,
    max_population=600,         # per village
    max_relationships=150,      # Dunbar's number: nobody keeps up with more than this, and it keeps growth linear
    demand_multiplier=1.0,
    era="medieval",             # ancient | medieval | industrial | modern | future
)


class World:
    """The realm. Five villages share one map, one river, one calendar and one cast of people;
    `focus` says which village the single-town systems (and `world.policy`, `world.alive()`…) mean."""

    def __init__(self, seed: int = 42, population: int = 300, width: int = 0, height: int = 0,
                 brain: Optional[Brain] = None, config: Optional[dict] = None, name: str = "New Haven"):
        self.realm_name = name
        self.seed = seed
        self.rng = random.Random(seed)
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        from .eras import ERAS
        e = ERAS.get(self.config["era"], ERAS["medieval"])
        for k in ("startup_cost", "base_wage"):
            if k not in (config or {}):
                self.config[k] = float(e[k])
        self.day = 0
        self.grid, regions, self.river_path, centres = terrain.generate_realm(self.rng)
        self.height, self.width = self.grid.shape
        self.grid_version = 0
        per = max(4, population // len(terrain.REALM_ORDER))
        self.villages: List[Village] = [
            Village(i, el, ELEMENTS[el]["name"], regions[i], centres[i], tech=float(e["tech"]), food=per * 10.0,
                    next_election_day=self.config["election_period_days"])
            for i, el in enumerate(terrain.REALM_ORDER)]
        for v in self.villages:
            v.tension = {o.idx: 0.05 for o in self.villages if o.idx != v.idx}
        self.focus = 0
        self.citizens: Dict[int, Citizen] = {}
        self.animals: Dict[int, "Animal"] = {}
        self.businesses: Dict[int, Business] = {}
        self.movements: Dict[int, Movement] = {}
        self.events: List[WorldEvent] = []        # rolling window of everything
        self.chronicle: List[WorldEvent] = []     # important events, kept forever
        self.realm_history: List[dict] = []
        self.wars: List[dict] = []                # every war, running or over
        self.fx: List[dict] = []                  # visual effects for the renderer: {type, x, y, day, until, village, ...}
        self.thoughts: List[dict] = []            # first-person lines for the UI: {day, cid, name, text, source}
        self.brain: Brain = brain or RulesBrain()
        self.brains: Dict[int, Brain] = {}        # per-citizen brains (sponsored residents); never pickled
        self.lock = threading.RLock()             # the shared village ticks on its own thread
        self.brain_calls = 0
        self._next_cid = 1
        self._next_bid = 1
        self._next_mid = 1
        for v in self.villages:
            with self.at(v.idx):
                self._seed_population(per)
                self._seed_businesses()
                from .systems import war, magic
                war.assign_roles(self)
                magic.seed_society(self)
                self.emit("founding", f"{per} settlers founded {v.name}, the {v.element} village, on the banks of the river.", 1.0)
        from .systems import animals
        animals.seed(self)
        for v in self.villages:
            with self.at(v.idx):
                self.record_metrics()
        self.record_realm_metrics()

    # ------------------------------------------------------------------ focus
    @contextmanager
    def at(self, idx: int):
        """Run the single-town systems for one village."""
        prev = self.focus
        self.focus = int(idx)
        try:
            yield self.villages[self.focus]
        finally:
            self.focus = prev

    @property
    def village(self) -> Village:
        return self.villages[self.focus]

    def village_of(self, c) -> Village:
        return self.villages[getattr(c, "village", 0)]

    def tiles(self, kinds, idx: Optional[int] = None):
        v = self.villages[self.focus if idx is None else idx]
        return terrain.tiles_in(self.grid, v.region, list(kinds))

    def set_tile(self, x: int, y: int, kind: int):
        if 0 <= x < self.width and 0 <= y < self.height and self.grid[y, x] != kind:
            self.grid[y, x] = kind
            self.grid_version += 1

    def add_fx(self, kind: str, x: float, y: float, days: int = 3, **extra):
        """Something the renderer should show happening at (x, y): fire, meteor, battle, flood, magic…"""
        self.fx.append({"type": kind, "x": float(x), "y": float(y), "day": self.day, "until": self.day + days,
                        "village": self.focus, **extra})
        if len(self.fx) > 200:
            self.fx = self.fx[-200:]

    # ------------------------------------------------------------------ setup
    def _new_id(self) -> int:
        i = self._next_cid
        self._next_cid += 1
        return i

    def new_name(self, sex: str, surname: Optional[str] = None) -> str:
        first = self.rng.choice(FIRST_F if sex == "F" else FIRST_M)
        return f"{first} {surname or self.rng.choice(LAST)}"

    def _random_home(self):
        v = self.village
        kinds = [terrain.TOWN, terrain.GRASS] + ([terrain.SAND] if v.element == "water" else []) + \
            ([terrain.ASH] if v.element == "fire" else [])
        tiles = self.tiles(kinds)
        cx, cy = v.centre
        near = [t for t in tiles if abs(t[0] - cx) + abs(t[1] - cy) <= 11]
        return self.rng.choice(near or tiles or [v.centre])

    def _seed_population(self, n: int):
        shape = self.config["initial_inequality"]
        for _ in range(n):
            sex = self.rng.choice("FM")
            age = self.rng.randint(18, 62)
            wealth = 300 + 900 * self.rng.paretovariate(shape)
            lean = ELEMENTS[self.village.element]["temper"]
            p = {k: float(np.clip(self.rng.gauss(0.5 + lean.get(k, 0.0), 0.18), 0.02, 0.98)) for k in TRAITS}
            home = self._random_home()
            c = Citizen(id=self._new_id(), name=self.new_name(sex), sex=sex, born_day=-age * 365 - self.rng.randint(0, 364),
                        personality=p, money=wealth, home=home, pos=home,
                        education=float(np.clip(self.rng.gauss(0.4, 0.2), 0.05, 1)),
                        skill=float(np.clip(self.rng.gauss(0.4, 0.15), 0.05, 1)),
                        goal=self.rng.choice(lifecycle.ADULT_GOALS), village=self.focus, origin=self.focus)
            c.surname = c.name.split()[-1]
            c.beliefs = politics.initial_beliefs(self, c)
            self.citizens[c.id] = c

    def _seed_businesses(self):
        adults = self.alive()
        kinds = ["farm", "farm", "farm", "bakery", "workshop", "market", "mine", "tavern", "school", "clinic"]
        for kind in kinds:
            owner = max(self.rng.sample(adults, min(5, len(adults))), key=lambda c: c.money)
            b = self.found_business(owner, kind, initial=True)
        # assign jobs
        for c in adults:
            if c.employer_id is None and self.rng.random() < 0.82:
                economy.hire_anyone(self, c)

    def found_business(self, owner: Citizen, kind: str, initial: bool = False) -> Business:
        spot = economy.pick_site(self, kind)
        from .eras import kind_label
        name = f"{self.rng.choice(BUSINESS_NAMES[kind])} {kind_label(self, kind)}"
        b = Business(id=self._next_bid, name=name, kind=kind, x=spot[0], y=spot[1], owner_id=owner.id,
                     founded_day=self.day, cash=2500.0 if initial else self.config["startup_cost"] * 0.8,
                     wage=self.config["base_wage"] * self.rng.uniform(0.8, 1.2), village=self.focus)
        self._next_bid += 1
        if kind == "farm":
            b.livestock = self.rng.randint(2, 6)
        self.businesses[b.id] = b
        if owner.employer_id is None:
            owner.employer_id = b.id
            owner.job = economy.JOB_FOR_KIND[kind]
            b.employees.append(owner.id)
        return b

    # ------------------------------------------------------------------ events
    def emit(self, category: str, text: str, importance: float = 0.2, actors: Optional[List[int]] = None, tone: str = "",
             kind: str = "", village: Optional[int] = None, secret: bool = False, culprit: Optional[int] = None) -> WorldEvent:
        ev = WorldEvent(self.day, category, text, float(importance), [a for a in (actors or []) if a is not None], tone=tone,
                        village=self.focus if village is None else village, kind=kind, secret=secret)
        if culprit is not None:
            ev.culprit = culprit              # who did it: they don't react as a victim would
        self.events.append(ev)
        self.events_total = getattr(self, "events_total", 0) + 1
        if len(self.events) > 20000:
            self.events = self.events[-20000:]
        if importance >= self.config["chronicle_threshold"]:
            self.chronicle.append(ev)
            if len(self.chronicle) > 1200:
                self.chronicle = self.chronicle[-1200:]
        if importance >= self.config["brain_threshold"] and ev.actors:
            self._consult_brain(ev)
        return ev

    def _consult_brain(self, ev: WorldEvent):
        # social incidents: only the person it happened *to* reacts; the perpetrator already acted
        culprit = getattr(ev, "culprit", None)
        for cid in [a for a in ev.actors if a != culprit][:1 if ev.category in ("social", "work", "crime") else 3]:
            c = self.citizens.get(cid)
            if not c or not c.alive:
                if cid in self.animals and self.animals[cid].alive:
                    from .systems import animals
                    animals.react(self, self.animals[cid], ev)
                continue
            with self.at(c.village):
                reaction = self.brains.get(cid, self.brain).react(self, c, ev)
                if reaction is None:
                    continue
                self._apply_reaction(c, ev, reaction)

    def _apply_reaction(self, c: Citizen, ev: WorldEvent, reaction):
        self.brain_calls += 1
        ev.brain = reaction.source
        reaction.apply(self, c, ev)
        if reaction.memory:
            self.think(c, reaction.memory, reaction.source, reaction.emotion, getattr(reaction, "options", None), getattr(reaction, "face", None))

    def think(self, c: Citizen, text: str, source: str = "rules", emotion: str = "neutral", options=None, face=None):
        t = {"day": self.day, "cid": c.id, "name": c.name, "text": text, "source": source, "emotion": emotion, "village": c.village}
        if options:
            t["options"], t["face"] = options, face        # the six things they considered, and which the die chose
        self.thoughts.append(t)
        self.thoughts_total = getattr(self, "thoughts_total", 0) + 1
        if len(self.thoughts) > 10000:
            self.thoughts = self.thoughts[-10000:]

    # ------------------------------------------------------------------ stepping
    def step(self, days: int = 1):
        with self.lock:
            for _ in range(days):
                self._step_day()

    def _step_day(self):
            self.day += 1
            import time as _t
            now = _t.time()
            for cid, b in list(self.brains.items()):        # session-only minds expire; the person carries on with the rules brain
                exp = getattr(b, "expires_at", None)
                if exp and now > exp:
                    if hasattr(b, "forget_key"):
                        b.forget_key()
                    del self.brains[cid]
                    c = self.citizens.get(cid)
                    if c and c.alive:
                        self.think(c, "My steward's voice has gone quiet. I'll manage on my own for a while.", "rules", "neutral")
            for brain in [self.brain] + list(self.brains.values()):
                drain = getattr(brain, "drain", None)
                if drain:                               # deferred (async) cognition lands here
                    try:
                        landed = drain()
                    except Exception as e:
                        self.emit("error", f"a mind's answers could not be read: {type(e).__name__}", 0.0, [], village=-1)
                        landed = []
                    for cid, ev, reaction in landed:
                        c = self.citizens.get(cid)
                        if c and c.alive:
                            with self.at(c.village):
                                try:
                                    self._apply_reaction(c, ev, reaction)
                                except Exception as e:    # a reaction that won't apply is dropped; the day goes on
                                    self.emit("error", f"{c.name}'s reaction could not be applied: {type(e).__name__}", 0.0, [], village=-1)
            from . import behaviour
            from .systems import river, war, magic, animals
            river.daily(self)
            for v in self.villages:
                if v.fallen:
                    continue
                with self.at(v.idx):
                    self.gdp_today = 0.0
                    v.crime_today = 0
                    lifecycle.daily(self)
                    economy.daily(self)
                    social.daily(self)
                    politics.daily(self)
                    disasters.daily(self)
                    behaviour.daily(self)
                    war.village_daily(self)
                    self.gdp_year += self.gdp_today
                    if self.day % 7 == 0:
                        self.record_metrics()
            war.daily(self)
            magic.daily(self)
            animals.daily(self)
            self.fx = [f for f in self.fx if f["until"] >= self.day]
            if self.day % 7 == 0:
                self.record_realm_metrics()
            if self.day % 365 == 0:
                self._year_end()

    def prune(self):
        """Keep the world's footprint finite: the dead keep their names but not their inner lives,
        and the living forget people they barely knew. The full record lives in the store."""
        keep_dead_days = 30 * 365
        for c in self.citizens.values():
            # someone's adopted person keeps their diary and their ties, whatever happens to them
            if not c.alive and not c.sponsor and (c.memories or c.relationships):
                c.memories, c.relationships = [], {}      # a name, dates and a family line are enough
        # anyone still pointed at by a family tie, a movement, the chronicle or a diary line must stay,
        # or lookups elsewhere would break
        referenced = set()
        for c in self.citizens.values():
            referenced.update(c.parent_ids)
            referenced.update(c.children)
            if c.spouse_id:
                referenced.add(c.spouse_id)
            referenced.update(c.relationships)
        for m in self.movements.values():
            referenced.add(m.founder_id)
            referenced.update(m.members)
        for e in self.chronicle:
            referenced.update(e.actors)
        for t in self.thoughts:
            referenced.add(t["cid"])
        if self.strike:
            referenced.update(self.strike["members"])
        gone = [c.id for c in self.citizens.values()
                if not c.alive and not c.sponsor and c.id not in referenced
                and self.day - (c.died_day or 0) > keep_dead_days]
        for cid in gone:
            del self.citizens[cid]
            self.brains.pop(cid, None)
        cap = int(self.config.get("max_relationships", 150))
        for c in self.alive():
            for oid, r in list(c.relationships.items()):
                other = self.citizens.get(oid)
                stale = self.day - r.last_interaction > 3 * 365
                if other is None or (not other.alive and abs(r.score) < 60) or (stale and abs(r.score) < 20):
                    del c.relationships[oid]
            # nobody can hold more than Dunbar's number of people in mind: family first, then whoever
            # they feel most strongly about, then whoever they saw most recently
            if len(c.relationships) > cap:
                ranked = sorted(c.relationships.values(),
                                key=lambda r: (0 if r.kind in (REL_SPOUSE, REL_FAMILY) else 1, -abs(r.score), -r.last_interaction))
                c.relationships = {r.other_id: r for r in ranked[:cap]}
        for m in list(self.movements.values()):
            if not m.alive and self.day - m.founded_day > keep_dead_days:
                del self.movements[m.id]
        return len(gone)

    def _year_end(self):
        self.prune()
        if not self.alive_all():
            self.emit("collapse", f"Year {self.year}: every village of {self.realm_name} is empty. The civilisation has ended.", 1.0, village=-1)
            return
        for v in self.villages:
            with self.at(v.idx):
                alive = self.alive()
                if not alive:
                    continue
                self.emit("year", f"Year {self.year} ends in {v.name}. Population {len(alive)}, GDP £{self.gdp_year:,.0f}, "
                                  f"unemployment {self.unemployment*100:.0f}%, {v.crimes_year} crimes ({v.arrests_year} arrests, "
                                  f"{v.murders_year} murders), river share {v.water_met*100:.0f}% of need.", 0.35)
                self.gdp_year = 0.0
                v.crimes_year = v.arrests_year = v.murders_year = 0

    def heirs_of(self, cid: int) -> List[Citizen]:
        """Living children of a citizen, eldest first — whoever could carry on their line."""
        c = self.citizens.get(cid)
        if not c:
            return []
        kids = [self.citizens[k] for k in c.children if k in self.citizens and self.citizens[k].alive]
        return sorted(kids, key=lambda x: -x.age_on(self.day))

    def inherit(self, dead_id: int, heir_id: int) -> Citizen:
        """A steward's line passes to one of their children: the sponsorship, the mind, the story."""
        with self.lock:
            dead, heir = self.citizens[dead_id], self.citizens[heir_id]
            heir.sponsor = dead.sponsor or "anonymous"
            parent_word = "mother" if dead.sex == "F" else "father"
            heir.backstory = (f"Child of {dead.name}. {dead.backstory}".strip())[:600]
            if dead_id in self.brains:
                self.brains[heir_id] = self.brains.pop(dead_id)      # the same mind, the next generation
            heir.remember(self.day, f"My {parent_word} {dead.name} is gone. Whatever they were to this town, it falls to me now.",
                          "grief", 0.9, [dead_id], tag="life")
            self.emit("society", f"{heir.name} took up {dead.name}'s place in {self.name}.", 0.6, [heir.id], tone="good")
            return heir

    def adopt_relative(self, dead_id: int) -> Citizen:
        """No children left: a relative of the same name arrives to carry the line on."""
        dead = self.citizens[dead_id]
        sex = self.rng.choice("FM")
        relation = self.rng.choice(["niece" if sex == "F" else "nephew", "cousin", "younger sibling"])
        c = self.adopt(self.new_name(sex, dead.surname), sex, self.rng.randint(20, 34), dead.personality,
                       backstory=f"{dead.name}'s {relation}, come to take over the family's place. {dead.backstory}".strip()[:600],
                       sponsor=dead.sponsor or "anonymous", village=dead.village)
        if dead_id in self.brains:
            self.brains[c.id] = self.brains.pop(dead_id)
        return c

    def inject(self, name: str, **kwargs):
        """God mode. See disasters.INJECTABLE for names."""
        with self.lock:
            return disasters.inject(self, name, **kwargs)

    def adopt(self, name: str, sex: str, age: int, personality: Dict[str, float], backstory: str = "",
              sponsor: str = "", brain: Optional[Brain] = None, money: float = 400.0, village: Optional[int] = None) -> Citizen:
        """A visitor moves their own person into the village, optionally with their own brain (and key)."""
        from .security import clean_text
        name, backstory, sponsor = clean_text(name, 40), clean_text(backstory, 600), clean_text(sponsor, 40)
        named_sponsor = bool(sponsor)
        sponsor = sponsor or "anonymous"      # always set, so adopted citizens are always countable
        sex = "F" if sex == "F" else "M"
        age = int(min(90, max(18, int(age))))
        idx = self.focus if village is None else int(village) % len(self.villages)
        with self.lock, self.at(idx):
            home = self._random_home()
            c = Citizen(id=self._new_id(), name=name or self.new_name(sex), sex=sex, born_day=self.day - int(age) * 365,
                        personality={k: float(np.clip(personality.get(k, 0.5), 0.02, 0.98)) for k in TRAITS}, money=money, home=home, pos=home,
                        education=0.5, skill=0.4, goal=self.rng.choice(lifecycle.ADULT_GOALS), backstory=backstory.strip()[:600], sponsor=sponsor.strip()[:40],
                        village=idx, origin=idx)
            c.surname = c.name.split()[-1]
            c.beliefs = politics.initial_beliefs(self, c)
            self.citizens[c.id] = c
            if brain is not None:
                self.brains[c.id] = brain
            economy.hire_anyone(self, c)
            self.emit("society", f"{c.name} arrived in {self.name}" + (f", sent by {c.sponsor}" if named_sponsor else "") + ". " + (backstory.strip()[:120] or ""), 0.6, [c.id])
            return c

    # ------------------------------------------------------------------ queries
    @property
    def year(self) -> int:
        return self.day // 365 + 1

    def alive(self) -> List[Citizen]:
        """The living people of the focused village."""
        v = self.focus
        return [c for c in self.citizens.values() if c.alive and c.village == v]

    def alive_all(self) -> List[Citizen]:
        return [c for c in self.citizens.values() if c.alive]

    def adults(self) -> List[Citizen]:
        v = self.focus
        return [c for c in self.citizens.values() if c.alive and c.village == v and c.age_on(self.day) >= 18]

    def open_businesses(self) -> List[Business]:
        v = self.focus
        return [b for b in self.businesses.values() if b.alive and b.village == v]

    def open_businesses_all(self) -> List[Business]:
        return [b for b in self.businesses.values() if b.alive]

    def movements_here(self) -> List[Movement]:
        v = self.focus
        return [m for m in self.movements.values() if m.village == v]

    def free(self, c) -> bool:
        """Not in a cell."""
        return c.jailed_until < self.day

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
            "tech": round(self.tech, 3), "movements": sum(1 for m in self.movements_here() if m.alive),
            "infected": sum(1 for c in alive if c.infected), "tax_rate": self.policy.tax_rate,
            "brain_calls": self.brain_calls, "village": self.village.name,
            "water": round(self.village.water_met * 100, 1), "diversion": round(self.village.diversion * 100, 1),
            "crimes": self.village.crimes_year, "jailed": sum(1 for c in alive if c.jailed_until >= self.day),
            "anger": round(float(np.mean([c.feel("anger") for c in alive])) * 100, 1) if alive else 0,
            "fear": round(float(np.mean([c.feel("fear") for c in alive])) * 100, 1) if alive else 0,
            "soldiers": sum(1 for c in alive if c.role == "guard"), "police": sum(1 for c in alive if c.role == "police"),
        }
        self.history.append(row)
        if len(self.history) > 2500:
            self.history = self.history[-2500:]

    def record_realm_metrics(self):
        """One row for the whole realm (what the store keeps), with each village's headline numbers inside."""
        per = {}
        for v in self.villages:
            last = v.history[-1] if v.history else {}
            per[v.element] = {k: last.get(k) for k in ("population", "happiness", "food_price", "unemployment", "treasury",
                                                     "grievance", "water", "crimes", "anger", "soldiers")}
            per[v.element]["occupied_by"] = self.villages[v.occupier].element if v.occupier is not None else None
            per[v.element]["fallen"] = v.fallen
        alive = self.alive_all()
        money = np.array([c.money for c in alive]) if alive else np.array([0.0])
        row = {"day": self.day, "year": self.year, "population": len(alive), "animals": sum(1 for a in self.animals.values() if a.alive),
               "happiness": round(float(np.mean([c.happiness for c in alive])) * 100, 1) if alive else 0,
               "gini": round(gini(money), 3), "median_wealth": round(float(np.median(money)), 2),
               "grievance": round(float(np.mean([c.grievance for c in alive])) * 100, 1) if alive else 0,
               "wars": sum(1 for w in self.wars if w.get("active")), "villages": per, "brain_calls": self.brain_calls}
        self.realm_history.append(row)
        if len(self.realm_history) > 2500:
            self.realm_history = self.realm_history[-2500:]

    def metrics_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.history)

    def citizens_df(self) -> pd.DataFrame:
        rows = []
        for c in self.citizens.values():
            if not c.alive:
                continue
            emp = self.businesses.get(c.employer_id) if c.employer_id else None
            rows.append({"id": c.id, "name": c.name, "village": self.villages[c.village].name, "role": c.role,
                         "age": c.age_on(self.day), "sex": c.sex, "job": c.job,
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
                heart = "❤️" if r.score > 10 else ("💢" if r.score < -10 else "🤝")
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
        brain, brains, lock = self.brain, self.brains, self.lock
        self.brain, self.brains, self.lock = None, {}, None
        try:
            with self.__class__.lock_of(lock):
                with open(path, "wb") as f:
                    pickle.dump(self, f)
        finally:
            self.brain, self.brains, self.lock = brain, brains, lock

    @staticmethod
    def lock_of(lock):
        return lock if lock is not None else threading.RLock()

    @staticmethod
    def load(path: str, brain: Optional[Brain] = None) -> "World":
        with open(path, "rb") as f:
            w = pickle.load(f)
        w.brain = brain or RulesBrain()
        w.brains = {}
        w.lock = threading.RLock()
        return w


def _vprop(name):
    return property(lambda self: getattr(self.villages[self.focus], name),
                    lambda self, value: setattr(self.villages[self.focus], name, value))


for _f in VFIELDS:                 # world.policy, world.treasury, world.food… mean the focused village's
    setattr(World, _f, _vprop(_f))


def gini(x: np.ndarray) -> float:
    x = np.sort(np.clip(np.asarray(x, dtype=float), 0, None))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    cum = np.cumsum(x)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)
