# Overnight log

Unsupervised iterations. Newest last. Every number here was re-run on a clean
tree before being written down.

Baseline defended throughout:

| | |
|---|---|
| clean 200 sessions | 0.953064, Hit@10 1.0000 |
| robustness | none 0.9531 / light 0.9305 / medium 0.9240 / heavy 0.8915 |
| `evaluator/` and `data/` | untouched (checked each iteration) |
| pushes | none — all work is committed locally for morning review |

---

## Iteration 1 — a real test suite

**Chosen because** `tests/` held only the organizer's three tests and *nothing*
covered the six modules we wrote. Technical Execution is 35% of judging and the
largest single gap was that a reader had no way to tell which behaviours are
intentional. It is also the highest-value work that cannot regress the score,
which matters when nobody is reviewing.

**Added 75 tests across five files** (78 total with the organizer's):

| file | n | what it pins down |
|---|---|---|
| `test_simcard.py` | 10 | card reconstruction, checked *against the evaluator's own `intent_card()`* rather than against our idea of it |
| `test_dialog.py` | 18 | slot accumulation, override erasure, boundary-vs-exhausted, probe order, dead-turn counter, the 10-turn clamp |
| `test_orchestrate.py` | 18 | strategy selection at every boundary, the `HOLD_UNTIL_TURN` bound, window paging |
| `test_profile.py` | 12 | signature stability, distillation, long-term memory, junk tolerance |
| `test_agent_contract.py` | 17 | the interface the organizer actually scores, plus hardening and the pure-stdlib guarantee |

**Two tests failed first, and in both cases the test was wrong, not the code.**
Worth recording because both would have been easy to "fix" in the wrong
direction:

1. `card_slots({})` returns `("product",)`, not `()`. The evaluator does
   `str(product.get("title") or "product")`, so a product with nothing usable
   still yields the literal string `"product"` as its only slot. Mirroring that
   exactly is the point of the module; "tidying" it would silently change which
   candidates count as consistent. Test rewritten to assert the mirror.
2. "turn 1 always holds back" is false against a three-product fixture — the
   consistent set is immediately tiny, so `ANSWER_IF_CONSISTENT` correctly fires
   and turn 1 answers. That test was asserting a property of the fixture, not of
   the agent. Restated as an invariant: *whenever* the list is empty, the message
   must read as a question.

**Tests worth singling out**, because they encode constraints that are
expensive to rediscover:

- `test_the_bound_always_wins_past_hold_until_turn` — removing `HOLD_UNTIL_TURN`
  scores 0.24. The contract says never remove it; now something enforces that.
- `test_runs_with_numpy_and_sentence_transformers_absent` — simulates the
  absence of numpy, torch and sentence-transformers together and asserts the
  agent still answers. This is the pure-stdlib guarantee, checked rather than
  asserted in prose.
- `test_scored_path_opens_no_socket` — monkeypatches `socket.socket` to raise.
  Verifies the offline claim by making a violation fail loudly.
- `test_ask_attribute_is_allowed_or_none` — an out-of-vocabulary attribute is
  silently coerced to `"other"` by the simulator, wasting the ask. Silent
  failures deserve tests more than loud ones.
- `test_extracts_a_constraint_from_a_paraphrased_carrier` — guards the fix that
  took paraphrase robustness from 0.48 to 0.03. Easy to regress by "simplifying"
  the three-step extractor.

**Verified after:** clean 0.953064 / Hit@10 1.0000; robustness none 0.953064,
light 0.930547, medium 0.924029, heavy 0.891482 — all identical to baseline, as
expected for a test-only change. `evaluator/` and `data/` untouched.

**Result: adopted.** Tests only, no source changed.

---

## Iteration 2 — how much of the shipped config is real

**Chosen because** every tunable was adopted on one even/odd split. One draw.
The hidden 800 use different users and products, so knowing which choices are
structural and which were luck is worth more than another +0.002 — and it is
information nobody had.

**Cheap first:** the naive design is hundreds of evaluator runs. `evaluate()`
returns per-session results, so each config runs over the full 200 **once** and
every split is computed by aggregating subsets of the cached session list. Nine
configs, ~4 minutes, then unlimited splits free. Same random partitions reused
across every choice so comparisons are like-for-like.

**Added `tools/stability.py`.** 200 random split-halves:

| choice | full delta | both+ | verdict |
|---|---|---|---|
| post-fusion card promotion | +0.0843 | 100% | structural |
| popularity tie-break | +0.0225 | 100% | structural |
| early answer when identified | +0.0037 | 100% | structural |
| post-fusion category match | +0.0016 | 82% | probably real |
| hold-back threshold 3 (vs 4) | +0.0007 | 52% | coin flip |
| fuzzy card tier | +0.0008 | 50% | coin flip (adopted for robustness) |
| rating tie-break | +0.0002 | 8% | likely luck |
| exact-phrase bonus | +0.0001 | 0% | inert |
| verbatim category bonus | -0.0000 | 0% | inert |

**Findings worth a human's attention in the morning:**

1. **Three choices carry the whole margin** — +0.111 of +0.115. The rest is
   rounding. That is a much cleaner story for the writeup than nine tunables.
2. **The rating tie-break failed this project's own standard.** Adopted on one
   split showing +0.0011/+0.0025; over 200 splits it holds 8% of the time with a
   full-set gain of +0.0002, under the +0.002 noise floor. I adopted it and I
   was wrong to.
3. **Two exact-match bonuses are now inert**, subsumed by the post-fusion layer.
   Removing the category one even scores fractionally higher (0.953089).

**Not reverted, deliberately.** Reverting any of them drops the score below the
frozen 0.953064 baseline, and the standing instruction for unsupervised work is
to report rather than act on this basis. Flagged in `SCOREBOARD.md` for a human.

**Verified after:** clean 0.953064 / Hit@10 1.0000, 78 tests pass, `evaluator/`
and `data/` untouched. Tool-and-docs only; no source changed.

**Result: adopted** (the tool and the finding).

---

## Iteration 3 — robustness with error bars, and three new perturbation styles

**Chosen because** iteration 2 established that single-draw estimates are
unreliable — and the robustness numbers quoted in README and SCOREBOARD were
themselves single-seed point estimates. The same weakness, in claims I had
already published. Fixing the measurement before adding more claims.

**Added to `tools/robustness.py`:** `--seeds N` reporting mean/min/max/spread,
plus three perturbation levels chosen for what they probe rather than for
severity:

- `interject` — a stray clause before the constraint, plus a foreign-language
  fragment. Probes whether the bounded lead-in prefix in the extractor overflows.
- `truncate` — a mid-sentence cut, as if the shopper hit send early. Extraction
  must yield a *shorter* constraint, not a wrong one.
- `adversarial` — decoy colon, doubled punctuation, FTS metacharacters. Nothing
  should raise and the real constraint should still survive.

**Results, 5 seeds per level (7,000 sessions):**

| level | mean | spread | worst Hit@10 |
|---|---|---|---|
| none | 0.953064 | 0.000 | 1.0000 |
| light | 0.930350 | 0.003 | 1.0000 |
| medium | 0.929159 | 0.011 | 0.9900 |
| heavy | 0.890615 | 0.012 | 0.9800 |
| interject | 0.920960 | 0.011 | 0.9900 |
| adversarial | 0.889718 | 0.016 | 0.9750 |
| truncate | **0.855272** | 0.022 | 0.9300 |

**Two findings:**

1. **The medium figure I have been quoting (0.9240) is the minimum of five
   seeds, not the mean (0.9292).** Conservative rather than wrong, but a point
   estimate presented without its uncertainty — precisely what iteration 2
   criticised in the tunables. README and SCOREBOARD now carry mean and spread,
   and say plainly that the earlier numbers were single-seed.

2. **Truncation is the weakest case by a clear margin** — 0.8553, costing 0.098,
   with Hit@10 falling to 0.93 at worst. Mechanism: a mid-string cut leaves text
   that neither equals a card slot nor reaches the 75% token overlap the fuzzy
   tier needs.

**Not fixed, and that is a judgement rather than an omission.** Truncation is
explicitly outside the spec's allowed assumptions — "inputs are pre-cleaned text
strings" — so it cannot appear in the graded set. Loosening the fuzzy threshold
to catch it would weaken discrimination on inputs that *are* in scope, and a 0.6
threshold was already measured worse (0.568 vs 0.597 at 0.75). Measured and
documented as a real deployment gap rather than defended.

**Verified after:** clean 0.953064 / Hit@10 1.0000, 78 tests pass, `evaluator/`
and `data/` untouched. Tool-and-docs only.

**Result: adopted** (the instrumentation and the corrected figures).
