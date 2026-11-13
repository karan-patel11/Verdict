# DEVIATIONS

Anything done differently from the v2 plan, with date and reason. The lockbox also appends here when an override is used.
Entries dated before the `prereg-v1` tag are design changes; entries after it are true deviations and must appear in any write-up.

| id | date | what changed | why | effect on claims |
|---|---|---|---|---|
| DEV-001 | 2026-11-13 | TEST filings must be filed on or after the latest extractor knowledge cutoff (Fable 5.2: 2026-07-01), so the corpus is mostly Q2/Q3 2026 10-Qs and off-cycle 10-Ks, not December-FYE 10-Ks. | A model with a Jun 2026 cutoff may have seen anything filed earlier; the plan's contamination rule forces this. | Fewer 10-Ks, more quarterly statements (3-month vs YTD columns). Gold derivation handles both. Results must say "10-Q-heavy". |
| DEV-002 | 2026-11-13 | `LLMExtractor` does not implement `extraction.base.Extractor`. | That interface is typed to the synthetic `FieldType`; the real fields have different semantics (scale, period, absent). | None; the decision core is unchanged and is fed through `real_eval.py` observations. |
| DEV-003 | 2026-11-13 | Leakage rule 4 clarified: gold values legitimately appear in the document text, so the test checks (a) no tag markup, (b) no gold values outside the document block of the prompt. | The plan's wording ("gold values never appear in a prompt") is impossible, since the filing contains its own numbers. | None; the real protection is stripping XBRL. |
| DEV-004 | 2026-11-13 | Fable 5.2 exposes no temperature and no token log-probs, so `token_prob` is None for E1 and `agreement` uses default sampling. | Per Anthropic's model page. | The primary-signal choice for E1 is among `stated`, `agreement`, `structural`. |
| DEV-005 | 2026-11-13 | H2 compares window-violation counts with a block bootstrap over filings. | Windows overlap and fields within a filing are correlated; a plain paired test would be overconfident. | Wider intervals. |
| DEV-006 | 2026-11-13 | ACI gamma corrected in config/report meta from 0.005 to 0.02; library default (`conformal/aci.py`, `field_loop.py`) left at 0.005. | Every published synthetic result was produced at 0.02 (`report.py` uses `max(gamma, 0.02)`); the stated value was wrong. | No synthetic number changed. Real run pre-registers 0.02 with 0.01 and 0.005 as sensitivity runs. |
