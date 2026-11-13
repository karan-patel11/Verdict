# CLAIMS ledger

Governance rule 8: a figure is published only through a row here. `python -m pytest tests/test_claims_ledger.py`
loads each source, follows the pointer, and fails if the stored value no longer equals `expected`.
In the README or site, write a figure as `[[claim:<id>]]` next to the sentence that uses it; a marker whose id is not in
this table fails the test. Numbers typed without a marker are NOT detected (see `experiment/claims.py`).

## Simulation (synthetic data only: nothing here supports a claim about real filings)

| id | statement | source | pointer | expected | tol |
|---|---|---|---|---|---|
| abl.a05.full.automation | Full gate automation rate at alpha=0.05 (synthetic, severe shift) | report/ablation_aci.json | targets.1.variants.full.automation_rate | 0.6288 | 0.0005 |
| abl.a05.full.miscoverage | Full gate marginal miscoverage at alpha=0.05 | report/ablation_aci.json | targets.1.variants.full.marginal_miscoverage | 0.0477 | 0.0005 |
| abl.a05.reviewer_only.automation | Reviewer-rule-only automation rate at alpha=0.05 | report/ablation_aci.json | targets.1.variants.reviewer_only.automation_rate | 0.7605 | 0.0005 |
| abl.a05.reviewer_only.miscoverage | Reviewer-rule-only marginal miscoverage at alpha=0.05 | report/ablation_aci.json | targets.1.variants.reviewer_only.marginal_miscoverage | 0.0685 | 0.0005 |

## Pre-registered parameters

| id | statement | source | pointer | expected | tol |
|---|---|---|---|---|---|
| prereg.gamma | ACI step size used by every published number, and pre-registered for the real-filings run | configs/real_eval.yaml | gamma | 0.02 | 0 |
| prereg.min_errors | Minimum test errors before any hypothesis can be concluded | configs/real_eval.yaml | min_errors | 60 | 0 |

## Real filings

No rows yet. Rows are added only by `experiment/run_real.py evaluate` output after the lockbox run
(`report/real_eval_results.json`). Until then the project makes no claim about real filings.
