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
    # exhausted_turns: how many turns in a row the shopper has had nothing left
    #   to disclose. agent.py uses it to slide the returned window down the
    #   ranked list, so a dead turn shows the next ten instead of the same ten.
    exhausted_turns: int = 0
    # Set by ranking.rank(): how many pooled candidates are still consistent
    # with every disclosed constraint. 1 = identified, large = still guessing.
    card_consistent: int = 0
    # How many distinct constraints the shopper has disclosed so far. The
    # consistent-product set collapses from a median of 78 at two to 1 at three,
    # so this is the agent's cue that it can identify rather than guess.
    disclosed_count: int = 0
    # The disclosed constraints themselves, normalised exactly as the intent
    # card that produced them was. Set by ranking.rank() alongside the count,
    # so explanations are built from the same strings the ranker matched on
    # rather than from a second, possibly divergent, parse of the dialog.
    disclosed_values: tuple = ()
    # --- written by orchestrate.select(), for inspection and transcripts ---
    # Which of CLARIFY / IDENTIFY / EXPLORE this turn ran, and why. Nothing in
    # the pipeline reads these back; they exist so the agent's own reasoning is
    # legible in a transcript rather than implicit in its output.
    strategy: str = ""
    strategy_reason: str = ""
    # --- personalized context distillation (starter/profile.py) ---
    # The aggregate profile parsed into typed fields once at reset(), plus terms
    # this same profile used in EARLIER sessions (empty on first exposure).
    profile_signature: str = ""
    profile_tags: tuple = ()
    profile_prior: dict = field(default_factory=dict)
