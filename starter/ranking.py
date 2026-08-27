"""Seat 1: LLM semantic re-ranking over the top-N from retrieve().

The baseline does no re-ranking of its own -- the bm25() ORDER BY inside
retrieve() is already the final order -- so this starts as a pass-through.
"""
from __future__ import annotations

from .state import Candidate, DialogState


def rank(candidates: list[Candidate], state: DialogState) -> list[Candidate]:
    return list(candidates)
