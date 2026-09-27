"""The behaviour engine: what a person *does* about what happens to them.

Three ideas:

1. **Situations.** Every event is read as one of ~45 real-life situations (insulted in
   public, robbed, a child born, the river cut off upstream, the village conquered…). Each
   situation lists the things a person might plausibly do about it, with a *relevance*
   0..1. Only responses at least 10% relevant are considered; absurd ones (a holiday while
   the house burns) only enter the menu when there are not six sensible ones.

2. **Feelings with depth.** A situation stirs an emotion by an amount set by temperament:
   the same insult barely moves a steady, kind person and sets a hot-tempered one boiling.
   Feelings build up with repeated provocation and fade at a temperament-dependent rate. The
   level matters: anger at 0.3 retorts, at 0.6 shoves, at 0.9 may kill. Every response has a
   band of feeling where it is natural.

3. **A loaded die.** Six responses are drawn for the menu (weighted by relevance, so the menu
   itself differs each time) and the die is loaded by temperament, the level of feeling, the
   person's goal, and their history with whoever is involved. Then it is rolled. Nobody's
   path is formulaic; nobody is forbidden anything; conscience only loads the die.

Goals always pull: every response carries goal tags, a matching goal loads it heavily, and
every day people take *initiatives* toward their goal through the same six-way roll.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .models import Citizen, WorldEvent

EMOTIONS = ("anger", "fear", "grief", "joy", "shame", "pride", "envy", "hope", "love")
BANDS = ((0.25, "calm"), (0.5, "stirred"), (0.75, "heated"), (1.01, "boiling"))

GOAL_TAGS = {
    "earn money": "wealth", "start a business": "wealth", "get rich": "wealth",
    "find a partner": "love", "have children": "family", "help family": "family", "grow up": "family",
    "learn a skill": "knowledge", "become respected": "status", "see the world change": "change",
    "gain power": "power", "master the old arts": "magic", "protect the village": "duty",
    "live quietly": "peace", "enjoy retirement": "peace", "get revenge": "revenge",
}
NEW_GOALS = ["gain power", "master the old arts", "protect the village", "live quietly", "get rich"]


def band_name(level: float) -> str:
    for hi, name in BANDS:
        if level < hi:
            return name
    return "boiling"


# ---------------------------------------------------------------- temperament
def disposition(c) -> Dict[str, float]:
    p = c.personality
    return {
        "temper": 0.55 * (1 - p["agreeableness"]) + 0.45 * p["neuroticism"],            # how hot
        "conscience": 0.55 * p["conscientiousness"] + 0.45 * p["agreeableness"],         # what holds them back
        "boldness": 0.45 * p["extraversion"] + 0.35 * (1 - p["neuroticism"]) + 0.2 * p["openness"],
        "vengeful": 0.5 * (1 - p["agreeableness"]) + 0.3 * p["neuroticism"] + 0.2 * p["conscientiousness"],
        "warmth": 0.6 * p["agreeableness"] + 0.4 * p["extraversion"],
        "drive": 0.6 * p["conscientiousness"] + 0.4 * p["openness"],
    }


SENSITIVITY = {   # which disposition amplifies which feeling
    "anger": lambda d, p: d["temper"], "fear": lambda d, p: p["neuroticism"], "grief": lambda d, p: 0.5 * p["agreeableness"] + 0.5 * p["neuroticism"],
    "shame": lambda d, p: 0.5 * p["neuroticism"] + 0.5 * p["conscientiousness"], "envy": lambda d, p: 0.6 * (1 - p["agreeableness"]) + 0.4 * p["neuroticism"],
    "joy": lambda d, p: 0.6 * p["extraversion"] + 0.4 * (1 - p["neuroticism"]), "pride": lambda d, p: 0.5 * p["extraversion"] + 0.5 * p["conscientiousness"],
    "hope": lambda d, p: 0.6 * p["openness"] + 0.4 * (1 - p["neuroticism"]), "love": lambda d, p: d["warmth"],
}
# per-day fraction that fades, for a person with temper/neuroticism 0 and 1
FADE = {"anger": (0.4, 0.1), "fear": (0.25, 0.06), "grief": (0.05, 0.015), "joy": (0.2, 0.12), "shame": (0.12, 0.04),
        "pride": (0.12, 0.06), "envy": (0.1, 0.02), "hope": (0.08, 0.05), "love": (0.03, 0.02)}


def stir(c, emotion: str, amount: float, rng=None) -> float:
    """Raise a feeling by an amount the person's temperament scales. Returns the new level."""
    if emotion not in SENSITIVITY:
        return 0.0
    d = disposition(c)
    s = SENSITIVITY[emotion](d, c.personality)
    jitter = rng.uniform(0.75, 1.3) if rng else 1.0
    rise = amount * (0.3 + 1.25 * s) * jitter
    cur = c.emotions.get(emotion, 0.0)
    new = cur + rise * (1 - 0.5 * cur)          # it is harder to get from 0.8 to 0.9 than from 0.2 to 0.3
    c.emotions[emotion] = float(min(1.0, new))
    return c.emotions[emotion]


def fade(c):
    p = c.personality
    for e, lvl in list(c.emotions.items()):
        calm, hot = FADE.get(e, (0.1, 0.05))
        key = p["neuroticism"] if e in ("fear", "grief", "shame", "hope") else disposition(c)["temper"]
        rate = calm + (hot - calm) * key
        lvl *= 1 - rate
        if lvl < 0.02:
            del c.emotions[e]
        else:
            c.emotions[e] = lvl


# ---------------------------------------------------------------- the acts
@dataclass
class Ctx:
    world: object
    c: Citizen
    ev: WorldEvent
    sit: str
    emotion: str
    level: float
    other: Optional[Citizen] = None
    forget: bool = False            # a shrug: the memory barely lodges
    note: str = ""                  # what they did, in their own words


@dataclass
class Act:
    key: str
    lines: Tuple[str, ...]                       # first person; {o} is the other's first name
    tags: Tuple[str, ...] = ()                   # goal tags it serves
    traits: Dict[str, float] = field(default_factory=dict)   # trait -> pull (-1..1)
    band: Tuple[float, float] = (0.0, 1.0)       # level of the situation's feeling where this is natural
    crime: str = ""
    violent: bool = False
    needs: Optional[Callable] = None
    do: Optional[Callable] = None


ACTS: Dict[str, Act] = {}


def act(key, lines, tags=(), traits=None, band=(0.0, 1.0), crime="", violent=False, needs=None):
    def deco(fn):
        ACTS[key] = Act(key, tuple([lines] if isinstance(lines, str) else lines), tuple(tags), traits or {}, band, crime, violent, needs, fn)
        return fn
    return deco


def _o(ctx):
    return ctx.other is not None and ctx.other.alive


def _first(c):
    return c.name.split()[0] if c else "them"


def _adj(ctx, delta):
    from .systems import social
    if _o(ctx):
        social.adjust(ctx.world, ctx.c, ctx.other, delta)


def _calm(ctx, f=0.5):
    if ctx.emotion in ctx.c.emotions:
        ctx.c.emotions[ctx.emotion] *= f


def _emit(ctx, text, imp=0.3, actors=None, kind="", tone="", culprit=None, **kw):
    return ctx.world.emit(kw.pop("category", "social"), text, imp, actors if actors is not None else [ctx.c.id], tone=tone, kind=kind,
                          culprit=culprit, **kw)


def _rich_target(ctx, exclude=()):
    w = ctx.world
    pool = [x for x in w.alive() if x.id != ctx.c.id and x.id not in exclude and x.money > ctx.c.money + 100 and w.free(x)]
    if not pool:
        return None
    return w.rng.choices(pool, weights=[x.money for x in pool])[0]


def _target_business(ctx):
    w = ctx.world
    if _o(ctx):
        owned = [b for b in w.open_businesses() if b.owner_id == ctx.other.id]
        if owned:
            return owned[0]
        if ctx.other.employer_id and ctx.other.employer_id in w.businesses and w.businesses[ctx.other.employer_id].alive:
            return w.businesses[ctx.other.employer_id]
    bs = [b for b in w.open_businesses() if b.owner_id != ctx.c.id]
    return w.rng.choice(bs) if bs else None


def _hurt(ctx, victim, amount, cause):
    victim.health = float(max(0.0, victim.health - amount))
    if victim.health <= 0.02 and victim.alive:
        from .systems import lifecycle
        lifecycle.die(ctx.world, victim, cause, killer=ctx.c.id)
        return True
    return False


# --- letting it go -----------------------------------------------------------------
@act("shrug_off", ("I let it go. Life's too short.", "Shrugged it off. Tomorrow's another day.", "Not worth a second thought."),
     ("peace",), {"agreeableness": 0.6, "neuroticism": -0.9}, (0.0, 0.35))
def _shrug(ctx):
    _calm(ctx, 0.2)
    ctx.forget = True


@act("walk_away", ("I walked away from {o}. Not worth it.", "Turned my back and left. Let {o} stew."), ("peace",),
     {"agreeableness": 0.4, "neuroticism": -0.5}, (0.0, 0.55))
def _walk(ctx):
    _adj(ctx, -3)
    _calm(ctx, 0.5)


@act("forgive", ("I forgave {o}. Carrying it would only hurt me.", "Told {o} it was forgotten. Mostly it is."), ("peace", "love"),
     {"agreeableness": 1.0, "neuroticism": -0.4}, (0.0, 0.45))
def _forgive(ctx):
    _adj(ctx, 10)
    _calm(ctx, 0.3)
    ctx.c.grievance = max(0.0, ctx.c.grievance - 0.04)


@act("brood", ("I can't stop turning it over. {o} will regret this.", "Sat up all night thinking about {o}."), ("revenge",),
     {"neuroticism": 0.8, "extraversion": -0.5, "agreeableness": -0.3}, (0.3, 0.85))
def _brood(ctx):
    _adj(ctx, -8)
    stir(ctx.c, ctx.emotion, 0.1)


@act("sulk", ("Said nothing to anyone all day.", "Stayed in. Let them wonder."), (), {"neuroticism": 0.6, "extraversion": -0.6}, (0.2, 0.6))
def _sulk(ctx):
    ctx.c.happiness = max(0.0, ctx.c.happiness - 0.02)


@act("weep", ("I cried until there was nothing left.", "Wept where nobody could see."), (), {"neuroticism": 0.7, "agreeableness": 0.3}, (0.3, 1.0))
def _weep(ctx):
    _calm(ctx, 0.75)


@act("drink", ("Drank until the tavern threw me out.", "Found the bottom of a lot of cups tonight."), (),
     {"conscientiousness": -0.8, "extraversion": 0.4, "neuroticism": 0.4}, (0.3, 1.0), needs=lambda x: x.c.money > 15)
def _drink(ctx):
    w, c = ctx.world, ctx.c
    spend = min(c.money, w.rng.uniform(10, 45))
    c.money -= spend
    taverns = [b for b in w.open_businesses() if b.kind == "tavern"]
    if taverns:
        taverns[0].cash += spend
        taverns[0].revenue_today += spend
    c.health = max(0.0, c.health - 0.015)
    _calm(ctx, 0.8)
    if ctx.emotion == "anger" and ctx.level > 0.7 and w.rng.random() < 0.3:
        # drink and fury: a brawl with whoever is nearest
        near = [x for x in w.alive() if x.id != c.id and x.pos == c.pos] or [x for x in w.alive() if x.id != c.id]
        if near:
            victim = w.rng.choice(near)
            _hurt(ctx, victim, w.rng.uniform(0.05, 0.2), "a tavern brawl")
            from .systems import crime
            crime.commit(w, c, "assault", victim, f"{c.name}, drunk and furious, started a brawl and beat {victim.name}.", 0.45, witnesses=3)


@act("seek_support", ("Went to my friends. They listened.", "Needed company tonight, and got it."), ("love", "family"),
     {"extraversion": 0.6, "agreeableness": 0.4}, (0.2, 0.9))
def _support(ctx):
    w, c = ctx.world, ctx.c
    friends = [w.citizens[r.other_id] for r in c.relationships.values() if r.score >= 40 and r.other_id in w.citizens and w.citizens[r.other_id].alive]
    for f in friends[:3]:
        c.rel(f.id).score = min(100, c.rel(f.id).score + 3)
    c.happiness = min(1.0, c.happiness + 0.02 * len(friends[:3]))
    _calm(ctx, 0.6 if friends else 0.9)


@act("pray", ("Went to the shrine of the {el}. Asked for strength.", "Lit a candle and asked the old powers for help."), ("magic", "peace"),
     {"conscientiousness": 0.4, "agreeableness": 0.4, "openness": 0.2}, (0.1, 0.9))
def _pray(ctx):
    stir(ctx.c, "hope", 0.2)
    _calm(ctx, 0.75)
    if ctx.c.magic is not None:
        ctx.c.magic["practice"] = min(1.0, ctx.c.magic.get("practice", 0) + 0.01)


@act("work_harder", ("Threw myself into work. It's the only thing I control.", "Put in extra hours. Money doesn't argue."),
     ("wealth", "status", "duty"), {"conscientiousness": 0.9}, (0.0, 0.7), needs=lambda x: x.c.employer_id is not None)
def _work(ctx):
    c = ctx.c
    c.money += c.last_wage * 0.5
    c.skill = min(1.0, c.skill + 0.004)
    c.health = max(0.0, c.health - 0.01)
    _calm(ctx, 0.8)


@act("study", ("Buried myself in books. Knowledge is the way out.", "Studied late into the night."), ("knowledge", "status", "magic"),
     {"openness": 0.8, "conscientiousness": 0.5}, (0.0, 0.6))
def _study(ctx):
    ctx.c.education = min(1.0, ctx.c.education + 0.01)
    ctx.c.skill = min(1.0, ctx.c.skill + 0.003)


@act("keep_secret", ("Told no one. Some things you carry alone.",), (), {"extraversion": -0.6, "conscientiousness": 0.3}, (0.0, 0.8))
def _secret(ctx):
    pass


# --- words ---------------------------------------------------------------------------
@act("retort", ("Gave {o} as good as I got.", "Told {o} exactly what I thought of them. Loudly."), ("status",),
     {"extraversion": 0.6, "agreeableness": -0.6}, (0.2, 0.7), needs=_o)
def _retort(ctx):
    _adj(ctx, -8)
    _emit(ctx, f"{ctx.c.name} fired back at {ctx.other.name} in front of everyone.", 0.35, [ctx.other.id, ctx.c.id],
          kind="insulted", tone="bad", culprit=ctx.c.id)


@act("demand_apology", ("Demanded {o} apologise.",), ("status",), {"extraversion": 0.4, "conscientiousness": 0.5}, (0.2, 0.65), needs=_o)
def _demand(ctx):
    o = ctx.other
    if ctx.world.rng.random() < 0.3 + 0.6 * o.personality["agreeableness"] - 0.004 * o.rel(ctx.c.id).score * -1:
        _adj(ctx, 12)
        _calm(ctx, 0.3)
        _emit(ctx, f"{o.name} apologised to {ctx.c.name}.", 0.3, [ctx.c.id, o.id], kind="apology", tone="good")
    else:
        _adj(ctx, -10)
        stir(ctx.c, "anger", 0.2)
        _emit(ctx, f"{o.name} laughed off {ctx.c.name}'s demand for an apology.", 0.4, [ctx.c.id, o.id], kind="humiliated", tone="bad", culprit=o.id)


@act("mock_publicly", ("Made {o} a laughing stock in the square.",), ("status", "revenge"),
     {"extraversion": 0.6, "agreeableness": -0.8}, (0.35, 0.85), needs=_o)
def _mock(ctx):
    ctx.other.reputation = float(np.clip(ctx.other.reputation - 0.05, -1, 1))
    ctx.c.reputation = float(np.clip(ctx.c.reputation - 0.02, -1, 1))
    _emit(ctx, f"{ctx.c.name} mocked {ctx.other.name} in front of half the village.", 0.45, [ctx.other.id, ctx.c.id],
          kind="humiliated", tone="bad", culprit=ctx.c.id)


@act("spread_rumour", ("Let slip a few things about {o}. Let's see how they like it.", "Whispered what I know about {o}."),
     ("revenge", "status"), {"agreeableness": -0.7, "neuroticism": 0.4, "extraversion": 0.3}, (0.25, 0.8), needs=_o)
def _rumour(ctx):
    w, o = ctx.world, ctx.other
    o.reputation = float(np.clip(o.reputation - 0.06, -1, 1))
    for f in [w.citizens[r.other_id] for r in ctx.c.relationships.values() if r.score > 30 and r.other_id in w.citizens][:4]:
        f.rel(o.id).score = max(-100, f.rel(o.id).score - 8)
    if w.rng.random() < 0.3:
        _emit(ctx, f"Word got round that {ctx.c.name} was spreading stories about {o.name}.", 0.35, [o.id, ctx.c.id],
              kind="slandered", tone="bad", culprit=ctx.c.id)


@act("cut_ties", ("I'm done with {o}. Dead to me.",), ("peace",), {"agreeableness": -0.5, "conscientiousness": 0.3}, (0.3, 0.9), needs=_o)
def _cut(ctx):
    r = ctx.c.rel(ctx.other.id)
    r.score = min(r.score, -45)
    r.kind = "rival" if r.kind not in ("spouse", "family") else r.kind


@act("reconcile", ("Went to {o} and made peace.", "Shook hands with {o}. It felt better than I expected."), ("peace", "love"),
     {"agreeableness": 0.9, "extraversion": 0.3}, (0.0, 0.5), needs=_o)
def _reconcile(ctx):
    _adj(ctx, 15)
    _calm(ctx, 0.3)
    _emit(ctx, f"{ctx.c.name} made peace with {ctx.other.name}.", 0.3, [ctx.c.id, ctx.other.id], kind="reconciled", tone="good")


@act("apologise", ("Went to {o} and said sorry. It cost me something.",), ("peace", "love"), {"agreeableness": 0.8, "conscientiousness": 0.4},
     (0.0, 0.7), needs=_o)
def _apologise(ctx):
    _adj(ctx, 12)
    ctx.c.emotions.pop("shame", None)


@act("gift", ("Gave {o} something to show I meant it.", "Helped {o} out with a little money."), ("love", "status", "family"),
     {"agreeableness": 0.8, "extraversion": 0.2}, (0.0, 1.0), needs=lambda x: _o(x) and x.c.money > 80)
def _gift(ctx):
    amt = min(ctx.c.money * 0.1, 150)
    ctx.c.money -= amt
    ctx.other.money += amt
    _adj(ctx, 12)
    _emit(ctx, f"{ctx.c.name} gave {ctx.other.name} £{amt:.0f}.", 0.3, [ctx.other.id, ctx.c.id], kind="helped", tone="good")


@act("boast", ("Made sure everyone heard about it.",), ("status",), {"extraversion": 0.8, "agreeableness": -0.4}, (0.2, 1.0))
def _boast(ctx):
    w, c = ctx.world, ctx.c
    c.reputation = float(np.clip(c.reputation + 0.02, -1, 1))
    rivals = [w.citizens[r.other_id] for r in c.relationships.values() if r.score < -10 and r.other_id in w.citizens and w.citizens[r.other_id].alive]
    for r in rivals[:2]:
        stir(r, "envy", 0.3, w.rng)
        if r.feel("envy") > 0.5:
            w.emit("social", f"{r.name} seethed as {c.name} boasted of their luck.", 0.4, [r.id, c.id], tone="bad", kind="rival_success", culprit=c.id)


@act("celebrate", ("Threw a feast. Everyone came.", "Bought a round for the whole tavern."), ("status", "love"),
     {"extraversion": 0.9}, (0.2, 1.0), needs=lambda x: x.c.money > 60)
def _celebrate(ctx):
    w, c = ctx.world, ctx.c
    spend = min(c.money * 0.15, 250)
    c.money -= spend
    for f in [w.citizens[r.other_id] for r in c.relationships.values() if r.score > 20 and r.other_id in w.citizens and w.citizens[r.other_id].alive][:6]:
        f.happiness = min(1.0, f.happiness + 0.02)
        f.rel(c.id).score = min(100, f.rel(c.id).score + 4)
    _emit(ctx, f"{c.name} threw a feast.", 0.3, [c.id], kind="feast", tone="good")


@act("court", ("I've been thinking about {o}. Went to see them.", "Walked {o} home. Didn't want the walk to end."), ("love", "family"),
     {"extraversion": 0.5, "openness": 0.4}, (0.0, 1.0), needs=lambda x: x.c.spouse_id is None and x.c.age_on(x.world.day) >= 18)
def _court(ctx):
    w, c = ctx.world, ctx.c
    from .systems import social
    o = ctx.other if (_o(ctx) and ctx.other.spouse_id is None and ctx.other.sex != c.sex and ctx.other.age_on(w.day) >= 18) else None
    if o is None:
        pool = [x for x in w.alive() if x.spouse_id is None and x.sex != c.sex and 18 <= x.age_on(w.day) and abs(x.age_on(w.day) - c.age_on(w.day)) < 15]
        if not pool:
            return
        o = max(w.rng.sample(pool, min(5, len(pool))), key=lambda x: social.compatibility(c, x) + 0.01 * c.rel(x.id).score)
    ctx.other = o
    social.adjust(w, c, o, w.rng.uniform(4, 12))
    if c.rel(o.id).score > 55 and w.rng.random() < 0.25:
        _propose(ctx)


@act("propose", ("Asked {o} to marry me.",), ("love", "family"), {"extraversion": 0.4, "openness": 0.3, "neuroticism": -0.3}, (0.0, 1.0),
     needs=lambda x: _o(x) and x.c.spouse_id is None and x.other.spouse_id is None and x.other.sex != x.c.sex and x.c.rel(x.other.id).score > 35)
def _propose(ctx):
    w, c, o = ctx.world, ctx.c, ctx.other
    from .systems import social
    yes = o.rel(c.id).score / 100 * 0.7 + social.compatibility(c, o) * 0.4 + (0.1 if c.money > o.money else 0)
    if w.rng.random() < yes - 0.2:
        c.spouse_id, o.spouse_id = o.id, c.id
        c.rel(o.id).kind = o.rel(c.id).kind = "spouse"
        c.rel(o.id).score = o.rel(c.id).score = max(c.rel(o.id).score, 75)
        o.home = c.home
        for x in (c, o):
            x.happiness = min(1.0, x.happiness + 0.15)
            stir(x, "joy", 0.6)
            if x.goal == "find a partner":
                x.goal_progress = 1.0
        _emit(ctx, f"{c.name} and {o.name} got married.", 0.5, [c.id, o.id], kind="married", tone="good", category="society")
    else:
        _emit(ctx, f"{c.name} proposed to {o.name} and was turned down.", 0.45, [c.id, o.id], kind="rejected", tone="bad", culprit=o.id)


@act("leave_spouse", ("I left. I should have done it years ago.",), ("change", "peace"), {"agreeableness": -0.6, "openness": 0.4, "neuroticism": 0.4},
     (0.4, 1.0), needs=lambda x: x.c.spouse_id is not None)
def _leave(ctx):
    w, c = ctx.world, ctx.c
    sp = w.citizens.get(c.spouse_id)
    c.spouse_id = None
    if sp:
        sp.spouse_id = None
        c.rel(sp.id).kind = sp.rel(c.id).kind = "acquaintance"
        c.rel(sp.id).score = sp.rel(c.id).score = -30
        c.home = w._random_home()
        _emit(ctx, f"{c.name} walked out on {sp.name}.", 0.55, [sp.id, c.id], kind="abandoned", tone="bad", culprit=c.id, category="society")


@act("affair", ("I shouldn't. I did anyway.",), ("love", "change"), {"agreeableness": -0.5, "conscientiousness": -0.7, "extraversion": 0.5},
     (0.0, 1.0), needs=lambda x: x.c.spouse_id is not None)
def _affair(ctx):
    w, c = ctx.world, ctx.c
    pool = [x for x in w.alive() if x.id not in (c.id, c.spouse_id) and x.sex != c.sex and x.age_on(w.day) >= 18]
    if not pool:
        return
    lover = w.rng.choice(pool)
    c.rel(lover.id).score = min(100, c.rel(lover.id).score + 20)
    sp = w.citizens.get(c.spouse_id)
    if sp and sp.alive and w.rng.random() < 0.35:
        _emit(ctx, f"{sp.name} found out that {c.name} has been seeing {lover.name}.", 0.65, [sp.id, c.id, lover.id],
              kind="spouse_unfaithful", tone="bad", culprit=c.id, category="society")


@act("mourn", ("Sat with the family. Said the old words.", "We buried them by the river."), ("family", "love"),
     {"agreeableness": 0.6}, (0.2, 1.0))
def _mourn(ctx):
    _calm(ctx, 0.8)
    ctx.c.happiness = max(0.0, ctx.c.happiness - 0.02)


@act("comfort_others", ("Spent the day looking after the others.",), ("family", "duty", "love"), {"agreeableness": 0.9, "extraversion": 0.3}, (0.0, 0.8))
def _comfort(ctx):
    w, c = ctx.world, ctx.c
    for f in [w.citizens[r.other_id] for r in c.relationships.values() if r.score > 30 and r.other_id in w.citizens and w.citizens[r.other_id].alive][:4]:
        f.happiness = min(1.0, f.happiness + 0.02)
        f.rel(c.id).score = min(100, f.rel(c.id).score + 5)
    c.reputation = float(np.clip(c.reputation + 0.01, -1, 1))


# --- violence ----------------------------------------------------------------------------
@act("threaten", ("Told {o} what happens if they cross me again.",), ("revenge", "power"), {"agreeableness": -0.7, "extraversion": 0.5},
     (0.4, 0.9), needs=_o)
def _threaten(ctx):
    stir(ctx.other, "fear", 0.35, ctx.world.rng)
    _adj(ctx, -10)
    _emit(ctx, f"{ctx.c.name} threatened {ctx.other.name}.", 0.4, [ctx.other.id, ctx.c.id], kind="threatened", tone="bad", culprit=ctx.c.id)


@act("shove", ("Shoved {o} into the dirt.", "Put {o} on the ground. They had it coming."), ("revenge",),
     {"agreeableness": -0.7, "neuroticism": 0.4}, (0.45, 0.85), crime="assault", violent=True, needs=_o)
def _shove(ctx):
    from .systems import crime
    _hurt(ctx, ctx.other, 0.05, "a beating")
    _adj(ctx, -12)
    crime.commit(ctx.world, ctx.c, "assault", ctx.other, f"{ctx.c.name} shoved {ctx.other.name} to the ground.", 0.4, witnesses=2)


@act("brawl", ("Went for {o} with my fists.", "Fought {o} in the street."), ("revenge", "status"),
     {"agreeableness": -0.8, "extraversion": 0.4, "neuroticism": 0.4}, (0.6, 1.0), crime="assault", violent=True, needs=_o)
def _brawl(ctx):
    from .systems import crime
    w, c, o = ctx.world, ctx.c, ctx.other
    strength_c = c.health + 0.3 * disposition(c)["boldness"] + w.rng.random() * 0.6
    strength_o = o.health + 0.3 * disposition(o)["boldness"] + w.rng.random() * 0.6
    loser, winner = (o, c) if strength_c > strength_o else (c, o)
    killed = _hurt(ctx, loser, w.rng.uniform(0.05, 0.22), "a street fight")
    _hurt(ctx, winner, w.rng.uniform(0.0, 0.08), "a street fight")
    _adj(ctx, -20)
    crime.commit(w, c, "murder" if killed and loser is o else "assault", o,
                 f"{c.name} and {o.name} fought in the street; {loser.name} came off worst" + (" and did not get up." if killed else "."),
                 0.75 if killed else 0.5, witnesses=3)


@act("kill", ("I killed {o}. I'd do it again.", "It's done. {o} won't laugh at anyone now."), ("revenge", "power"),
     {"agreeableness": -1.0, "conscientiousness": -0.6, "neuroticism": 0.6}, (0.82, 1.0), crime="murder", violent=True, needs=_o)
def _kill(ctx):
    from .systems import crime
    w, c, o = ctx.world, ctx.c, ctx.other
    if w.rng.random() < 0.55 - 0.3 * o.health + 0.2 * disposition(c)["boldness"]:
        from .systems import lifecycle
        lifecycle.die(w, o, "murder", killer=c.id)
        crime.commit(w, c, "murder", o, f"{o.name} was found dead. {c.name} was seen leaving in a hurry.", 0.9, witnesses=w.rng.randint(0, 2), fx="blood")
    else:
        _hurt(ctx, o, 0.4, "an attack")
        crime.commit(w, c, "assault", o, f"{c.name} tried to kill {o.name}; {_first(o)} survived, badly hurt.", 0.8, witnesses=1)
    if c.goal == "get revenge":
        c.goal_progress = 1.0


@act("poison", ("Something in {o}'s cup. Nobody will know.",), ("revenge", "power", "wealth"),
     {"agreeableness": -0.9, "conscientiousness": 0.5, "openness": 0.4, "extraversion": -0.4}, (0.6, 1.0), crime="poisoning", violent=True, needs=_o)
def _poison(ctx):
    from .systems import crime, lifecycle
    w, c, o = ctx.world, ctx.c, ctx.other
    if w.rng.random() < 0.4:
        lifecycle.die(w, o, "poison", killer=c.id)
        crime.commit(w, c, "poisoning", o, f"{o.name} died suddenly after supper. Some say poison.", 0.85)
    else:
        o.health = max(0.05, o.health - 0.5)
        crime.commit(w, c, "poisoning", o, f"{o.name} fell violently ill. The healer suspects poison.", 0.65)


@act("smash_property", ("Smashed up {o}'s place.", "Put every window of theirs through."), ("revenge",),
     {"agreeableness": -0.7, "conscientiousness": -0.6}, (0.5, 1.0), crime="vandalism", violent=True)
def _smash(ctx):
    from .systems import crime
    b = _target_business(ctx)
    if b is None:
        return
    b.cash -= ctx.world.rng.uniform(150, 500)
    crime.commit(ctx.world, ctx.c, "vandalism", ctx.other if _o(ctx) else None, f"{b.name} was smashed up in the night.", 0.4, business=b)


@act("arson", ("Burned it. Let it all burn.", "Watched {o}'s place go up from the hill."), ("revenge",),
     {"agreeableness": -0.9, "conscientiousness": -0.7, "neuroticism": 0.6}, (0.75, 1.0), crime="arson", violent=True)
def _arson(ctx):
    from .systems import crime, economy
    w = ctx.world
    b = _target_business(ctx)
    if b is None:
        return
    x, y = b.x, b.y
    w.add_fx("fire", x, y, days=4)
    dead = []
    for e in list(b.employees):
        p = w.citizens[e]
        if w.rng.random() < 0.08:
            from .systems import lifecycle
            lifecycle.die(w, p, "fire", killer=ctx.c.id)
            dead.append(p.name)
    if w.rng.random() < 0.6:
        economy.bankrupt(w, b)
        from . import terrain
        w.set_tile(x, y, terrain.RUIN)
    else:
        b.cash -= 800
    crime.commit(w, ctx.c, "arson", ctx.other if _o(ctx) else None,
                 f"{b.name} burned down in the night" + (f"; {', '.join(dead)} died in the flames." if dead else "."), 0.8, business=b)


@act("sabotage", ("Made sure {o}'s business had a very bad week.",), ("revenge", "wealth"),
     {"agreeableness": -0.7, "conscientiousness": 0.4, "openness": 0.4}, (0.4, 0.9), crime="vandalism")
def _sabotage(ctx):
    from .systems import crime
    b = _target_business(ctx)
    if b is None:
        return
    b.cash -= 300
    b.productivity = max(0.5, b.productivity * 0.93)
    if ctx.world.rng.random() < 0.4:
        crime.commit(ctx.world, ctx.c, "vandalism", ctx.other if _o(ctx) else None, f"Someone sabotaged {b.name}'s tools.", 0.4, business=b)


@act("plot_revenge", ("I'll bide my time. But {o} will pay.",), ("revenge",), {"conscientiousness": 0.6, "agreeableness": -0.8}, (0.5, 1.0), needs=_o)
def _plot(ctx):
    c = ctx.c
    c.goal, c.goal_progress, c.goal_target = "get revenge", 0.0, ctx.other.id


@act("hire_thugs", ("Paid some men to teach {o} a lesson.",), ("revenge", "power"), {"agreeableness": -0.8, "conscientiousness": 0.3},
     (0.55, 1.0), crime="assault", violent=True, needs=lambda x: _o(x) and x.c.money > 300)
def _thugs(ctx):
    from .systems import crime
    ctx.c.money -= 250
    _hurt(ctx, ctx.other, ctx.world.rng.uniform(0.15, 0.35), "a beating")
    crime.commit(ctx.world, ctx.c, "assault", ctx.other, f"{ctx.other.name} was beaten by hired men in an alley.", 0.55)


# --- money ------------------------------------------------------------------------------
@act("steal", ("Took what I needed. They won't miss it.", "Lifted a purse at the market."), ("wealth",),
     {"conscientiousness": -0.8, "agreeableness": -0.6}, (0.0, 1.0), crime="theft")
def _steal(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    v = ctx.other if (_o(ctx) and ctx.other.money > 40 and ctx.sit.startswith("crime") is False) else _rich_target(ctx)
    if v is None:
        return
    amt = min(v.money * w.rng.uniform(0.05, 0.25), 400)
    v.money -= amt
    c.money += amt
    crime.commit(w, c, "theft", v, f"{v.name} was robbed of £{amt:.0f}.", 0.4 + min(0.2, amt / 2000))


@act("burgle", ("Went in through the back window. Took everything worth taking.",), ("wealth",),
     {"conscientiousness": -0.7, "agreeableness": -0.7, "neuroticism": -0.3}, (0.0, 1.0), crime="burglary")
def _burgle(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    v = _rich_target(ctx)
    if v is None:
        return
    amt = min(v.money * w.rng.uniform(0.15, 0.4), 1200)
    v.money -= amt
    c.money += amt
    crime.commit(w, c, "burglary", v, f"{v.name}'s house was burgled; £{amt:.0f} gone.", 0.5)


@act("swindle", ("Sold {o} a fine story and a worthless deal.", "A little creative bookkeeping."), ("wealth",),
     {"conscientiousness": 0.3, "agreeableness": -0.8, "openness": 0.5}, (0.0, 1.0), crime="fraud")
def _swindle(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    v = ctx.other if (_o(ctx) and ctx.other.money > 100) else _rich_target(ctx)
    if v is None:
        return
    amt = min(v.money * w.rng.uniform(0.1, 0.3), 900)
    v.money -= amt
    c.money += amt
    if w.rng.random() < 0.6:
        crime.commit(w, c, "fraud", v, f"{v.name} realised {c.name} had cheated them of £{amt:.0f}.", 0.45)


@act("embezzle", ("Nobody reads the ledgers. Why shouldn't I take my share?",), ("wealth", "power"),
     {"conscientiousness": -0.3, "agreeableness": -0.8}, (0.0, 1.0), crime="embezzlement",
     needs=lambda x: x.c.role == "councillor" and x.world.treasury > 300)
def _embezzle(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    amt = min(w.treasury * w.rng.uniform(0.03, 0.12), 2500)
    w.treasury -= amt
    c.money += amt
    if w.rng.random() < 0.5:
        crime.commit(w, c, "embezzlement", None, f"£{amt:.0f} went missing from {w.name}'s treasury. Councillor {c.name} is suspected.", 0.7)


@act("extort", ("Reminded {o} what I know. Their silence has a price.",), ("wealth", "power"),
     {"agreeableness": -0.8, "conscientiousness": 0.3, "extraversion": 0.3}, (0.2, 1.0), crime="extortion",
     needs=lambda x: _o(x) and x.other.money > 200)
def _extort(ctx):
    from .systems import crime
    w, c, o = ctx.world, ctx.c, ctx.other
    amt = min(o.money * 0.2, 500)
    o.money -= amt
    c.money += amt
    stir(o, "fear", 0.3, w.rng)
    crime.commit(w, c, "extortion", o, f"{c.name} forced {o.name} to pay £{amt:.0f} to keep quiet.", 0.5)


@act("beg", ("Swallowed my pride and asked for help.",), ("family",), {"agreeableness": 0.4, "neuroticism": 0.5, "extraversion": 0.2},
     (0.0, 1.0), needs=lambda x: x.c.money < 60)
def _beg(ctx):
    w, c = ctx.world, ctx.c
    rich = _rich_target(ctx)
    if rich and w.rng.random() < 0.3 + 0.6 * rich.personality["agreeableness"]:
        amt = min(rich.money * 0.03, 60)
        rich.money -= amt
        c.money += amt
        c.rel(rich.id).score = min(100, c.rel(rich.id).score + 10)
    else:
        stir(c, "shame", 0.3, w.rng)


@act("gamble", ("Put it all on the dice. Why not?", "Won a little, lost a lot."), ("wealth",),
     {"openness": 0.5, "conscientiousness": -0.7, "neuroticism": -0.2}, (0.0, 1.0), needs=lambda x: x.c.money > 30)
def _gamble(ctx):
    w, c = ctx.world, ctx.c
    stake = min(c.money * w.rng.uniform(0.1, 0.6), 1500)
    if w.rng.random() < 0.45:
        c.money += stake * w.rng.uniform(0.8, 2.5)
        stir(c, "joy", 0.3)
        if stake > 500:
            _emit(ctx, f"{c.name} won big at the dice.", 0.35, [c.id], kind="windfall", tone="good")
    else:
        c.money -= stake
        stir(c, "shame", 0.2)
        if stake > 400:
            _emit(ctx, f"{c.name} lost £{stake:.0f} at the dice.", 0.4, [c.id], kind="broke", tone="bad")


@act("ask_raise", ("Asked for more money. I'm worth it.",), ("wealth", "status"), {"extraversion": 0.5, "conscientiousness": 0.4, "neuroticism": -0.3},
     (0.0, 0.8), needs=lambda x: x.c.employer_id is not None)
def _raise(ctx):
    w, c = ctx.world, ctx.c
    b = w.businesses.get(c.employer_id)
    if b is None:
        return
    if b.cash > 20 * b.wage and w.rng.random() < 0.3 + 0.5 * c.skill:
        b.wage *= 1.04
        stir(c, "pride", 0.3)
    elif w.rng.random() < 0.15:
        from .systems import economy
        economy.leave_job(w, c, "fired")
        _emit(ctx, f"{c.name} asked {b.name} for a raise and was shown the door.", 0.45, [c.id] + ([b.owner_id] if b.owner_id else []),
              kind="fired", tone="bad", culprit=b.owner_id, category="work")


@act("quit_job", ("Walked out. I'm worth more than this.",), ("change", "status"), {"agreeableness": -0.4, "openness": 0.5, "conscientiousness": -0.3},
     (0.35, 1.0), needs=lambda x: x.c.employer_id is not None)
def _quit(ctx):
    from .systems import economy
    b = ctx.world.businesses.get(ctx.c.employer_id)
    economy.leave_job(ctx.world, ctx.c, "quit")
    _emit(ctx, f"{ctx.c.name} quit {b.name if b else 'their job'}.", 0.3, [ctx.c.id], kind="quit", category="work")


@act("find_work", ("Knocked on every door in town.", "Went looking for work. Anything."), ("wealth", "family"), {"conscientiousness": 0.7},
     (0.0, 1.0), needs=lambda x: x.c.employer_id is None and x.c.age_on(x.world.day) < 65)
def _find(ctx):
    from .systems import economy
    if economy.hire_anyone(ctx.world, ctx.c):
        b = ctx.world.businesses[ctx.c.employer_id]
        _emit(ctx, f"{ctx.c.name} found work at {b.name}.", 0.25, [ctx.c.id], kind="hired", tone="good", category="work")


@act("start_business", ("Put my savings into a place of my own.",), ("wealth", "status", "change"), {"openness": 0.6, "conscientiousness": 0.5, "extraversion": 0.3},
     (0.0, 0.8), needs=lambda x: x.c.money > x.world.config["startup_cost"] * 1.1)
def _start(ctx):
    from .systems import economy
    w, c = ctx.world, ctx.c
    if len(w.open_businesses()) >= max(12, len(w.alive()) // 5):
        return                               # the town can't carry another shop; the savings stay put
    c.money -= w.config["startup_cost"]
    if c.employer_id is not None:
        economy.leave_job(w, c)
    b = w.found_business(c, economy._best_kind(w))
    if c.goal in ("start a business",):
        c.goal_progress = 1.0
    _emit(ctx, f"{c.name} founded {b.name}.", 0.5, [c.id], kind="business_founded", tone="good", category="economy")


@act("work_overtime", ("Double shifts. Sleep is for the rich.",), ("wealth",), {"conscientiousness": 0.8, "neuroticism": 0.2},
     (0.0, 0.9), needs=lambda x: x.c.employer_id is not None)
def _overtime(ctx):
    ctx.c.money += ctx.c.last_wage * 0.8
    ctx.c.health = max(0.0, ctx.c.health - 0.02)
    ctx.c.happiness = max(0.0, ctx.c.happiness - 0.01)


@act("sell_belongings", ("Sold my mother's ring. Food first.",), ("family",), {"conscientiousness": 0.4}, (0.0, 1.0), needs=lambda x: x.c.money < 80)
def _sell(ctx):
    ctx.c.money += ctx.world.rng.uniform(20, 90)
    stir(ctx.c, "shame", 0.15)


@act("hoard", ("Filled the cellar with grain. Let the others learn.",), ("wealth", "family"), {"conscientiousness": 0.6, "neuroticism": 0.6, "agreeableness": -0.4},
     (0.0, 1.0), needs=lambda x: x.c.money > 150 and x.world.food > 50)
def _hoard(ctx):
    w, c = ctx.world, ctx.c
    units = min(w.food * 0.03, c.money / max(1, w.food_price), 60)
    w.food -= units
    c.money -= units * w.food_price
    c.hunger = 0.0
    if units > 20 and w.food_price > 5:
        _emit(ctx, f"{c.name} bought up {units:.0f} sacks of grain while prices rose.", 0.35, [c.id], kind="hoarding", category="economy")


@act("smuggle", ("Ran goods over the border at night.",), ("wealth",), {"openness": 0.6, "conscientiousness": -0.5, "neuroticism": -0.4},
     (0.0, 1.0), crime="smuggling")
def _smuggle(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    gain = w.rng.uniform(60, 400) * (1.8 if w.village.water_met < 0.6 or any(x.get("active") for x in w.wars) else 1.0)
    c.money += gain
    if w.village.water_met < 0.7:
        w.food += 15        # smuggled grain and water
    if w.rng.random() < 0.35:
        crime.commit(w, c, "smuggling", None, f"{c.name} was caught smuggling across the border.", 0.4)


@act("loot", ("Everyone was running. I took what was lying there.",), ("wealth",), {"conscientiousness": -0.8, "agreeableness": -0.5},
     (0.0, 1.0), crime="looting")
def _loot(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    bs = w.open_businesses()
    if not bs:
        return
    b = w.rng.choice(bs)
    amt = min(max(0.0, b.cash) * 0.15, 500)
    b.cash -= amt
    c.money += amt
    crime.commit(w, c, "looting", None, f"{c.name} looted {b.name} in the chaos.", 0.45, business=b)


# --- leaving ---------------------------------------------------------------------------------
@act("emigrate", ("Packed everything. There's nothing for me here now.", "Left for {dest}. A fresh start."), ("change", "wealth", "peace", "family"),
     {"openness": 0.8, "neuroticism": 0.3, "conscientiousness": -0.2}, (0.3, 1.0))
def _emigrate(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    here = w.village
    options = [v for v in w.villages if v.idx != here.idx and not v.fallen and v.occupier is None]
    if not options:
        return
    size = lambda v: sum(1 for x in w.citizens.values() if x.alive and x.village == v.idx)
    dest = max(options, key=lambda v: min(1.2, v.water_met) + 0.5 * w.rng.random() - v.tension.get(here.idx, 0) * 0.5 - size(v) / 120)
    ctx.note = dest.name
    crime.relocate(w, c, dest.idx, reason=f"left {here.name}")
    c.moved_day = w.day
    if c.spouse_id and c.spouse_id in w.citizens and w.citizens[c.spouse_id].alive and w.citizens[c.spouse_id].village == here.idx:
        crime.relocate(w, w.citizens[c.spouse_id], dest.idx, reason=f"followed {_first(c)}")


@act("flee", ("Took the children and ran.", "Ran for the hills with what I could carry."), ("family", "peace"),
     {"neuroticism": 0.8, "extraversion": -0.2}, (0.4, 1.0))
def _flee(ctx):
    w, c = ctx.world, ctx.c
    if w.rng.random() < 0.3:
        _emigrate(ctx)
    else:
        c.pos = (int(np.clip(c.pos[0] + w.rng.randint(-5, 5), 0, w.width - 1)), int(np.clip(c.pos[1] + w.rng.randint(-5, 5), 0, w.height - 1)))
        _calm(ctx, 0.8)


# --- the community ------------------------------------------------------------------------
@act("report_to_watch", ("Went to the watch and told them everything.",), ("duty", "peace"), {"conscientiousness": 0.8, "agreeableness": 0.3},
     (0.0, 1.0), needs=lambda x: _o(x) and x.ev.category == "crime" and x.world.free(x.other))
def _report(ctx):
    from .systems import crime
    w = ctx.world
    kind = ctx.ev.kind[6:] if ctx.ev.kind.startswith("crime_") else "theft"
    if w.rng.random() < 0.25 + 0.5 * crime.police_strength(w):
        crime.arrest(w, ctx.other, kind, ctx.c)


@act("vigilante", ("The watch won't do it, so I will.",), ("revenge", "duty"), {"agreeableness": -0.6, "extraversion": 0.5, "neuroticism": 0.3},
     (0.6, 1.0), crime="assault", violent=True, needs=_o)
def _vigil(ctx):
    _brawl(ctx)


@act("petition_council", ("Stood up at the council and said what everyone's thinking.",), ("change", "status", "duty"),
     {"extraversion": 0.6, "conscientiousness": 0.5}, (0.2, 0.9))
def _petition(ctx):
    w, c = ctx.world, ctx.c
    c.reputation = float(np.clip(c.reputation + 0.02, -1, 1))
    w.policy.approval = float(np.clip(w.policy.approval - 0.01, 0, 1))
    if w.rng.random() < 0.25:
        _emit(ctx, f"{c.name} stood up at the {w.name} council and demanded action.", 0.35, [c.id], kind="petition", category="politics")


@act("join_movement", ("Joined the cause. About time.",), ("change", "power"), {"extraversion": 0.4, "openness": 0.4},
     (0.2, 1.0), needs=lambda x: x.c.movement_id is None and any(m.alive for m in x.world.movements_here()))
def _join(ctx):
    w, c = ctx.world, ctx.c
    m = max((m for m in w.movements_here() if m.alive), key=lambda m: len(m.members))
    c.movement_id = m.id
    m.members.append(c.id)


@act("found_movement", ("Called a meeting. Enough is enough.",), ("change", "power", "status"),
     {"extraversion": 0.8, "openness": 0.4, "agreeableness": -0.2}, (0.4, 1.0), needs=lambda x: x.c.movement_id is None)
def _found(ctx):
    from .systems import politics
    politics.try_found_movement(ctx.world, ctx.c, force=True)


@act("incite_riot", ("Stood on a cart and told them to take what's theirs.", "Threw the first stone."), ("change", "revenge", "power"),
     {"agreeableness": -0.7, "extraversion": 0.7, "neuroticism": 0.5}, (0.6, 1.0), crime="rioting", violent=True)
def _riot(ctx):
    from .systems import politics
    politics.riot(ctx.world, ctx.c)


@act("run_for_council", ("Put my name forward for the council.",), ("power", "status", "change", "duty"),
     {"extraversion": 0.7, "conscientiousness": 0.5}, (0.0, 0.8), needs=lambda x: x.c.role != "councillor" and x.c.age_on(x.world.day) >= 25)
def _run_office(ctx):
    from .systems import war
    w, c = ctx.world, ctx.c
    c.ran_day = w.day
    council = [x for x in w.alive() if x.role == "councillor"]
    weakest = min(council, key=lambda x: x.reputation, default=None)
    if weakest is None or c.reputation + 0.2 * w.rng.random() > weakest.reputation + 0.1:
        if weakest is not None and len(council) >= war.COUNCIL_SIZE:
            weakest.role = ""
            _emit(ctx, f"{c.name} took {weakest.name}'s seat on the council of {w.name}.", 0.55, [c.id, weakest.id], kind="won_office",
                  tone="good", category="politics")
        else:
            _emit(ctx, f"{c.name} joined the council of {w.name}.", 0.5, [c.id], kind="won_office", tone="good", category="politics")
        c.role = "councillor"
        if c.goal == "gain power":
            c.goal_progress = 1.0
    else:
        c.reputation = float(np.clip(c.reputation - 0.02, -1, 1))
        stir(c, "shame", 0.2)


@act("enlist", ("Joined the border guard. Someone has to.",), ("duty", "status"), {"conscientiousness": 0.5, "extraversion": 0.3, "neuroticism": -0.4},
     (0.0, 1.0), needs=lambda x: x.c.role == "" and 18 <= x.c.age_on(x.world.day) <= 50)
def _enlist(ctx):
    ctx.c.role = "guard"
    if ctx.c.goal == "protect the village":
        ctx.c.goal_progress = min(1.0, ctx.c.goal_progress + 0.5)


@act("desert", ("Threw down my spear and went home.",), ("peace", "family"), {"neuroticism": 0.7, "conscientiousness": -0.5},
     (0.5, 1.0), crime="desertion", needs=lambda x: x.c.role == "guard")
def _desert(ctx):
    from .systems import crime
    ctx.c.role = ""
    if any(x.get("active") and ctx.c.village in (x["a"], x["b"]) for x in ctx.world.wars):
        crime.commit(ctx.world, ctx.c, "desertion", None, f"{ctx.c.name} deserted the border guard.", 0.5)


@act("betray_village", ("Sold what I know to the other side.",), ("wealth", "revenge"), {"agreeableness": -0.8, "conscientiousness": -0.5, "openness": 0.4},
     (0.5, 1.0), crime="treason")
def _betray(ctx):
    from .systems import crime
    w, c = ctx.world, ctx.c
    here = w.village
    enemy = max((v for v in w.villages if v.idx != here.idx and not v.fallen), key=lambda v: here.tension.get(v.idx, 0), default=None)
    if enemy is None:
        return
    c.money += w.rng.uniform(200, 700)
    enemy.tension[here.idx] = min(1.0, enemy.tension.get(here.idx, 0) + 0.05)
    here.morale = max(0.0, here.morale - 0.03)
    if w.rng.random() < 0.4:
        crime.commit(w, c, "treason", None, f"{c.name} was caught selling secrets to {enemy.name}.", 0.8)


@act("take_up_arms", ("Picked up a spear. Nobody takes our village.",), ("duty", "revenge", "status"),
     {"extraversion": 0.4, "neuroticism": -0.5, "agreeableness": -0.2}, (0.0, 1.0), needs=lambda x: 16 <= x.c.age_on(x.world.day) <= 60)
def _arms(ctx):
    if ctx.c.role == "":
        ctx.c.role = "guard"
    ctx.world.village.morale = min(1.0, ctx.world.village.morale + 0.01)


@act("collaborate", ("Work is work, whoever pays.", "Made myself useful to the new masters."), ("wealth", "peace"),
     {"agreeableness": 0.2, "conscientiousness": 0.3, "neuroticism": 0.4}, (0.0, 1.0), needs=lambda x: x.world.village.occupier is not None)
def _collab(ctx):
    ctx.c.money += 60
    ctx.c.reputation = float(np.clip(ctx.c.reputation - 0.04, -1, 1))


@act("resist", ("We meet at night. We will have our village back.",), ("revenge", "duty", "change", "magic"),
     {"agreeableness": -0.3, "conscientiousness": 0.5, "neuroticism": -0.3}, (0.3, 1.0), needs=lambda x: x.world.village.occupier is not None)
def _resist(ctx):
    w = ctx.world
    v = w.village
    v.morale = min(1.0, v.morale + 0.02)
    if ctx.c.magic:
        ctx.c.magic["practice"] = min(1.0, ctx.c.magic["practice"] + 0.02)
    if w.rng.random() < 0.15:
        occ = w.villages[v.occupier]
        _emit(ctx, f"Someone cut the throats of two {occ.name} soldiers in {v.name} in the night.", 0.55, [ctx.c.id], kind="resistance",
              category="war", secret=True)


@act("sabotage_dam", ("Opened the sluices on their dam. Let the river run.",), ("revenge", "duty", "change"),
     {"agreeableness": -0.5, "openness": 0.5, "neuroticism": -0.3}, (0.4, 1.0))
def _sabotage_dam(ctx):
    w = ctx.world
    here = w.village
    up = [v for v in w.villages if v.idx < here.idx and v.diversion > 0.15 and not v.fallen]
    if not up:
        return
    v = max(up, key=lambda v: v.diversion)
    v.diversion = max(0.05, v.diversion - 0.15)
    v.tension[here.idx] = min(1.0, v.tension.get(here.idx, 0) + 0.2)
    v.grudges[here.idx] = min(1.0, v.grudges.get(here.idx, 0) + 0.15)
    with w.at(v.idx):
        if v.dam:
            w.add_fx("flood", *v.dam, days=3)
        w.emit("war", f"Raiders from {here.name} broke the sluices of {v.name}'s dam in the night.", 0.75, [], kind="dam_sabotaged", tone="bad")


@act("raid_upstream", ("Crossed the border with the others and took back what's ours.",), ("revenge", "wealth", "duty"),
     {"agreeableness": -0.6, "extraversion": 0.5, "neuroticism": -0.2}, (0.5, 1.0), violent=True)
def _raid(ctx):
    from .systems import war
    war.border_raid(ctx.world, ctx.world.village, ctx.c)


@act("help_rescue", ("Went back in for them. I'd do it again.", "Pulled people out until my arms gave out."), ("duty", "status", "love"),
     {"agreeableness": 0.6, "extraversion": 0.3, "neuroticism": -0.6}, (0.0, 1.0))
def _rescue(ctx):
    w, c = ctx.world, ctx.c
    c.reputation = float(np.clip(c.reputation + 0.05, -1, 1))
    if w.rng.random() < 0.08:
        _hurt(ctx, c, 0.3, "a rescue")
    _emit(ctx, f"{c.name} risked their life pulling neighbours to safety.", 0.4, [c.id], kind="hero", tone="good", category="society")


@act("rebuild", ("Started clearing the rubble at first light.",), ("duty", "wealth", "family"), {"conscientiousness": 0.8}, (0.0, 0.8))
def _rebuild(ctx):
    ctx.c.skill = min(1.0, ctx.c.skill + 0.003)
    ctx.world.village.morale = min(1.0, ctx.world.village.morale + 0.005)


@act("practice_arts", ("Practised the old forms at dawn where nobody could see.", "Felt the {el} answer me, just a little."),
     ("magic", "knowledge", "power"), {"openness": 0.8, "conscientiousness": 0.6, "extraversion": -0.2}, (0.0, 1.0))
def _practice(ctx):
    from .systems import magic
    magic.practise(ctx.world, ctx.c, 1.0)


@act("invent", ("Tinkered all night. I think I've got something.",), ("knowledge", "wealth", "status"),
     {"openness": 0.9, "conscientiousness": 0.5}, (0.0, 0.8), needs=lambda x: x.c.education > 0.5)
def _invent(ctx):
    w, c = ctx.world, ctx.c
    if w.rng.random() < 0.04 * c.education:
        w.tech *= 1.03
        c.reputation = float(np.clip(c.reputation + 0.2, -1, 1))
        c.money += 300
        _emit(ctx, f"{c.name} invented something that made every workshop in {w.name} a little faster.", 0.6, [c.id],
              kind="discovery", tone="good", category="discovery")


@act("care_for_family", ("Spent the day with the children.", "Sent money to my mother."), ("family", "love"),
     {"agreeableness": 0.7, "conscientiousness": 0.3}, (0.0, 0.9))
def _care(ctx):
    w, c = ctx.world, ctx.c
    kin = [w.citizens[k] for k in c.children + c.parent_ids + ([c.spouse_id] if c.spouse_id else []) if k in w.citizens and w.citizens[k].alive]
    for k in kin[:4]:
        k.happiness = min(1.0, k.happiness + 0.02)
        c.rel(k.id).score = min(100, c.rel(k.id).score + 3)
        if c.money > 200 and k.money < 50:
            c.money -= 30
            k.money += 30
    stir(c, "love", 0.15)


@act("hunt", ("Went up into the woods with a bow.",), ("wealth", "family"), {"extraversion": -0.1, "openness": 0.3, "neuroticism": -0.4}, (0.0, 1.0))
def _hunt(ctx):
    from .systems import animals
    animals.hunt(ctx.world, ctx.c)


# --- the unreasonable (only when nothing sensible fits) -----------------------------------------
@act("holiday", ("Went off to the hills for a week. Couldn't face it.",), ("peace",), {"openness": 0.6, "conscientiousness": -0.6}, (0.0, 1.0))
def _holiday(ctx):
    ctx.c.money = max(0.0, ctx.c.money - 40)
    _calm(ctx, 0.4)


@act("sing", ("Sang in the square until someone threw a boot.",), ("status",), {"extraversion": 0.9, "openness": 0.5}, (0.0, 1.0))
def _sing(ctx):
    ctx.c.happiness = min(1.0, ctx.c.happiness + 0.02)


@act("take_up_hobby", ("Started carving little birds. It helps.",), ("peace", "knowledge"), {"openness": 0.6, "extraversion": -0.3}, (0.0, 1.0))
def _hobby(ctx):
    _calm(ctx, 0.85)


@act("wander", ("Walked for hours without knowing where.",), ("peace",), {"openness": 0.5, "neuroticism": 0.3}, (0.0, 1.0))
def _wander(ctx):
    _calm(ctx, 0.9)


FALLBACK = ["holiday", "sing", "take_up_hobby", "wander", "drink", "keep_secret", "pray"]


# ---------------------------------------------------------------- situations
# key: (feeling it stirs, how hard, second feeling or None, {response: relevance})
S = {}


def sit(key, emotion, strength, menu, second=None):
    S[key] = (emotion, strength, second, menu)


_WRONGED = {"shrug_off": 0.7, "walk_away": 0.8, "forgive": 0.5, "retort": 0.8, "brood": 0.6, "sulk": 0.5, "demand_apology": 0.6,
            "mock_publicly": 0.45, "spread_rumour": 0.5, "cut_ties": 0.5, "threaten": 0.4, "shove": 0.35, "brawl": 0.25, "plot_revenge": 0.3,
            "drink": 0.35, "seek_support": 0.45, "smash_property": 0.15, "sabotage": 0.15, "kill": 0.1, "arson": 0.1, "hire_thugs": 0.12,
            "reconcile": 0.3, "work_harder": 0.2, "pray": 0.15}
sit("insulted", "anger", 0.45, _WRONGED)
sit("humiliated", "anger", 0.6, {**_WRONGED, "shrug_off": 0.4, "brawl": 0.35, "kill": 0.12, "emigrate": 0.12, "weep": 0.3}, second="shame")
sit("slandered", "anger", 0.4, {**_WRONGED, "demand_apology": 0.7, "spread_rumour": 0.7})
sit("threatened", "fear", 0.5, {"walk_away": 0.6, "report_to_watch": 0.4, "seek_support": 0.6, "threaten": 0.5, "brawl": 0.4, "flee": 0.3,
                                "hire_thugs": 0.25, "kill": 0.15, "keep_secret": 0.4, "pray": 0.2, "enlist": 0.1, "poison": 0.1, "emigrate": 0.2}, second="anger")
sit("assaulted", "anger", 0.7, {"report_to_watch": 0.8, "vigilante": 0.5, "brawl": 0.5, "brood": 0.5, "plot_revenge": 0.5, "seek_support": 0.6,
                                "weep": 0.4, "flee": 0.3, "kill": 0.2, "hire_thugs": 0.3, "forgive": 0.15, "drink": 0.4, "arson": 0.12, "poison": 0.12,
                                "emigrate": 0.15, "enlist": 0.1}, second="fear")
sit("robbed", "anger", 0.55, {"report_to_watch": 0.9, "vigilante": 0.45, "work_harder": 0.4, "brood": 0.4, "steal": 0.3, "seek_support": 0.4,
                              "beg": 0.25, "plot_revenge": 0.35, "sell_belongings": 0.3, "drink": 0.3, "shrug_off": 0.3, "gamble": 0.15, "hoard": 0.15})
sit("cheated", "anger", 0.5, {"report_to_watch": 0.8, "demand_apology": 0.6, "spread_rumour": 0.6, "vigilante": 0.4, "swindle": 0.3, "cut_ties": 0.6,
                              "brood": 0.4, "shrug_off": 0.3, "work_harder": 0.3, "sabotage": 0.3, "threaten": 0.4, "arson": 0.1})
sit("betrayed", "anger", 0.65, {"cut_ties": 0.8, "brood": 0.6, "spread_rumour": 0.5, "threaten": 0.4, "brawl": 0.3, "weep": 0.5, "forgive": 0.25,
                                "plot_revenge": 0.5, "drink": 0.5, "kill": 0.12, "seek_support": 0.5, "leave_spouse": 0.3, "emigrate": 0.15}, second="grief")
sit("spouse_unfaithful", "anger", 0.8, {"leave_spouse": 0.8, "brawl": 0.4, "kill": 0.15, "weep": 0.6, "forgive": 0.3, "brood": 0.5, "drink": 0.5,
                                        "cut_ties": 0.4, "affair": 0.25, "poison": 0.12, "seek_support": 0.5, "threaten": 0.4, "emigrate": 0.2}, second="grief")
sit("abandoned", "grief", 0.7, {"weep": 0.7, "drink": 0.5, "brood": 0.5, "seek_support": 0.6, "court": 0.3, "work_harder": 0.4, "emigrate": 0.25,
                                "spread_rumour": 0.35, "threaten": 0.25, "care_for_family": 0.5, "kill": 0.1, "forgive": 0.3}, second="anger")
sit("rejected", "shame", 0.5, {"weep": 0.4, "shrug_off": 0.5, "court": 0.4, "drink": 0.5, "brood": 0.4, "work_harder": 0.4, "spread_rumour": 0.3,
                               "sulk": 0.5, "threaten": 0.15, "take_up_hobby": 0.3, "emigrate": 0.1}, second="anger")
sit("helped", "joy", 0.4, {"gift": 0.5, "reconcile": 0.4, "comfort_others": 0.4, "work_harder": 0.4, "celebrate": 0.3, "seek_support": 0.3,
                           "care_for_family": 0.4, "court": 0.15, "shrug_off": 0.2, "keep_secret": 0.2, "start_business": 0.15, "pray": 0.3}, second="love")
sit("married", "joy", 0.7, {"celebrate": 0.9, "care_for_family": 0.6, "work_harder": 0.5, "gift": 0.4, "boast": 0.4, "pray": 0.3, "start_business": 0.2,
                            "take_up_hobby": 0.2, "affair": 0.1}, second="love")
sit("child_born", "joy", 0.7, {"celebrate": 0.8, "care_for_family": 0.9, "work_harder": 0.6, "work_overtime": 0.5, "pray": 0.4, "boast": 0.3,
                               "start_business": 0.15, "hoard": 0.2, "drink": 0.15, "leave_spouse": 0.1}, second="love")
sit("loved_one_died", "grief", 0.75, {"mourn": 0.9, "weep": 0.8, "drink": 0.5, "seek_support": 0.6, "comfort_others": 0.5, "work_harder": 0.4,
                                      "pray": 0.5, "brood": 0.3, "emigrate": 0.15, "keep_secret": 0.2, "wander": 0.3, "practice_arts": 0.1})
sit("loved_one_murdered", "anger", 0.9, {"vigilante": 0.6, "kill": 0.35, "plot_revenge": 0.7, "report_to_watch": 0.7, "mourn": 0.7, "weep": 0.6,
                                         "brood": 0.5, "arson": 0.2, "hire_thugs": 0.3, "poison": 0.2, "emigrate": 0.2, "forgive": 0.1,
                                         "practice_arts": 0.15, "drink": 0.4}, second="grief")
sit("home_lost", "grief", 0.7, {"rebuild": 0.8, "seek_support": 0.6, "beg": 0.4, "emigrate": 0.5, "weep": 0.5, "work_overtime": 0.4,
                                "steal": 0.2, "brood": 0.3, "pray": 0.4, "loot": 0.15}, second="fear")
sit("rival_success", "envy", 0.5, {"work_harder": 0.7, "spread_rumour": 0.5, "sabotage": 0.35, "brood": 0.5, "shrug_off": 0.4, "start_business": 0.35,
                                   "swindle": 0.2, "study": 0.4, "drink": 0.3, "gamble": 0.3, "steal": 0.15, "mock_publicly": 0.3, "arson": 0.1})
sit("broke", "fear", 0.55, {"find_work": 0.8, "work_overtime": 0.6, "beg": 0.5, "sell_belongings": 0.6, "steal": 0.35, "gamble": 0.35,
                            "swindle": 0.25, "emigrate": 0.3, "burgle": 0.2, "drink": 0.3, "seek_support": 0.5, "smuggle": 0.25, "pray": 0.3}, second="shame")
sit("windfall", "joy", 0.5, {"celebrate": 0.7, "start_business": 0.5, "gift": 0.4, "gamble": 0.4, "boast": 0.5, "care_for_family": 0.5, "hoard": 0.3,
                             "keep_secret": 0.5, "work_harder": 0.3, "holiday": 0.2}, second="pride")
sit("fired", "fear", 0.6, {"find_work": 0.9, "brood": 0.4, "drink": 0.4, "start_business": 0.35, "petition_council": 0.3, "join_movement": 0.35,
                           "found_movement": 0.2, "smash_property": 0.2, "emigrate": 0.3, "steal": 0.2, "seek_support": 0.5, "sabotage": 0.2,
                           "study": 0.3, "arson": 0.1}, second="anger")
sit("hired", "joy", 0.45, {"work_harder": 0.8, "celebrate": 0.4, "boast": 0.3, "care_for_family": 0.4, "study": 0.3, "shrug_off": 0.3, "gift": 0.2}, second="hope")
sit("business_failed", "shame", 0.75, {"start_business": 0.4, "find_work": 0.6, "drink": 0.5, "brood": 0.5, "emigrate": 0.35, "weep": 0.4,
                                       "gamble": 0.3, "swindle": 0.25, "steal": 0.15, "petition_council": 0.3, "seek_support": 0.5, "kill": 0.05}, second="fear")
sit("business_founded", "pride", 0.6, {"work_harder": 0.8, "celebrate": 0.5, "boast": 0.5, "work_overtime": 0.5, "gift": 0.2, "study": 0.3,
                                       "swindle": 0.2, "hoard": 0.2})
sit("starving", "fear", 0.7, {"beg": 0.7, "steal": 0.6, "find_work": 0.6, "sell_belongings": 0.5, "hunt": 0.5, "emigrate": 0.45, "loot": 0.3,
                              "petition_council": 0.4, "join_movement": 0.4, "incite_riot": 0.25, "burgle": 0.3, "smuggle": 0.3, "pray": 0.3,
                              "kill": 0.05}, second="anger")
sit("jailed", "shame", 0.6, {"brood": 0.6, "plot_revenge": 0.4, "weep": 0.4, "study": 0.3, "pray": 0.4, "shrug_off": 0.3, "sulk": 0.5,
                             "practice_arts": 0.15}, second="anger")
sit("released", "hope", 0.5, {"find_work": 0.7, "steal": 0.35, "plot_revenge": 0.35, "emigrate": 0.3, "seek_support": 0.4, "drink": 0.4,
                              "care_for_family": 0.4, "burgle": 0.2, "study": 0.2}, second="shame")
sit("witnessed_crime", "fear", 0.35, {"report_to_watch": 0.8, "keep_secret": 0.6, "vigilante": 0.3, "shrug_off": 0.4, "extort": 0.2,
                                      "seek_support": 0.3, "enlist": 0.15})
sit("got_away_with_it", "pride", 0.4, {"steal": 0.5, "burgle": 0.4, "celebrate": 0.3, "keep_secret": 0.7, "gamble": 0.3, "drink": 0.3,
                                       "shrug_off": 0.3, "swindle": 0.3, "gift": 0.15})
sit("political_loss", "anger", 0.45, {"join_movement": 0.6, "found_movement": 0.35, "petition_council": 0.5, "incite_riot": 0.2, "emigrate": 0.25,
                                      "shrug_off": 0.4, "brood": 0.4, "run_for_council": 0.3, "spread_rumour": 0.3}, second="fear")
sit("political_win", "hope", 0.45, {"celebrate": 0.6, "run_for_council": 0.3, "work_harder": 0.4, "boast": 0.3, "shrug_off": 0.3,
                                    "petition_council": 0.3, "enlist": 0.15})
sit("disaster", "fear", 0.7, {"help_rescue": 0.8, "flee": 0.6, "rebuild": 0.6, "hoard": 0.4, "loot": 0.3, "pray": 0.5, "seek_support": 0.5,
                              "emigrate": 0.35, "comfort_others": 0.5, "petition_council": 0.3, "weep": 0.4, "steal": 0.15}, second="grief")
sit("plague", "fear", 0.6, {"flee": 0.5, "hoard": 0.4, "pray": 0.6, "comfort_others": 0.5, "help_rescue": 0.4, "emigrate": 0.4, "keep_secret": 0.3,
                            "drink": 0.3, "seek_support": 0.3, "loot": 0.15})
sit("water_cut", "anger", 0.5, {"petition_council": 0.7, "sabotage_dam": 0.4, "raid_upstream": 0.35, "smuggle": 0.4, "hoard": 0.4,
                                "emigrate": 0.35, "enlist": 0.4, "join_movement": 0.3, "pray": 0.3, "incite_riot": 0.2, "brood": 0.3,
                                "take_up_arms": 0.3, "practice_arts": 0.15}, second="fear")
sit("war_declared", "fear", 0.7, {"take_up_arms": 0.8, "enlist": 0.7, "flee": 0.5, "hoard": 0.5, "pray": 0.5, "desert": 0.2,
                                  "betray_village": 0.12, "emigrate": 0.3, "comfort_others": 0.4, "practice_arts": 0.2, "smuggle": 0.2}, second="anger")
sit("battle_lost", "grief", 0.7, {"take_up_arms": 0.5, "desert": 0.35, "flee": 0.5, "mourn": 0.6, "weep": 0.4, "betray_village": 0.15,
                                  "plot_revenge": 0.4, "pray": 0.5, "practice_arts": 0.2, "drink": 0.4}, second="fear")
sit("occupied", "anger", 0.6, {"resist": 0.7, "collaborate": 0.6, "flee": 0.5, "emigrate": 0.45, "keep_secret": 0.4, "practice_arts": 0.35,
                               "brood": 0.5, "pray": 0.4, "betray_village": 0.2, "incite_riot": 0.25, "kill": 0.1, "work_harder": 0.3}, second="shame")
sit("liberated", "joy", 0.8, {"celebrate": 0.9, "rebuild": 0.7, "vigilante": 0.3, "mourn": 0.4, "enlist": 0.4, "pray": 0.5, "boast": 0.3}, second="pride")
sit("foreign_insult", "anger", 0.45, {"retort": 0.6, "brawl": 0.4, "enlist": 0.4, "spread_rumour": 0.4, "shrug_off": 0.4, "petition_council": 0.3,
                                      "raid_upstream": 0.2, "walk_away": 0.5, "smuggle": 0.15})
sit("discovery", "pride", 0.6, {"boast": 0.6, "start_business": 0.5, "keep_secret": 0.4, "celebrate": 0.5, "work_harder": 0.5, "study": 0.4,
                                "invent": 0.4, "gift": 0.2}, second="joy")
sit("awakening", "fear", 0.6, {"keep_secret": 0.9, "practice_arts": 0.9, "pray": 0.6, "study": 0.4, "weep": 0.2, "boast": 0.15}, second="pride")
sit("good_news", "joy", 0.35, {"celebrate": 0.5, "work_harder": 0.5, "gift": 0.3, "care_for_family": 0.4, "shrug_off": 0.4, "boast": 0.3,
                               "court": 0.2, "study": 0.2})
sit("bad_news", "fear", 0.35, {"work_harder": 0.4, "brood": 0.4, "seek_support": 0.4, "shrug_off": 0.5, "drink": 0.3, "pray": 0.3,
                               "petition_council": 0.2, "hoard": 0.2, "emigrate": 0.1})
sit("attacked_by_animal", "fear", 0.7, {"hunt": 0.7, "flee": 0.5, "enlist": 0.2, "seek_support": 0.4, "weep": 0.3, "pray": 0.4,
                                        "petition_council": 0.4, "emigrate": 0.15}, second="anger")

# initiatives: every goal has its own menu of things to *do* about it, every day
sit("ambition_wealth", "hope", 0.1, {"work_overtime": 0.7, "ask_raise": 0.6, "start_business": 0.6, "find_work": 0.7, "swindle": 0.35,
                                     "steal": 0.3, "burgle": 0.2, "gamble": 0.35, "smuggle": 0.35, "hoard": 0.3, "embezzle": 0.4,
                                     "extort": 0.2, "study": 0.3, "invent": 0.3, "emigrate": 0.1, "court": 0.1, "hunt": 0.2})
sit("ambition_love", "love", 0.1, {"court": 0.9, "propose": 0.8, "celebrate": 0.4, "gift": 0.5, "sing": 0.3, "affair": 0.2, "emigrate": 0.15})
sit("ambition_family", "love", 0.1, {"care_for_family": 0.9, "work_overtime": 0.6, "court": 0.5, "propose": 0.5, "find_work": 0.5,
                                     "hoard": 0.3, "steal": 0.15, "emigrate": 0.2, "hunt": 0.3})
sit("ambition_knowledge", "hope", 0.1, {"study": 0.9, "invent": 0.6, "practice_arts": 0.3, "work_harder": 0.4, "emigrate": 0.15, "take_up_hobby": 0.3})
sit("ambition_status", "pride", 0.1, {"run_for_council": 0.6, "celebrate": 0.4, "gift": 0.4, "boast": 0.5, "work_harder": 0.5, "mock_publicly": 0.25,
                                      "spread_rumour": 0.25, "petition_council": 0.4, "enlist": 0.3, "start_business": 0.3, "comfort_others": 0.3})
sit("ambition_power", "pride", 0.1, {"run_for_council": 0.8, "found_movement": 0.5, "join_movement": 0.4, "extort": 0.3, "threaten": 0.2,
                                     "embezzle": 0.35, "spread_rumour": 0.35, "enlist": 0.3, "practice_arts": 0.25, "hire_thugs": 0.15, "incite_riot": 0.12})
sit("ambition_change", "hope", 0.1, {"found_movement": 0.6, "join_movement": 0.6, "petition_council": 0.7, "run_for_council": 0.4, "incite_riot": 0.2,
                                     "emigrate": 0.12, "invent": 0.3, "study": 0.3})
sit("ambition_revenge", "anger", 0.15, {"kill": 0.2, "brawl": 0.45, "poison": 0.15, "arson": 0.15, "sabotage": 0.5, "spread_rumour": 0.6,
                                        "threaten": 0.5, "hire_thugs": 0.3, "brood": 0.5, "forgive": 0.3, "reconcile": 0.25, "mock_publicly": 0.5,
                                        "cut_ties": 0.4, "report_to_watch": 0.2, "smash_property": 0.3})
sit("ambition_magic", "hope", 0.1, {"practice_arts": 0.95, "study": 0.6, "pray": 0.6, "keep_secret": 0.4, "wander": 0.2, "hunt": 0.15})
sit("ambition_duty", "pride", 0.1, {"enlist": 0.7, "report_to_watch": 0.2, "work_harder": 0.6, "comfort_others": 0.5, "petition_council": 0.4,
                                    "run_for_council": 0.4, "take_up_arms": 0.4, "rebuild": 0.4})
sit("ambition_peace", "joy", 0.05, {"take_up_hobby": 0.7, "care_for_family": 0.6, "seek_support": 0.5, "work_harder": 0.4, "pray": 0.5,
                                    "shrug_off": 0.4, "sing": 0.3, "wander": 0.4, "reconcile": 0.4})

CRIME_SITUATION = {"murder": "loved_one_murdered", "assault": "assaulted", "theft": "robbed", "burglary": "robbed", "fraud": "cheated",
                   "extortion": "threatened", "vandalism": "cheated", "arson": "home_lost", "poisoning": "assaulted", "looting": "robbed"}


def classify(world, c, ev) -> str:
    """Which real-life situation this event is, for this person."""
    k = ev.kind
    first = ev.actors[0] if ev.actors else None
    if k.startswith("crime_"):
        crime = k[6:]
        if getattr(ev, "culprit", None) == c.id or (len(ev.actors) > 1 and ev.actors[1] == c.id and first != c.id):
            return "got_away_with_it"
        if first == c.id:
            return CRIME_SITUATION.get(crime, "robbed")
        return "witnessed_crime"
    direct = {"insulted": "insulted", "humiliated": "humiliated", "slandered": "slandered", "threatened": "threatened",
              "rejected": "rejected", "helped": "helped", "married": "married", "child_born": "child_born", "fired": "fired",
              "hired": "hired", "business_failed": "business_failed", "business_founded": "business_founded", "jailed": "jailed",
              "released": "released", "spouse_unfaithful": "spouse_unfaithful", "abandoned": "abandoned", "rival_success": "rival_success",
              "broke": "broke", "windfall": "windfall", "death": "loved_one_died", "murdered": "loved_one_murdered",
              "water_cut": "water_cut", "war_declared": "war_declared", "battle_lost": "battle_lost", "occupied": "occupied",
              "liberated": "liberated", "foreign_insult": "foreign_insult", "discovery": "discovery", "awakening": "awakening",
              "disaster": "disaster", "plague": "plague", "starving": "starving", "animal_attack": "attacked_by_animal",
              "lost_office": "political_loss", "won_office": "political_win", "exiled": "humiliated", "executed": "loved_one_died",
              "dam_sabotaged": "foreign_insult", "betrayed": "betrayed"}
    if k in direct:
        return direct[k]
    if k.startswith("ambition_"):
        return k
    # older emission sites: read the text
    t = ev.text.lower()
    cat = ev.category
    if "died of murder" in t or "was murdered" in t:
        return "loved_one_murdered"
    if " died " in t or "died of" in t:
        return "loved_one_died"
    if cat == "social" and ev.tone == "bad":
        return "humiliated" if any(w in t for w in ("in front of", "the whole", "square", "tavern")) else "insulted"
    if cat == "social" and ev.tone == "good":
        return "helped"
    if "laid off" in t or "fired" in t or "automated" in t or "replaced" in t:
        return "fired"
    if "was hired" in t or "found work" in t:
        return "hired"
    if "bankrupt" in t or "failed" in t:
        return "business_failed" if first == c.id else "fired"
    if "founded" in t and cat == "economy":
        return "business_founded"
    if "married" in t:
        return "married"
    if "was born" in t:
        return "child_born"
    if "discovered" in t or "devised" in t:
        return "discovery"
    if cat == "politics":
        return "political_win" if ev.tone == "good" or "took power" in t else ("political_loss" if ev.tone == "bad" else "bad_news")
    if cat == "disaster":
        return "plague" if ("sick" in t or "fell ill" in t or "fever" in t or "cough" in t) else "disaster"
    if cat == "war":
        return "war_declared"
    if ev.tone == "good":
        return "good_news"
    if ev.tone == "bad" or any(w in t for w in ("lost", "raid", "flood", "drought", "famine", "riot", "starv", "collapsed")):
        return "bad_news"
    return "good_news" if any(w in t for w in ("opened", "won", "elected", "promoted", "recovered", "gave")) else "bad_news"


def _other_of(world, c, ev):
    cul = getattr(ev, "culprit", None)
    if cul is not None and cul != c.id and cul in world.citizens:
        return world.citizens[cul]
    for a in ev.actors:
        if a != c.id and a in world.citizens:
            return world.citizens[a]
    return None


# ---------------------------------------------------------------- the decision
def _fit(act_: Act, ctx: Ctx, rel: float, d: dict) -> float:
    c, p, w = ctx.c, ctx.c.personality, ctx.world
    trait = math.exp(2.2 * sum(k * (p[t] - 0.5) for t, k in act_.traits.items()))
    lo, hi = act_.band
    lvl = ctx.level
    dist = 0.0 if lo <= lvl <= hi else (lo - lvl if lvl < lo else lvl - hi)
    band = math.exp(-6.0 * dist)
    tag = GOAL_TAGS.get(c.goal, "")
    goal = (1.8 + 1.4 * p["conscientiousness"]) if tag in act_.tags else 1.0
    if tag == "revenge" and getattr(c, "goal_target", None) is not None and ctx.other is not None and ctx.other.id == c.goal_target:
        goal *= 2.0
    crime = 1.0
    if act_.crime:
        # conscience loads the die against it; it never takes it off the table
        grave = act_.crime in ("murder", "poisoning", "arson")
        crime = (0.004 + 1.6 * (1 - d["conscience"]) ** 3) if grave else (0.02 + 2.0 * (1 - d["conscience"]) ** 2.5)
        if grave and ctx.other is not None and c.rel(ctx.other.id).score > -50:
            crime *= 0.25                    # it takes real hatred, not a bad day
        if c.convictions and act_.crime in ("theft", "burglary", "fraud"):
            crime *= 1.3                     # habits
        if not w.free(c):
            crime *= 0.3
    history = 1.0
    if ctx.other is not None:
        score = c.rel(ctx.other.id).score
        if act_.violent:
            history = (1 + max(0.0, -score) / 40) * (0.25 if score > 50 else 1.0)
        elif act_.key in ("forgive", "reconcile", "apologise", "gift"):
            history = 1 + max(0.0, score) / 60
    hunger = 1.6 if (c.hunger > 0.6 and "wealth" in act_.tags) else 1.0
    roots = 1.0
    if act_.key in ("emigrate", "flee"):
        # people with a job, a family and a house mostly stay, even when things are bad
        roots = (0.35 if c.employer_id is not None else 1.0) * (0.5 if c.spouse_id else 1.0) * (0.6 if c.children else 1.0)
        if w.day - getattr(c, "moved_day", -9999) < 730:
            roots *= 0.1
    if act_.key == "run_for_council" and w.day - getattr(c, "ran_day", -9999) < 365:
        roots = 0.05
    return max(1e-4, rel ** 0.7 * trait * band * goal * crime * history * hunger * roots)


def menu_for(world, c, sit_key: str, ctx: Ctx) -> List[Tuple[Act, float]]:
    """Six things this person might do. Relevant ones first; the unreasonable only if nothing else fits."""
    _, _, _, menu = S[sit_key]
    rng = world.rng
    ok = []
    for k, rel in menu.items():
        a = ACTS.get(k)
        if a is None or rel < 0.1:
            continue
        try:
            if a.needs and not a.needs(ctx):
                continue
        except Exception:
            continue
        ok.append((a, rel))
    picked = []
    pool = list(ok)
    while pool and len(picked) < 6:
        i = rng.choices(range(len(pool)), weights=[r for _, r in pool])[0]
        picked.append(pool.pop(i))
    if len(picked) < 6:
        for k in FALLBACK:
            a = ACTS[k]
            if all(a.key != x.key for x, _ in picked) and (not a.needs or a.needs(ctx)):
                picked.append((a, 0.05))
            if len(picked) >= 6:
                break
    return picked


def decide(world, c, ev, sit_key: Optional[str] = None):
    """Feel it, draw six options, load the die, roll. Returns a Reaction."""
    from .brains import Reaction
    rng = world.rng
    sit_key = sit_key or classify(world, c, ev)
    emotion, strength, second, _ = S[sit_key]
    other = _other_of(world, c, ev)
    amount = strength * (0.55 + 0.9 * ev.importance)
    level = stir(c, emotion, amount, rng) if strength > 0.12 else c.feel(emotion)
    if second:
        stir(c, second, amount * 0.6, rng)
    ctx = Ctx(world, c, ev, sit_key, emotion, level, other)
    d = disposition(c)
    options = menu_for(world, c, sit_key, ctx)
    if not options:
        return None
    weights = [_fit(a, ctx, rel, d) * rng.uniform(0.8, 1.25) for a, rel in options]
    face = rng.choices(range(len(options)), weights=weights)[0]
    chosen = options[face][0]
    total = sum(weights)
    r = Reaction(emotion=_voice_emotion(emotion), intensity=float(np.clip(level, 0.05, 1)), action=chosen.key, source="rules")
    r.situation = sit_key
    r.options = [(a.key, round(wt / total, 3)) for (a, _), wt in zip(options, weights)]
    r.face = face + 1
    r.target = other.id if other is not None else None
    r.level = level
    if other is not None and emotion == "anger":
        r.relationship_changes[other.id] = -(4 + 22 * level * d["vengeful"])
    elif other is not None and emotion in ("joy", "love", "hope"):
        r.relationship_changes[other.id] = 4 + 10 * d["warmth"]
    if ev.tone == "bad" or emotion in ("anger", "fear", "grief", "shame"):
        r.grievance_delta = 0.02 + 0.1 * ev.importance * level
    elif emotion in ("joy", "pride", "hope"):
        r.grievance_delta = -0.03
    return r


def _voice_emotion(e):
    return {"envy": "anger", "love": "joy"}.get(e, e)


def perform(world, c, ev, reaction) -> str:
    """Carry out the chosen act. Returns a first-person line about it."""
    a = ACTS.get(reaction.action)
    if a is None or not c.alive:
        return ""
    other = world.citizens.get(getattr(reaction, "target", None) or -1)
    if other is None:
        other = _other_of(world, c, ev)
    ctx = Ctx(world, c, ev, getattr(reaction, "situation", ""), reaction.emotion, getattr(reaction, "level", reaction.intensity), other)
    try:
        if a.needs is None or a.needs(ctx) or a.key in ("kill", "brawl", "steal"):
            a.do(ctx)
    except Exception as e:                   # an act must never take the world down
        world.emit("error", f"{c.name} tried to {a.key} and something went wrong: {type(e).__name__}", 0.0, [], village=-1)
        return ""
    reaction.forget = ctx.forget
    line = world.rng.choice(a.lines)
    return line.format(o=_first(ctx.other) if ctx.other else "them", el=world.villages[c.village].element,
                       dest=ctx.note or "somewhere else")


# ---------------------------------------------------------------- every day
def _pseudo(world, c, kind, text, imp=0.3, other=None):
    return WorldEvent(world.day, "life", text, imp, [c.id] + ([other] if other else []), kind=kind, village=c.village)


def daily(world):
    """Feelings fade; ambitions push; hardship and occupation press on people; the jailed wait."""
    from .systems import crime
    rng = world.rng
    v = world.village
    crime.release_due(world)
    alive = world.alive()
    at_war = any(w_.get("active") and v.idx in (w_["a"], w_["b"]) for w_ in world.wars)
    for c in alive:
        if c.emotions:
            fade(c)
            # feelings colour the day
            pull = 0.2 * c.feel("joy") + 0.1 * c.feel("pride") + 0.1 * c.feel("hope") + 0.1 * c.feel("love") \
                - 0.15 * c.feel("anger") - 0.3 * c.feel("grief") - 0.2 * c.feel("fear") - 0.15 * c.feel("shame") - 0.1 * c.feel("envy")
            c.happiness = float(np.clip(c.happiness + 0.02 * pull, 0, 1))
        age = c.age_on(world.day)
        if age < 16 or not world.free(c):
            continue
        d = disposition(c)
        # ambition: the goal always pulls
        if world.day - c.last_initiative >= 3:
            frustration = 1 - c.goal_progress
            p = 0.012 + 0.03 * d["drive"] + 0.02 * frustration + 0.03 * (c.feel("anger") + c.feel("envy"))
            if GOAL_TAGS.get(c.goal) == "revenge":
                p += 0.03
            if rng.random() < p:
                c.last_initiative = world.day
                tag = GOAL_TAGS.get(c.goal, "wealth")
                ev = _pseudo(world, c, f"ambition_{tag}", f"{c.name} worked toward {c.goal}", 0.2, getattr(c, "goal_target", None))
                _run(world, c, ev, f"ambition_{tag}", quiet=True)
                continue
        # pressures that don't come as a single event
        if c.hunger > 0.7 and rng.random() < 0.08:
            _run(world, c, _pseudo(world, c, "starving", f"{c.name} has not eaten properly in days", 0.45), "starving")
        elif c.employer_id is None and age < 65 and c.money < 40 and rng.random() < 0.04:
            _run(world, c, _pseudo(world, c, "broke", f"{c.name} is down to their last coins", 0.4), "broke")
        elif v.occupier is not None and rng.random() < 0.02:
            _run(world, c, _pseudo(world, c, "occupied", f"{world.villages[v.occupier].name} soldiers patrol {v.name}", 0.5), "occupied")
        elif v.water_met < 0.55 and rng.random() < 0.015:
            _run(world, c, _pseudo(world, c, "water_cut", f"The river runs low through {v.name}", 0.45), "water_cut")
        elif at_war and rng.random() < 0.01:
            _run(world, c, _pseudo(world, c, "war_declared", f"{v.name} is at war", 0.5), "war_declared")
        # grudges fester
        if c.feel("anger") > 0.75 and rng.random() < 0.05 * d["vengeful"]:
            foe = min((r for r in c.relationships.values() if r.other_id in world.citizens and world.citizens[r.other_id].alive
                       and world.citizens[r.other_id].village == c.village), key=lambda r: r.score, default=None)
            if foe is not None and foe.score < -40:
                ev = _pseudo(world, c, "ambition_revenge", f"{c.name} cannot let it go", 0.5, foe.other_id)
                ev.culprit = foe.other_id
                _run(world, c, ev, "ambition_revenge")


def _run(world, c, ev, sit_key, quiet=False):
    """Decide and act on a situation that isn't a broadcast event."""
    if getattr(world.brains.get(c.id, world.brain), "name", "") == "silent":
        return                                     # the control arm of an experiment: nobody reacts
    brain = world.brains.get(c.id)
    r = None
    if brain is not None and getattr(brain, "name", "") == "llm" and not quiet and ev.importance >= getattr(brain, "threshold", 0.6):
        r = brain.react(world, c, ev)
    if r is None:
        r = decide(world, c, ev, sit_key)
    if r is None:
        return
    if quiet:
        # ambitions are routine: act, but only keep the memory if the act mattered
        line = perform(world, c, ev, r)
        a = ACTS.get(r.action)
        if line and a and (a.crime or a.violent or a.key in ("start_business", "propose", "run_for_council", "found_movement",
                                                              "emigrate", "invent", "enlist", "court")):
            c.remember(world.day, line, r.emotion, 0.45, tag="ambition")
            world.think(c, line, "rules", r.emotion, options=r.options, face=r.face)
        return
    world._apply_reaction(c, ev, r)
