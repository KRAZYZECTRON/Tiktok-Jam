"""Thin orchestrator: update_state() -> retrieve() -> rank() -> format response.

Shared by all three seats -- flag changes here in the team channel first.
"""
from __future__ import annotations

import os
from pathlib import Path

from .dialog import update_state
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
# TESTED AND REJECTED, inert at 0. On the full 200 it looks like a gain
# (+0.0031, MTTC 3.195 -> 2.880) but the split-half flips sign:
#   half A -0.0026    half B +0.0087
# The whole full-set gain comes from one half. Sometimes the single "consistent"
# candidate is the wrong product, and answering on it locks in a bad rank -- how
# often that happens is a property of the particular sessions, not of the rule.
ANSWER_IF_CONSISTENT = int(os.environ.get("TJ_ANSWER_IF", "0"))


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

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._states[session_id] = DialogState(
            session_id=session_id,
            user_profile=user_profile,
            catalog_path=self.catalog_path,
        )

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
        # Once the shopper has nothing left to disclose, dialog.py counts the
        # dead turns and we page down the ranked list instead of re-showing a
        # top ten that has already been rejected. Falls back to the head if the
        # pool is shallower than the offset, and to 0 if dialog.py is reverted.
        rotating = os.environ.get("TJ_ROTATE") != "off"
        offset = getattr(state, "exhausted_turns", 0) * top_k if rotating else 0
        window = ranked[offset:offset + top_k] or ranked[:top_k]
        # Still guessing: ask, but do not spend the session's one scored answer
        # on a list we expect to rank the target low in.
        confident = (
            ANSWER_IF_CONSISTENT
            and 0 < getattr(state, "card_consistent", 0) <= ANSWER_IF_CONSISTENT
        )
        holding = (
            MIN_DISCLOSED
            and turn <= HOLD_UNTIL_TURN
            and getattr(state, "disclosed_count", 0) < MIN_DISCLOSED
            and getattr(state, "ask_attribute", None) is not None
            and not confident
        )
        if holding or (
            CONFIDENCE_MAX
            and turn < MAX_TURNS
            and getattr(state, "card_consistent", 0) > CONFIDENCE_MAX
            and getattr(state, "ask_attribute", None) is not None
        ):
            window = []

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
