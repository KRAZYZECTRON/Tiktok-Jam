"""Tests for component matching of "; "-joined card slots (ranking.CARD_COMPONENT_MATCH).

`_disclosed_constraints` splits the shopper's reply on ";" because the evaluator
joins several constraints that way. But `simcard.card_slots` can also emit a
SINGLE slot with "; " inside it, and then the split shatters one slot into parts
that match nothing -- the conjunctive filter empties and the identification
signal, worth +0.084, switches off.

Diagnosed by `tools/extract_probe.py` over 800 unseen sessions: 23 sessions
where the target fails its own card, zero of them a vocabulary gap, and the
examples all this shape. Adopted on a held-out gain of +0.0023 across four
seeds with the public score exactly unchanged.
"""
from __future__ import annotations

from starter.ranking import CARD_COMPONENT_MATCH, _catalog_for, _disclosed_constraints

CATALOG = "data/catalog.jsonl"


def test_component_matching_is_on_by_default():
    assert CARD_COMPONENT_MATCH is True


def test_disclosed_constraints_split_on_semicolons():
    """The behaviour that creates the mismatch in the first place."""
    out = _disclosed_constraints(["solid colors: 100% cotton; heather grey: 90% cotton"])
    assert out == ("solid colors: 100% cotton", "heather grey: 90% cotton")


def test_catalog_indexes_components_of_compound_slots():
    catalog = _catalog_for(CATALOG)
    compound = [
        asin for asin, slots in list(catalog.card.items())[:5000]
        if any("; " in slot for slot in slots)
    ]
    assert compound, "no compound slots in the first 5000 products; test is vacuous"
    asin = compound[0]
    parts = catalog.card_parts.get(asin)
    assert parts, f"{asin} has a compound slot but no indexed components"
    # Every indexed part must really be a piece of one of that product's slots.
    joined = " ".join(catalog.card[asin])
    for part in parts:
        assert part.split(":")[0][:12] in joined.lower() or part[:12] in joined.lower()


def test_a_shattered_constraint_now_matches_its_slot():
    """The end-to-end property: agent's split pieces resolve against the whole."""
    catalog = _catalog_for(CATALOG)
    for asin, slots in catalog.card.items():
        compound = next((s for s in slots if "; " in s), None)
        if not compound:
            continue
        pieces = _disclosed_constraints([compound])
        if len(pieces) < 2:
            continue
        parts = catalog.card_parts.get(asin, frozenset())
        # Each piece the agent would extract is recoverable as a component.
        assert all(p in slots or p in parts for p in pieces), (
            f"{asin}: {pieces} not recoverable from {parts}"
        )
        return
    raise AssertionError("no compound slot found in the catalog; test is vacuous")


def test_products_without_compound_slots_are_not_indexed():
    """The index stays small: only compound slots cost anything."""
    catalog = _catalog_for(CATALOG)
    assert len(catalog.card_parts) < len(catalog.card), (
        "every product got a component set; the 'only compound slots' guard is broken"
    )
