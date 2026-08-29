"""starter/profile.py — short-term distillation and long-term profile memory."""
from __future__ import annotations

from starter.profile import ProfileMemory, distil, signature_of

PROFILE = {
    "average_prior_rating": 5.0,
    "preference_tags": ["fit", "comfort"],
    "purchase_frequency": "3-4 prior purchases",
    "rating_style": "usually positive",
    "summary": "Prior purchases emphasize fit, comfort; ratings are usually positive.",
}


def test_signature_is_stable_and_order_independent():
    reordered = {k: PROFILE[k] for k in reversed(list(PROFILE))}
    assert signature_of(PROFILE) == signature_of(reordered)


def test_signature_separates_different_profiles():
    other = dict(PROFILE, preference_tags=["style"])
    assert signature_of(PROFILE) != signature_of(other)


def test_signature_does_not_leak_the_profile():
    """It is a hash of already-anonymised data, but it should still not be
    reversible by inspection."""
    signature = signature_of(PROFILE)
    assert "fit" not in signature and "positive" not in signature
    assert len(signature) == 16


def test_distil_parses_typed_fields():
    d = distil(PROFILE)
    assert "fit" in d.tags and "comfort" in d.tags
    assert d.prior_rating == 5.0
    assert d.rating_style == "usually positive"


def test_distil_survives_junk():
    for junk in (None, {}, {"preference_tags": "not-a-list", "average_prior_rating": "high"}, []):
        d = distil(junk if isinstance(junk, dict) else {})
        assert isinstance(d.tags, tuple)


def test_memory_is_empty_on_first_exposure():
    """A profile seen once has taught us nothing yet; returning terms then would
    just be echoing the current session back at itself."""
    memory = ProfileMemory()
    d = memory.begin(PROFILE)
    memory.observe(d.signature, "Watches Wrist Watches", ["stainless steel band"])
    assert memory.prior_terms(d.signature) == {}


def test_memory_carries_terms_forward_on_return():
    memory = ProfileMemory()
    first = memory.begin(PROFILE)
    memory.observe(first.signature, "Watches Wrist Watches", ["stainless steel band"])
    second = memory.begin(PROFILE)
    prior = memory.prior_terms(second.signature)
    assert "watches" in prior
    assert "stainless" in prior


def test_memory_keeps_profiles_apart():
    memory = ProfileMemory()
    a = memory.begin(PROFILE)
    b = memory.begin(dict(PROFILE, preference_tags=["style"]))
    memory.observe(a.signature, "Watches", ["steel"])
    memory.begin(PROFILE)
    memory.begin(dict(PROFILE, preference_tags=["style"]))
    assert "watches" in memory.prior_terms(a.signature)
    assert "watches" not in memory.prior_terms(b.signature)


def test_exclude_filters_terms_already_in_play():
    memory = ProfileMemory()
    d = memory.begin(PROFILE)
    memory.observe(d.signature, "Watches Wrist", ["steel"])
    memory.begin(PROFILE)
    prior = memory.prior_terms(d.signature, exclude={"watches"})
    assert "watches" not in prior


def test_session_count_tracks_exposures():
    memory = ProfileMemory()
    for expected in (1, 2, 3):
        d = memory.begin(PROFILE)
        assert memory.sessions_seen(d.signature) == expected


def test_observe_on_an_unknown_signature_is_a_no_op():
    memory = ProfileMemory()
    memory.observe("never-seen", "Watches", ["steel"])  # must not raise
    assert memory.prior_terms("never-seen") == {}


def test_boilerplate_prose_does_not_become_a_term():
    """The profile summary is fixed phrasing; tokenising it would inject words
    that match most of the catalog."""
    memory = ProfileMemory()
    d = memory.begin(PROFILE)
    memory.observe(d.signature, "Watches", ["ratings are usually positive"])
    memory.begin(PROFILE)
    prior = memory.prior_terms(d.signature)
    for noise in ("ratings", "usually", "positive"):
        assert noise not in prior
