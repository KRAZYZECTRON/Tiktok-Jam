"""Tests for question-value estimation (starter/question.py).

The estimator ships disabled, so these tests are not protecting the score. They
protect the *claim*: that the thing we built and measured is a real
expected-posterior-size estimator and not a heuristic wearing the name. A
negative result is only worth publishing if the thing that lost was correct.

The properties pinned here are the ones the mechanism argument rests on:
`classify_constraint` matches the evaluator's, the reply model honours the [:2]
cap, and a question that cannot split the field scores zero.
"""
from __future__ import annotations

import pytest

from evaluator.local_evaluator import classify_constraint as evaluator_classify
from starter.question import (
    CANDIDATE_ATTRIBUTES,
    best_attribute,
    classify_constraint,
    score_attributes,
    _reply_for,
)
from starter.state import DialogState


# --- the copied classifier must not drift from the evaluator's -------------

@pytest.mark.parametrize(
    "value",
    [
        "100% cotton", "leather", "color: black", "budget around $25",
        "under 30", "size: wide", "sleeve length: long", "for hiking",
        "Triple Moon Pentagram Symbol", "Buckle closure", "polyester blend",
        "narrow width", "neck: crew", "outdoor work boots", "$19.99",
    ],
)
def test_classifier_matches_the_evaluator(value):
    """question.py reimplements classify_constraint; it must stay identical."""
    assert classify_constraint(value) == evaluator_classify(value)


# --- the reply model -------------------------------------------------------

def test_reply_honours_the_two_constraint_cap():
    """The [:2] cap is the whole reason 'other' is hard to beat."""
    slots = ("cotton", "color: black", "crew neck", "for hiking")
    assert len(_reply_for(slots, frozenset(), "other")) == 2


def test_reply_excludes_what_is_already_disclosed():
    slots = ("cotton", "color: black", "crew neck")
    out = _reply_for(slots, frozenset({"cotton"}), "other")
    assert "cotton" not in out
    assert out == ("color: black", "crew neck")


def test_reply_for_a_specific_attribute_filters_by_class():
    slots = ("cotton", "color: black", "crew neck")
    assert _reply_for(slots, frozenset(), "color") == ("color: black",)
    assert _reply_for(slots, frozenset(), "material") == ("cotton",)


def test_reply_is_empty_when_nothing_of_that_kind_is_left():
    """Which is itself informative -- the shopper says they have no preference."""
    assert _reply_for(("cotton",), frozenset({"cotton"}), "material") == ()


# --- the estimator ---------------------------------------------------------

def test_empty_candidate_set_scores_everything_zero():
    assert all(value == 0.0 for _, value in score_attributes([], frozenset()))


def test_a_question_that_cannot_split_the_field_scores_zero():
    """Identical cards give identical answers, so nothing is learned."""
    identical = [("cotton", "color: black")] * 8
    scored = dict(score_attributes(identical, frozenset()))
    assert scored["other"] == pytest.approx(0.0)
    assert scored["material"] == pytest.approx(0.0)


def test_a_perfectly_splitting_question_scores_the_full_reduction():
    """N candidates, N distinct answers -> expected posterior size 1."""
    distinct = [(f"feature {i}",) for i in range(10)]
    scored = dict(score_attributes(distinct, frozenset()))
    assert scored["other"] == pytest.approx(9.0)  # 10 - 1


def test_expected_size_matches_the_closed_form():
    """Two groups of 3 and 1: E[|C'|] = (3/4)*3 + (1/4)*1 = 2.5, so value 1.5."""
    cards = [("cotton",)] * 3 + [("leather",)]
    scored = dict(score_attributes(cards, frozenset()))
    assert scored["material"] == pytest.approx(4 - 2.5)


def test_a_useless_attribute_never_outscores_an_informative_one():
    cards = [("cotton", "color: black"), ("leather", "color: black")]
    scored = dict(score_attributes(cards, frozenset()))
    assert scored["material"] > scored["color"]
    assert scored["color"] == pytest.approx(0.0)


def test_every_candidate_attribute_is_scored():
    scored = dict(score_attributes([("cotton",)], frozenset()))
    assert set(scored) == set(CANDIDATE_ATTRIBUTES)


def test_ties_resolve_toward_other():
    """So any divergence from the shipped heuristic is one the estimator earned."""
    identical = [("cotton", "color: black")] * 4
    assert score_attributes(identical, frozenset())[0][0] == "other"


# --- best_attribute --------------------------------------------------------

def _state(**kw) -> DialogState:
    state = DialogState(session_id="t", user_profile={})
    for key, value in kw.items():
        setattr(state, key, value)
    return state


def test_best_attribute_is_none_without_a_stashed_candidate_set():
    assert best_attribute(_state()) is None


def test_best_attribute_is_none_when_no_question_can_inform():
    identical = (("cotton", "color: black"),) * 5
    assert best_attribute(_state(consistent_slots=identical)) is None


def test_best_attribute_skips_exhausted_attributes():
    cards = (("cotton",), ("leather",), ("silk",))
    assert best_attribute(_state(consistent_slots=cards)) == "other"
    chosen = best_attribute(
        _state(consistent_slots=cards, exhausted_attributes={"other"})
    )
    assert chosen == "material"


def test_estimator_is_off_by_default():
    """The shipped path must not pay for it, and must not be changed by it."""
    import starter.question as question

    assert question.ENABLED is False
