"""Measure latency and token cost of the scored path.

docs/submission_rules.md requires "a disclosure of latency, token usage, and
estimated model cost". This produces those numbers rather than estimating them,
and it exercises the real Agent over the real protocol.

Reports cold start (index build, paid once per process) separately from
steady-state per-turn latency, because the organizer's timeout almost certainly
applies to one or the other and they differ by three orders of magnitude.

    py -m tools.perf
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
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
from starter.agent import Agent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output", default="results_perf.json")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    agent = Agent(args.catalog)

    # --- cold start: first respond() pays for the FTS index and the IDF table
    first = samples[0]
    card, behavior = materialize_hidden_fields(first, products)
    target = str(first["ground_truth"]["parent_asin"])
    opening = initial_message(
        {**first, "intent_card": card, "behavior": behavior},
        coarse_category(categories.get(target, [])),
        set(),
    )
    agent.reset("warm", first["user_profile"])
    started = time.perf_counter()
    agent.respond("warm", opening, 1, TOP_K)
    cold_start = time.perf_counter() - started

    # --- steady state
    latencies: list[float] = []
    prompt_tokens = completion_tokens = 0
    sessions = 0
    wall_started = time.perf_counter()

    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        message = initial_message(effective, coarse_category(categories.get(target, [])), disclosed)

        session_id = f"perf_{sample['sample_id']}"
        agent.reset(session_id, sample["user_profile"])
        sessions += 1

        for turn in range(1, MAX_TURNS + 1):
            started = time.perf_counter()
            response = agent.respond(session_id, message, turn, TOP_K)
            latencies.append(time.perf_counter() - started)

            usage = response.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)

            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if override_applied and target in ranked:
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
                    effective, response.get("ask_attribute"), disclosed, boundary_used
                )

    wall = time.perf_counter() - wall_started
    ordered = sorted(latencies)

    def pct(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(p * len(ordered)))]

    report = {
        "sessions": sessions,
        "turns": len(latencies),
        "cold_start_seconds": round(cold_start, 3),
        "per_turn_ms": {
            "mean": round(statistics.fmean(latencies) * 1000, 2),
            "p50": round(pct(0.50) * 1000, 2),
            "p95": round(pct(0.95) * 1000, 2),
            "p99": round(pct(0.99) * 1000, 2),
            "max": round(max(latencies) * 1000, 2),
        },
        "wall_seconds_200_sessions": round(wall, 2),
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "estimated_model_cost_usd": 0.0,
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"sessions              {sessions}")
    print(f"turns                 {len(latencies)}")
    print(f"cold start            {report['cold_start_seconds']:.3f} s  (index build, once per process)")
    print(f"per-turn mean         {report['per_turn_ms']['mean']:.2f} ms")
    print(f"per-turn p50 / p95    {report['per_turn_ms']['p50']:.2f} / {report['per_turn_ms']['p95']:.2f} ms")
    print(f"per-turn p99 / max    {report['per_turn_ms']['p99']:.2f} / {report['per_turn_ms']['max']:.2f} ms")
    print(f"wall, 200 sessions    {report['wall_seconds_200_sessions']:.2f} s")
    print(f"tokens                {report['tokens']['total']}  (prompt {report['tokens']['prompt']}, completion {report['tokens']['completion']})")
    print(f"estimated model cost  ${report['estimated_model_cost_usd']:.2f}")


if __name__ == "__main__":
    main()
