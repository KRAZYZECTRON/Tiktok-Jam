"""Tests for transparent recommendation explanations (agent._explanation).

The spec names "transparent recommendation explanations" as an Innovation
Direction. The risk with that feature is not that it breaks scoring -- the
simulator reads `ask_attribute`, not prose -- it is that the explanation drifts
away from what the ranker actually did and becomes a plausible-sounding fiction.

So these tests pin the property that matters: the sentence only ever names
constraints the product's own intent card really contains, and says nothing at
all when there is no card evidence.
"""
from __future__ import annotations

import pytest

from starter.agent import _explanation, _message, _readable
from starter.state import Candidate, DialogState


class _State(DialogState):
    """A DialogState with the fields rank() would have written."""


def _state(**kw) -> DialogState:
    state = DialogState(session_id="t", user_profile={}, catalog_path="data/catalog.jsonl")
    for key, value in kw.items():
        setattr(state, key, value)
    return state


# --- _readable ------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("material:alloy", "alloy"),
        ("color: black", "black"),
        ("colour: blue", "blue"),
        ("100% Leather", "100% Leather"),
        ("Buckle closure", "Buckle closure"),
        ("  spaced   out  ", "spaced out"),
    ],
)
def test_readable_tidies_without_rewording(raw, expected):
    assert _readable(raw) == expected


def test_readable_truncates_a_card_slot_that_runs_long():
    long = "The Triple Moon represents the Phases of the Moon which are linked to the three aspects"
    out = _readable(long)
    assert len(out) <= 44
    assert out.endswith("...")
    assert long.startswith(out[:-3].rstrip())


def test_readable_never_emits_non_ascii():
    """cp1252 consoles mangle curly quotes; this copy is echoed to a terminal."""
    for raw in ("material:alloy", "x" * 200, "color: black"):
        assert all(ord(c) < 128 for c in _readable(raw))


# --- _explanation ---------------------------------------------------------

def test_no_disclosed_constraints_means_no_explanation():
    assert _explanation(_state(), [Candidate("B0001")]) == ""


def test_empty_window_means_no_explanation():
    assert _explanation(_state(disclosed_values=("leather",)), []) == ""


def test_explanation_is_silent_when_the_ranker_had_no_card_evidence(monkeypatch):
    """The important negative case: say nothing rather than invent a reason."""
    monkeypatch.setattr("starter.agent.evidence_for", lambda asin, state: ())
    out = _explanation(_state(disclosed_values=("leather", "buckle")), [Candidate("B0001")])
    assert out == ""


def test_full_match_is_phrased_as_everything(monkeypatch):
    monkeypatch.setattr(
        "starter.agent.evidence_for", lambda asin, state: ("leather", "buckle closure")
    )
    out = _explanation(
        _state(disclosed_values=("leather", "buckle closure")), [Candidate("B0001")]
    )
    assert "everything you've mentioned" in out
    assert "leather" in out and "buckle closure" in out


def test_partial_match_states_the_true_fraction(monkeypatch):
    monkeypatch.setattr("starter.agent.evidence_for", lambda asin, state: ("leather",))
    out = _explanation(
        _state(disclosed_values=("leather", "buckle closure", "brown")), [Candidate("B0001")]
    )
    assert "1 of the 3" in out
    # It must not overclaim by naming constraints that did not match.
    assert "buckle closure" not in out and "brown" not in out


def test_long_match_lists_three_and_counts_the_rest(monkeypatch):
    matched = ("a", "b", "c", "d", "e")
    monkeypatch.setattr("starter.agent.evidence_for", lambda asin, state: matched)
    out = _explanation(_state(disclosed_values=matched), [Candidate("B0001")])
    assert "(and 2 more)" in out


def test_explanation_describes_only_the_first_result(monkeypatch):
    """The message says 'the first one'; it must be about window[0]."""
    seen = []

    def fake(asin, state):
        seen.append(asin)
        return ("leather",)

    monkeypatch.setattr("starter.agent.evidence_for", fake)
    _explanation(
        _state(disclosed_values=("leather",)),
        [Candidate("B_FIRST"), Candidate("B_SECOND")],
    )
    assert seen == ["B_FIRST"]


# --- _message integration -------------------------------------------------

def test_message_still_asks_its_question_alongside_the_explanation(monkeypatch):
    monkeypatch.setattr("starter.agent.evidence_for", lambda asin, state: ("leather",))
    out = _message(
        _state(disclosed_values=("leather",), ask_attribute="material"), [Candidate("B0001")]
    )
    assert "Here are the closest matches so far." in out
    assert "leather" in out
    assert out.rstrip().endswith("?"), "the clarification question must survive"


def test_message_with_no_window_is_unchanged_and_asks():
    out = _message(_state(ask_attribute="color"), [])
    assert out.endswith("?")


def test_message_is_always_a_string(monkeypatch):
    """docs/competition_specification.md: 'message must be a string'."""
    monkeypatch.setattr("starter.agent.evidence_for", lambda asin, state: ("leather",))
    for state in (_state(), _state(disclosed_values=("leather",), ask_attribute="material")):
        assert isinstance(_message(state, [Candidate("B0001")]), str)
        assert isinstance(_message(state, []), str)
