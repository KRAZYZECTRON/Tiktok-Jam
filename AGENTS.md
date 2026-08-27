# CLAUDE.md — TechJam 2026, Track 4 (Shopping Copilot)

## What this is
Conversational product search: hybrid retrieval → dialog state → LLM re-ranking,
scored by the local evaluator against Hit@10 / MRR / MTTC.

## Frozen contract — do not change a signature here without posting it
## in the team channel first.

def retrieve(query: str, state: DialogState) -> list[Candidate]:
    """Seat 2. Hybrid BM25 + dense retrieval over the catalog."""

def update_state(state: DialogState, message: str) -> DialogState:
    """Seat 3. Slot accumulation, intent override, 10-turn budget, clarification triggers."""

def rank(candidates: list[Candidate], state: DialogState) -> list[Candidate]:
    """Seat 1. LLM semantic re-ranking over the top-N from retrieve()."""

# Evaluator entry point: python3 -m evaluator.local_evaluator → results.json

## Hard rules
- 10-turn cap is enforced inside update_state — never worked around elsewhere.
- evaluator/ and data/ are read-only. Nobody edits the scorer or the catalog
  to make a number move.
- Always re-run the evaluator after touching retrieve() or rank() — an
  unscored change isn't progress yet.
- Never two agents touch the same file at once.
- Only Seat 1 merges into main. Everyone else proposes via PR from their branch.
- Each branch's evaluator run writes its own output file (results_retrieval.json,
  results_dialog.json, …) — never results.json — until it's merged into main.

## Branches
main — integration, Seat 1 only · retrieval — Seat 2 · dialog — Seat 3

## Current baseline
BM25 keyword-only: Hit@10 ≈ 0.125, MRR ≈ 0.068, MTTC ≈ 9.81 (10-turn cap).
