# CLAUDE.md — TechJam 2026, Track 4 (Shopping Copilot)

## What this is
Conversational product search: intent-routed multi-route retrieval → accumulated
dialog state → rank-fusion re-ranking with simulator-card identification, scored
by the local evaluator against Hit@10 / MRR / MTTC.

**The default scoring path is pure Python standard library** — no numpy, no
model weights, no network. Two optional routes exist and are both off by
default, each because it was measured and lost:
- dense/vector retrieval (`TJ_DENSE=1`) — 0.9254 vs 0.9522, and ~13 min of CPU
  to embed the catalog cold;
- LLM semantic re-ranking (`RANK_USE_LLM=1`) — costs 0.014 after rank fusion.

Official scoring may run offline and CPU-only, so nothing load-bearing may
depend on either. Verified by simulating the absence of numpy, torch and
sentence-transformers together: still 0.952231.

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
    # --- written by ranking.rank(), read by agent.py ---
    card_consistent: int = 0   # pooled candidates still consistent with all
                               # disclosed constraints; the agent's confidence
    disclosed_count: int = 0

# starter/retrieval.py — Seat 2
def retrieve(query: str, state: DialogState, top_k: int) -> list[Candidate]:
    """Intent-routed multi-route retrieval. BM25 (SQLite FTS5) always; an
    optional dense leg behind TJ_DENSE=1, fused by reciprocal rank."""

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
  agent.py holds its answer back on turns 1-2 until MIN_DISCLOSED (currently 3)
  are disclosed, and always answers from turn 3. The spec's own wording permits
  it:
  the README lists asking a clarification question as a standalone option,
  separate from returning a ranked list.
  The bound matters more than the threshold, and the failure is total. Measured
  now, with the shipped `ANSWER_IF_CONSISTENT=4`:

  | config | Hit@10 | score |
  |---|---|---|
  | `hold<=2 min=3` (shipped) | 1.0000 | 0.9531 |
  | `hold<=3 min=5` | 0.8650 | 0.8279 |
  | `hold<=10 min=9` | 0.7900 | 0.7617 |

  and with early-answering disabled:

  | config | Hit@10 | score |
  |---|---|---|
  | `hold<=3 min=5` | 0.2400 | 0.2215 |
  | `hold<=10 min=9` | **0.0000** | **0.000000** |

  **Two independent mechanisms defend this failure, and only one was written
  down.** `HOLD_UNTIL_TURN` bounds the wait; `ANSWER_IF_CONSISTENT` rescues a
  session whose candidate set has already collapsed even when the turn budget
  says keep waiting. Remove either and a mis-set threshold degrades; remove both
  and it scores **zero**. `ANSWER_IF_CONSISTENT` looks like a +0.0037 nicety in
  the scoreboard — it is also a safety net. **Do not delete it as dead weight.**
  **Never remove HOLD_UNTIL_TURN.**
- **MIN_DISCLOSED and ANSWER_IF_CONSISTENT are trades against ranking quality,
  not constants.** Improving the ranker moved both optima: the threshold went
  4 → 3, and early-answering went from rejected to adopted. Re-check both
  whenever ranking changes materially. This is the one coupling in the pipeline
  where a local improvement silently invalidates a setting in another module.
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
Current `main`: **Hit@10 1.0000 · MRR 0.9465 · MTTC 2.545 · score 0.953064**.
Held out on targets never tuned on: **0.9212** (four draws). That is the
number that predicts the hidden 800; treat 0.953064 as the ceiling.
The kit's shipped baseline was 0.1250 / 0.0680 / 9.81 / 0.1067.

Per-scenario and the full history are in `SCOREBOARD.md`, which also records
what to read before changing anything:
- the old "recall@500 caps Hit@10 at 0.860" ceiling is **retired** — it was
  measured on the turn-1 query only and we are above it;
- a **Tested and rejected** table, so nobody re-derives a dozen dead ends;
- the dead-turn rotation in `agent.py` and the turn-1-2 hold-back are the two
  mechanisms a judge might question. Both have kill switches (`TJ_ROTATE=off`,
  `TJ_MIN_DISCLOSED=0`) and both are disclosed in the README.

**TechnicalScore is not a judging criterion.** It is one input to Technical
Execution (35%); Innovation 20%, Impact 20%, Feasibility 15% and Presentation
10% are scored on the writeup, the architecture and the demo. Do not trade a
named requirement from the four pillars for a small score gain — that mistake
was already made once, by declining to merge the retrieval branch on score
grounds.
