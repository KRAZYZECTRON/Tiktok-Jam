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
