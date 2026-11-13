# V2 evaluation plan

The full plan, with the timeline and source list, lives in the planning doc:
https://claude.ai/artifact/NYK3b42Bx5r7urSCas5SNf ("Verdict to 8: Real-Data Evaluation Plan with Strict Governance").

The binding, version-controlled parts are `PREREG.md` (hypotheses, pass rules, frozen choices), `configs/real_eval.yaml`
(parameters), `DEVIATIONS.md`, `DATA_CARD.md` and `EVAL_CARD.md`. If the doc and `PREREG.md` disagree, `PREREG.md` wins.

## Run order

```bash
export SEC_USER_AGENT="Your Name your@email"        # must contain an email
export ANTHROPIC_API_KEY=...
python -m abstention.data.edgar_corpus --index <form.idx files> --cutoff 2026-07-01 --out corpus
python -m abstention.experiment.run_real extract --split dev --run-id e1_pilot --limit 10 --max-usd 20   # cost pilot
python -m abstention.experiment.run_real extract --split dev --run-id e1_dev --max-usd <cap>
python -m abstention.experiment.run_real choose-signal --run runs/e1_dev
# fill TODO(freeze) in PREREG.md, primary_signal in configs/real_eval.yaml, then:
git add -A && git commit -m "Freeze pre-registration" && git tag prereg-v1 && git push origin prereg-v1
python -m abstention.experiment.run_real extract --split test --run-id e1_test --max-usd <cap>   # once
python -m abstention.experiment.run_real evaluate --dev E1=runs/e1_dev --test E1=runs/e1_test
```
