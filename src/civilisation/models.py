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


@dataclass
class Policy:
    tax_rate: float = 0.10
    welfare: float = 0.0              # daily payment to unemployed
    pension: float = 0.0              # daily payment to retirees
    min_wage: float = 0.0
    public_education: bool = False
    public_health: bool = False
    ruling_party: str = "Founders' Council"


@dataclass
class WorldEvent:
    day: int
    category: str
    text: str
    importance: float = 0.2           # 0..1, feeds the chronicle and the brain gate
    actors: List[int] = field(default_factory=list)
    brain: str = ""                   # which brain (if any) processed this event
