# New Haven — Architecture

> v0.3: five elemental villages on one river, the behaviour engine, crime, war, magic, animals and an animated 3D realm.
> The sections below "The realm" describe the single-town systems that now run once per village.

## The realm

`World` holds five `Village`s (`realm.py`: sky, air, earth, fire, water — upstream to downstream) on one 90×60 map
(`terrain.generate_realm`). Each village owns what used to be global: `policy`, `treasury`, `food`, `food_price`,
`tech`, `history`, `strike`, `pandemic`… `World.focus` names one village, and properties on `World` delegate those
names to it, while `alive()`, `adults()`, `open_businesses()` and `movements_here()` return only that village's. So
the economy, social, lifecycle, politics and disasters systems — written for one town — run unchanged once per village
inside `with world.at(idx):`. `alive_all()` / `open_businesses_all()` see the whole realm. Citizens, businesses and
movements carry a `village`; events carry `village`, a situation `kind` and a `secret` flag (only god sees secrets).

Each simulated day: `river.daily` (flow and shares) → per village: lifecycle, economy, social, politics, disasters,
`behaviour.daily` (feelings fade, ambitions, pressures, grudges), `war.village_daily` (stipends, offices, tribute, the
council's weekly roll) → realm: `war.daily` (battles), `magic.daily` (circles, awakenings, resurrections),
`animals.daily`.

## The behaviour engine (`behaviour.py`)

1. **Situations.** `classify(world, citizen, event)` reads an event as one of ~55 situations (insulted, humiliated,
   robbed, spouse unfaithful, loved one murdered, water cut, war declared, occupied, awakening… plus one *ambition*
   situation per goal). Each lists responses with a relevance 0..1.
2. **Feelings.** `stir()` raises a feeling by an amount scaled by temperament (`disposition()`: temper, conscience,
   boldness, vengefulness, warmth, drive); `fade()` lets it ebb at a temperament-dependent rate. Bands: calm, stirred,
   heated, boiling. Every act has a band of feeling where it is natural.
3. **Six and a die.** `menu_for()` draws six responses at ≥10% relevance, weighted by relevance (so the menu itself
   varies); fallbacks (holiday, singing…) enter only when fewer than six fit. `_fit()` loads each face by traits, band,
   goal (×1.8–3.2 when the act serves it), conscience (crimes are never zero), history with the other person, hunger and
   roots (people with jobs and families rarely emigrate). `decide()` rolls; `perform()` runs the act. The six options and
   the face are kept on the thought (`world.thoughts[i]["options"|"face"]`) and shown in the app.
4. **Goals.** Every day each free adult may take an initiative toward their goal through the same roll
   (`ambition_<tag>` situations). LLM minds are shown the six options and choose one; off-menu answers fall back to the die.

## Conflict (`systems/crime.py`, `river.py`, `war.py`, `magic.py`)

Crimes are acts like any other. `crime.commit` records them, lets the victim react, and gives the village watch a chance
(`police_strength`: officers per head × skill × trust × curfew). Caught: fines and jail scaled by the government's
authority, exile, hanging; corrupt officers take bribes. Water: each village takes its need plus `diversion` of the
flow; shortfalls hurt health and push `tension`/`grudges` toward whoever upstream diverted most. Councils roll weekly on
wait/parley/threaten/raid/war/tribute; wars fight a battle every nine days at the border (real deaths, morale); losers
surrender (tribute, water terms) or collapse into occupation; empty villages fall to ruin. Secret mages (3–5% at
founding, then earned) add strength in battle and reveal themselves; an occupied village's circle rises when strong
enough against the garrison, and a fallen village's scattered mages lead its people home.

## Renderer (`scene.py`) and models (`static/models/`)

three.js, served from jsdelivr; the iframe polls `static/world_<session>.json` (`iso.world_payload`). The ~60 people
nearest the camera are rigged figures (CC0 Quaternius mannequin, 22 clips) chosen by state — walking, talking,
working, fighting, dancing, mourning, casting, sitting in the cells; everyone else is an instanced figure. Animals use
animated CC0 models (CC-BY Poly models for bear, tiger, lion, elephant, eagle). `world.fx` entries (meteor, fire,
lightning, tornado, quake, flood, riot, raid, battle, spells…) become effects; `world.set_tile` changes (ash, ruins,
dams, craters) rebuild the terrain. The camera follows the selected person, or glides to a village, front or dam.
Model files are trimmed with `tools/repack_glb.py`; credits in `static/models/CREDITS.md`.


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

## Persistence — what is a record and what is a save-game

Two very different things go to the store, and confusing them is what nearly took the database down:

- **The log** (`events`, `thoughts`, `metrics`) is the permanent record and is **append-only**: each flush writes only the rows created since the last one. Nothing is ever rewritten. Every interaction and every inner voice is kept by default (`STORE_MIN_IMPORTANCE=0`). The world's in-memory lists are rolling windows, so the recorder counts lifetime totals (`events_total`, `thoughts_total`) rather than list lengths, and reports `dropped` if a window ever wraps before a flush — that number must stay at zero.
- **The snapshot** is a save-game, not a record: the whole world, pickled, gzipped and signed. It exists so a restart resumes the village rather than restarting it. It is written at most once per `SNAPSHOT_INTERVAL_SECONDS` **and** per `SNAPSHOT_EVERY_DAYS`, and refused above `MAX_SNAPSHOT_MB`. Losing one costs at most the minutes since the last; the log still has everything that happened.

Two things bound the world's size. `max_relationships` (default 150 — Dunbar's number) caps how many people
anyone can hold in mind, keeping the social graph linear in population rather than quadratic; family and
spouses are never the ties dropped. And because the snapshot is a whole-world copy, `World.prune()` runs each simulated year, stripping memories and relationships from the dead, forgetting stale acquaintances among the living, capping the in-memory history and chronicle, and deleting long-dead citizens that nothing references. Without it, relationships grow with the square of the population (157k by year 60) and the snapshot grows without limit.

**Storage cost scales with simulated time, not real time.** A village produces ~2.2 log rows per simulated day, so rows per real day = 2.2 × (86400 / `TICK_SECONDS`). At `TICK_SECONDS=10` that is ~19k rows/day (~4 MB); at 30 it is ~6k (~1.4 MB). Slowing the clock is the cheapest way to make a complete record affordable.

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
| `World.heirs_of` / `inherit` / `adopt_relative` | succession: a steward's line passes to a child (or a relative) with the same claim token |
| `chronicle.py` · `experiments.py` | documentary generator, scenario runner |
| `scene.py` · `iso.py` | renderers |
| `persistence.py` · `security.py` | store, recorder, signing, escaping, URL policy, limiters |
| `app.py` · `cli.py` | Streamlit app, command line |
| `tests/test_sim.py` | 21 tests |
