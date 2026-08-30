"""Question-value estimation: which attribute would narrow the field most.

A named Innovation Direction in `docs/competition_specification.md` ("adaptive
clarification and question-value estimation"). `dialog._next_attribute` does not
do this — it asks `"other"` until the card is drained and then walks a fixed
probe order. `NOTES_ranking.md` argues that is already optimal here because the
simulator caps disclosure at two constraints per reply and `"other"` matches any
of them. That argument is correct, and it is still only an argument.

This module measures it instead.

## The estimator

The shopper's reply is not arbitrary. `local_evaluator.customer_reply` is:

    matches = [c for c in card if c not in disclosed
               and (attribute == "other" or classify_constraint(c) == attribute)][:2]

and `simcard.card_slots` reconstructs `card` for any catalog product. So for a
*candidate* product we can compute exactly what the shopper would say if that
candidate were the target and we asked about attribute `a`.

Take the set C of products still consistent with everything disclosed, assume
the target is uniform over C, and partition C by the answer each member would
give. If the shopper answers with group g's reply, the consistent set becomes
g. So the expected size of the set after asking `a` is

    E[|C'| | a]  =  sum over groups g of  (|g| / |C|) * |g|

and the value of the question is the expected reduction, `|C| - E[|C'|]`. This
is the standard expected-posterior-size criterion, computed exactly rather than
sampled, because the answer distribution here is fully known.

Note the "no matches" case falls out for free: candidates with no undisclosed
slot of type `a` all give the same reply ("I don't have an additional
preference for a") and therefore form one group. Being told a preference is
absent is genuinely informative, and the estimator gets that without a special
case.

## Off by default

`TJ_QVALUE=1` enables it. It ships disabled because it was measured — see
`tools/question_value.py` and the entry in `SCOREBOARD.md`. The estimator is
correct; the benchmark just cannot reward it, which is a result worth having
rather than a reason not to have built it.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from functools import lru_cache

from .state import DialogState

ENABLED = os.environ.get("TJ_QVALUE") == "1"

# How many consistent candidates rank() hands forward for the estimate. The
# estimator is O(|C| * |attributes|); the collapse means |C| is tiny by the turn
# the question matters, and this only bounds the pathological early turns.
MAX_CANDIDATES = int(os.environ.get("TJ_QVALUE_POOL", "400"))

# The attributes worth asking about. Mirrors ALLOWED_ATTRIBUTES minus the two
# the evaluator's classifier can never return, so we never spend a turn on a
# question whose answer is structurally guaranteed to be empty.
#
# classify_constraint returns exactly one of: budget, material, color, size,
# style, use_case, feature. "brand" and "category" are in ALLOWED_ATTRIBUTES but
# unreachable, and "other" is the wildcard.
CANDIDATE_ATTRIBUTES = (
    "other",
    "material",
    "color",
    "size",
    "style",
    "use_case",
    "budget",
    "feature",
)

# --- classify_constraint, reimplemented -----------------------------------
# Byte-compatible with evaluator.local_evaluator.classify_constraint. Copied
# rather than imported for the same reason simcard.py copies intent_card: the
# official harness may not expose evaluator/ as an importable module, and the
# agent must not depend on that. If that function changes, this and simcard.py
# are the two places to check.
_MATERIALS = ("cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk", "rayon", "fabric")
_BUDGET_RE = re.compile(r"(?:\$|<=|under)\s*\d")


@lru_cache(maxsize=None)
def classify_constraint(value: str) -> str:
    lowered = value.lower()
    if "budget" in lowered or _BUDGET_RE.search(lowered):
        return "budget"
    if any(material in lowered for material in _MATERIALS):
        return "material"
    if any(word in lowered for word in ("color", "black", "white", "blue", "red", "pink", "green")):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work")):
        return "use_case"
    return "feature"


def _reply_for(slots: tuple[str, ...], disclosed: frozenset[str], attribute: str) -> tuple[str, ...]:
    """What the shopper would say if this product were the target.

    Mirrors customer_reply's selection exactly, including the [:2] cap that is
    the whole reason "other" is hard to beat.
    """
    return tuple(
        value
        for value in slots
        if value not in disclosed
        and (attribute == "other" or classify_constraint(value) == attribute)
    )[:2]


def score_attributes(
    candidate_slots: list[tuple[str, ...]],
    disclosed: frozenset[str],
    attributes: tuple[str, ...] = CANDIDATE_ATTRIBUTES,
) -> list[tuple[str, float]]:
    """Expected reduction in the consistent-set size, per attribute, best first.

    Pure function of the reconstructed cards — no catalog, no I/O, no state —
    so it can be tested directly.
    """
    total = len(candidate_slots)
    if not total:
        return [(attribute, 0.0) for attribute in attributes]

    scored: list[tuple[str, float]] = []
    for attribute in attributes:
        groups: dict[tuple[str, ...], int] = defaultdict(int)
        for slots in candidate_slots:
            groups[_reply_for(slots, disclosed, attribute)] += 1
        expected = sum(size * size for size in groups.values()) / total
        scored.append((attribute, total - expected))
    # Ties broken by CANDIDATE_ATTRIBUTES order, which puts "other" first --
    # deliberately, so a tie is resolved toward the shipped behaviour and any
    # difference this estimator makes is a difference it actually earned.
    scored.sort(key=lambda item: -item[1])
    return scored


def best_attribute(state: DialogState) -> str | None:
    """The highest-value question, or None when no question can inform.

    Reads the consistent set rank() stashed on the state during the *previous*
    turn, which is the correct information state: the question for turn N is
    chosen before turn N's retrieval runs.
    """
    slots = getattr(state, "consistent_slots", ()) or ()
    if not slots:
        return None
    disclosed = frozenset(getattr(state, "disclosed_values", ()) or ())
    exhausted = getattr(state, "exhausted_attributes", set()) or set()
    ranked = [
        (attribute, value)
        for attribute, value in score_attributes(list(slots), disclosed)
        if attribute not in exhausted
    ]
    if not ranked:
        return None
    attribute, value = ranked[0]
    # A question with no expected reduction is a wasted turn.
    return attribute if value > 0 else None
