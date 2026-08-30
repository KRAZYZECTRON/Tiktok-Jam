# Overnight log

## Morning summary — read this first

**Nothing regressed. Nothing was pushed.** Eleven commits are waiting on local
`main` for your review.

| | verified on a fresh run at 06:32 |
|---|---|
| clean 200 sessions | **0.953064**, Hit@10 **1.0000**, MRR 0.946548, MTTC 2.545 |
| tests | **80 passed** (was 3 — the organizer's) |
| documented claims re-verified | **19/19** via `py -m tools.verify_claims` |
| robustness (3 seeds) | light 0.9302 · medium 0.9268 · heavy 0.8932 · interject 0.9188 · adversarial 0.8890 · truncate 0.8589 |
| `evaluator/` and `data/` | untouched, checked every iteration |

### What the night was actually about

I set out to add things and mostly ended up **checking things**. Ten of eleven
iterations found a claim we had already published to be wrong. None of them
changed the score; all of them changed what we can honestly say about it.

| what was claimed | what is true |
|---|---|
| nine tunables earning their place | **three** carry +0.111 of the +0.115; two are inert, one was luck |
| robustness figures | they were **single-seed draws**, and the medium number quoted was the *minimum* of five |
| "hold≤3/min=5 scores 0.24" — the reason never to remove `HOLD_UNTIL_TURN` | it scores **0.8279**; the figure predated a second guard nobody had documented |
| peak memory ~735 MB | **235 MB is ours**; the rest was the evaluator's own harness, and `tracemalloc` could not see SQLite anyway |
| `BONUS_EXACT_PHRASE` worth +0.016 | **+0.00008** — subsumed, while a table 350 lines away in the same file already said so |
| `NOTES_ranking.md` "Open questions" | wrong in **all four lines**, including "`ask_attribute` is still hardcoded `None`" |
| `holdout_check.py`'s "+0.031 vs original" | "original" still contained the post-fusion layer; the real figure is ~+0.85 |

Two of those were **my own process failures**, and they are the ones I would
most want you to see:

- Iteration 4 said it fixed a stale figure in three files. It fixed two. The
  wrong number sat in `agent.py` for five more iterations while the log said it
  was handled.
- Iteration 2 noticed `holdout_check.py`'s configs were stale, mentioned it in
  passing, and moved on. Noticing a defect and moving on records it as *known*,
  which later reads as *resolved*.

### Three decisions that need you

None were acted on overnight: each would push the score below the frozen
0.953064 baseline, and the standing instruction was to report rather than act.
All three are in `SCOREBOARD.md`.

1. **The rating tie-break never met our own bar.** Adopted on one split showing
   +0.0011/+0.0025; over 200 random splits it holds **8%** of the time, full-set
   gain +0.0002 — under the +0.002 noise floor this project set for itself.
2. **`BONUS_EXACT_PHRASE` and `BONUS_EXACT_CATEGORY` are inert.** Both were real
   when adopted; the post-fusion layer has since subsumed them. Removing the
   category one scores fractionally *higher*.
3. **Seven of eleven tools reach into private agent internals** (`agent._states`,
   `ranking._catalog_for`). A justified diagnostic liberty, but an `agent.py`
   refactor breaks seven tools silently.

### Also worth knowing

- **The submission reproduces cold**: 0.953064 from a clean checkout with all 14
  caches removed, and again with the system temp directory unwritable. That was
  an untested total-loss risk — the rules say an unreproducible run may be
  treated as invalid.
- **Two mechanisms defend the hold-back cliff, not one.** `HOLD_UNTIL_TURN`
  bounds the wait; `ANSWER_IF_CONSISTENT` rescues an already-collapsed candidate
  set. Remove either and it degrades; remove **both** and the agent scores
  exactly zero. Early-answering looks like a +0.0037 nicety in the stability
  table. Do not delete it as dead weight.
- **`DEMO_TRANSCRIPTS.md`** holds six sessions picked by behaviour, including one
  the agent gets wrong, ready for the video and writeup.
- **Truncated input is the weakest case** (0.8589) and is deliberately not
  defended — it sits outside the spec's "inputs are pre-cleaned text strings".

### Still untouched, as agreed

Devpost description, demo video, and the report. The team message drafted
earlier was never sent, and `main` on GitHub is still at `fc41a5e` — eleven
commits behind this tree.

---

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

---

## Iteration 8 — two SCOREBOARD tables contradicted the rest of the file

**Chosen because** iteration 4 established that documented numbers drift, and
the sweep tables were the largest block nothing checked. They record
measurements taken at *past* pipeline states, which is legitimate as history —
but only if labelled. Unlabelled, a judge re-running one gets a different number
and concludes we are sloppy rather than rigorous.

**Cheap first:** re-ran the two cheapest sweeps rather than reasoning about
whether they had drifted.

**Both had, and one had become false.**

`BONUS_EXACT_PHRASE`, as documented: "the score rises monotonically to 120 and
is then flat", 0.8402 -> 0.8560, a +0.016 gain.

| bonus | 0 | 12 | 250 | 1000 |
|---|---|---|---|---|
| documented | 0.8402 | 0.8505 | 0.8560 | 0.8560 |
| **current** | 0.952981 | 0.953064 | 0.953064 | 0.953064 |

It is now worth **+0.00008** and is flat from 12 upward. The post-fusion card
term added later expresses the same signal where rank fusion cannot flatten it,
and has subsumed this one entirely. The section describing it as load-bearing
sat about 350 lines above the stability table reaching the opposite conclusion
independently (0% of splits) — **the file contradicted itself.**

`WEIGHT_CATEGORY`, as documented: 0.5 / 1.0 / 2.0 -> 0.8108 / 0.8096 / 0.8028,
"a 0.008 spread across a 4x range".

| | 0.5 | 1.0 | 2.0 | 5.0 |
|---|---|---|---|---|
| documented | 0.8108 | 0.8096 | 0.8028 | — |
| **current** | 0.953064 | 0.953314 | 0.953004 | 0.953127 |

Here the *conclusion* survives and is stronger — 0.0003 across a 10x range
rather than 0.008 across 4x, and non-monotonic. Still a plateau, 0.5 still fine.
Only the numbers were wrong.

**Both tables now carry historical and current rows side by side**, because the
historical figure is what justified the decision at the time and the current one
is what a reader reproduces. Deleting the history would hide the reasoning;
leaving it unlabelled misleads.

**Both are now in `verify_claims.py`** (17 -> 19 checks), so the next drift
fails loudly instead of sitting in the file for a week.

**Verified after:** all 19 claims pass, clean 0.953064 / Hit@10 1.0000, 80 tests
pass, `evaluator/` and `data/` untouched. Docs and verifier only.

**Result: adopted.**

---

## Iteration 9 — auditing the claims inside shipped code, and a miss of my own

**Chosen because** iteration 8 found `SCOREBOARD.md` contradicting itself, and
the same drift risk applies to the `NOTES_*` files and — worse — to justification
comments inside `starter/`, which a judge reads directly. Nothing had checked
either all night.

**The first finding was a miss from iteration 4.** That iteration corrected the
stale hold-back cliff figure and its log entry says it fixed "CLAUDE.md,
SCOREBOARD.md and agent.py". It did not fix `agent.py` — the grid at lines 45-50
still read `hold<=3 min=5  0.2750 / 0.2438`, the figure measured before
`ANSWER_IF_CONSISTENT` existed. **I reported a fix I had not made.** Now
corrected, with both the early-answering-on and -off rows and the note that two
mechanisms defend that failure.

**`recall@10 = 0.185 / @100 = 0.525 / @500 = 0.860`, asserted in `agent.py` as
the justification for `POOL_K = 500`, re-measured: exactly unchanged.** A rare
case where nothing had drifted, and the reason is instructive — with the dense
leg off, the merged intent-routed retrieval reduces to the same BM25 ordering,
exactly as claimed when it was merged. Only the median rank moved, 86 -> 73;
`agent.py` now says 73 and records that the claim was re-verified post-merge.

**A third comment stated reasoning I later disproved.** The `CONFIDENCE_MAX`
block still carried the per-session "6:1 in favour of waiting" arithmetic. That
argument was *wrong* — it assumed the delayed hit still happens, and unbounded
holding collapsed Hit@10 to 0.90. The comment now says so, and points at
`MIN_DISCLOSED` as the bounded version that works.

**`NOTES_ranking.md` had a stale "Open questions / next" section, wrong in all
four lines**, sitting mid-file where it reads as current guidance:

| open question, 28 Aug | reality now |
|---|---|
| confirm whether scoring is offline before building on a model | answered by measurement instead; both optional paths built, measured, disabled |
| stage A weights unswept, cheap headroom | swept; two are now inert |
| `ask_attribute` still hardcoded `None`, biggest lever left | implemented — it *was* the biggest lever, 0.205 -> 0.87 |
| pool ceiling 0.860, above that needs dense retrieval | both halves wrong: ceiling retired, and dense measured harmful |

Rewritten as a resolved table rather than deleted. What was open at the time is
part of the reasoning; read alone it was simply misleading.

**Verified after:** 80 tests pass, 19 documented claims re-verify, clean
0.953064 / Hit@10 1.0000, `evaluator/` and `data/` untouched. Comments and docs
only; no executable change.

**Result: adopted.** The lesson worth keeping is the first one: iteration 4
claimed a fix in three files and delivered it in two, and nothing caught that for
five iterations. Reporting a fix is not making one.

---

## Iteration 10 — the last two unaudited documents

**Chosen because** iteration 9 found four wrong lines in `NOTES_ranking.md`, and
these two had never been checked. Both turned out to mislead in the same way:
not by stating falsehoods, but by **stopping before the story ended**.

**`NOTES_retrieval.md` ends on 2026-08-27** with "First measured result: Hit@10
`0.22`" and no mention that the branch was later merged, that the dense leg was
run for the first time and *lost*, or that it is now behind `TJ_DENSE=1`. Read
on its own — which is how a judge reads a per-seat notes file — it implies dense
retrieval is live and carrying that 0.22. Appended an integration entry with the
measurement (0.9254 with dense against 0.9531 without, 774.6 s cold encode), the
mechanism (constraints are verbatim strings from the target's own `features`, so
there is no paraphrase gap for embeddings to close), and the two robustness
fixes the merged code needed.

I also made a point of writing that this does **not** make the branch wasted
work: the intent routing ships and is one of two named Pillar I requirements,
and "we built it, measured it, rejected it on evidence" is a stronger line than
carrying an untested dense leg. A notes file that reads as a rebuke of a
teammate's work would be both unfair and inaccurate.

**`NOTES_dialog.md` quoted per-scenario MTTC from before the hold-back was
re-tuned:**

| scenario | as written | now |
|---|---|---|
| buying | 1.93 | 2.05 |
| browsing | 2.22 | 2.56 |
| intent_override | 3.66 | 3.63 |

Worth stating carefully rather than just correcting: **the rise is not a
regression.** It is the hold-back deliberately trading turns for rank, which
took MRR 0.66 → 0.94. Someone reading only the drift could reasonably conclude
dialog had got worse. Both columns now sit side by side with that explanation,
and the override floor of 3.5 is marked as structural — it comes from the
override landing on turn 3 or 4 with equal probability, so no dialog change can
beat it.

**Verified after:** 80 tests pass, 19 documented claims re-verify, clean
0.953064 / Hit@10 1.0000, `evaluator/` and `data/` untouched. Docs only.

**Result: adopted.** With this every document in the repo has now been audited
against a fresh run at least once tonight.

---

## Iteration 11 — a tool that measured something other than its label

**Chosen because** `tools/` was the last unexamined surface, and because in
iteration 2 I noticed `holdout_check.py`'s baked-in configs were stale, said so
in passing, and did not fix it. That is the same pattern as iteration 4's unmade
fix. A tool printing a misleading number is worse than one that does not exist,
because someone will quote it.

**The defect.** `holdout_check.py` compares three configurations and prints
`delta, best swept minus original`. But its `ORIGINAL` dict overrides only the
fusion mode and a few stage-A weights — **every later addition (the post-fusion
card, category, popularity and rating terms) stays at its shipped value in every
row, including the one called "original"**. So the headline delta of +0.031 was
never "what tuning was worth"; the real figure from the kit baseline to shipped
is about +0.85. The row was mislabelled, not miscomputed.

**Not deleted, because the measurement is real.** Holding the post-fusion layer
constant and varying only fusion and weights is a legitimate thing to know. What
was wrong was calling the baseline "original" and the delta "best swept minus
original". Now:

- the row is `old fusion+weights`, not `original`
- the delta says "from the fusion and weight choices alone" and states
  explicitly that every row already contains the post-fusion layer
- the module docstring opens by warning that the labels used to overstate the
  scope, and redirects to `tools/stability.py`, which supersedes it: one shipped
  choice at a time, against the real shipped config, over 200 partitions

`README.md` updated to name `stability.py` as the honest instrument and describe
`holdout_check.py` as the narrower, older one.

**Also noted, not acted on:** seven of the eleven tools reach into private agent
internals (`agent._states`, `ranking._catalog_for`, `_terms`, `_score`). That is
a deliberate diagnostic liberty — `_states` is the only way to see the composed
query — but it means a refactor of `agent.py` would break seven tools silently.
Worth a human's judgement rather than an overnight refactor of working
diagnostics.

**Verified after:** 80 tests pass, 19 documented claims re-verify, clean
0.953064 / Hit@10 1.0000, `evaluator/` and `data/` untouched.

**Result: adopted.** Second instance tonight of a problem I had already spotted
and left. Both are now fixed; the pattern is worth naming — noticing a defect
and moving on records it as known, which reads later like it was handled.

---

## Iteration 12 — the required standalone report

**Chosen because** it is a hard deliverable, not an improvement.
`docs/competition_specification.md` lists "a short report covering architecture,
models, cost, limitations, and team contributions" under Final Deliverables, and
`docs/submission_rules.md` repeats it as "a short report describing method,
model choice, and limitations". Neither is satisfied by `README.md`, which is a
repository guide addressed to someone running the code, not a report addressed
to a judge. `TASKS.md` has carried this as unchecked since 29 Aug.

**Written:** `REPORT.md`, nine sections.

Three editorial choices worth recording, because they are the reason it is not
just README.md rearranged:

1. **It leads with the mechanism, not the score.** Section 1 is the invertible
   simulator and the median-consistent-set collapse (2574 → 78 → 1). The score
   does not appear until section 2. A judge scoring Innovation & Problem Insight
   at 20% is reading for whether we understood the problem, and "the job is
   identification, not ranking" is the sentence that demonstrates it.
2. **The held-out row is printed above the in-sample row**, with "read the
   second row first" in bold over the table. 0.9189 is the number that predicts
   the hidden 800; 0.9531 is the ceiling. Burying that would be the single
   easiest way to lose credibility if a judge ran `holdout_synth` themselves.
3. **Both disabled capabilities are stated as measurements with mechanisms**
   (−0.014 for the LLM stage under RRF, −0.027 and a maxed Hit@10 surrendered
   for the dense leg), not as "we tried it and it didn't help". Section 4 also
   states the gating rationale explicitly: the environment must not be able to
   change our answer.

**One correction made during drafting.** The first draft invented a surname for
the ranking seat that appears nowhere in the repository or the git history. The
only attributions available are `TASKS.md` and `git shortlog`; the report now
uses exactly the names those record. Fabricating an author name in a deliverable
that will be read by an employer would have been a serious error, and it was
mine to catch before commit rather than a human's to catch after.

**Not claimed:** no new measurements were taken for this document. Every figure
in it is quoted from an existing verified source — `results.json`,
`results_perf.json`, the `holdout_synth` draws, the `robustness` table, and
`stability.py`. Two figures were taken fresh from `results.json` rather than
from the docs, because the docs are known to be stale in six places and fixing
that is queue item (4); the report is therefore *ahead* of README.md and
SCOREBOARD.md on the per-scenario intent_override MRR (0.9075, not 0.8909) and
the current MRR (0.9465, not 0.9438).

**Verified after:** 102 tests pass, 20 documented claims re-verify, `evaluator/`
and `data/` untouched. New file only; no code path changed.

**Result: adopted.** Queue item (1) of 12 complete.

---

## Iteration 13 — the Devpost submission text

**Chosen because** it is the second of three hard deliverables and the one that
is read first. Track 4's deliverables require a written project description
covering how the solution addresses the problem statement plus development
tools, APIs, libraries, and datasets used. None of that existed.

**Written:** `DEVPOST.md`, structured so each `##` heading maps to a Devpost
form field and can be pasted directly.

**The framing decision.** Technical Execution is 35% but Innovation & Problem
Insight and Impact & Relevance are 20% each — 40% combined, and both are scored
on whether the reader believes we *understood* the problem rather than on the
number. So the document opens on the baseline's actual defect (`ask_attribute:
None` means every turn after the first re-queries on filler, so turn 1 is the
only turn that can hit) and moves from there to the invertible simulator. The
score table is third, not first.

**Three claims were checked against live output before writing them down**,
rather than copied from README.md, which is known stale in six places:

- `context_demo --sample public_0002` really does run CLARIFY at **203**
  consistent candidates and switch to IDENTIFY at **18**, and the turn-3
  override really does erase the `feature` slot while keeping both `material`
  slots. Re-run tonight; all three match.
- Public MRR is **0.9465** and intent_override MRR is **0.9075**, taken from
  `results.json` rather than from the docs.

**One more stale figure found while drafting.** `README.md` says the hold-back
runs "until four constraints are disclosed". `MIN_DISCLOSED` has been **3** since
the 29 Aug re-tune against the stronger ranker, and `agent.py` says so. That is
a seventh entry for the queue-item-(4) staleness sweep, and it was found by
writing the disclosure paragraph rather than by grepping — the disclosures are
the part of the docs a judge is most likely to test against the code, so an
error there costs more than the same error in a results table.

**Disclosures are a section, not a footnote.** Both metric-aware behaviours are
stated with their kill switches, and the rotation disclosure spells out that the
evaluator records rank *within the ten returned*, so paging inflates MRR as well
as Hit@10. If a judge is going to find that, they should find it in our own text.

**Verified after:** 102 tests pass, 20 documented claims re-verify, `evaluator/`
and `data/` untouched. New file only; no code path changed.

**Result: adopted.** Queue item (2) of 12 complete.

---

## Iteration 14 — the demo video script, and a finding that changed it

**Chosen because** it is the third and last hard deliverable, and the only one
that cannot be finished without a human. Getting it wrong wastes someone's
recording session rather than just costing a document.

**The finding that shaped the whole script: four of the six tools we would want
to show are too slow to film, and I only know that because I timed them instead
of assuming.**

| command | measured tonight |
|---|---|
| `tools.context_demo --sample public_0002` | **6.4 s** |
| `pytest tests/ -q` | **0.9 s** |
| `evaluator.local_evaluator` | **34.7 s** |
| `tools.holdout_synth --seeds 1` | 68.3 s |
| `tools.stability` | **273 s** |
| `tools.verify_claims` | **378 s** |

`stability` and `verify_claims` are 4.5 and 6.3 minutes. A three-minute video
cannot contain either. Worse, **neither writes its output to a file** — both
print to stdout only — so they cannot even be `cat`-ed on camera without a prep
step that captures them first. The script now opens with that prep step and a
table saying explicitly which shots are live and which are pre-captured.

Had the script been written from the queue item as given, it would have told a
human to run `py -m tools.stability` on camera and they would have discovered
the 4.5-minute wait with the recorder running.

**Structure.** Six shots. The two that must never be cut are named as such:

- **Shot 3** (`context_demo`, live, 6.4 s runtime / 50 s of screen time) is the
  only place the system is visibly *reasoning* rather than scoring — 203
  consistent candidates and a refusal to guess, the collapse to 18, and the
  turn-3 override erasing the `feature` slot while both `material` slots
  survive. Re-verified against live output tonight before writing the narration.
- **Shot 5** is the held-out 0.9189 and the `LIKELY LUCK` rows from
  `stability.txt`. Almost every submission will show a score; very few will show
  the number they think is actually true and the three tunables that did not
  survive scrutiny.

The evaluator shot is marked **speed-ramp, do not cut away** — 34.7 s of real
wait compressed in the edit rather than hidden behind a jump cut, because the
unbroken take is the evidence.

**Also written:** a 90-second cut-down, an explicit cut-order for overruns, and
an upload checklist (the deliverable says *public*, not unlisted, which is an
easy way to fail a requirement while believing it is met).

**Housekeeping:** `demo_capture/` added to `.gitignore` — the prep step writes
three files there and they are scratch.

**Verified after:** 102 tests pass; `tools.verify_claims` ran green this
iteration (378 s, rc=0, 20/20) during the timing measurements and no code has
changed since. `evaluator/` and `data/` untouched.

**Result: adopted.** Queue item (3) of 12 complete — all three hard deliverables
now drafted. Next is the staleness sweep, which now has seven known entries.

---

## Iteration 15 — the staleness sweep, and making it the last one

**Chosen because** this project's headline claim is that every number in it is
measured. Six figures were stale simultaneously, which does more damage here
than in a repo that never made the claim.

**Fixed, nine sites:**

| where | was | now |
|---|---|---|
| `SCOREBOARD.md` per-scenario table | intent_override MRR 0.8909 | 0.9075 |
| `SCOREBOARD.md` headline | MRR 0.9438, 180 at rank 1, 20 costing 0.0169 | 0.9465, 183, 17 costing 0.0160 |
| `SCOREBOARD.md` ceiling section | "rank 1 in 157 of 200" | 183, with the stage marked |
| `AGENTS.md` / `CLAUDE.md` "Current main" | MRR 0.9438 · score 0.9522 | 0.9465 · 0.953064, plus the held-out 0.9189 |
| `README.md` pillar IV row | MRR 0.9438 · MTTC 2.55 | 0.9465 · 2.545 |
| `README.md` disclosures | "until four constraints are disclosed" | three — `MIN_DISCLOSED` moved 4→3 on 29 Aug |
| `README.md` disclosures | "expect the hidden set nearer 0.78 than 0.81" | expect 0.9189, per `holdout_synth` |
| `README.md` repo map | 80 tests | 114 |
| `TASKS.md` | score 0.8629 / MRR 0.6406, ~14 merges behind | rewritten against current `main` |

`OVERNIGHT_LOG.md`'s own historical entries were **not** touched. A dated log
records what was measured at the time; editing it would be falsifying it.

**The durable part: `verify_claims.py` now scans the docs.**

Every existing check re-runs a measurement. None of them could notice a doc
quoting a number nobody had registered — which is exactly how six figures went
stale at once. The new scan asserts 14 current-state claims against the live
run and flags superseded literals presented as current. `--no-docs` skips it.

**The scanner shipped broken, and the only reason I know is that I tried to
break it.** After it came up green I injected two stale figures into `TASKS.md`
to prove it could fail. It caught `score 0.9522` and **missed `MRR **0.9438**`**
— it was matching against the raw markdown line, and the emphasis asterisks
between "MRR" and the number defeated the substring test. Had I trusted the
green run, the sweep would have shipped with a drift check that silently ignored
every bolded figure in the repo, which is most of them.

Fixed by stripping `*` and `` ` `` before matching. That is now pinned by
`tests/test_verify_docs.py`, which parametrises five emphasis styles, and the
matcher was extracted to a module-level `superseded_hits()` so it is testable at
all rather than buried in `main()`. Twelve new tests, 102 → 114.

**A check that cannot fail is worse than no check**, because it gets quoted as
evidence. This one has now demonstrably failed once, on purpose.

**Second-order effect worth noting:** adding those 12 tests changed the live
test count, and the new scanner immediately failed the run by flagging four docs
still saying "102 tests". It caught a drift I had created thirty seconds
earlier. That is the tool working.

**Also corrected:** `verify_claims --slow` still asserted "peak memory (docs say
~735 MB)" — a figure the docs themselves now describe as wrong twice over. It
compared `tracemalloc` output against an RSS number measured a different way, so
it was never really checking the documented claim. Relabelled as the loose
sanity bound it actually is.

**Verified after:** 114 tests pass, **21** documented claims re-verify (the doc
scan is now one of them), clean 0.953064 / Hit@10 1.0000, `evaluator/` and
`data/` untouched.

**Result: adopted.** Queue item (4) of 12 complete; all four bounded deliverables
are done.

---

## Iteration 16 — transparent recommendation explanations, and a test bug worse than the feature

**Chosen because** `docs/competition_specification.md` lists "transparent
recommendation explanations" as an Innovation Direction and we had not built it.
`_message()` returned the same sentence for every result set. Innovation &
Problem Insight is 20% of the grade against Technical Execution's 35%, and this
was the cheapest unbuilt item on that list.

**Built.** `rank()` now records `state.disclosed_values`, and a new
`ranking.evidence_for()` answers, for one product, *which disclosed constraints
its own intent card actually contains*. `agent._explanation()` turns that into a
sentence:

> "Here are the closest matches so far. The first one matches everything you've
> mentioned: buckle closure, leather, 100% leather. Tell me a bit more about
> what matters to you."

**The design constraint that mattered.** The explanation is built from the same
`catalog.card` slots the ranker scored on — not from a second parse of the
dialog. An explanation that can disagree with the ranking is worse than none,
because it invites a judge to trust a story the system did not follow. Exact
tier only: the fuzzy and partial tiers exist to keep the *ordering* sane when
extraction has failed, and neither is something we can honestly phrase as "this
matches what you asked for". Where there is no card evidence the agent says
nothing rather than inventing a reason — pinned by a test.

**Score unchanged: 0.953064, Hit@10 1.0000.** As predicted — the simulator reads
`ask_attribute`, not prose — but predicted is not verified, so it was measured.

**Two bugs, both found by tests, both mine.**

1. **The ASCII switch broke the length budget.** The truncation was
   `text[:CAP-1] + ellipsis`, correct while the ellipsis was one `\u2026`
   character. I switched the copy to ASCII to avoid cp1252 mojibake on a
   Windows console — `context_demo` already renders em-dashes as `?` here — and
   the 3-character `...` silently pushed output to 46 against a 44 cap. Fixed to
   `CAP-3` so the *result* honours the cap rather than the slice.

2. **A latent hazard in the suite, which my tests were the first to trip.**
   `test_agent_contract.py` evicts every `starter.*` module from `sys.modules`
   to force a fresh import under an import guard, and its `finally` evicted them
   again without restoring the originals. So the next `import starter.agent`
   built a **new module object**, while any test module that had already bound
   `from starter.agent import _explanation` kept the old one. Patching
   `"starter.agent.evidence_for"` then patched a module the function no longer
   belonged to.

   Symptom: `tests/test_explain.py` passed 18/18 in isolation and failed 5 in
   the suite. **That is the worst shape a test bug can take** — it looks like a
   flaky feature and it is actually an ordering dependency. Fixed at the source
   by saving and restoring the original modules, which makes the suite hermetic
   for every future test, not just these.

**Also fixed:** `tools/demo_transcripts.py` truncated the agent message at 90
characters, which cut the new explanation off mid-word (`"...mentioned: al"`) —
hiding the one part of the message a reader is meant to notice. The message is
bounded by construction (three constraints at 44 characters), so it is now
quoted whole. Transcripts regenerated.

**Verified after:** 132 tests pass (18 new), 21 documented claims re-verify,
clean 0.953064 / Hit@10 1.0000, `evaluator/` and `data/` untouched.

**Result: adopted.** Queue item (5) of 12 complete.

---

## Iteration 17 — question-value estimation, and a claim of ours that was too strong

**Chosen because** `docs/competition_specification.md` names "adaptive
clarification and question-value estimation" as an Innovation Direction, and
this repo dismissed it in two places as **"not implementable"**. That is a
stronger claim than we had earned, and it is the kind a judge can check.

**Built.** `starter/question.py` is a real expected-posterior-size estimator,
not a heuristic with the name attached. `customer_reply` is deterministic --
first two undisclosed card slots matching the asked attribute -- and `simcard`
reconstructs any product's card, so for the consistent set C we can partition by
the reply each member *would* give and compute

    E[|C'| | a] = sum over groups g of (|g|/|C|) * |g|

exactly rather than by sampling. Value of asking `a` is `|C| - E[|C'| | a]`. The
"no preference for that" reply falls out for free as its own group, which is
right: absence is informative.

**Measured, and it loses.**

| | |
|---|---|
| `"other"` is the argmax, at the runtime's 400-candidate cap | **1000/1000 turns** |
| `"other"` is the argmax, uncapped | 990/1000 (99.0%) |
| full evaluator, `TJ_QVALUE=1` | **0.952214 vs 0.953064 — costs 0.00085** |

**The measurement nearly misled me, twice.**

First run, capped, on 20 sessions: 97% agreement with three `feature` wins.
Full run capped: **100%**, zero wins. The cap was doing the work -- and
`consistent[:400]` is the first 400 in catalog order, a *biased* slice, not a
random sample. Reporting only the capped number would have overstated how
settled this is, so `--uncapped` now measures the idealised estimator too, and
both are published.

Second: the ten uncapped wins are **one information state, not ten findings**.
Every one is turn 1 with a consistent set of exactly 7017 and a gain of exactly
62.424 -- ten sessions sharing an opening constraint, so the estimator sees an
identical problem ten times. Counting them as ten independent results would
have inflated a 0.9%-of-set effect at the one turn where the agent holds its
answer back anyway.

**Why enabling it still costs 0.00085 when the argmax agrees everywhere.** At
runtime `consistent_slots` is the previous turn's *pooled* consistent set -- a
smaller, differently ordered sample than the tool's catalog-wide one -- and the
divergence bites once `"other"` is exhausted, where the shipped `PROBE_ORDER`
and the estimator's ranking disagree. The estimator chooses well on a sample;
the fixed order happens to choose slightly better on the full problem.

**Corrected in two places.** `SCOREBOARD.md`'s rejected table said "not
implementable"; it now says "built and measured: -0.00085" with the numbers, and
`NOTES_ranking.md` carries a dated correction. *Not worth doing* is not *not
implementable*, and against a spec that names this as an Innovation Direction
the difference is the difference between a measured negative and an unexamined
assertion.

Fourth capability shipped disabled with a number, after the LLM re-ranker, the
dense leg and the global popularity prior.

**Verified after:** 162 tests pass (30 new, including a check that the copied
`classify_constraint` still matches the evaluator's on 15 inputs), 21 documented
claims re-verify, clean **0.953064 / Hit@10 1.0000** with the gate off,
`evaluator/` and `data/` untouched.

The drift scanner earned its keep again: adding 30 tests immediately failed the
run over `README.md` and `REPORT.md` still saying 132.

**Result: adopted, shipped disabled.** Queue item (6) of 12 complete.

---

## Iteration 18 — the EXTRACT class: the planned fix was refuted, a different one adopted

**Chosen because** it is the largest remaining opportunity: held-out sits 0.034
below public, and a third of held-out failures are defects rather than ties.

**The plan was a catalog-mined synonym lexicon. The diagnosis killed it.**

Before building anything I checked two things.

First, the repo already contains the "third tier that fires only when both card
tiers are empty" — `BONUS_CARD_PARTIAL`, in the `elif hits:` branch, tested and
rejected on held-out with a monotone decline. Building it again would have been
re-running a disproved experiment.

Second, `tools/extract_probe.py` (new) sizes the lexicon opportunity before
paying for it. Over **800 unseen sessions**:

| verdict | constraints | meaning |
|---|---|---|
| MATCHES | 47 | not the culprit |
| FUZZY | 56 | shipped fuzzy tier already covers it |
| **VOCAB** | **0** | **a lexicon would fix it** |
| ABSENT | 2 | genuine mis-extraction |

**Zero VOCAB.** Not few — none. And in hindsight it follows from the premise the
whole submission rests on: the shopper's constraints are verbatim strings from
the target's own metadata, so shopper and product *cannot* use different words
for the same thing. Both 7a (catalog-mined lexicon) and 7b (pruned GloVe /
WordNet) targeted a class with no members. The probe cost an hour and saved a
day, and it is the second time tonight measuring first has changed the plan.

**Building the probe took three wrong turns, all mine, all silent failures.**

1. Filtered on `session["rank"]`; the field is `best_rank`. The filter never
   fired, so every session was examined and the tool reported a clean zero.
2. Looked up agent state by `sample_id`. The evaluator mints a **random**
   `session_id`, so `agent._states` had none of them — instrumenting revealed
   state found for **0 of 82** failing sessions while the headline still said
   "no defects found". Fixed by replaying each session with a session id we own.
3. Left a dead `worst = min(...)` immediately overwritten by `max(...)`.

Every one of those produced a *plausible* number. A diagnostic that fails
loudly is worth more than one that quietly reports zero — the same lesson this
project already learned about the truncating extractor, relearned in the tool
built to look for it.

**What the failure actually is.** The examples showed it at once:

```
agent extracted : "solid colors: 100% cotton"
                  "heather grey: 90% cotton, 10% polyester"
target's slot   : "solid colors: 100% cotton; heather grey: 90% cotton, 10% ..."
```

`_disclosed_constraints` splits the reply on `";"` — correct, `customer_reply`
joins constraints that way — but `card_slots` can emit **one slot with `"; "`
inside it**, and the same split shatters it into pieces matching nothing.

**Adopted: component matching.** A disclosed constraint may equal a whole
`"; "`-delimited component of a slot. It reverses exactly the split the agent
performed and nothing looser.

| | held-out mean | s1 | s2 | s3 | s4 | non-rank-1 | defects |
|---|---|---|---|---|---|---|---|
| before | 0.918948 | .9093 | .9225 | .9275 | .9165 | 148 | 50 |
| **after** | **0.921214** | .9110 | .9247 | .9284 | .9207 | **140** | **42** |

**Up on four draws of four. Public score bit-identical at 0.953064 / Hit@10
1.0000** — which is precisely why nobody found this: the failure barely exists
on the set we tuned on. Robustness gate passed, worst level down 0.0024 against
a 0.01 limit, and the two weakest cases both *improved* (truncate 0.8553 →
0.8588, paraphrase 0.8906 → 0.8932).

**This contradicts one of our own rejected rows, and the correction matters.**
`SCOREBOARD` had "semicolon-tolerant card matching" as tested and rejected twice
— containment (0.9090) and substring tolerance (0.9096). Both deserved
rejection: they manufacture false positives. Component *equality* is a third
form that was never tried, and the family was written off after two of three.
Both earlier tests also ran on the **public** set, where the fix is worth
literally zero digits.

Renamed `CARD_COMPONENT_MATCH` (a flag, not a bonus — 0.1 and 0.04 scored
identically because the value was never read as a weight).

**Verified after:** 167 tests pass (5 new), 21 documented claims re-verify,
public 0.953064 / Hit@10 1.0000 unchanged, `evaluator/` and `data/` untouched.
Held-out figures refreshed across seven documents.

**Result: adopted, default ON.** First change in this project adopted purely on
held-out evidence. Queue item (7) complete; (8) is folded in above.

---

## Iteration 19 — the HOLD_UNTIL_TURN gate ran, and refused

**Chosen because** it was the one measured lead this project had left open, with
an explicit gate written out in `SCOREBOARD.md` and never run. It was also worth
re-measuring rather than reusing the old sweep: component matching landed this
morning, and the docs' own coupling note says to re-check this parameter
whenever ranking moves materially.

**Everything except the gate said adopt.**

| | hold=2 | hold=3 |
|---|---|---|
| public | 0.953064 | **0.953900**, Hit@10 1.0000 |
| held out, 4 draws | 0.921214 | **0.924957** (+0.0037) |
| held-out non-rank-1 | 140 / 800 | **120** |
| held-out defects | 42 | **26** |

Up on three of four held-out draws, sixteen fewer defects, public up as well.
Held-out evidence over four draws is the strongest signal this project collects,
and last iteration I adopted a change on a *smaller* one (+0.0023).

**The gate refused, and not narrowly.** `robustness --seeds 3`:

| level | hold=2 | hold=3 | delta | worst Hit@10 |
|---|---|---|---|---|
| **casing / punctuation** | 0.930232 | **0.850407** | **−0.0798** | **0.8900** |
| **truncated** | 0.858798 | **0.795236** | **−0.0636** | **0.8550** |
| interject | 0.919009 | 0.915575 | −0.0034 | 0.9900 |
| (others) | | | +0.0008 to +0.0031 | ≥0.9800 |

The allowance is 0.01. Two levels miss by **8x** and **6x**, and the *mildest*
perturbation in the suite — casing and punctuation drift — takes Hit@10 from
1.0000 to **0.8900**, with a 0.064 spread across three seeds. Not merely worse:
unstable.

Split-half fails too: **−0.0004 / +0.0021** on the even/odd split the gate
names, and 49% both-positive over 200 random splits — a coin flip, statistically
indistinguishable from the `hold-back 3 vs 4` row at 52%.

**One of three conditions passed. Not adopted; `HOLD_UNTIL_TURN` stays at 2.**

**The mechanism, which makes it obvious afterwards.** `HOLD_UNTIL_TURN` is a
*budget*. At 2 the agent always answers from turn 3; at 3, from turn 4 — one
more of ten turns spent before it can score. On verbatim wording that turn is
free and the extra disclosure is pure gain. Under perturbed wording extraction
sometimes needs another round-trip, and the session no longer has slack for
both. The gain and the exposure are the same turn.

**The lesson is about the evidence, not the parameter.** Held-out draws vary the
*target*; every one of them still uses verbatim simulator wording. They cannot
see a robustness cliff. A held-out set is not a substitute for an adversarial
one — this change passes one and fails the other, and only running both revealed
which. I would have adopted this on held-out evidence alone, and I would have
been wrong.

Worth noting the gate was written by someone who suspected precisely this and
wrote down the check rather than the conclusion. It sat unrun for two days.

**Verified after:** `main` confirmed still at `HOLD_UNTIL_TURN=2` and scoring
0.953064 / Hit@10 1.0000, 167 tests pass, 21 documented claims re-verify.
Documentation only — no code changed this iteration, which is the correct
outcome.

**Result: rejected, recorded.** Queue item (9) complete.

---

## Iteration 20 — the two inert bonuses, decided on held-out

**Chosen because** `stability.py` flagged both as candidates for removal weeks
ago (0% both-halves) and explicitly deferred the call to a human, on the grounds
that they might matter on the hidden 800. Held-out draws are the closest proxy
we have, and nobody had run it.

**A false start worth recording.** I launched three parallel held-out runs with
`TJ_B_EXACT_PHRASE=0` and `TJ_B_EXACT_CATEGORY=0` — env var names I inferred
from the constant names. The real gates are `TJ_B_EXACT` and `TJ_B_EXACT_CAT`.
An unknown env var is silently ignored, so all three runs would have completed
normally and reported the **default configuration** as if it were three
experiments. I only caught it because a `grep` for the names I had just used
returned nothing.

That is the third silent failure tonight, and the same shape each time: the run
succeeds, the number is plausible, and nothing indicates the experiment did not
happen. Killed and re-run against the real names.

**The measurement.** Four seeds each, current pipeline (component matching on).

| config | public | held-out | vs shipped | held-out Hit@10 by seed |
|---|---|---|---|---|
| **shipped** | 0.953064 | **0.921214** | — | .985/.985/.985/.980 |
| phrase = 0 | 0.953064 | 0.921295 | +0.00008 | .985/.985/.985/.980 |
| category = 0 | **0.953214** | 0.920985 | −0.00023 | .985/.985/.985/**.975** |
| both = 0 | 0.953014 | 0.921086 | −0.00013 | .985/.985/.985/**.975** |

**Decision: keep both.** The rule was "do not remove unless held-out clearly
improves". The entire spread is ±0.00023 — an order of magnitude under this
project's own +0.002 noise floor. Nothing improves, clearly or otherwise.

**The category bonus is not inert, and the public set said it was.** Removing it
scores *higher* on public — 0.953214 against 0.953064 — which is exactly the
reading that made it look like dead weight. On held-out it is lower, and it
**costs a hit on seed 4** (Hit@10 0.980 → 0.975, reproduced in the both-zero
row). Hit@10 carries 0.50 weight. A term that buys a hit on unseen targets is
not dead weight however the public set scores it.

The phrase bonus really is inert: identical to six decimals on public, +0.00008
held out. It does nothing and costs nothing, which is not a strong enough reason
to touch working code three days before a deadline.

**Second time tonight the public set pointed the wrong way**, after component
matching (invisible on public, +0.0023 held out). Stated plainly in SCOREBOARD:
on any question worth ±0.002 the public 200 is not merely uninformative, it is
occasionally misleading.

**Verified after:** `main` unchanged at 0.953064 / Hit@10 1.0000, 167 tests
pass, 21 claims re-verify. Documentation only — no code changed, which is again
the correct outcome.

**Result: both kept, recorded, and the stability table's open question closed.**
Queue item (10) complete.

---

## Iteration 21 — the architecture diagram

**Chosen because** it was the last unbuilt item on the task board before the
final pass — `TASKS.md` has carried "a designed version for Devpost is still
worth doing" since 29 Aug — and it is the only asset a judge sees before reading
a single word.

**Built:** `docs/architecture.svg`, hand-written, no dependencies, plus
`docs/architecture.png` (1200x780, 124 KB) rendered from it. Devpost's uploader
takes raster formats, so the PNG is the deliverable and the SVG is the source;
the regeneration command is recorded in `DEVPOST.md` so the numbers cannot drift
away from a file nobody can rebuild.

**What it shows, and what it deliberately does not.** Four panels: the per-turn
pipeline, the invertible-simulator collapse (2,574 -> 78 -> 1), the three
decisions carrying +0.111 of the +0.115 margin, and the four capabilities built
and shipped disabled with their costs. The header carries both scores side by
side, and a dark strip along the bottom says **read the held-out number first**.

The temptation was to make it a picture of the pipeline. A pipeline diagram
shows that we built a system; it does not show that we understood the problem,
and Innovation & Problem Insight plus Impact are 40% between them against
Technical Execution's 35%. So the pipeline is one column on the left and the
*reasoning* takes the other two thirds.

**Verified by looking at it, not by trusting the markup.** Rendered in the
browser pane and inspected before converting, then the PNG re-opened and read.
Both are correct including the footer, which the pane had cropped — an SVG that
compiles is not an SVG that renders.

Linked from `README.md`, `REPORT.md` and `DEVPOST.md`, and `DEMO_SCRIPT.md`
shot 2 now names it as the on-screen asset instead of describing a title card
that did not exist.

**Verified after:** 167 tests pass, 21 documented claims re-verify, public
0.953064 / Hit@10 1.0000, `evaluator/` and `data/` untouched. Assets and docs
only.

**Result: adopted.** Queue item (11) complete. Only the final pass remains.

---

## Iteration 22 — final pass, and a correction to my own reporting

**Chosen because** it is the last queue item: fold everything from (5)-(10) into
the two documents a judge reads, then stop.

**Folded in.** `REPORT.md` §3 now carries component matching as a fourth
load-bearing decision and the self-explaining messages; §4 lists the
question-value estimator as a third measured-and-disabled capability with its
mechanism; §6 leads its defect discussion with the probe's zero-VOCAB result;
§9 marks two of its four "next steps" as closed and adds the `HOLD_UNTIL_TURN`
refusal as the thing we would explicitly *not* do. `DEVPOST.md` gains the two
Innovation Directions in the pillar table, "four capabilities disabled" instead
of three, the diagnosis-deleted-the-plan story, the gate refusal, and a
learnings paragraph on the public set pointing the wrong way twice in one night.

**A correction I owe the record.** Item (8) asked for `robustness --seeds 5`
after the component change. In iteration 18 I ran **three** seeds, and reported
that truncation improved 0.8553 -> 0.8588 and paraphrase 0.8906 -> 0.8932. The
five-seed run says otherwise:

| level | 5 seeds, before | 5 seeds, after |
|---|---|---|
| truncated | 0.8553 | **0.8571** (+0.0018) |
| light paraphrase | 0.8906 | **0.8906** (0.0000) |
| casing | 0.9304 | 0.9304 |
| adversarial | 0.8897 | 0.8899 |

**Both "improvements" were seed noise.** The honest statement is that component
matching is **robustness-neutral** — it buys held-out accuracy without spending
any of the paraphrase margin, which is a perfectly good result and is not the
one I reported. Three seeds against spreads of 0.02 was never enough to claim a
0.003 movement, and I made the same mistake this project already documented when
it caught itself quoting single-seed robustness figures as measurements.

Docs corrected to the five-seed numbers throughout.

**Final state of `main`:**

| | |
|---|---|
| public | **0.953064** · Hit@10 **1.0000** · MRR 0.946548 · MTTC 2.545 |
| held out, 4 draws | **0.921214** (was 0.918948 at the start of the night) |
| tests | **167** |
| documented claims re-verified | **21**, including a documentation-drift scan |
| `evaluator/` and `data/` | untouched |

**Twelve queue items, eleven iterations, three adopted changes, four recorded
refusals.** The refusals are the part worth keeping: a synonym lexicon deleted
by diagnosis before it was built, a hold-back change that passed held-out and
failed adversarial, two bonus terms that measured inert on public and turned out
to buy a hit on unseen targets, and a question-value estimator that was correct
and still lost.

**Result: complete.** The loop stops here.
