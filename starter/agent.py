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
POOL_K = int(os.environ.get("TJ_POOL_K", "500"))


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
        candidates = retrieve(user_message, state, max(POOL_K, top_k))
        ranked = rank(candidates, state)[:top_k]
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        if os.environ.get("RANK_USE_LLM") == "1":
            from .llm_rerank import usage as llm_usage

            usage = llm_usage()
        return {
            "message": "Here are the closest matches I found.",
            "ask_attribute": None,
            "recommendations": [{"parent_asin": candidate.parent_asin} for candidate in ranked],
            "usage": usage,
        }
