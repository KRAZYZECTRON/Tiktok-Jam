"""Re-run the load-bearing numbers the documentation asserts.

The headline claim of this submission is not the score, it is that everything is
measured. One wrong number in the README undermines that whole claim, and stale
figures have already slipped through five times: a retired recall ceiling, a
per-scenario table left at an earlier stage, perf figures carried forward
unchanged, a frozen contract describing fields that no longer existed, and
robustness numbers quoted as measurements when they were single-seed draws.

Every check here re-runs the measurement and compares it to what the docs say.
Run it before submitting, and after any change to `starter/`.

    py -m tools.verify_claims              # fast checks only (~2 min)
    py -m tools.verify_claims --slow       # adds perf and memory (~4 min)

Exit status is non-zero if any claim fails, so it can gate a commit.

Deliberately NOT checked here: anything needing torch (the dense leg) or a
running Ollama (the LLM stage). Both are optional and off, and a verification
tool that cannot run on a clean checkout is not a verification tool. Their
numbers are marked in SCOREBOARD as requiring those dependencies.
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
from collections import Counter, defaultdict

from evaluator.local_evaluator import (
    Agent,
    MAX_TURNS,
    catalog_index,
    evaluate,
    intent_card,
    load_jsonl,
)

CATALOG = "data/catalog.jsonl"
DATASET = "data/public_set.jsonl"


# Literals that were true once and must not be presented as current state.
# SCOREBOARD.md keeps history deliberately, so it is exempt where noted.
SUPERSEDED = [
    ("MRR 0.9438", "pre-fuzzy-tier MRR", ("SCOREBOARD.md",)),
    ("score 0.9522", "pre-fuzzy-tier score", ("SCOREBOARD.md",)),
    ("80 tests", "test count before the ranking suite landed", ()),
    ("0.78 than 0.81", "hidden-set estimate superseded by holdout_synth", ()),
]

# A dated log records what was measured at the time. Rewriting it would be
# falsifying it, so it is never scanned.
DOC_SCAN_SKIP = {"OVERNIGHT_LOG.md"}


def superseded_hits(filename: str, text: str) -> list[str]:
    """Superseded literals presented as current, as 'file:line: ...' strings.

    Markdown emphasis is stripped before matching. That is not cosmetic: the
    first version of this scanner missed `MRR **0.9438**` entirely because it
    compared against the raw line, and the gap was only found by deliberately
    injecting drift and watching one of two planted figures slip through.
    """
    if filename in DOC_SCAN_SKIP:
        return []
    out = []
    for literal, why, exempt in SUPERSEDED:
        if filename in exempt:
            continue
        for i, raw in enumerate(text.splitlines(), 1):
            if literal in raw.replace("*", "").replace("`", ""):
                out.append(f"{filename}:{i}: superseded literal {literal!r} ({why})")
    return out


# claim -> (expected, tolerance). Tolerances are deliberately tight: these are
# deterministic measurements, not estimates.
CLAIMS: list[tuple[str, float, float]] = []
results: list[tuple[str, str, float, float, bool]] = []


def check(label: str, actual: float, expected: float, tol: float, unit: str = "") -> bool:
    ok = abs(actual - expected) <= tol
    results.append((label, unit, actual, expected, ok))
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="skip the documentation-drift scan (it shells out to pytest --collect-only)",
    )
    parser.add_argument("--slow", action="store_true", help="also check perf and memory")
    args = parser.parse_args()

    samples = load_jsonl(DATASET)
    catalog_ids, categories, products = catalog_index(CATALOG)

    # --- headline score -----------------------------------------------------
    result = evaluate(Agent(CATALOG), samples, catalog_ids, categories, products)
    check("clean technical score", result["recommended_technical_score"], 0.953064, 1e-6)
    check("clean Hit@10", result["hit_rate_at_10"], 1.0000, 1e-6)
    check("clean MRR", result["mrr"], 0.9465, 5e-4)
    check("clean MTTC", result["mttc"], 2.545, 5e-3)

    sessions = result["sessions"]

    # --- README/SCOREBOARD structural claims --------------------------------
    at_rank_one = sum(1 for s in sessions if s["best_rank"] == 1)
    check("sessions at rank 1 (docs say 183)", at_rank_one, 183, 3, "sessions")

    not_rank_one = [s for s in sessions if s["best_rank"] and s["best_rank"] > 1]
    mrr_cost = sum(1 - 1 / s["best_rank"] for s in not_rank_one) / len(sessions) * 0.30
    check("MRR cost of non-rank-1 sessions", mrr_cost, 0.0160, 3e-3)

    by_scenario = defaultdict(list)
    for s in sessions:
        by_scenario[s["scenario_type"]].append(s)
    late_override = sum(1 for s in by_scenario["intent_override"] if s["first_hit_turn"] > 2)
    check("intent_override sessions hitting after turn 2 (docs say all 30)",
          late_override, 30, 0, "sessions")
    late_boundary = sum(1 for s in by_scenario["boundary"] if s["first_hit_turn"] > 2)
    check("boundary sessions hitting after turn 2 (docs say all 10)",
          late_boundary, 10, 0, "sessions")

    # --- the identification result, the core mechanism claim ----------------
    from starter.simcard import card_slots

    index = defaultdict(set)
    for asin, product in products.items():
        for slot in card_slots(product):
            index[slot].add(asin)

    unique, sizes = 0, []
    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        card = intent_card(products[target])
        disclosed = [str(v).lower() for v in card["hard_constraints"] + card["soft_preferences"]]
        sets = [index.get(value, set()) for value in disclosed if value]
        consistent = len(set.intersection(*sets)) if sets else len(products)
        sizes.append(consistent)
        if consistent == 1:
            unique += 1
    sizes.sort()
    check("sessions where the card uniquely identifies the target (docs say 147)",
          unique, 147, 0, "sessions")
    check("median consistent-product set size (docs say 1)",
          sizes[len(sizes) // 2], 1, 0, "products")

    # --- simcard fidelity: the mechanism everything rests on ----------------
    # Checked over the WHOLE catalog, not the 200 public targets. Those 200 are
    # the products the ranking was tuned against, so agreement on them says
    # nothing about the hidden 800 -- whose targets are drawn from the other
    # 49,800. This is the claim `tools/holdout_synth.py` depends on to be able
    # to synthesise a valid session for any product at all.
    mismatches = 0
    for product in products.values():
        card = intent_card(product)
        theirs = {str(v).lower() for v in card["hard_constraints"] + card["soft_preferences"]}
        if not theirs <= set(card_slots(product)):
            mismatches += 1
    check("simcard reconstruction mismatches across the whole catalog (must be 0)",
          mismatches, 0, 0, "products")
    check("...products actually checked (docs say all 50,000)", len(products), 50000, 0, "products")

    # --- the hold-back cliff, quoted in three places ------------------------
    import starter.agent as agent_mod

    saved = (agent_mod.MIN_DISCLOSED, agent_mod.HOLD_UNTIL_TURN, agent_mod.ANSWER_IF_CONSISTENT)
    try:
        # Both configurations, because they say different things. With
        # early-answering on, a mis-set hold is survivable; with it off, the same
        # setting is catastrophic. The docs previously quoted only the second
        # number, measured before early-answering existed.
        agent_mod.MIN_DISCLOSED, agent_mod.HOLD_UNTIL_TURN = 5, 3
        cliff = evaluate(Agent(CATALOG), samples, catalog_ids, categories, products)
        check("hold<=3/min=5, early-answering ON", cliff["recommended_technical_score"], 0.8279, 0.02)

        agent_mod.ANSWER_IF_CONSISTENT = 0
        bare = evaluate(Agent(CATALOG), samples, catalog_ids, categories, products)
        check("hold<=3/min=5, early-answering OFF", bare["recommended_technical_score"], 0.2215, 0.02)

        agent_mod.MIN_DISCLOSED, agent_mod.HOLD_UNTIL_TURN = 9, 10
        worst = evaluate(Agent(CATALOG), samples, catalog_ids, categories, products)
        check("unbounded hold with no safety net scores zero",
              worst["recommended_technical_score"], 0.0, 1e-9)
    finally:
        agent_mod.MIN_DISCLOSED, agent_mod.HOLD_UNTIL_TURN, agent_mod.ANSWER_IF_CONSISTENT = saved

    # --- sweep tables SCOREBOARD quotes, so they cannot drift unnoticed -----
    import starter.ranking as ranking_mod

    def with_weight(attribute: str, value: float) -> float:
        held = getattr(ranking_mod, attribute)
        setattr(ranking_mod, attribute, value)
        try:
            return evaluate(Agent(CATALOG), samples, catalog_ids, categories,
                            products)["recommended_technical_score"]
        finally:
            setattr(ranking_mod, attribute, held)

    # Both were real gains when adopted and are now near-inert. The check is
    # that the *documented current* values still hold, not the historical ones.
    check("BONUS_EXACT_PHRASE=0 (docs: near-inert at 0.952981)",
          with_weight("BONUS_EXACT_PHRASE", 0.0), 0.952981, 5e-4)
    check("WEIGHT_CATEGORY=1.0 (docs: 0.953314, a plateau)",
          with_weight("WEIGHT_CATEGORY", 1.0), 0.953314, 5e-4)

    # --- the pure-stdlib guarantee ------------------------------------------
    import starter.retrieval as retrieval_mod

    check("dense retrieval is OFF by default", float(retrieval_mod._DENSE_ENABLED), 0.0, 0.0)
    check("reported prompt tokens", result["reported_token_usage"]["prompt_tokens"], 0, 0, "tokens")
    check("reported completion tokens", result["reported_token_usage"]["completion_tokens"], 0, 0, "tokens")

    if args.slow:
        import time
        import tracemalloc

        agent = Agent(CATALOG)
        tracemalloc.start()
        latencies = []
        for sample in samples[:60]:
            agent.reset(sample["sample_id"], sample["user_profile"])
            started = time.perf_counter()
            agent.respond(sample["sample_id"], "I'm looking for Clothing Tops. A key requirement is: cotton.", 1, 10)
            latencies.append((time.perf_counter() - started) * 1000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # 735 MB was wrong twice over and the docs now say so explicitly: it
        # charged the evaluator's own 50k dict to us, and tracemalloc cannot see
        # SQLite's C-heap FTS index at all. The documented figure is 235 MB RSS
        # via GetProcessMemoryInfo. tracemalloc measures a different thing, so
        # this check is a loose sanity bound, not the documented number.
        check("tracemalloc peak (sanity bound, not the 235 MB RSS figure)", peak / 1e6, 200, 180, "MB")
        check("per-turn mean latency (docs say ~58 ms)", statistics.fmean(latencies), 58, 45, "ms")

    # --- documentation drift -------------------------------------------------
    # Every check above re-runs a measurement. None of them notice when a doc
    # quotes a number nobody registered here -- which is how six figures went
    # stale at once: the per-scenario intent_override MRR, two "Current main"
    # lines, a pillar table row, a superseded hidden-set estimate, a test count,
    # and a hold-back threshold that had moved 4 -> 3 in the code.
    #
    # So this scans the docs that make CURRENT-STATE claims and requires the live
    # value to appear. OVERNIGHT_LOG.md is excluded on purpose: it is a dated
    # log, and rewriting what a past entry measured would be falsifying it.
    if not args.no_docs:
        import re as _re
        import subprocess as _sp

        collected = _sp.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
            capture_output=True, text=True,
        )
        m = _re.search(r"(\d+) tests? collected", collected.stdout)
        live_tests = int(m.group(1)) if m else -1

        import starter.agent as _agent_mod

        live = {
            "score": f"{result['recommended_technical_score']:.6f}",
            "mrr": f"{result['mrr']:.4f}",
            "mttc": f"{result['mttc']:.3f}".rstrip("0").rstrip("."),
            "io_mrr": f"{result['scenario_metrics']['intent_override']['mrr']:.4f}",
            "tests": str(live_tests),
            "min_disclosed": str(_agent_mod.MIN_DISCLOSED),
            "claims": str(len(results)),
        }

        # (file, human description, regex that must match somewhere in the file)
        required = [
            ("README.md",   "headline technical score",      rf"{live['score']}"),
            ("README.md",   "current MRR",                   rf"{live['mrr']}"),
            ("README.md",   "test count",                    rf"{live['tests']} tests"),
            ("REPORT.md",   "headline technical score",      rf"{live['score']}"),
            ("REPORT.md",   "current MRR",                   rf"{live['mrr']}"),
            ("REPORT.md",   "intent_override MRR",           rf"{live['io_mrr']}"),
            ("REPORT.md",   "test count",                    rf"{live['tests']} tests"),
            ("DEVPOST.md",  "headline technical score",      rf"{live['score']}"),
            ("DEVPOST.md",  "current MRR",                   rf"{live['mrr']}"),
            ("SCOREBOARD.md", "intent_override MRR",         rf"{live['io_mrr']}"),
            ("AGENTS.md",   "current-main score",            rf"{live['score']}"),
            ("CLAUDE.md",   "current-main score",            rf"{live['score']}"),
            ("TASKS.md",    "current-main score",            rf"{live['score']}"),
            ("TASKS.md",    "current MRR",                   rf"{live['mrr']}"),
        ]

        doc_failures = []
        for fname, what, pattern in required:
            path = pathlib.Path(fname)
            if not path.exists():
                doc_failures.append(f"{fname}: missing, cannot check {what}")
                continue
            if not _re.search(pattern, path.read_text(encoding="utf-8")):
                doc_failures.append(f"{fname}: {what} -- expected /{pattern}/, not found")

        for path in sorted(pathlib.Path(".").glob("*.md")):
            doc_failures.extend(
                superseded_hits(path.name, path.read_text(encoding="utf-8"))
            )

        print()
        if doc_failures:
            print(f"documentation drift -- {len(doc_failures)} problem(s):")
            for f in doc_failures:
                print(f"  {f}")
        else:
            print(
                f"documentation scan clean: {len(required)} current-state claims "
                f"match the live run, no superseded literals presented as current."
            )
        results.append(
            ("documentation free of drift", "", len(doc_failures), 0, not doc_failures)
        )

    # --- report -------------------------------------------------------------
    width = max(len(label) for label, *_ in results)
    print(f"{'claim':<{width}}  {'measured':>12}  {'documented':>12}   ")
    print("-" * (width + 34))
    failed = 0
    for label, unit, actual, expected, ok in results:
        mark = "ok" if ok else "MISMATCH"
        if not ok:
            failed += 1
        print(f"{label:<{width}}  {actual:>12.6g}  {expected:>12.6g}   {mark}")
    print()
    if failed:
        print(f"{failed} of {len(results)} documented claims no longer hold. Fix the docs or the code.")
    else:
        print(f"all {len(results)} documented claims re-verified against a fresh run.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
