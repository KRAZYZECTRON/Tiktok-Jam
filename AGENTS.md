# CLAUDE.md — TechJam 2026, Track 4 (Shopping Copilot)

## What this is
Conversational product search: BM25 retrieval over a wide pool → accumulated
dialog state → rank-fusion re-ranking, scored by the local evaluator against
Hit@10 / MRR / MTTC.

The whole scoring path is **pure Python standard library** — no numpy, no model
weights, no network. That is deliberate: official scoring may run offline and
CPU-only, so anything that changes it has to justify itself against that.

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
    # --- written by dialog.py, read by agent.py and ranking.py ---
    # Additive only; every consumer uses getattr with a fallback, so reverting
    # dialog.py degrades the pipeline instead of breaking it.
    slots: dict[str, str] = field(default_factory=dict)
    category: str = ""
    query: str = ""            # what retrieve() sees, NOT the raw turn message
    ask_attribute: str | None = None
    exhausted_attributes: set[str] = field(default_factory=set)
    exhausted_turns: int = 0

# starter/retrieval.py — Seat 2
def retrieve(query: str, state: DialogState, top_k: int) -> list[Candidate]:
    """Hybrid BM25 + dense retrieval over the catalog."""

# starter/dialog.py — Seat 3
def update_state(state: DialogState, message: str, turn: int) -> DialogState:
    """Slot accumulation, intent override, 10-turn budget, clarification triggers."""

# starter/ranking.py — Seat 1
def rank(candidates: list[Candidate], state: DialogState) -> list[Candidate]:
    """Reciprocal-rank fusion of retrieve()'s ordering with a state-aware
    lexical score. Optional LLM stage behind RANK_USE_LLM=1, off by default."""

# starter/agent.py — shared orchestrator (not owned by one seat)
# Agent.reset() builds the initial DialogState from user_profile.
# Agent.respond() just calls update_state() -> retrieve() -> rank() and
# formats the result. Anyone touching this file flags it in the team
# channel first — it's the one place all three seats' work threads together.

# Evaluator entry point: python3 -m evaluator.local_evaluator

## Hard rules
- 10-turn cap. The official problem statement states it as "Hard limit of 10
  turns per session (forced termination and zero score if exceeded)", and that
  is the rule we build to. In the shipped harness it is **structurally
  unreachable**: evaluator/local_evaluator.py loops
  `for turn in range(1, MAX_TURNS + 1)`, so the agent is never called an 11th
  time and cannot exceed the cap on its own. update_state() still holds the cap
  for its own bookkeeping.
  The practical consequence, which earlier versions of this file got backwards:
  because the cap cannot be breached from inside the agent, there is nothing to
  defend against, and a session that simply runs out of turns scores hit=False,
  reciprocal_rank=0.0 and MAX_TURNS + 1 toward MTTC. So do not spend design
  effort guarding a boundary the harness already enforces.
- The loop breaks on the first hit, so an unused turn costs nothing. Never
  terminate early.
- **Superseded (29 Aug): "never withhold recommendations to stay safe".** That
  was correct while Hit@10 was the binding metric — an extra turn was a free
  retry. Hit@10 is now 1.0000, so the binding metric is MRR, and the evaluator
  scores the rank at the *first* hit. Answering before the shopper has disclosed
  enough locks in a poor reciprocal rank for the whole session. The consistent-
  product set has median size 78 at two disclosed constraints and 1 at three, so
  agent.py holds its answer back on turns 1-2 until four are disclosed, and
  always answers from turn 3. Worth +0.041. The spec's own wording permits it:
  the README lists asking a clarification question as a standalone option,
  separate from returning a ranked list.
  The bound matters more than the threshold — see the cliff documented in
  agent.py. Never remove HOLD_UNTIL_TURN.
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

## Where we are
Current `main`: **Hit@10 0.9550 · MRR 0.5729 · MTTC 2.93 · score 0.8108**.
The kit's shipped baseline was 0.1250 / 0.0680 / 9.81 / 0.1067.

Per-scenario and the full history are in `SCOREBOARD.md`, which also records
two things worth knowing before changing anything:
- the old "recall@500 caps Hit@10 at 0.860" ceiling is **retired** — it was
  measured on the turn-1 query only, and we are now above it;
- the dead-turn rotation in `agent.py` is worth +0.018 and has a kill switch
  (`TJ_ROTATE=off`), because it is the one mechanism a judge might question.
