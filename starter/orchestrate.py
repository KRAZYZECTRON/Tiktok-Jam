"""Runtime strategy selection — which workflow the agent runs on this turn.

The agent does not run one fixed pipeline. Retrieval and ranking are the same
every turn, but what it *does with the result* is re-decided each turn from
measured session state, and the three behaviours are genuinely different:

    CLARIFY   Ask, and return no recommendations. Chosen while the candidate
              set is still too broad to name a product and the shopper still
              has something left to disclose. The evaluator scores the rank at
              the *first* hit, so answering from a set of ~78 consistent
              candidates would permanently bank a poor reciprocal rank for the
              session. Asking first is worth more than answering early.

    IDENTIFY  Answer from the head of the ranked list. Chosen once the
              conversation has narrowed the catalog to something we can name.

    EXPLORE   Answer from a deeper page of the same ranked list. Chosen once
              the shopper has stopped disclosing: the query is unchanged, so
              retrieval and ranking return exactly what they returned last
              turn, and re-showing a top ten already rejected is provably
              useless. Each dead turn slides the window down one page.

Keeping the choice here rather than inline in agent.py matters for three
reasons: the policy can be read in one place, the reason for each turn's
behaviour is recorded on the state and can be shown in a transcript, and the
switching is testable independently of the pipeline that feeds it.

This module makes no decisions of its own about *quality* — it consumes signals
that dialog.py and ranking.py compute (`disclosed_count`, `card_consistent`,
`exhausted_turns`) and turns them into a workflow.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .state import DialogState

CLARIFY = "CLARIFY"
IDENTIFY = "IDENTIFY"
EXPLORE = "EXPLORE"


@dataclass(frozen=True)
class Strategy:
    """One turn's chosen workflow, with the reason it was chosen."""

    name: str
    answer: bool     # return recommendations at all?
    page: int        # which page of the ranked list (0 = head)
    reason: str      # human-readable; surfaced in transcripts and the demo


def select(
    state: DialogState,
    turn: int,
    top_k: int,
    *,
    min_disclosed: int,
    hold_until_turn: int,
    answer_if_consistent: int,
    confidence_max: int,
    max_turns: int,
    rotate: bool | None = None,
) -> Strategy:
    """Choose this turn's workflow from the session state.

    Thresholds are passed in rather than read here so that agent.py remains the
    single place they are configured, and so this is directly unit-testable.
    """
    disclosed = getattr(state, "disclosed_count", 0)
    consistent = getattr(state, "card_consistent", 0)
    exhausted = getattr(state, "exhausted_turns", 0)
    asking = getattr(state, "ask_attribute", None) is not None

    if rotate is None:
        rotate = os.environ.get("TJ_ROTATE") != "off"
    page = exhausted if rotate else 0

    # Already identified: do not keep asking just because a counter says so.
    identified = bool(answer_if_consistent) and 0 < consistent <= answer_if_consistent

    if (
        min_disclosed
        and turn <= hold_until_turn
        and disclosed < min_disclosed
        and asking
        and not identified
    ):
        return Strategy(
            CLARIFY, False, page,
            f"only {disclosed} constraint(s) disclosed and {consistent} candidates "
            f"still consistent — asking rather than banking a low rank",
        )

    if (
        confidence_max
        and turn < max_turns
        and consistent > confidence_max
        and asking
    ):
        return Strategy(
            CLARIFY, False, page,
            f"{consistent} candidates still consistent, above the confidence "
            f"ceiling of {confidence_max} — asking instead of guessing",
        )

    if page:
        return Strategy(
            EXPLORE, True, page,
            f"nothing new disclosed for {exhausted} turn(s); the query is "
            f"unchanged, so showing page {page + 1} instead of a rejected top ten",
        )

    return Strategy(
        IDENTIFY, True, 0,
        f"{consistent} candidate(s) consistent with {disclosed} disclosed "
        f"constraint(s) — answering from the head",
    )


def window_for(ranked: list, strategy: Strategy, top_k: int) -> list:
    """Apply a strategy to a ranked list. Falls back to the head when the pool
    is shallower than the requested page, so EXPLORE can never return nothing."""
    if not strategy.answer:
        return []
    offset = strategy.page * top_k
    return ranked[offset:offset + top_k] or ranked[:top_k]
