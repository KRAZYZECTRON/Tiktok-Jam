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

## What I'd try next

- **`intent_override` is still the weakest scenario.** Hits before the override
  turn do not count at all (`if override_applied and target in ranked`), so its
  MTTC floor is 3–4. Worth checking how much of the remaining gap is that floor
  versus genuinely missed targets.
- **Probe order after `"other"` is spent is untested.** `PROBE_ORDER` is a
  reasoned guess, not a measured ranking. Low value — `"other"` drains the card
  in ~2 turns and the probes rarely fire.
- **Nothing here is tuned to the visible 200** beyond the simulator's own
  mechanics, which is deliberate. Resist adding anything that keys off specific
  products or categories.
