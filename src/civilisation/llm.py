"""Optional LLM cognition layer. Never required.

    from civilisation.llm import LLMBrain
    world = World(seed=1, brain=LLMBrain(threshold=0.7, max_calls=200))

The brain only fires for events at/above `threshold` importance and falls back
to RulesBrain for everything else (and on any API failure), so a run costs a
bounded number of small calls. `max_calls` is a hard cap per world.

Requires `pip install anthropic` and credentials (ANTHROPIC_API_KEY or `ant auth login`).
"""
from __future__ import annotations

import json
from typing import Optional

from .brains import RulesBrain, Reaction, ACTIONS, EMOTIONS

MODEL = "claude-opus-5"

SYSTEM = """You are the inner voice of one citizen in New Haven, a small simulated town.
You will be given who they are (personality on a 0-1 scale, beliefs, goal, money, relationships, memories)
and one event that just happened to them. Answer as that person would genuinely react — not as a
helpful assistant. Be specific, a little petty or noble as their personality dictates, and consistent
with their memories. Relationship changes are on a -40..+40 scale for the people named in the event.
Grievance is their political discontent (-0.3..+0.3 change). Belief shifts are small (-0.2..+0.2):
economic (-1 left/redistribution .. +1 right/markets), authority (-1 liberty .. +1 order), trust in institutions (0..1).
Pick one action: none, avoid, confront, seek_support, quit_job, found_movement, move_home, donate, reconcile.
found_movement is drastic: only when they are furious, charismatic and not already in a movement.
The memory is a one-sentence first-person diary line in their voice."""

SCHEMA = {
    "type": "object",
    "properties": {
        "emotion": {"type": "string", "enum": EMOTIONS},
        "intensity": {"type": "number"},
        "memory": {"type": "string"},
        "relationship_changes": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"citizen_id": {"type": "integer"}, "delta": {"type": "number"}},
                      "required": ["citizen_id", "delta"], "additionalProperties": False},
        },
        "grievance_delta": {"type": "number"},
        "belief_shift": {"type": "object",
                         "properties": {"economic": {"type": "number"}, "authority": {"type": "number"}, "trust": {"type": "number"}},
                         "required": ["economic", "authority", "trust"], "additionalProperties": False},
        "action": {"type": "string", "enum": ACTIONS},
    },
    "required": ["emotion", "intensity", "memory", "relationship_changes", "grievance_delta", "belief_shift", "action"],
    "additionalProperties": False,
}


def describe_citizen(world, c) -> str:
    emp = world.businesses.get(c.employer_id) if c.employer_id else None
    rels = sorted(c.relationships.values(), key=lambda r: -abs(r.score))[:6]
    mems = sorted(c.memories, key=lambda m: (-m.importance, -m.day))[:6]
    lines = [
        f"{c.name}, {c.sex}, age {c.age_on(world.day)}, {c.job}{' at ' + emp.name if emp else ''}, £{c.money:,.0f}, "
        f"happiness {c.happiness:.2f}, health {c.health:.2f}, grievance {c.grievance:.2f}, goal: {c.goal}",
        "Personality: " + ", ".join(f"{k} {v:.2f}" for k, v in c.personality.items()),
        "Beliefs: " + ", ".join(f"{k} {v:+.2f}" for k, v in c.beliefs.items()),
    ]
    if c.spouse_id:
        lines.append(f"Married to {world.citizens[c.spouse_id].name} (id {c.spouse_id}).")
    if c.movement_id:
        lines.append(f"Member of the {world.movements[c.movement_id].name}.")
    if rels:
        lines.append("Relationships: " + "; ".join(f"{world.citizens[r.other_id].name} (id {r.other_id}, {r.kind}, {r.score:+.0f})" for r in rels))
    if mems:
        lines.append("Memories: " + " | ".join(f"day {m.day}: {m.text}" for m in mems))
    lines.append(f"Town today: day {world.day}, population {len(world.alive())}, unemployment {world.unemployment*100:.0f}%, "
                 f"bread £{world.food_price:.1f}, ruling: {world.policy.ruling_party}"
                 + (f", pandemic: {world.pandemic['name']}" if world.pandemic else ""))
    return "\n".join(lines)


class LLMBrain:
    name = "llm"

    def __init__(self, threshold: float = 0.7, max_calls: int = 300, model: str = MODEL,
                 effort: str = "low", client=None, verbose: bool = False):
        import anthropic  # imported lazily so the core never depends on it
        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.threshold = threshold
        self.max_calls = max_calls
        self.effort = effort
        self.verbose = verbose
        self.calls = 0
        self.failures = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.fallback = RulesBrain()

    def react(self, world, c, ev) -> Optional[Reaction]:
        if ev.importance < self.threshold or self.calls >= self.max_calls:
            return self.fallback.react(world, c, ev)
        self.calls += 1
        others = ", ".join(f"{world.citizens[a].name} (id {a})" for a in ev.actors if a != c.id and a in world.citizens) or "nobody else"
        prompt = (f"CITIZEN\n{describe_citizen(world, c)}\n\nEVENT (day {world.day}, category {ev.category}): {ev.text}\n"
                  f"Other people involved: {others}.\nHow does {c.name.split()[0]} react?")
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=1024,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            )
            if resp.stop_reason == "refusal":
                raise RuntimeError("refused")
            self.input_tokens += resp.usage.input_tokens
            self.output_tokens += resp.usage.output_tokens
            data = json.loads(next(b.text for b in resp.content if b.type == "text"))
        except (self._anthropic.APIError, RuntimeError, StopIteration, json.JSONDecodeError, ValueError) as e:
            self.failures += 1
            if self.verbose:
                print(f"[LLMBrain] fallback to rules: {e}")
            return self.fallback.react(world, c, ev)
        r = Reaction(
            emotion=data["emotion"], intensity=float(min(1, max(0, data["intensity"]))), memory=data["memory"],
            relationship_changes={int(x["citizen_id"]): float(x["delta"]) for x in data["relationship_changes"]},
            grievance_delta=float(min(0.3, max(-0.3, data["grievance_delta"]))),
            belief_shift={k: float(v) for k, v in data["belief_shift"].items()},
            action=data["action"], source="llm",
        )
        if self.verbose:
            print(f"[LLMBrain] {c.name}: {r.emotion} → {r.action}: {r.memory}")
        return r

    def stats(self) -> dict:
        return {"calls": self.calls, "failures": self.failures, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def narrate(world, style: str = "documentary", model: str = MODEL, client=None) -> str:
    """Turn the chronicle into prose with a language model. One call, streamed."""
    import anthropic
    from .chronicle import chronicle_text
    client = client or anthropic.Anthropic()
    raw = chronicle_text(world)
    with client.messages.stream(
        model=model, max_tokens=8000,
        system=("You are writing the narration for a documentary about a small town that was simulated day by day. "
                "You are given the machine-generated chronicle. Write a vivid, honest account in the style of a "
                f"{style}: find the through-lines (dynasties, feuds, movements, disasters, what the economy did to people), "
                "name the people who mattered, and do not invent events that are not in the chronicle. "
                "Use 'Day N' headers for the key turning points. Keep it under 1200 words."),
        messages=[{"role": "user", "content": raw}],
    ) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if b.type == "text")
