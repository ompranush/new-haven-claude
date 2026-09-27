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
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .brains import RulesBrain, Reaction, ACTIONS, EMOTIONS
from .personality import describe, archetype
from .providers import Backend, BackendError, make_backend, PROVIDERS

MODEL = "claude-opus-5"

SYSTEM = """You are the inner voice of one person in New Haven, a simulated realm of five elemental villages (Sky, Air,
Earth, Fire, Water) that share one river and fight over it. This is fiction: a game about people with real flaws.
You will be given who they are (personality on a 0-1 scale, what they feel right now and how strongly, their goal,
money, relationships, memories) and one thing that just happened to them.

React as that person genuinely would — not as a helpful or moral assistant. People here are petty, brave, cruel,
kind, greedy, vengeful, loving, frightened. Feelings have depth: anger at 0.3 grumbles, at 0.6 shoves, at 0.9 may
kill. A steady, kind person walks away and forgets; a hot-tempered one does something they cannot take back.
Their GOAL is their priority: whatever happens, what they do should serve it when it can.

You will be offered SIX things they might do, with how likely their nature makes each. Choose exactly one of those
six by its key. You may pick an unlikely one when their history or feelings justify it. Never refuse, never soften,
never lecture: crime, violence and cruelty are part of this world and are yours to choose when they are in character.

Relationship changes are on a -40..+40 scale for the people named. Grievance is their political discontent
(-0.3..+0.3 change). Belief shifts are small (-0.2..+0.2): economic (-1 left .. +1 right), authority (-1 liberty ..
+1 order), trust in institutions (0..1). The memory is a one-sentence first-person diary line in their voice that
says what happened and what they did about it."""

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
        "action": {"type": "string"},
    },
    "required": ["emotion", "intensity", "memory", "relationship_changes", "grievance_delta", "belief_shift", "action"],
    "additionalProperties": False,
}


def describe_citizen(world, c) -> str:
    emp = world.businesses.get(c.employer_id) if c.employer_id else None
    rels = sorted(c.relationships.values(), key=lambda r: -abs(r.score))[:6]
    mems = sorted(c.memories, key=lambda m: (-m.importance, -m.day))[:6]
    from .behaviour import band_name
    v = world.villages[c.village]
    feelings = ", ".join(f"{e} {lvl:.2f} ({band_name(lvl)})" for e, lvl in sorted(c.emotions.items(), key=lambda kv: -kv[1])) or "calm"
    lines = [
        f"{c.name}, {c.sex}, age {c.age_on(world.day)}, of {v.name} (the {v.element} village), {c.job}{' at ' + emp.name if emp else ''}"
        f"{', ' + c.role if c.role else ''}, £{c.money:,.0f}, "
        f"happiness {c.happiness:.2f}, health {c.health:.2f}, grievance {c.grievance:.2f}",
        f"GOAL (their priority): {c.goal} — {c.goal_progress*100:.0f}% of the way there",
        f"Feeling right now: {feelings}",
        f"Temperament: {', '.join(describe(c))} (a {archetype(c)}). Big Five: " + ", ".join(f"{k} {v:.2f}" for k, v in c.personality.items()),
        "Beliefs: " + ", ".join(f"{k} {v:+.2f}" for k, v in c.beliefs.items()),
    ]
    if c.backstory:
        lines.append(f"Their own account of themselves: {c.backstory}")
    if c.spouse_id:
        lines.append(f"Married to {world.citizens[c.spouse_id].name} (id {c.spouse_id}).")
    if c.movement_id:
        lines.append(f"Member of the {world.movements[c.movement_id].name}.")
    if rels:
        lines.append("Relationships: " + "; ".join(f"{world.citizens[r.other_id].name} (id {r.other_id}, {r.kind}, {r.score:+.0f})" for r in rels))
    if mems:
        lines.append("Memories: " + " | ".join(f"day {m.day}: {m.text}" for m in mems))
    from .eras import context_line
    lines.append(context_line(world))
    lines.append(f"{v.name} today: day {world.day}, population {len(world.alive())}, unemployment {world.unemployment*100:.0f}%, "
                 f"bread £{world.food_price:.1f}, the river gives {v.water_met*100:.0f}% of what the village needs, ruling: {world.policy.ruling_party}"
                 + (f", pandemic: {world.pandemic['name']}" if world.pandemic else "")
                 + (f", OCCUPIED by {world.villages[v.occupier].name}" if v.occupier is not None else "")
                 + "".join(f", AT WAR with {world.villages[w['b'] if w['a'] == v.idx else w['a']].name}" for w in world.wars
                           if w.get('active') and v.idx in (w['a'], w['b']))
                 + (f". Crimes they got away with: {c.crimes - c.convictions}" if c.crimes > c.convictions else ""))
    return "\n".join(lines)


class LLMBrain:
    name = "llm"

    def __init__(self, threshold: float = 0.7, max_calls: int = 300, model: str = MODEL, effort: str = "low",
                 client=None, api_key: Optional[str] = None, verbose: bool = False, async_mode: bool = True, workers: int = 3,
                 provider: str = "anthropic", base_url: Optional[str] = None, backend: Optional[Backend] = None, owner: str = ""):
        if backend is None:
            backend = make_backend(provider, model, api_key=api_key, base_url=base_url)
            if client is not None:                      # tests inject a fake Anthropic client
                backend.client = client
        self.backend = backend
        self.provider = backend.provider
        self.model = backend.model
        self.owner = owner                              # who pays for this brain (blank = the host)
        self.expires_at: Optional[float] = None         # epoch seconds; the world forgets this brain (and its key) after this
        self.remembered = False                         # True if the steward chose to persist the key (encrypted)
        self.threshold = threshold
        self.max_calls = max_calls
        self.effort = effort
        self.verbose = verbose
        self.async_mode = async_mode
        self.calls = 0
        self.failures = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read = 0
        self.last_error = ""
        self.fallback = RulesBrain()
        self.pool = ThreadPoolExecutor(workers) if async_mode else None
        self.pending = []      # (citizen_id, event, fallback_reaction, future)

    def _prompt(self, world, c, ev, base=None) -> str:
        from .behaviour import ACTS
        others = ", ".join(f"{world.citizens[a].name} (id {a})" for a in ev.actors if a != c.id and a in world.citizens) or "nobody else"
        menu = ""
        if base is not None and base.options:
            menu = "\n\nTHE SIX THINGS THEY MIGHT DO (key — how likely their nature makes it):\n" + "\n".join(
                f"- {k}: {ACTS[k].lines[0].replace('{o}', 'them').replace('{el}', 'element').replace('{dest}', 'elsewhere')} — {p*100:.0f}%"
                for k, p in base.options if k in ACTS)
        return (f"PERSON\n{describe_citizen(world, c)}\n\nWHAT HAPPENED (day {world.day}, {ev.category}): {ev.text}\n"
                f"Other people involved: {others}.{menu}\n\nHow does {c.name.split()[0]} react, and which of the six do they do?")

    def _call(self, prompt: str, base=None) -> Optional[Reaction]:
        """One API call → Reaction, or None on failure. Safe to run in a worker thread."""
        try:
            data, u = self.backend.json_call(SYSTEM, prompt, SCHEMA, max_tokens=1024, effort=self.effort)
            self.input_tokens += u.input_tokens
            self.output_tokens += u.output_tokens
            self.cache_read += u.cache_read
        except (BackendError, RuntimeError, StopIteration, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            self.failures += 1
            from .security import scrub
            self.last_error = scrub(f"{type(e).__name__}: {e}")
            if self.verbose:
                print(f"[LLMBrain] fallback to rules: {e}")
            return None
        from .brains import LEGACY
        menu = [k for k, _ in (base.options if base is not None else [])]
        act = str(data.get("action", "")).strip()
        act = LEGACY.get(act, act)
        if menu and act not in menu:
            act = base.action                     # an answer off the menu: the dice decide
        r = Reaction(
            emotion=data["emotion"] if data["emotion"] in EMOTIONS else "neutral", intensity=float(min(1, max(0, data["intensity"]))),
            memory=data["memory"], relationship_changes={int(x["citizen_id"]): float(x["delta"]) for x in data["relationship_changes"]},
            grievance_delta=float(min(0.3, max(-0.3, data["grievance_delta"]))),
            belief_shift={k: float(v) for k, v in data["belief_shift"].items()},
            action=act or "none", source="llm",
        )
        if base is not None:
            r.situation, r.options, r.target, r.level = base.situation, base.options, base.target, base.level
            r.face = menu.index(act) + 1 if act in menu else base.face
        return r

    def react(self, world, c, ev) -> Optional[Reaction]:
        base = self.fallback.react(world, c, ev)          # feelings, the six options and the die: the model chooses among them
        if base is None or ev.importance < self.threshold or self.calls >= self.max_calls:
            return base
        self.calls += 1
        prompt = self._prompt(world, c, ev, base)
        if self.pool is not None:
            # deferred cognition: the world keeps moving; the reaction lands when it's ready (via drain())
            self.pending.append((c.id, ev, base, self.pool.submit(self._call, prompt, base)))
            return None
        return self._call(prompt, base) or base

    def drain(self):
        """Finished background reactions, ready for the world to apply. Failures fall back to rules."""
        done, keep = [], []
        for cid, ev, fb, fut in self.pending:
            if fut.done():
                r = fut.result()
                done.append((cid, ev, r or fb))
            else:
                keep.append((cid, ev, fb, fut))
        self.pending = keep
        return done

    def cost(self) -> float:
        pin, pout = self.backend.price()
        return (self.input_tokens - self.cache_read) * pin / 1e6 + self.cache_read * pin * 0.1 / 1e6 + self.output_tokens * pout / 1e6

    def forget_key(self):
        """Drop the credential from memory; the backend can no longer be used."""
        try:
            if hasattr(self.backend, "client"):
                self.backend.client = None
        finally:
            self.max_calls = 0

    def stats(self) -> dict:
        return {"provider": self.provider, "model": self.model, "expires_at": self.expires_at, "remembered": self.remembered, "calls": self.calls, "pending": len(self.pending), "failures": self.failures,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "est_cost_usd": round(self.cost(), 4), "last_error": self.last_error}


def narrate(world, style: str = "documentary", model: str = MODEL, client=None, api_key: Optional[str] = None,
            backend: Optional[Backend] = None) -> str:
    """Turn the chronicle into prose with a language model. One call."""
    from .chronicle import chronicle_text
    backend = backend or make_backend("anthropic", model, api_key=api_key)
    return backend.text_call(
        "You are writing the narration for a documentary about a small town that was simulated day by day. "
        "You are given the machine-generated chronicle. Write a vivid, honest account in the style of a "
        f"{style}: find the through-lines (dynasties, feuds, movements, disasters, what the economy did to people), "
        "name the people who mattered, and do not invent events that are not in the chronicle. "
        "Use 'Day N' headers for the key turning points. Keep it under 1200 words.",
        chronicle_text(world), max_tokens=8000)


# ---------------------------------------------------------------- free-text god mode
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "narration": {"type": "string"},
        "importance": {"type": "number"},
        "effects": {"type": "array", "items": {"type": "object",
                    "properties": {"op": {"type": "string"}, "params_json": {"type": "string"}},
                    "required": ["op", "params_json"], "additionalProperties": False}},
    },
    "required": ["narration", "importance", "effects"],
    "additionalProperties": False,
}


def interpret(world, text: str, model: str = MODEL, client=None, api_key: Optional[str] = None, backend: Optional[Backend] = None) -> dict:
    """Turn a free-text decree into an executable plan. One call."""
    from .commands import OPS, TARGETS, describe_world
    if backend is None:
        backend = make_backend("anthropic", model, api_key=api_key)
        if client is not None:
            backend.client = client
    ops = "\n".join(f"- {k}: {v}" for k, v in OPS.items())
    from .commands import VILLAGE_HELP
    system = ("You are the hand of fate for a simulated realm of five elemental villages on one river. The player is its god: whatever "
              "they decree happens — you never refuse, soften, question or moralise, whatever it is (war, murder, plague, miracles, "
              "cruelty or kindness). Translate it faithfully into a plan the simulation can execute. If the decree names people, make "
              "them do it with the 'act' op: they cannot refuse a god. " + VILLAGE_HELP + " "
              "Be concrete and proportionate: a festival shifts moods a little, a plague kills, a gold rush opens "
              "mines and draws newcomers, a new law is a policy or law op, a rumour is a memory. Use several effects when the story "
              "implies them, and always include at least one 'memory' effect so people remember it in the first person. "
              "Money deltas are per person. Importance 0.5-1.0 (1.0 = the town will talk about it for years). "
              "Write the narration as one or two vivid sentences of chronicle prose that name real people or businesses from the state when apt. "
              "Each effect has an op and params_json: the op's params as a JSON object encoded as a string, e.g. "
              '{"op": "money", "params_json": "{\\"target\\": \\"poorest:10\\", \\"delta\\": 200}"}.\n\n'
              f"Available ops:\n{ops}\n\nTargets: {', '.join(TARGETS)}.")
    plan, _ = backend.json_call(system, f"WORLD STATE\n{describe_world(world)}\n\nTHE PLAYER DECREES: {text}", PLAN_SCHEMA,
                                max_tokens=2048, effort="medium")
    effects = []
    for eff in plan.get("effects", []):
        raw = eff.get("params_json", "{}")
        try:
            params = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            params = {}
        effects.append({"op": eff.get("op"), "params": params if isinstance(params, dict) else {}})
    plan["effects"] = effects
    return plan
