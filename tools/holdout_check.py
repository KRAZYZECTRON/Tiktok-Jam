"""Split-half stability check for a rank() weight configuration.

Sweeping picks the configuration that scores best on the 200 visible sessions,
which is exactly the procedure that manufactures a number the hidden 800 will
not reproduce. This scores a configuration on two deterministic halves of the
public set (even-indexed and odd-indexed samples) separately.

A real improvement shows up on both halves. A gain that appears on one half and
not the other is a property of those particular sessions, not of the ranker.

    python -m tools.holdout_check

Scores nothing new and tunes nothing -- it only re-runs configurations that
were already chosen.
"""
from __future__ import annotations

import json
import os

import starter.ranking as ranking
from evaluator.local_evaluator import Agent, catalog_index, evaluate, load_jsonl

CATALOG = "data/catalog.jsonl"
DATASET = "data/public_set.jsonl"

# The configuration rank() shipped with before this session: stage A replacing
# retrieve()'s order, with a flat prior worth at most 1.0.
ORIGINAL = {
    "FUSION": "linear",
    "WEIGHT_PRIOR": 1.0,
    "WEIGHT_CATEGORY": 2.0,
    "WEIGHT_CONSTRAINT": 1.0,
    "BONUS_MATERIAL": 3.0,
    "BONUS_COLOR": 3.0,
    "BONUS_BUDGET": 2.5,
}

# Best of the 53 configurations swept, on the full 200.
BEST = {
    "FUSION": "rrf",
    "RRF_K": 60.0,
    "WEIGHT_RRF_RETRIEVAL": 1.0,
    "WEIGHT_RRF_STAGE_A": 1.0,
    "WEIGHT_CATEGORY": 0.5,
    "WEIGHT_CONSTRAINT": 1.0,
    "BONUS_MATERIAL": 3.0,
    "BONUS_COLOR": 3.0,
    "BONUS_BUDGET": 2.5,
}

# retrieve()'s own BM25 order, untouched -- the "delete stage A" alternative.
RANK_OFF = {**ORIGINAL, "_rank_off": True}

# BEST plus dialog.py's dead-turn rotation, which is code rather than a weight.
FINAL = dict(BEST)


def score(config: dict, samples, catalog_ids, categories, products) -> dict:
    """Evaluate one configuration, restoring the module globals afterwards."""
    saved = {name: getattr(ranking, name) for name in config if not name.startswith("_")}
    for name, value in config.items():
        if not name.startswith("_"):
            setattr(ranking, name, value)
    previous = os.environ.get("TJ_RANK")
    if config.get("_rank_off"):
        os.environ["TJ_RANK"] = "off"
    # The rotation is on by default, so every pre-rotation configuration has to
    # switch it back off to stay comparable with what it originally scored.
    if not config.get("_rotate"):
        os.environ["TJ_ROTATE"] = "off"
    else:
        os.environ.pop("TJ_ROTATE", None)
    try:
        return evaluate(Agent(CATALOG), samples, catalog_ids, categories, products)
    finally:
        for name, value in saved.items():
            setattr(ranking, name, value)
        os.environ.pop("TJ_ROTATE", None)
        if config.get("_rank_off"):
            if previous is None:
                del os.environ["TJ_RANK"]
            else:
                os.environ["TJ_RANK"] = previous


def main() -> None:
    samples = load_jsonl(DATASET)
    catalog_ids, categories, products = catalog_index(CATALOG)
    halves = {
        "full (200)": samples,
        "half A, even idx (100)": samples[0::2],
        "half B, odd idx (100)": samples[1::2],
    }
    configs = {
        "original": ORIGINAL,
        "swept only": BEST,
        "swept+rotate": {**FINAL, "_rotate": True},
    }

    table: dict[str, dict[str, dict]] = {}
    print(f"{'split':<26}{'config':<14}{'hit':>8}{'mrr':>10}{'mttc':>8}{'technical':>12}")
    for split_name, subset in halves.items():
        table[split_name] = {}
        for config_name, config in configs.items():
            result = score(config, subset, catalog_ids, categories, products)
            table[split_name][config_name] = {
                "hit_rate_at_10": result["hit_rate_at_10"],
                "mrr": result["mrr"],
                "mttc": result["mttc"],
                "technical": result["recommended_technical_score"],
            }
            print(f"{split_name:<26}{config_name:<14}{result['hit_rate_at_10']:>8.4f}"
                  f"{result['mrr']:>10.6f}{result['mttc']:>8.3f}"
                  f"{result['recommended_technical_score']:>12.6f}")

    print("\ndelta, best swept minus original")
    for split_name in halves:
        best = table[split_name]["swept+rotate"]
        original = table[split_name]["original"]
        print(f"  {split_name:<26} hit {best['hit_rate_at_10'] - original['hit_rate_at_10']:+.4f}"
              f"   technical {best['technical'] - original['technical']:+.6f}")

    with open("results_holdout.json", "w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=2)


if __name__ == "__main__":
    main()
