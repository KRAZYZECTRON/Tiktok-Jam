"""Shared types passed between retrieve(), update_state(), and rank()."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A single ranked catalog item."""

    parent_asin: str
    score: float | None = None


@dataclass
class DialogState:
    """Per-session conversational state threaded through the pipeline."""

    session_id: str
    user_profile: dict
    catalog_path: str = "data/catalog.jsonl"
    turn: int = 0
    messages: list[str] = field(default_factory=list)
