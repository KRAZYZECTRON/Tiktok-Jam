"""Personalized context distillation — short-term session state, long-term memory.

Two layers, both operating on the anonymized aggregate profile the evaluator
supplies. No raw identifiers are involved; the profile is already a safe summary
(`preference_tags`, `purchase_frequency`, `rating_style`, `average_prior_rating`).

**Short term** — `distil()` turns the free-text profile into a typed structure
once per session, so downstream code reads fields rather than re-parsing prose.

**Long term** — `ProfileMemory` accumulates, across sessions sharing the same
profile signature, what that shopper turns out to search for. This is real here
rather than hypothetical: the evaluator constructs one Agent and calls reset()
per session, and the 200 public sessions contain only 125 distinct profiles —
30 recur, one of them 26 times. So a later session can genuinely benefit from an
earlier one.

What it deliberately does **not** do is learn from outcomes. The agent is never
told whether it hit, so there is no supervision signal and anything claiming to
learn correctness would be fiction. What it accumulates is exposure: which
product categories and which constraint vocabulary this profile has used before.

Privacy note, since this is a memory layer over user data: the signature is a
hash of the aggregate profile the organizer already sanitised, nothing is
written to disk, and the store dies with the process.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
# Profile prose is boilerplate; only the tags inside it carry signal.
PROSE_NOISE = {
    "prior", "purchases", "emphasize", "ratings", "are", "usually", "and",
    "positive", "critical", "mixed", "rating", "style", "purchase", "frequency",
}


@dataclass
class DistilledProfile:
    """One session's view of the shopper, parsed once at reset()."""

    signature: str
    tags: tuple[str, ...] = ()
    prior_rating: float | None = None
    rating_style: str = ""
    purchase_frequency: str = ""


@dataclass
class _Accumulated:
    """What repeated exposure to one profile has taught us."""

    sessions: int = 0
    category_terms: Counter = field(default_factory=Counter)
    constraint_terms: Counter = field(default_factory=Counter)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text or "")
        if len(token) > 2 and token.lower() not in PROSE_NOISE
    ]


def signature_of(profile: dict) -> str:
    """Stable identity for an aggregate profile. Hashed rather than stored raw."""
    try:
        canonical = json.dumps(profile or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(profile)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def distil(profile: dict) -> DistilledProfile:
    """Parse the aggregate profile into typed fields. Never raises on bad input."""
    profile = profile or {}
    tags: list[str] = []
    for tag in profile.get("preference_tags") or []:
        for term in _terms(str(tag)):
            if term not in tags:
                tags.append(term)
    try:
        prior_rating = float(profile.get("average_prior_rating"))
    except (TypeError, ValueError):
        prior_rating = None
    return DistilledProfile(
        signature=signature_of(profile),
        tags=tuple(tags),
        prior_rating=prior_rating,
        rating_style=str(profile.get("rating_style") or ""),
        purchase_frequency=str(profile.get("purchase_frequency") or ""),
    )


class ProfileMemory:
    """Cross-session store, held by the Agent and shared by every session it runs."""

    def __init__(self) -> None:
        self._store: dict[str, _Accumulated] = {}

    def begin(self, profile: dict) -> DistilledProfile:
        distilled = distil(profile)
        self._store.setdefault(distilled.signature, _Accumulated()).sessions += 1
        return distilled

    def observe(self, signature: str, category: str, constraints: list[str]) -> None:
        """Record what this profile searched for. Called as the session runs."""
        entry = self._store.get(signature)
        if entry is None:
            return
        entry.category_terms.update(_terms(category))
        for constraint in constraints:
            entry.constraint_terms.update(_terms(constraint))

    def prior_terms(self, signature: str, exclude: set[str] | None = None) -> dict[str, float]:
        """Terms this profile has used in *earlier* sessions, weighted by how
        consistently they recur. Empty on first exposure, which is the common
        case and must stay cheap."""
        entry = self._store.get(signature)
        if entry is None or entry.sessions <= 1:
            return {}
        exclude = exclude or set()
        weights: dict[str, float] = {}
        for term, count in entry.category_terms.items():
            if term not in exclude:
                weights[term] = count / entry.sessions
        for term, count in entry.constraint_terms.items():
            if term not in exclude:
                weights[term] = max(weights.get(term, 0.0), count / entry.sessions)
        return weights

    def sessions_seen(self, signature: str) -> int:
        entry = self._store.get(signature)
        return entry.sessions if entry else 0
