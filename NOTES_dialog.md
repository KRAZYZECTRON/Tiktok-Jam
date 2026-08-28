# NOTES — dialog branch (Seat 3)

Running log for `starter/dialog.py::update_state()`. Appended as work happens.
Two of us trade off on this branch, so read the top section before starting.

## Status for whoever picks this up

- Driver so far: **Tanush** (session 1, 28 Aug). Next: YY.
- `dialog` is rebased onto `main` @ `9dfa909`. Do `git pull` first.
- **`starter/agent.py` and `starter/state.py` were both touched.** Flagged to
  Vishwak — see "Shared-file changes" below. Not yet merged.
- Nothing is half-built. The module is complete and scored; the open items in
  "What I'd try next" are ideas, not unfinished work.

## The thing that was actually wrong

The brief pointed at `ask_attribute: None` in `agent.py`, and that was real, but
it was only half of it. The other half is that `agent.py` passed the **raw
current-turn message** to `retrieve()`:

```python
candidates = retrieve(user_message, state, max(POOL_K, top_k))
```

After turn 1 the shopper's message is fixed filler — `"Those options are not
quite right yet."`, `"I don't have an additional preference for color."`. So the
500-candidate pool was being built from tokens like *options*, *preference*,
*judgment*. Stage-A ranking then re-ranked that noise. Turn 1 was the only turn
in a 10-turn session that could ever produce a hit, which is exactly what the
baseline distribution shows: 20.5% of sessions hit at a mean turn of ~1.6, and
the other 79.5% take the 11-turn miss penalty.

Both halves had to be fixed together. Asking a question without accumulating the
answer into the retrieval query just produces a better filler message.

## What `update_state()` does now

1. **Slot accumulation.** Disclosed constraints are parsed out of the reply
   (`"For that, what matters is: X; Y."`) and stored in `state.slots`, keyed by
   attribute. Same-class facts get suffixed keys (`feature`, `feature_2`) rather
   than overwriting — two features per card is the common case and dropping one
   discards a fact that cost a turn.
2. **Composed query.** `state.query` = category + every constraint so far.
   `agent.py` now retrieves on this instead of the current message. The category
   goes first because `retrieve()` truncates at 40 unique terms.
3. **Attribute selection.** `state.ask_attribute` is `"other"` while it pays,
   then specific probes. `"other"` matches *any* undisclosed constraint, so it
   yields two facts per turn where a specific attribute often yields zero — it
   strictly dominates for information gain. `category` and `brand` are never
   asked: `evaluator.classify_constraint()` cannot return either, so they are
   guaranteed-empty replies.
4. **Intent override.** Erases only the overridden preference, keeps the rest.
   See below — this was worth a measured 2nd iteration.
5. **10-turn cap.** Enforced in `update_state`, per the contract. Past the cap it
   stops asking and stops growing the query, leaving the last scored state
   intact. `_next_attribute()` also returns `None` at turn 10, since no turn
   after it can be scored.

The three filler replies are distinguished from each other, which matters more
than it looks:

| reply | meaning | response |
|---|---|---|
| `Those options are not quite right yet.` | we asked nothing | ask something |
| `I don't have a preference for X; please use your judgment.` | boundary scenario's **one-shot** deflection | ask again, it lands next time |
| `I don't have an additional preference for X.` | X genuinely exhausted | mark X spent, probe elsewhere |

The middle and bottom rows differ by the single word *additional*. Treating the
boundary deflection as "card is empty" would strand all 10 boundary sessions.

## Measurements

Full 200-session public set, `py -m evaluator.local_evaluator --output
results_dialog.json`. Score = 0.50·Hit@10 + 0.30·MRR + 0.20·efficiency.

| # | change | Hit@10 | MRR | MTTC | score |
|---|--------|--------|-----|------|-------|
| 0 | `main` @ 9dfa909, reproduced locally | 0.2050 | 0.1045 | 9.08 | 0.1722 |
| 1 | slots + composed query + `ask_attribute` | 0.8500 | 0.5087 | 3.62 | 0.7253 |
| 2 | narrow the override wipe | **0.8700** | **0.5314** | **3.47** | **0.7450** |

Per-scenario, iteration 2 (baseline in brackets):

| scenario | n | Hit@10 (was) | MTTC (was) |
|---|---|---|---|
| boundary | 10 | 1.000 (0.200) | 2.90 (9.00) |
| browsing | 80 | 0.887 (0.150) | 3.21 (9.55) |
| buying | 80 | 0.863 (0.250) | 3.17 (8.54) |
| intent_override | 30 | 0.800 (0.233) | 5.13 (9.30) |

Iteration 2 moved `intent_override` alone: Hit@10 0.667 → 0.800, MTTC 6.10 →
5.13. The other three scenarios are untouched by it, as expected — they have no
override turn.

### Iteration 2 — narrowing the override wipe

`intent_override` was the clear laggard above, and the cause was my own
over-correction. The contract says an override erases rather than blends, so I
cleared every slot. But reading `evaluator.behavior_for()`:

```python
old_value = soft[-1]        # the one preference being overridden
new_value = hard[0]         # what replaces it
```

`old_value` is a *single* constraint, and it is the bare sentence the shopper
opens with in turn 1. Everything else in `slots` arrived from questions we asked
*after* that opening, and none of it was overridden — it still describes the
target. A blanket wipe left those sessions searching on one constraint.

Now only the opening constraint is dropped, identified as the one slot whose
text is a substring of `messages[0]`. `exhausted_attributes` is deliberately not
reset either: the evaluator never clears its `disclosed` set, so an attribute
that came back empty before the override is still empty after it.

## Shared-file changes — flagged, not yet merged

**`starter/agent.py`** (2 lines, no frozen signature moved, both `getattr` with
a fallback so reverting `dialog.py` degrades instead of breaking):

```python
query = getattr(state, "query", "") or user_message
candidates = retrieve(query, state, max(POOL_K, top_k))
...
"ask_attribute": getattr(state, "ask_attribute", None),
```

**`starter/state.py`** — five additive fields with defaults, nothing reordered:
`slots`, `category`, `query`, `ask_attribute`, `exhausted_attributes`.
`slots` is the dict `ranking.split_dialog()` already reads via `getattr` — the
hook was there waiting, this just fills it.

## Honest caveat on the size of this jump

The gain is real but it is worth understanding *why* it is this large, because
it changes how much to trust it.

`evaluator.intent_card()` builds the shopper's constraints out of the target
product's own `features`/`details` text. So every constraint we extract by
asking is a verbatim string from the target document, which BM25 then matches
almost directly. We are not exploiting a scorer bug — this is the intended
ask → learn → refine loop, and the hidden 800 sessions run the same evaluator
code — but the ceiling here is a property of how the simulator writes cards, and
a real shopper paraphrasing in their own words would not hand us exact tokens.

Two consequences:
- Hit@10 0.85 is close to the measured pool ceiling (recall@500 = 0.860 on the
  turn-1 query). Further dialog work has little room; **retrieval's pool width
  is the binding constraint now**, not dialog.
- Don't quote this as "we solved dialog". Quote it as the disclosure loop being
  worth ~4x, which it is.

## Where the remaining 26 misses actually are — for Seat 1 and Seat 2

Replayed all 26 missed sessions keeping the full 500-pool at every turn, to
separate "the target was never retrievable" from "it was retrieved and then
ordered badly". These are different people's problems.

| | count | share |
|---|---|---|
| never in the 500-pool (retrieval ceiling) | **0** | 0% |
| in pool, ranked 11–50 after `rank()` | 21 | 80.8% |
| in pool, ranked >50 after `rank()` | 5 | 19.2% |

**Every single remaining miss is an ordering problem, not a recall problem.**
Mean slots accumulated in a missed session: 3.85, so these are not sessions
where the shopper told us nothing.

This retires the number the whole team has been designing around. The
`recall@500 = 0.860` ceiling in `NOTES_ranking.md`/`SCOREBOARD.md` was measured
**on the turn-1 query**. On the accumulated query the pool contains the target
in 26 of 26 missed sessions. Dense embeddings would now have to earn their
keep by improving *ordering inside the pool*, not by widening recall — worth
Chetan knowing before he spends the remaining hours on the pool.

### Stage-A re-ranking is now a wash

Measured with Vishwak's own `TJ_RANK=off` flag, dialog changes active, full 200:

| | Hit@10 | MRR | MTTC | score |
|---|---|---|---|---|
| `rank()` on | 0.8700 | 0.5314 | 3.47 | 0.7450 |
| `rank()` off (BM25 pool order) | 0.8650 | 0.5544 | 3.53 | **0.7482** |

Session-level: 12 sessions hit *only* with ranking on, 11 hit *only* with it
off, 162 hit either way. So stage A is not broken and should not be deleted —
it is close to break-even, helping boundary (1.000 vs 0.900) and browsing,
costing buying MRR (0.478 vs 0.532) and intent_override (0.800 vs 0.833).

The likely reason is the same one that applied to Chetan's `bm25_limit`
multipliers after the pool went to 500: **stage A's weights were tuned against a
one-turn query.** `BONUS_MATERIAL`, `BONUS_COLOR` and `WEIGHT_CONSTRAINT` were
carrying information that the query itself now carries directly — the material
and colour are literally in the query text, so BM25 already scores them, and
bonusing them again double-counts. This is a re-tune against the new regime, not
a rewrite. It is Seat 1's file and Seat 1's call; flagged, not touched.

## What I'd try next (dialog)

Dialog itself is close to saturated — every scenario now hits about as early as
its structure allows (buying mean turn 1.93, browsing 2.22, override 3.66
against a hard floor of 3.5, since hits before the override turn are not
counted). The remaining ideas are small:

- **Boilerplate slots dilute the query.** Constraints lifted from `details` are
  often near-universal ("Imported", "Machine wash cold"). They eat into
  `retrieve()`'s 40-term budget and add flat `WEIGHT_CONSTRAINT` mass in
  `rank()`. Suppressing them needs IDF, which lives in `ranking.py` — so this is
  better done as term weighting on Seat 1's side than as a stoplist here, which
  would just be overfitting to the visible 200.
- **`PROBE_ORDER` is a reasoned guess, not a measured ranking.** Low value:
  `"other"` drains the card in ~2 turns and the probes rarely fire.
- **Nothing here keys off specific products or categories**, deliberately, and it
  should stay that way — the hidden 800 use different ones.

## Robustness

Fuzzed `update_state()` with 13 malformed inputs (empty, whitespace-only, no
lead-in, truncated payloads, empty `;`-separated parts, 5000-char messages,
unicode, 200 constraints in one reply) — all handled, no exceptions. This
matters because `evaluator.evaluate()` swallows any exception into an empty
recommendation list, so a crash would show up as a silent zero rather than an
error. Turn cap verified to hold at 10 when `update_state` is called 13 times,
with `ask_attribute` going `None` at the cap. `user_profile=None` handled.
