"""Economy: production, wages, spending, prices, hiring, bankruptcy, founding, tax.

Businesses are real accounting entities: they earn revenue from citizens'
spending, pay wages from cash, and die when they run out. Nothing is scripted —
recessions, monopolies and mass unemployment emerge from these rules.
"""
from __future__ import annotations
import numpy as np
from .. import terrain
from ..models import Citizen, Business

JOB_FOR_KIND = {"farm": "farmer", "bakery": "baker", "workshop": "craftsperson", "market": "merchant",
                "mine": "miner", "tavern": "innkeeper", "school": "teacher", "clinic": "doctor"}
SITE_FOR_KIND = {"farm": terrain.FARMLAND, "mine": terrain.ROCK}
# output value per worker-day for non-food businesses
BASE_OUTPUT = {"bakery": 40, "workshop": 48, "market": 42, "mine": 45, "tavern": 32, "school": 28, "clinic": 34}
FOOD_PER_FARMER = 14.0        # food units per farmer-day at skill 0.5, tech 1
STARTUP_KINDS = ["farm", "bakery", "workshop", "market", "tavern", "mine", "clinic", "school"]
EXPORTABLE = {"workshop", "mine"}   # goods that earn money from outside the town
MAX_EMPLOYEES = 8


def pick_site(world, kind):
    target = SITE_FOR_KIND.get(kind)
    if target is not None:
        tiles = terrain.find_tiles(world.grid, target)
    else:
        tiles = terrain.find_tiles(world.grid, terrain.TOWN) + terrain.find_tiles(world.grid, terrain.GRASS)[:200]
    taken = {(b.x, b.y) for b in world.businesses.values()}
    free = [t for t in tiles if t not in taken] or tiles
    return world.rng.choice(free)


def hire(world, c: Citizen, b: Business):
    c.employer_id = b.id
    c.job = JOB_FOR_KIND[b.kind]
    c.unemployed_days = 0
    b.employees.append(c.id)
    for other in b.employees:
        if other != c.id:
            c.rel(other).kind = "colleague" if c.rel(other).kind == "acquaintance" else c.rel(other).kind


def farm_yield(world) -> float:
    """Food units one farmer grows per day right now (drought, technology)."""
    return FOOD_PER_FARMER * 0.9 * world.tech * (0.45 if world.drought_days > 0 else 1.0)


def needs_staff(b: Business, food_price: float = 0.0, world=None) -> bool:
    """A business hires only when another pair of hands would pay for itself."""
    if len(b.employees) >= MAX_EMPLOYEES:
        return False
    if b.kind == "farm" and world is not None:
        # scarcity pulls labour into food — but only while a farmer's grain is worth more than their wage
        return farm_yield(world) * food_price > b.wage * 1.1
    if b.cash < 15 * b.wage:
        return False
    if len(b.revenue_history) < 7 or len(b.employees) == 0:
        return True
    rev = float(np.mean(b.revenue_history[-14:]))
    return rev / (len(b.employees) + 1) > b.wage * 1.2


def hire_anyone(world, c: Citizen) -> bool:
    open_bs = [b for b in world.open_businesses() if needs_staff(b, world.food_price, world)]
    if not open_bs:
        return False
    # prefer nearby, cash-rich businesses
    weights = [max(0.1, b.cash) / (1 + 0.05 * (abs(b.x - c.home[0]) + abs(b.y - c.home[1]))) for b in open_bs]
    b = world.rng.choices(open_bs, weights=weights)[0]
    hire(world, c, b)
    return True


def leave_job(world, c: Citizen, reason: str = "left"):
    b = world.businesses.get(c.employer_id)
    if b and c.id in b.employees:
        b.employees.remove(c.id)
    c.employer_id = None
    c.job = "unemployed"
    c.unemployed_days = 0


def _skill_of(world, b: Business) -> float:
    if not b.employees:
        return 0.0
    return float(np.mean([world.citizens[e].skill for e in b.employees]))


def daily(world):
    rng = world.rng
    cfg = world.config
    alive = world.alive()
    adults = [c for c in alive if c.age_on(world.day) >= 18]
    laws = world.policy.laws
    demand_mult = cfg["demand_multiplier"] * (0.5 if world.recession_days > 0 else 1.0) * (1.4 if world.boom_days > 0 else 1.0) \
        * (1.2 if "tax_holiday" in laws else 1.0) * (0.7 if "quarantine" in laws else 1.0)
    striking = set(world.strike["members"]) if world.strike else set()
    drought = 0.45 if world.drought_days > 0 else 1.0

    # ---- production
    open_bs = world.open_businesses()
    food_produced = 0.0
    outputs = {}
    for b in open_bs:
        workers = [e for e in b.employees if e not in striking]
        n = len(workers)
        skill = float(np.mean([world.citizens[e].skill for e in workers])) if workers else 0.0
        eff = (0.5 + skill) * world.tech * b.productivity
        if "quarantine" in laws and b.kind in ("tavern", "market", "school"):
            n = 0                                            # shut by law
        if b.kind == "farm":
            produced = n * FOOD_PER_FARMER * eff * rng.uniform(0.85, 1.15) * drought
            herd = getattr(b, "livestock", 0)
            produced += herd * 1.2 * (0.6 if drought < 1 else 1.0)          # milk, eggs, the odd slaughter
            if herd and n and rng.random() < 0.0012 * herd and herd < 12:
                b.livestock = herd + 1
            elif herd and drought < 1 and rng.random() < 0.01:
                b.livestock = herd - 1                                      # the herd thins in a drought
            food_produced += produced
            b.inventory += produced
        else:
            outputs[b.id] = n * BASE_OUTPUT[b.kind] * eff
        b.revenue_today = 0.0
    world.food += food_produced
    world.food *= 0.995          # spoilage: grain does not keep forever

    # ---- prices: a week of reserves is "normal"
    weekly_need = max(1.0, len(alive) * 7.0)
    world.food_price = float(np.clip(3.5 * (weekly_need / max(1.0, world.food)) ** 0.5, 1.0, 12.0))
    market_price = world.food_price
    world.market_price = market_price
    if "rationing" in laws and world.treasury > 0:
        world.food_price = min(world.food_price, 4.0)
    squeeze = max(0.0, world.food_price / 3.5 - 1)      # cost-of-living pressure

    # ---- citizens eat and spend
    farms = [b for b in open_bs if b.kind == "farm"]
    farm_share = np.array([b.inventory for b in farms]) if farms else None
    goods_bs = [b for b in open_bs if b.kind != "farm"]
    food_revenue = 0.0
    for c in alive:
        age = c.age_on(world.day)
        # eat: children are fed by parents (we just charge the world's food)
        if world.food >= 1.0 and (c.money >= world.food_price or age < 18 or "rationing" in laws):
            world.food -= 1.0
            payer = c
            if age < 18 and c.parent_ids:
                p = world.citizens.get(c.parent_ids[0])
                if p and p.alive:
                    payer = p
            pay = min(payer.money, world.food_price)
            payer.money -= pay
            food_revenue += pay
            c.hunger = max(0.0, c.hunger - 0.5)
            if squeeze > 0 and c.money < 2000:
                c.happiness = max(0.0, c.happiness - 0.004 * squeeze)
                c.grievance = min(1.0, c.grievance + 0.002 * squeeze)
        else:
            c.hunger = min(1.0, c.hunger + 0.15)
        # discretionary spending → goods businesses (proximity weighted)
        if age >= 18 and goods_bs and c.money > 20:
            spend = (8 + c.money * 0.006) * demand_mult * (0.5 + 0.5 * c.happiness)
            spend = min(spend, c.money - 10)
            if spend > 0:
                c.money -= spend
                b = goods_bs[int(rng.random() * len(goods_bs))]
                b.cash += spend
                b.revenue_today += spend
                world.gdp_today += spend
    # surplus grain is exported at a floor price, so a good harvest doesn't bankrupt the farms
    surplus = world.food - weekly_need * 6
    if surplus > 0:
        world.food -= surplus
        food_revenue += surplus * 2.0
        world.gdp_today += surplus * 2.0
    if farms and farm_share is not None and farm_share.sum() > 0:
        shares = farm_share / farm_share.sum()
        for b, s in zip(farms, shares):
            b.cash += food_revenue * s
            b.revenue_today += food_revenue * s
            b.inventory = 0.0
    subsidy = (market_price - world.food_price) * max(0.0, food_revenue / max(0.01, world.food_price))
    if subsidy > 0:                      # rationing: the treasury tops farms up to the market price
        subsidy = min(subsidy, world.treasury)
        world.treasury -= subsidy
        food_revenue += subsidy
    world.food_price = market_price if "rationing" not in laws else world.food_price
    world.gdp_today += food_revenue
    # tradable goods earn export income from outside the town
    for bid, out in outputs.items():
        b = world.businesses[bid]
        if b.kind in EXPORTABLE:
            bonus = out * 0.25 * demand_mult
            b.cash += bonus
            b.revenue_today += bonus
            world.gdp_today += bonus
    # the council spends: public contracts recycle tax money into the economy
    if world.treasury > 0 and goods_bs:
        spend = world.treasury * 0.004
        world.treasury -= spend
        for _ in range(3):
            b = goods_bs[int(rng.random() * len(goods_bs))]
            b.cash += spend / 3
            b.revenue_today += spend / 3
        world.gdp_today += spend

    # ---- wages, tax, owner profit, hiring & firing
    pol = world.policy
    for b in open_bs:
        if b.kind == "farm":
            # a farmer is worth what their grain sells for; the wage follows the price of bread and the harvest
            worth = 0.6 * farm_yield(world) * world.food_price
            b.wage = max(min(b.wage, worth * 1.3), worth, cfg["base_wage"] * 0.5)
        b.revenue_history.append(b.revenue_today)
        if len(b.revenue_history) > 60:
            b.revenue_history.pop(0)
        payroll = 0.0
        for e in list(b.employees):
            c = world.citizens[e]
            if e in striking:
                continue
            wage = max(b.wage, pol.min_wage) * (0.7 + 0.6 * c.skill)
            if c.age_on(world.day) >= 65 and rng.random() < 0.01:
                retire(world, c)
                continue
            tax = wage * pol.tax_rate * (0.5 if "tax_holiday" in laws else 1.0)
            c.money += wage - tax
            c.last_wage = wage
            world.treasury += tax
            payroll += wage
            c.skill = min(1.0, c.skill + 0.00025 * (0.5 + c.education))
            c.happiness = float(np.clip(c.happiness + 0.001, 0, 1))
        public = (b.kind == "school" and pol.public_education) or (b.kind == "clinic" and pol.public_health)
        if public and world.treasury > payroll:
            world.treasury -= payroll          # the council pays public staff
        else:
            b.cash -= payroll
        profit = b.revenue_today - payroll
        if profit > 0:
            owner = world.citizens.get(b.owner_id)
            if owner and owner.alive:
                take = profit * 0.3
                owner.money += take * (1 - pol.tax_rate)
                world.treasury += take * pol.tax_rate
                b.cash -= take
            b.loss_days = max(0, b.loss_days - 1)
            if profit / max(1, len(b.employees)) > 0.5 * b.wage and rng.random() < 0.15:
                b.wage = min(b.wage * 1.03, cfg["base_wage"] * 2.2)
            if b.cash > 25 * payroll + 800 and needs_staff(b, world.food_price, world) and rng.random() < 0.15:
                unemployed = [c for c in adults if c.employer_id is None and c.age_on(world.day) < 65 and not c.infected]
                if unemployed:
                    pick = max(rng.sample(unemployed, min(4, len(unemployed))), key=lambda c: c.skill)
                    hire(world, pick, b)
                    world.emit("work", f"{pick.name} was hired at {b.name}.", 0.25, [pick.id])
                    pick.remember(world.day, f"Got a job at {b.name}.", "joy", 0.3, tag="work")
        # a business that wants staff but can't justify them at this wage lets the wage drift down
        if len(b.employees) < 4 and b.wage > cfg["base_wage"] and not needs_staff(b, world.food_price, world) and rng.random() < 0.2:
            b.wage = max(b.wage * 0.97, cfg["base_wage"])
        if profit <= 0:
            b.loss_days += 1
            if b.loss_days > 5 and rng.random() < 0.1:
                b.wage = max(b.wage * 0.95, pol.min_wage, cfg["base_wage"] * 0.5)
            if b.loss_days > 15 and len(b.employees) > 1 and rng.random() < 0.2:
                victim = min((world.citizens[e] for e in b.employees if e != b.owner_id), key=lambda c: c.skill, default=None)
                if victim:
                    leave_job(world, victim, "fired")
                    world.emit("work", f"{victim.name} was laid off from {b.name}.", 0.45, [victim.id, b.owner_id] if b.owner_id else [victim.id])
                    b.wage = max(b.wage * 0.95, pol.min_wage, cfg["base_wage"] * 0.5)
            if b.cash < -max(300.0, 20 * payroll):
                bankrupt(world, b)

    # ---- unemployed: job search, welfare, founding
    for c in adults:
        if c.age_on(world.day) >= 65:
            if pol.pension > 0 and world.treasury > pol.pension:
                world.treasury -= pol.pension
                c.money += pol.pension
            continue
        if c.employer_id is not None and rng.random() < (0.05 if world.food_price > 6 else 0.01):
            # look for a better-paid job (everyone looks harder when bread is dear)
            current = world.businesses[c.employer_id]
            better = [b for b in world.open_businesses() if b.id != current.id and b.wage > current.wage * 1.15 and needs_staff(b, world.food_price, world)]
            if better:
                b = max(better, key=lambda b: b.wage)
                leave_job(world, c, "switched")
                hire(world, c, b)
                c.remember(world.day, f"Left {current.name} for better pay at {b.name}.", "hope", 0.3, tag="work")
        if c.employer_id is None:
            c.unemployed_days += 1
            c.happiness = float(np.clip(c.happiness - 0.003, 0, 1))
            if pol.welfare > 0 and world.treasury > pol.welfare:
                world.treasury -= pol.welfare
                c.money += pol.welfare
            if "public_works" in laws and world.treasury > cfg["base_wage"]:
                pay = cfg["base_wage"] * 0.7
                world.treasury -= pay
                c.money += pay
                c.happiness = min(1, c.happiness + 0.004)      # work, even mending roads, is dignity
        if "poor_relief" in laws and c.hunger > 0.4 and world.treasury > 8:
            world.treasury -= 8
            c.money += 8
            if rng.random() < 0.04:
                hire_anyone(world, c)
            elif world.food_price > 5 and c.hunger > 0.3:
                c.hunger = max(0.0, c.hunger - 0.15)     # forage on the commons
        # entrepreneurship
        ambition = c.personality["openness"] * 0.5 + c.personality["conscientiousness"] * 0.5
        wants = c.goal == "start a business" or c.employer_id is None
        scarce = getattr(world, "market_price", world.food_price) > 6
        p_found = 0.004 * (6.0 if scarce else 1.0) * (2.0 if c.employer_id is None else 1.0)
        cost = cfg["startup_cost"] * (0.5 if scarce else 1.0)          # a farm on the commons is cheap to start when bread is dear
        if wants and c.money > cost * 1.2 and ambition > (0.35 if scarce else 0.5) and rng.random() < p_found \
                and len(world.open_businesses()) < max(12, len(alive) // 6):
            kind = "farm" if scarce and rng.random() < 0.8 else _best_kind(world)
            c.money -= cost
            if c.employer_id is not None:
                leave_job(world, c)
            b = world.found_business(c, kind)
            c.goal_progress = 1.0 if c.goal == "start a business" else c.goal_progress
            world.emit("economy", f"{c.name} founded {b.name}.", 0.5, [c.id])
            c.remember(world.day, f"I opened {b.name} with my savings.", "pride", 0.7, tag="economy")

    # ---- no farms at all: the council opens one on the commons before the town starves
    if not any(b.kind == "farm" for b in world.open_businesses()) and world.treasury > 500 and adults:
        steward = max((c for c in adults if c.employer_id is None), key=lambda c: c.skill, default=rng.choice(adults))
        world.treasury -= 500
        if steward.employer_id is not None:
            leave_job(world, steward)
        b = world.found_business(steward, "farm")
        b.cash = 1500.0
        world.emit("economy", f"With no farm left standing, the council opened {b.name} on the commons and put {steward.name} in charge.", 0.7, [steward.id])
    # ---- treasury interest-free overdraft limit: austerity if broke
    if world.treasury < -5000:
        world.policy.welfare = 0.0
        world.policy.pension = 0.0


def _best_kind(world):
    """Founders copy what's profitable, with a bit of random novelty."""
    open_bs = world.open_businesses()
    if world.rng.random() < 0.3 or not open_bs:
        return world.rng.choice(STARTUP_KINDS)
    counts = {k: 0 for k in STARTUP_KINDS}
    rev = {k: 0.0 for k in STARTUP_KINDS}
    for b in open_bs:
        counts[b.kind] += 1
        rev[b.kind] += float(np.mean(b.revenue_history[-30:])) if b.revenue_history else 0
    score = {k: (rev[k] / max(1, counts[k])) / (1 + counts[k]) for k in STARTUP_KINDS}
    if getattr(world, "market_price", world.food_price) > 5:   # food crisis → farms
        score["farm"] *= 3
    return max(score, key=score.get)


def retire(world, c: Citizen):
    b = world.businesses.get(c.employer_id)
    leave_job(world, c)
    c.job = "retired"
    c.goal = "enjoy retirement"
    world.emit("life", f"{c.name} retired from {b.name if b else 'work'} at {c.age_on(world.day)}.", 0.3, [c.id])
    c.remember(world.day, "Retired. Strange to wake up with nowhere to be.", "hope", 0.4, tag="work")


def bankrupt(world, b: Business):
    b.alive = False
    b.closed_day = world.day
    staff = [world.citizens[e] for e in b.employees]
    for c in staff:
        leave_job(world, c, "bankrupt")
    b.employees = []
    owner = world.citizens.get(b.owner_id)
    ids = [c.id for c in staff]
    world.emit("economy", f"{b.name} went bankrupt after {world.day - b.founded_day} days; {len(staff)} people lost their jobs.",
               0.55 + 0.03 * len(staff), ([owner.id] if owner else []) + ids[:2])
    for c in staff:
        c.remember(world.day, f"{b.name} collapsed and I lost my job.", "fear", 0.6, tag="work")
    if owner and owner.alive:
        owner.remember(world.day, f"My business, {b.name}, failed.", "shame", 0.8, tag="economy")
        owner.reputation -= 0.2
