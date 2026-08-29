"""Show the agent's dynamic context programming on a real session.

Pillar III is the hardest part of this system to see from the outside: the
runtime strategy switching and the long-term profile memory both live in state
that never appears in the agent's output. This prints them.

    py -m tools.context_demo                 # one session, turn by turn
    py -m tools.context_demo --sample public_0002
    py -m tools.context_demo --memory        # long-term profile accumulation

The transcript view shows, per turn: what the shopper said, what the agent
distilled from it, which of CLARIFY / IDENTIFY / EXPLORE it chose and why, and
what it returned. The memory view shows a profile recurring across sessions and
what the store has learned by the time it is seen again.

Read-only; drives the real Agent through the evaluator's own protocol.
"""
from __future__ import annotations

import argparse

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
from starter.agent import Agent

RULE = "-" * 78


def transcript(sample: dict, agent: Agent, catalog_ids, categories, products) -> None:
    target = str(sample["ground_truth"]["parent_asin"])
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}

    session_id = f"demo_{sample['sample_id']}"
    agent.reset(session_id, sample["user_profile"])
    state = agent._states[session_id]

    print(RULE)
    print(f"session {sample['sample_id']}   scenario={sample['scenario_type']}   "
          f"difficulty={sample.get('difficulty_bucket', '?')}")
    print(f"target: {str(products[target].get('title'))[:70]}")
    print(f"profile: tags={list(state.profile_tags)}  "
          f"signature={state.profile_signature}  "
          f"seen before: {'yes' if state.profile_prior else 'no'}")
    print(RULE)

    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    message = initial_message(effective, coarse_category(categories.get(target, [])), disclosed)

    for turn in range(1, MAX_TURNS + 1):
        print(f"\nTURN {turn}")
        print(f"  shopper : {message[:100]}")
        response = agent.respond(session_id, message, turn, TOP_K)
        state = agent._states[session_id]
        window = normalize_recommendations(response.get("recommendations"), catalog_ids)

        print(f"  distilled slots : {dict(state.slots)}")
        print(f"  query           : {state.query[:90]}")
        print(f"  consistent set  : {state.card_consistent} product(s) from "
              f"{state.disclosed_count} disclosed constraint(s)")
        print(f"  STRATEGY        : {state.strategy}")
        print(f"    because       : {state.strategy_reason}")
        print(f"  agent   : {response['message'][:90]}")
        print(f"  asks    : {response['ask_attribute']}")
        print(f"  returns : {len(window)} recommendation(s)"
              + (f", target at rank {window.index(target) + 1}" if target in window else ""))

        if override_applied and target in window:
            print(f"\n  >>> HIT on turn {turn} at rank {window.index(target) + 1}")
            break
        if turn == MAX_TURNS:
            print("\n  >>> no hit")
            break

        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            message = str(override.get("message", "Actually, please ignore my earlier preference."))
            print("  (the shopper is about to override an earlier preference)")
        else:
            message, boundary_used = customer_reply(
                effective, response.get("ask_attribute"), disclosed, boundary_used
            )


def memory_view(samples, agent, catalog_ids, categories, products, limit: int = 40) -> None:
    """Run sessions in order and show a profile being recognised on return."""
    from starter.profile import signature_of

    counts: dict[str, int] = {}
    for sample in samples:
        counts[signature_of(sample["user_profile"])] = counts.get(signature_of(sample["user_profile"]), 0) + 1
    recurring = {sig for sig, n in counts.items() if n > 1}
    print(f"{len(counts)} distinct profiles across {len(samples)} sessions; "
          f"{len(recurring)} recur\n")

    shown = 0
    for sample in samples[:limit]:
        signature = signature_of(sample["user_profile"])
        if signature not in recurring:
            continue
        seen_before = agent._profiles.sessions_seen(signature)
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        session_id = f"mem_{sample['sample_id']}"
        agent.reset(session_id, sample["user_profile"])
        state = agent._states[session_id]
        message = initial_message(effective, coarse_category(categories.get(target, [])), set())
        agent.respond(session_id, message, 1, TOP_K)

        if seen_before:
            top = sorted(state.profile_prior.items(), key=lambda kv: -kv[1])[:8]
            print(f"{sample['sample_id']}  profile {signature} seen {seen_before}x before")
            print(f"   carried forward: {[t for t, _ in top] or '(nothing yet)'}")
            shown += 1
            if shown >= 6:
                break
    if not shown:
        print("(no profile recurred within the sampled window)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--sample", default="", help="sample_id, default the first session")
    parser.add_argument("--memory", action="store_true", help="show long-term profile accumulation")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    agent = Agent(args.catalog)

    if args.memory:
        memory_view(samples, agent, catalog_ids, categories, products)
        return

    chosen = next((s for s in samples if s["sample_id"] == args.sample), samples[0])
    transcript(chosen, agent, catalog_ids, categories, products)


if __name__ == "__main__":
    main()
