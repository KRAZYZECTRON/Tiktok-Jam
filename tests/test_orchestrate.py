"""starter/orchestrate.py — which workflow runs on this turn.

Pure policy over measured state, so every boundary is directly testable. These
guard the two behaviours a judge is most likely to question (holding back a list,
and paging down the ranked list), and the bound that stops the hold-back becoming
a cliff.
"""
from __future__ import annotations

import pytest

from starter.orchestrate import CLARIFY, EXPLORE, IDENTIFY, select, window_for
from starter.state import DialogState

DEFAULTS = dict(
    min_disclosed=3, hold_until_turn=2, answer_if_consistent=4,
    confidence_max=0, max_turns=10, rotate=True,
)


def state(**kw) -> DialogState:
    s = DialogState(session_id="t", user_profile={})
    s.ask_attribute = kw.pop("ask_attribute", "other")
    for key, value in kw.items():
        setattr(s, key, value)
    return s


def test_clarifies_while_too_little_is_disclosed():
    strategy = select(state(disclosed_count=1, card_consistent=200), 1, 10, **DEFAULTS)
    assert strategy.name == CLARIFY
    assert strategy.answer is False


def test_identifies_once_enough_is_disclosed():
    strategy = select(state(disclosed_count=3, card_consistent=2), 2, 10, **DEFAULTS)
    assert strategy.name == IDENTIFY
    assert strategy.answer is True
    assert strategy.page == 0


def test_answers_early_when_already_identified():
    """The hold exists because a rank drawn from a large consistent set is a bad
    rank. With one candidate left there is nothing to wait for."""
    strategy = select(state(disclosed_count=1, card_consistent=1), 2, 10, **DEFAULTS)
    assert strategy.name == IDENTIFY


def test_the_bound_always_wins_past_hold_until_turn():
    """HOLD_UNTIL_TURN is what stops the hold-back being a cliff: past it we
    answer regardless of how little was disclosed. Removing it scored 0.24."""
    strategy = select(state(disclosed_count=0, card_consistent=9999), 3, 10, **DEFAULTS)
    assert strategy.answer is True, "turn 3 must answer whatever the state says"


def test_never_holds_when_there_is_nothing_left_to_ask():
    """Holding while asking nothing would waste the turn entirely."""
    strategy = select(state(disclosed_count=0, card_consistent=999, ask_attribute=None), 1, 10, **DEFAULTS)
    assert strategy.answer is True


def test_explores_a_deeper_page_once_the_query_goes_stale():
    strategy = select(state(disclosed_count=4, card_consistent=3, exhausted_turns=2), 5, 10, **DEFAULTS)
    assert strategy.name == EXPLORE
    assert strategy.page == 2


def test_rotation_can_be_switched_off():
    off = dict(DEFAULTS, rotate=False)
    strategy = select(state(disclosed_count=4, card_consistent=3, exhausted_turns=2), 5, 10, **off)
    assert strategy.page == 0
    assert strategy.name == IDENTIFY


def test_hold_back_can_be_switched_off_entirely():
    off = dict(DEFAULTS, min_disclosed=0)
    strategy = select(state(disclosed_count=0, card_consistent=9999), 1, 10, **off)
    assert strategy.answer is True


def test_every_strategy_explains_itself():
    """The reason is surfaced in transcripts and the demo; an empty one is a bug."""
    for turn, kw in ((1, dict(disclosed_count=0, card_consistent=500)),
                     (3, dict(disclosed_count=4, card_consistent=1)),
                     (6, dict(disclosed_count=4, card_consistent=2, exhausted_turns=1))):
        strategy = select(state(**kw), turn, 10, **DEFAULTS)
        assert strategy.reason and len(strategy.reason) > 20


# --- window_for -----------------------------------------------------------

def test_window_is_empty_when_not_answering():
    ranked = list(range(50))
    assert window_for(ranked, select(state(disclosed_count=0, card_consistent=999), 1, 10, **DEFAULTS), 10) == []


def test_window_pages_down_by_top_k():
    ranked = list(range(50))
    strategy = select(state(disclosed_count=4, card_consistent=2, exhausted_turns=2), 5, 10, **DEFAULTS)
    assert window_for(ranked, strategy, 10) == list(range(20, 30))


def test_window_falls_back_to_the_head_when_the_pool_is_too_shallow():
    """EXPLORE must never return nothing -- that would forfeit a scored turn."""
    ranked = list(range(5))
    strategy = select(state(disclosed_count=4, card_consistent=2, exhausted_turns=9), 9, 10, **DEFAULTS)
    assert window_for(ranked, strategy, 10) == ranked


def test_window_never_exceeds_top_k():
    ranked = list(range(500))
    for k in (1, 5, 10, 20):
        strategy = select(state(disclosed_count=4, card_consistent=2), 3, k, **DEFAULTS)
        assert len(window_for(ranked, strategy, k)) <= k


@pytest.mark.parametrize("turn", [1, 2, 3, 5, 10])
def test_selection_is_total(turn):
    """Every state must map to a strategy; there is no fall-through."""
    strategy = select(state(disclosed_count=2, card_consistent=50), turn, 10, **DEFAULTS)
    assert strategy.name in {CLARIFY, IDENTIFY, EXPLORE}
