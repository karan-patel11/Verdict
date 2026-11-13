# PREREG: real-filings evaluation of Verdict (v2)

**Status: DRAFT. Not frozen.** This file becomes binding when it is committed and tagged `prereg-v1`.
The lockbox (`src/abstention/experiment/lockbox.py`) refuses to open the test set unless that tag exists,
this file and `configs/real_eval.yaml` are byte-identical to their tagged versions, and the corpus hash
below matches the corpus manifest. Anything still marked `TODO(freeze)` must be filled from DEV results only.

Self-registration caveat: one person writes, labels, adjudicates and runs this. The tag is
self-registration. Push the tag to GitHub before the test run so the hosted timestamp shows the order of events.

## 1. Claim under test

On real SEC filings read by a real LLM extractor, a Verdict gate keeps automated-and-wrong fields at or below a
stated share of ALL fields, while the extractor's own raw confidence at a conventional cutoff does not.

The guaranteed quantity is **marginal miscoverage** (automated-and-wrong fields / all fields).
Conditional selective risk is reported but is not guaranteed.

## 2. Data

- Source: SEC EDGAR filings and the filers' own XBRL facts (gold labels). Declared User-Agent, at most 8 requests/s.
- Unit: the primary financial statements section, rendered to text pages. Locating that section is a separate
  retrieval step done by `render.select_statement_pages` (heuristic); its failures are counted as extractor errors only
  if the statements are present in the filing, and are reported separately.
- Fields (8): revenue, operating income, net income, depreciation and amortization, interest expense,
  total assets, total liabilities, cash and equivalents. Specs: `data/gold_labels.py::SPECS`.
- Split: by company, never by filing. DEV 100 filings, TEST (lockbox) 300 filings, at most 2 filings per company in TEST,
  stratified by SIC division.
- Contamination control: every TEST filing is filed on or after the latest knowledge cutoff of every extractor used
  (Claude Fable 5.2: 2026-07-01, per Anthropic's model page). In practice that means mostly Q2/Q3 2026 10-Qs
  and off-cycle 10-Ks. See DEVIATIONS.md DEV-001.
- Leakage control: inline-XBRL markup and hidden facts are stripped before the extractor sees anything.
  `tests/test_no_leakage.py` enforces tag-markup absence and that gold values are not injected outside the document block.
- corpus_hash: `TODO(freeze)` (64 hex chars from `corpus/manifest.json`; format the lockbox expects:
  `corpus_hash: <64 hex>` on its own line)

## 3. Extractors

| id | model | notes |
|---|---|---|
| E1 | `claude-fable-5-2` via the Anthropic Messages API | `output_config.effort = TODO(freeze, default medium)`, `max_tokens = 16000`. Adaptive thinking is always on. No temperature, top_p, top_k or forced tool use is sent (the API rejects or ignores them). JSON returned as text. |
| E2 | `TODO(freeze)`: a second, different model (smaller or open-weights, ideally with token log-probs) | Needed for H5 and H6. If E2 is not run, H5 and H6 are reported `not_evaluable`, not passed. |

Prompt: `extraction/llm_extractor.py::SYSTEM` and `build_prompt`. Prompt SHA-256 is stored with every call.
Prompts are tuned on DEV only.

## 4. Confidence signals

`stated`, `agreement` (k = 5 samples at default sampling), `token_prob` (None for Fable 5.2: no logprobs exposed),
`structural`. One primary signal per extractor, chosen by lowest DEV AURC with `run_real choose-signal`
and written into `configs/real_eval.yaml::primary_signal` before the freeze. All signals are reported on TEST as exploratory.

## 5. Methods

B0 automate everything; B1 raw confidence >= 0.90; B2 naive max-coverage threshold; B3 static SGR threshold fitted on DEV;
B4 reviewer-accuracy rule only; B5 adaptive conformal threshold only; B6 full Verdict.
Parameters are frozen in `configs/real_eval.yaml`: alpha in {0.10, 0.05}, ACI gamma = 0.02
(0.01 and 0.005 as sensitivity runs), batch 200, minimum calibration 100, quantile window 800, reviewer accuracy 0.70,
audit rates 1.0 and 0.2. The reviewer is an **oracle** (the gold value plays the reviewer). It is never described as human review.

Streams: chronological by filing date, and an industry-shift ordering. Statistics: resample FILINGS (never fields),
1000 bootstrap draws, seed 20261123, 95% intervals, paired resampling for method comparisons.

## 6. Hypotheses and pass rules (TEST stream, per extractor, per ordering)

| id | pass rule | if it fails |
|---|---|---|
| H1 | B6 marginal miscoverage <= alpha + 0.02 at BOTH alpha = 0.10 and 0.05, AND B6 automation >= 30% at alpha = 0.10 | Report the miss and its size. Claim no guarantee on real data. |
| H2 | Primary-signal B1 breaks the 5% target in more 200-field windows than B6, and the paired block-bootstrap interval for the difference excludes zero | Publish it; reframe as "adds a guarantee to a practice that happened to work". |
| H3 | Learned calibrator has lower AURC than the raw primary signal (paired bootstrap interval excludes zero) | Keep the calibrator off the decision path and say so. |
| H4 | At alpha = 0.05, B6 has lower marginal miscoverage than B4 and automates at least 1 point less | Report that the reviewer rule suffices on real data. |
| H5 | After the industry shift and after swapping E1 for E2 at the stream midpoint, B6 miscoverage over the next 300 fields stays <= alpha + 0.02 with adaptation on, and exceeds that bound for a threshold frozen before the shift | Narrow the claim to the conditions where it held. |
| H6 | H1 and H4 hold in the same direction for both extractors and both orderings | Report which cells held and which did not. |

Verdict values: `pass`, `fail`, `inconclusive`, `not_evaluable`.

**Minimum evidence:** if an extractor makes fewer than 60 errors on TEST (`min_errors`), every hypothesis for that
extractor is `inconclusive`, regardless of point estimates. A degraded-scan stress variant may then be run and
labelled a stress test. It is never mixed into the main results.

## 7. Other pre-committed checks

- **Closed-book probe:** ask each extractor for the field values with no document, on TEST filings. Accuracy must be near zero;
  otherwise absolute accuracy is flagged as contaminated and only relative comparisons are reported.
- **Label adjudication:** every extractor-vs-gold disagreement is reviewed blind to confidence, plus a random 3% of agreements.
  A gold label changes only if the filing text shows a tagging error; each change is a row in `label_changes.csv` with evidence.
- **Raw retention:** every model call is stored (`runs/<id>/raw.jsonl`, `prompts/<sha>.txt`); metrics are recomputed from stored outputs.
- **Budget cap:** `TODO(freeze)` USD for the whole run, enforced by `CostMeter` (`--max-usd`). Run a 10-filing pilot first and price the run from real token counts, including thinking tokens.
- **No hand-typed numbers:** every published figure is a row in `CLAIMS.md`, regenerated from stored outputs.
- **Everything is reported:** all extractors, both alphas, both orderings. Only H1 to H6 are confirmatory; all else is exploratory.

## 8. Claims allowed after the run

Allowed only if the matching hypothesis passed: a statement of the form "On N real SEC filings filed after the extractor's
knowledge cutoff, Verdict held automated-and-wrong fields to X% of all fields (95% CI Y to Z) at a 10% target, where a 0.90
confidence cutoff reached W%." Never allowed: "validated on small-business loan documents", "production-ready",
"guarantees accuracy", any figure not in `CLAIMS.md`.
