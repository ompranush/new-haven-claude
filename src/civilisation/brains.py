"""The cognition layer.

A Brain is asked one question: "given who this citizen is, what they remember and
what just happened, how do they react?" It returns a Reaction — a small structured
object the world knows how to apply. The world never calls a brain for mundane
days; only for events above `config["brain_threshold"]`.

RulesBrain is free and deterministic. LLMBrain (see llm.py) answers the same
question with a language model and falls back to RulesBrain on any failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .world import World
    from .models import Citizen, WorldEvent

ACTIONS = ["none", "avoid", "confront", "seek_support", "quit_job", "found_movement", "move_home", "donate", "reconcile"]
EMOTIONS = ["joy", "grief", "anger", "fear", "pride", "shame", "hope", "neutral", "envy", "love"]
# the older, smaller action list a model may still answer with
LEGACY = {"avoid": "walk_away", "confront": "retort", "seek_support": "seek_support", "quit_job": "quit_job",
          "found_movement": "found_movement", "move_home": "emigrate", "donate": "gift", "reconcile": "reconcile"}


@dataclass
class Reaction:
    emotion: str = "neutral"
    intensity: float = 0.3                       # 0..1
    memory: str = ""                             # first-person memory text
    relationship_changes: Dict[int, float] = field(default_factory=dict)
    grievance_delta: float = 0.0
    belief_shift: Dict[str, float] = field(default_factory=dict)
    action: str = "none"
    source: str = "rules"
    situation: str = ""
    options: list = field(default_factory=list)  # [(act, probability)] — the six things they considered
    face: int = 0                                # which of the six the die landed on
    target: Optional[int] = None
    level: float = 0.0
    forget: bool = False

    def apply(self, world: "World", c: "Citizen", ev: "WorldEvent"):
        from .systems import social
        from . import behaviour
        if self.source != "rules" and self.emotion in behaviour.SENSITIVITY:
            behaviour.stir(c, self.emotion, 0.3 + 0.5 * self.intensity, world.rng)     # a model's feelings count too
        mood = {"joy": 0.12, "pride": 0.10, "hope": 0.06, "love": 0.08, "neutral": 0.0, "fear": -0.08, "envy": -0.05,
                "shame": -0.08, "anger": -0.06, "grief": -0.15}.get(self.emotion, 0.0)
        c.happiness = float(np.clip(c.happiness + mood * self.intensity, 0, 1))
        for oid, delta in self.relationship_changes.items():
            oid = int(oid)
            if oid in world.citizens and oid != c.id:
                social.adjust(world, c, world.citizens[oid], float(np.clip(delta, -40, 40)))
        c.grievance = float(np.clip(c.grievance + self.grievance_delta, 0, 1))
        for k, d in self.belief_shift.items():
            if k in c.beliefs:
                lo, hi = (0, 1) if k == "trust" else (-1, 1)
                c.beliefs[k] = float(np.clip(c.beliefs[k] + float(np.clip(d, -0.3, 0.3)), lo, hi))
        self.action = LEGACY.get(self.action, self.action)
        line = behaviour.perform(world, c, ev, self) if self.action in behaviour.ACTS else ""
        if not self.memory:
            from .personality import voice
            text = ev.text
            if text.startswith(c.name):
                text = "I" + text[len(c.name):]
            else:
                text = text.replace(c.name + "'s", "my", 1).replace(c.name, "me", 1)
            self.memory = (voice(c, self.emotion if self.emotion in ("joy", "grief", "anger", "fear", "pride", "shame", "hope") else "neutral",
                                 text, salt=ev.day) + (" " + line if line else "")).strip()
        elif line and line not in self.memory:
            self.memory = f"{self.memory} {line}"
        weight = max(ev.importance, self.intensity) * (0.35 if self.forget else 1.0)
        c.remember(world.day, self.memory, self.emotion, weight, about=[a for a in ev.actors if a != c.id], tag=ev.category)


class Brain(Protocol):
    name: str
    def react(self, world: "World", c: "Citizen", ev: "WorldEvent") -> Optional[Reaction]: ...


class RulesBrain:
    """The behaviour engine (behaviour.py): situations, feelings with depth, six options and a loaded die."""
    name = "rules"

    def react(self, world: "World", c: "Citizen", ev: "WorldEvent") -> Optional[Reaction]:
        from . import behaviour
        return behaviour.decide(world, c, ev)


class SilentBrain:
    """Never reacts. Useful as the control arm of an experiment."""
    name = "silent"

    def react(self, world, c, ev):
        return None
