"""Animals: tame ones that live with people, wild ones in the hills, and visitors' own.

An animal eats, roams, breeds, ages and dies; tame ones follow and bond with their person;
predators hunt the herds, the deer and — when hungry and bold enough — people; people hunt
them back. Animals feel things too, and react to what happens around them through the same
six-option loaded roll, with instincts instead of plans.
"""
from __future__ import annotations
import numpy as np
from ..models import Animal
from .. import terrain

SPECIES = {
    #            wild?  predator  lifespan  danger  food/day (tame herds feed the village)
    "dog":      dict(wild=False, predator=False, life=13, danger=0.05, feeds=0.0, emoji="🐕"),
    "cat":      dict(wild=False, predator=False, life=15, danger=0.0, feeds=0.0, emoji="🐈"),
    "horse":    dict(wild=False, predator=False, life=28, danger=0.02, feeds=0.0, emoji="🐎"),
    "cow":      dict(wild=False, predator=False, life=20, danger=0.01, feeds=0.8, emoji="🐄"),
    "sheep":    dict(wild=False, predator=False, life=12, danger=0.0, feeds=0.5, emoji="🐑"),
    "goat":     dict(wild=False, predator=False, life=15, danger=0.01, feeds=0.5, emoji="🐐"),
    "elephant": dict(wild=True, predator=False, life=60, danger=0.08, feeds=0.0, emoji="🐘"),
    "deer":     dict(wild=True, predator=False, life=15, danger=0.01, feeds=0.0, emoji="🦌"),
    "bird":     dict(wild=True, predator=False, life=10, danger=0.0, feeds=0.0, emoji="🦅"),
    "wolf":     dict(wild=True, predator=True, life=12, danger=0.25, feeds=0.0, emoji="🐺"),
    "bear":     dict(wild=True, predator=True, life=25, danger=0.4, feeds=0.0, emoji="🐻"),
    "tiger":    dict(wild=True, predator=True, life=18, danger=0.55, feeds=0.0, emoji="🐅"),
    "lion":     dict(wild=True, predator=True, life=16, danger=0.5, feeds=0.0, emoji="🦁"),
}
HABITAT = {   # who lives around each village
    "sky":   ["goat", "wolf", "bear", "bird", "deer", "dog", "horse"],
    "air":   ["horse", "sheep", "bird", "deer", "dog", "cat", "wolf"],
    "earth": ["cow", "deer", "bear", "wolf", "dog", "sheep", "cat"],
    "fire":  ["goat", "lion", "tiger", "dog", "cat", "horse", "bird"],
    "water": ["cow", "elephant", "bird", "cat", "dog", "tiger", "sheep"],
}
NAMES = ["Ash", "Bramble", "Clover", "Dusk", "Ember", "Fern", "Grit", "Hazel", "Ivy", "Juniper", "Kestrel", "Lark", "Moss", "Nettle",
         "Oak", "Pip", "Quill", "Rook", "Sorrel", "Thistle", "Umber", "Vale", "Wren", "Yarrow", "Bolt", "Storm", "Tide", "Cinder", "Gale", "Stone"]
CAP_PER_SPECIES = 8


def _name(world, species):
    return f"{world.rng.choice(NAMES)} the {species}"


def _wild_spot(world, idx):
    v = world.villages[idx]
    tiles = world.tiles([terrain.FOREST, terrain.ROCK, terrain.GRASS, terrain.SNOW, terrain.ASH, terrain.SAND], idx)
    cx, cy = v.centre
    far = [t for t in tiles if abs(t[0] - cx) + abs(t[1] - cy) > 7]
    return world.rng.choice(far or tiles or [v.centre])


def new_animal(world, species: str, idx: int, owner=None, name: str = "", sex: str = "", age: int = None,
               temperament: dict = None, sponsor: str = "", backstory: str = "") -> Animal:
    rng = world.rng
    spec = SPECIES[species]
    age = rng.randint(1, max(2, spec["life"] // 2)) if age is None else int(age)
    wild = spec["wild"] and owner is None
    home = _wild_spot(world, idx) if wild else (owner.home if owner else world.villages[idx].centre)
    t = temperament or {}
    a = Animal(id=world._new_id(), name=name or _name(world, species), species=species, sex=sex or rng.choice("FM"),
               born_day=world.day - age * 365 - rng.randint(0, 300), village=idx, home=home, pos=home,
               temperament={k: float(np.clip(t.get(k, rng.gauss(0.5, 0.18)), 0.02, 0.98)) for k in ("boldness", "aggression", "loyalty", "curiosity")},
               owner_id=owner.id if owner else None, bond=0.4 if owner else 0.0, wild=wild, sponsor=sponsor, backstory=backstory)
    if spec["predator"]:
        a.temperament["aggression"] = max(a.temperament["aggression"], 0.45)
    world.animals[a.id] = a
    return a


def seed(world):
    rng = world.rng
    for v in world.villages:
        with world.at(v.idx):
            people = world.adults()
            kinds = HABITAT[v.element]
            tame = [k for k in kinds if not SPECIES[k]["wild"]]
            wild = [k for k in kinds if SPECIES[k]["wild"]]
            for _ in range(5):
                owner = rng.choice(people) if people else None
                new_animal(world, rng.choice(tame), v.idx, owner=owner)
            for _ in range(6):
                new_animal(world, rng.choice(wild), v.idx)


def alive_in(world, idx):
    return [a for a in world.animals.values() if a.alive and a.village == idx]


def _step_towards(a, target, world, n=2):
    x, y = a.pos
    tx, ty = target
    x += int(np.sign(tx - x)) * min(n, abs(tx - x))
    y += int(np.sign(ty - y)) * min(n, abs(ty - y))
    a.pos = (int(np.clip(x, 0, world.width - 1)), int(np.clip(y, 0, world.height - 1)))


def daily(world):
    rng = world.rng
    for a in list(world.animals.values()):
        if not a.alive:
            continue
        spec = SPECIES[a.species]
        v = world.villages[a.village]
        for e in list(a.emotions):
            a.emotions[e] *= 0.85
            if a.emotions[e] < 0.02:
                del a.emotions[e]
        a.hunger = min(1.0, a.hunger + (0.05 if spec["predator"] else 0.03))
        owner = world.citizens.get(a.owner_id) if a.owner_id else None
        if owner is not None and not owner.alive:
            a.remember(world.day, f"{owner.name.split()[0]} didn't come home. I waited by the door.", "grief", 0.9, [owner.id])
            a.emotions["grief"] = 0.9
            world.emit("animals", f"{a.name} waits by the door for {owner.name}, who will not come back.", 0.35, [a.id], village=a.village)
            heirs = [world.citizens[k] for k in owner.children + ([owner.spouse_id] if owner.spouse_id else []) if k in world.citizens and world.citizens[k].alive]
            a.owner_id = heirs[0].id if heirs else None
            a.bond = 0.2 if heirs else 0.0
            owner = heirs[0] if heirs else None
        # where they go and what they do
        if owner is not None and not a.wild:
            a.bond = min(1.0, a.bond + 0.002 * (0.5 + a.temperament["loyalty"]))
            target = owner.pos if rng.random() < 0.6 + 0.3 * a.bond else owner.home
            _step_towards(a, (target[0] + rng.randint(-1, 1), target[1] + rng.randint(-1, 1)), world, 3)
            a.hunger = max(0.0, a.hunger - 0.08)
            a.doing = "following " + owner.name.split()[0] if a.pos != owner.home else "at home"
            if spec["feeds"]:
                with world.at(a.village):
                    world.food += spec["feeds"]
        elif spec["predator"]:
            _prowl(world, a)
        else:
            if rng.random() < 0.5:
                _step_towards(a, (a.home[0] + rng.randint(-4, 4), a.home[1] + rng.randint(-4, 4)), world, 2)
            a.hunger = max(0.0, a.hunger - 0.06)
            a.doing = "grazing" if a.species not in ("bird", "cat", "dog") else "wandering"
            # a stray that likes someone may adopt them
            if not spec["wild"] and a.owner_id is None and rng.random() < 0.01:
                with world.at(a.village):
                    people = world.alive()
                if people:
                    a.owner_id = rng.choice(people).id
                    a.bond = 0.1
        # age, sickness, breeding
        if a.hunger > 0.97:
            a.health -= 0.02
        age = a.age_on(world.day)
        if rng.random() < max(0.0, (age - 0.7 * spec["life"]) / (spec["life"] * 365 * 0.3)) or a.health <= 0:
            die(world, a, "old age" if a.health > 0 else "hunger")
            continue
        same = [b for b in alive_in(world, a.village) if b.species == a.species]
        if a.sex == "F" and len(same) < CAP_PER_SPECIES and any(b.sex == "M" for b in same) and rng.random() < 0.003:
            owner = world.citizens.get(a.owner_id) if a.owner_id else None
            young = new_animal(world, a.species, a.village, owner=owner, age=0)
            young.wild = a.wild
            with world.at(a.village):
                world.emit("animals", f"{a.name} had young: {young.name}.", 0.25 if not a.sponsor else 0.45, [a.id], village=a.village, tone="good")


def _prowl(world, a):
    """Predators: hunt the deer and the herds; very occasionally, a person."""
    rng = world.rng
    spec = SPECIES[a.species]
    a.doing = "prowling"
    _step_towards(a, (a.home[0] + rng.randint(-6, 6), a.home[1] + rng.randint(-6, 6)), world, 3)
    if a.hunger < 0.5 or rng.random() > 0.25:
        return
    if rng.random() < 0.7:                  # most kills are game in the wild nobody names
        a.hunger = max(0.0, a.hunger - 0.6)
        return
    prey = [b for b in alive_in(world, a.village) if b.id != a.id and not SPECIES[b.species]["predator"] and b.species not in ("elephant",)]
    with world.at(a.village):
        farms = [b for b in world.open_businesses() if b.kind == "farm" and b.livestock > 0]
        people = world.alive()
        roll = rng.random()
        if prey and roll < 0.35 and len(prey) > 3:
            b = rng.choice(prey)
            die(world, b, f"killed by {a.name}")
            a.hunger = 0.0
            a.kills += 1
        elif farms and roll < 0.85:
            f = rng.choice(farms)
            f.livestock -= 1
            a.hunger = 0.1
            a.kills += 1
            world.add_fx("attack", f.x, f.y, days=1)
            world.emit("animals", f"A {a.species} took an animal from {f.name}'s herd in the night.", 0.35,
                       [f.owner_id] if f.owner_id else [], kind="animal_attack", tone="bad")
        elif people and rng.random() < spec["danger"] * a.temperament["aggression"] * a.hunger:
            victim = rng.choice([c for c in people if c.pos[0] != c.home[0] or rng.random() < 0.3] or people)
            victim.health -= rng.uniform(0.2, 0.7)
            a.kills += 1
            a.hunger = 0.0
            world.add_fx("attack", *victim.pos, days=2)
            if victim.health <= 0.02:
                from . import lifecycle
                world.emit("animals", f"{a.name} killed {victim.name} on the edge of {world.name}.", 0.75, [victim.id], kind="animal_attack",
                           tone="bad")
                lifecycle.die(world, victim, f"mauled by a {a.species}")
            else:
                world.emit("animals", f"{victim.name} was mauled by a {a.species} and barely escaped.", 0.6, [victim.id], kind="animal_attack", tone="bad")


def die(world, a, cause):
    a.alive = False
    a.died_day = world.day
    a.cause_of_death = cause
    if a.sponsor or a.owner_id:
        owner = world.citizens.get(a.owner_id) if a.owner_id else None
        with world.at(a.village):
            world.emit("animals", f"{a.name} died ({cause}).", 0.5 if a.sponsor else 0.3, [owner.id] if owner and owner.alive else [a.id],
                       tone="bad", kind="death" if owner else "")


def hunt(world, c):
    """A person goes hunting. Deer feed the family; a bear might feed on the hunter."""
    rng = world.rng
    game = [a for a in alive_in(world, c.village) if a.wild]
    if not game or rng.random() < 0.4:
        return
    a = rng.choice(game)
    spec = SPECIES[a.species]
    if spec["predator"] and rng.random() < spec["danger"] * (1.2 - c.health):
        c.health -= rng.uniform(0.2, 0.6)
        a.emotions["anger"] = 0.8
        if c.health <= 0.02:
            from . import lifecycle
            world.emit("animals", f"{c.name} went hunting and was killed by {a.name}.", 0.7, [c.id], kind="animal_attack", tone="bad")
            lifecycle.die(world, c, f"killed by a {a.species} while hunting")
        else:
            world.emit("animals", f"{c.name} went after {a.name} and came home torn and bleeding.", 0.5, [c.id], kind="animal_attack", tone="bad")
        return
    die(world, a, f"hunted by {c.name}")
    world.food += 25 if a.species in ("deer", "elephant", "bear") else 10
    c.hunger = 0.0
    c.money += 30
    if spec["predator"] or a.species == "elephant":
        c.reputation = float(np.clip(c.reputation + 0.05, -1, 1))
        world.emit("animals", f"{c.name} killed {a.name}, the {a.species} that has been haunting the village.", 0.45, [c.id], kind="hero", tone="good")


INSTINCTS = {   # (feeling, [(what they do, relevance)])
    "threat":  ("fear", [("flee", 0.9), ("fight", 0.5), ("hide", 0.7), ("seek_owner", 0.6), ("growl", 0.5), ("freeze", 0.4)]),
    "loss":    ("grief", [("wait", 0.9), ("howl", 0.6), ("seek_owner", 0.5), ("wander", 0.4), ("refuse_food", 0.4), ("hide", 0.3)]),
    "good":    ("joy", [("play", 0.8), ("follow", 0.7), ("rest", 0.5), ("explore", 0.5), ("seek_owner", 0.4), ("howl", 0.2)]),
}
INSTINCT_LINES = {"flee": "Ran. Ran until the noise stopped.", "fight": "Bared teeth. Stood my ground.", "hide": "Hid under the cart until dark.",
                  "seek_owner": "Went looking for my person.", "growl": "Growled until they backed away.", "freeze": "Froze. Didn't breathe.",
                  "wait": "Waited by the door.", "howl": "Howled at the dark.", "wander": "Walked the old paths.", "refuse_food": "Couldn't eat.",
                  "play": "Chased my tail in the sun.", "follow": "Stayed close all day.", "rest": "Slept in a warm patch.", "explore": "Found a new smell."}


def react(world, a, ev):
    """Animals respond to events they're caught up in: instinct, weighted by temperament, rolled."""
    rng = world.rng
    kind = "loss" if ev.kind in ("death", "murdered") else ("good" if ev.tone == "good" else "threat")
    feeling, menu = INSTINCTS[kind]
    t = a.temperament
    weights = []
    for act, rel in menu:
        w = rel
        if act in ("fight", "growl"):
            w *= 0.4 + t["boldness"] + t["aggression"]
        if act in ("flee", "hide", "freeze"):
            w *= 1.4 - t["boldness"]
        if act in ("seek_owner", "follow", "wait"):
            w *= (0.3 + t["loyalty"]) * (1.5 if a.owner_id else 0.3)
        weights.append(w * rng.uniform(0.8, 1.25))
    act = rng.choices([m[0] for m in menu], weights=weights)[0]
    a.emotions[feeling] = min(1.0, a.emotions.get(feeling, 0) + 0.5)
    a.doing = act.replace("_", " ")
    line = INSTINCT_LINES.get(act, "")
    a.remember(world.day, f"{ev.text} {line}".strip(), feeling, ev.importance)
    if a.sponsor:
        world.thoughts.append({"day": world.day, "cid": a.id, "name": a.name, "text": line, "source": "instinct", "emotion": feeling,
                               "village": a.village})
        world.thoughts_total = getattr(world, "thoughts_total", 0) + 1


# ---------------------------------------------------------------- visitors' animals
def adopt(world, name: str, species: str, village: int, sponsor: str = "", backstory: str = "", temperament: dict = None, age: int = 3):
    """A visitor drops an animal into a village. Tame kinds look for a person; wild ones take to the hills."""
    from ..security import clean_text
    species = species if species in SPECIES else "dog"
    with world.lock, world.at(int(village) % len(world.villages)):
        a = new_animal(world, species, world.focus, name=clean_text(name, 40) or _name(world, species), age=age,
                       temperament=temperament, sponsor=clean_text(sponsor, 40) or "anonymous", backstory=clean_text(backstory, 400))
        world.emit("animals", f"{a.name} arrived in {world.name}" + (f", sent by {a.sponsor}" if a.sponsor != "anonymous" else "") + ".", 0.5,
                   [], kind="arrived")
        return a


def instruct(world, a, text: str) -> list:
    """What a steward can ask of an animal: go somewhere, stick with someone, go for someone, hunt, rest."""
    from ..commands import _names_in, _villages_in
    t = " " + text.lower() + " "
    done = []
    names = _names_in(world, t)
    who = names[0] if names else None
    with world.lock:
        if any(k in t for k in ("attack", "bite", "maul", "kill", "go for", "hunt down")) and who is not None:
            victim = who
            victim.health -= world.rng.uniform(0.1, 0.4) * (0.5 + SPECIES[a.species]["danger"] * 2)
            a.pos = victim.pos
            with world.at(victim.village):
                if victim.health <= 0.02:
                    from . import lifecycle
                    world.emit("animals", f"{a.name} went for {victim.name} and killed them.", 0.8, [victim.id], kind="animal_attack", tone="bad")
                    lifecycle.die(world, victim, f"mauled by {a.name}")
                else:
                    world.emit("animals", f"{a.name} went for {victim.name}.", 0.55, [victim.id], kind="animal_attack", tone="bad")
            done.append(f"went for {victim.name}")
        elif any(k in t for k in ("follow", "befriend", "stay with", "love", "adopt", "owner", "guard")) and who is not None:
            a.owner_id, a.wild = who.id, False
            a.bond = max(a.bond, 0.3)
            a.pos = who.pos
            with world.at(who.village):
                world.emit("animals", f"{a.name} has taken to following {who.name} everywhere.", 0.4, [who.id], tone="good")
            done.append(f"now follows {who.name}")
        elif "hunt" in t:
            a.hunger = 1.0
            _prowl(world, a) if SPECIES[a.species]["predator"] else None
            done.append("went hunting")
        elif any(k in t for k in ("wild", "hills", "forest", "roam", "explore", "run free")):
            a.owner_id, a.wild = None, True
            a.home = _wild_spot(world, a.village)
            done.append("took to the wild")
        vs = _villages_in(world, t)
        if vs and any(k in t for k in ("go to", "move to", "travel", "cross")):
            from ..commands import village_index
            a.village = village_index(world, vs[0])[0]
            a.home = _wild_spot(world, a.village) if a.wild else world.villages[a.village].centre
            a.pos = a.home
            done.append(f"crossed into {world.villages[a.village].name}")
        if not done:
            a.doing = "resting"
            done.append("curled up somewhere warm")
    a.remember(world.day, "My person asked something of me. " + "; ".join(done).capitalize() + ".", "hope", 0.5)
    return done
