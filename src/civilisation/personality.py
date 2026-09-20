"""Personality made visible: descriptors, a voice per temperament, and thoughts.

Everything here is text generation from state — cheap, deterministic, and the
reason two citizens who live through the same event don't sound the same.
"""
from __future__ import annotations
import random

TRAIT_WORDS = {
    "openness": (["curious", "restless", "dreamy", "inventive"], ["set in their ways", "practical", "traditional"]),
    "conscientiousness": (["diligent", "meticulous", "dependable", "driven"], ["impulsive", "careless", "easy-going"]),
    "extraversion": (["gregarious", "loud", "charming", "a born talker"], ["quiet", "solitary", "watchful"]),
    "agreeableness": (["kind", "loyal", "soft-hearted", "forgiving"], ["abrasive", "hot-tempered", "sharp-tongued", "unforgiving"]),
    "neuroticism": (["anxious", "brooding", "thin-skinned", "moody"], ["unflappable", "steady", "cheerful"]),
}


def _rng(c, salt=0):
    return random.Random(c.id * 7919 + salt)


def describe(c, n=3) -> list[str]:
    """Up to n adjectives for the traits furthest from the middle."""
    r = _rng(c)
    ranked = sorted(c.personality.items(), key=lambda kv: -abs(kv[1] - 0.5))
    out = []
    for k, v in ranked[:n]:
        if abs(v - 0.5) < 0.12:
            continue
        hi, lo = TRAIT_WORDS[k]
        out.append(r.choice(hi if v > 0.5 else lo))
    return out or ["unremarkable"]


def archetype(c) -> str:
    p = c.personality
    if p["agreeableness"] < 0.35 and p["neuroticism"] > 0.55:
        return "firebrand"
    if p["agreeableness"] < 0.35:
        return "cynic"
    if p["neuroticism"] > 0.65:
        return "worrier"
    if p["extraversion"] > 0.65 and p["openness"] > 0.55:
        return "dreamer"
    if p["conscientiousness"] > 0.65:
        return "striver"
    if p["agreeableness"] > 0.7:
        return "saint"
    if p["extraversion"] < 0.35:
        return "loner"
    return "plain"


VOICE = {
    "anger": {
        "firebrand": ["{ev} People are going to hear about this.", "{ev} I don't get mad. I get even.", "{ev} Someone should have hit them."],
        "cynic": ["{ev} Typical. This town is full of them.", "{ev} I expected nothing and was still let down.", "{ev} Noted. Filed. Never forgotten."],
        "worrier": ["{ev} Why does it always come back to me?", "{ev} I keep replaying it. I can't sleep.", "{ev} What did I do to deserve this?"],
        "dreamer": ["{ev} Small people, small minds. I'll be somewhere better one day.", "{ev} It stung, but it gave me an idea."],
        "striver": ["{ev} Fine. I'll work twice as hard and they can watch.", "{ev} I don't have time for this nonsense."],
        "saint": ["{ev} I'm sure they didn't mean it. I hope they're all right.", "{ev} I'll forgive it. Not today, but I will."],
        "loner": ["{ev} This is why I keep to myself.", "{ev} Said nothing. Walked home the long way."],
        "plain": ["{ev} I won't forget this.", "{ev} That was uncalled for."],
    },
    "grief": {
        "firebrand": ["{ev} Grief is just anger with nowhere to go.", "{ev} Somebody is to blame for this."],
        "cynic": ["{ev} That's how it goes. Everyone leaves eventually.", "{ev} Life takes and takes."],
        "worrier": ["{ev} I can't stop thinking about who is next.", "{ev} The house is so quiet now."],
        "dreamer": ["{ev} I'll do something worthy of them.", "{ev} They'd have wanted me to keep going."],
        "striver": ["{ev} Work is the only thing that helps.", "{ev} I went back to work the same day. What else is there?"],
        "saint": ["{ev} I sat with the family until dark.", "{ev} I lit a candle and said what I never said aloud."],
        "loner": ["{ev} I didn't go to the burial. I said goodbye my own way.", "{ev} Nobody asked how I was. Fine."],
        "plain": ["{ev} It still hurts.", "{ev} The town feels smaller."],
    },
    "fear": {
        "firebrand": ["{ev} Fear makes people stupid. Not me. I'm making a list.", "{ev} If the council won't act, we will."],
        "cynic": ["{ev} Nobody in charge has a clue. As usual.", "{ev} I've buried coin under the floor. Trust no one."],
        "worrier": ["{ev} I checked the locks three times. Then a fourth.", "{ev} I felt the ground shift under me."],
        "dreamer": ["{ev} Maybe this is the push I needed to leave.", "{ev} Strange times make room for new things."],
        "striver": ["{ev} Plan, prepare, endure. That's all any of us can do.", "{ev} I counted the stores and made a budget."],
        "saint": ["{ev} I took soup to the neighbours. It's what you do.", "{ev} We'll get through it together or not at all."],
        "loner": ["{ev} I'll be fine. I have never needed anyone.", "{ev} Stayed in. Watched the street from the window."],
        "plain": ["{ev} Hard times.", "{ev} I hope it passes quickly."],
    },
    "joy": {
        "firebrand": ["{ev} About time something went right.", "{ev} Let them all see it."],
        "cynic": ["{ev} Enjoy it while it lasts, I suppose.", "{ev} Not bad. For this town."],
        "worrier": ["{ev} I keep waiting for the catch.", "{ev} I was so happy I nearly cried. Then I worried about it."],
        "dreamer": ["{ev} One of the good days. There will be more.", "{ev} I could feel the whole world opening up."],
        "striver": ["{ev} Earned, not given.", "{ev} Good. Now, the next thing."],
        "saint": ["{ev} I'm so happy for everyone.", "{ev} Days like this are why we're here."],
        "loner": ["{ev} I smiled. Nobody saw. That's how I like it.", "{ev} Quietly pleased."],
        "plain": ["{ev} A good day.", "{ev} Things are looking up."],
    },
    "pride": {
        "firebrand": ["{ev} I told them. I told all of them.", "{ev} Remember who did this when it matters."],
        "cynic": ["{ev} Not that anyone will thank me.", "{ev} Fine work. Wasted on this lot."],
        "worrier": ["{ev} I hope I can live up to it.", "{ev} They'll expect it again now."],
        "dreamer": ["{ev} This is only the beginning.", "{ev} I always knew I was meant for more."],
        "striver": ["{ev} Years of work. Worth every hour.", "{ev} On to the next goal."],
        "saint": ["{ev} I couldn't have done it without everyone.", "{ev} If it helps someone, that's enough."],
        "loner": ["{ev} Did it alone. Prefer it that way.", "{ev} Quiet satisfaction."],
        "plain": ["{ev} I earned this.", "{ev} Proud of it."],
    },
    "hope": {
        "firebrand": ["{ev} Now we push.", "{ev} Change doesn't ask permission."],
        "cynic": ["{ev} We'll see.", "{ev} I'll believe it when I see it."],
        "worrier": ["{ev} Please let this be real.", "{ev} Hope is a dangerous thing to get used to."],
        "dreamer": ["{ev} Maybe things are changing.", "{ev} I can see the shape of a better year."],
        "striver": ["{ev} An opening. I'll take it.", "{ev} Good. More to do."],
        "saint": ["{ev} Maybe things will be easier for the children.", "{ev} There's good in people if you wait."],
        "loner": ["{ev} Perhaps.", "{ev} Cautious. Always cautious."],
        "plain": ["{ev} Maybe things are changing.", "{ev} Let's hope."],
    },
    "shame": {"plain": ["{ev} I'd rather nobody knew.", "{ev} I can't look them in the eye."]},
    "neutral": {"plain": ["{ev}", "{ev} Life goes on."]},
}


def voice(c, emotion: str, event_text: str, salt: int = 0) -> str:
    table = VOICE.get(emotion, VOICE["neutral"])
    options = table.get(archetype(c)) or table["plain"]
    return _rng(c, salt).choice(options).format(ev=event_text).strip()


def thought(world, c) -> str:
    """What is on their mind right now — from state, in their voice."""
    r = random.Random(c.id * 31 + world.day // 7)
    a = archetype(c)
    lines = []
    if c.hunger > 0.6:
        lines.append({"firebrand": "Bread at £{p:.0f}. Somebody is getting rich off my empty stomach.", "worrier": "I lie awake doing sums about bread.",
                      "saint": "I gave my share to the little ones again.", "cynic": "Hungry. Again. And the council feasts."}.get(a, "I'm hungry, and bread is £{p:.0f}."))
    if c.employer_id is None and c.age_on(world.day) < 65 and c.job != "child":
        lines.append({"striver": "{d} days without work. I knock on every door.", "cynic": "No work. No prospects. No surprise.",
                      "firebrand": "They cut me loose and expect me to smile about it.", "dreamer": "Out of work — maybe this is when I finally start my own thing."}.get(a, "{d} days without work now."))
    if world.pandemic:
        lines.append({"worrier": "I hear coughing everywhere. Everywhere.", "saint": "I've been nursing the sick. Someone has to.", "cynic": "The sickness takes the good ones first, naturally."}.get(a, f"Everyone is afraid of {world.pandemic['name']}."))
    if c.spouse_id and world.citizens[c.spouse_id].alive:
        sp = world.citizens[c.spouse_id]
        sc = c.rel(sp.id).score
        if sc > 85:
            lines.append({"dreamer": f"{sp.name.split()[0]} laughed at breakfast and the whole day was fine.", "loner": f"{sp.name.split()[0]} understands the silences."}.get(a, f"{sp.name.split()[0]} and I are happy, mostly."))
        elif sc < 40:
            lines.append({"firebrand": f"{sp.name.split()[0]} and I fought again. Loudly.", "worrier": f"I think {sp.name.split()[0]} is tired of me."}.get(a, f"Things with {sp.name.split()[0]} are cold lately."))
    enemies = [r_ for r_ in c.relationships.values() if r_.score <= -40 and world.citizens[r_.other_id].alive]
    if enemies:
        e = world.citizens[max(enemies, key=lambda r_: r_.score).other_id]
        lines.append({"firebrand": f"If {e.name.split()[0]} so much as looks at me…", "saint": f"I should make peace with {e.name.split()[0]}. Tomorrow.",
                      "cynic": f"Saw {e.name.split()[0]} at the market. Pretended not to."}.get(a, f"I avoid {e.name.split()[0]} when I can."))
    if c.movement_id and world.movements[c.movement_id].alive:
        m = world.movements[c.movement_id]
        lines.append({"firebrand": f"The {m.name} meets tonight. Bring everyone.", "worrier": f"I joined the {m.name}. I hope that was wise.",
                      "dreamer": f"The {m.name} could change everything here."}.get(a, f"The {m.name} is the only thing giving me hope."))
    if c.money > 5000:
        lines.append({"cynic": "Money doesn't buy friends here. It buys quiet.", "saint": "I have more than I need. I should do something with it.",
                      "striver": "£{m:,.0f} saved. The plan is on track."}.get(a, "The savings are healthy. That helps me sleep."))
    if c.goal_progress > 0.7:
        lines.append({"striver": "Nearly there: {g}.", "dreamer": "So close to it now: {g}."}.get(a, "I can almost reach my goal: {g}."))
    if not lines:
        lines = {"dreamer": ["I watched the river for an hour. Thinking of leaving. Thinking of staying.", "There's a better version of this town somewhere in my head."],
                 "striver": ["Up before dawn. Work to do.", "Counted the week's takings twice. Good."],
                 "worrier": ["Nothing is wrong. That's what worries me.", "I keep waiting for bad news."],
                 "cynic": ["Another day in this town.", "Everyone is exactly as I expected them to be."],
                 "firebrand": ["Somebody said something at the tavern. I'm still deciding whether to be offended.", "Quiet week. Suspicious."],
                 "saint": ["Took the neighbour's washing in when the rain came.", "Everyone seems well. That's all I ask."],
                 "loner": ["Walked the hills alone. Best day in weeks.", "Nobody called. Good."],
                 "plain": ["An ordinary day.", "Work, supper, bed."]}[a]
    return r.choice(lines).format(p=world.food_price, d=c.unemployed_days, m=c.money, g=c.goal)


INSULT_TOPICS = [
    ("money", lambda a, b: b.money < 300, "{a} mocked {b} for being penniless"),
    ("job", lambda a, b: b.employer_id is None, "{a} called {b} a layabout"),
    ("business", lambda a, b: any(m.emotion == "shame" for m in b.memories[-5:]), "{a} laughed about {b}'s failed business"),
    ("spouse", lambda a, b: b.spouse_id is not None, "{a} made a crude joke about {b}'s marriage"),
    ("politics", lambda a, b: a.movement_id is not None and a.movement_id != b.movement_id, "{a} accused {b} of siding with the council against ordinary people"),
    ("drink", lambda a, b: True, "{a}, in their cups, told {b} exactly what they thought of them"),
    ("family", lambda a, b: bool(b.parent_ids), "{a} sneered at {b}'s family name"),
]


def insult_text(world, a, b, public: bool) -> str:
    r = random.Random(world.day * 131 + a.id)
    fits = [t for t in INSULT_TOPICS if t[1](a, b) and t[0] != "drink"]
    _, _, tmpl = r.choice(fits) if fits and r.random() < 0.8 else INSULT_TOPICS[5]
    text = tmpl.format(a=a.name, b=b.name)
    where = " at the tavern" if public else ", in private"
    flavour = {"firebrand": " — and meant every word", "cynic": ", drily", "worrier": ", then immediately regretted it",
               "saint": ", which shocked everyone who knew them", "dreamer": ", rather theatrically"}.get(archetype(a), "")
    return f"{text}{where}{flavour}."
