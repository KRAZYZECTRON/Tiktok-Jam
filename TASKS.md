| Task      | Owner(s)      | Branch    | Status      | Blocked on |
|-----------|---------------|-----------|-------------|------------|
| Ranking   | Vishwak       | main      | stage A merged (0.205 Hit@10); stage B (LLM) in test | |
| Retrieval | Chetan        | retrieval | not started | rebase on main first — see note |
| Dialog    | YY + Tanush   | dialog    | not started | rebase on main first — see note |

## Rebase before you start — `main` moved

`main` is at `d3179a3`, ahead of where `retrieval` and `dialog` were cut. It
changes `starter/agent.py`, which is the shared file, so branch work started
before this will be measuring against the old pipeline:

```
git fetch origin && git rebase origin/main
```

**What changed and why it affects you:** `agent.py` now asks `retrieve()` for a
**500-candidate pool** instead of 10, and `rank()` narrows it back to 10. No
frozen signature moved. It was worth doing because the ground truth sits at
median rank 86 in retrieval's ordering — recall@10 is 0.185 but recall@500 is
0.860 — so handing `rank()` only 10 candidates capped Hit@10 at 0.185 no matter
what anything downstream did.

- **Chetan / retrieval:** `retrieve()` is now called with `top_k=500`. It needs
  to stay sensible and fast at that depth — that pool is the headroom for the
  whole rest of the pipeline. The 0.860 recall@500 ceiling is yours to raise;
  nothing downstream can beat it.
- **YY + Tanush / dialog:** `ask_attribute` is still hardcoded `None` in
  `agent.py`. The simulated shopper only reveals a new constraint when asked
  about a specific attribute — otherwise it replies with filler. So right now
  the query never grows after turn 1, and every session burns all 10 turns.
  That is the biggest remaining lever on MTTC and it is in your module.

Current `main`: Hit@10 0.205 · MRR 0.104 · MTTC 9.08 (was 0.125 / 0.068 / 9.81).
See `SCOREBOARD.md` for history and measured ceilings.
