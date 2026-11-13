# Formula Verification Gate — Report (Part 1)

**Date:** 2026-07-16 (supersedes the provisional report of the same date)
**Status:** ✅ **GATE COMPLETE — all 23 formulas verified against the printed papers.**
Verification method: each formula's page was rendered from the uploaded PDF and read visually
(math in text extraction garbles; images don't). Numeric anchors were additionally grepped from
extracted text. Papers live in `papers/`; extracted text alongside each PDF.

**Discrepancies found:** 2 substantive (synthesis's TATA formula wrong; Theorem 4.2 tail term
mis-transcribed in the provisional report), 1 paper-internal typo noted (Mohri Cor. 5.3),
4 earlier flags resolved as non-issues. Full ledger in `DISCREPANCIES.md`.

Per Part 8 this is hard stop #1: **no domain code has been written.** DISCREPANCIES.md is included
here because it is the gate's evidence record (Part 1: "the paper wins and you record it in
DISCREPANCIES.md"); step 3 (domain/ + failing tests) awaits confirmation.

---

## Geifman & El-Yaniv 2017 — *Selective Classification for Deep Neural Networks* (NeurIPS)

**F1 — Selective risk and coverage. VERIFIED.** §2 "Problem Setting", p.2. Coverage in prose:
"coverage, defined to be φ(f,g) ≜ E_P[g(x)], is the probability mass of the non-rejected region
in X." Selective risk displayed as **Eq. (1)**:

    R(f,g) ≜ E_P[ℓ(f(x),y) g(x)] / φ(f,g)                                        (1)

Guarantee formulation is **Eq. (2)**: Pr_{S_m}{R(f,g) > r*} < δ, coverage maximized subject to it.

**F2 — Threshold selection function. VERIFIED.** §3, **Eq. (3)**, p.3:

    g_θ(x) = g_θ(x|κ_f) ≜ { 1  if κ_f(x) ≥ θ;  0  otherwise }                     (3)

**F3 — Gascuel–Caraux bound. VERIFIED.** §3, **Lemma 3.1 (Gascuel and Caraux, 1992, [10])**,
**Eq. (4)**, p.3. B*(r̂, δ, S_m) is the solution b of:

    Σ_{j=0}^{m·r̂(f|S_m)} C(m,j) b^j (1−b)^{m−j} = δ                              (4)

Then Pr_{S_m}{R(f|P) > B*(r̂_i, δ, S_m)} < δ. Directly beneath, as printed: "the analytic bounds
derived using, e.g., Hoeffding inequality (or other concentration inequalities), approximate this
numerical bound and incur some slack." Binomial tail confirmed; Hoeffding explicitly deprecated.
The summation's upper limit is printed exactly `m·r̂(f|S_m)` (an integer error count under 0/1 loss;
no ceiling/floor decoration in print).

Also verified for implementation: empirical selective risk r̂(f,g|S_m) ≜ (1/m Σ ℓ(f(x_i),y_i)g(x_i)) / φ̂(f,g|S_m),
empirical coverage φ̂(f,g|S_m) ≜ (1/m)Σ g(x_i), g-projection g(S_m) ≜ {(x,y) ∈ S_m : g(x)=1};
**footnote 1**: an infeasible (S_m, δ, r*) triplet returns a vacuous solution with zero coverage.

**F4 — SGR Algorithm 1 with δ/k. VERIFIED.** §3, **Algorithm 1**, p.4, as printed:

    1: SGR(f, κ_f, δ, r*, S_m)
    2: Sort S_m according to κ_f(x_i), x_i ∈ S_m (w.l.o.g. indices reflect ordering)
    3: z_min = 1; z_max = m
    4: for i = 1 to k ≜ ⌈log₂ m⌉ do
    5:   z = ⌈(z_min + z_max)/2⌉
    6:   θ = κ_f(x_z)
    7:   g_i = g_θ  {(see (3))}
    8:   r̂_i = r̂(f, g_i|S_m)
    9:   b*_i = B*(r̂_i, δ/⌈log₂ m⌉, g_i(S_m))   {see Lemma 3.1}
    10:  if b*_i < r* then  z_max = z  else  z_min = z
    16: Output- (f, g_k) and the bound b*_k.

The δ/⌈log₂ m⌉ correction is on line 9, as gated.

**F5 — Theorem 3.2. VERIFIED.** §3, p.4, with P_g(X,Y) ≜ P(X,Y | g(X)=1):

    Pr_{S_m}{ ∃i : R(f|P_{g_i}) > B*(r̂_i, δ/k, g_i(S_m)) } < δ,   k ≜ ⌈log₂ m⌉

Proof allocates δ/k per iteration (displayed Eq. (5) in the proof) and closes with the union bound.
**Footnote 2** (implementation-relevant): Theorem 3.2 always holds, but a severely skewed κ_f can
leave the bound far from the target risk.

**Naive-baseline result (Part 4 dependency). VERIFIED**, §5.2, p.7, verbatim: "a basic baseline in
which the threshold is defined to be the value that maximizes coverage while keeping train error
smaller then r*. For this simple baseline we found that in over 50% of the cases (1000 random
train/test splits), the bound r* was violated over the test set, with a mean violation of 18%
relative to the requested r*."

## Mozannar & Sontag 2020 — *Consistent Estimators for Learning to Defer to an Expert* (ICML, PMLR 119)

**F6 — System loss. VERIFIED.** §3 "Problem Formulation", **Eq. (1)** and **Eq. (2)**, pp.2–3:

    L(h,r) = E_{(x,y)∼P, m∼M|(x,y)} [ l(x,y,h(x))·1_{r(X)=0} + l_exp(x,y,m)·1_{r(x)=1} ]   (1)
    L_{0−1}(h,r) = E_{(x,y)∼P, m∼M|(x,y)} [ 1_{h(x)≠y}·1_{r(x)=0} + 1_{m≠y}·1_{r(x)=1} ]   (2)

**Deferral cost (invariant 6). VERIFIED**, §3, p.3, verbatim: "One may also assume a constant
additive cost function c(x) for querying the expert depending on the instance x making
l_exp(x,y,m) = 1_{m≠y} + c(x); such additive costs can be easily integrated into our analysis."

**F7 — Bayes-optimal pair. VERIFIED.** §4, **Proposition 2**, displayed as **Eq. (5)**, pp.3–4,
with η_y(x) = P(Y=y|X=x): "The minimizers of the loss L_{0−1} ... are defined point-wise for all
x ∈ X as:"

    h^B(x) = argmax_{y∈Y} η_y(x)
    r^B(x) = 1[ max_{y∈Y} η_y(x) ≤ P(Y=M | X=x) ]                                  (5)

Numbering confirmed: it is Proposition 2 (Proposition 1 is the consistency of the cost-sensitive
surrogate L̃_CE, Eq. (3)).

**F8 — L_CE surrogate. VERIFIED.** §4, **Eq. (6)**, p.4, with h(x) = argmax_{y∈Y} g_y(x) and
r(x) = 1[max_{y∈Y} g_y(x) ≤ g_⊥(x)]:

    L_CE(h,r,x,y,m) = −log( exp(g_y(x)) / Σ_{y'∈Y∪⊥} exp(g_{y'}(x)) )
                      − 1_{m=y} log( exp(g_⊥(x)) / Σ_{y'∈Y∪⊥} exp(g_{y'}(x)) )      (6)

**Theorem 1** as printed: L_CE is convex in g, upper bounds L_{0−1}, and is consistent —
inf_{h,r} E[L_CE] is attained at (h*_CE, r*_CE) with h^B(x) = h*_CE(x), r^B(x) = r*_CE(x) ∀x.

**F9 — α-reweighted surrogate. VERIFIED.** §4, **Eq. (7)**, p.4:

    L^α_CE(h,r,x,y,m) = −(α·1_{m=y} + 1_{m≠y}) log( exp(g_y(x)) / Σ_{y'∈Y∪⊥} exp(g_{y'}(x)) )
                        − 1_{m=y} log( exp(g_⊥(x)) / Σ_{y'∈Y∪⊥} exp(g_{y'}(x)) )    (7)

"Note that L¹_CE = L_CE"; α is "an additional hyperparameter to optimize for" (CheXpert selected
α per task; §6.4 trains one epoch with L^α_CE, α maximizing AU-ROC).

**F10 — CheXpert coverage protocol. VERIFIED.** **§6.4**, p.8, verbatim: "We achieve this for our
method by first sorting the test set based on g_⊥(x) − max(g_0(x), g_1(x)) := q(x) across all
patients x in the test set, then to achieve coverage c, we define τ = q(x_c) where q(x_c) is the
c'th percentile of the outputs q(x), then we let r(x) = 1 ⟺ q(x) ≥ τ. The definition of τ
ensures that we obtain exactly c% coverage." Percentile over the test stream; defer iff q(x) ≥ τ.

**Fairness anchor (invariant 10). VERIFIED**, §6.5, p.8: classifier discrimination 0.226, fair
expert 0.03, confidence-baseline composition 0.449 — "fairness does not compose (Dwork & Ilvento,
2018)."

## Gibbs & Candès 2021 — *Adaptive Conformal Inference Under Distribution Shift* (NeurIPS)

**F11 — ACI update. VERIFIED.** §2, **Eq. (2)**, p.3, with α_1 = α as the initial estimate:

    err_t := { 1 if Y_t ∉ Ĉ_t(α_t); 0 otherwise },  Ĉ_t(α_t) := {y : S_t(X_t,y) ≤ Q̂_t(1−α_t)}
    α_{t+1} := α_t + γ(α − err_t)                                                   (2)

Also verified: M_t(α) := P(S_t(X_t,Y_t) > Q̂_t(1−α)); α*_t := sup{β ∈ [0,1] : M_t(β) ≤ α};
weighted alternative Eq. (3) with w_s ∝ 0.95^{t−s} produces very similar, smoother trajectories;
the paper's experiments use γ = 0.005 (§2.1/§2.2), which is the configs/baseline.yaml library default
(invariant 3). This project's stream experiments run at γ = 0.02 (`experiment/report.py` takes max(config, 0.02));
the real-filings evaluation pre-registers γ = 0.02 and reports 0.01 and 0.005 as sensitivity runs.

**F12 — Clamp bounds. VERIFIED.** §4.1, **Lemma 4.1**, p.6, verbatim: "With probability one we
have that ∀t ∈ ℕ, α_t ∈ [−γ, 1+γ]." (Not [0,1].)

**F13 — Long-run coverage. VERIFIED.** §4.1, **Proposition 4.1 / Eq. (5)**, p.6:

    | (1/T) Σ_{t=1}^T err_t − α | ≤ (max{α_1, 1−α_1} + γ) / (Tγ)                    (5)

"In particular, lim_{T→∞} (1/T) Σ err_t =^{a.s.} α." And: "Proposition 4.1 puts no constraints on
the data generating distribution." Approximate-tightness discussion (noiseless update,
(1−(1−cγ)^T)/(Tγ)·|α_1 − α*|) verified beneath it.

**F14 — Shift statistic. VERIFIED WITH CORRECTION.** §4.2.3, **Theorem 4.2 / Eq. (7)**, p.8.
Hypotheses: |M(α_2|a) − M(α_1|a)| ≤ L|α_2 − α_1| for all a ∈ A and α_1, α_2 ∈ ℝ; ∀a ∃α*_a ∈ (0,1)
with M(α*_a|a) = α. As printed:

    E[(M(α_t|A_t) − α)²] ≤ (L(1+γ)/γ)·E[|α*_{A_{t+1}} − α*_{A_t}|] + (L/2)·γ        (7)

⚠ The tail term is **(L/2)γ**, NOT the "L²γ" that the synthesis's garbled extraction suggested
(DISCREPANCIES.md D6). Cross-check: minimizing the printed RHS over γ gives exactly the printed
corollary γ = (2E[|α*_{A_{t+1}} − α*_{A_t}|])^{1/2} and bound L(√2+1)·√(E[|α*_{A_{t+1}} − α*_{A_t}|])
— internally consistent only with (L/2)γ. E|α*_{A_{t+1}} − α*_{A_t}| is the shift statistic for
telemetry/shift.py.

**F15 — Normalized vs unnormalized score. VERIFIED.** **§5** "Impact of S_t(·) on the
performance", p.9:

    S_t := |V_t − σ̂²_t| / σ̂²_t        (normalized — used in §2.2)
    S̃_t := |V_t − σ̂²_t|               (the "a priori reasonable alternative")

Verbatim: "normalization by σ̂²_t is critical for obtaining an approximately stationary conformity
score and thus S̃_t leads to much worse coverage properties... the coverage now undergoes much
wider swings away from the target level of 0.9. This issue can be partially mitigated by choosing
a larger value of γ." Figure 2 (p.9) shows the swings (≈0.4–1.0 on the Fannie Mae panel) versus
Figure 1's tight band — the invariant-2 / ablation_unnormalized.yaml basis.

## Kamath, Jia & Liang 2020 — *Selective Question Answering under Domain Shift* (ACL)

**F16 — Calibrator spec. VERIFIED.** **§4.3 "Training a calibrator"**, p.5, verbatim: "The
calibrator itself could be any binary classification model. We use a random forest classifier
with seven features: passage length, the length of the predicted answer ŷ, and the top five
softmax probabilities output by the model." Training regime (§5.1, p.5): scikit-learn RF; 1,600
SQuAD + 1,600 known-OOD examples; remaining 400 + 400 as validation for grid search; averaged
over 10 random splits; 3,200/800 when trained on p_source only. Feature ablations §5.5/Table 4;
MLP and logistic regression slightly worse than RF (Appendix A.2).

**F17 — Evaluation protocol. VERIFIED.** §3.1–3.2, pp.3–4. Selective prediction outputs (ŷ, c);
"Given a threshold γ ∈ ℝ, the overall system predicts ŷ if c ≥ γ and abstain otherwise"; risk
versus coverage evaluated by "the area under this curve (AUC), as well as the maximum possible
coverage for a desired risk level" (coverage @ 80%/90% accuracy in the results). Test mixture,
**Eq. (1)**, p.4: p_test = α·p_source + (1−α)·q_unk, α = 1/2.

Numeric anchors verified in print: MaxProb 20.54/48.23/21.07; calibrator (p_source+q_known)
18.47/56.06/29.42; CI [1.01, 1.69] paired bootstrap 1000 samples; **A.3 outlier detector** — same
model class, training data, and features as the calibrator, "does not achieve good selective
prediction performance" (24.23/37.91/14.26), QA models "can often get a non-trivial fraction of
OOD examples correct" (§2.3) [invariant 4]; **§5.7** calibrator 54.0 EM / MaxProb 53.1 / majority
48.9 — "identifying unanswerable questions is a very different task from knowing when to abstain
under distribution shift" [invariant 11 / Path 1]; **§5.6** "62% of overconfidence errors are due
to the model predicting valid alternate answers, or span mismatches" [invariant 9]; Figure 4
transfer — HotpotQA best 9.93 (multi-hop dissimilarity).

## Mohri & Hashimoto 2024 — *Language Models with Conformal Factuality Guarantees* (ICML)

**F18 — Conformity score. VERIFIED.** §3 (application to the language setting), **Eq. (4)**, p.5:

    r(x, y*) := inf{ t ∈ T : ∀j ≥ t, y* ∈ E(F_j(x)) }                               (4)

**Footnote 3**, verbatim: "The key difference with respect to (Gupta et al., 2022) is that in the
definition of r we write: ∀j ≥ t. This is implicitly encoded in their definition due to the nested
property of their set predictors, but as we do not require nestedness, we instead explicitly
modify our thresholds to be strictly safe." Soundness: F_{sup T}(x, y_0) = ∅.

**F19 — Algorithm 1 quantile. VERIFIED.** **Algorithm 1**, p.6: for i = 1..n compute
r(X_i, Y*_i) ← inf{t ∈ T: ∀j ≥ t, y* ∈ E(F_j(x, L(x)))}; then

    q̂_α ← ⌈(n+1)(1−α)⌉/n -th quantile of {r(X_i, Y*_i)}_{i=1}^n
    Output: conformally factual L̄(x) := F_{q̂_α}(x, L(x))

**Theorem 4.1**, p.6: exchangeable {X_i, Y*_i}_{i=1}^{n+1}, F_t sound, scores distinct WLOG,
α ∈ [1/(n+1), 1] ⇒ P(Y*_{n+1} ∈ E(F_{q̂_α}(X_{n+1}))) ≥ 1−α; if E(F_t(·)) follows the nested
property, upper bound 1−α+1/(n+1) ≥ P(·). Both bounds verified as printed.

**F20 — Assumption 5.1 and Proposition 5.2. VERIFIED.** §5, pp.7–8. Assumption 5.1: for any
y* ∈ Y and {c_i}_{i=1}^n ∈ 2^Y:

    { y* ⇒ M({c_i}_{i=1}^n) } ⟺ { ∀i ∈ [n], y* ⇒ c_i }
    equivalently  E(M({c_i}_{i=1}^n)) = ∩_{i=1}^n E(c_i)

Sub-claim implementation **Eq. (5)**, p.7: F_t(x) = M({c ∈ (S∘L)(x): s((S∘L)(x), c) ≥ t}).
Proposition 5.2, with A_t(x) := {c ∈ (S∘L)(x): s((S∘L)(x), c) ≥ t}:

    r(x, y*) = inf{ t ∈ T : ∀j ≥ t, ∀c ∈ A_t(x), y* ⇒ c }

Confirmed at 400 DPI: the paper prints **A_t(x)** (the ∀j ≥ t is redundant-but-harmless here,
since A_j(x) ⊆ A_t(x) for j ≥ t under Eq. (5) — the synthesis transcribed print faithfully; see
DISCREPANCIES.md D2). Annotation-cost consequence verbatim: "one only has to call the entailment
oracle on the sub-claims appearing in the original output..." Nestedness (hence the Thm 4.1 upper
bound) follows from Assumption 5.1 via E(F_t(x)) = ∩_{c∈A_t(x)} E(c).

(Non-gated observation: Corollary 5.3 prints the quantile as ⌈(n+1)(1−a)⌉/n using the entailment
level a; the proof "identical to Theorem 4.1's lower bound" requires (1−α). Likely paper typo —
recorded as D7 since propagation.py's docstring may cite this corollary.)

## Beneish 1999 — *The Detection of Earnings Manipulation* (FAJ, **corrected January 2004** — confirmed on p.1 of the uploaded PDF)

**F21 — Eight variable definitions. VERIFIED** against Table 2 notes (printed p.27), which give
Compustat item numbers [in brackets]:

    DSRI = (Receivables_t[2]/Sales_t[12]) / (Receivables_{t−1}/Sales_{t−1})
    GMI  = [(Sales_{t−1}[12] − COGS_{t−1}[41])/Sales_{t−1}[12]] / [(Sales_t[12] − COGS_t[41])/Sales_t[12]]
    AQI  = [1 − (CurrentAssets_t[4] + PP&E[8])/TotalAssets_t[6]] / [1 − (CA_{t−1} + PP&E_{t−1})/TA_{t−1}]
    SGI  = Sales_t[12] / Sales_{t−1}
    DEPI = [Depreciation_{t−1}[14−65]/(Depreciation_{t−1} + PP&E_{t−1}[8])] / [Depreciation_t/(Depreciation_t + PP&E_t)]
    SGAI = (SG&A_t[189]/Sales_t[12]) / (SG&A_{t−1}/Sales_{t−1})
    LVGI = [(LTD_t[9] + CurrentLiabilities_t[5])/TotalAssets_t[6]] / [(LTD_{t−1} + CL_{t−1})/TA_{t−1}]
    TATA = [ ΔCurrentAssets_t[4] − ΔCash_t[1]
             − (ΔCurrentLiabilities_t[5] − ΔCurrentMaturitiesOfLTD_t[44] − ΔIncomeTaxPayable_t[71])
             − DepreciationAndAmortization_t[14] ] / TotalAssets[6]

⚠ **TATA includes "− Depreciation and amortization_t[14]"** — the synthesis's displayed formula
omitted this term (its own prose had it right: "the change in working capital accounts other than
cash less depreciation," §"Total accruals to total assets," p.28). Paper wins — DISCREPANCIES.md
D1. **AQI numerator is the two-term (CA + PP&E) version** — no Securities term in the 1999 FAJ
printing (D3 resolved).

Preprocessing verified (p.28): winsorize at the 1st/99th percentiles per variable; AQI set to 1
(neutral) when the reference-year denominator is zero (period t−1 assets exclusively CA + PP&E);
DEPI and SGAI set to 1 when components (amortization of intangibles #65, SG&A #189) unavailable;
estimating with and without those observations yielded similar results.

**F22 — Both probit coefficient vectors. VERIFIED** against Table 3 Panel A (printed p.29),
t-statistics in parentheses:

    WESML:      −4.954 (−11.80) + 0.789 (6.40)·DSRI + 0.459 (3.02)·GMI + 0.306 (2.82)·AQI
                + 0.701 (3.43)·SGI + 0.033 (0.15)·DEPI − 0.006 (−0.04)·SGAI
                + 3.937 (3.07)·TATA − 0.264 (−0.83)·LVGI
                [pseudo-R² 0.306; χ² 34.50 (p = 0.00); prior P(M) = 0.0069]

    Unweighted: −4.840 (−11.01) + 0.920 (6.02)·DSRI + 0.528 (2.20)·GMI + 0.404 (3.20)·AQI
                + 0.892 (5.39)·SGI + 0.115 (0.70)·DEPI − 0.172 (−0.71)·SGAI
                + 4.679 (3.73)·TATA − 0.327 (−1.22)·LVGI
                [pseudo-R² 0.371; χ² 129.20 (p = 0.00); prior P(M) = 0.02844]

All coefficients and t-stats match the synthesis exactly. Per non-goals, these betas are never
applied to SMB inputs — they exist for test_formulas.py checks and methodology provenance only.

**F23 — ECM. VERIFIED** against Table 5 notes (printed p.32), verbatim:

    ECM = P(M)·P_I·C_I + [1 − P(M)]·P_II·C_II

"where P(M) is the prior probability of encountering earnings manipulators (0.0069 for WESML and
0.02844 for unweighted probit), P_I and P_II are the conditional probabilities of, respectively,
Type I and Type II errors, and C_I and C_II are the costs of Type I and Type II errors. Cutoff
probabilities were chosen for each level of relative costs to minimize the expected costs of
misclassification."

Conventions confirmed in print: **Type I = misclassifying a manipulator as a nonmanipulator**
(text: at 10:1 the model "misclassified 42 percent of the manipulators" = Table 5 Type I 0.4200).
Footnote a: naive all-nonmanipulator ECM = 0.0069·C_I (WESML) / 0.02844·C_I (unweighted).
Footnote b: at 40:1 and beyond (unweighted) the naive strategy switches to all-manipulator
"because the ratio of relative costs was greater than the population proportion of manipulators...
(> 1/0.02844)"; relative-cost-vs-naive column: 0.680/0.496/0.417/0.433/0.562/0.819 (estimation),
0.746/0.623/0.582/0.628/0.896/1.535 (holdout). Investor-relevant cost range verified (p.32): ~40%
risk-adjusted value loss in the discovery quarter vs 1–2% quarterly appreciation ⇒ "the relevant
range is likely between 20:1 and 30:1." Holdout detection range verified: "correctly classified
manipulators ranges from 37.5 percent to 56.1 percent."

---

## Gate verdict

All 23 gated formulas verified against print. Two transcription errors caught and corrected
(D1: TATA missing −D&A in the synthesis's displayed formula; D6: Theorem 4.2 tail term (L/2)γ,
not L²γ). The uploaded Beneish PDF is the corrected January 2004 printing the spec cites, so
D5 is moot. See DISCREPANCIES.md for the full ledger.

Awaiting confirmation to proceed to step 3 (domain/ + failing tests).
