"""Seat 2: hybrid BM25 + dense retrieval over the catalog.

Extracted as-is from the original weak-baseline Agent: a SQLite FTS5 BM25
matcher over the whole catalog, built once and reused. Seat 2 improves the
matching/ranking signal here (e.g. add a dense/embedding leg for "hybrid").
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .state import Candidate, DialogState

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
}

_CONNECTIONS: dict[str, sqlite3.Connection] = {}


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


def _connection_for(catalog_path: str) -> sqlite3.Connection:
    """Index is built once per catalog path and cached — rebuilding per call is too slow."""
    if catalog_path not in _CONNECTIONS:
        _CONNECTIONS[catalog_path] = _build_index(catalog_path)
    return _CONNECTIONS[catalog_path]


def retrieve(query: str, state: DialogState, top_k: int) -> list[Candidate]:
    """BM25 match over the catalog FTS index for the current-turn query text."""
    connection = _connection_for(state.catalog_path)
    unique_terms = list(dict.fromkeys(_terms(query)))[:40]
    expression = " OR ".join(f'"{term}"' for term in unique_terms)
    if not expression:
        return []
    rows = connection.execute(
        "SELECT parent_asin FROM products WHERE products MATCH ? "
        "ORDER BY bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) LIMIT ?",
        (expression, top_k),
    ).fetchall()
    return [Candidate(parent_asin=str(row[0])) for row in rows]
