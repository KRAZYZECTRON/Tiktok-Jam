# TASKS

`main` — Hit@10 **1.0000** · MRR 0.6406 · MTTC 2.465 · **score 0.8629**
(baseline was 0.1067). Full history and caveats in `SCOREBOARD.md`.

| Task | Owner(s) | Branch | Status |
|------|----------|--------|--------|
| Ranking | Vishwak | main | ✅ merged — stage A + RRF fusion |
| Dialog | YY + Tanush | merged | ✅ merged — accumulated query, `ask_attribute`, rotation |
| Retrieval | Chetan | `retrieval` | ❌ **not merging — measured, see below** |

## Retrieval: pending a decision, not pending work

Chetan's hybrid BM25 + dense branch is finished and merges cleanly into current
`main`. It is unmerged because two things changed underneath it:

1. **It was built against a 0.205 pipeline.** Its tuning constants assume
   `retrieve()` is called on the raw turn message. `dialog.py` now passes a
   composed `state.query`, which is a different input distribution.
2. **Its premise is undercut.** The dense leg exists to close a paraphrase gap
   between what the shopper says and how the product is described. But the
   simulated shopper discloses constraints as *verbatim strings from the target
   product's own `features` field* — so on the public set there is no paraphrase
   gap for embeddings to close.

Against that, merging it costs the thing `main` currently has for free: it is
**pure stdlib**, and official scoring may run offline and CPU-only. Adding
`numpy` + `torch` + a HuggingFace download trades a real robustness advantage
for a benefit nobody has yet measured on the current pipeline.

**Measured, and the answer is no.** Merged onto `main` and scored, dense leg
absent (which is exactly the offline-grading case): **0.807951 against 0.810768**
— a slight regression, before the later improvements took `main` to 0.862880.

The decisive evidence arrived afterwards. `tools/attribution.py` now reports
**MISS_RETRIEVAL = 0**: the existing BM25 pool contains the target in all 200
sessions, and Hit@10 is **1.0000**. There is no retrieval failure left for a
dense leg to fix. Merging it would trade the pure-stdlib property — our immunity
to an offline, CPU-only grading run — for a measured negative.

**This is a real result, not a wasted seat**, and it belongs in the writeup: a
hybrid dense retriever was built, evaluated, and rejected on evidence. The
branch stays for that purpose.

Known issues to fix first if it does merge:
- `import numpy as np` is unguarded at module top — a missing numpy kills the
  whole agent at import instead of degrading. The `sentence_transformers`
  import is correctly wrapped; numpy is not.
- The 50k-document encode has no disk cache, so it re-embeds the entire catalog
  on every process start. Real risk under a grading timeout.
- `results_retrieval.json` (1641 lines) is committed. `.gitignore` covers
  `results_*.json` now but will not untrack it — needs `git rm --cached`.

## Remaining work

**Verification** — all done
- [x] `tools/attribution.py` rewritten to drive the real `Agent`
- [x] `RANK_USE_LLM=1` re-tested after RRF — **regression (−0.014), stays off**
- [x] `tools/holdout_check.py` re-run — both halves reach Hit@10 1.0000,
      deltas +0.0466 / +0.0460

**Submission packaging**
- [x] `requirements.txt` — no runtime dependencies
- [x] `README.md` — setup, Python version, one run command, disclosures
- [x] Latency / token / cost disclosure — measured via `tools/perf.py`
- [x] Architecture diagram — ASCII in `README.md` (a designed version for
      Devpost is still worth doing)
- [ ] Devpost description · demo video · the report — Vishwak

**Open**
- Hit@10 is **1.0000 and cannot improve**. Only MRR (0.6406, 30% weight) and
  MTTC (2.465 → efficiency 0.8535, 20% weight) can still move, worth about
  +0.11 and +0.029 respectively at their theoretical limits.
- Roughly 100 of 200 hits land at rank 1; the rest spread over ranks 2-10. All
  remaining headroom is in telling near-identical clothing items apart. The
  cheap tuning levers are exhausted — see the rejected table in `SCOREBOARD.md`
  before trying anything, several plausible ideas are already disproved.

**The offline question is now moot for scoring** — `main` is pure stdlib, calls
no model and opens no socket, so it is unaffected either way. Still worth
confirming for the writeup.

## Standing rules

`evaluator/` and `data/` are read-only. Never two people on one file at once.
Only Seat 1 merges to `main`, and never without a green full-200 run. Every
merge appends a row to `SCOREBOARD.md`.
