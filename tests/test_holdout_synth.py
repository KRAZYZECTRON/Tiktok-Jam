"""tools/holdout_synth.py — synthesising sessions over targets we never tuned on.

The tool's whole value is that its sessions are (a) genuinely unseen and (b)
indistinguishable to the evaluator from real ones. Both are properties a bug
could quietly break while the tool still printed a plausible number, which is
the failure mode this project has been bitten by most often. So the tests here
check those two things directly, and check them against the evaluator's own
`materialize_hidden_fields` rather than against our idea of what it wants.
"""
from __future__ import annotations

import pytest

from evaluator.local_evaluator import materialize_hidden_fields
from tools.holdout_synth import build, consistent_size, slot_index

PRODUCTS = {
    f"B{i:03d}": {
        "parent_asin": f"B{i:03d}",
        "title": f"Item {i}",
        "features": [f"Feature {i}", "Machine wash"],
        "details": {"Fit": "Regular"},
        "description": "A black cotton shirt.",
        "categories": ["Clothing", "Tops"],
        "store": "ACME",
        "price": 10 + i,
    }
    for i in range(60)
}

SAMPLES = [
    {
        "sample_id": f"public_{i:04d}",
        "scenario_type": ["buying", "browsing", "intent_override", "boundary"][i % 4],
        "ground_truth": {"parent_asin": f"B{i:03d}"},
        "user_profile": {"summary": f"profile {i}", "preference_tags": ["fit"]},
    }
    for i in range(8)
]

SEEN = {s["ground_truth"]["parent_asin"] for s in SAMPLES}


def test_never_reuses_a_target_the_tuning_saw():
    """The one property that makes this a holdout at all."""
    for seed in range(1, 6):
        picked = {s["ground_truth"]["parent_asin"] for s in build(SAMPLES, PRODUCTS, 20, seed)}
        assert not picked & SEEN


def test_targets_are_distinct_within_a_draw():
    synthetic = build(SAMPLES, PRODUCTS, 40, seed=1)
    targets = [s["ground_truth"]["parent_asin"] for s in synthetic]
    assert len(set(targets)) == len(targets)


def test_scenario_mix_matches_the_public_set_exactly():
    """Copied position by position, not resampled — a seed must vary the
    products drawn, never the 80/80/30/10 balance the real set has."""
    synthetic = build(SAMPLES, PRODUCTS, 40, seed=3)
    for offset, sample in enumerate(synthetic):
        assert sample["scenario_type"] == SAMPLES[offset % len(SAMPLES)]["scenario_type"]


def test_same_seed_reproduces_and_different_seeds_do_not():
    first = [s["ground_truth"]["parent_asin"] for s in build(SAMPLES, PRODUCTS, 20, 7)]
    again = [s["ground_truth"]["parent_asin"] for s in build(SAMPLES, PRODUCTS, 20, 7)]
    other = [s["ground_truth"]["parent_asin"] for s in build(SAMPLES, PRODUCTS, 20, 8)]
    assert first == again
    assert first != other


def test_sessions_round_trip_through_the_evaluators_own_materializer():
    """If this fails the tool is measuring something the evaluator would reject,
    and its number means nothing."""
    for sample in build(SAMPLES, PRODUCTS, 20, seed=2):
        card, behavior = materialize_hidden_fields(sample, PRODUCTS)
        assert card["hard_constraints"], sample
        assert behavior["scenario_type"] == sample["scenario_type"]
        if sample["scenario_type"] == "intent_override":
            assert behavior["override"]["turn"] in (3, 4)


def test_asking_for_more_targets_than_exist_fails_loudly():
    """Silently sampling with replacement would inflate the score by scoring the
    same easy targets repeatedly."""
    with pytest.raises(SystemExit):
        build(SAMPLES, PRODUCTS, len(PRODUCTS) + 1, seed=1)


def test_consistent_size_separates_identifiable_from_ambiguous():
    """The report's headline distinction: a session lost with size 1 is a
    defect, one lost with size 40 may be undecidable. Twins must not read as
    uniquely identified."""
    twins = {
        "T1": {"parent_asin": "T1", "title": "Tee", "features": ["Ribbed collar"],
               "details": {}, "description": "", "categories": ["Tops"], "store": "A"},
        "T2": {"parent_asin": "T2", "title": "Tee", "features": ["Ribbed collar"],
               "details": {}, "description": "", "categories": ["Tops"], "store": "A"},
        "U1": {"parent_asin": "U1", "title": "Hat", "features": ["Wide brim"],
               "details": {}, "description": "", "categories": ["Hats"], "store": "B"},
    }
    index = slot_index(twins)
    assert consistent_size("T1", twins, index) == 2
    assert consistent_size("U1", twins, index) == 1
