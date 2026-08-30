"""starter/ranking.py — the scoring stage, and the one module nothing tested.

Every other module we wrote had a test file; the largest one, where the score
actually lives, had none. That is a gap worth closing on its own, but the tests
below are chosen for a sharper reason: three of the four worst bugs this project
shipped were in this file, and all three passed every check that existed at the
time because the checks were end-to-end scores rather than assertions about
behaviour. A score can absorb a broken sub-stage; an assertion cannot.

So the emphasis here is on the specific failures that happened:

  * the category being swallowed by constraint extraction (twice, in two
    different functions, which is why `split_dialog` is now the only one);
  * extraction silently returning the WRONG substring rather than nothing;
  * the layering rule — tolerant tiers strictly behind strict ones — which is
    load-bearing and expressed only as constants that anyone could reorder.
"""
from __future__ import annotations

from starter.ranking import (
    BONUS_CARD_FUSED,
    BONUS_CARD_FUZZY,
    BONUS_CARD_PARTIAL,
    RRF_K,
    WEIGHT_RRF_RETRIEVAL,
    WEIGHT_RRF_STAGE_A,
    _disclosed_constraints,
    _find_payload,
    _phrases,
    _terms,
    split_dialog,
)
from starter.state import DialogState


def _state(messages, **kwargs) -> DialogState:
    state = DialogState(session_id="t", user_profile={})
    state.messages = list(messages)
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


# --- the bug that shipped twice -------------------------------------------

def test_opening_turn_keeps_the_category_and_the_constraint():
    """The regression that cost the most: `_strip_noise` ran payload extraction
    over the whole opening and returned only the constraint, so this session
    was ranked as if the shopper had asked for "alloy" rather than for jewellery
    made of alloy. Fixed once, then reintroduced in `_need_text` for the LLM
    stage, which is why both stages now share `split_dialog`."""
    category, constraints = split_dialog(
        _state(["I'm looking for Jewelry Necklaces. A key requirement is: Material:alloy."])
    )
    assert "jewelry" in category.lower()
    assert "necklaces" in category.lower()
    assert any("alloy" in text.lower() for text in constraints)


def test_a_colon_inside_the_constraint_does_not_sever_the_category():
    """Turn 1 disables the bare-colon fallback because product copy is full of
    colons — "FAVORITE SLIPPERS: Slip into divine comfort" is a title, not a
    stated requirement. Splitting there severs the category, the strongest
    signal in the session, and cost 0.025 when the fallback ran here.

    With no carrier phrase present the whole opening stays the category, which
    is the safe direction: the category keeps its words rather than being
    replaced by the fragment after an arbitrary colon."""
    category, _ = split_dialog(
        _state(["I'm looking for Clothing Shoes. FAVORITE SLIPPERS: Slip into comfort."])
    )
    assert "clothing shoes" in category.lower()
    assert not category.lower().startswith("slip into")


def test_the_looking_for_lead_in_is_stripped_from_the_category():
    category, _ = split_dialog(_state(["I'm looking for Clothing Tops, but I'm still exploring."]))
    assert not category.lower().startswith("i'm looking for")
    assert "clothing tops" in category.lower()


def test_structured_slots_win_over_the_regex_fallback():
    """dialog.py owns constraint accumulation once it has started; the regex
    path exists only so ranking still works if that is reverted."""
    state = _state(
        ["I'm looking for Clothing Tops. A key requirement is: cotton.",
         "For that, what matters is: black."],
        slots={"material": "linen", "color": "green"},
    )
    _, constraints = split_dialog(state)
    assert constraints == ["linen", "green"]


def test_an_empty_conversation_yields_nothing_rather_than_raising():
    assert split_dialog(_state([])) == ("", [])


# --- extraction across phrasings -------------------------------------------

def test_the_simulators_own_carriers_all_extract_the_payload():
    for carrier in ("what matters is:", "a key requirement is:", "what I need is:"):
        found = _find_payload(f"For that, {carrier} 100% cotton.")
        assert found and "100% cotton" in found.group(1)


def test_a_paraphrased_carrier_that_drops_the_colon_still_extracts_in_full():
    """The subtle one. With a colon required this fell through to the fallback,
    which latched onto the *wrong* colon and returned "100% cotton", silently
    dropping "solids:". Extraction appeared to succeed while truncating, and
    truncated text matches no card slot."""
    found = _find_payload("the thing that matters is solids: 100% cotton")
    assert found
    assert "solids" in found.group(1)
    assert "100% cotton" in found.group(1)


def test_extraction_returns_nothing_rather_than_guessing_when_told_not_to_fall_back():
    assert _find_payload("Just some text with a colon: here", fallback=False) is None
    assert _find_payload("Just some text with a colon: here", fallback=True) is not None


# --- normalisation ---------------------------------------------------------

def test_a_multi_constraint_reply_splits_back_into_its_parts():
    """The evaluator joins up to two constraints with "; " into one reply, so
    they have to split apart again or neither matches a card slot."""
    assert _disclosed_constraints(["100% cotton; machine wash"]) == ("100% cotton", "machine wash")


def test_disclosed_constraints_deduplicate_and_lowercase():
    assert _disclosed_constraints(["Cotton", "cotton", "  COTTON  "]) == ("cotton",)


def test_disclosed_constraints_normalise_the_way_the_card_did():
    """A match against a card slot has to be exact, so both sides must go
    through the same normaliser — collapsed whitespace, stripped punctuation."""
    assert _disclosed_constraints(["  Pull   on   closure.  "]) == ("pull on closure",)


def test_terms_drop_stopwords_and_single_characters():
    terms = _terms("A black cotton T shirt for the summer")
    assert "black" in terms and "cotton" in terms
    assert "a" not in terms and "the" not in terms


def test_phrases_deduplicate_and_drop_ones_too_short_to_discriminate():
    """Verbatim containment only means something for a phrase long enough to be
    rare: `EXACT_MIN_CHARS` is 12, so "cotton" is dropped as a phrase even
    though it survives as a term and as a card slot."""
    phrases = _phrases(["pull on closure; pull on closure; cotton"])
    assert phrases.count("pull on closure") == 1
    assert "cotton" not in phrases


# --- the layering invariant ------------------------------------------------

def test_the_card_tiers_stay_strictly_ordered():
    """Exact beats fuzzy beats partial, and partial is off. This ordering is
    the whole design — a tolerant rule is only ever allowed to decide who wins
    when the stricter one is silent. It lives in three constants that anyone
    could reorder without any score moving enough to notice."""
    assert BONUS_CARD_FUSED > BONUS_CARD_FUZZY
    assert BONUS_CARD_FUZZY > BONUS_CARD_PARTIAL
    assert BONUS_CARD_PARTIAL == 0.0, "rejected: it promotes rivals, see the note in ranking.py"


def test_the_card_bonus_outweighs_the_entire_fusion_range():
    """Card consistency is a lexicographic key, not a weight: any consistent
    candidate must outrank any inconsistent one whatever the fusion says. That
    holds only while the bonus exceeds the largest possible RRF total, and RRF_K
    is tunable, so the two can silently drift into the same range."""
    max_rrf = WEIGHT_RRF_RETRIEVAL / (RRF_K + 1) + WEIGHT_RRF_STAGE_A / (RRF_K + 1)
    assert BONUS_CARD_FUSED > max_rrf
