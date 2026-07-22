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

## Deploy to Vercel

The static site lives in `frontend/` and the live-analysis serverless function in `api/`, both
under `Verdictproject/` — **not** the repo root. A zero-config deploy of the repo root 404s
(there is no `index.html` there). Settings:

1. In the Vercel project, set **Root Directory → `Verdictproject`**
   (Settings → General → Root Directory). This is a dashboard setting; it cannot be set from
   `vercel.json`. The Python function imports the real pipeline from `src/`, so the root must be
   `Verdictproject` (which contains both `frontend/` and `src/`), not `frontend/`.
2. **Framework Preset → Other**, no build command. `vercel.json` (at `Verdictproject/`) rewrites
   every non-`/api` path into `frontend/` so `/` serves `frontend/index.html`, enables clean URLs
   (`/workspace` ⇄ `workspace.html`), and bundles `src/**` + `configs/**` with the function.
3. The function needs Python; `requirements.txt` pins its one dependency (PyYAML — the judgment
   pipeline itself is pure standard library). Vercel installs it automatically.

`frontend/report.json` is committed (a snapshot from the experiment) so the deployed pages load
real numbers directly; re-run the experiment to regenerate it. Linked docs (README, gate report,
discrepancies, and the full project report as markdown) live in `frontend/docs/` so the static
deploy is self-contained.

### Live document submission

`POST /api/analyze` runs the **real** judgment pipeline (field loop, three-path routing, ACI
threshold) on an uploaded file. Extraction is **simulated** — the file is hashed to a
deterministic seed that drives the existing synthetic field model; the demo never reads document
contents. The upload is processed in memory only: never written to disk, never logged.

Locally, the static pages open from `file://` or `python -m http.server` (from `frontend/`), but
the `/api/analyze` function needs Vercel's runtime — use `vercel dev` from `Verdictproject/` to
exercise the live path locally:

```bash
cd Verdictproject && vercel dev          # serves the static site AND the Python function
# or, static only, from frontend/:
cd Verdictproject/frontend && python -m http.server 8000
```

## Layout

```
src/abstention/{domain,extraction,scoring,deferral,conformal,loops,derived,forecast,oracle,
                telemetry,baselines,data,experiment}/
tests/   configs/   papers/   frontend/
api/analyze.py                # Vercel Python function — live run of the real judgment pipeline
vercel.json                   # deploy config: rewrites static → frontend/, bundles src/ with api/
requirements.txt              # PyYAML (pipeline is otherwise pure stdlib)
```
