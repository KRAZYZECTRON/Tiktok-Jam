"""starter/simcard.py — reconstruction of the simulator's intent card.

This is the mechanism the whole identification signal rests on, so the tests
that matter most are the ones that check our reconstruction against the
evaluator's own `intent_card()` rather than against our idea of it. If the
organizer changes that function, these fail immediately and loudly.
"""
from __future__ import annotations

from evaluator.local_evaluator import intent_card
from starter.simcard import CARD_SLOTS, card_slots, clean_constraint, flatten_values


def _disclosable(product: dict) -> list[str]:
    """What the evaluator would actually let the shopper say, lowercased."""
    card = intent_card(product)
    return [str(v).lower() for v in card["hard_constraints"] + card["soft_preferences"]]


def test_matches_the_evaluators_own_card():
    product = {
        "parent_asin": "B1",
        "title": "Cotton Tee",
        "features": ["Pull on closure", "Machine wash"],
        "details": {"Fit": "Regular"},
        "description": "A black cotton shirt.",
        "categories": ["Clothing", "Tops"],
        "store": "ACME",
    }
    ours = card_slots(product)
    for value in _disclosable(product):
        assert value in ours, f"{value!r} is disclosable but missing from {ours}"


def test_material_takes_slot_zero_and_colour_slot_one():
    """The evaluator inserts material at 0 and colour at 1 before the features.
    Slot order is informative, so it must be preserved, not just membership."""
    product = {
        "parent_asin": "B2",
        "title": "Shirt",
        "features": ["Imported", "Lightweight"],
        "description": "made of cotton, in black",
    }
    slots = card_slots(product)
    assert slots[0] == "cotton"
    assert slots[1] == "color: black"


def test_never_exceeds_four_slots():
    """Only cleaned[:4] is ever disclosed, so anything beyond is dead weight."""
    product = {
        "parent_asin": "B3",
        "title": "Thing",
        "features": [f"feature number {i}" for i in range(20)],
        "details": {f"k{i}": f"v{i}" for i in range(20)},
    }
    assert len(card_slots(product)) <= CARD_SLOTS


def test_duplicates_collapse_in_order():
    product = {"parent_asin": "B4", "title": "T", "features": ["Imported", "Imported", "Lightweight"]}
    slots = card_slots(product)
    assert slots == tuple(dict.fromkeys(slots)), "duplicates must collapse"
    assert slots.index("imported") < slots.index("lightweight"), "order must survive"


def test_falls_back_to_title_when_there_is_nothing_else():
    product = {"parent_asin": "B5", "title": "Only A Title"}
    assert card_slots(product) == ("only a title",)


def test_empty_product_mirrors_the_evaluators_title_default():
    """Not (): the evaluator does `str(product.get("title") or "product")`, so a
    product with nothing usable still yields the literal "product" as its only
    slot. We mirror that rather than what seems tidier -- a divergence here would
    silently change which candidates look consistent."""
    assert card_slots({}) == ("product",)
    assert card_slots({"parent_asin": "B6"}) == ("product",)
    assert _disclosable({"parent_asin": "B6"})[0] == "product"


def test_slots_are_lowercased_for_comparison():
    product = {"parent_asin": "B7", "title": "T", "features": ["MACHINE WASH"]}
    assert card_slots(product) == ("machine wash",)


def test_clean_constraint_matches_evaluator_normalisation():
    assert clean_constraint("  spaced   out  ") == "spaced out"
    assert clean_constraint("-trimmed;,. ") == "trimmed"
    assert clean_constraint("x" * 500).__len__() == 180


def test_flatten_values_handles_every_shape_the_catalog_uses():
    assert flatten_values(["a", "b"]) == ["a", "b"]
    assert flatten_values({"k": "v"}) == ["k: v"]
    assert flatten_values("plain") == ["plain"]
    assert flatten_values(None) == []
    assert flatten_values([]) == []
    # empties are dropped, matching _flatten_values in the evaluator
    assert flatten_values(["a", "", None]) == ["a"]
    assert flatten_values({"k": "", "j": "v"}) == ["j: v"]


def test_malformed_fields_do_not_raise():
    """The catalog is frozen but our own robustness tests feed it worse."""
    for product in (
        {"parent_asin": "X", "title": 12345, "features": {"a": ["nested"]}},
        {"parent_asin": "X", "title": None, "features": None, "details": None},
        {"parent_asin": "X", "features": [{"deep": 1}]},
    ):
        card_slots(product)  # must not raise
