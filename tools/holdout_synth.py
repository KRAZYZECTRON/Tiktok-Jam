"""Score the agent on catalog products the tuning never saw.

Every number in `SCOREBOARD.md` was measured on the same 200 public sessions the
tunables were chosen on. The even/odd split-half used throughout is a split of
*those* 200 -- it varies which sessions are scored but never the fact that all
200 targets were visible while thresholds, bonuses and hold-back rules were
being picked. It cannot detect overfitting to the target set itself, and the
hidden 800 are drawn from products we have never scored against.

This closes that gap as far as it can be closed locally. The evaluator derives a
session's entire hidden state from the target product plus the sample id --
`materialize_hidden_fields` calls `intent_card(product)` and `behavior_for(...)`
-- so a valid session can be synthesised for ANY catalog product out of four
fields. `starter/simcard.py`'s reconstruction of that card is exact on all
50,000 products (`tools.verify_claims` checks this), so the simulated shopper
behaves the same way for a synthetic target as for a real one.

    py -m tools.holdout_synth                  # 200 unseen targets, one draw
    py -m tools.holdout_synth --seeds 5        # spread across draws
    py -m tools.holdout_synth --n 800          # the size of the real hidden set

**What this is not.** The real sessions are sampled from the official Clothing
5-core leave-last-out split, so their targets are products with review history;
these are drawn uniformly from the catalog. Profiles are resampled from the
public set's 125 distinct ones rather than being real. The absolute number is a
*proxy*, not a prediction -- the quantity of interest is the gap between it and
the public score, measured across several draws so one draw cannot masquerade
as a measurement.

The last line of the report is the one worth acting on: of the sessions we get
wrong, how many had a card that uniquely identifies the target. Those are not
ambiguity, they are defects -- and the public set shows far fewer of them.
"""
from __future__ import annotations

import argparse
import random
import statistics
from collections import defaultdict

from evaluator.local_evaluator import (
    Agent,
    catalog_index,
    evaluate,
    intent_card,
    load_jsonl,
)
from starter.simcard import card_slots


def build(samples: list[dict], products: dict, n: int, seed: int) -> list[dict]:
    """Synthesise `n` sessions over catalog products absent from `samples`.

    The scenario mix is copied from the public set position by position rather
    than resampled, so the four scenarios keep their 80/80/30/10 proportions
    exactly and a seed varies only which products and profiles are drawn.
    """
    rng = random.Random(seed)
    seen = {str(sample["ground_truth"]["parent_asin"]) for sample in samples}
    profiles = [sample["user_profile"] for sample in samples]
    scenarios = [sample["scenario_type"] for sample in samples]
    unseen = sorted(set(products) - seen)
    if n > len(unseen):
        raise SystemExit(f"asked for {n} unseen targets; only {len(unseen)} exist")
    return [
        {
            "sample_id": f"synth_{seed}_{i:04d}",
            "scenario_type": scenarios[i % len(scenarios)],
            "ground_truth": {"parent_asin": asin},
            "user_profile": profiles[rng.randrange(len(profiles))],
            "category_bucket": "clothing",
            "difficulty_bucket": "synthetic",
        }
        for i, asin in enumerate(rng.sample(unseen, n))
    ]


def slot_index(products: dict) -> dict:
    index = defaultdict(set)
    for asin, product in products.items():
        for slot in card_slots(product):
            index[slot].add(asin)
    return index


def consistent_size(asin: str, products: dict, index: dict) -> int:
    """How many catalog products stay compatible with this target's whole card.

    1 means the conversation, fully played out, does single the target out. A
    session lost with a consistent size of 1 is a defect; one lost with a size
    of 40 may be genuinely undecidable from what the shopper disclosed.
    """
    card = intent_card(products[asin])
    disclosed = [str(value).lower()
                 for value in card["hard_constraints"] + card["soft_preferences"]]
    sets = [index.get(value, set()) for value in disclosed if value]
    return len(set.intersection(*sets)) if sets else len(products)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--n", type=int, default=200, help="sessions per seed")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--first-seed", type=int, default=1)
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    index = slot_index(products)

    public = evaluate(Agent(args.catalog), samples, catalog_ids, categories, products)
    baseline = public["recommended_technical_score"]
    print(f"public 200 (in-sample)  score {baseline:.6f}   Hit@10 {public['hit_rate_at_10']:.4f}"
          f"   MRR {public['mrr']:.6f}   MTTC {public['mttc']:.3f}")
    print()

    header = f"{'seed':<6}{'score':>10}{'Hit@10':>9}{'MRR':>10}{'MTTC':>8}{'vs public':>11}"
    print(header)
    print("-" * len(header))

    scores: list[float] = []
    wrong_total = solvable_total = 0
    for seed in range(args.first_seed, args.first_seed + args.seeds):
        synthetic = build(samples, products, args.n, seed)
        result = evaluate(Agent(args.catalog), synthetic, catalog_ids, categories, products)
        score = result["recommended_technical_score"]
        scores.append(score)
        print(f"{seed:<6}{score:>10.6f}{result['hit_rate_at_10']:>9.4f}"
              f"{result['mrr']:>10.6f}{result['mttc']:>8.3f}{score - baseline:>+11.6f}")
        if args.seeds == 1:
            for name, metrics in result["scenario_metrics"].items():
                print(f"      {name:<16} n={metrics['sample_count']:<4}"
                      f"  hit {metrics['hit_rate_at_10']:.4f}"
                      f"  mrr {metrics['mrr']:.4f}  mttc {metrics['mttc']:.2f}")

        target_of = {sample["sample_id"]: str(sample["ground_truth"]["parent_asin"])
                     for sample in synthetic}
        wrong = [s for s in result["sessions"] if s["best_rank"] != 1]
        wrong_total += len(wrong)
        solvable_total += sum(
            1 for s in wrong
            if consistent_size(target_of[s["sample_id"]], products, index) == 1
        )

    if args.seeds > 1:
        print("-" * len(header))
        mean = statistics.fmean(scores)
        print(f"{'mean':<6}{mean:>10.6f}{'':>27}{mean - baseline:>+11.6f}")
        print(f"{'spread':<6}{max(scores) - min(scores):>10.6f}"
              f"   (min {min(scores):.6f}, max {max(scores):.6f})")

    total = args.n * args.seeds
    print()
    print(f"not returned at rank 1: {wrong_total} of {total} sessions")
    print(f"  ...of which the card uniquely identifies the target: {solvable_total}"
          f" ({solvable_total / max(wrong_total, 1):.0%} of the failures)")
    print()
    print("Those last ones are defects rather than ambiguity: the conversation does")
    print("single the product out and the agent still did not put it first. The public")
    print("set shows far fewer of them, which is what tuning on a visible set looks like.")


if __name__ == "__main__":
    main()
