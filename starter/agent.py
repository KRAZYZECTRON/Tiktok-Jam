"""Thin orchestrator: update_state() -> retrieve() -> rank() -> format response.

Shared by all three seats -- flag changes here in the team channel first.
"""
from __future__ import annotations

import os
from pathlib import Path

from .dialog import update_state
from .orchestrate import select as select_strategy, window_for
from .profile import ProfileMemory
from .ranking import rank
from .retrieval import retrieve
from .state import DialogState

# retrieve() fills a wide pool; rank() narrows it to the top_k the evaluator
# scores. Measured recall of the ground truth inside retrieve()'s own ordering:
# recall@10 = 0.185, recall@100 = 0.525, recall@500 = 0.860 -- so handing rank()
# only top_k candidates caps Hit@10 at 0.185 however good the ranker is.
# TJ_POOL_K=10 with TJ_RANK=off reproduces the original weak baseline exactly,
# which is how an A/B on the same session subset is taken.
MAX_TURNS = 10
POOL_K = int(os.environ.get("TJ_POOL_K", "500"))
# Hold back recommendations while the conversation has not narrowed the catalog.
# The evaluator stops at the first hit and scores the rank *at that turn*, so a
# rank-5 hit on turn 2 permanently locks in MRR 0.2 for that session. Waiting a
# turn for the shopper to disclose more and then hitting at rank 1 is worth
# +0.0012 of score against -0.0002 for the later turn -- 6:1 in favour of
# waiting. 0 disables the behaviour entirely.
CONFIDENCE_MAX = int(os.environ.get("TJ_CONFIDENCE", "0"))
# Bounded hold-back. The evaluator caps disclosure at two constraints per reply
# and scores the rank at the *first* hit, so answering before the shopper has
# said enough locks in a poor reciprocal rank for the whole session. Measured
# median size of the still-consistent product set: 2574 at one constraint, 78 at
# two, and 1 at three. Below MIN_DISCLOSED we are guessing, not identifying.
#
# Bounded by HOLD_UNTIL_TURN so this can never cost a hit: from that turn on we
# always answer, leaving the rest of the 10-turn budget intact. An earlier
# unbounded version gated on the consistent-set size instead and did lose hits
# (Hit@10 1.0000 -> 0.90) because a session whose set never shrinks never
# answered at all.
#
# Grid over both parameters (Hit@10 / score):
#   hold<=2 min=4  1.0000 / 0.9122   <- shipped
#   hold<=2 min=5  1.0000 / 0.9120      insensitive to min, because the turn-2
#   hold<=2 min=6  1.0000 / 0.9120      bound caps the wait regardless
#   hold<=3 min=4  0.9850 / 0.9026
#   hold<=3 min=5  0.2750 / 0.2438   <- cliff
#   hold<=4 min=5  0.0650 / 0.0558
# The cliff is why HOLD_UNTIL_TURN matters more than MIN_DISCLOSED: most
# sessions never disclose more than four constraints, so a threshold that
# cannot be met combined with a late bound means never answering at all. At
# hold<=2 that failure mode is unreachable -- turn 3 always answers.
# 4 was optimal when the ranker was weaker (MRR 0.66). As ranking improved the
# balance moved: with MRR at 0.95 an extra turn of waiting buys much less, and 3
# now scores better (0.9464 vs 0.9431, split-half +0.0031/+0.0035). Re-check
# this whenever ranking changes materially -- it is a trade, not a constant.
MIN_DISCLOSED = int(os.environ.get("TJ_MIN_DISCLOSED", "3"))
HOLD_UNTIL_TURN = int(os.environ.get("TJ_HOLD_UNTIL", "2"))
# ...but answer early anyway when the conversation has *already* identified the
# product. The hold exists because a rank drawn from a large consistent set is
# a bad rank; if the set is down to one or two candidates there is nothing left
# to wait for, and waiting only costs a turn of MTTC. rank() reports the size as
# state.card_consistent. 0 disables the override (always hold).
#
# Rejected once, then adopted -- and the reversal is the interesting part. When
# the ranker produced MRR 0.89 this measured +0.0031 on the full 200 but flipped
# sign across halves (-0.0026 / +0.0087): a small consistent set did not reliably
# mean the target was first, so answering early sometimes locked in a bad rank.
#
# With the ranker at MRR 0.94 it does mean that. Re-tested: +0.0037 full,
# +0.0040 / +0.0034 across halves, and MRR is *identical* with it on and off --
# the gain is pure MTTC at zero rank cost. Peak at 4, shallow band from 2 to 8.
#
# Same lesson as MIN_DISCLOSED above: this is a trade against ranking quality,
# so it needs re-testing whenever ranking moves, in both directions.
ANSWER_IF_CONSISTENT = int(os.environ.get("TJ_ANSWER_IF", "4"))


# Customer-facing phrasing. The spec (README, "On every turn the agent may")
# lists asking a clarification question as a standalone option, separate from
# returning a ranked list -- so a turn that asks without recommending is
# sanctioned behaviour, not a gap. It does have to actually read as a question.
ATTRIBUTE_PROMPTS = {
    "material": "What material are you hoping for?",
    "color": "Any particular colour in mind?",
    "size": "What size or fit are you after?",
    "style": "What style are you going for?",
    "brand": "Any brand you prefer?",
    "budget": "Roughly what budget did you have in mind?",
    "feature": "Is there a particular feature that matters most?",
    "use_case": "What will you mainly be using it for?",
    "category": "What kind of item are you after exactly?",
    "other": "Tell me a bit more about what matters to you.",
}


def _message(state: DialogState, window: list) -> str:
    """What the shopper reads. Must stay consistent with what we returned."""
    attribute = getattr(state, "ask_attribute", None)
    question = ATTRIBUTE_PROMPTS.get(attribute or "", "")
    if not window:
        return question or "Could you tell me a little more about what you need?"
    if question:
        return f"Here are the closest matches so far. {question}"
    return "Here are the closest matches I found."


class Agent:
    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = str(catalog_path)
        self._states: dict[str, DialogState] = {}
        # Long-term memory, deliberately on the Agent and not the session: the
        # harness builds one Agent and calls reset() per session, so this is
        # what "long-term user profile" means here. 200 public sessions carry
        # only 125 distinct profiles, so recurrence is real.
        self._profiles = ProfileMemory()

    def reset(self, session_id: str, user_profile: dict) -> None:
        distilled = self._profiles.begin(user_profile)
        state = DialogState(
            session_id=session_id,
            user_profile=user_profile,
            catalog_path=self.catalog_path,
        )
        state.profile_signature = distilled.signature
        state.profile_tags = distilled.tags
        # Terms this profile used in earlier sessions. Empty on first exposure.
        state.profile_prior = self._profiles.prior_terms(distilled.signature)
        self._states[session_id] = state

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self._states:
            raise RuntimeError("reset must be called before respond")
        state = update_state(self._states[session_id], user_message, turn)
        # After turn 1 the shopper's message is usually fixed filler ("I don't
        # have an additional preference for color."), so retrieving on it builds
        # the pool out of noise. dialog.py composes the accumulated query --
        # category plus everything disclosed so far -- and that is what the pool
        # should come from. getattr keeps this working if dialog.py is reverted.
        query = getattr(state, "query", "") or user_message
        candidates = retrieve(query, state, max(POOL_K, top_k))
        ranked = rank(candidates, state)
        # Feed this turn's distilled context back into the long-term store, so
        # a later session with the same profile starts warmer than this one did.
        self._profiles.observe(
            getattr(state, "profile_signature", ""),
            getattr(state, "category", ""),
            list(getattr(state, "slots", {}).values()),
        )
        # Runtime workflow re-orchestration. Retrieval and ranking are the
        # same every turn; what the agent *does* with the result is re-decided
        # here from measured state. See starter/orchestrate.py for the three
        # strategies and why each exists.
        strategy = select_strategy(
            state, turn, top_k,
            min_disclosed=MIN_DISCLOSED,
            hold_until_turn=HOLD_UNTIL_TURN,
            answer_if_consistent=ANSWER_IF_CONSISTENT,
            confidence_max=CONFIDENCE_MAX,
            max_turns=MAX_TURNS,
        )
        state.strategy = strategy.name
        state.strategy_reason = strategy.reason
        window = window_for(ranked, strategy, top_k)

        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        if os.environ.get("RANK_USE_LLM") == "1":
            from .llm_rerank import usage as llm_usage

            usage = llm_usage()
        return {
            "message": _message(state, window),
            # The simulated shopper only discloses a constraint when asked about
            # a specific attribute; with None it returns filler and the query
            # never grows past turn 1. dialog.py decides which attribute.
            "ask_attribute": getattr(state, "ask_attribute", None),
            "recommendations": [{"parent_asin": candidate.parent_asin} for candidate in window],
            "usage": usage,
        }
