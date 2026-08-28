"""Where does the ground truth actually sit, before and after rank()?

Aggregate metrics say a session missed; they do not say whether the target was
never retrieved (a recall problem, Seat 2's) or retrieved and then ordered badly
(an ordering problem, Seat 1's). This replays the real evaluator loop -- same
dialog trajectory, same pools -- and records the target's position in
retrieve()'s BM25 ordering and in rank()'s ordering at every scored turn.

    python -m tools.rank_probe [--limit N]

Read-only: it patches starter.agent.rank in-process to observe the pool, and
touches nothing on disk.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import starter.agent as agent_module
from evaluator.local_evaluator import (
    Agent,
    catalog_index,
    evaluate,
    load_jsonl,
)
from starter.ranking import rank as real_rank

# session_id -> turn -> (pool order, ranked order). Filled by the patched rank().
OBSERVED: dict[str, dict[int, tuple[list[str], list[str]]]] = {}
# session_id -> dialog state at the last scored turn.
DIALOG: dict[str, dict] = {}


def _patched_rank(candidates, state):
    """Delegate to the real rank(), recording what went in and what came out."""
    ranked = real_rank(candidates, state)
    turns = OBSERVED.setdefault(state.session_id, {})
    turns[state.turn] = (
        [candidate.parent_asin for candidate in candidates],
        [candidate.parent_asin for candidate in ranked],
    )
    # Dialog-side state at the same instant: a miss where the shopper disclosed
    # nothing is Seat 3's problem, a miss with a full slot card is not.
    DIALOG[state.session_id] = {
        "slots": len(getattr(state, "slots", {}) or {}),
        "exhausted": sorted(getattr(state, "exhausted_attributes", set()) or set()),
        "query_terms": len(set((getattr(state, "query", "") or "").lower().split())),
        "asked": getattr(state, "ask_attribute", None),
    }
    return ranked


def _position(order: list[str], target: str) -> int | None:
    """1-indexed position of the target, or None if it is not in the list."""
    try:
        return order.index(target) + 1
    except ValueError:
        return None


def _bucket(position: int | None) -> str:
    if position is None:
        return "not in pool"
    if position <= 10:
        return "1-10"
    if position <= 50:
        return "11-50"
    if position <= 100:
        return "51-100"
    return ">100"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="first N sessions only")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    if args.limit:
        samples = samples[: args.limit]
    catalog_ids, categories, products = catalog_index(args.catalog)

    # The evaluator resets and responds one sample at a time, so recording the
    # order reset() is called in is enough to map session_id back to a sample.
    order: list[str] = []
    original_reset = Agent.reset

    def _patched_reset(self, session_id, user_profile):
        order.append(session_id)
        return original_reset(self, session_id, user_profile)

    Agent.reset = _patched_reset
    agent_module.rank = _patched_rank
    try:
        result = evaluate(Agent(args.catalog), samples, catalog_ids, categories, products)
    finally:
        Agent.reset = original_reset
        agent_module.rank = real_rank

    miss_pool: Counter[str] = Counter()
    miss_ranked: Counter[str] = Counter()
    rows: list[dict] = []
    for sample, session, session_id in zip(samples, result["sessions"], order):
        target = str(sample["ground_truth"]["parent_asin"])
        turns = OBSERVED.get(session_id, {})
        # The last scored turn is the one that decides the session: for a hit it
        # is the hitting turn, for a miss it is the deepest state we ever built.
        last_turn = max(turns) if turns else 0
        pool, ranked = turns.get(last_turn, ([], []))
        pool_position = _position(pool, target)
        ranked_position = _position(ranked, target)
        rows.append({
            "sample_id": sample["sample_id"],
            "scenario_type": sample["scenario_type"],
            "hit": session["hit"],
            "last_turn": last_turn,
            "pool_position": pool_position,
            "ranked_position": ranked_position,
            **DIALOG.get(session_id, {}),
        })
        if not session["hit"]:
            miss_pool[_bucket(pool_position)] += 1
            miss_ranked[_bucket(ranked_position)] += 1

    misses = sum(miss_ranked.values())
    print(f"sessions {len(rows)}  hits {len(rows) - misses}  misses {misses}")
    print("\nmissed sessions, target position at the last scored turn")
    print(f"{'bucket':<12}{'in BM25 pool':>14}{'after rank()':>14}")
    for bucket in ("1-10", "11-50", "51-100", ">100", "not in pool"):
        print(f"{bucket:<12}{miss_pool[bucket]:>14}{miss_ranked[bucket]:>14}")

    with open("results_rank_probe.json", "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    print("\nper-session detail written to results_rank_probe.json")


if __name__ == "__main__":
    main()
