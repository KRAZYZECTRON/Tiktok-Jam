"""How much of the shipped configuration is real, and how much was luck?

Every tunable in this project was adopted on a **single** even/odd split. That
is one draw. A gain that holds on one particular partition of 200 sessions can
still be a property of those sessions rather than of the ranker, and the hidden
800 use different users and different products.

This re-tests each shipped choice across many random split-halves and reports
how often its gain holds on *both* halves at once. A change that survives 95% of
splits is structural; one that survives 55% is a coin flip we happened to win.

The trick that makes this affordable: `evaluate()` returns per-session results,
so each configuration is run over the full 200 **once** and every split is then
computed by aggregating subsets of that cached session list. Naively re-running
the evaluator per split would be hundreds of runs; this is one per config.

    py -m tools.stability                 # all shipped choices, 200 splits
    py -m tools.stability --splits 500

Reports only. Nothing here adopts or reverts anything -- a low survival rate is
information for a human, not a trigger.
"""
from __future__ import annotations

import argparse
import random
import statistics

from evaluator.local_evaluator import (
    MAX_TURNS,
    Agent,
    catalog_index,
    evaluate,
    load_jsonl,
)
import starter.agent as agent_mod
import starter.ranking as ranking_mod

# Each entry: label, module, attribute, the value to compare the shipped one
# against. The comparison value is what the setting was before it was adopted.
CHOICES = [
    ("post-fusion card promotion", ranking_mod, "BONUS_CARD_FUSED", 0.0),
    ("post-fusion category match", ranking_mod, "BONUS_CAT_FUSED", 0.0),
    ("popularity tie-break", ranking_mod, "BONUS_POP_FUSED", 0.0),
    ("rating tie-break", ranking_mod, "BONUS_RATING_FUSED", 0.0),
    ("fuzzy card tier", ranking_mod, "BONUS_CARD_FUZZY", 0.0),
    ("verbatim category bonus", ranking_mod, "BONUS_EXACT_CATEGORY", 0.0),
    ("exact-phrase bonus", ranking_mod, "BONUS_EXACT_PHRASE", 0.0),
    ("hold-back threshold 3 (vs 4)", agent_mod, "MIN_DISCLOSED", 4),
    ("early answer when identified", agent_mod, "ANSWER_IF_CONSISTENT", 0),
]


def score_of(sessions: list[dict]) -> float:
    """The official formula, recomputed over an arbitrary subset of sessions."""
    if not sessions:
        return 0.0
    n = len(sessions)
    hit = sum(1 for s in sessions if s["hit"]) / n
    mrr = statistics.fmean(s["reciprocal_rank"] for s in sessions)
    mttc = statistics.fmean(
        s["first_hit_turn"] if s["first_hit_turn"] is not None else MAX_TURNS + 1
        for s in sessions
    )
    efficiency = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    return 0.50 * hit + 0.30 * mrr + 0.20 * efficiency


def sessions_for(catalog: str, samples, catalog_ids, categories, products,
                 module=None, attribute: str = "", value=None) -> list[dict]:
    """Full 200-session run under one configuration, restored afterwards."""
    saved = getattr(module, attribute) if module else None
    if module:
        setattr(module, attribute, value)
    try:
        return evaluate(Agent(catalog), samples, catalog_ids, categories, products)["sessions"]
    finally:
        if module:
            setattr(module, attribute, saved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--splits", type=int, default=200)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)

    print("running each configuration once over the full 200 sessions...")
    shipped = sessions_for(args.catalog, samples, catalog_ids, categories, products)
    print(f"  shipped: {score_of(shipped):.6f}")

    variants = []
    for label, module, attribute, alternative in CHOICES:
        rows = sessions_for(args.catalog, samples, catalog_ids, categories, products,
                            module, attribute, alternative)
        variants.append((label, attribute, alternative, rows))
        print(f"  without {label}: {score_of(rows):.6f}")

    rng = random.Random(args.seed)
    n = len(shipped)
    # One set of random partitions, reused for every choice so the comparison
    # between choices is like-for-like rather than each getting its own luck.
    partitions = []
    for _ in range(args.splits):
        order = list(range(n))
        rng.shuffle(order)
        partitions.append((set(order[: n // 2]), set(order[n // 2:])))

    print(f"\n{args.splits} random split-halves, reused across every choice\n")
    print(f"{'shipped choice':<32}{'full d':>10}{'both+':>8}{'median d':>11}{'worst d':>10}  verdict")
    print("-" * 88)

    for label, attribute, alternative, rows in variants:
        full_delta = score_of(shipped) - score_of(rows)
        deltas_a, deltas_b, both_positive = [], [], 0
        for left, right in partitions:
            da = score_of([s for i, s in enumerate(shipped) if i in left]) - \
                 score_of([s for i, s in enumerate(rows) if i in left])
            db = score_of([s for i, s in enumerate(shipped) if i in right]) - \
                 score_of([s for i, s in enumerate(rows) if i in right])
            deltas_a.append(da)
            deltas_b.append(db)
            if da > 0 and db > 0:
                both_positive += 1
        rate = both_positive / len(partitions)
        alld = deltas_a + deltas_b
        alld.sort()
        median = alld[len(alld) // 2]
        worst = alld[0]
        if rate >= 0.90:
            verdict = "structural"
        elif rate >= 0.70:
            verdict = "probably real"
        elif rate >= 0.45:
            verdict = "COIN FLIP"
        else:
            verdict = "LIKELY LUCK"
        print(f"{label:<32}{full_delta:>+10.4f}{rate:>8.0%}{median:>+11.4f}{worst:>+10.4f}  {verdict}")

    print("\n'both+' is the fraction of random splits where the shipped value beats")
    print("the alternative on BOTH halves at once -- the standard every one of these")
    print("was originally adopted under, but measured over many draws instead of one.")
    print("\nThis reports only. A low rate is information for a human, not a trigger:")
    print("a small structural gain can look fragile simply because it is small.")


if __name__ == "__main__":
    main()
