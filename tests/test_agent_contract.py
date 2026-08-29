"""starter/agent.py — the interface the organizer actually scores.

Every rule here comes from docs/competition_specification.md or
docs/submission_rules.md. A violation is not a lower score, it is an invalid or
forfeited session, so these are the tests worth having even if nothing else is.
"""
from __future__ import annotations

import builtins
import json
import sys

import pytest

from evaluator.local_evaluator import ALLOWED_ATTRIBUTES
from starter.agent import Agent

PRODUCTS = [
    {"parent_asin": "B000A", "title": "Mens Cotton V-Neck Undershirt", "categories": ["Clothing", "Underwear"],
     "features": ["100% cotton", "tagless"], "details": {"Fit": "regular"},
     "description": "soft black cotton", "store": "ACME", "price": 12.5,
     "average_rating": 4.4, "rating_number": 900},
    {"parent_asin": "B000B", "title": "Womens Leather Tote Handbag", "categories": ["Clothing", "Handbags"],
     "features": ["genuine leather", "zipper closure"], "details": {"Strap": "adjustable"},
     "description": "brown leather", "store": "BCorp", "price": 89.0,
     "average_rating": 4.8, "rating_number": 120},
    {"parent_asin": "B000C", "title": "Nylon Running Shorts", "categories": ["Clothing", "Activewear"],
     "features": ["nylon", "pull on closure"], "description": "blue nylon",
     "price": 22.0, "average_rating": 4.1, "rating_number": 40},
]


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("cat") / "catalog.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in PRODUCTS), encoding="utf-8")
    return str(path)


@pytest.fixture
def agent(catalog) -> Agent:
    return Agent(catalog)


def run(agent: Agent, messages: list[str], top_k: int = 10) -> list[dict]:
    agent.reset("s", {"preference_tags": ["fit"]})
    return [agent.respond("s", m, i, top_k) for i, m in enumerate(messages, start=1)]


# --- required output shape ------------------------------------------------

def test_response_shape_matches_the_published_contract(agent):
    for response in run(agent, ["I'm looking for Clothing Underwear. A key requirement is: 100% cotton.",
                                "For that, what matters is: tagless."]):
        assert isinstance(response["message"], str)
        assert isinstance(response["recommendations"], list)
        assert all(isinstance(r, dict) and "parent_asin" in r for r in response["recommendations"])
        assert isinstance(response["usage"], dict)
        assert response["usage"]["prompt_tokens"] >= 0
        assert response["usage"]["completion_tokens"] >= 0


def test_ask_attribute_is_allowed_or_none(agent):
    """The simulator reads this field instead of guessing from prose, so an
    out-of-vocabulary value is silently coerced to "other" and wastes the ask."""
    for response in run(agent, ["I'm looking for Clothing Underwear.",
                                "For that, what matters is: tagless.",
                                "I don't have an additional preference for other."]):
        attribute = response["ask_attribute"]
        assert attribute is None or attribute in ALLOWED_ATTRIBUTES


@pytest.mark.parametrize("top_k", [1, 3, 10, 25])
def test_never_returns_more_than_top_k(agent, top_k):
    for response in run(agent, ["I'm looking for Clothing Underwear. A key requirement is: 100% cotton.",
                                "For that, what matters is: tagless."], top_k):
        assert len(response["recommendations"]) <= top_k


def test_recommendations_are_unique(agent):
    """Duplicates are dropped by the scorer, so emitting them silently shortens
    our own list."""
    for response in run(agent, ["I'm looking for Clothing Underwear. A key requirement is: 100% cotton.",
                                "For that, what matters is: tagless."]):
        asins = [r["parent_asin"] for r in response["recommendations"]]
        assert len(asins) == len(set(asins))


def test_default_path_reports_zero_tokens(agent):
    """No model is called on the scored path, so this is structurally zero.
    If it ever becomes non-zero, an optional stage has been left enabled."""
    for response in run(agent, ["I'm looking for Clothing Underwear. A key requirement is: 100% cotton."]):
        assert response["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}


def test_message_is_a_question_whenever_no_list_is_returned(agent):
    """Asking without recommending is one of the three turn shapes the spec
    documents -- but the message has to actually read as a question, or the
    transcript is incoherent.

    Stated as an invariant over the run rather than "turn 1 holds back": against
    a three-product catalog the consistent set is immediately tiny, so
    ANSWER_IF_CONSISTENT correctly fires and turn 1 answers. Asserting the
    hold-back here would be testing the fixture, not the agent."""
    responses = run(agent, ["I'm looking for Clothing Underwear.",
                            "Those options are not quite right yet.",
                            "For that, what matters is: tagless."])
    for response in responses:
        if not response["recommendations"]:
            assert response["message"].strip().endswith("?"), response["message"]


def test_held_turn_emits_a_question(agent):
    """The empty-window branch itself, exercised directly."""
    from starter.agent import _message
    from starter.state import DialogState

    state = DialogState(session_id="t", user_profile={})
    state.ask_attribute = "material"
    assert _message(state, []).strip().endswith("?")
    state.ask_attribute = None
    assert _message(state, []).strip().endswith("?")


# --- hardening ------------------------------------------------------------

def test_non_string_messages_do_not_raise(agent):
    """The rules say exceptions may count as a miss, so an unhandled error
    forfeits a session rather than degrading it."""
    agent.reset("s", {})
    for message in (None, 12345, 3.5, ["a", "list"]):
        response = agent.respond("s", message, 1, 10)
        assert isinstance(response["message"], str)


def test_respond_without_reset_does_not_raise(agent):
    response = agent.respond("never-reset", "I'm looking for shoes.", 1, 10)
    assert isinstance(response["message"], str)


def test_malformed_profiles_do_not_raise(agent):
    for profile in (None, {}, [], {"preference_tags": "fit", "average_prior_rating": "high"}):
        agent.reset("p", profile)
        agent.respond("p", "I'm looking for Clothing Underwear.", 1, 10)


def test_sessions_stay_independent(agent):
    agent.reset("one", {})
    agent.reset("two", {})
    agent.respond("one", "I'm looking for Clothing Handbags. A key requirement is: genuine leather.", 1, 10)
    agent.respond("two", "I'm looking for Clothing Activewear. A key requirement is: nylon.", 1, 10)
    assert "handbag" in agent._states["one"].query.lower()
    assert "activewear" in agent._states["two"].query.lower()
    assert "handbag" not in agent._states["two"].query.lower()


def test_empty_catalog_returns_nothing_rather_than_raising(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    a = Agent(str(path))
    a.reset("s", {})
    response = a.respond("s", "I'm looking for shoes. A key requirement is: leather.", 3, 10)
    assert response["recommendations"] == []


# --- the pure-stdlib guarantee -------------------------------------------

def test_runs_with_numpy_and_sentence_transformers_absent(catalog):
    """The rules permit scoring with network access disabled. The default path
    must not depend on anything optional -- if this fails, something
    load-bearing has crept in."""
    blocked = {"numpy", "sentence_transformers", "torch"}
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError(f"simulated absence of {name}")
        return real_import(name, *args, **kwargs)

    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] in blocked}
    for key in list(sys.modules):
        if key.split(".")[0] in blocked or key.startswith("starter."):
            sys.modules.pop(key, None)
    builtins.__import__ = guard
    try:
        import starter.agent as reloaded
        a = reloaded.Agent(catalog)
        a.reset("s", {})
        response = a.respond("s", "I'm looking for Clothing Underwear. A key requirement is: 100% cotton.", 3, 10)
        assert isinstance(response["recommendations"], list)
    finally:
        builtins.__import__ = real_import
        for key in list(sys.modules):
            if key.startswith("starter."):
                sys.modules.pop(key, None)
        sys.modules.update(saved)


def test_scored_path_opens_no_socket(agent, monkeypatch):
    """Verified by making socket creation fail rather than by inspection."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("the scored path must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    run(agent, ["I'm looking for Clothing Underwear. A key requirement is: 100% cotton.",
                "For that, what matters is: tagless."])
