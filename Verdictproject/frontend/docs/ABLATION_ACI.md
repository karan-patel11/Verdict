# ACI ablation: which gate is doing the work?

Loop A automates a field only when two gates both pass: the conformal gate (nonconformity
score within the ACI-adapted threshold) and the reviewer gate (confidence at least the
reviewer's expected accuracy, 0.70 here). The headline run reports 6.9% marginal miscoverage
against a 10% target. That number does not say which gate produced it. This ablation does.

Reproduce:

```bash
python -m abstention.experiment.ablation --config configs/shift_severe.yaml --out report/ablation_aci.json
```

Stream: `configs/shift_severe.yaml`, 12,000 fields per seed, means over 8 seeds. Synthetic data;
every caveat in `PROJECT_REPORT.md` applies. "Max marginal" is the worst single seed.

| Target α | Variant | Automated | Marginal miscoverage | Max marginal | Conditional selective risk |
| ---: | --- | ---: | ---: | ---: | ---: |
| 0.10 | full | 75.8% | 6.8% | 7.0% | 9.0% |
| 0.10 | reviewer only | 76.0% | 6.9% | 7.0% | 9.0% |
| 0.10 | aci only | 85.8% | 9.3% | 9.5% | 10.9% |
| 0.10 | neither | 97.5% | 12.4% | 12.6% | 12.7% |
| 0.05 | full | 62.9% | 4.8% | 4.8% | 7.6% |
| 0.05 | reviewer only | 76.0% | 6.9% | 7.0% | 9.0% |
| 0.05 | aci only | 62.7% | 4.8% | 4.8% | 7.6% |
| 0.05 | neither | 97.5% | 12.4% | 12.6% | 12.7% |
| 0.03 | full | 48.1% | 2.8% | 2.9% | 5.9% |
| 0.03 | reviewer only | 76.0% | 6.9% | 7.0% | 9.0% |
| 0.03 | aci only | 48.1% | 2.8% | 2.9% | 5.9% |
| 0.03 | neither | 97.5% | 12.4% | 12.6% | 12.7% |
| 0.01 | full | 25.6% | 0.9% | 0.9% | 3.5% |
| 0.01 | reviewer only | 76.0% | 6.9% | 7.0% | 9.0% |
| 0.01 | aci only | 25.6% | 0.9% | 0.9% | 3.5% |
| 0.01 | neither | 97.5% | 12.4% | 12.6% | 12.7% |

Variants: **full** = both gates (shipped). **reviewer only** = conformal gate off after warm-up.
**aci only** = reviewer gate off. **neither** = every scored field automated after warm-up.

## What it shows

1. **At the headline target (α = 0.10) ACI is slack.** Full and reviewer-only differ by 0.2
   points of automation and under 0.1 points of miscoverage. The reviewer gate alone keeps
   the stream under 10%, so the adaptive level drifts to its ceiling. The 6.9% headline is the
   reviewer gate's result, not evidence that ACI was needed.
2. **ACI alone does hold the target.** With the reviewer gate removed, ACI holds 9.3% (worst
   seed 9.5%) against 10%, while automating 85.8%. With no gate at all, miscoverage is 12.4%.
   So the mechanism works; at this target the reviewer gate is simply the stricter of the two.
3. **At stricter targets ACI binds and holds.** At α = 0.05, 0.03 and 0.01 the reviewer gate
   alone stays at 6.9% and misses every target. With ACI on, realised miscoverage is 4.8%,
   2.8% and 0.9%.
4. **The price is automation.** Holding 5% costs 13 points of automation (76% to 63%); holding
   1% leaves 26% automated. That trade-off is the real product decision.
5. **Conditional selective risk is still not controlled.** It falls as α tightens (9.0% to
   3.5%) but nothing guarantees it. Only at α = 0.01 does it fall under r* = 0.05.

## Implementation note

`experiment/report.py` runs the field loop with `gamma = max(config gamma, 0.02)`, so the loop's
ACI step size on these configs is 0.02, not the 0.005 written in the config files and reported
in `report.json` meta. The ablation uses the same floor so its numbers match the headline run.
The 0.005 value should either be used or the reported value corrected.
