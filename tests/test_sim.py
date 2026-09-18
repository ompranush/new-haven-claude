import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from civilisation import World, SilentBrain, chronicle_text
from civilisation.brains import RulesBrain, Reaction
from civilisation.systems.disasters import INJECTABLE
from civilisation.experiments import run_one


def test_world_initialises():
    w = World(seed=1, population=40)
    assert len(w.citizens) == 40
    assert len(w.open_businesses()) == 10
    assert all(c.alive for c in w.citizens.values())
    assert w.chronicle[0].category == "founding"


def test_simulation_advances_and_records():
    w = World(seed=1, population=40)
    w.step(60)
    assert w.day == 60
    assert len(w.history) >= 8
    assert w.history[-1]["day"] == 56


def test_seed_reproducibility():
    a, b = World(seed=99, population=40), World(seed=99, population=40)
    a.step(120); b.step(120)
    assert [c.name for c in a.citizens.values()] == [c.name for c in b.citizens.values()]
    assert a.history == b.history
    assert [e.text for e in a.events] == [e.text for e in b.events]


def test_different_seeds_differ():
    a, b = World(seed=1, population=40), World(seed=2, population=40)
    assert [c.name for c in a.citizens.values()] != [c.name for c in b.citizens.values()]


def test_citizens_form_relationships_and_memories():
    w = World(seed=5, population=60)
    w.step(180)
    assert any(r.score >= 45 for c in w.alive() for r in c.relationships.values())
    assert any(c.memories for c in w.alive())
    assert any(c.spouse_id for c in w.alive()), "nobody married in half a year"


def test_generations_and_inheritance():
    w = World(seed=3, population=80, config={"fertility": 3.0})
    w.step(365 * 3)
    kids = [c for c in w.citizens.values() if c.generation == 1]
    assert kids, "no children born"
    k = kids[0]
    assert len(k.parent_ids) == 2
    a, b = (w.citizens[p] for p in k.parent_ids)
    for t, v in k.personality.items():
        lo, hi = min(a.personality[t], b.personality[t]) - 0.3, max(a.personality[t], b.personality[t]) + 0.3
        assert lo <= v <= hi
    assert k.surname in (a.surname, b.surname)


def test_every_injection_runs():
    for name in INJECTABLE:
        w = World(seed=11, population=40)
        w.step(30)
        w.inject(name)
        w.step(30)
        assert w.day == 60


def test_pandemic_spreads_and_ends():
    w = World(seed=4, population=80, config={"random_shocks": False})
    w.step(30)
    w.inject("pandemic")
    w.step(120)
    assert w.pandemic is None
    assert any("burned out" in e.text for e in w.chronicle)
    assert any(c.immune for c in w.alive())


def test_automation_creates_unemployment():
    w = World(seed=8, population=100, config={"random_shocks": False})
    w.step(200)
    before = w.unemployment
    w.inject("automation", share=0.5)
    w.record_metrics()
    assert w.unemployment > before


def test_brain_gate_and_silent_brain():
    w = World(seed=6, population=40, brain=SilentBrain())
    w.step(200)
    assert w.brain_calls == 0
    w2 = World(seed=6, population=40)
    w2.step(200)
    assert w2.brain_calls > 0


def test_reaction_applies():
    w = World(seed=6, population=40)
    c = w.alive()[0]
    o = w.alive()[1]
    ev = w.emit("test", f"{o.name} insulted {c.name}.", 0.0, [])   # importance 0 → no brain; apply manually
    r = Reaction(emotion="anger", intensity=0.8, memory="Never again.", relationship_changes={o.id: -30}, grievance_delta=0.2, action="avoid")
    r.apply(w, c, ev)
    assert c.rel(o.id).score <= -30
    assert c.grievance >= 0.2
    assert c.memories[-1].text == "Never again."


def test_politics_can_emerge_under_hardship():
    # squeeze everyone: no shocks, heavy automation, recession → movements should appear in most seeds
    found = 0
    for seed in range(4):
        w = World(seed=seed, population=100, config={"random_shocks": False})
        w.step(365)
        w.inject("automation", share=0.6)
        w.inject("recession", days=400)
        w.inject("drought")
        w.step(365 * 2)
        found += bool(w.movements)
    assert found >= 2


def test_chronicle_and_biography_render():
    w = World(seed=2, population=40)
    w.step(400)
    text = chronicle_text(w)
    assert "Turning points" in text and "Day 0" in text
    bio = w.biography(w.alive()[0].id)
    assert "Personality" in bio


def test_save_load(tmp_path):
    w = World(seed=2, population=30)
    w.step(50)
    p = tmp_path / "w.pkl"
    w.save(str(p))
    w2 = World.load(str(p))
    assert w2.day == 50 and len(w2.citizens) == len(w.citizens)
    w2.step(10)


def test_experiment_row():
    row = run_one(("baseline", 1, 1, 40))
    assert row["scenario"] == "baseline" and "gini" in row and row["population"] > 0
