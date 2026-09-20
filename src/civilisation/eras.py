"""Eras: when the civilisation exists. Same engine, different clothes and constraints.

An era sets the calendar, starting technology and prices, what the trades and
buildings are called, the building style the renderer uses, which shocks make
sense, and the context the language models are given.
"""
from __future__ import annotations

ERAS = {
    "ancient": dict(
        label="Ancient", start_year=-800, calendar="{y} BC|{y} AD", tech=0.6, startup_cost=800, base_wage=24, style="ancient",
        kinds={"farm": "Farm", "bakery": "Bakehouse", "workshop": "Potter's Yard", "market": "Agora", "mine": "Quarry", "tavern": "Wine House", "school": "Academy", "clinic": "Temple of Healing"},
        jobs={"farmer": "farmer", "baker": "baker", "craftsperson": "potter", "merchant": "trader", "miner": "quarryman", "innkeeper": "vintner", "teacher": "philosopher", "doctor": "healer"},
        blurb="a bronze-and-iron age settlement of farmers, potters and traders, ruled by a council of elders",
        shocks_off={"automation", "automation_wave", "bank_failure", "inflation", "breakthrough", "school_reform", "cure_discovered"},
    ),
    "medieval": dict(
        label="Medieval", start_year=1250, calendar="{y} AD", tech=1.0, startup_cost=1000, base_wage=30, style="medieval",
        kinds={"farm": "Farm", "bakery": "Bakery", "workshop": "Workshop", "market": "Market", "mine": "Mine", "tavern": "Tavern", "school": "School", "clinic": "Clinic"},
        jobs={"farmer": "farmer", "baker": "baker", "craftsperson": "craftsperson", "merchant": "merchant", "miner": "miner", "innkeeper": "innkeeper", "teacher": "teacher", "doctor": "doctor"},
        blurb="a river town of farms, mills and guild workshops, with a council in the square",
        shocks_off={"automation", "automation_wave", "bank_failure"},
    ),
    "industrial": dict(
        label="Industrial", start_year=1840, calendar="{y}", tech=1.6, startup_cost=2000, base_wage=34, style="industrial",
        kinds={"farm": "Farm", "bakery": "Bakery", "workshop": "Factory", "market": "Emporium", "mine": "Colliery", "tavern": "Public House", "school": "School", "clinic": "Infirmary"},
        jobs={"farmer": "farmer", "baker": "baker", "craftsperson": "factory hand", "merchant": "shopkeeper", "miner": "collier", "innkeeper": "publican", "teacher": "schoolmaster", "doctor": "physician"},
        blurb="a mill town of smokestacks, collieries and railway sidings, with a council of mill-owners and a growing union hall",
        shocks_off={"witch_hunt", "royal_visit"},
    ),
    "modern": dict(
        label="Modern", start_year=1998, calendar="{y}", tech=2.6, startup_cost=4000, base_wage=40, style="modern",
        kinds={"farm": "Farm", "bakery": "Café", "workshop": "Tech Workshop", "market": "Supermarket", "mine": "Quarry", "tavern": "Bar", "school": "School", "clinic": "Clinic"},
        jobs={"farmer": "farmer", "baker": "barista", "craftsperson": "technician", "merchant": "retail manager", "miner": "quarry worker", "innkeeper": "bar owner", "teacher": "teacher", "doctor": "doctor"},
        blurb="a small modern town with a supermarket, a clinic, a tech workshop and an elected council",
        shocks_off={"witch_hunt", "royal_visit", "conscription", "locusts"},
    ),
    "future": dict(
        label="Future", start_year=2140, calendar="{y}", tech=4.5, startup_cost=6000, base_wage=48, style="future",
        kinds={"farm": "Hydroponics Farm", "bakery": "Food Lab", "workshop": "Fabrication Bay", "market": "Exchange", "mine": "Extraction Rig", "tavern": "Lounge", "school": "Learning Hub", "clinic": "Med Bay"},
        jobs={"farmer": "hydroponics tech", "baker": "food designer", "craftsperson": "fabricator", "merchant": "exchange broker", "miner": "rig operator", "innkeeper": "host", "teacher": "mentor", "doctor": "medic"},
        blurb="a settlement of hydroponic farms, fabrication bays and med bays under a governing assembly, where machines do much of the work",
        shocks_off={"witch_hunt", "royal_visit", "conscription", "locusts", "harsh_winter"},
    ),
}


def era(world) -> dict:
    return ERAS.get(world.config.get("era", "medieval"), ERAS["medieval"])


def display_year(world) -> str:
    e = era(world)
    y = e["start_year"] + world.year - 1
    if "|" in e["calendar"]:
        bc, ad = e["calendar"].split("|")
        return bc.format(y=-y) if y < 0 else ad.format(y=y)
    return e["calendar"].format(y=y)


def kind_label(world, kind: str) -> str:
    return era(world)["kinds"].get(kind, kind.title())


def job_label(world, job: str) -> str:
    return era(world)["jobs"].get(job, job)


def context_line(world) -> str:
    e = era(world)
    return f"It is {display_year(world)}. {world.name} is {e['blurb']}."
