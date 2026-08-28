"""Seat 1, stage B: LLM semantic re-rank of stage A's shortlist.

Enabled with RANK_USE_LLM=1; off by default so the evaluator stays fast enough
to iterate on the rest of the pipeline.

Why this stage exists, in numbers (turn-1 recall of the ground truth, 200
public sessions -- see NOTES_ranking.md):

    BM25 order        @10 = 0.185   @50 = 0.380
    after stage A     @10 = 0.210   @50 = 0.455

Stage A is a good funnel and a poor finisher: it concentrates the target into
the top 50 but barely improves the top 10, because term overlap is the same
signal BM25 already used. Re-ranking those 50 semantically is the part that can
actually move Hit@10, and 0.455 is its ceiling.

Talks to a local Ollama over HTTP with nothing but the standard library -- no
API key, no rate limit, no extra dependency to install on a teammate's machine.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import pickle
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .state import Candidate, DialogState

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("RANK_LLM_MODEL", "qwen2.5:7b-instruct")
SHORTLIST = int(os.environ.get("RANK_LLM_SHORTLIST", "50"))
KEEP = int(os.environ.get("RANK_LLM_KEEP", "10"))
TIMEOUT = float(os.environ.get("RANK_LLM_TIMEOUT", "60"))
# How hard the model's opinion pushes against stage A's score, as a fraction of
# the shortlist's score spread. 0 = stage A untouched, 1 = model dominates.
LLM_WEIGHT = float(os.environ.get("RANK_LLM_WEIGHT", "0.3"))
TITLE_CHARS = 110

SYSTEM = (
    "You match shoppers to products. You are given what a shopper is looking "
    "for and a numbered list of candidate products. Reply with ONLY a JSON "
    "array of the numbers of the 10 best matches, best first, e.g. "
    "[7,2,19,1,5,33,8,12,40,3]. No prose, no explanation."
)

_cache: dict[str, list[int]] | None = None
_cache_path = Path(tempfile.gettempdir()) / "tj4_llm_rerank_cache.pkl"
_usage = {"prompt_tokens": 0, "completion_tokens": 0}


def _load_cache() -> dict[str, list[int]]:
    global _cache
    if _cache is None:
        try:
            _cache = pickle.loads(_cache_path.read_bytes())
        except Exception:
            _cache = {}
        # Flushed at exit rather than per call -- an evaluator run makes
        # thousands, and without this the cache never survives the process.
        atexit.register(save_cache)
    return _cache


def save_cache() -> None:
    if _cache is not None:
        try:
            _cache_path.write_bytes(pickle.dumps(_cache))
        except Exception:
            pass


def usage() -> dict[str, int]:
    """Tokens spent since the last drain -- agent.py reports these."""
    spent = dict(_usage)
    _usage["prompt_tokens"] = 0
    _usage["completion_tokens"] = 0
    return spent


def _need_text(state: DialogState) -> str:
    """What the shopper is after, with the product type stated first.

    Goes through ranking.split_dialog so the category cannot be dropped -- an
    earlier version built this separately and sent the model needs like
    "leather." with no idea the shopper wanted handbags.
    """
    from .ranking import split_dialog

    category, constraints = split_dialog(state)
    seen: list[str] = []
    for value in constraints:
        value = value.strip(" .;,")
        if value and value not in seen:
            seen.append(value)
    need = category.strip() or "a clothing item"
    if seen:
        need += ". Requirements: " + "; ".join(seen)
    return need[:600]


def _call(prompt: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        # Deterministic: a reranker that reshuffles between runs makes every
        # A/B unreadable.
        "options": {"temperature": 0.0, "num_predict": 64},
    }).encode()
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read())
    _usage["prompt_tokens"] += int(payload.get("prompt_eval_count") or 0)
    _usage["completion_tokens"] += int(payload.get("eval_count") or 0)
    return str(payload.get("message", {}).get("content", ""))


def _parse(text: str, limit: int) -> list[int]:
    """Pull the index list out of whatever the model actually said."""
    found = re.search(r"\[[^\]]*\]", text)
    chunk = found.group(0) if found else text
    order: list[int] = []
    for token in re.findall(r"\d+", chunk):
        value = int(token)
        if 1 <= value <= limit and value not in order:
            order.append(value)
    return order


def llm_rerank(candidates: list[Candidate], state: DialogState, catalog) -> list[Candidate]:
    """Re-rank the head of stage A's ordering; the tail keeps its order."""
    head = candidates[:SHORTLIST]
    tail = candidates[SHORTLIST:]
    if len(head) < 2:
        return candidates

    need = _need_text(state)
    if not need:
        return candidates

    lines = []
    for index, candidate in enumerate(head, start=1):
        title = catalog.fields.get(candidate.parent_asin, {}).get("title", "")
        title = re.sub(r"\s+", " ", title).strip()[:TITLE_CHARS]
        lines.append(f"{index}. {title}")
    listing = "\n".join(lines)

    cache = _load_cache()
    key = hashlib.sha256(f"{MODEL}\0{need}\0{listing}".encode()).hexdigest()

    order = cache.get(key)
    if order is None:
        prompt = (
            f"Shopper is looking for: {need}\n\n"
            f"Candidates:\n{listing}\n\n"
            f"Return the {KEEP} best matches as a JSON array of numbers, best first."
        )
        try:
            order = _parse(_call(prompt), len(head))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            # Ollama down, slow, or talking nonsense: stage A's order is a
            # perfectly good answer. Never let this stage zero a session.
            return candidates
        cache[key] = order

    if not order:
        return candidates

    # Blend, don't overwrite. Letting the model's ordering replace stage A's
    # measured worse: it moved the target up in 6 sessions but down in 12, and
    # knocked it out of the top 10 in 6. As a *bonus* on top of stage A's score
    # it can promote what it is confident about without discarding a good
    # placement stage A already made.
    scores = [item.score or 0.0 for item in head]
    spread = (max(scores) - min(scores)) or 1.0
    for position, index in enumerate(order[:KEEP]):
        candidate = head[index - 1]
        candidate.score = (candidate.score or 0.0) + LLM_WEIGHT * spread * (KEEP - position) / KEEP

    head = sorted(head, key=lambda item: item.score or 0.0, reverse=True)
    return head + tail
