#!/usr/bin/env python
"""New Haven command line.

  python cli.py run --years 20 --seed 42            # run and print the chronicle
  python cli.py run --years 10 --inject 3:automation --inject 6:pandemic
  python cli.py experiment baseline automation --seeds 8 --years 15
  python cli.py bio --seed 42 --years 5 --citizen 17
  python cli.py run --years 5 --llm --llm-threshold 0.8 --llm-max-calls 50
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from civilisation import World, chronicle_text
from civilisation.experiments import SCENARIOS, compare, summary, ascii_table
from civilisation.systems.disasters import INJECTABLE


def build_world(a):
    brain = None
    if a.llm:
        from civilisation.llm import LLMBrain
        brain = LLMBrain(threshold=a.llm_threshold, max_calls=a.llm_max_calls, verbose=a.verbose)
    return World(seed=a.seed, population=a.population, brain=brain)


def cmd_run(a):
    w = build_world(a)
    schedule = sorted((int(s.split(":")[0]) * 365, s.split(":")[1]) for s in a.inject)
    t0 = time.time()
    total = a.years * 365
    for day, name in schedule:
        w.step(min(day, total) - w.day)
        w.inject(name)
        print(f"⚡ injected {name} on day {w.day}", file=sys.stderr)
    w.step(total - w.day)
    print(chronicle_text(w))
    print(f"\n({time.time()-t0:.1f}s, {w.day/365:.0f} years, brain calls {w.brain_calls})", file=sys.stderr)
    if a.llm:
        print(w.brain.stats(), file=sys.stderr)
    if a.narrate:
        from civilisation.llm import narrate
        print("\n\n# Narration\n")
        print(narrate(w))
    if a.save:
        w.save(a.save)
        print(f"saved to {a.save}", file=sys.stderr)


def cmd_bio(a):
    w = build_world(a)
    w.step(a.years * 365)
    cid = a.citizen or max(w.alive(), key=lambda c: len(c.memories)).id
    print(w.biography(cid))


def cmd_experiment(a):
    df = compare(a.scenarios, seeds=range(a.seeds), years=a.years, population=a.population, workers=a.workers)
    print(summary(df).to_string())
    print(ascii_table(df))
    if a.csv:
        df.to_csv(a.csv, index=False)
        print(f"raw results → {a.csv}")


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--seed", type=int, default=42)
p.add_argument("--population", type=int, default=100)
p.add_argument("--years", type=int, default=10)
p.add_argument("--llm", action="store_true", help="use the Claude brain for important events")
p.add_argument("--llm-threshold", type=float, default=0.7)
p.add_argument("--llm-max-calls", type=int, default=100)
p.add_argument("-v", "--verbose", action="store_true")
sub = p.add_subparsers(dest="cmd", required=True)
r = sub.add_parser("run", help="run one world and print its chronicle")
r.add_argument("--inject", action="append", default=[], metavar="YEAR:NAME", help=f"one of: {', '.join(INJECTABLE)}")
r.add_argument("--narrate", action="store_true", help="also write the documentary with Claude")
r.add_argument("--save", help="pickle the world to this path")
r.set_defaults(fn=cmd_run)
b = sub.add_parser("bio", help="print one citizen's biography")
b.add_argument("--citizen", type=int)
b.set_defaults(fn=cmd_bio)
e = sub.add_parser("experiment", help="compare scenarios over many seeds")
e.add_argument("scenarios", nargs="+", choices=list(SCENARIOS))
e.add_argument("--seeds", type=int, default=8)
e.add_argument("--workers", type=int, default=4)
e.add_argument("--csv")
e.set_defaults(fn=cmd_experiment)

if __name__ == "__main__":
    args = p.parse_args()
    args.fn(args)
