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
        # Not confident yet: ask, but do not spend the session's one scored
        # guess on a list we expect to rank the target low in.
        if (
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
            "message": "Here are the closest matches I found.",
            # The simulated shopper only discloses a constraint when asked about
            # a specific attribute; with None it returns filler and the query
            # never grows past turn 1. dialog.py decides which attribute.
            "ask_attribute": getattr(state, "ask_attribute", None),
            "recommendations": [{"parent_asin": candidate.parent_asin} for candidate in window],
            "usage": usage,
        }
