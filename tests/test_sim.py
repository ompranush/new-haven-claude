import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from civilisation import World, SilentBrain, chronicle_text
from civilisation.brains import RulesBrain, Reaction
from civilisation.systems.disasters import INJECTABLE, all_injectable
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
    assert len(all_injectable()) > len(INJECTABLE)
    for name in all_injectable():
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


def test_decree_plan_executes():
    from civilisation.commands import apply_plan, FALLBACK, select
    w = World(seed=9, population=60)
    w.step(30)
    before = len(w.open_businesses())
    done = apply_plan(w, FALLBACK["gold"], source="rules")
    assert len(w.open_businesses()) >= before + 2
    assert any("newcomers" in d for d in done)
    assert w.chronicle[-1].category == "decree"
    plan = {"narration": "Test.", "importance": 0.6, "effects": [
        {"op": "money", "params": {"target": "poorest:5", "delta": 1000}},
        {"op": "policy", "params": {"field": "tax_rate", "value": 0.3}},
        {"op": "law", "params": {"name": "rationing", "enact": True}},
        {"op": "kill", "params": {"target": "random:2", "cause": "a duel"}},
        {"op": "bogus", "params": {}}]}
    n = len(w.alive())
    apply_plan(w, plan, source="rules")
    assert w.policy.tax_rate == 0.3 and "rationing" in w.policy.laws and len(w.alive()) == n - 2


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET", "test-secret")
    from civilisation.persistence import SQLiteStore, Recorder, restore_world, encrypt_key, decrypt_key
    store = SQLiteStore(str(tmp_path / "t.db"))
    rec = Recorder(store, "v", snapshot_every=5)
    w = World(seed=4, population=40)
    w.step(12); rec.flush(w)
    assert rec.last_error == "" and store.read_events("v") and store.read_metrics("v")
    w2 = restore_world(store, "v")
    assert w2.day == 12 and w2.brain is not None
    w2.step(3)                                   # a restored world must keep running
    tok = encrypt_key("sk-abc")
    assert tok != "sk-abc" and decrypt_key(tok) == "sk-abc"
    store.write_resident("v", {"citizen_id": 1, "name": "A", "sponsor": "s", "provider": "openai", "model": "gpt-5", "enc_key": tok, "max_calls": 10})
    assert store.read_residents("v")[0]["enc_key"] == tok


def test_steward_controls():
    from civilisation.person import apply_person_plan, rules_interpret_person
    from civilisation.brains import RulesBrain
    w = World(seed=5, population=60)
    w.step(60)
    c = w.adopt("Ada Okonkwo", "F", 28, {"openness": .8, "conscientiousness": .5, "extraversion": .8, "agreeableness": .5, "neuroticism": .3}, "A smith's daughter.", sponsor="t", brain=RulesBrain())
    other = next(x for x in w.alive() if x.id != c.id and not x.spouse_id and x.age_on(w.day) >= 20)
    done = apply_person_plan(w, c, {"effects": [{"op": "goal", "params": {"goal": "start a business"}}] + [{"op": "visit", "params": {"who": other.name}}] * 5
                                    + [{"op": "propose", "params": {"who": other.name}}, {"op": "nope", "params": {}}]})
    assert c.goal == "start a business" and c.spouse_id == other.id and any("unknown op" in d for d in done)
    c.money = 5000
    plan = rules_interpret_person(w, c, "open a tavern")
    apply_person_plan(w, c, plan)
    assert any(b.kind == "tavern" and b.owner_id == c.id for b in w.open_businesses())


def test_security_helpers(monkeypatch):
    from civilisation.security import esc, clean_text, scrub, check_base_url, sign_blob, verify_blob, Limiter
    assert esc('<img onerror="x">') == "&lt;img onerror=&quot;x&quot;&gt;"
    assert clean_text("a\x00b\x1fc" + "x" * 100, 5) == "abcxx"
    assert "sk-" not in scrub("Error 401 for key sk-ant-abcdefghijklmnop at api") and "[redacted]" in scrub("token sk-abcdefghijklmnop")
    for bad in ("http://example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1", "https://10.0.0.1/v1", "https://169.254.169.254/latest"):
        try:
            check_base_url(bad); assert False, bad
        except ValueError:
            pass
    monkeypatch.setenv("APP_SECRET", "s3cret")
    signed = sign_blob(b"payload")
    assert signed != b"payload" and verify_blob(signed) == b"payload"
    try:
        verify_blob(signed[:-1] + b"X"); assert False
    except ValueError:
        pass
    try:
        verify_blob(b"payload"); assert False        # unsigned refused when a secret is set
    except ValueError:
        pass
    lim = Limiter(2, 60)
    lim.hit("k"); lim.hit("k")
    assert not lim.allow("k") and lim.allow("other")


def test_adopt_sanitises_input():
    w = World(seed=1, population=30)
    c = w.adopt("<b>Evil</b>\x00Name" + "x" * 100, "Z", 5, {}, "story\x07", sponsor="s" * 100)
    assert "\x00" not in c.name and len(c.name) <= 40 and c.sex == "M" and c.age_on(w.day) == 18 and len(c.sponsor) == 40


def test_custom_provider_gated(monkeypatch):
    from civilisation.providers import make_backend, BackendError
    monkeypatch.delenv("ALLOW_CUSTOM_PROVIDERS", raising=False)
    for prov in ("custom", "ollama"):
        try:
            make_backend(prov, "m", api_key="k", base_url="https://example.com/v1"); assert False
        except BackendError:
            pass
    try:
        make_backend("openai", "gpt-5", api_key="k", base_url="https://evil.example/v1"); assert False
    except BackendError:
        pass
