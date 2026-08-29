# TASKS

`main` is at **`e5b3a2f`** — Hit@10 0.9550 · MRR 0.5729 · MTTC 2.93 · **score 0.8108**
(baseline was 0.1067). Full history and caveats in `SCOREBOARD.md`.

| Task | Owner(s) | Branch | Status |
|------|----------|--------|--------|
| Ranking | Vishwak | main | ✅ merged — stage A + RRF fusion |
| Dialog | YY + Tanush | merged | ✅ merged — accumulated query, `ask_attribute`, rotation |
| Retrieval | Chetan | `retrieval` | ⚠️ pushed (`80f3cd8`), **unmerged — decision pending, see below** |

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

**Next action:** measure the merge on current `main` before deciding. If it does
not clearly beat 0.8108, leave it on the branch and write it up as an evaluated
alternative — that is a legitimate and honest result, not a wasted seat.

Known issues to fix first if it does merge:
- `import numpy as np` is unguarded at module top — a missing numpy kills the
  whole agent at import instead of degrading. The `sentence_transformers`
  import is correctly wrapped; numpy is not.
- The 50k-document encode has no disk cache, so it re-embeds the entire catalog
  on every process start. Real risk under a grading timeout.
- `results_retrieval.json` (1641 lines) is committed. `.gitignore` covers
  `results_*.json` now but will not untrack it — needs `git rm --cached`.

## Remaining work

**Verification**
- [ ] `tools/attribution.py` still hardcodes `ask_attribute=None`; rewrite it to
      drive the real `Agent` and re-run against the 9 remaining misses
- [ ] `RANK_USE_LLM=1` is untested since RRF landed — stage B blends into
      `candidate.score`, which moved from ~30 to ~0.03. Off by default, so it
      cannot affect scoring, but it is unverified
- [ ] Re-run `tools/holdout_check.py` on the shipped config

**Submission packaging**
- [ ] `requirements.txt` (trivial while `main` stays stdlib)
- [ ] `README.md` — setup, exact Python version, one run command, env vars
- [ ] Latency / token / cost disclosure — explicitly required by
      `docs/submission_rules.md`
- [ ] Architecture diagram
- [ ] Devpost description · demo video · the report — Vishwak

**Open, not promised**
- [ ] `intent_override` at 0.867 is the weakest slice and 4 of the 9 misses.
      Any gain here is a bonus; at 0.81 a clean submission is worth more than
      the marginal point.

**Unanswered question that gates the retrieval decision:** does official scoring
run offline / CPU-only? One question to the organizer settles it.

## Standing rules

`evaluator/` and `data/` are read-only. Never two people on one file at once.
Only Seat 1 merges to `main`, and never without a green full-200 run. Every
merge appends a row to `SCOREBOARD.md`.
