"""Fast, scenario-stratified subset of the local evaluator, for iteration only.

The real number is always `python -m evaluator.local_evaluator` over all 200
public sessions -- that is what gates a merge into main. This exists because a
full run with LLM re-ranking on is ~2000 model calls, which is too slow to tune
a prompt against. Reads evaluator/ and data/ without modifying either.

    py -m tools.quick_eval --n 40
    py -m tools.quick_eval --n 40 --scenario browsing
    py -m tools.quick_eval --full          # all 200, same as the real evaluator
"""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from starter.agent import Agent


def stratified(samples: list[dict], n: int, seed: int) -> list[dict]:
    """Sample n keeping each scenario's share of the full set -- browsing is
    80/200 of the real score and also the weakest, so it must stay represented."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[sample["scenario_type"]].append(sample)

    rng = random.Random(seed)
    picked: list[dict] = []
    for scenario in sorted(grouped):
        pool = sorted(grouped[scenario], key=lambda item: item["sample_id"])
        take = max(1, round(n * len(pool) / len(samples)))
        picked.extend(rng.sample(pool, min(take, len(pool))))
    return sorted(picked, key=lambda item: item["sample_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=40, help="subset size (default 40)")
    parser.add_argument("--full", action="store_true", help="run all 200 sessions")
    parser.add_argument("--scenario", help="restrict to one scenario_type")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output", default="results_quick.json")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    if args.scenario:
        samples = [item for item in samples if item["scenario_type"] == args.scenario]
    subset = samples if args.full else stratified(samples, args.n, args.seed)

    catalog_ids, categories, products = catalog_index(args.catalog)
    started = time.time()
    result = evaluate(Agent(args.catalog), subset, catalog_ids, categories, products)
    elapsed = time.time() - started

    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in result.items() if key != "sessions"}
    print(json.dumps(summary, indent=2))
    print(f"\n{len(subset)} sessions in {elapsed:.1f}s ({elapsed/len(subset):.2f}s/session) -> {args.output}")
    if not args.full:
        print("subset only -- re-run with --full before treating this as the score")


if __name__ == "__main__":
    main()
