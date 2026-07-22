# Verdict — a credit underwriting agent that only rules when it's earned the right to

Calibrated, **field-level abstention that holds up under distribution shift**. The contribution
is narrow and provable: the system forecasts, *in advance*, what fraction of fields it can
safely automate versus hand to a human — and that forecast survives archetypes and industries
absent from training.

## The falsifiable claim this repo supports

> On a stream containing document archetypes and industries absent from training, the system
> automates a fraction of fields at a marginal miscoverage of at most α, and the realized
> miscoverage does not exceed α — while the naive confidence-threshold baseline violates r* in
> **>50% of runs**.

Every module exists to make that sentence checkable.

**Honest scoping.** The field layer (Loop A) carries a distribution-free guarantee via ACI; the
guaranteed quantity is **marginal** miscoverage (auto-and-wrong / all fields ≤ α), not
conditional selective risk — "ACI gives marginal" (non-goals). Conditional selective risk is
reported and segmented, with the worst segment surfaced, never claimed as guaranteed. The case
layer (Loop B) is instrumented only: it does not run the ACI update and claims no coverage
(delayed, selective labels; Gibbs & Candès §7).

## Reproduce it

```bash
pip install -e .            # numpy, scikit-learn, PyYAML
pytest                      # 57 tests: 12 invariants, formula checks, the >50% baseline, loops
python -m abstention.experiment --config configs/shift_severe.yaml   # writes frontend/report.json
```

Expected under `shift_severe.yaml`: the **naive baseline violates r* in ~54% of runs** (>50%,
PASS, aggregated over 8 seeds at ~5σ above the boundary), while the **field loop holds marginal
miscoverage ≈ α** and logs **0 forecast failures**. On the same windows SGR's Gascuel–Caraux
bound threshold violates only ~9% — the guarantee machinery beats eyeball-thresholding badly.

**Honest mechanism.** The naive rule's >50% failure is dominated by finite-sample *selection
bias* (maximizing coverage picks the luckiest threshold, so train risk under-estimates true
risk) — Geifman's result, which holds even i.i.d.; distribution shift adds to it. So the rate
sits in the mid-50s across regimes rather than swinging dramatically with shift severity; that
is the faithful reproduction ("just over 50%," mean relative violation ~0.5), not an engineered
0.8. `tests/test_naive_baseline.py` asserts >50% under `shift_severe.yaml`, aggregated over
seeds (as Geifman aggregated 1000 splits). If it ever fails, either the stream stopped shifting
or the baseline is misimplemented — both are findings.

## Two loops

- **Loop A — field extraction (GUARANTEED).** extract → score conformity → calibrate → route or
  accept → observe reviewer correction → update α_t. ACI applies here (reviewer corrections give
  fast feedback on routed items). `loops/field_loop.py`, `conformal/`, `scoring/`, `deferral/`.
- **Loop B — case decision (INSTRUMENTED, NOT GUARANTEED).** aggregate → derived metrics → case
  decision. No ACI update, no coverage claim. `loops/case_loop.py` raises on any attempt to
  close the loop. Does **not** inherit Loop A.

## Three paths, never collapsed

`ABSENT` (extraction refusal, a separate detector) · `UNCERTAIN` (calibrated abstention — the
contribution) · `CONTRADICTED` (reconciliation across ≥2 sources; fires at confidence 0.99,
never suppressed by budget). `domain/paths.py` discriminates them with no confidence parameter,
by construction.

## Provenance & the papers

The formula gate (`GATE_REPORT.md`) verified all 23 gated formulas against the printed source
PDFs (`papers/`); paper-vs-synthesis conflicts are recorded in `DISCREPANCIES.md` (notably D1:
Beneish's TATA carries the −D&A term; D6: Gibbs Thm 4.2's tail is (L/2)γ).

## Front-end

`frontend/queue.html` is a working single-file reviewer-queue prototype reading the report JSON;
`frontend/DESIGN_RATIONALE.md` argues every design decision from the legibility-of-uncertainty
thesis. Open the HTML directly (embeds a snapshot) or serve `frontend/` to load a fresh
`report.json`.

## Layout

```
src/abstention/{domain,extraction,scoring,deferral,conformal,loops,derived,forecast,oracle,
                telemetry,baselines,data,experiment}/
tests/   configs/   papers/   frontend/
```
