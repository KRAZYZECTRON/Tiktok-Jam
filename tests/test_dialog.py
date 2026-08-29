"""starter/dialog.py — slot accumulation, intent override, probing, dead turns.

No catalog needed: update_state() only manipulates DialogState.
"""
from __future__ import annotations

from starter.dialog import MAX_TURNS, PROBE_ORDER, update_state
from starter.state import DialogState


def fresh() -> DialogState:
    return DialogState(session_id="t", user_profile={"preference_tags": ["fit"]})


def drive(messages: list[str]) -> DialogState:
    state = fresh()
    for turn, message in enumerate(messages, start=1):
        state = update_state(state, message, turn)
    return state


# --- turn 1 ---------------------------------------------------------------

def test_opening_splits_category_from_constraint():
    state = drive(["I'm looking for Jewelry Necklaces. A key requirement is: Material:alloy."])
    assert "jewelry" in state.category.lower()
    assert "necklaces" in state.category.lower()
    assert any("alloy" in v.lower() for v in state.slots.values())


def test_browsing_opener_keeps_the_category_and_drops_the_filler():
    state = drive(["I'm looking for Basketball Men, but I'm still exploring."])
    assert "basketball" in state.category.lower()
    assert "exploring" not in state.category.lower()
    assert state.slots == {}


def test_category_survives_a_constraint_containing_a_colon():
    """Product copy often contains a colon. Splitting on it severs the category,
    which is the strongest single signal in the session."""
    state = drive(["I'm looking for Shoes Slippers. YOUR NEW FAVORITE SLIPPERS: Slip into comfort."])
    assert "slippers" in state.category.lower()
    assert "shoes" in state.category.lower()


# --- accumulation ---------------------------------------------------------

def test_slots_accumulate_without_losing_earlier_ones():
    state = drive([
        "I'm looking for Tops. A key requirement is: cotton.",
        "For that, what matters is: machine wash; regular fit.",
    ])
    joined = " ".join(state.slots.values()).lower()
    assert "cotton" in joined
    assert "machine wash" in joined
    assert "regular fit" in joined


def test_filler_replies_record_nothing():
    before = drive(["I'm looking for Tops. A key requirement is: cotton."])
    n = len(before.slots)
    after = update_state(before, "Those options are not quite right yet. Ask me about one specific attribute.", 2)
    assert len(after.slots) == n


def test_query_grows_and_contains_the_category():
    state = drive([
        "I'm looking for Handbags Totes. A key requirement is: leather.",
        "For that, what matters is: zipper closure.",
    ])
    assert "handbags" in state.query.lower()
    assert "leather" in state.query.lower()
    assert "zipper" in state.query.lower()


# --- intent override ------------------------------------------------------

def test_override_erases_the_opening_preference_but_keeps_later_ones():
    state = drive([
        "I'm looking for Belts. Buckle closure",
        "For that, what matters is: leather; 100% Leather.",
        "Actually, ignore my earlier preference. What I need is: leather.",
    ])
    joined = " ".join(state.slots.values()).lower()
    assert "buckle" not in joined, "the overridden opening preference must go"
    assert "leather" in joined, "constraints disclosed after the opening still hold"


def test_override_does_not_reset_exhausted_attributes():
    """The evaluator never un-discloses; an attribute that came back empty
    before the override is still empty after it."""
    state = drive([
        "I'm looking for Belts. Buckle closure",
        "I don't have an additional preference for color.",
    ])
    assert "color" in state.exhausted_attributes
    state = update_state(state, "Actually, ignore my earlier preference. What I need is: leather.", 3)
    assert "color" in state.exhausted_attributes


# --- boundary vs exhausted ------------------------------------------------

def test_boundary_deflection_is_not_treated_as_exhausted():
    """"I don't have a preference for X; please use your judgment" is a one-shot
    deflection. Reading it as an empty card wastes every remaining turn."""
    state = drive([
        "I'm looking for Tops.",
        "I don't have a preference for material; please use your judgment.",
    ])
    assert "material" not in state.exhausted_attributes


def test_additional_preference_reply_does_mark_exhausted():
    state = drive([
        "I'm looking for Tops.",
        "I don't have an additional preference for material.",
    ])
    assert "material" in state.exhausted_attributes


# --- probing --------------------------------------------------------------

def test_first_ask_is_other_because_other_matches_anything():
    state = drive(["I'm looking for Tops."])
    assert state.ask_attribute == "other"


def test_probe_order_never_asks_category_or_brand():
    """classify_constraint() in the evaluator can never return either, so asking
    is a guaranteed-empty reply and a wasted turn."""
    assert "category" not in PROBE_ORDER
    assert "brand" not in PROBE_ORDER


def test_moves_on_to_specific_attributes_once_other_is_spent():
    state = drive([
        "I'm looking for Tops.",
        "I don't have an additional preference for other.",
    ])
    assert state.ask_attribute in PROBE_ORDER


def test_stops_asking_on_the_final_turn():
    state = fresh()
    for turn in range(1, MAX_TURNS + 1):
        state = update_state(state, "I'm looking for Tops." if turn == 1 else "Those options are not quite right yet.", turn)
    assert state.ask_attribute is None, "an ask on turn 10 can never be answered"


# --- dead turns -----------------------------------------------------------

def test_dead_turn_counter_rises_when_the_query_stops_changing():
    state = drive(["I'm looking for Tops."])
    start = state.exhausted_turns
    for turn in (2, 3):
        state = update_state(state, "Those options are not quite right yet.", turn)
    assert state.exhausted_turns > start


def test_dead_turn_counter_resets_when_the_query_moves_again():
    """Without the reset the window stays parked on a deep page after a later
    disclosure has refreshed the head -- measured as an MRR loss."""
    state = drive(["I'm looking for Tops."])
    state = update_state(state, "Those options are not quite right yet.", 2)
    assert state.exhausted_turns > 0
    state = update_state(state, "For that, what matters is: cotton.", 3)
    assert state.exhausted_turns == 0


# --- cap ------------------------------------------------------------------

def test_turn_is_clamped_at_the_cap():
    state = drive(["I'm looking for Tops."])
    state = update_state(state, "anything", MAX_TURNS + 5)
    assert state.turn == MAX_TURNS
    assert state.ask_attribute is None


# --- phrasing tolerance ---------------------------------------------------

def test_extracts_a_constraint_from_a_paraphrased_carrier():
    """The spec allows the organizer to add paraphrasing. A carrier we have not
    seen before must still yield the constraint, or the state stays empty and
    the whole pipeline collapses."""
    for carrier in (
        "For that, what matters is: cotton twill.",
        "For that, the thing that matters is cotton twill.",
        "For that, what I care about is: cotton twill.",
    ):
        state = drive(["I'm looking for Tops.", carrier])
        joined = " ".join(state.slots.values()).lower()
        assert "cotton twill" in joined, f"nothing extracted from {carrier!r}"
