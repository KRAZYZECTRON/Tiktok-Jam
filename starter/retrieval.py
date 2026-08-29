"""Seat 2: hybrid BM25 + dense retrieval over the catalog.

Extracted as-is from the original weak-baseline Agent: a SQLite FTS5 BM25
matcher over the whole catalog, built once and reused. Seat 2 improves the
matching/ranking signal here (e.g. add a dense/embedding leg for "hybrid").
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .state import Candidate, DialogState

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
}

_CONNECTIONS: dict[str, sqlite3.Connection] = {}
_CATALOGS: dict[str, "CatalogIndex"] = {}
_EMBED_MODELS: dict[str, object] = {}
_DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"


@dataclass
class CatalogIndex:
    parent_asins: list[str]
    texts: list[str]
    dense_vectors: np.ndarray | None = None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _catalog_text(product: dict) -> str:
    return " \n".join(
        part
        for part in (
            _text(product.get("title")),
            _text(product.get("categories")),
            _text(product.get("features")),
            _text(product.get("details")),
            _text(product.get("store")),
            _text(product.get("description")),
        )
        if part
    )


def _build_index(catalog_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()
    cursor.execute(
        "CREATE VIRTUAL TABLE products USING fts5("
        "parent_asin UNINDEXED, title, categories, features, details, store, description, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    batch: list[tuple[str, str, str, str, str, str, str]] = []
    with Path(catalog_path).open(encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            batch.append(
                (
                    str(product["parent_asin"]),
                    _text(product.get("title")),
                    _text(product.get("categories")),
                    _text(product.get("features")),
                    _text(product.get("details")),
                    _text(product.get("store")),
                    _text(product.get("description")),
                )
            )
            if len(batch) >= 1000:
                cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                batch.clear()
    if batch:
        cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
    connection.commit()
    return connection


def _catalog_for(catalog_path: str | Path) -> CatalogIndex:
    key = str(catalog_path)
    if key not in _CATALOGS:
        parent_asins: list[str] = []
        texts: list[str] = []
        with Path(catalog_path).open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                parent_asins.append(str(product["parent_asin"]))
                texts.append(_catalog_text(product))
        _CATALOGS[key] = CatalogIndex(parent_asins=parent_asins, texts=texts)
    return _CATALOGS[key]


def _connection_for(catalog_path: str) -> sqlite3.Connection:
    """Index is built once per catalog path and cached — rebuilding per call is too slow."""
    if catalog_path not in _CONNECTIONS:
        _CONNECTIONS[catalog_path] = _build_index(catalog_path)
    return _CONNECTIONS[catalog_path]


def _embed_model() -> object | None:
    if _DEFAULT_EMBED_MODEL in _EMBED_MODELS:
        return _EMBED_MODELS[_DEFAULT_EMBED_MODEL]
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        _EMBED_MODELS[_DEFAULT_EMBED_MODEL] = None
        return None
    try:
        model = SentenceTransformer(_DEFAULT_EMBED_MODEL)
    except Exception:
        _EMBED_MODELS[_DEFAULT_EMBED_MODEL] = None
        return None
    _EMBED_MODELS[_DEFAULT_EMBED_MODEL] = model
    return model


def _ensure_dense_vectors(catalog_path: str) -> CatalogIndex:
    catalog = _catalog_for(catalog_path)
    if catalog.dense_vectors is not None:
        return catalog
    model = _embed_model()
    if model is None:
        catalog.dense_vectors = np.zeros((0, 0), dtype=np.float32)
        return catalog
    vectors = model.encode(
        catalog.texts,
        batch_size=256,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    catalog.dense_vectors = np.asarray(vectors, dtype=np.float32)
    return catalog


def _classify_intent(query: str, state: DialogState) -> str:
    text = " ".join(state.messages[-3:] + [query]).lower()
    buying_cues = {
        "buy", "buying", "budget", "cheap", "color", "delivery", "exact", "gift",
        "inch", "inches", "lightweight", "material", "price", "replacement",
        "size", "small", "medium", "large", "under", "waterproof", "wireless",
    }
    browsing_cues = {
        "any", "best", "browse", "browsing", "explore", "ideas", "maybe",
        "options", "recommend", "show", "trending", "what", "which",
    }
    if any(char.isdigit() for char in text):
        return "buying"
    buying_hits = sum(cue in text for cue in buying_cues)
    browsing_hits = sum(cue in text for cue in browsing_cues)
    if buying_hits >= browsing_hits + 1:
        return "buying"
    return "browsing"


def _query_text(query: str, state: DialogState, intent: str) -> str:
    if intent == "buying":
        return query
    history = list(dict.fromkeys(message.strip() for message in state.messages[-3:] if message.strip()))
    if query not in history:
        history.append(query)
    return " ".join(history)


def _bm25_candidates(
    connection: sqlite3.Connection,
    query_text: str,
    limit: int,
) -> list[str]:
    unique_terms = list(dict.fromkeys(_terms(query_text)))[:40]
    expression = " OR ".join(f'"{term}"' for term in unique_terms)
    if not expression:
        return []
    rows = connection.execute(
        "SELECT parent_asin FROM products WHERE products MATCH ? "
        "ORDER BY bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) LIMIT ?",
        (expression, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _dense_candidates(catalog_path: str, query_text: str, limit: int) -> list[tuple[str, float]]:
    catalog = _ensure_dense_vectors(catalog_path)
    if catalog.dense_vectors is None or catalog.dense_vectors.size == 0:
        return []
    model = _embed_model()
    if model is None:
        return []
    query_vector = np.asarray(
        model.encode(
            [query_text],
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0],
        dtype=np.float32,
    )
    similarities = catalog.dense_vectors @ query_vector
    if limit >= len(similarities):
        indices = np.argsort(-similarities)
    else:
        candidate_idx = np.argpartition(-similarities, limit - 1)[:limit]
        indices = candidate_idx[np.argsort(-similarities[candidate_idx])]
    return [
        (catalog.parent_asins[int(index)], float(similarities[int(index)]))
        for index in indices[:limit]
    ]


def retrieve(query: str, state: DialogState, top_k: int) -> list[Candidate]:
    """Hybrid retrieval: preserve BM25 precision while adding dense semantic recall."""
    connection = _connection_for(state.catalog_path)
    intent = _classify_intent(query, state)
    query_text = _query_text(query, state, intent)
    bm25_limit = max(top_k * (8 if intent == "browsing" else 5), top_k)
    dense_limit = max(top_k * (10 if intent == "browsing" else 4), top_k)
    bm25_weight = 0.45 if intent == "browsing" else 0.7
    dense_weight = 1.0 - bm25_weight

    bm25_results = _bm25_candidates(connection, query_text, bm25_limit)
    dense_results = _dense_candidates(state.catalog_path, query_text, dense_limit)
    if not bm25_results and not dense_results:
        return []

    fused: dict[str, float] = {}
    for rank, parent_asin in enumerate(bm25_results, start=1):
        fused[parent_asin] = fused.get(parent_asin, 0.0) + bm25_weight / rank
    for rank, (parent_asin, similarity) in enumerate(dense_results, start=1):
        dense_rank_score = dense_weight / rank
        dense_similarity_score = dense_weight * max(similarity, 0.0)
        fused[parent_asin] = fused.get(parent_asin, 0.0) + dense_rank_score + dense_similarity_score

    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [Candidate(parent_asin=parent_asin, score=score) for parent_asin, score in ranked]
