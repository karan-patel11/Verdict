# DISCREPANCIES — paper vs. synthesis conflicts found at the formula gate

Rule (Part 1): the PDFs are authoritative; where the synthesis disagrees with the paper, the paper
wins and the conflict is recorded here. Ledger numbering (D1–D5) carries over from the provisional
gate report; D6–D7 were found during print verification.

| # | Status | Severity | Item |
|---|--------|----------|------|
| D1 | **CONFIRMED — paper wins** | High | Synthesis's displayed TATA formula omits the `− Depreciation and amortization` term |
| D2 | Resolved — no conflict | — | Mohri Prop 5.2 prints `A_t(x)`; synthesis was faithful |
| D3 | Resolved — no conflict | — | Beneish AQI is the two-term (CA + PP&E) version in the 1999 FAJ printing |
| D4 | Resolved — no conflict | — | Bayes-optimal pair is Proposition 2 / Eq. (5) in Mozannar (PMLR version) |
| D5 | Resolved — moot | — | Uploaded Beneish PDF is the corrected Jan-2004 printing; all digits verified against it |
| D6 | **CONFIRMED — paper wins** | Medium | Gibbs Thm 4.2 tail term is `(L/2)γ`, not `L²γ` |
| D7 | Paper-internal typo (noted) | Low (non-goal branch) | Mohri Cor. 5.3 prints quantile `⌈(n+1)(1−a)⌉/n` where the proof needs `(1−α)` |

---

## D1 — Beneish TATA: synthesis displayed formula omits −Depreciation & Amortization. PAPER WINS.

- **Synthesis (displayed formula, Track 5):**
  `TATA = [ΔCA − ΔCash − (ΔCL − ΔCurrMatLTD − ΔTaxPayable)] / Total Assets` — no D&A term.
- **Paper (Table 2 notes, printed p.27, corrected Jan-2004 PDF):**
  `TATA = [ΔCurrentAssets_t[4] − ΔCash_t[1] − (ΔCurrentLiabilities_t[5] − ΔCurrentMaturitiesOfLTD_t[44] − ΔIncomeTaxPayable_t[71]) − DepreciationAndAmortization_t[14]] / TotalAssets[6]`
- The synthesis contradicted itself: its own prose ("change in working capital accounts other than
  cash **less depreciation**") and the paper's text (p.28, "Total accruals were calculated as the
  change in working capital accounts other than cash less depreciation") both include the term.
- **Why it matters:** TATA carries the largest coefficient in both probit vectors (4.679 unweighted,
  3.937 WESML) and is the methodological seed of Path 3 (accrual–cash divergence). Dropping D&A
  systematically inflates accruals for any capital-intensive applicant.
- **Action:** `derived/accrual_indices.py` implements the printed formula (with D&A subtraction);
  `tests/test_formulas.py` pins it.

## D6 — Gibbs & Candès Theorem 4.2: tail term is (L/2)γ, not L²γ. PAPER WINS.

- **Synthesis (garbled extraction):** `... + 𝐿2𝛾` — ambiguous; the provisional gate report
  transcribed it as `L²γ`.
- **Paper (Eq. (7), §4.2.3, p.8):**
  `E[(M(α_t|A_t) − α)²] ≤ (L(1+γ)/γ)·E[|α*_{A_{t+1}} − α*_{A_t}|] + (L/2)·γ`
- **Internal cross-check:** minimizing the printed RHS over γ yields the paper's own corollary
  γ = (2·E[|α*_{A_{t+1}} − α*_{A_t}|])^{1/2} with bound L(√2+1)·√(E[|·|]) — consistent only with
  (L/2)γ. (With L²γ the optimizer would be (2E/L)^{1/2}, contradicting the printed corollary.)
- **Why it matters:** telemetry/shift.py reports this bound; γ-tuning guidance derives from it.
  An overstated tail term degrades slowly and invisibly — exactly the F12-class silent failure the
  prompt warned about.
- **Action:** implement the printed form; pin both the bound and the γ* corollary in
  `tests/test_formulas.py`.

## D2 — Mohri Prop 5.2: `A_t(x)` as printed; no synthesis error.

Verified at 400 DPI: the paper prints `r(x,y*) = inf{t ∈ T : ∀j ≥ t, ∀c ∈ A_t(x), y* ⇒ c}` — inner
set subscript **t**, quantifier ∀j ≥ t retained from Eq. (4). Under the Eq. (5) implementation the
score s does not depend on t, so A_j(x) ⊆ A_t(x) for j ≥ t and the two readings coincide (the
quantifier is redundant but harmless). Implementation may compute r by a single descending sweep
over sub-claim scores; document this equivalence in `conformal/` docstrings rather than "fixing"
the printed statement.

## D3 — Beneish AQI: two-term numerator confirmed.

Table 2 notes print `AQI = [1 − (CurrentAssets_t[4] + PP&E[8])/TotalAssets_t[6]] / [same, t−1]`.
No Securities term in the 1999 FAJ printing (the three-term variant belongs to later work, e.g.
Beneish–Lee–Nichols 2013). Synthesis faithful.

## D4 — Mozannar numbering confirmed.

Bayes-optimal (h^B, r^B) is **Proposition 2**, displayed as **Eq. (5)** (§4, pp.3–4 of the PMLR
PDF). Proposition 1 is the consistency of the cost-sensitive surrogate L̃_CE (Eq. (3)). Synthesis
labels were correct.

## D5 — Beneish correction status: moot.

The uploaded PDF is the **corrected January 2004** printing (noted on its first page), i.e. the
exact version the project brief cites. All gated digits (Table 2 definitions, Table 3 coefficient
vectors and t-statistics, Table 5 cutoffs/ECM) were verified against this printing directly.

## D7 — Mohri Corollary 5.3 (paper-internal; not gated; non-goal branch).

Corollary 5.3 prints q̂_α as the `⌈(n+1)(1−a)⌉/n` quantile of the r_a scores, where a ∈ [0,1] is
the acceptable entailment level; the proof ("identical to lower bound of Theorem 4.1") requires
the `(1−α)` quantile for the stated P(·) ≥ 1−α guarantee. Almost certainly a typo for (1−α) in
print. Partial entailment is a non-goal (propagation.py is a typed seam), but if its docstring
cites Corollary 5.3, cite it with this caveat.
