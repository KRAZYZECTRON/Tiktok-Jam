"""Stress the agent against a shopper who does not phrase things verbatim.

This exists because most of our score above ~0.87 rests on string equality with
text the simulator lifts from the target product:

  * `BONUS_EXACT_PHRASE`   - disclosed phrase contained intact in the product
  * `BONUS_EXACT_CATEGORY` - opening category contained intact in `categories`
  * card-slot consistency  - disclosed constraint EQUALS one of the product's
                             own reconstructed intent-card slots

The competition spec says plainly: "If natural-language paraphrasing is added by
the organizer, it cannot decide correctness." So a paraphrasing shopper is an
allowed variation of the hidden 800, and all three signals would degrade at once.

This runs the evaluator's own protocol with the shopper's *wording* perturbed,
never the ground truth, and reports how far the score falls. It does not modify
`evaluator/` -- it wraps the message functions at call time.

    py -m tools.robustness                # all levels
    py -m tools.robustness --level heavy

Levels, in rough order of how much a real deployment would see:

  none    unchanged, to confirm the harness reproduces the headline number
  light   casing and punctuation drift
  medium  filler phrases and clause reordering around the constraint
  heavy   light lexical paraphrase of the constraint itself
"""
from __future__ import annotations

import argparse
import random
import re

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    metric_summary,
    normalize_recommendations,
)
from starter.agent import Agent

FILLERS = (
    "I think ", "honestly ", "if possible ", "ideally ", "something like ",
)
# Deliberately conservative: swaps that a person would obviously accept as the
# same requirement, so a degradation here cannot be dismissed as a broken test.
SYNONYMS = {
    "100%": "pure",
    "closure": "fastening",
    "imported": "not domestically made",
    "lightweight": "light",
    "adjustable": "you can adjust it",
    "comfortable": "comfy",
    "durable": "hard-wearing",
    "pull on": "slip on",
    "long sleeve": "with long sleeves",
    "short sleeve": "with short sleeves",
    "machine wash": "washable in a machine",
}


def perturb(text: str, level: str, rng: random.Random) -> str:
    if not text or level == "none":
        return text
    if level == "light":
        out = text
        if rng.random() < 0.5:
            out = out.replace(";", ",")
        if rng.random() < 0.5:
            out = re.sub(r"\s+", " ", out).strip().rstrip(".")
        if rng.random() < 0.4:
            out = out[:1].lower() + out[1:]
        return out
    if level == "medium":
        out = text
        if rng.random() < 0.7:
            out = out.replace("what matters is:", rng.choice([
                "the thing that matters is", "what I care about is",
                "what's important to me is",
            ]))
        if rng.random() < 0.6:
            out = out.replace(": ", ": " + rng.choice(FILLERS), 1)
        return re.sub(r"\s+", " ", out).strip()
    # heavy: medium, plus lexical substitution inside the constraint itself
    out = perturb(text, "medium", rng)
    lowered = out.lower()
    for source, target in SYNONYMS.items():
        if source in lowered:
            out = re.sub(re.escape(source), target, out, count=1, flags=re.I)
    return out


def run(samples, agent_factory, catalog_ids, categories, products, level: str, seed: int = 11) -> dict:
    rng = random.Random(seed)
    agent = agent_factory()
    sessions = []
    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        message = perturb(
            initial_message(effective, coarse_category(categories.get(target, [])), disclosed),
            level, rng,
        )
        session_id = f"rb_{sample['sample_id']}"
        agent.reset(session_id, sample["user_profile"])
        hit_turn = best_rank = None

        for turn in range(1, MAX_TURNS + 1):
            try:
                response = agent.respond(session_id, message, turn, TOP_K)
            except Exception:
                response = {"message": "", "ask_attribute": None, "recommendations": []}
            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if override_applied and target in ranked:
                best_rank = ranked.index(target) + 1
                hit_turn = turn
                break
            if turn == MAX_TURNS:
                break
            override = effective.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                message = perturb(str(override.get("message", "")), level, rng)
            else:
                raw, boundary_used = customer_reply(
                    effective, response.get("ask_attribute"), disclosed, boundary_used
                )
                message = perturb(raw, level, rng)

        sessions.append({
            "hit": hit_turn is not None,
            "first_hit_turn": hit_turn,
            "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
        })

    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    overall["efficiency"] = round(efficiency, 6)
    overall["score"] = round(
        0.50 * overall["hit_rate_at_10"] + 0.30 * overall["mrr"] + 0.20 * efficiency, 6
    )
    return overall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--level", default="", help="none|light|medium|heavy")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    levels = [args.level] if args.level else ["none", "light", "medium", "heavy"]

    print(f"{'level':<9}{'Hit@10':>9}{'MRR':>10}{'MTTC':>8}{'score':>10}{'vs none':>10}")
    base = None
    for level in levels:
        r = run(samples, lambda: Agent(args.catalog), catalog_ids, categories, products, level)
        if base is None:
            base = r["score"]
        print(f"{level:<9}{r['hit_rate_at_10']:>9.4f}{r['mrr']:>10.4f}"
              f"{r['mttc']:>8.3f}{r['score']:>10.6f}{r['score'] - base:>+10.6f}")


if __name__ == "__main__":
    main()
