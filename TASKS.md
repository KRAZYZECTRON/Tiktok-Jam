# TASKS

`main` — Hit@10 **1.0000** · MRR **0.9465** · MTTC **2.545** · **score 0.953064**
(kit baseline was 0.1067). Held out on targets never tuned on: **0.9212**.

**Treat 0.9212 as the expectation for the hidden 800 and 0.953064 as the
ceiling.** Full history, every intermediate measurement, and the retired claims
are in `SCOREBOARD.md`.

| Task | Owner(s) | Branch | Status |
|------|----------|--------|--------|
| Ranking | Vishwak | main | ✅ merged — stage A, RRF fusion, post-fusion identification layer |
| Dialog | Zou Yuyang + Bhao Tanush | merged | ✅ merged — accumulated query, `ask_attribute`, override erasure, rotation |
| Retrieval | Chetan | merged | ✅ intent routing merged and active; dense leg merged but **shipped off** |

## Submission deliverables

| | Status |
|---|---|
| Public GitHub repository | ⚠️ **repo must be set to public before submitting** |
| `README.md` — setup, Python version, one run command, disclosures | ✅ |
| `REPORT.md` — the required standalone report | ✅ |
| `DEVPOST.md` — Devpost description text | ✅ drafted, needs pasting into Devpost |
| `DEMO_SCRIPT.md` — shot list for the video | ✅ drafted |
| **Demo video recorded and uploaded** | ❌ **human required** — YouTube, **public**, linked on Devpost |
| Latency / token / cost disclosure | ✅ `tools/perf.py` |
| Architecture diagram | ✅ ASCII in `README.md` and `REPORT.md`; designed SVG for Devpost still open |
| Devpost + Registration Form both submitted | ❌ **human required** |

## Where the remaining score actually is

Hit@10 is **1.0000 and cannot improve**, and the public 200 are saturated — every
tunable was chosen with all 200 targets visible, so public gains are close to
meaningless now. **Judge everything on `tools/holdout_synth.py`.**

Ranked by measured value:

| opportunity | size | note |
|---|---|---|
| Paraphrase / truncation robustness | **0.063 at risk** | Truncated input scores 0.8553, paraphrase 0.8906. The spec says paraphrasing *may* be added. Insurance, not expected gain. |
| The **EXTRACT** failure class | ~**+0.014** held-out | 50 of 148 unseen non-rank-1 sessions had a card that uniquely identifies the target. Defects, not ties. Both card tiers are conjunctive, so one mis-extraction empties the set. |
| `HOLD_UNTIL_TURN` 2 → 3 | +0.0028 held-out | Measured, **not adopted** — the Hit@10 confirmation never finished. Gate is specified in `SCOREBOARD.md`. |
| Retire the two inert bonus terms | ~0 | `BONUS_EXACT_PHRASE` and `BONUS_EXACT_CATEGORY` are inert on public (0% of splits). Untested on held-out. |

Two Innovation Directions named in the spec are **unbuilt**: question-value
estimation, and transparent recommendation explanations. Neither moves the
score; both are scored under Innovation & Problem Insight (20%).

**Read the rejected table in `SCOREBOARD.md` before trying anything.** Fourteen
plausible ideas are already disproved there with numbers, including several that
sound obviously right.

## Retrieval: resolved

Chetan's hybrid branch is merged. The Buying/Browsing routing it brings is
active and part of the shipped path. The **dense leg is opt-in (`TJ_DENSE=1`)
and stays off**: 0.9254 against 0.9522 when measured, it surrenders a maxed
Hit@10, and it costs 21.8 s of model load plus 774.6 s to embed 50k products on
CPU.

The mechanism is specific and checkable: the shopper's constraints are verbatim
strings from the target's own `features` field, so there is no paraphrase gap
for embeddings to close, and their semantic neighbours displace exact matches.
`tools/attribution.py` independently confirms `MISS_RETRIEVAL = 0` — the BM25
pool contains the target in all 200 sessions, so there is no retrieval failure
left for a dense leg to fix.

**This is a result, not a wasted seat**, and it is in the writeup as one.

## Standing rules

- `evaluator/` and `data/` are **read-only**.
- Never two people on one file at once.
- Only Seat 1 merges to `main`, and never without a green full-200 run.
- Every merge appends a row to `SCOREBOARD.md`.
- `main` is **pure stdlib** — no third-party import on the scored path, no
  socket. Official scoring may run offline, CPU-only, under a timeout. Anything
  that changes that must justify itself against this constraint.
- Before any commit: `py -m pytest tests/ -q` and `py -m tools.verify_claims`
  must both be green.
