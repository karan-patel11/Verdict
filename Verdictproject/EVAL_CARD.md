# EVAL CARD: what the v2 evaluation can and cannot show

**Can show:** whether the gate's marginal-miscoverage control transfers from a simulator to real documents read by a real LLM, under rules fixed in PREREG.md.
**Cannot show:** behaviour on small-business lending documents; behaviour with real human reviewers (the reviewer is an oracle); case-level decision quality (Loop B stays synthetic); anything if the extractor makes fewer than 60 test errors (verdict `inconclusive`).
**One person** labels, adjudicates and runs this; there is no outside replication. The git tag is self-registration.
**Sensitivity:** gamma 0.02 (pre-registered) with 0.01 and 0.005 as sensitivity runs; audit rates 1.0 and 0.2.
**Results file:** `report/real_eval_results.json`, produced by `run_real evaluate`. Figures are published only via `CLAIMS.md`.
**Status:** no real-filings result exists yet. Simulation results elsewhere in this repo do not support claims about real filings.
