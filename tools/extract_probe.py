"""Why is the consistent set empty? A diagnosis before a fix.

`tools/holdout_synth.py` reports that on unseen targets a third of our non-rank-1
sessions are **defects rather than ties** -- the card uniquely identifies the
target and we still miss. `SCOREBOARD.md` names the mechanism: both card tiers
are conjunctive, so one mis-extracted constraint empties the consistent set and
the identification signal, worth +0.084, switches off entirely.

`BONUS_CARD_PARTIAL` was the obvious fix and it lost, monotonically, on exactly
these held-out draws. The reason it lost is important and easy to misread as a
reason to give up: partial agreement is *anti-correlated* with being the target,
because the constraint that failed is the one the target fails.

That argument only holds if the failure really is a mis-extraction. It says
nothing about the other possibility -- that extraction was fine and the
**matcher** could not see a match that is really there, because the shopper's
word and the product's word differ. Those two need completely different fixes,
and nothing in this repo has separated them.

This tool separates them. For every synthesised session whose consistent set is
empty, it asks of each disclosed constraint:

  MATCHES     the target's own card contains it exactly. Not the culprit.
  FUZZY       no exact match, but >=75% token overlap with a slot -- so the
              shipped fuzzy tier should already rescue it.
  VOCAB       no token overlap with any slot, but the constraint and some slot
              share a *semantic* neighbourhood. A lexicon could fix this.
  ABSENT      no relationship to any slot at all. Genuine mis-extraction, and
              exactly the case BONUS_CARD_PARTIAL was right to refuse.

The split decides whether a catalog-mined synonym lexicon is worth building. If
VOCAB is ~0, it is not, and this tool has saved the work.

    py -m tools.extract_probe --seeds 2
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from evaluator.local_evaluator import (
    MAX_TURNS,
    Agent,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.ranking import _disclosed_constraints, _terms, split_dialog
from starter.simcard import card_slots
from tools.holdout_synth import build

CATALOG = "data/catalog.jsonl"
DATASET = "data/public_set.jsonl"
FUZZY_MIN_OVERLAP = 0.75


def _classify(constraint: str, slots: tuple[str, ...]) -> str:
    if constraint in slots:
        return "MATCHES"
    tokens = set(_terms(constraint))
    if not tokens:
        return "ABSENT"
    best = 0.0
    any_shared = False
    for slot in slots:
        slot_tokens = set(_terms(slot))
        shared = len(tokens & slot_tokens)
        if shared:
            any_shared = True
            best = max(best, shared / len(tokens))
    if best >= FUZZY_MIN_OVERLAP:
        return "FUZZY"
    if any_shared:
        # Partial token overlap below the fuzzy threshold. A lexicon that maps
        # the *unshared* tokens to synonyms could push this over the line.
        return "VOCAB"
    return "ABSENT"


def _replay(agent, sample, catalog_ids, categories, products):
    """One session, mirroring evaluator.evaluate's loop with a session id we own.

    The evaluator mints a random `session_id`, so `agent._states` cannot be
    looked up by `sample_id` afterwards -- an earlier version of this tool did
    exactly that and silently found state for 0 of 82 failing sessions while
    reporting "no defects". Replaying is the only way to hold both the ranking
    the agent produced and the state it produced it from.
    """
    session_id = f"probe_{sample['sample_id']}"
    agent.reset(session_id, sample["user_profile"])
    target = str(sample["ground_truth"]["parent_asin"])
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    user_message = initial_message(effective, coarse_category(categories.get(target, [])), disclosed)
    best_rank = None
    for turn in range(1, MAX_TURNS + 1):
        response = agent.respond(session_id, user_message, turn, 10)
        ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
        if override_applied and target in ranked:
            best_rank = ranked.index(target) + 1
            break
        if turn == MAX_TURNS:
            break
        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            user_message = str(override.get("message", "Actually, please ignore my earlier preference."))
        else:
            user_message, boundary_used = customer_reply(
                effective, response.get("ask_attribute"), disclosed, boundary_used
            )
    return best_rank, agent._states.get(session_id)


def probe(seeds: int, n: int) -> dict:
    catalog_ids, categories, products = catalog_index(CATALOG)
    samples = load_jsonl(DATASET)
    slots_by_asin = {asin: card_slots(product) for asin, product in products.items()}

    verdicts: Counter[str] = Counter()
    sessions_by_worst: Counter[str] = Counter()
    examples: list[dict] = []
    total_sessions = non_rank1 = empty_sessions = no_disclosed = 0

    for seed in range(1, seeds + 1):
        synthetic = build(samples, products, n, seed)
        agent = Agent(CATALOG)
        for sample in synthetic:
            total_sessions += 1
            best_rank, state = _replay(agent, sample, catalog_ids, categories, products)
            if best_rank == 1:
                continue
            non_rank1 += 1
            if state is None:
                continue
            target_slots = slots_by_asin.get(str(sample["ground_truth"]["parent_asin"]), ())
            _category, constraint_texts = split_dialog(state)
            disclosed = _disclosed_constraints(constraint_texts)
            if not disclosed:
                no_disclosed += 1
                continue
            if all(value in target_slots for value in disclosed):
                continue
            empty_sessions += 1
            per = [(_classify(value, target_slots), value) for value in disclosed]
            for verdict, _value in per:
                verdicts[verdict] += 1
            worst = max(
                (v for v, _ in per),
                key=lambda v: ("MATCHES", "FUZZY", "VOCAB", "ABSENT").index(v),
            )
            sessions_by_worst[worst] += 1
            if len(examples) < 12:
                examples.append({
                    "seed": seed, "sample": sample["sample_id"], "rank": best_rank,
                    "verdict": worst,
                    "constraints": [{"verdict": v, "said": c[:70]} for v, c in per],
                    "target_slots": [s[:70] for s in target_slots],
                })

    return {
        "seeds": seeds,
        "sessions_scored": total_sessions,
        "non_rank_1": non_rank1,
        "no_disclosed_constraints": no_disclosed,
        "sessions_where_target_fails_its_own_card": empty_sessions,
        "constraint_verdicts": dict(verdicts),
        "session_worst_verdict": dict(sessions_by_worst),
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--n", type=int, default=200)
    args = parser.parse_args()

    print(f"probing {args.seeds} draw(s) of {args.n} unseen targets...")
    report = probe(args.seeds, args.n)

    print()
    print(f"  sessions scored                          {report['sessions_scored']}")
    print(f"  non-rank-1 sessions                      {report['non_rank_1']}")
    print(f"  ...of those, no disclosed constraints    {report['no_disclosed_constraints']}")
    print(f"  non-rank-1 where the TARGET fails its    "
          f"{report['sessions_where_target_fails_its_own_card']}")
    print(f"  own card (the empty-set case)")
    print()
    print("  per-constraint verdicts in those sessions:")
    total = sum(report["constraint_verdicts"].values()) or 1
    for verdict in ("MATCHES", "FUZZY", "VOCAB", "ABSENT"):
        count = report["constraint_verdicts"].get(verdict, 0)
        print(f"    {verdict:9s} {count:5d}  ({100*count/total:5.1f}%)")
    print()
    print("  worst verdict per session (what would have to be fixed):")
    for verdict, count in sorted(report["session_worst_verdict"].items()):
        print(f"    {verdict:9s} {count:5d}")

    with open("results_extract_probe.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print("\nwrote results_extract_probe.json")


if __name__ == "__main__":
    main()
