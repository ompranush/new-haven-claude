"""The realm: five villages, one per element, strung along one river.

Each village is a full society with its own government, treasury, granary, prices,
police, border force and council. `World` keeps one `Village` per element and
*focuses* on one at a time: while focused, `world.policy`, `world.treasury`,
`world.food`, `world.alive()` and friends all mean that village's. The daily
systems (economy, social, lifecycle, politics, disasters) are written for one
town, so the world simply runs them once per village with the focus set.

What ties the villages together — the river, borders, tension, war, occupation,
refugees and the secret societies of mages — lives in `systems/river.py`,
`systems/war.py` and `systems/magic.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Policy

ELEMENTS = {
    "sky":   dict(name="Skyreach",   colour="#8ab4ff", emblem="✦", power="lightning and storm-calling",
                  temper={"openness": 0.08, "neuroticism": -0.04},
                  blurb="a mountain village at the river's source, among snow and pine, who read the stars and the weather"),
    "air":   dict(name="Galehaven",  colour="#c9f0ff", emblem="༄", power="wind, speed and breath",
                  temper={"extraversion": 0.08, "conscientiousness": -0.05},
                  blurb="a windswept plains village of windmills, horse-breeders and traders"),
    "earth": dict(name="Rootwood",   colour="#8fbf5a", emblem="⛰", power="stone, roots and the growing of things",
                  temper={"conscientiousness": 0.08, "openness": -0.05},
                  blurb="a forest village of farmers, miners and woodcutters on the richest soil in the valley"),
    "fire":  dict(name="Emberhold",  colour="#ff7a45", emblem="🜂", power="flame, heat and the forge",
                  temper={"agreeableness": -0.08, "extraversion": 0.05},
                  blurb="a smith's village among ash fields and lava vents, proud, hot-tempered and short of water"),
    "water": dict(name="Tidewater",  colour="#3fa7d6", emblem="≋", power="tides, rain and healing",
                  temper={"agreeableness": 0.08, "neuroticism": 0.03},
                  blurb="a lakeside village at the end of the river, of fishers and healers, who get whatever the others leave"),
}

# Everything a village owns that the single-town systems read as `world.<name>`.
VFIELDS = ("name", "policy", "treasury", "food", "food_price", "market_price", "tech", "gdp_today", "gdp_year",
           "unemployment", "gini", "recession_days", "drought_days", "boom_days", "strike", "next_election_day",
           "reckonings", "history", "pandemic")


@dataclass
class Village:
    idx: int
    element: str
    name: str
    region: Tuple[int, int, int, int]
    centre: Tuple[int, int]
    policy: Policy = field(default_factory=Policy)
    treasury: float = 2000.0
    food: float = 600.0
    food_price: float = 3.0
    market_price: float = 3.0
    tech: float = 1.0
    gdp_today: float = 0.0
    gdp_year: float = 0.0
    unemployment: float = 0.0
    gini: float = 0.0
    recession_days: int = 0
    drought_days: int = 0
    boom_days: int = 0
    strike: Optional[dict] = None
    next_election_day: int = 730
    reckonings: list = field(default_factory=list)
    history: List[dict] = field(default_factory=list)
    pandemic: Optional[dict] = None
    # the river
    diversion: float = 0.1            # extra share of the passing river this village takes (dams, canals)
    water_in: float = 1.0             # flow reaching the village today
    water_take: float = 0.0           # what it kept
    water_met: float = 1.0            # kept / needed; below 1 the fields and the people go thirsty
    dam: Optional[Tuple[int, int]] = None
    # standing and conflict
    tension: Dict[int, float] = field(default_factory=dict)       # toward each other village, 0..1
    grudges: Dict[int, float] = field(default_factory=dict)       # long memory of wrongs, decays slowly
    treaties: Dict[int, dict] = field(default_factory=dict)
    occupier: Optional[int] = None    # village idx that holds this one
    occupied_since: Optional[int] = None
    fallen: bool = False              # nobody left; ruins
    fallen_day: Optional[int] = None
    wars_won: int = 0
    wars_lost: int = 0
    morale: float = 0.6
    tribute: float = 0.0              # share of tax paid to an occupier
    crime_today: int = 0
    crimes_year: int = 0
    arrests_year: int = 0
    murders_year: int = 0
    stipend: float = 20.0             # daily pay for police, guards and councillors

    @property
    def meta(self) -> dict:
        return ELEMENTS[self.element]

    @property
    def colour(self) -> str:
        return ELEMENTS[self.element]["colour"]

    @property
    def title(self) -> str:
        return f"{self.name} ({self.element.title()})"


def element_of(world, idx: int) -> str:
    return world.villages[idx].element
