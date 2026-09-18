# 🌍 New Haven — an artificial civilisation

> **Small people. Big stories.**

New Haven is an agent-based civilisation simulator. A hundred settlers land on a riverbank with a personality, some money and a goal. Then you let them live: they work, trade, marry, gossip, hold grudges, have children who inherit their temperament, go hungry, get angry, found political movements, strike, vote, and die. Nothing in the story is scripted — the parties, the famines, the dynasties and the revolutions all emerge from the rules.

The whole thing runs **with zero LLM calls**. A language model is an *optional* cognition layer that is consulted only when something important happens to someone — and even then it just answers one question: *"given who you are and what you remember, how do you react?"*

```
$ python cli.py --seed 42 --years 15 run

- Day 203  · Lina Fischer founded the United Party, a movement against hardship.
- Day 1,460 · Election of year 5: Founders' Council held on with 100% (turnout 46%).
- Day 3,650 · Famine: 6 people starved to death this month with bread at £12.
- Day 3,668 · Lina Fischer founded the United Party, a movement against hunger. 5 joined on the first day.
- Day 3,675 · The United Party now counts 20 members (24% of adults) and declared itself a political party.
- Day 4,380 · Election of year 13: United Party took power with 67% (turnout 68%).
               Policy now: tax 24%, welfare £9/day, public schooling.
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py            # the world, live
python cli.py run --years 20    # or just print a chronicle
pytest -q                       # tests
```

The Streamlit app has six tabs: the **map** (citizens move between home, work and the tavern; a pandemic visibly spreads through the social hubs), a **citizen inspector** (biography, relationships, memories), **society** (belief space with movement platforms, the friendship/feud graph, wealth distribution), **trajectory** charts, the **chronicle** (a generated documentary), and an **experiment runner**. The sidebar has god mode.

## What's inside

| Layer | What it does |
|---|---|
| `models.py` | Plain dataclasses: `Citizen` (Big Five personality, needs, skills, beliefs, memories, relationships), `Business`, `Movement`, `Policy`, `Memory`, `Relationship`, `WorldEvent` |
| `terrain.py` | Procedural map: river, farmland, forest, ore hills, a plaza, roads |
| `world.py` | The `World`: owns state, runs the systems each day, records metrics, gates the brain, keeps the chronicle |
| `systems/economy.py` | Real accounting. Farms grow food, prices float on reserves, businesses pay wages from cash, hire when a hand would pay for itself, cut wages, lay people off, go bankrupt. Workers switch to better-paid jobs. Citizens found businesses. Tax → treasury → welfare, pensions, public schools and clinics, public contracts. Exports and spoilage keep it from exploding or imploding. |
| `systems/social.py` | Who meets whom (colleagues, neighbours, existing ties), compatibility from personality, insults, gifts, friendships, feuds, marriage, gossip that moves reputations, grievance contagion, pandemic transmission. |
| `systems/lifecycle.py` | Hunger, health, a Gompertz mortality curve, schooling, coming of age, births with weighted-inherited personality + mutation, inheritance of money and businesses, goals. |
| `systems/politics.py` | Beliefs (economic left/right, authority, trust) anchored in wealth and temperament, pushed by hardship and friends. Aggrieved extraverts with angry friends found movements; movements recruit through the social graph, become parties at 12% of adults, strike; elections every 4 years; riots force snap elections; the winner's platform sets tax, welfare, minimum wage, public services — which changes the economy, which changes beliefs. |
| `systems/disasters.py` | Random and injected shocks: drought, flood, pandemic (person-to-person over the social graph), recession, boom, raid, automation, technological breakthrough, meteor, immigration, plus emergent discoveries and famine detection. |
| `brains.py` | The cognition contract: `Brain.react(world, citizen, event) -> Reaction`. `RulesBrain` is free and personality-driven. `SilentBrain` is the control arm. |
| `llm.py` | `LLMBrain`: the same contract answered by Claude via structured JSON output, with an importance threshold, a hard call cap, prompt caching and rules fallback. `narrate()` turns the chronicle into a documentary. |
| `chronicle.py` | The rules-based documentary: eras, turning points, dynasties, people who mattered. |
| `experiments.py` | Scenarios × seeds → distributions. |

### The brain gate

```
event emitted ──► importance ≥ chronicle_threshold? ──► kept forever in the chronicle
              └─► importance ≥ brain_threshold and has actors? ──► brain.react() for each actor
                                                                    │
                                              RulesBrain (free) ◄───┴───► LLMBrain (≥ llm threshold, capped)
                                                                    │
                                                        Reaction: emotion, memory, relationship deltas,
                                                        grievance, belief shift, action (confront / avoid /
                                                        seek support / quit / found movement / donate …)
```

A 15-year run of 100 people produces ~3,000 brain-worthy events. With `LLMBrain(threshold=0.75, max_calls=100)` that becomes about 100 small API calls — a few pence — and every one of them is something a person would actually remember.

## God mode

```python
from civilisation import World
w = World(seed=7, population=100)
w.step(365 * 3)
w.inject("automation", share=0.3)     # machines replace 30% of workshop, mine, market and bakery jobs
w.step(365 * 2)
w.inject("pandemic")                  # patient zero is the most sociable person in town
w.step(365 * 5)
print(w.biography(17))
from civilisation import chronicle_text; print(chronicle_text(w))
```

Injections: `drought, flood, pandemic, recession, boom, breakthrough, automation, raid, meteor_strike, immigration`.

## Experiments

```bash
python cli.py experiment baseline automation universal_education --seeds 10 --years 20
```

Built-in scenarios: `baseline, high_inequality, equal_start, universal_education, no_school, automation, longevity_x2, declining_births, baby_boom, pandemic_y2, great_recession, no_shocks, open_borders, expensive_startups`. Each runs N seeds and reports medians and spreads of population, wealth, Gini, unemployment, happiness, grievance, parties formed, deaths. Add your own in `experiments.SCENARIOS` — a scenario is just a config dict plus a schedule of injections.

## The Claude layer

```bash
pip install anthropic            # and set ANTHROPIC_API_KEY or run `ant auth login`
python cli.py --llm --llm-threshold 0.75 --llm-max-calls 100 --years 10 run --narrate
```

In the app, flip **Claude brain for major events** before creating a world. Events processed by Claude are tagged `(brain: llm)` in the feed and the citizen's memory is written in their own voice.

The research question this sets up: run a **rules-only** world and an **LLM-assisted** world from the same seed and compare. Does giving citizens language and memory change the social structures that emerge? `World(seed=1, brain=RulesBrain())` vs `World(seed=1, brain=LLMBrain())` — same rules, same dice, different minds.

## Determinism

Given a seed, a config and the same sequence of injections, a rules-only world is fully reproducible (`tests/test_sim.py::test_seed_reproducibility`). Worlds pickle: `w.save("world.pkl")`, `World.load("world.pkl")`.

## Roadmap

- Isometric renderer with pathfinding, houses and districts
- Citizen-to-citizen conversations (LLM) that produce rumours and alliances
- Institutions: courts, a press, religion as an emergent belief cluster
- Migration between multiple towns
- Local-model adapter so the LLM layer runs on your own machine
- The 1,000-year two-world comparison

## Design rule

We don't optimise for impressive code. We optimise for *"holy shit, what just happened in my simulation?"*

MIT.
