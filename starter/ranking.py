"""Seat 1: re-ranking over the candidate pool from retrieve().

Two stages, both operating on a *wide* pool (agent.py retrieves POOL_K, this
narrows to the top 10 the evaluator actually scores):

  Stage A (here, no LLM): score every pooled candidate against the *accumulated*
    dialog state -- every constraint the shopper has disclosed so far, not just
    the current turn's message, which is all retrieve() sees.
  Stage B (starter/llm_rerank.py, optional): LLM semantic re-rank of the top of
    stage A's ordering. Off unless RANK_USE_LLM=1, so the evaluator stays fast.

Why the wide pool matters -- measured recall of the ground truth in retrieve()'s
own ordering on the turn-1 query (see NOTES_ranking.md):
    recall@10 = 0.185    recall@100 = 0.525    recall@500 = 0.860
Re-ranking can only reorder what it is handed, so a 10-candidate pool caps
Hit@10 at 0.185 no matter how good the ranker is. The pool width is the lever.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import tempfile
from collections import Counter
from pathlib import Path

from .state import Candidate, DialogState

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")

# Kept in sync with retrieval.py -- the same words are noise on both sides.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
}

# The simulated shopper emits fixed boilerplate when it has nothing to add.
# Tokenising these pollutes the query with words like "preference"/"judgment"
# that match half the catalog, so they are dropped before scoring.
NOISE_PATTERNS = (
    re.compile(r"^those options are not quite right yet\.?", re.I),
    re.compile(r"^i don'?t have an additional preference for\b", re.I),
    re.compile(r"^i don'?t have a preference for\b", re.I),
    re.compile(r"\bask me about one specific attribute\b", re.I),
    re.compile(r"\bplease use your judgment\b", re.I),
    re.compile(r",?\s*but i'?m still exploring\.?", re.I),
)
# Turn 1 is always "I'm looking for {category}." plus, for some scenarios, a
# constraint clause. The category half is the strongest single signal there is,
# so it is split off rather than swallowed by the constraint extractor.
LEAD_RE = re.compile(r"^\s*i'?m looking for\s+", re.I)
# "Actually, ignore my earlier preference. What I need is: X."
OVERRIDE_RE = re.compile(r"\bignore my earlier preference\b", re.I)
# The informative half of a reply: "For that, what matters is: X; Y."
PAYLOAD_RE = re.compile(r"(?:what matters is|a key requirement is|what i need is)\s*:?\s*(.+)", re.I)

FIELD_WEIGHTS = {
    "title": 6.0,
    "categories": 4.0,
    "features": 2.5,
    "details": 2.5,
    "store": 1.5,
    "description": 1.0,
}

# The category decides *what kind of thing* this is; a constraint only filters
# within it. Weighting them the other way round returns leather gloves to
# someone who asked for leather snow boots -- measured, not hypothetical.
# Material/colour get their own bonuses below, so the constraint text itself
# does not need to carry that weight.
WEIGHT_CATEGORY = 2.0
WEIGHT_CONSTRAINT = 1.0
BONUS_MATERIAL = 3.0
BONUS_COLOR = 3.0
BONUS_BUDGET = 2.5
# Profile tags are things like "fit"/"comfort" -- they match most of the
# catalog, so they break ties and nothing more.
BONUS_PROFILE_TAG = 0.1

MATERIAL_RE = re.compile(r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b", re.I)
COLOR_RE = re.compile(r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b", re.I)

_CATALOGS: dict[str, "_Catalog"] = {}


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


class _Catalog:
    """Product text + IDF, built once per catalog path and cached on disk.

    Only pooled candidates are ever tokenised (lazily, memoised) -- tokenising
    all 50k products up front costs seconds per run and most are never scored.
    """

    def __init__(self, catalog_path: str) -> None:
        self.path = catalog_path
        self.fields: dict[str, dict[str, str]] = {}
        self.price: dict[str, float] = {}
        self.idf: dict[str, float] = {}
        self._token_cache: dict[str, dict[str, set[str]]] = {}
        self._load()

    def _cache_file(self) -> Path:
        stat = Path(self.path).stat()
        key = f"{Path(self.path).resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
        # hashlib, not hash() -- str hashing is salted per process, so hash()
        # would mint a new cache file on every run and never hit.
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return Path(tempfile.gettempdir()) / f"tj4_rank_idf_{digest}.pkl"

    def _load(self) -> None:
        document_frequency: Counter[str] = Counter()
        documents = 0
        with Path(self.path).open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                parent_asin = str(product["parent_asin"])
                self.fields[parent_asin] = {
                    name: _text(product.get(name)) for name in FIELD_WEIGHTS
                }
                raw_price = product.get("price")
                if raw_price not in (None, ""):
                    try:
                        self.price[parent_asin] = float(raw_price)
                    except (TypeError, ValueError):
                        pass
                documents += 1

        cache = self._cache_file()
        if cache.exists():
            try:
                self.idf = pickle.loads(cache.read_bytes())
                return
            except Exception:
                pass

        # IDF over title + categories only: short, high-signal, and ~10x faster
        # to tokenise than the full description text.
        for parent_asin, fields in self.fields.items():
            seen = set(_terms(fields["title"])) | set(_terms(fields["categories"]))
            document_frequency.update(seen)
        self.idf = {
            term: math.log(1.0 + documents / (1.0 + count))
            for term, count in document_frequency.items()
        }
        try:
            cache.write_bytes(pickle.dumps(self.idf))
        except Exception:
            pass

    def tokens(self, parent_asin: str) -> dict[str, set[str]]:
        cached = self._token_cache.get(parent_asin)
        if cached is None:
            fields = self.fields.get(parent_asin)
            if fields is None:
                cached = {name: set() for name in FIELD_WEIGHTS}
            else:
                cached = {name: set(_terms(text)) for name, text in fields.items()}
            self._token_cache[parent_asin] = cached
        return cached

    def blob(self, parent_asin: str) -> str:
        fields = self.fields.get(parent_asin)
        return " ".join(fields.values()) if fields else ""


def _catalog_for(catalog_path: str) -> _Catalog:
    if catalog_path not in _CATALOGS:
        _CATALOGS[catalog_path] = _Catalog(catalog_path)
    return _CATALOGS[catalog_path]


def _strip_noise(message: str) -> str:
    """Drop the shopper's fixed filler. Does *not* touch the constraint clause --
    turn 1 still needs the category half, which lives before it."""
    text = message.strip()
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _payload(message: str) -> str:
    """The informative half of a follow-up reply, minus its lead-in."""
    found = PAYLOAD_RE.search(message)
    return found.group(1) if found else message


def _query_profile(state: DialogState) -> tuple[dict[str, float], str]:
    """Accumulate weighted query terms across the whole conversation.

    Falls back to raw messages, but prefers structured slots if dialog.py has
    started populating them (Seat 3) -- so this keeps working either way.
    """
    messages = list(getattr(state, "messages", []) or [])
    slots = getattr(state, "slots", None)
    if not messages:
        return {}, ""

    # Split turn 1 into "what they are shopping for" and "the first constraint".
    opening = _strip_noise(messages[0])
    payload = PAYLOAD_RE.search(opening)
    if payload:
        category_text = LEAD_RE.sub("", opening[: payload.start()])
        opening_constraint = payload.group(1)
    else:
        category_text = LEAD_RE.sub("", opening)
        opening_constraint = ""
    category_text = category_text.strip(" .,;")

    constraint_texts: list[str] = [opening_constraint] if opening_constraint else []

    if isinstance(slots, dict) and slots:
        constraint_texts = [str(value) for value in slots.values() if value]
    else:
        for message in messages[1:]:
            # An override wipes everything disclosed before it -- the shopper
            # changed their mind, so blending old and new constraints is wrong.
            if OVERRIDE_RE.search(message):
                constraint_texts.clear()
            cleaned = _payload(_strip_noise(message)).strip()
            if cleaned:
                constraint_texts.append(cleaned)

    weights: dict[str, float] = {}
    for term in _terms(category_text):
        weights[term] = weights.get(term, 0.0) + WEIGHT_CATEGORY
    for text in constraint_texts:
        for term in _terms(text):
            weights[term] = weights.get(term, 0.0) + WEIGHT_CONSTRAINT

    for tag in (state.user_profile or {}).get("preference_tags", []) or []:
        for term in _terms(str(tag)):
            weights[term] = weights.get(term, 0.0) + BONUS_PROFILE_TAG

    constraint_blob = " ".join([category_text, *constraint_texts])
    return weights, constraint_blob


def _score(parent_asin: str, weights: dict[str, float], blob: str, catalog: _Catalog) -> float:
    tokens = catalog.tokens(parent_asin)
    total = 0.0
    for term, weight in weights.items():
        idf = catalog.idf.get(term, 1.0)
        for field, field_weight in FIELD_WEIGHTS.items():
            if term in tokens[field]:
                total += weight * field_weight * idf
                break  # a term counts once, at its highest-weighted field

    product_text = catalog.blob(parent_asin).lower()

    material = MATERIAL_RE.search(blob)
    if material and material.group(1).lower() in product_text:
        total += BONUS_MATERIAL
    color = COLOR_RE.search(blob)
    if color and color.group(1).lower() in product_text:
        total += BONUS_COLOR

    budget = PRICE_RE.search(blob)
    price = catalog.price.get(parent_asin)
    if budget and price:
        target = float(budget.group(1))
        if target > 0:
            ratio = abs(price - target) / target
            if ratio <= 0.5:
                total += BONUS_BUDGET * (1.0 - ratio / 0.5)

    return total


def rank(candidates: list[Candidate], state: DialogState) -> list[Candidate]:
    """Re-rank the pool against everything the shopper has said so far."""
    if not candidates or os.environ.get("TJ_RANK") == "off":
        return list(candidates)

    catalog = _catalog_for(state.catalog_path)
    weights, blob = _query_profile(state)
    if not weights:
        return list(candidates)

    # retrieve() returns its pool already in BM25 order; keep a small
    # prior on that so a total scoring miss degrades to retrieval's answer
    # rather than to noise.
    total = len(candidates)
    for position, candidate in enumerate(candidates):
        prior = (total - position) / total
        candidate.score = _score(candidate.parent_asin, weights, blob, catalog) + prior

    ordered = sorted(candidates, key=lambda item: item.score or 0.0, reverse=True)

    if os.environ.get("RANK_USE_LLM") == "1":
        from .llm_rerank import llm_rerank

        return llm_rerank(ordered, state, catalog)
    return ordered
