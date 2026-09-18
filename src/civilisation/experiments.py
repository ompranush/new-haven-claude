"""Experiment platform: run a scenario across many seeds and compare distributions.

    from civilisation.experiments import run, compare, SCENARIOS
    df = run("automation", seeds=range(10), years=20)
    print(compare(["baseline", "automation"], seeds=range(10), years=20))

Scenarios are functions (world_kwargs, schedule) — schedule is a list of
(day, injection_name, kwargs) applied at those days.
"""
from __future__ import annotations
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Dict, Iterable, List, Tuple
import numpy as np
import pandas as pd

from .world import World

Schedule = List[Tuple[int, str, dict]]

SCENARIOS: Dict[str, Callable[[], Tuple[dict, Schedule]]] = {
    "baseline": lambda: ({}, []),
    "high_inequality": lambda: ({"config": {"initial_inequality": 1.05}}, []),
    "equal_start": lambda: ({"config": {"initial_inequality": 6.0}}, []),
    "universal_education": lambda: ({"config": {"education_access": 1.0}}, []),
    "no_school": lambda: ({"config": {"education_access": 0.0}}, []),
    "automation": lambda: ({}, [(365 * 3, "automation", {"share": 0.3})]),
    "longevity_x2": lambda: ({"config": {"longevity": 2.0}}, []),
    "declining_births": lambda: ({"config": {"fertility": 0.4}}, []),
    "baby_boom": lambda: ({"config": {"fertility": 2.0}}, []),
    "pandemic_y2": lambda: ({}, [(365 * 2, "pandemic", {})]),
    "great_recession": lambda: ({}, [(365 * 2, "recession", {"days": 365})]),
    "no_shocks": lambda: ({"config": {"random_shocks": False}}, []),
    "open_borders": lambda: ({}, [(365 * y, "immigration", {"n": 15}) for y in range(1, 30)]),
    "expensive_startups": lambda: ({"config": {"startup_cost": 4000.0}}, []),
}

METRICS = ["population", "median_wealth", "avg_wealth", "gini", "unemployment", "happiness", "grievance",
           "businesses", "avg_education", "movements", "tech"]


def run_one(args) -> dict:
    scenario, seed, years, population = args
    kwargs, schedule = SCENARIOS[scenario]()
    w = World(seed=seed, population=population, **kwargs)
    schedule = sorted(schedule)
    total = years * 365
    for day, name, kw in schedule:
        if day > total:
            break
        w.step(day - w.day)
        w.inject(name, **kw)
    w.step(total - w.day)
    row = {k: w.history[-1][k] for k in METRICS}
    row.update(scenario=scenario, seed=seed, deaths=sum(1 for c in w.citizens.values() if not c.alive),
               elections_lost_by_incumbent=sum(1 for e in w.chronicle if "took power" in e.text),
               strikes=sum(1 for e in w.chronicle if "went on strike" in e.text),
               parties=sum(1 for m in w.movements.values() if m.is_party),
               collapsed=int(row["population"] == 0))
    return row


def run(scenario: str, seeds: Iterable[int] = range(10), years: int = 20, population: int = 100,
        workers: int = 4) -> pd.DataFrame:
    jobs = [(scenario, s, years, population) for s in seeds]
    # "fork" so workers inherit the loaded modules instead of re-importing the caller's
    # main script (which, under Streamlit, would boot a whole app per worker).
    if workers > 1 and "fork" in mp.get_all_start_methods():
        with ProcessPoolExecutor(workers, mp_context=mp.get_context("fork")) as ex:
            rows = list(ex.map(run_one, jobs))
    else:
        rows = [run_one(j) for j in jobs]
    return pd.DataFrame(rows)


def compare(scenarios: List[str], seeds: Iterable[int] = range(10), years: int = 20, population: int = 100,
            workers: int = 4) -> pd.DataFrame:
    seeds = list(seeds)
    frames = [run(s, seeds, years, population, workers) for s in scenarios]
    df = pd.concat(frames)
    return df


def summary(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in METRICS + ["deaths", "strikes", "parties", "collapsed"] if c in df]
    return df.groupby("scenario")[cols].agg(["median", "std"]).round(2)


def ascii_table(df: pd.DataFrame, metrics=("population", "median_wealth", "gini", "unemployment", "happiness", "grievance", "parties")) -> str:
    med = df.groupby("scenario")[list(metrics)].median()
    lines = []
    w = max(len(s) for s in med.index) + 2
    for m in metrics:
        mx = med[m].max() or 1
        lines.append(f"\n{m}")
        for s, v in med[m].items():
            bar = "█" * int(round(24 * v / mx)) if mx else ""
            lines.append(f"  {s:<{w}} {bar:<24} {v:,.2f}")
    return "\n".join(lines)
