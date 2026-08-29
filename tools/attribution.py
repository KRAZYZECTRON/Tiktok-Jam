"""Attribute every missed session to the seat that could have saved it.

"What do we work on next" is guesswork unless we know *why* each session failed.
This drives the real Agent through the evaluator's exact conversation protocol,
then instruments each turn: where the target sat in retrieve()'s pool, and
whether it reached the window agent.py actually returned.

  HIT              found it
  MISS_RETRIEVAL   target never entered the pool on any turn        -> Seat 2
  MISS_RANKING     in the pool, never in the returned window        -> Seat 1
  MISS_DIALOG      reached the window but the session still failed
                   (blocked by the override gate, or found too late) -> Seat 3

An earlier version of this file replayed the protocol by hand and passed
ask_attribute=None, which was true of the baseline and became wrong the moment
dialog.py started asking. It now drives the real Agent, so it cannot drift from
the pipeline again.

Read-only: imports the evaluator, modifies nothing.

    py -m tools.attribution
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import POOL_K, Agent
from starter.retrieval import retrieve


def replay(sample: dict, agent: Agent, catalog_ids: set, categories: dict, products: dict) -> dict:
    target = str(sample["ground_truth"]["parent_asin"])
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}

    session_id = f"attr_{sample['sample_id']}"
    agent.reset(session_id, sample["user_profile"])

    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    message = initial_message(effective, coarse_category(categories.get(target, [])), disclosed)

    best_pool_rank: int | None = None
    ever_in_window = False
    hit_turn = hit_rank = None
    asked: list[str] = []
    turns_used = 0

    for turn in range(1, MAX_TURNS + 1):
        turns_used = turn
        response = agent.respond(session_id, message, turn, TOP_K)
        window = normalize_recommendations(response.get("recommendations"), catalog_ids)

        # The agent has already built its state; re-issue the same query to see
        # where the target sits in the pool it drew from. Reading _states is a
        # diagnostic liberty -- it is the only way to see the composed query.
        state = agent._states[session_id]
        pool_query = getattr(state, "query", "") or message
        pool_ids = [c.parent_asin for c in retrieve(pool_query, state, max(POOL_K, TOP_K))]
        if target in pool_ids:
            position = pool_ids.index(target) + 1
            best_pool_rank = position if best_pool_rank is None else min(best_pool_rank, position)

        attribute = response.get("ask_attribute")
        if isinstance(attribute, str):
            asked.append(attribute)

        if target in window:
            ever_in_window = True
            if override_applied:
                hit_turn, hit_rank = turn, window.index(target) + 1
                break

        if turn == MAX_TURNS:
            break

        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            message = str(override.get("message", "Actually, please ignore my earlier preference."))
        else:
            message, boundary_used = customer_reply(
                effective, attribute, disclosed, boundary_used
            )

    if hit_turn is not None:
        bucket = "HIT"
    elif best_pool_rank is None:
        bucket = "MISS_RETRIEVAL"
    elif not ever_in_window:
        bucket = "MISS_RANKING"
    else:
        bucket = "MISS_DIALOG"

    return {
        "sample_id": sample["sample_id"],
        "scenario": sample["scenario_type"],
        "difficulty": sample.get("difficulty_bucket", "?"),
        "bucket": bucket,
        "hit_turn": hit_turn,
        "hit_rank": hit_rank,
        "best_pool_rank": best_pool_rank,
        "turns_used": turns_used,
        "asked": asked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output", default="results_attribution.json")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    agent = Agent(args.catalog)
    rows = [replay(s, agent, catalog_ids, categories, products) for s in samples]
    Path(args.output).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    total = len(rows)
    buckets = Counter(row["bucket"] for row in rows)
    print(f"=== {total} sessions ===")
    for name in ("HIT", "MISS_RETRIEVAL", "MISS_RANKING", "MISS_DIALOG"):
        print(f"  {name:<16} {buckets[name]:>4}  {buckets[name]/total:6.1%}")

    print("\n=== by scenario ===")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["scenario"]].append(row)
    for scenario in sorted(grouped):
        group = grouped[scenario]
        counts = Counter(row["bucket"] for row in group)
        detail = "  ".join(
            f"{name.replace('MISS_', '')[:4]}={counts[name]}"
            for name in ("HIT", "MISS_RETRIEVAL", "MISS_RANKING", "MISS_DIALOG")
        )
        print(f"  {scenario:<16} n={len(group):<4} {detail}")

    misses = [row for row in rows if row["bucket"] != "HIT"]
    if misses:
        print(f"\n=== the {len(misses)} remaining misses ===")
        for row in misses:
            pool = row["best_pool_rank"]
            print(
                f"  {row['sample_id']}  {row['scenario']:<16} {row['bucket']:<15} "
                f"difficulty={row['difficulty']:<7} best_pool_rank={pool if pool else '-':<6} "
                f"asked={','.join(row['asked'][:6]) or '-'}"
            )

    hits = [row for row in rows if row["bucket"] == "HIT"]
    if hits:
        print(f"\n=== of {len(hits)} hits ===")
        print(f"  mean hit turn: {sum(r['hit_turn'] for r in hits)/len(hits):.2f}")
        print(f"  mean hit rank: {sum(r['hit_rank'] for r in hits)/len(hits):.2f}")
        by_turn = Counter(r["hit_turn"] for r in hits)
        print("  hits by turn:  " + "  ".join(f"t{t}={by_turn[t]}" for t in sorted(by_turn)))


if __name__ == "__main__":
    main()
