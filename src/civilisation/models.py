"""Core data models for New Haven.

Everything here is plain data. Behaviour lives in the systems modules so the
world can be inspected, serialised and replayed without dragging logic along.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

TRAITS = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]

# Relationship kinds, roughly ordered from warm to hostile.
REL_SPOUSE = "spouse"
REL_FAMILY = "family"
REL_FRIEND = "friend"
REL_COLLEAGUE = "colleague"
REL_ACQUAINTANCE = "acquaintance"
REL_RIVAL = "rival"
REL_ENEMY = "enemy"


@dataclass
class Memory:
    """One episodic memory. Importance decays; strong emotions decay slower."""
    day: int
    text: str
    emotion: str = "neutral"          # joy, grief, anger, fear, pride, shame, neutral
    importance: float = 0.3           # 0..1
    about: List[int] = field(default_factory=list)  # citizen ids involved
    tag: str = "life"                 # life, work, social, politics, disaster, economy


@dataclass
class Relationship:
    other_id: int
    score: float = 0.0                # -100 (hatred) .. +100 (devotion)
    kind: str = REL_ACQUAINTANCE
    last_interaction: int = 0
    interactions: int = 0


@dataclass
class Citizen:
    id: int
    name: str
    sex: str
    born_day: int                     # negative for the founding generation
    personality: Dict[str, float]
    money: float = 0.0
    job: str = "unemployed"
    employer_id: Optional[int] = None
    home: Tuple[int, int] = (0, 0)
    pos: Tuple[int, int] = (0, 0)
    happiness: float = 0.65
    health: float = 0.9
    hunger: float = 0.1
    energy: float = 0.9
    education: float = 0.3
    skill: float = 0.3
    grievance: float = 0.0            # accumulated discontent, feeds politics
    reputation: float = 0.0           # -1..1, what others think of them
    goal: str = "earn money"
    goal_progress: float = 0.0
    beliefs: Dict[str, float] = field(default_factory=dict)   # economic, authority, trust
    memories: List[Memory] = field(default_factory=list)
    relationships: Dict[int, Relationship] = field(default_factory=dict)
    alive: bool = True
    died_day: Optional[int] = None
    cause_of_death: Optional[str] = None
    spouse_id: Optional[int] = None
    parent_ids: List[int] = field(default_factory=list)
    children: List[int] = field(default_factory=list)
    generation: int = 0
    surname: str = ""
    movement_id: Optional[int] = None
    unemployed_days: int = 0
    infected: bool = False
    immune: bool = False
    infected_day: Optional[int] = None
    last_wage: float = 0.0
    backstory: str = ""               # who they say they are (sponsored citizens)
    sponsor: str = ""                 # display name of the person who adopted them, if any
    village: int = 0                  # index into World.villages
    emotions: Dict[str, float] = field(default_factory=dict)   # live feelings 0..1 that rise with events and fade with time
    role: str = ""                    # councillor | police | guard | "" — public office, paid by the village
    magic: Optional[dict] = None      # {"element", "power" 0..1, "practice" 0..1, "revealed": bool} — secret unless revealed
    jailed_until: int = -1            # day they walk free
    crimes: int = 0                   # offences they got away with or were caught for
    convictions: int = 0
    exiled_from: Optional[int] = None
    last_initiative: int = -999       # last day they acted on their own ambition
    origin: int = 0                   # village they were born in (refugees and exiles keep it)
    goal_target: Optional[int] = None # who a revenge is aimed at

    def feel(self, emotion: str) -> float:
        return self.emotions.get(emotion, 0.0)

    def dominant(self):
        if not self.emotions:
            return "neutral", 0.0
        k = max(self.emotions, key=self.emotions.get)
        return (k, self.emotions[k]) if self.emotions[k] > 0.05 else ("neutral", 0.0)

    def age_on(self, day: int) -> int:
        return max(0, (day - self.born_day) // 365)

    def rel(self, other_id: int) -> Relationship:
        r = self.relationships.get(other_id)
        if r is None:
            r = Relationship(other_id)
            self.relationships[other_id] = r
        return r

    def remember(self, day: int, text: str, emotion: str = "neutral", importance: float = 0.3,
                 about: Optional[List[int]] = None, tag: str = "life") -> Memory:
        m = Memory(day, text, emotion, float(min(1.0, max(0.0, importance))), list(about or []), tag)
        self.memories.append(m)
        if len(self.memories) > 60:
            # keep the most important + most recent
            self.memories.sort(key=lambda x: (x.importance, x.day), reverse=True)
            self.memories = sorted(self.memories[:60], key=lambda x: x.day)
        return m


@dataclass
class Business:
    id: int
    name: str
    kind: str
    x: int
    y: int
    owner_id: Optional[int]
    founded_day: int = 0
    cash: float = 500.0
    employees: List[int] = field(default_factory=list)
    wage: float = 30.0
    inventory: float = 0.0
    revenue_today: float = 0.0
    revenue_history: List[float] = field(default_factory=list)
    productivity: float = 1.0        # technology multiplier
    alive: bool = True
    closed_day: Optional[int] = None
    loss_days: int = 0
    livestock: int = 0               # farms keep a herd; it grazes on the map and adds to the food supply
    village: int = 0


@dataclass
class Movement:
    id: int
    name: str
    founder_id: int
    founded_day: int
    platform: Dict[str, float]        # economic, authority
    members: List[int] = field(default_factory=list)
    is_party: bool = False
    seats_won: int = 0
    alive: bool = True
    grievance_theme: str = "hardship"
    last_strike_day: int = -999
    village: int = 0


@dataclass
class Policy:
    tax_rate: float = 0.10
    welfare: float = 0.0              # daily payment to unemployed
    pension: float = 0.0              # daily payment to retirees
    min_wage: float = 0.0
    public_education: bool = False
    public_health: bool = False
    ruling_party: str = "Founders' Council"
    platform: Dict[str, float] = field(default_factory=lambda: {"economic": 0.15, "authority": 0.1})
    laws: List[str] = field(default_factory=list)      # active emergency laws: rationing, quarantine, public_works, tax_holiday, curfew
    approval: float = 0.6
    took_office: int = 0


@dataclass
class WorldEvent:
    day: int
    category: str
    text: str
    importance: float = 0.2           # 0..1, feeds the chronicle and the brain gate
    actors: List[int] = field(default_factory=list)
    brain: str = ""                   # which brain (if any) processed this event
    tone: str = ""                    # "good" / "bad" / "" — how it lands on the first actor
    village: int = -1                 # where it happened (-1: across the realm)
    kind: str = ""                    # situation key the behaviour engine understands (see behaviour.SITUATIONS)
    secret: bool = False              # only god sees it (the secret societies)


@dataclass
class Animal:
    """An animal living in or around a village. Wild ones roam; tame ones bond with a person."""
    id: int
    name: str
    species: str
    sex: str
    born_day: int
    village: int
    home: Tuple[int, int] = (0, 0)
    pos: Tuple[int, int] = (0, 0)
    health: float = 1.0
    hunger: float = 0.1
    temperament: Dict[str, float] = field(default_factory=dict)   # boldness, aggression, loyalty, curiosity
    emotions: Dict[str, float] = field(default_factory=dict)
    owner_id: Optional[int] = None
    bond: float = 0.0                 # 0..1 attachment to the owner
    wild: bool = True
    alive: bool = True
    died_day: Optional[int] = None
    cause_of_death: Optional[str] = None
    memories: List[Memory] = field(default_factory=list)
    sponsor: str = ""
    backstory: str = ""
    doing: str = "wandering"
    kills: int = 0
    magic: Optional[dict] = None      # only god can grant an animal power

    def age_on(self, day: int) -> int:
        return max(0, (day - self.born_day) // 365)

    def feel(self, emotion: str) -> float:
        return self.emotions.get(emotion, 0.0)

    def remember(self, day: int, text: str, emotion: str = "neutral", importance: float = 0.3,
                 about: Optional[List[int]] = None, tag: str = "life") -> Memory:
        m = Memory(day, text, emotion, float(min(1.0, max(0.0, importance))), list(about or []), tag)
        self.memories.append(m)
        if len(self.memories) > 30:
            self.memories = sorted(sorted(self.memories, key=lambda x: (x.importance, x.day), reverse=True)[:30], key=lambda x: x.day)
        return m
