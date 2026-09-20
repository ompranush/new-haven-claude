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

The app is a dark game-style dashboard. The centre is a **live isometric voxel village** rendered from the world state — houses with pitched roofs, farms, forest, the river, and tiny citizens who walk between home, work and the tavern (scroll to zoom, drag to pan, hover for names). Press ▶ and the world ticks in real time. Around it: a world overview with deltas, a minimap, the selected citizen's card (bars, goal, recent memories), god mode, recent events and key metrics. Other pages: **Citizens** (table + full biographies), **Economy** (businesses, wealth distribution, prices), **Politics** (belief space with movement platforms, the friendship/feud graph), **Events** (the generated chronicle + full log), **Research** (the experiment runner), **Settings** (new worlds, the Claude brain, save/load).

The renderer is [`iso.py`](src/civilisation/iso.py): a self-contained HTML canvas that polls a JSON snapshot the app writes each tick, so the iframe never re-mounts while the simulation runs.

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

## What makes them feel like people

- **Temperament** — every citizen is one of eight archetypes (firebrand, cynic, worrier, dreamer, striver, saint, loner, plain) derived from their Big Five scores, with adjectives on their card. The same event produces different memories in different voices: a firebrand's *"People are going to hear about this"* vs a worrier's *"Why does it always come back to me?"* ([`personality.py`](src/civilisation/personality.py)).
- **Thoughts** — each citizen has something on their mind, generated from their actual situation: hunger, unemployment, a cold marriage, a grudge, a movement they joined. The *Inner voices* panel streams them.
- **Insults with reasons** — people mock each other's poverty, joblessness, failed businesses, marriages, politics or family, and it shows in the feed.
- **Claude** — with a key set (Settings, or `ANTHROPIC_API_KEY`), important events are handed to Claude with the citizen's full temperament, memories and relationships. The reply — emotion, a first-person memory, relationship changes, an action — lands a day or two later so play stays smooth. Claude-authored lines are marked ✨. Cost is tracked on screen.

## Politics with teeth

Elections every two years. The governing party has an **approval rating**; six weeks below 22% and it falls. Parties pass **emergency laws** according to their platform: bread rationing (with the treasury subsidising farms), quarantine during a pandemic, public works when unemployment bites, tax holidays in a recession, curfews under authoritarian governments, poor relief. Every law is an event with consequences in the economy.

## Shocks that leave marks

A drought halves harvests for a season and pulls labour into the fields; floods wreck riverside businesses and rehouse families; raids burn a business; recessions bankrupt the weak; pandemics spread person-to-person and kill. A month after each shock the chronicle records the reckoning: who died, what closed, who is hungry.

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

Built-in shocks: `drought, flood, pandemic, recession, boom, breakthrough, automation, raid, meteor_strike, immigration`.

Plus a catalogue of historical shocks in [`presets.py`](src/civilisation/presets.py), each written as a decree plan that names real people from the town: `festival, religious_revival, witch_hunt, royal_visit, feud, gold_rush, bank_failure, new_trade_route, inflation, land_reform, automation_wave, great_fire, harsh_winter, locusts, earthquake, cure_discovered, assassination, coup, conscription, refugees, charter_of_rights, school_reform, strike_wave`. Adding one is a ten-line function.

With an API key, the **decree box** accepts anything you can type: Claude turns it into the same kind of plan ([`commands.py`](src/civilisation/commands.py) is the effects language).

## Experiments

```bash
python cli.py experiment baseline automation universal_education --seeds 10 --years 20
```

Built-in scenarios: `baseline, high_inequality, equal_start, universal_education, no_school, automation, longevity_x2, declining_births, baby_boom, pandemic_y2, great_recession, no_shocks, open_borders, expensive_startups`. Each runs N seeds and reports medians and spreads of population, wealth, Gini, unemployment, happiness, grievance, parties formed, deaths. Add your own in `experiments.SCENARIOS` — a scenario is just a config dict plus a schedule of injections.

## Any model, anyone's model

**Providers.** Settings → *The mind behind the citizens*: Claude (native SDK), OpenAI, xAI/Grok, Gemini, Mistral, Groq, OpenRouter, a local **Ollama** (free), or any OpenAI-compatible endpoint. Everything that uses a model — citizens' reactions, decrees, the narrator — goes through [`providers.py`](src/civilisation/providers.py), so a provider is one entry in a table. Keys live in the browser session / server memory only.

**The public village.** Settings → *Public village*: one world shared by everyone on the server, ticking on its own thread (pace adjustable). **Move in** lets a visitor create their own citizen — name, backstory, temperament sliders — and bring **their own key**: that citizen thinks with the visitor's model at the visitor's expense, alongside everyone else's. Their sponsor sees a diary of what their person did. The host's key (if any) drives the rest of the town. Sponsors' keys are never written to disk; a restart forgets them (the citizens survive — the village autosaves yearly to `static/commons.pkl`).

**One god, many stewards.** On the public village the civilisation-level controls — play/pause, pace, shocks, decrees, the host brain — belong to whoever knows `ADMIN_PASSWORD` (Settings → *God login*). Everyone else is a **steward** of their own person: the Move in page gives them a claim token (their only way back from another device — `?claim=TOKEN` in the URL also works) and a control panel — set their goal, apply for or quit a job, found a business, visit / confront / persuade / propose to / give money to anyone, join, leave or found a movement, move house, retire them from the town — plus free-text instructions ("court Otto Petrov, then save up for a tavern") that *their own* model turns into actions and answers in character, and standing instructions their model reads before every reaction. Stewards' actions are logged as decrees tagged with the person's name. `MAX_RESIDENTS` caps the village.

**Renderer.** The village is a three.js scene ([`scene.py`](src/civilisation/scene.py)) — sun and shadows, low-poly trees, gabled houses, distinct buildings per trade, chimney smoke, drifting clouds, a slow day/night cycle, and citizens who walk between snapshots. Orbit with the mouse. Settings can switch to the lighter classic canvas renderer for machines without WebGL or internet (the 3D library loads from a CDN).

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it fits together and [`SECURITY.md`](SECURITY.md) for how visitors' keys are handled.

## Deploying an always-on village (Railway + Supabase)

The public village persists everything — metrics, events, inner voices, decrees, residents and periodic world snapshots — through [`persistence.py`](src/civilisation/persistence.py). With no configuration it uses a local SQLite file; with Supabase it uses Postgres, and the village restores itself (people, history, and sponsored minds) after every restart.

1. **Supabase** → SQL editor → run [`supabase_schema.sql`](supabase_schema.sql). The tables have row-level security on and no policies, so only the service-role key can touch them. Copy the project URL and the **service_role** key (Settings → API).
2. **Railway** → New project → Deploy from GitHub repo (this one; the `Dockerfile` is picked up automatically). Add variables — see [`.env.example`](.env.example):
   - `APP_SECRET` — a long random string (`openssl rand -hex 32`). Visitors' API keys are encrypted with it before being stored; without it they are not stored at all.
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
   - optionally a host key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY` …) so the town itself thinks; `LLM_MODEL`, `LLM_THRESHOLD`, `LLM_MAX_CALLS` to tune it.
   - `ADMIN_PASSWORD` — makes you god. Without it, a production server has *no* god.
   - `TICK_SECONDS` (default 4 — one simulated day every 4 s), `SNAPSHOT_EVERY_DAYS` (30), `MAX_RESIDENTS` (60), `VILLAGE_ERA`.
3. Generate a domain in Railway → Settings → Networking. Open it, go to Settings → *Public village*.

What's protected how: the service-role key and `APP_SECRET` exist only in Railway's environment; visitors' keys travel over HTTPS into server memory, are Fernet-encrypted at rest, and are decrypted only inside the server process; nothing key-shaped is ever written to the event log. The Events page shows the **persistent log** with an importance filter, the whole recorded history chart, and every decree ever made.

## Eras

Settings → New world → **Era**: Ancient (800 BC), Medieval (1250), Industrial (1840), Modern (1998) or Future (2140). Same engine, different clothes and constraints ([`eras.py`](src/civilisation/eras.py)): the calendar, starting technology and prices, what the trades and buildings are called (a tavern is a wine house, a public house, a bar, a lounge), the building style in the 3D scene (mud-brick and flat roofs; timber and thatch; brick, slate and smokestacks; glass and flat roofs; domes), which shocks are possible (no automation before the machines exist, no witch hunts after), and the context the language models are given. Farms keep **livestock** that grazes on the map, feeds the town, breeds slowly, and gets stolen in raids; hens, deer and birds are scenery.

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
