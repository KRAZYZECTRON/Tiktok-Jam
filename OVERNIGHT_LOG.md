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

---

## Iteration 4 — re-verify every documented number, and find a stale safety claim

**Chosen because** the headline claim of this submission is not the score, it is
that everything is measured. One wrong number undermines that whole claim, and
stale figures have already slipped through five times. Three iterations of
changes since many figures were taken made drift likely.

**Added `tools/verify_claims.py`** — re-runs 17 load-bearing documented numbers
and exits non-zero on any mismatch, so it can gate a commit before submission.
Deliberately excludes anything needing torch or a running Ollama: a verification
tool that cannot run on a clean checkout is not a verification tool.

**16 of 17 held. The one that failed was a safety claim**, which is the worst
kind to have wrong.

`CLAUDE.md`, `SCOREBOARD.md` and `agent.py` all cited "hold<=3/min=5 scores
0.24" as the reason never to remove `HOLD_UNTIL_TURN`. Re-measured: **0.8279**.

The figure was taken before `ANSWER_IF_CONSISTENT` existed. Characterising the
current behaviour properly:

| config | early-answer ON | early-answer OFF |
|---|---|---|
| `hold<=2 min=3` (shipped) | 1.0000 / 0.9531 | 1.0000 / 0.9494 |
| `hold<=3 min=5` | 0.8650 / 0.8279 | 0.2400 / 0.2215 |
| `hold<=10 min=9` | 0.7900 / 0.7617 | 0.0000 / **0.000000** |

**The real finding: two independent mechanisms defend this failure and only one
was documented.** `HOLD_UNTIL_TURN` bounds the wait; `ANSWER_IF_CONSISTENT`
rescues a session whose candidate set has already collapsed even when the turn
budget says keep waiting. Remove either and a mis-set threshold degrades; remove
**both** and the agent scores zero.

That matters because `tools/stability.py` reports early-answering as worth
+0.0037 — it reads like a nicety. Someone trimming "dead weight" from the
config could delete the guard that stops a mis-set hold being catastrophic.
Now stated in `CLAUDE.md`, `SCOREBOARD.md`, and enforced by two checks in
`verify_claims.py` including one asserting the unbounded case scores exactly
zero.

**Verified after:** all 17 claims pass, clean 0.953064 / Hit@10 1.0000, 78 tests
pass, `evaluator/` and `data/` untouched. Tool-and-docs only; no source changed.

**Result: adopted.** The stale number is corrected and the undocumented
dependency between the two guards is now written down.

---

## Iteration 5 — the memory figure was wrong, and the footprint shrank

**Chosen because** item 5 was the last substantive engineering item, and the
rules permit grading under a memory cap. But the cheap diagnostic came first,
and it killed the premise.

**The documented 735 MB was wrong twice over.** It was taken with `tracemalloc`
around a block that also built the evaluator's own 50k-product dict — charging
the harness's memory to us — and `tracemalloc` cannot see SQLite's C-heap FTS
index at all, so it was not measuring resident memory either.

Measured properly with `GetProcessMemoryInfo` (what a cgroup or ulimit cap sees):

| | RSS |
|---|---|
| interpreter start | 16 MB |
| + evaluator harness (**not ours**) | 235 MB |
| + our agent warmed | 490 MB -> **255 MB ours** |
| after 200 sessions | 491 MB peak |

So the true story is better than documented: the agent is 255 MB, not 735, and
235 MB of the total belongs to a harness the graders run regardless of our
implementation.

**Then a real reduction.** The catalog is far more repetitive than it looks:
**70% of intent-card slots and 40% of field strings are exact duplicates** of
another product's, each held as a separate object. Pooling them at load so each
distinct string exists once is behaviourally free — equality does not depend on
identity — and the pool is discarded when loading finishes.

  agent 254.8 -> 235.3 MB (-19.5, -7.7%), total peak 491.5 -> 472.2 MB

**Verified after:** clean 0.953064 / Hit@10 1.0000 / MRR 0.946548 (identical),
78 tests pass, all 17 documented claims re-verify, medium robustness 0.924029
unchanged, `evaluator/` and `data/` untouched.

**Result: adopted.** A corrected figure and a free 7.7% reduction. Not pursued
further: `_Catalog.fields` (92 MB) is the next largest block, but every
alternative — re-reading from disk, storing offsets — trades memory for
per-turn latency, and 235 MB is not a number worth paying latency to improve.

---

## Iteration 6 — curated demo transcripts

**Chosen because** it was the last queue item, and because the interesting claim
about this system is not its score but that its reasoning is inspectable turn by
turn. A transcript showing the agent refuse to answer, then identify, then have
a slot erased by an override argues Pillars II and III better than prose.

**Added `tools/demo_transcripts.py`**, which replays all 200 sessions and selects
by *behaviour exercised* rather than by outcome. Six slots, each naming a
behaviour, each filled by the clearest real example:

| behaviour | session |
|---|---|
| refusing to guess, then identifying | `public_0001` |
| an intent override erasing a slot | `public_0002` |
| browsing narrowing from nothing to one candidate | `public_0006` |
| a boundary deflection handled | `public_0035` |
| paging deeper when the shopper runs dry | `public_0020` |
| **a session the agent gets wrong** | `public_0076` |

The last slot is deliberate. A demo reel of only successes invites the question
"what does it look like when it fails?", and the honest answer is a good one:
every rival ranked above the target is equally consistent with everything the
shopper disclosed, so the conversation genuinely does not separate them.

`public_0002` is the strongest single artefact: consistent-product count moves
203 → 18 → 123 as the override lands, `'feature': 'Buckle closure'` visibly
disappears from the slots, and the retrieval query is rewritten without it while
the later-disclosed material constraints survive.

**One weakness noticed and not fixed:** because the probe asks `"other"`, the
customer-facing question is the generic "Tell me a bit more about what matters
to you" rather than something specific. It is honest and it is what the agent
actually says, but a more targeted question would demo better. Recorded rather
than papered over — changing the probe to improve a transcript would be tuning
for the demo instead of for the shopper.

**Verified after:** clean 0.953064 / Hit@10 1.0000, 78 tests pass, all 17
documented claims re-verify, `evaluator/` and `data/` untouched. Tool and
generated-artefact only; no source changed.

**Result: adopted.**

---

## Iteration 7 — does the submission actually reproduce?

**Chosen because** the stated queue was finished, and of the remaining
candidates this one carries a total-loss risk rather than a marginal one:
`docs/submission_rules.md` says an unreproducible run **may be treated as
invalid**. Nothing had ever tested it, and we now write disk caches a fresh
grading environment will not have — 14 of them on this machine.

**Method:** clean worktree at HEAD, all 14 caches moved aside, then the exact
command the README gives.

| | result |
|---|---|
| cold run, no caches | **0.953064** in 36.6 s |
| second run, now warm | **0.953064** in 35.4 s |
| 78 tests in the clean worktree | pass |
| 17 documented claims in the clean worktree | verify |
| system temp made unwritable | **0.953064** |

**Reproduction is sound**, and the caches turn out to be worth ~1.3 s on a 36 s
run — nearly nothing. They are an optimisation, never a dependency, and the
unwritable-temp case degrades silently as intended.

**Two regression tests added**, since both properties are easy to break later:

- `test_works_when_the_temp_directory_is_unwritable` — a sandboxed grader may
  have temp read-only; caches must never become load-bearing.
- `test_no_absolute_paths_baked_into_the_agent` — a path from this machine in
  `starter/` would reproduce only here.

**The second test failed on its first run, and the failure was mine.** It
flagged `starter/llm_rerank.py:35`, which is the localhost Ollama URL — my
pattern matched `p://` inside `http://`. Then the fix was wrong too: a
convoluted lookbehind let `D:\data` through undetected, which I only caught by
probing the compiled pattern against eight cases rather than trusting a green
test. A guard that silently fails to guard is worse than no guard. Final pattern
is `(?<![A-Za-z0-9])[A-Za-z]:[\/]|/home/|/Users/`, verified against all eight.

**Verified after:** 80 tests pass, clean 0.953064 / Hit@10 1.0000, all 17 claims
re-verify, caches restored, worktree removed, `evaluator/` and `data/` untouched.

**Result: adopted.**
