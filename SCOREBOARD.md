# Scoreboard

Every merge into `main` appends a row here. Full 200-session public set via
`py -m evaluator.local_evaluator` — subset runs never go in this table.

Score = 0.50·Hit@10 + 0.30·MRR + 0.20·efficiency, efficiency = (11 − MTTC)/10.

| date | what changed | Hit@10 | MRR | MTTC | score |
|------|--------------|--------|-----|------|-------|
| 27 Aug | BM25 keyword baseline (kit as shipped) | 0.1250 | 0.0680 | 9.81 | 0.1067 |
| 28 Aug | wide pool (500) + state-aware stage-A rerank | 0.2050 | 0.1045 | 9.08 | 0.1722 |

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
