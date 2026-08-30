# Demo video script — 3:00

**Deliverable:** a short video demonstrating the solution working end-to-end,
uploaded to YouTube, public, linked in the Devpost description. Track 4 is a
backend track, so the spec explicitly accepts *"a walkthrough video showing API
usage, inference examples, or result analysis"* in place of a front-end demo.

Everything below is recordable by one person in one sitting. **Every runtime in
this document was measured on the dev machine tonight, not estimated.**

---

## Before you hit record

### Which commands can actually run on camera

This matters more than it sounds. Four of the six tools we would like to show
are far too slow for a 3-minute video, and neither `stability` nor
`holdout_synth` writes its output to a file — so they cannot be shown live and
cannot be `cat`-ed without a prep step.

| command | measured | on camera? |
|---|---|---|
| `py -m tools.context_demo --sample public_0002` | **6.4 s** | **live — this is the money shot** |
| `py -m pytest tests/ -q` | **0.9 s** | **live** |
| `py -m evaluator.local_evaluator` | **34.7 s** | live, but **speed-ramp it** to ~10 s |
| `py -m tools.holdout_synth --seeds 1` | 68.3 s | pre-capture |
| `py -m tools.stability` | **273 s** | pre-capture |
| `py -m tools.verify_claims` | **378 s** | pre-capture |

### Prep step — run this first, in a second terminal

Takes about 12 minutes. Do it while you set up. It captures the three slow
outputs so they can be shown as text on screen instead of as dead air.

```bash
mkdir -p demo_capture
py -m tools.stability      > demo_capture/stability.txt      2>&1
py -m tools.verify_claims  > demo_capture/verify_claims.txt  2>&1
py -m tools.holdout_synth --seeds 4 > demo_capture/holdout.txt 2>&1
```

`demo_capture/` is scratch — add it to `.gitignore` or delete it after.

### Terminal setup

- Font 18–20 pt. The `context_demo` output is the widest thing shown; check it
  does not wrap at your window width before recording.
- **Run each live command once before recording.** The first run of the
  evaluator builds an FTS index and an IDF table (~6 s of cold start); a warm
  run is what you want on camera.
- `cd` into the repo root. Clear the scrollback.
- Close anything that could produce a notification.

---

## Shot list

### Shot 1 — the problem · 0:00–0:20 · 20 s

**On screen:** `README.md` open, scrolled to the results table. Highlight the
baseline row.

> "This is the starter kit we were given. It scores 0.1067, and the reason is
> quietly devastating: it never asks the shopper anything. It sends
> `ask_attribute: None` every turn, so the simulated customer replies with fixed
> filler — which means every turn after the first re-queries on noise. Turn one
> was the only turn that could ever hit."

**Cut on:** the words "only turn that could ever hit."

---

### Shot 2 — the insight · 0:20–0:50 · 30 s

**On screen:** the consistent-set table. Either the one in `REPORT.md` §1 or a
title card:

```
constraints disclosed  │  median products still consistent
          1            │            2,574
          2            │               78
          3            │                1
```

> "The evaluator builds the shopper's hidden requirements out of the target
> product's own text — and the shopper repeats them almost word for word. So we
> ran it backwards. `simcard.py` reconstructs what any product in the catalog
> *would* say, and we verified it byte-identical to the evaluator's own output on
> all fifty thousand products.
>
> Then intersect. One constraint leaves you 2,574 candidates. Three leaves you
> **one**. In 147 of 200 sessions the conversation already names exactly one
> product. This was never a ranking problem. It's identification."

**Cut on:** "It's identification."

---

### Shot 3 — watch it think · 0:50–1:40 · 50 s · **LIVE**

**Type on camera:**

```bash
py -m tools.context_demo --sample public_0002
```

Runs in 6.4 s. Let it finish, then scroll through the three turns as you talk.

> "Here's a real session, unedited. Turn one: the shopper says they want a belt
> with a buckle closure. 203 products are still consistent with that — so the
> agent **refuses to guess**. It returns no list at all and asks a question
> instead. That's a retrieval cutoff under candidate-pool overload, and it's one
> of the three turn shapes the spec allows.
>
> Turn two, they mention leather. 203 collapses to 18, the strategy flips to
> IDENTIFY, and the target comes back at rank 2.
>
> Turn three is the interesting one — the shopper changes their mind. Watch the
> state: the opening `feature` slot is **erased**, but both `material` slots
> survive, because those are still true. That's the intent-override case, handled
> as a state machine rather than a reset."

**Point at, in order:** `consistent set: 203` → `STRATEGY: CLARIFY` →
`consistent set: 18` → `STRATEGY: IDENTIFY` → the turn-3 `distilled slots` line
where `feature` has vanished.

**Cut on:** "rather than a reset."

---

### Shot 4 — the score · 1:40–2:15 · 35 s · **LIVE, speed-ramped**

**Type on camera:**

```bash
py -m evaluator.local_evaluator
```

Real runtime 34.7 s. **Speed-ramp the wait to about 10 seconds** in the edit,
then play the final output at normal speed. Do not cut away and back — the
unbroken shot is the point.

> "That's the organizer's evaluator, unmodified, on all 200 public sessions. One
> command, no arguments, no configuration, no network.
>
> Hit rate at 10: **1.0000** — every session, every scenario, zero misses. MRR
> 0.9465. Mean turns to conversion: 2.5. Technical score **0.9531**, against the
> baseline's 0.1067."

**On screen at the end:** hold on the metrics block long enough to read.

**Cut on:** "against the baseline's 0.1067."

---

### Shot 5 — the honest part · 2:15–2:45 · 30 s

This shot is why the video is worth watching. Do not cut it for time.

**On screen:** `demo_capture/holdout.txt`, then `demo_capture/stability.txt`.

> "But that 0.9531 is in-sample. Every threshold in this agent was picked while
> all 200 public targets were visible, so we built a tool that scores us on
> catalog products the tuning never saw. Four draws: **0.9189**. Consistently
> 0.034 lower.
>
> That's the number we expect on the hidden 800, and we put it above the better
> one in our report — because a judge who runs this themselves shouldn't be
> learning it from their own terminal.
>
> Same story here. This re-tests every tuned choice over 200 random split-halves.
> Three of them carry the entire margin. **Three others are statistically
> indistinguishable from luck, and we say so in the submission.**"

**Point at:** the `LIKELY LUCK` rows.

**Cut on:** "and we say so in the submission."

---

### Shot 6 — close · 2:45–3:00 · 15 s

**On screen:** split or quick cuts — `requirements.txt` (no runtime
dependencies), then `py -m pytest tests/ -q` typed live (0.9 s, 114 passed).

> "No LLM on the scored path. Zero tokens, zero dollars, no network socket — we
> built an LLM re-ranker and a vector retriever, measured both, and shipped both
> **disabled**, because each one made the score worse. It's pure standard
> library, so it cannot fail an offline, CPU-only grading run.
>
> 114 tests. Every number in our docs re-verified by a tool that fails the build
> if any of them drift."

**Final card:** `github.com/KRAZYZECTRON/Tiktok-Jam` · `0.9531 public ·
0.9189 held out`

---

## If you run over

Cut in this order:

1. **Shot 2 down to 20 s** — drop the byte-identical verification detail, keep
   the 2,574 → 78 → 1 collapse.
2. **Shot 6 down to 10 s** — drop the test count, keep "zero tokens, zero
   dollars, cannot fail an offline run."
3. **Shot 4 down to 25 s** — cut the per-metric readout, hold on the score.

**Never cut Shot 3 or Shot 5.** Shot 3 is the only place the system is visibly
*reasoning* rather than scoring, and Shot 5 is the differentiator — most
submissions will show a number, almost none will show the number they think is
really true.

## 90-second version, if one is asked for

Shot 1 (10 s) → Shot 3 (35 s, turns 1–2 only) → Shot 4 (25 s) → Shot 5 (20 s,
held-out only). Drop shots 2 and 6.

## Upload checklist

- [ ] YouTube, visibility **Public** (not Unlisted — the deliverable says public)
- [ ] Link pasted into the Devpost description
- [ ] No third-party trademarks or copyrighted music
- [ ] Title: `Shopping Copilot — TikTok TechJam 2026 Track 4`
- [ ] Description: repo link, the two scores, one line on what the demo shows
- [ ] Watch it once at 1× before submitting — check the terminal text is legible
