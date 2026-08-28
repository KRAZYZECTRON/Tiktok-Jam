# CLAUDE.md — TechJam 2026, Track 4 (Shopping Copilot)

## What this is
Conversational product search: hybrid retrieval → dialog state → LLM re-ranking,
scored by the local evaluator against Hit@10 / MRR / MTTC.

## Frozen contract — do not change a signature here without posting it
## in the team channel first.

# starter/state.py — shared dataclasses
@dataclass
class Candidate:
    parent_asin: str
    score: float | None = None

@dataclass
class DialogState:
    session_id: str
    user_profile: dict
    catalog_path: str = "data/catalog.jsonl"
    turn: int = 0
    messages: list[str] = field(default_factory=list)

# starter/retrieval.py — Seat 2
def retrieve(query: str, state: DialogState, top_k: int) -> list[Candidate]:
    """Hybrid BM25 + dense retrieval over the catalog."""

# starter/dialog.py — Seat 3
def update_state(state: DialogState, message: str, turn: int) -> DialogState:
    """Slot accumulation, intent override, 10-turn budget, clarification triggers."""

# starter/ranking.py — Seat 1
def rank(candidates: list[Candidate], state: DialogState) -> list[Candidate]:
    """LLM semantic re-ranking over the top-N from retrieve()."""

# starter/agent.py — shared orchestrator (not owned by one seat)
# Agent.reset() builds the initial DialogState from user_profile.
# Agent.respond() just calls update_state() -> retrieve() -> rank() and
# formats the result. Anyone touching this file flags it in the team
# channel first — it's the one place all three seats' work threads together.

# Evaluator entry point: python3 -m evaluator.local_evaluator

## Hard rules
- 10-turn cap. The harness owns it, not us: evaluator/local_evaluator.py loops
  `for turn in range(1, MAX_TURNS + 1)`, so the agent is never called an 11th
  time and cannot exceed the cap. update_state() still holds the cap for its own
  bookkeeping, but there is nothing to enforce and nothing to work around.
  (Earlier versions of this file said exceeding the cap was "a forced
  termination AND a zero score, not just a worse metric." That was wrong —
  verified against the evaluator. A session that runs out scores hit=False,
  reciprocal_rank=0.0, and contributes MAX_TURNS + 1 to MTTC: exactly a worse
  metric. The correction is kept visible because the false version had already
  propagated into starter/dialog.py and into the seat briefs.)
- The loop breaks on the first hit, so an unused turn costs nothing. Never
  terminate early and never withhold recommendations to "stay safe" — doing so
  gives up free retries and strictly loses points.
- Local scoring is against the 200 public dev sessions only — the organizer
  holds 800 additional hidden sessions for final scoring, with different
  users and products, so don't over-tune to quirks of the visible 200.
- evaluator/ and data/ are read-only. Nobody edits the scorer or the catalog
  to make a number move.
- Always re-run the evaluator after touching retrieve(), update_state(),
  or rank() — an unscored change isn't progress yet.
- Never two agents touch the same file at once.
- starter/agent.py is shared orchestration code — flag changes there in the
  team channel first, same as a signature change.
- Only Seat 1 merges into main. Everyone else proposes via PR from their branch.
- Each branch's evaluator run writes its own output file (results_retrieval.json,
  results_dialog.json, …) — never results.json — until it's merged into main.

## Branches
main — integration, Seat 1 only · retrieval — Seat 2 · dialog — Seat 3

## Current baseline
BM25 keyword-only: Hit@10 ≈ 0.125, MRR ≈ 0.068, MTTC ≈ 9.81 (10-turn cap).
