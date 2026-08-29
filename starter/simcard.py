"""Reconstruct the shopper simulator's intent card for any catalog product.

The simulated shopper does not invent constraints. `local_evaluator.intent_card`
derives them deterministically from the target product's own metadata, and only
the first four survive:

    candidates = flatten(features) + flatten(details)
    insert material at 0 if one appears anywhere in the product's text
    insert "color: x" at 1 if a colour does
    append "budget around $price"
    cleaned  = dedup(normalise(candidates))
    disclosed = cleaned[:2] (hard) + cleaned[2:4] (soft)

That function is invertible in the only direction that matters here. Given what
the shopper has disclosed, we can ask of every candidate: *would your card have
said this?* A product whose own four card slots contain the disclosed strings is
a far stronger match than one that merely happens to contain those words
somewhere in a long description — which is all plain text matching can see, and
why 97 of 99 non-rank-1 sessions were pure tie-breaks before this existed.

Reimplemented here rather than imported from `evaluator/` on purpose. The
evaluator is read-only and, more importantly, the official harness may not
expose it as an importable module; the agent must not depend on that.

Kept byte-compatible with the evaluator's version -- if that file changes, this
is the first place to check.
"""
from __future__ import annotations

import re

CARD_SLOTS = 4
CLEAN_LIMIT = 180

# Mirrors local_evaluator.SEARCH_FIELDS / MATERIAL_RE / COLOR_RE exactly.
SEARCH_FIELDS = ("title", "features", "details", "description", "categories", "store")
MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b", re.I
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b", re.I
)
WHITESPACE_RE = re.compile(r"\s+")
STRIP_CHARS = " -;,.\t\n"


def searchable_text(product: dict) -> str:
    parts: list[str] = []
    for field in SEARCH_FIELDS:
        value = product.get(field)
        if isinstance(value, dict):
            parts.extend(f"{key} {item}" for key, item in value.items())
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).strip()


def flatten_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def clean_constraint(value: str, limit: int = CLEAN_LIMIT) -> str:
    return WHITESPACE_RE.sub(" ", value).strip(STRIP_CHARS)[:limit].rstrip()


def card_slots(product: dict) -> tuple[str, ...]:
    """The <=4 constraint strings this product's card could ever disclose.

    Lowercased for comparison. Order is preserved, because it is informative:
    slot 0 is almost always the material and slot 1 the colour.
    """
    candidates = [*flatten_values(product.get("features")), *flatten_values(product.get("details"))]
    corpus = searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    if material:
        candidates.insert(0, material.group(1).lower())
    if color:
        candidates.insert(1, f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        candidates.append(f"budget around ${product['price']}")

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        value = clean_constraint(item)
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
        if len(cleaned) >= CARD_SLOTS:
            break
    if not cleaned:
        title = clean_constraint(str(product.get("title") or "product"))
        cleaned = [title] if title else []
    return tuple(value.lower() for value in cleaned)
