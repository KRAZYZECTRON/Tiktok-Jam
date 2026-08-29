"""Sweep rank()'s weights over the full 200-session public set.

Loading the catalog and building the FTS index costs ~15 s and dominates a
single evaluator run, so a subprocess-per-config sweep is mostly startup. This
loads both once and mutates starter.ranking's module-level weights between
runs -- _score() reads them as globals at call time, so that is enough.

    python -m tools.rank_sweep                      # the shipped defaults
    python -m tools.rank_sweep --grid prior         # a named grid

Always reports the full 200 sessions: NOTES_ranking.md records an hour lost to
a 40-session subset that showed a regression where the full set showed a gain.
"""
from __future__ import annotations

import argparse
import itertools
import json

import starter.ranking as ranking
from evaluator.local_evaluator import Agent, catalog_index, evaluate, load_jsonl

# name in starter.ranking -> the environment variable that overrides it
WEIGHTS = {
    "WEIGHT_CATEGORY": "TJ_W_CATEGORY",
    "WEIGHT_CONSTRAINT": "TJ_W_CONSTRAINT",
    "BONUS_MATERIAL": "TJ_B_MATERIAL",
    "BONUS_COLOR": "TJ_B_COLOR",
    "BONUS_BUDGET": "TJ_B_BUDGET",
    "WEIGHT_PRIOR": "TJ_W_PRIOR",
    # RRF is what actually orders the head now, so its parameters matter more
    # to MRR than any of the term weights above.
    "BONUS_EXACT_PHRASE": "TJ_B_EXACT",
    "BONUS_EXACT_PER_CHAR": "TJ_B_EXACT_CHAR",
    "BONUS_EXACT_CATEGORY": "TJ_B_EXACT_CAT",
    "BONUS_POPULARITY": "TJ_B_POPULARITY",
    "BONUS_PROFILE_RATING": "TJ_B_PROFILE_RATING",
    "EXACT_MIN_CHARS": "TJ_B_EXACT_MIN",
    "EXACT_MAX_PHRASES": "TJ_B_EXACT_MAXN",
    "BONUS_EXACT_TITLE": "TJ_B_EXACT_TITLE",
    "RRF_K": "TJ_RRF_K",
    "WEIGHT_RRF_RETRIEVAL": "TJ_W_RRF_RETRIEVAL",
    "WEIGHT_RRF_STAGE_A": "TJ_W_RRF_STAGE_A",
}

GRIDS: dict[str, dict[str, list[float]]] = {
    "prior": {"WEIGHT_PRIOR": [1.0, 3.0, 6.0, 10.0, 15.0, 25.0, 40.0]},
    "bonuses": {"BONUS_MATERIAL": [0.0, 1.5, 3.0], "BONUS_COLOR": [0.0, 1.5, 3.0]},
    "constraint": {"WEIGHT_CONSTRAINT": [0.25, 0.5, 1.0, 1.5]},
    "category": {"WEIGHT_CATEGORY": [1.0, 2.0, 3.0, 4.0]},
    # Low K makes 1/(K+rank) steep at the head -- the shape MRR rewards.
    "exact": {"BONUS_EXACT_PHRASE": [0.0, 4.0, 8.0, 12.0, 20.0, 35.0, 60.0]},
    "rrfk": {"RRF_K": [2.0, 5.0, 10.0, 20.0, 40.0, 60.0]},
    "rrfmix": {
        "WEIGHT_RRF_RETRIEVAL": [0.25, 0.5, 1.0],
        "WEIGHT_RRF_STAGE_A": [0.5, 1.0, 2.0],
    },
}


def run(agent_args, config: dict[str, float]) -> dict:
    """Score one weight configuration. Mutates the module globals in place."""
    saved = {name: getattr(ranking, name) for name in config}
    for name, value in config.items():
        setattr(ranking, name, value)
    try:
        samples, catalog_ids, categories, products, catalog_path = agent_args
        return evaluate(Agent(catalog_path), samples, catalog_ids, categories, products)
    finally:
        for name, value in saved.items():
            setattr(ranking, name, value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--grid", default="", help=f"one of {', '.join(GRIDS)}")
    parser.add_argument(
        "--set", action="append", default=[],
        help="NAME=value, repeatable; held fixed across every configuration",
    )
    parser.add_argument(
        "--sweep", action="append", default=[],
        help="NAME=v1,v2,... repeatable; the cross product is scored",
    )
    parser.add_argument("--output", default="results_rank_sweep.json")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    agent_args = (samples, catalog_ids, categories, products, args.catalog)

    fixed = {}
    for item in args.set:
        name, _, value = item.partition("=")
        fixed[name] = float(value)

    if args.grid:
        grid = GRIDS[args.grid]
    elif args.sweep:
        grid = {}
        for item in args.sweep:
            name, _, values = item.partition("=")
            grid[name] = [float(value) for value in values.split(",")]
    else:
        grid = {}

    if grid:
        names = list(grid)
        configs = [
            {**fixed, **dict(zip(names, values))}
            for values in itertools.product(*grid.values())
        ]
    else:
        configs = [fixed]

    print(f"{'config':<52}{'hit':>8}{'mrr':>10}{'mttc':>8}{'score':>10}")
    results = []
    for config in configs:
        result = run(agent_args, config)
        label = ", ".join(f"{name}={value:g}" for name, value in config.items()) or "shipped defaults"
        print(f"{label:<52}{result['hit_rate_at_10']:>8.4f}{result['mrr']:>10.6f}"
              f"{result['mttc']:>8.3f}{result['recommended_technical_score']:>10.6f}")
        results.append({
            "config": config,
            "hit_rate_at_10": result["hit_rate_at_10"],
            "mrr": result["mrr"],
            "mttc": result["mttc"],
            "technical": result["recommended_technical_score"],
            "scenario_metrics": result["scenario_metrics"],
        })

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)


if __name__ == "__main__":
    main()
