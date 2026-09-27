"""The v0.3 realm: five villages, the behaviour engine, crime, war, magic, animals, decrees."""
import os
import sys
import collections

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from civilisation import World
from civilisation import behaviour
from civilisation.models import WorldEvent


def _world(seed=1, pop=150):
    return World(seed=seed, population=pop)


def test_five_villages_share_one_river():
    w = _world()
    assert [v.element for v in w.villages] == ["sky", "air", "earth", "fire", "water"]
    for v in w.villages:
        with w.at(v.idx):
            assert w.alive() and all(c.village == v.idx for c in w.alive())
            assert all(b.village == v.idx for b in w.open_businesses())
    w.villages[0].diversion = 0.6                     # Sky takes most of the river…
    w.step(14)
    assert w.villages[0].water_met > w.villages[3].water_met    # …and Fire, downstream, goes thirsty


def test_six_options_all_relevant():
    w = _world()
    c, o = w.alive()[0], w.alive()[1]
    ev = WorldEvent(w.day, "social", f"{o.name} insulted {c.name}.", 0.45, [c.id, o.id], tone="bad", kind="insulted", village=0)
    for _ in range(30):
        r = behaviour.decide(w, c, ev)
        assert len(r.options) == 6 and 1 <= r.face <= 6
        menu = behaviour.S["insulted"][3]
        assert all(menu.get(k, 0) >= 0.1 for k, _ in r.options)      # plenty of relevant options, so nothing absurd
        assert r.action in dict(r.options)


def test_temperament_and_feeling_depth_change_what_people_do():
    w = _world(seed=3)
    calm, hot = w.alive()[0], w.alive()[1]
    calm.personality.update(agreeableness=0.95, neuroticism=0.05, conscientiousness=0.9)
    hot.personality.update(agreeableness=0.05, neuroticism=0.95, conscientiousness=0.1)
    o = w.alive()[2]
    tally = {calm.id: collections.Counter(), hot.id: collections.Counter()}
    peak = {}
    for c in (calm, hot):
        for _ in range(40):
            c.emotions.clear()
            for _ in range(3):                      # insulted three times in a row
                ev = WorldEvent(w.day, "social", f"{o.name} insulted {c.name}.", 0.45, [c.id, o.id], tone="bad", kind="insulted", village=0)
                r = behaviour.decide(w, c, ev)
            tally[c.id][r.action] += 1
            peak[c.id] = c.feel("anger")
    gentle = {"shrug_off", "walk_away", "forgive", "reconcile", "seek_support", "work_harder", "pray"}
    rough = {"shove", "brawl", "kill", "threaten", "mock_publicly", "smash_property", "arson", "hire_thugs", "retort", "spread_rumour", "plot_revenge"}
    assert peak[hot.id] > peak[calm.id] + 0.3                     # the same insults make one boil and barely stir the other
    assert sum(tally[calm.id][k] for k in gentle) > sum(tally[hot.id][k] for k in gentle)
    assert sum(tally[hot.id][k] for k in rough) > sum(tally[calm.id][k] for k in rough)


def test_goals_pull_every_day():
    w = _world(seed=4)
    for c in w.alive_all():
        c.goal = "earn money"
    w.step(60)
    thoughts = [t for t in w.thoughts if t.get("options")]
    assert thoughts
    acts = collections.Counter()
    for c in w.alive_all():
        acts[c.last_initiative > 0] += 1
    assert acts[True] > len(w.alive_all()) * 0.3                  # most people acted on their ambition within two months


def test_crime_is_possible_and_the_law_answers():
    w = _world(seed=5, pop=300)
    w.step(365)
    crimes = [e for e in w.events if e.kind.startswith("crime_")]
    justice = [e for e in w.events if e.category == "justice"]
    assert crimes and justice


def test_decrees_compel_and_leave_marks():
    from civilisation.commands import rules_plan, apply_plan
    w = _world(seed=6)
    a, b = w.alive()[0], w.alive()[1]
    a.rel(b.id).score = 90                                          # even someone who loves them
    for _ in range(5):
        if not b.alive:
            break
        apply_plan(w, {"narration": "x", "effects": [{"op": "act", "params": {"target": f"name:{a.name}", "act": "kill", "who": b.name}}]})
    assert not b.alive or b.health < 0.9
    before = w.grid_version
    apply_plan(w, rules_plan(w, "A meteor shower falls on Emberhold"), "rules")
    assert w.grid_version > before and any(f["type"] == "meteor" for f in w.fx)
    apply_plan(w, rules_plan(w, "War between fire and water"), "rules")
    assert any(x["active"] and {x["a"], x["b"]} == {3, 4} for x in w.wars)


def test_war_occupation_and_the_mages_bring_it_back():
    from civilisation.systems import war, magic
    w = _world(seed=7, pop=300)
    war.declare(w, 3, 4, "test")
    wr = war.war_between(w, 3, 4)
    war._end(w, wr, winner=3, terms="collapse")
    assert w.villages[4].occupier == 3
    with w.at(4):
        for c in w.alive()[:4]:
            magic.awaken(w, c, power=1.0, granted=True)
    for _ in range(80):
        w.step(7)
        if w.villages[4].occupier is None:
            break
    assert w.villages[4].occupier is None, "strong mages should eventually rise"


def test_stewards_cannot_make_a_mage_but_god_can():
    from civilisation.person import apply_person_plan, rules_interpret_person
    from civilisation.commands import apply_plan
    w = _world(seed=8)
    c = w.adopt("Ada Wish", "F", 30, {}, "x", sponsor="om", village=2)
    plan = rules_interpret_person(w, c, "Make me a mage with magic power")
    apply_person_plan(w, c, plan)
    assert not magic_awake(c) and c.goal == "master the old arts"
    apply_plan(w, {"narration": "blessed", "effects": [{"op": "magic", "params": {"target": f"name:{c.name}", "power": 0.7}}]})
    assert magic_awake(c)


def magic_awake(c):
    return bool(c.magic and c.magic.get("awakened"))


def test_stewards_are_obeyed():
    from civilisation.person import apply_person_plan, rules_interpret_person
    w = _world(seed=9)
    c = w.adopt("Bo Grim", "M", 30, {}, "x", sponsor="om", village=0)
    victim = next(x for x in w.alive() if x.id != c.id and x.village == 0)
    before = victim.money
    plan = rules_interpret_person(w, c, f"Steal from {victim.name}")
    done = apply_person_plan(w, c, plan)
    assert any("steal" in d for d in done) and (victim.money < before or c.crimes > 0)


def test_animals_live_and_can_be_adopted():
    from civilisation.systems import animals
    w = _world(seed=10)
    assert sum(a.alive for a in w.animals.values()) > 20
    pet = animals.adopt(w, "Rex", "tiger", 3, sponsor="om")
    person = w.alive_all()[0]
    animals.instruct(w, pet, f"follow {person.name}")
    assert pet.owner_id == person.id
    w.step(30)
    assert pet.id in w.animals
