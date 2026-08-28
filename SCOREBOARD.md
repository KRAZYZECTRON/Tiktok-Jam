# Scoreboard

Every merge into `main` appends a row here. Full 200-session public set via
`py -m evaluator.local_evaluator` — subset runs never go in this table.

Score = 0.50·Hit@10 + 0.30·MRR + 0.20·efficiency, efficiency = (11 − MTTC)/10.

| date | what changed | Hit@10 | MRR | MTTC | score |
|------|--------------|--------|-----|------|-------|
| 27 Aug | BM25 keyword baseline (kit as shipped) | 0.1250 | 0.0680 | 9.81 | 0.1067 |
| 28 Aug | wide pool (500) + state-aware stage-A rerank | 0.2050 | 0.1045 | 9.08 | **0.1722** |
| 28 Aug | + stage-B LLM blend (`RANK_USE_LLM=1`, *not* default) | 0.2300 | 0.1099 | 8.83 | 0.1914 |

**The row in bold is what `main` scores as committed.** Stage B is off by
default and the reason is in the next section — do not quote 0.1914 as our
number without the caveat attached.

## Why stage B is off by default — read before betting on an LLM

`docs/submission_rules.md` and `docs/competition_specification.md`, read after
stage B was already working:

> For official final scoring, organizer policy may disable network access.

> The organizer reserves the right to run your submission under CPU, memory,
> timeout, and network restrictions.

and, under disallowed submission contents:

> code that depends on undeclared external services for official final scoring

Stage B talks to Ollama on `localhost:11434`. In the organizer's scoring
environment that service will not exist, so the +0.019 measured here is very
likely **not** in our official score. Two consequences for the whole team:

1. Everything that has to hold up under official scoring must run **offline,
   CPU-only, and inside a timeout**. Stage A does (pure stdlib, ~0.3 s/session).
   Stage B at ~2 s/session on a *GPU* would not survive a CPU-only run of 1000
   sessions even if the service existed.
2. Seat 2's `sentence-transformers` leg is more defensible than an HTTP service
   — the weights are local — but only if they are bundled in the submission and
   fast enough on CPU. Worth confirming early rather than at hour 60.

Stage B is kept because it is legitimate for the demo and the writeup (the rules
explicitly allow local models, and require us to *disclose* fallback behaviour,
which we have: any connection failure falls back to stage A's ordering). It is
just not something to build the score on.

## Per-scenario, current `main`

| scenario | n | Hit@10 | MRR | MTTC |
|----------|---|--------|-----|------|
| buying | 80 | 0.2500 | 0.1209 | 8.54 |
| browsing | 80 | 0.1500 | 0.0476 | 9.55 |
| intent_override | 30 | 0.2667 | 0.1698 | 9.20 |
| boundary | 10 | 0.2000 | 0.1167 | 9.00 |

## Known ceilings (measured, turn-1 query)

Recall of the ground truth inside the 500-candidate pool — nothing downstream
can beat these without retrieval changing:

| | @10 | @50 | @100 | @500 |
|---|-----|-----|------|------|
| BM25 order | 0.185 | 0.380 | 0.525 | 0.860 |
| after stage A | 0.210 | 0.455 | 0.645 | 0.860 |

Stage B (LLM) re-ranks stage A's top 50, so **0.455 is its Hit@10 ceiling**.
Raising the 0.860 pool ceiling is retrieval's job (dense embeddings), not
ranking's.
