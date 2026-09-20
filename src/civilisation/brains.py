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
EMOTIONS = ["joy", "grief", "anger", "fear", "pride", "shame", "hope", "neutral"]


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

    def apply(self, world: "World", c: "Citizen", ev: "WorldEvent"):
        from .systems import social, politics
        c.remember(world.day, self.memory or ev.text, self.emotion, max(ev.importance, self.intensity),
                   about=[a for a in ev.actors if a != c.id], tag=ev.category)
        mood = {"joy": 0.12, "pride": 0.10, "hope": 0.06, "neutral": 0.0, "fear": -0.08,
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
        self._act(world, c, ev)

    def _act(self, world: "World", c: "Citizen", ev: "WorldEvent"):
        from .systems import social, politics, economy
        others = [a for a in ev.actors if a != c.id and a in world.citizens]
        if self.action == "avoid" and others:
            for o in others:
                c.rel(o).score -= 5
        elif self.action == "confront" and others:
            o = world.citizens[others[0]]
            social.adjust(world, c, o, -10)
            world.emit("social", f"{c.name} confronted {o.name} over it.", 0.3, [c.id, o.id])
        elif self.action == "reconcile" and others:
            o = world.citizens[others[0]]
            social.adjust(world, c, o, +15)
            world.emit("social", f"{c.name} made peace with {o.name}.", 0.3, [c.id, o.id])
        elif self.action == "seek_support":
            friends = [r for r in c.relationships.values() if r.score >= 40 and world.citizens[r.other_id].alive]
            for r in friends[:3]:
                r.score = min(100, r.score + 4)
            c.happiness = min(1, c.happiness + 0.03 * len(friends[:3]))
        elif self.action == "quit_job" and c.employer_id is not None:
            economy.leave_job(world, c, reason="quit")
            world.emit("work", f"{c.name} quit their job at {ev.text.split(' at ')[-1].rstrip('.') if ' at ' in ev.text else 'work'}.", 0.3, [c.id])
        elif self.action == "found_movement":
            politics.try_found_movement(world, c, force=True)
        elif self.action == "move_home":
            c.home = world._random_home()
            c.pos = c.home
        elif self.action == "donate" and c.money > 300:
            poorest = min(world.alive(), key=lambda x: x.money)
            gift = min(c.money * 0.1, 200)
            c.money -= gift
            poorest.money += gift
            social.adjust(world, poorest, c, +12)
            world.emit("social", f"{c.name} gave £{gift:.0f} to {poorest.name}, who was struggling.", 0.3, [c.id, poorest.id])


class Brain(Protocol):
    name: str
    def react(self, world: "World", c: "Citizen", ev: "WorldEvent") -> Optional[Reaction]: ...


class RulesBrain:
    """Personality-driven reactions. Cheap, deterministic, surprisingly expressive."""
    name = "rules"

    def react(self, world: "World", c: "Citizen", ev: "WorldEvent") -> Optional[Reaction]:
        p = c.personality
        rng = world.rng
        others = [a for a in ev.actors if a != c.id]
        r = Reaction(intensity=float(np.clip(ev.importance * (0.6 + 0.8 * p["neuroticism"]), 0.1, 1)))
        cat = ev.category
        text = ev.text.lower()
        bad = ev.tone == "bad" or (not ev.tone and any(w in text for w in ["died", "insult", "fired", "bankrupt", "lost", "flood", "drought", "attack",
                                       "raid", "starv", "layoff", "laid off", "collapsed", "closed", "cheated", "robbed", "mocked", "sneered", "accused", "laughed about", "crude joke", "layabout", "famine", "burst its banks", "riot"]))
        good = ev.tone == "good" or (not ev.tone and not bad and any(w in text for w in ["married", "born", "founded", "opened", "promoted", "won", "discover",
                                        "helped", "gave", "elected", "recovered", "hired", "took power", "raised wages"]))
        if bad:
            if "died" in text:
                r.emotion = "grief"
            elif others and (p["agreeableness"] < 0.45 or p["neuroticism"] > 0.6):
                r.emotion = "anger"
            elif cat in ("disaster", "economy", "work", "politics"):
                r.emotion = "fear"
            else:
                r.emotion = "anger" if p["agreeableness"] < 0.6 else "fear"
        elif good:
            r.emotion = "pride" if (c.id in ev.actors[:1] and p["extraversion"] > 0.5) else "joy"
        else:
            r.emotion = "hope" if p["openness"] > 0.6 else "neutral"

        # relationships: blame or credit the other actors
        for o in others:
            if o not in world.citizens:
                continue
            if r.emotion == "anger":
                r.relationship_changes[o] = -12 - 20 * (1 - p["agreeableness"])
            elif r.emotion in ("joy", "pride", "hope"):
                r.relationship_changes[o] = 6 + 10 * p["agreeableness"]
            elif r.emotion == "grief" and "died" not in text:
                r.relationship_changes[o] = -4

        # grievance & beliefs
        if bad:
            r.grievance_delta = 0.05 + 0.15 * ev.importance * (1 - p["agreeableness"] * 0.5)
            if cat in ("economy", "work"):
                r.belief_shift["economic"] = -0.06 * ev.importance      # hardship pushes left
                r.belief_shift["trust"] = -0.04
            if cat in ("disaster", "politics"):
                r.belief_shift["authority"] = 0.05 * p["neuroticism"]  # fear seeks order
                r.belief_shift["trust"] = -0.05
        elif good:
            r.grievance_delta = -0.05
            r.belief_shift["trust"] = 0.03

        # action selection
        roll = rng.random()
        if r.emotion == "anger" and others:
            if p["extraversion"] > 0.55 and roll < 0.5:
                r.action = "confront"
            else:
                r.action = "avoid"
        elif r.emotion in ("grief", "fear"):
            r.action = "seek_support" if p["extraversion"] > 0.4 else "none"
            if cat == "work" and "fired" in text and p["openness"] > 0.7 and roll < 0.2:
                r.action = "move_home"
        elif r.emotion in ("joy", "pride") and p["agreeableness"] > 0.7 and c.money > 800 and roll < 0.25:
            r.action = "donate"
        if bad and c.grievance + r.grievance_delta > 0.75 and p["extraversion"] > 0.6 and c.movement_id is None and roll < 0.35:
            r.action = "found_movement"
        if r.emotion == "anger" and p["agreeableness"] > 0.75 and roll > 0.7 and others:
            r.action = "reconcile"

        r.memory = self._memory_text(c, ev, r)
        return r

    @staticmethod
    def _memory_text(c: "Citizen", ev: "WorldEvent", r: Reaction) -> str:
        from .personality import voice
        text = ev.text
        if text.startswith(c.name):
            text = "I" + text[len(c.name):]
        else:
            text = text.replace(c.name + "'s", "my", 1).replace(c.name, "me", 1)
        return voice(c, r.emotion, text, salt=ev.day)


class SilentBrain:
    """Never reacts. Useful as the control arm of an experiment."""
    name = "silent"

    def react(self, world, c, ev):
        return None
