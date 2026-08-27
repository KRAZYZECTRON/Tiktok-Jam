"""Thin orchestrator: update_state() -> retrieve() -> rank() -> format response.

Shared by all three seats -- flag changes here in the team channel first.
"""
from __future__ import annotations

from pathlib import Path

from .dialog import update_state
from .ranking import rank
from .retrieval import retrieve
from .state import DialogState


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
        candidates = retrieve(user_message, state, top_k)
        ranked = rank(candidates, state)
        return {
            "message": "Here are the closest matches I found.",
            "ask_attribute": None,
            "recommendations": [{"parent_asin": candidate.parent_asin} for candidate in ranked],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
