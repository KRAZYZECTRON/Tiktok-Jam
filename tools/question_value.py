"""Does question-value estimation beat asking "other" every turn?

`NOTES_ranking.md` claims adaptive probing is "not implementable" here: the
simulator caps disclosure at two constraints per reply and `"other"` matches any
undisclosed constraint, so the agent is already extracting at the maximum
possible rate. That is a mechanism argument, and it is probably right. This
turns it into a measurement.

Two things are reported, because they answer different questions:

1. **Agreement.** Over every turn of the 200 public sessions, how often does
   the estimator's argmax equal `"other"`, and by what margin does `"other"`
   win when it wins? If the estimator almost always agrees, the shipped
   heuristic is not a shortcut — it is the optimum, and we can say so with a
   number instead of an argument.

2. **Score.** The full evaluator with `TJ_QVALUE=1` against the shipped path.
   Agreement on the argmax does not guarantee an identical score, because the
   estimator can differ on the turns where `"other"` is exhausted.

    py -m tools.question_value            # both, ~2 min
    py -m tools.question_value --no-score # agreement only, ~40 s
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

from evaluator.local_evaluator import (
    catalog_index,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
)
from starter.question import MAX_CANDIDATES, score_attributes
from starter.simcard import card_slots

CATALOG = "data/catalog.jsonl"
DATASET = "data/public_set.jsonl"


def coarse_category(categories) -> str:
    if isinstance(categories, list) and categories:
        return " ".join(str(value) for value in categories[:2])
    return "product"


def agreement(limit: int | None = None, cap: int | None = MAX_CANDIDATES) -> dict:
    """Replay each session's disclosure sequence and score every attribute."""
    _ids, categories, products = catalog_index(CATALOG)
    samples = load_jsonl(DATASET)
    if limit:
        samples = samples[:limit]

    # The consistent set is indexed by reconstructed card, exactly as ranking
    # does it. Built once over the whole catalog.
    all_slots = {asin: card_slots(product) for asin, product in products.items()}

    argmax_counts: Counter[str] = Counter()
    other_margin: list[float] = []
    turns_where_other_loses: list[dict] = []
    total_turns = 0

    for sample in samples:
        card, behavior = materialize_hidden_fields(sample, products)
        sample = {**sample, "intent_card": card, "behavior": behavior}
        target = str(sample["ground_truth"]["parent_asin"])
        disclosed: set[str] = set()
        initial_message(sample, coarse_category(categories.get(target)), disclosed)

        boundary_used = False
        for turn in range(1, 6):  # no public session has ever hit after turn 4
            frozen = frozenset(value.lower() for value in disclosed)
            consistent = [
                slots for slots in all_slots.values()
                if all(value in slots for value in frozen)
            ]
            if not consistent:
                break
            # Capped exactly as the runtime caps it by default, so this
            # measures the estimator that would actually ship. --uncapped
            # scores the whole consistent set instead, which is the idealised
            # estimator and a different (also interesting) question.
            scored = score_attributes(
                consistent if cap is None else consistent[:cap], frozen
            )
            best_attr, best_value = scored[0]
            other_value = dict(scored)["other"]
            argmax_counts[best_attr] += 1
            other_margin.append(other_value - best_value)
            total_turns += 1
            if best_attr != "other" and best_value - other_value > 1e-9:
                turns_where_other_loses.append({
                    "sample": sample["sample_id"], "turn": turn,
                    "best": best_attr, "gain": round(best_value - other_value, 3),
                    "consistent": len(consistent),
                })
            # Advance the conversation the way the harness would.
            _reply, boundary_used = customer_reply(sample, "other", disclosed, boundary_used)

    return {
        "turns_scored": total_turns,
        "argmax": dict(argmax_counts),
        "other_is_argmax": argmax_counts.get("other", 0),
        "other_is_argmax_pct": round(100 * argmax_counts.get("other", 0) / max(total_turns, 1), 2),
        "mean_shortfall_of_other": round(sum(other_margin) / max(len(other_margin), 1), 4),
        "turns_where_a_specific_attribute_wins": turns_where_other_loses[:20],
        "n_turns_where_a_specific_attribute_wins": len(turns_where_other_loses),
    }


def score_with(env_extra: dict[str, str]) -> dict:
    env = {**os.environ, **env_extra}
    subprocess.run(
        [sys.executable, "-m", "evaluator.local_evaluator"],
        env=env, capture_output=True, check=True,
    )
    with open("results.json", encoding="utf-8") as handle:
        result = json.load(handle)
    return {
        "score": result["recommended_technical_score"],
        "hit": result["hit_rate_at_10"],
        "mrr": result["mrr"],
        "mttc": result["mttc"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--uncapped", action="store_true",
                        help="score the whole consistent set, not the runtime's 400 cap")
    args = parser.parse_args()

    print(f"scoring every attribute at every turn of the public set "
          f"({'uncapped' if args.uncapped else f'cap={MAX_CANDIDATES}'})...")
    report = agreement(args.limit, cap=None if args.uncapped else MAX_CANDIDATES)
    print()
    print(f"  turns scored                     {report['turns_scored']}")
    print(f"  argmax distribution              {report['argmax']}")
    print(f"  \"other\" is the argmax            {report['other_is_argmax']}"
          f" ({report['other_is_argmax_pct']}%)")
    print(f"  mean shortfall of 'other'        {report['mean_shortfall_of_other']}"
          f"  (<=0 by construction)")
    print(f"  turns a specific attribute wins  {report['n_turns_where_a_specific_attribute_wins']}")
    for row in report["turns_where_a_specific_attribute_wins"][:5]:
        print(f"      {row}")

    out = {"agreement": report}
    if not args.no_score:
        print()
        print("scoring the full evaluator, estimator off then on...")
        off = score_with({"TJ_QVALUE": "0"})
        on = score_with({"TJ_QVALUE": "1"})
        out["score_off"], out["score_on"] = off, on
        print()
        print(f"  {'':22s} {'score':>10} {'Hit@10':>8} {'MRR':>8} {'MTTC':>7}")
        for label, row in (("shipped (estimator off)", off), ("TJ_QVALUE=1", on)):
            print(f"  {label:22s} {row['score']:>10.6f} {row['hit']:>8.4f}"
                  f" {row['mrr']:>8.4f} {row['mttc']:>7.3f}")
        delta = on["score"] - off["score"]
        print()
        print(f"  delta {delta:+.6f}")

    with open("results_question_value.json", "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
    print("\nwrote results_question_value.json")


if __name__ == "__main__":
    main()
