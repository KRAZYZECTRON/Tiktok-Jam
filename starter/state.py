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

    # --- populated by dialog.py (Seat 3); additive, no existing field moved ---
    # slots: disclosed constraints keyed by attribute. ranking.split_dialog()
    #   already prefers these over its own regex fallback when non-empty.
    # query: category + accumulated constraints, the text retrieve() should see
    #   instead of the current turn's message (which is usually filler).
    # ask_attribute: what to ask the shopper next; agent.py returns it, and it
    #   is the only thing that makes the shopper disclose anything.
    slots: dict[str, str] = field(default_factory=dict)
    category: str = ""
    query: str = ""
    ask_attribute: str | None = None
    exhausted_attributes: set[str] = field(default_factory=set)
