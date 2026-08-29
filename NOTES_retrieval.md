# Retrieval Notes

## 2026-08-27
- Baseline confirmed on the `retrieval` branch: Hit@10 `0.125`, MRR `0.068034`, MTTC `9.81`.
- First retrieval change: kept the working SQLite FTS5 BM25 path, added a lazy `sentence-transformers` dense retrieval path, and fused the two with a simple intent-sensitive weighting.
- Added a lightweight `buying` vs `browsing` heuristic so broad queries can use more semantic recall while constrained queries stay more BM25-heavy.
- Evaluated with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m evaluator.local_evaluator --output results_retrieval.json` to avoid long Hugging Face retries during local runs.
- First measured result: Hit@10 `0.22`, MRR `0.114298`, MTTC `8.97`. Biggest lift came from `buying` and `intent_override`; `browsing` improved from `0.025` to `0.0875` but is still the weakest slice.
