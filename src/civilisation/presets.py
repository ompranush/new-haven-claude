"""A catalogue of historical shocks, expressed as decree plans (see commands.apply_plan).

Each preset is a function world -> plan so it can name real people and react to the
state of the town. No model needed. Grouped loosely by the kind of history they echo.
"""
from __future__ import annotations
import random

PRESETS = {}
DESCRIPTIONS = {}


def preset(name, description):
    def deco(fn):
        PRESETS[name] = fn
        DESCRIPTIONS[name] = description
        return fn
    return deco


def _rng(world):
    return random.Random(world.day * 7 + world.seed)


def _pick(world, key):
    from .commands import select
    cs = select(world, key, _rng(world))
    return cs[0] if cs else None


# ------------------------------------------------------------------ society & culture
@preset("festival", "A harvest festival: a week of feasting, dancing and weddings.")
def festival(w):
    return {"narration": "The whole town spilled into the square for the harvest festival. There was dancing until dawn, three proposals and one very public fight.",
            "importance": 0.6, "effects": [
                {"op": "mood", "params": {"target": "all", "happiness": 0.15, "grievance": -0.08, "trust": 0.05}},
                {"op": "food", "params": {"delta": -len(w.alive()) * 3}},
                {"op": "memory", "params": {"target": "random:40", "text": "The festival. I danced with someone I shouldn't have.", "emotion": "joy", "importance": 0.55}}]}


@preset("religious_revival", "A preacher arrives; a fervent, order-loving movement forms around them.")
def revival(w):
    p = _pick(w, "random:1")
    return {"narration": f"A wandering preacher set up in the square and by the third night {p.name if p else 'half the town'} was weeping at their feet. They speak of order, sin and the wickedness of the rich.",
            "importance": 0.8, "effects": [
                {"op": "mood", "params": {"target": "poorest:50", "authority": 0.25, "trust": -0.1, "happiness": 0.05}},
                {"op": "movement", "params": {"founder": p.name if p else "", "name": "Brethren of the River", "economic": -0.3, "authority": 0.7, "theme": "sin and pride"}},
                {"op": "memory", "params": {"target": "random:35", "text": "I heard the preacher. Something in me answered.", "emotion": "hope", "importance": 0.6}}]}


@preset("witch_hunt", "Fear finds a scapegoat: an outsider is accused and driven out or killed.")
def witch_hunt(w):
    v = _pick(w, "random:1")
    return {"narration": f"After a run of bad luck the town needed someone to blame, and it chose {v.name if v else 'a stranger'}. Nobody who joined the mob will admit it now.",
            "importance": 0.85, "effects": [
                {"op": "kill", "params": {"target": f"name:{v.name}" if v else "random:1", "cause": "the mob"}},
                {"op": "mood", "params": {"target": "all", "trust": -0.15, "authority": 0.1, "happiness": -0.05}},
                {"op": "memory", "params": {"target": "random:40", "text": "I was there when they came for them. I did nothing.", "emotion": "shame", "importance": 0.7}}]}


@preset("royal_visit", "A powerful visitor arrives; the town preens, spends, and feels important.")
def royal_visit(w):
    return {"narration": "Word came that the Margrave would pass through. The roads were swept, the tavern repainted and every debt in town was called in to pay for it.",
            "importance": 0.6, "effects": [
                {"op": "mood", "params": {"target": "all", "happiness": 0.08, "trust": 0.1, "authority": 0.05}},
                {"op": "money", "params": {"target": "owners", "delta": 400}},
                {"op": "money", "params": {"target": "poorest:30", "delta": -40}},
                {"op": "memory", "params": {"target": "random:30", "text": "I saw the Margrave. He looked bored.", "emotion": "pride", "importance": 0.45}}]}


@preset("feud", "The two richest families fall out; the town takes sides.")
def feud(w):
    from .commands import select
    rich = select(w, "richest:2", _rng(w))
    if len(rich) < 2:
        return festival(w)
    a, b = rich
    return {"narration": f"An inheritance, a fence line and thirty years of resentment: the {a.surname}s and the {b.surname}s are no longer speaking, and everyone else is being asked to choose.",
            "importance": 0.75, "effects": [
                {"op": "relationship", "params": {"a": a.name, "b": b.name, "delta": -80}},
                {"op": "mood", "params": {"target": "all", "happiness": -0.03, "grievance": 0.05}},
                {"op": "memory", "params": {"target": "random:25", "text": f"The {a.surname}–{b.surname} feud. I've picked a side and I'm not sure it's the right one.", "emotion": "fear", "importance": 0.55}}]}


# ------------------------------------------------------------------ economy
@preset("gold_rush", "Gold in the hills: new mines, prospectors, and arguments.")
def gold_rush(w):
    return {"narration": "Gold was found in the hills. Within a month there were two new mines, a dozen strangers and a great many arguments about who owned what.",
            "importance": 0.85, "effects": [
                {"op": "business", "params": {"action": "open", "kind": "mine", "owner": "richest:1"}},
                {"op": "business", "params": {"action": "open", "kind": "mine", "owner": "random:1"}},
                {"op": "citizens", "params": {"count": 12, "wealth": 100, "note": "I came for the gold."}},
                {"op": "mood", "params": {"target": "all", "economic": 0.1}},
                {"op": "memory", "params": {"target": "random:30", "text": "Gold in the hills! Everyone has gone a little mad.", "emotion": "hope", "importance": 0.6}}]}


@preset("bank_failure", "The town's moneylender collapses; savings vanish, business cash halves.")
def bank_failure(w):
    return {"narration": "The moneylender's door was found locked, the ledger burned and the lender gone. Half the town's savings went with them.",
            "importance": 0.9, "effects": [
                {"op": "money", "params": {"target": "richest:40", "multiplier": 0.55}},
                {"op": "mood", "params": {"target": "all", "trust": -0.2, "grievance": 0.15, "economic": -0.1}},
                {"op": "inject", "params": {"name": "recession", "kwargs": {"days": 150}}},
                {"op": "memory", "params": {"target": "richest:40", "text": "Years of saving, gone in a night. I trusted the wrong man.", "emotion": "anger", "importance": 0.8}}]}


@preset("new_trade_route", "A trade road opens: exports boom, merchants prosper, prices ease.")
def trade_route(w):
    return {"narration": "The pass to the coast was cleared and the first caravans came through. Suddenly everything the town made had a buyer.",
            "importance": 0.75, "effects": [
                {"op": "inject", "params": {"name": "boom", "kwargs": {"days": 240}}},
                {"op": "business", "params": {"action": "open", "kind": "market", "owner": "richest:1"}},
                {"op": "tech", "params": {"multiplier": 1.05}},
                {"op": "mood", "params": {"target": "all", "happiness": 0.06, "economic": 0.08}},
                {"op": "memory", "params": {"target": "job:merchant", "text": "Caravans every week. I can barely keep the shelves stocked.", "emotion": "pride", "importance": 0.6}}]}


@preset("inflation", "Debased coin: prices double for a season, wages lag.")
def inflation(w):
    return {"narration": "The new coin was thinner than the old. Within weeks bread cost twice what it had and wages had not moved.",
            "importance": 0.7, "effects": [
                {"op": "food", "params": {"delta": -w.food * 0.5}},
                {"op": "money", "params": {"target": "all", "multiplier": 0.75}},
                {"op": "mood", "params": {"target": "poorest:60", "grievance": 0.15, "trust": -0.1}},
                {"op": "memory", "params": {"target": "random:30", "text": "Everything costs more and my purse is lighter. Someone is stealing from us by arithmetic.", "emotion": "anger", "importance": 0.6}}]}


@preset("land_reform", "The government seizes the largest fortunes and shares them out.")
def land_reform(w):
    from .commands import select
    rich = select(w, "richest:10", _rng(w))
    pot = sum(c.money for c in rich) * 0.5
    poor_n = max(1, len(w.alive()) // 2)
    return {"narration": f"By decree, half the wealth of the ten richest households was seized and shared among the poorest. {rich[0].name if rich else 'The rich'} called it robbery; the square called it justice.",
            "importance": 0.95, "effects": [
                {"op": "money", "params": {"target": "richest:10", "multiplier": 0.5}},
                {"op": "money", "params": {"target": f"poorest:{poor_n}", "delta": pot / poor_n}},
                {"op": "mood", "params": {"target": "richest:10", "grievance": 0.5, "trust": -0.4, "economic": 0.3}},
                {"op": "mood", "params": {"target": f"poorest:{poor_n}", "grievance": -0.3, "trust": 0.2, "economic": -0.1}},
                {"op": "memory", "params": {"target": "richest:10", "text": "They took what my family built. I will remember every name on that council.", "emotion": "anger", "importance": 0.9}}]}


@preset("automation_wave", "Machines arrive in the workshops and mines (30% of jobs).")
def automation_wave(w):
    return {"narration": "The engines arrived on carts and by the end of the month a third of the workshop hands had nothing to do.",
            "importance": 0.9, "effects": [{"op": "inject", "params": {"name": "automation", "kwargs": {"share": 0.3}}}]}


# ------------------------------------------------------------------ nature & disaster
@preset("great_fire", "Fire in the town centre: businesses and homes burn.")
def great_fire(w):
    bs = [b for b in w.open_businesses() if b.kind != "farm"]
    r = _rng(w)
    victims = r.sample(bs, min(2, len(bs)))
    effects = [{"op": "business", "params": {"action": "close", "name": b.name}} for b in victims]
    effects += [{"op": "kill", "params": {"target": "random:3", "cause": "the fire"}},
                {"op": "money", "params": {"target": "random:30", "multiplier": 0.6}},
                {"op": "mood", "params": {"target": "all", "happiness": -0.12, "trust": -0.05}},
                {"op": "memory", "params": {"target": "all", "text": "The night of the fire. The sky was orange and everyone was screaming names.", "emotion": "fear", "importance": 0.8}}]
    return {"narration": f"A lamp fell in the night and the wind did the rest. By morning {' and '.join(b.name for b in victims) or 'the centre of town'} were ash.",
            "importance": 0.95, "effects": effects}


@preset("harsh_winter", "A killing winter: food runs short, the old and young suffer.")
def harsh_winter(w):
    return {"narration": "The snow came early and stayed. The granary was rationed, the river froze, and the old people stopped coming to the square.",
            "importance": 0.8, "effects": [
                {"op": "food", "params": {"delta": -w.food * 0.4}},
                {"op": "weather", "params": {"kind": "drought", "days": 60}},
                {"op": "mood", "params": {"target": "elders", "health": -0.3, "happiness": -0.1}},
                {"op": "mood", "params": {"target": "children", "health": -0.15}},
                {"op": "kill", "params": {"target": "elders", "count": 2, "cause": "the winter"}},
                {"op": "memory", "params": {"target": "all", "text": "The long winter. We burned the furniture.", "emotion": "fear", "importance": 0.6}}]}


@preset("locusts", "A swarm strips the fields bare.")
def locusts(w):
    return {"narration": "The sky went dark at noon and when it cleared there was nothing green left within a day's walk.",
            "importance": 0.85, "effects": [
                {"op": "food", "params": {"delta": -w.food * 0.7}},
                {"op": "weather", "params": {"kind": "drought", "days": 45}},
                {"op": "mood", "params": {"target": "job:farmer", "grievance": 0.2, "happiness": -0.15}},
                {"op": "memory", "params": {"target": "all", "text": "The locusts. You could hear them chewing.", "emotion": "fear", "importance": 0.7}}]}


@preset("earthquake", "The ground shakes: buildings fall, people die, everyone is afraid.")
def earthquake(w):
    return {"narration": "The earth moved for a count of twenty. When it stopped, the school bell was ringing on its own and three houses were rubble.",
            "importance": 0.95, "effects": [
                {"op": "business", "params": {"action": "close", "kind": "school"}},
                {"op": "kill", "params": {"target": "random:5", "cause": "the earthquake"}},
                {"op": "money", "params": {"target": "all", "multiplier": 0.8}},
                {"op": "mood", "params": {"target": "all", "happiness": -0.15, "trust": -0.05, "authority": 0.1}},
                {"op": "memory", "params": {"target": "all", "text": "The ground itself betrayed us.", "emotion": "fear", "importance": 0.8}}]}


@preset("cure_discovered", "The clinic finds a cure: the sickness ends, the doctor is a hero.")
def cure(w):
    d = _pick(w, "job:doctor")
    return {"narration": f"{d.name if d else 'The clinic'} found that boiled willow bark and rest did what prayer had not. The sick got up; the town threw a party.",
            "importance": 0.8, "effects": [
                {"op": "end", "params": {"what": "pandemic"}},
                {"op": "tech", "params": {"multiplier": 1.05}},
                {"op": "mood", "params": {"target": "all", "happiness": 0.12, "trust": 0.1}},
                {"op": "money", "params": {"target": f"name:{d.name}" if d else "job:doctor", "delta": 800}},
                {"op": "memory", "params": {"target": "all", "text": "They found a cure. I had already written my goodbyes.", "emotion": "joy", "importance": 0.7}}]}


# ------------------------------------------------------------------ politics & war
@preset("assassination", "The head of the ruling party is murdered; a snap election follows.")
def assassination(w):
    from .commands import _movement_by_name
    m = _movement_by_name(w, w.policy.ruling_party)
    leader = w.citizens.get(m.founder_id) if m else max(w.alive(), key=lambda c: c.reputation)
    return {"narration": f"{leader.name} was found at the foot of the mill stairs with a knife in their back. Everyone has a theory; nobody has a witness.",
            "importance": 1.0, "effects": [
                {"op": "kill", "params": {"target": f"name:{leader.name}", "cause": "assassination"}},
                {"op": "mood", "params": {"target": "all", "trust": -0.2, "authority": 0.15, "grievance": 0.1}},
                {"op": "government", "params": {"name": "Emergency Council", "economic": w.policy.platform["economic"], "authority": min(1, w.policy.platform["authority"] + 0.4)}},
                {"op": "law", "params": {"name": "curfew", "enact": True}},
                {"op": "memory", "params": {"target": "all", "text": f"{leader.name.split()[0]} is dead and the town is full of whispers.", "emotion": "fear", "importance": 0.85}}]}


@preset("coup", "The militia seizes the council house; a strongman rules by curfew.")
def coup(w):
    s = max(w.adults(), key=lambda c: c.personality["extraversion"] * (1 - c.personality["agreeableness"]) + c.beliefs["authority"])
    return {"narration": f"At dawn the militia held the council house and {s.name} read a proclamation from its steps. There would be order now, and anyone who disagreed could say so to the guards.",
            "importance": 1.0, "effects": [
                {"op": "government", "params": {"name": f"{s.surname} Regime", "economic": 0.3, "authority": 0.9}},
                {"op": "law", "params": {"name": "curfew", "enact": True}},
                {"op": "mood", "params": {"target": "all", "trust": -0.15, "happiness": -0.05}},
                {"op": "money", "params": {"target": f"name:{s.name}", "delta": 3000}},
                {"op": "memory", "params": {"target": "all", "text": f"{s.name.split()[0]} rules now. We keep our heads down.", "emotion": "fear", "importance": 0.85}}]}


@preset("conscription", "A distant war calls up the young; some never return, wages rise.")
def conscription(w):
    return {"narration": "The recruiting sergeant took every able-bodied adult under thirty who couldn't pay the exemption. The fields are short-handed and the tavern is quiet.",
            "importance": 0.9, "effects": [
                {"op": "kill", "params": {"target": "young", "count": max(2, len(w.adults()) // 12), "cause": "the war"}},
                {"op": "money", "params": {"target": "richest:15", "delta": -300}},
                {"op": "mood", "params": {"target": "all", "grievance": 0.15, "trust": -0.1, "authority": 0.1}},
                {"op": "memory", "params": {"target": "all", "text": "They marched them out at dawn. Some of the mothers followed to the ford.", "emotion": "grief", "importance": 0.8}}]}


@preset("refugees", "Refugees from a war elsewhere arrive, poor and many.")
def refugees(w):
    return {"narration": "Forty people came down the north road with everything they owned on their backs. The town argued about them for a week and then found them somewhere to sleep.",
            "importance": 0.8, "effects": [
                {"op": "citizens", "params": {"count": 40, "wealth": 30, "note": "We lost everything on the road. This town took us in — or tolerated us."}},
                {"op": "mood", "params": {"target": "poorest:40", "grievance": 0.1, "authority": 0.1}},
                {"op": "mood", "params": {"target": "richest:20", "happiness": -0.03}},
                {"op": "memory", "params": {"target": "random:30", "text": "The refugees. I gave them bread and felt both good and afraid.", "emotion": "hope", "importance": 0.5}}]}


@preset("charter_of_rights", "A charter limits the government: trust and liberty rise, order-lovers grumble.")
def charter(w):
    return {"narration": "After a month of argument the council signed a charter: no curfews without a vote, no tax without an account, and every citizen may speak in the square.",
            "importance": 0.85, "effects": [
                {"op": "end", "params": {"what": "curfew"}},
                {"op": "mood", "params": {"target": "all", "trust": 0.2, "authority": -0.15, "grievance": -0.1}},
                {"op": "memory", "params": {"target": "all", "text": "The charter was read aloud. For once I felt like the town belonged to us.", "emotion": "hope", "importance": 0.7}}]}


@preset("school_reform", "Free schooling for every child, funded from the treasury.")
def school_reform(w):
    return {"narration": "The council voted to pay the schoolmaster from the treasury and to fine any parent who kept a child from lessons.",
            "importance": 0.7, "effects": [
                {"op": "policy", "params": {"field": "public_education", "value": True}},
                {"op": "policy", "params": {"field": "tax_rate", "value": min(0.5, w.policy.tax_rate + 0.04)}},
                {"op": "business", "params": {"action": "open", "kind": "school", "owner": "random:1"}},
                {"op": "mood", "params": {"target": "children", "happiness": -0.02}},
                {"op": "mood", "params": {"target": "richest:20", "grievance": 0.05}},
                {"op": "memory", "params": {"target": "adults", "text": "Every child in school now. Ours will read better than we do.", "emotion": "hope", "importance": 0.5}}]}


@preset("strike_wave", "The biggest movement calls a general strike.")
def strike_wave(w):
    m = max((m for m in w.movements.values() if m.alive), key=lambda m: len(m.members), default=None)
    if m is None:
        return revival(w)
    return {"narration": f"The {m.name} called everyone out. The mills are silent and there are pickets at the ford.",
            "importance": 0.85, "effects": [
                {"op": "strike", "params": {"action": "start", "movement": m.name, "days": 12}},
                {"op": "mood", "params": {"target": f"movement:{m.name}", "grievance": 0.1}},
                {"op": "memory", "params": {"target": f"movement:{m.name}", "text": "We downed tools together. Let them try to run the town without us.", "emotion": "pride", "importance": 0.7}}]}
