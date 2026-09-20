# New Haven — Architecture

New Haven is an agent-based civilisation with three kinds of participant: the **engine** (deterministic rules that run every simulated day), **language models** (consulted only when something important happens to someone), and **people** — one god who runs the world and many stewards who each look after a single citizen.

```
                     ┌──────────────────────── Streamlit app (app.py) ────────────────────────┐
  browser ──────────▶│  World · Citizens · Economy · Politics · Events · Move in · Research ·  │
  (three.js scene    │  Settings                                                               │
   polls JSON)       │        god controls ──┐              steward controls ──┐              │
                     └───────────────────────┼──────────────────────────────────┼──────────────┘
                                             ▼                                  ▼
   ┌──────────────┐   plan (DSL)   ┌────────────────────────────────────────────────────────┐
   │ LLM backends │◀──────────────▶│  World (world.py)  — one per private session, or the   │
   │ providers.py │  reactions     │  shared public village ticking on its own thread        │
   │ Claude native│                │                                                          │
   │ OpenAI-compat│                │  systems/: economy · social · lifecycle · politics ·    │
   │ (OpenAI, xAI,│                │            disasters        personality.py · eras.py    │
   │  Gemini, …)  │                │  brains.py gate → RulesBrain | LLMBrain (per citizen)   │
   └──────────────┘                │  commands.py (decrees) · person.py (steward actions)    │
                                   └───────────────────────────┬──────────────────────────────┘
                                                               ▼
                                   persistence.py  ──▶  Supabase (prod) | SQLite (dev)
                                   metrics · events · thoughts · decrees · residents · signed snapshots
```

## The engine

Each simulated day, `World._step_day` runs the systems in order:

| System | What happens every day |
|---|---|
| `lifecycle` | hunger and health; schooling; coming of age; births with weighted-inherited personality plus mutation; deaths on a Gompertz curve; inheritance of money and businesses |
| `economy` | farms grow food (and herds add to it); prices float on reserves; citizens eat and spend; businesses pay wages from cash, hire when a hand would pay for itself, cut wages, lay off, go bankrupt; workers switch to better pay; citizens found businesses; tax → treasury → welfare, pensions, public schools and clinics, public contracts; exports and spoilage |
| `social` | citizens move between home, work and the tavern; meet colleagues, neighbours and existing ties; compatibility from personality; insults (with reasons), gifts, friendships, feuds, marriage, gossip that moves reputations, grievance contagion, pandemic transmission |
| `politics` | weekly: beliefs regress toward anchors set by wealth and temperament, pushed by hardship and friends; grievance accumulates from unemployment, hunger, inequality, taxes; aggrieved extraverts with angry friends found movements; movements recruit, become parties at 12% of adults, strike; the government passes emergency laws by platform (rationing, quarantine, public works, tax holidays, curfews, poor relief), has an approval rating and falls after six bad weeks; elections every two years set policy; riots force snap elections |
| `disasters` | random and injected shocks; a pandemic spreads person-to-person; a month after each shock the chronicle records the reckoning |

Everything is deterministic given a seed, a configuration and the sequence of injections (`tests/test_sim.py::test_seed_reproducibility`).

## The brain gate

`World.emit(category, text, importance, actors, tone)` is the single event entry point. Events at or above `chronicle_threshold` are kept forever; events at or above `brain_threshold` with actors are handed to a brain for each actor: `brains.get(citizen_id, world.brain).react(world, citizen, event) → Reaction`. A `Reaction` is small and structured — emotion, a first-person memory, relationship deltas, grievance and belief shifts, one action from a fixed list — and `Reaction.apply` is the only way a brain changes the world.

- `RulesBrain` — free, deterministic, personality-driven; writes memories in one of eight temperament voices (`personality.py`).
- `LLMBrain` — the same contract answered by a model through `providers.py`. Calls run in a thread pool; results land a day or two later via `drain()` so play never blocks. Each brain has an importance threshold, a hard call cap, a cost estimate, and (for sponsored citizens) an owner and an optional expiry.
- `SilentBrain` — the control arm for experiments.

## Decrees and steward actions

Both are small effect languages executed by the engine, so a model plans and the rules execute:

- `commands.py` — **decrees** (god): inject a shock, change the granary, money/mood for targeted groups (`poorest:10`, `job:farmer`, `name:…`, `hungry`, `owners`…), kill, policy, laws, open/close businesses, newcomers, tech, relationships, found movements, replace the government, start/end strikes and other situations, and a first-person memory for everyone affected. `presets.py` is a catalogue of 23 historical shocks written in this language. `llm.interpret` turns free text into a plan.
- `person.py` — **steward actions** (one citizen): goal, apply/quit/found, move, visit, confront, propose, give, persuade, join/leave/found a movement, note. `interpret_person` turns free text into a plan *and* an in-character reply using the steward's own backend.

Unknown ops are reported, never silently dropped.

## Eras

`eras.py` parameterises the same engine for Ancient, Medieval, Industrial, Modern and Future: calendar, starting technology, start-up cost and wages, the names of trades and buildings, the renderer's building style, which shocks are possible, and the context line given to models.

## The app

`app.py` is a single Streamlit script. The **World** page is an `st.fragment` that reruns itself on a timer (stepping a private world when playing; the public village is stepped by its own thread). The 3D scene (`scene.py`, three.js) is an iframe that never re-mounts; it polls a JSON snapshot the app writes to `static/world_<session>.json` every tick and animates between snapshots. `iso.py` is a lighter canvas fallback.

**Modes.** A *private world* lives in one browser session; its user is god of everything. The *public village* is one `World` held in `st.cache_resource`, ticking on a daemon thread under `world.lock`; every render of it takes the lock.

**Roles.** `IS_GOD` is true in a private world, or in the public village after the `ADMIN_PASSWORD` login (on a production server with no password set, nobody is god). Gods control play, pace, shocks, decrees and the host brain. Anyone can watch. A **steward** is someone holding a claim token for a citizen they moved in.

## Persistence

`persistence.py` exposes one `Store` interface with Supabase and SQLite implementations. A `Recorder` attached to the public village flushes new events, thoughts and metrics every tick and a full pickled snapshot every N days. On boot the village restores the latest snapshot, re-attaches sponsored brains (only for residents who opted to store an encrypted key), and primes the recorder so history isn't duplicated. Snapshots are HMAC-signed with `APP_SECRET`; unsigned or mismatched snapshots are refused when a secret is set.

## Module map

| File | Role |
|---|---|
| `src/civilisation/models.py` | dataclasses: Citizen, Business, Movement, Policy, Memory, Relationship, WorldEvent |
| `world.py` | World: state, stepping, emit, brain gate, adopt, save/load, queries |
| `systems/*.py` | the five daily systems |
| `personality.py` · `eras.py` · `names.py` · `terrain.py` | flavour and parameters |
| `brains.py` · `llm.py` · `providers.py` | cognition contract, LLM brain and narrator, provider backends |
| `commands.py` · `presets.py` · `person.py` | decree language, shock catalogue, steward actions |
| `chronicle.py` · `experiments.py` | documentary generator, scenario runner |
| `scene.py` · `iso.py` | renderers |
| `persistence.py` · `security.py` | store, recorder, signing, escaping, URL policy, limiters |
| `app.py` · `cli.py` | Streamlit app, command line |
| `tests/test_sim.py` | 21 tests |
