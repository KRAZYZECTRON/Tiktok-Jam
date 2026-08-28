# NOTES_ranking.md — Seat 1 (ranking + integration), branch `main`

Running log. Newest last. Read this before picking up ranking work cold.

---

## 28 Aug — the finding that shaped everything else

Before writing any ranking code I measured where the ground truth actually sits
in `retrieve()`'s own ordering, on the turn-1 query, across all 200 sessions:

```
recall@10  = 0.185     recall@100 = 0.525
recall@25  = 0.290     recall@200 = 0.685
recall@50  = 0.380     recall@500 = 0.860
```

Median rank of the target is **86**.

`agent.py` was calling `retrieve(msg, state, top_k)` with `top_k=10`, so `rank()`
was handed exactly the ten items the evaluator scores. **Re-ranking ten items
cannot change Hit@10 at all** — only their order, i.e. MRR. Whatever the ranker
did, Hit@10 was pinned under 0.185.

So the first change is not a ranking change: widen the pool.

### Change to the shared file — flagged, needs a team ack

`starter/agent.py`, two lines:

```python
POOL_K = int(os.environ.get("TJ_POOL_K", "500"))
...
candidates = retrieve(user_message, state, max(POOL_K, top_k))
ranked = rank(candidates, state)[:top_k]
```

No signature changed — `retrieve`, `update_state`, `rank` all keep their frozen
contract. `retrieve()` is simply asked for a deeper pool and `rank()` narrows it.

**What Seat 2 needs to know:** `retrieve()` is now called with `top_k=500`, not
10. It must stay reasonable at that depth — that is the whole headroom for the
rest of the pipeline. Current SQLite FTS5 path handles it in ~30 ms.

`TJ_POOL_K=10 TJ_RANK=off` reproduces the original baseline exactly, which is how
every A/B below was taken.

---

## 28 Aug — stage A: state-aware lexical rerank

`rank()` now scores the whole pool against **everything the shopper has said so
far**, not just the current turn — which is all `retrieve()` sees. Per candidate:
IDF-weighted term overlap across title/categories/features/details/store/
description, plus explicit material, colour and budget bonuses (those three are
literally what the evaluator builds its intent cards from — see
`local_evaluator.intent_card`).

Two bugs found by diagnostic rather than by reading, both worth remembering:

1. **The category was being deleted.** My noise-stripper ran the "a key
   requirement is:" extractor and returned only the constraint, so
   `"I'm looking for Jewelry Necklaces. A key requirement is: Material:alloy."`
   scored as *alloy* with `jewelry`/`necklaces` gone entirely. Splitting the
   turn-1 message into category-half and constraint-half fixed it.

2. **Constraints were outweighing the category.** With `WEIGHT_CONSTRAINT` above
   `WEIGHT_CATEGORY`, a query for leather snow boots returned leather *gloves* —
   a perfect constraint match of the wrong kind of object. The category decides
   what kind of thing it is; the constraint only filters within it. Now 2.0 vs
   1.0, and material/colour carry their own bonuses so the constraint text does
   not need the weight.

Also: the simulated shopper emits fixed filler ("Those options are not quite
right yet…", "I don't have an additional preference for…"). Tokenising it
injects words matching half the catalog, so it is stripped before scoring.

**Result, full 200 sessions:**

| | Hit@10 | MRR | MTTC | score |
|---|--------|-----|------|-------|
| baseline | 0.1250 | 0.0680 | 9.81 | 0.1067 |
| stage A | 0.2050 | 0.1045 | 9.08 | 0.1722 |

Biggest movement is browsing, 0.025 → 0.150.

### Methodology warning — cost me an hour

A 40-session subset showed stage A at **0.100 vs baseline 0.125** — i.e. it
looked like a regression — while the full 200 showed 0.205 vs 0.125. At n=40 a
single session is 2.5 points of Hit@10; the subset is fine for smoke-testing and
for MTTC, but **never read a Hit@10 delta off it**. `tools/quick_eval.py` prints
a warning to that effect.

---

## 28 Aug — stage B: LLM rerank (built, not yet scored)

`starter/llm_rerank.py`, behind `RANK_USE_LLM=1`, off by default.

Stage A turns out to be a good funnel and a poor finisher — it lifts recall@100
from 0.525 to 0.645 but recall@10 only from 0.185 to 0.210. That is expected:
term overlap is the same signal BM25 already used. So stage B re-ranks stage A's
**top 50** semantically, where recall is 0.455 — **that is the Hit@10 ceiling for
this stage**, and roughly a 2x headroom over where we are now.

- Local Ollama (`qwen2.5:7b-instruct`) over HTTP, stdlib only — no API key, no
  rate limit, nothing extra for a teammate to install.
- `temperature=0` — a reranker that reshuffles between runs makes A/B unreadable.
- Responses cached to disk by (model, need-text, candidate list), so re-running
  the evaluator after an unrelated change does not re-pay for the LLM.
- Any failure — Ollama down, timeout, malformed output — falls back to stage A's
  order. This stage must never zero a session.
- Real token counts now flow back through `agent.py`'s `usage` field instead of
  the hardcoded zeros.

### Scored — and it failed first

First honest run, same 80 sessions as stage A:

| n=80 | Hit@10 | MRR | MTTC | score |
|------|--------|-----|------|-------|
| stage A | 0.2125 | 0.1242 | 9.06 | 0.1822 |
| stage B, replacing the order | 0.1625 | 0.0914 | 9.48 | 0.1392 |

A clear regression. Two causes, both found by diagnostic:

1. **The model was told the wrong thing.** `_need_text()` had its own copy of
   "pull the useful text out of the messages", built on `_payload()`, which eats
   the turn-1 category. So the model was asked to shortlist for a need of
   `"leather."` with no idea the shopper wanted handbags — and for
   `"Underwear Briefs"` with no gender, where it duly returned ladies' briefs
   against a men's target. Same bug class as the stage-A one above, second
   occurrence, so both stages now share one `split_dialog()`. **If you add a
   third consumer of the dialog text, route it through that function.**

2. **Replacing beats nothing; blending beats something.** Over the sessions
   where the target was already inside stage A's top 50, the model's ordering
   moved it up 6, down 12, and knocked it out of the top 10 six times. It is a
   worse judge than stage A's scoring, but a useful *second opinion*. Its
   ranking is now a bonus added to stage A's score, scaled to the shortlist's
   score spread (`RANK_LLM_WEIGHT`, default 0.3). Knocked-out went 6 → 1.

| full 200 | Hit@10 | MRR | MTTC | score |
|----------|--------|-----|------|-------|
| stage A | 0.2050 | 0.1045 | 9.08 | 0.1722 |
| + stage B blended | 0.2300 | 0.1099 | 8.83 | 0.1914 |

~2 s/session on the GPU, 333k prompt + 8.7k completion tokens for 200 sessions.

### …and it stays off by default anyway

Reading `docs/submission_rules.md` *after* building it: official scoring may run
with **network disabled, CPU-only, under a timeout**, and submissions may not
depend on undeclared external services. Ollama on `localhost:11434` will not be
there. The fallback means we lose nothing when it is absent — we just quietly
score 0.1722 instead of 0.1914.

So stage B is a demo/writeup asset, not a scoring strategy, and
**`main`'s real number is 0.1722**. Full reasoning in `SCOREBOARD.md`.

Lesson worth generalising for the team: read the submission constraints *before*
choosing an architecture, not after. The same question applies to Seat 2's
`sentence-transformers` leg — local weights are more defensible than an HTTP
service, but they still have to be bundled and CPU-fast.

---

## Open questions / next

- **Confirm the scoring environment before anyone builds further on a model.**
  Ask the organizer (or the Fri webinar) whether final scoring runs offline and
  CPU-only. The answer decides whether stage B and Seat 2's embeddings are worth
  anything at all, and it is one question.
- Stage A tuning is the cheap, safe headroom: the weights (`WEIGHT_CATEGORY`,
  the material/colour/budget bonuses) were set by reasoning, not swept. A short
  grid search over the full 200 is ~30 s a run.
- `ask_attribute` is still hardcoded `None` in `agent.py`. The simulated shopper
  only discloses new constraints when asked a specific attribute — until Seat 3
  ships that, every follow-up turn is filler and the query profile never grows
  after turn 1. **This is the single biggest lever left on MTTC**, and it is
  dialog's, not ranking's.
- Pool ceiling is 0.860 @500. Everything above that needs dense retrieval.

---

## 29 Aug - stage A was fighting retrieval, not helping it

Picked this up to re-tune `rank()`'s weights. The brief's premise was that
`BONUS_MATERIAL`/`BONUS_COLOR` double-count now that `dialog.py` composes an
accumulated query - the material and colour are in the query text, so BM25
scores them and stage A bonuses them again.

**That premise is wrong.** Swept both bonuses at 0 / 1.5 / 3 in every
combination, twice (before and after the change below). Hit@10 does not move by
a single session in any of the nine or the eight - only MRR moves, in the fourth
decimal. `BONUS_BUDGET` is provably inert: the rows for 0 and 2.5 are
*identical*, because `evaluator.intent_card()` appends the budget constraint
last and the shopper only ever discloses `cleaned[:4]`, so a `$` never reaches
the query on the public set. Left all three alone rather than churning on noise.

### What was actually wrong

`tools/rank_probe.py` (new) replays the real evaluator loop and records where
the ground truth sits in `retrieve()`'s BM25 ordering and in `rank()`'s ordering
at every scored turn. On the 26 misses:

| target position, last scored turn | in BM25 pool | after `rank()` |
|---|---|---|
| 1-10 | **11** | **0** |
| 11-50 | 9 | 21 |
| 51-100 | 4 | 4 |
| >100 | 2 | 1 |

Eleven of the twenty-six missed sessions had the target sitting in BM25's own
top ten, and `rank()` pushed every single one out. Stage A was not failing to
help; it was actively destroying hits retrieval had already found.

The cause is structural, not a weight. Stage A *replaced* retrieval's ordering,
keeping it only as a flat `(pool - position) / pool` prior worth at most 1.0
against term scores an order of magnitude larger. BM25's opinion was, in
practice, discarded.

### Reciprocal rank fusion

Raising the flat prior helps but cannot fix it: the prior is linear in position,
so at `WEIGHT_PRIOR=25` the whole distance from pool position 1 to position 61
is worth 3.0, still nothing. Swept it anyway to be sure - 0.745 to 0.762 across
`WEIGHT_PRIOR` 1 to 120, a broad flat plateau from 20 up, and the same ten
BM25-top-5 sessions still lost.

So fuse the two *rankings* instead of their scores:

```
score = 1 / (RRF_K + retrieval_rank) + 1 / (RRF_K + stage_a_rank)
```

Reciprocal rank fusion (Cormack et al. 2009). It is steep at the head and almost
flat in the tail, which is exactly the shape wanted here - a candidate BM25 puts
first is expensive to displace, while stage A stays free to promote something
from position 300 that BM25 had no reason to like. It is also scale-free, so
neither side needs calibrating against the other's units, which is the failure
that made the flat prior useless in the first place.

`RRF_K` is flat from 15 to 120 (0.7776-0.7800); kept the standard 60. The fusion
weights peak cleanly at 1:1 - the RRF default, i.e. not tuned at all.

`WEIGHT_CATEGORY` 2.0 to 0.5 is the one genuinely tuned scalar. The old value
was set when stage A replaced BM25 and the category had to dominate to stop
leather snow boots returning leather gloves. Under fusion the category is
already carried by retrieval's ranking, so stage A's job is to discriminate
*within* the category - which is what the constraints do. 0.25 / 0.5 / 0.75 /
1.0 all score 0.784-0.793; 0.5 is the middle of that plateau, not an argmax.

| full 200 | Hit@10 | MRR | MTTC | score |
|---|---|---|---|---|
| stage A as shipped | 0.8700 | 0.5314 | 3.47 | 0.7450 |
| `TJ_RANK=off` (BM25 order) | 0.8650 | 0.5544 | 3.53 | 0.7482 |
| RRF, `WEIGHT_CATEGORY` 2.0 | 0.9050 | 0.5662 | 3.16 | 0.7791 |
| RRF, `WEIGHT_CATEGORY` 0.5 | **0.9250** | **0.5655** | **2.97** | **0.7928** |

53 configurations in total; `tools/rank_sweep.py` runs them without a subprocess
per config (catalog + FTS index load once, module globals mutated between runs),
which is what made a sweep this size affordable.

### On the TJ_RANK=off question

`off` scored 0.7482 against `on`'s 0.7450, which made shipping `off` look
tempting. It was noise: split-half, `off` is **+0.029 on half A and -0.022 on
half B**. Do not ship it. Re-tuning was the right call, and stage A is now worth
+0.048 over BM25 order rather than -0.003.

### Split-half check - read this before quoting the number

Sweeping picks whatever scores best on the 200 visible sessions, which is the
exact procedure that manufactures a number the hidden 800 will not reproduce.
`tools/holdout_check.py` re-scores a configuration on the even- and odd-indexed
halves separately.

The gain is positive on **both** halves - it never loses on either. But it is
lopsided: +0.083 on half A against +0.013 on half B for the weight change alone.
So the sign is trustworthy and the magnitude is not. **0.7928 is a local number.
Plan on the low end.**

And the honest caveat on the check itself: the tuning used all 200, so both
halves are in-sample. This is a stability check, not a holdout - it can show a
gain is fragile, it cannot certify one is real. A clean test needs sessions that
were never in the loop.

### Not done

- Fusion-only vs fusion-plus-`WEIGHT_CATEGORY` was never attributed across the
  halves. The lopsidedness above is most likely the scalar, since the structural
  change behaves the same way on both. Worth an hour if anyone has one.
- Stage B (`llm_rerank.py`) has not been re-scored since fusion landed. Its
  blended bonus is added to a score that no longer exists in the same units -
  `candidate.score` is now an RRF sum around 0.03, not a term total around 30,
  so `RANK_LLM_WEIGHT`'s scaling to "the shortlist's score spread" still works
  but has not been checked. **`RANK_USE_LLM=1` is untested under fusion.**
