# Verdict — Project Report

**Calibrated, field-level abstention for SMB credit underwriting.**  

_21 July 2026 · generated from report.json (shift_severe.yaml, taxonomy 1.1.0, 12000 fields over 2000 cases)._


> Evidence tags: **[MEASURED]** = from a passing test or report.json · **[PARTIAL]** = measured but caveated (synthetic data / chosen operating point) · **[UNVERIFIED]** = stated in code, not independently confirmed.


---


---

# Part 1 — For everyone — plain language, no jargon, no formulas


## 1. The one-paragraph version

Verdict is a tool for reading the financial documents behind a small-business loan application — bank statements, tax returns, balance sheets — and pulling out the numbers an underwriter needs. The hard truth about most AI tools that do this is that they are **confidently wrong exactly on the difficult cases**: the messy document, the unusual industry, the figure that two documents disagree about. Verdict’s entire job is the opposite instinct — **to know when it does not know**, keep only the values it can stand behind, and hand the rest to a human. And it does this with a **measurable promise**: of the values it keeps and automates, it can state in advance roughly how often it will be wrong, and that promise holds even when the incoming applications drift toward industries and document types it has never seen. That restraint — automating less, but honestly — is the product.


## 2. What it does, in plain terms

Picture a loan file as a thick folder of documents. Verdict works through it like a careful clerk with a highlighter:

**Documents in.** The folder arrives — several documents, each with numbers scattered across pages.

**Numbers pulled out, with a source.** For every figure it needs (revenue, net income, debt service, and so on), Verdict records not just the number but *where it came from*: which document, which page, and the exact printed text it read — so anyone can check it later.

**Each number judged: keep or hand off.** This is the heart of it. For each value Verdict decides whether it is confident enough to *keep* (automate) or should *route* it to a person. It routes for three different reasons, and treats them differently: the number is **missing** from the folder; the number is **present but uncertain**; or two documents **disagree** about it.

**The human sees only the uncertain ones.** Instead of re-checking everything, the reviewer gets a short queue of just the flagged items — each with its evidence already attached, so they can resolve it in seconds rather than hunting through the folder.

**An analogy.** A good junior analyst does not guess when they are unsure; they put a sticky note on the page and ask their manager, and they attach the exact figure they were unsure about. Verdict is that instinct, made systematic and measurable — and the promise is about how often the notes it *doesn’t* flag are nonetheless correct.


## 3. What we built — and what we did not

This must be blunt, because it decides how the rest of the report should be read.

**We built** the judgment layer — the keep-or-route decision and the machinery that keeps it honest: the calibration that sets the confidence bar, the three-way handling of missing / uncertain / contradicted values, the closed list of reasons a value can be routed, the source-tracking, and the reviewer-facing screens (a live analysis view and a “memory graph” that maps every finding back to its evidence).

**We did not build a real document reader.** The part that would actually read a PDF and extract figures is a **stub** — a stand-in that produces realistic-looking numbers and confidences so the judgment layer can be exercised end to end. There is no computer vision, no real OCR.

**It has never run on a real loan.** Every result in this report comes from a **simulated stream** of applications, not real files, and not real underwriter corrections. A stakeholder reading only Part 1 should take away one sentence: **this is an honest proof-of-concept of the judgment layer, not a system you can point at real loans today.** Part 3 spells out exactly what would have to be true for that.


## 4. Why it is trustworthy (the differentiator, plainly)

The unusual thing about this project is not the model — it is that **we audited our own system adversarially**, assuming it was exaggerating until proven otherwise, and found four ways it was overstating itself. We fixed all four and re-ran. In plain terms:

**1. We were grading on two different scales.** The system’s success and the comparison’s failure were measured against different bars; we forced them onto one bar, and the win got smaller but honest.

**2. Our “prediction” was not really a prediction.** A number we called a forecast was computed from the same data it was scored against, so it could never be wrong; we made it predict genuinely unseen data.

**3. Our test data made the confidence look smarter than it was.** The simulated errors were tied too tightly to the confidence score; we loosened that so the confidence has to actually earn its keep. The honest error rate rose slightly, and we reported the higher number.

**4. We were calling a raw score “calibrated.”** A component we claimed improved the confidence turned out not to help at all on this data; we checked, found it lost, and labelled the score honestly as raw.

The rest of this report is technical. A non-technical reader can stop here with an accurate picture: a restrained, self-audited proof-of-concept whose honesty is the point.


---

# Part 2 — For technical readers — the rest is technical


## 5. Architecture

**Two loops, deliberately separate.** **Loop A (field extraction)** carries the guarantee: extract → score conformity → calibrate the threshold → route or accept → observe the reviewer’s correction → update. Adaptive Conformal Inference (ACI) applies here because routed items get fast, near-complete feedback. **Loop B (case decision)** is instrumented only — it aggregates fields into a risk tier but makes *no* coverage claim, because a loan’s true outcome arrives months later and only for approved loans. *loops/case_loop.py* raises on any attempt to close its feedback loop; the two layers are kept visually and structurally distinct everywhere. `[MEASURED]`

**Three paths, each a different mechanism.** A field is exactly one of: **ABSENT** (not in the bundle — an extraction-refusal detector, never a low-confidence score); **UNCERTAIN** (present, calibrated abstention — the actual contribution); or **CONTRADICTED** (two sources disagree — reconciliation, which fires regardless of confidence, even at 0.99). Collapsing these into one “needs review” bucket would discard the distinction that makes the queue actionable. The domain types enforce this at construction: a CONTRADICTED or ABSENT field *cannot* be marked ACCEPT (*domain/models.py*). `[MEASURED]`

**Closed reason taxonomy and provenance.** Every decision carries a reason from a fixed, versioned enumeration (*domain/taxonomy.py*, now version 1.1.0) — never free text — so the reasons are auditable and testable for exhaustiveness. Every extracted value carries document, page, bounding box, and the verbatim source text. The memory-graph domain (*memory/*) turns a finished analysis into a validated graph linking each finding to its affected field, the check that raised it, and its evidence; a malformed graph (dangling edge, detached finding, an accepted contradiction) is rejected before it can render. `[MEASURED]`


## 6. Research grounding

Each component is anchored to a specific paper; one honest line each on what actually transferred.

**Geifman &amp; El-Yaniv 2017** — selective risk with a conditional denominator (Eq. 1) and the finding that a boundary-sitting threshold violates its risk target on >50% of splits. *Transferred:* the metric and the baseline that the whole comparison rests on.

**Gibbs &amp; Candès 2021** — Adaptive Conformal Inference, the online update α_{t+1} = α_t + γ(α − err_t), which controls miscoverage under arbitrary drift. *Transferred:* the entire guarantee mechanism for Loop A, verbatim.

**Mozannar &amp; Sontag 2020** — learning-to-defer and the percentile budget protocol. *Transferred:* the deferral framing; the budget is surfaced as telemetry, not used to override a safety decision (see the audit, F5).

**Kamath, Jia &amp; Liang 2020** — a random-forest calibrator over softmax + structure, and the finding that softmax is a strong but imperfect, out-of-distribution-overconfident predictor. *Transferred:* the conceptual basis for treating confidence as partial. The **calibrator itself was cut** — on this synthetic data it did not beat raw softmax (audit F4).

**Mohri &amp; Hashimoto 2024** — conformal factuality and the idea of abstention as partial work (show what *was* established, then where it stopped). *Transferred:* the reviewer-facing framing of a routed item as resumable, not a blank failure.

**Beneish 1999** — the earnings-manipulation model behind the cross-document reconciliation intuition. *Transferred:* the motivation only. **Beneish’s fitted coefficients were deliberately not used** — they were estimated on a specific historical compustat sample and porting them to this synthetic setting would be a fabricated number.


## 7. Headline result, stated honestly

There are two numbers here and they are **not the same quantity**. Stating them as one was the first thing the audit fixed.

**The comparison** (from report.json, one r*, one metric, 8-seed aggregate): on **conditional selective risk** (Geifman Eq. 1) at a single **r* = 0.05**, over randomized adjacent calibrate/deploy windows of a non-exchangeable synthetic stream, the naive confidence-threshold rule violates r* on **57% of held-out windows** (mean 0.5715; min 51%, 0.512) while Verdict’s risk-controlled threshold (SGR / Gascuel–Caraux) violates on **15%** (0.147) — system beats naive on all 8 seeds. `[PARTIAL]`

**The guarantee** is a separate quantity: the Loop-A ACI update holds **marginal miscoverage** (auto-and-wrong over *all* fields) at **α = 0.1** — realized **6.9%** (0.0688), which holds. This is a weaker, different promise than the conditional selective risk above; the same system’s conditional selective risk is 9.0%, which exceeds r* — so the guarantee is genuinely marginal, not a stealth conditional claim. `[PARTIAL]`

Both are tagged `[PARTIAL]` for the same reason: the stream is synthetic and its error level was chosen (Part 3). Supporting figures, all from report.json: coverage 76.1% (a 13.9% shortfall below the 90% target); worst segment NAICS 44 at 70.8% coverage / 5.1% miscoverage (n=1122); 0/39 forecast failures.

Per-seed detail (conditional selective risk, r* = 0.05, violation rate per seed):


| seed | naive violates r* | Verdict violates r* |
| --- | --- | --- |
| 1 | 0.616 | 0.240 |
| 2 | 0.512 | 0.160 |
| 3 | 0.540 | 0.180 |
| 4 | 0.604 | 0.072 |
| 5 | 0.548 | 0.076 |
| 6 | 0.600 | 0.168 |
| 7 | 0.572 | 0.112 |
| 8 | 0.580 | 0.168 |
| mean | 0.5715 | 0.1470 |


## 8. The adversarial audit, in full

An independent pass assumed every claim was inflated until a falsifying test proved otherwise. Six defects were found and closed; each now has a test that goes red if the defect returns. The full suite is **88 Python tests + 18 front-end engine tests**, all passing. `[MEASURED]`


#### F1 — One goalpost, one metric

**Defect:** the system was scored on marginal miscoverage at α = 0.10 while the naive baseline was scored on conditional selective risk at r* = 0.05 — two metrics, two thresholds, no shared bar. **Basis:** Geifman Eq. 1. **Test:** *test_common_threshold_comparison*. **Before → after:** at a common r* = 0.05 on conditional selective risk, naive 57% vs Verdict 15% — a real but smaller win; the +0.02 slack that let “holds” report a miscoverage of up to 12% was removed. `[MEASURED]`


#### F2 — The forecast must be able to miss

**Defect:** the automation “forecast” was computed from the same batch it was scored on, so predicted equalled realized in 40/40 batches — it could not miss, making “0 failures” vacuous. **Basis:** Gibbs &amp; Candès (miscoverage is scored on the unseen next step). **Test:** *test_forecast_can_miss*. **Before → after:** the forecast now predicts each batch from the prior batch and is scored on the new one; maximum automation-rate miss 0.0867, with 32/40 batches missing materially. “0/39 failures” is now a genuine held-out result, not a tautology. `[MEASURED]`


#### F3 — Decouple ground truth from the scored signal

**Defect:** the simulated error was a near-deterministic function of the same confidence used to judge it — confidence was right by construction. **Basis:** Kamath (confidence is a partial, imperfect predictor). **Test:** *test_confidence_not_definitional*, which requires that at a fixed confidence, error probability still varies by more than 0.15. **Before → after:** error is now driven by a latent factor confidence sees only partially (correlation 0.70); the residual gap is 0.246. Fixing this **raised honest marginal miscoverage from 6.2% to 6.9%** — we reported the higher number rather than hide it behind slack. The naive baseline still violates on every seed and the ACI mechanism still reaches α. `[MEASURED]`


#### F4 — The calibrator was cut on an AUC check

**Defect:** the pipeline fed raw softmax while labelling it “calibrated.” **Basis:** Kamath §4. **Test:** *test_confidence_label_is_honest*. **Decision:** we ran the check the honesty demands — does the random-forest calibrator actually beat raw softmax on risk-coverage AUC (lower is better)? It does not: **AURC raw 0.0476 vs calibrator 0.0592**. So the calibrator is declared off-path, routing uses raw extractor softmax, no surface calls it “calibrated,” and the AUC evidence is recorded in report.json so the decision re-decides automatically on real data. `[MEASURED]`


#### F5 — No dead control surfaces

**Defect:** a budget method and two reason codes existed but were never called or emitted — they implied a control (budget flipping a routing decision) the system does not and should not exercise. **Basis:** Mozannar §6 (budget is enforced by construction, or it is telemetry — not a phantom). **Test:** *test_no_dead_control*. **Before → after:** deleted *can_route()* and both reason codes; the taxonomy version bumped to 1.1.0; the budget is now declared telemetry-only. `[MEASURED]`


#### F6 — The memory layer rejects an impossible outcome

**Defect:** the graph builder trusted its caller — an accepted contradiction produced no finding rather than an error. **Test:** *test_memory_layer_rejects_accepted_contradiction*. **Before → after:** the builder now raises *OutcomeInvariantError* on a PATH_3-or-ABSENT field marked ACCEPT, mirroring the domain-level invariant. `[MEASURED]`


---

# Part 3 — Drawbacks and limitations — read this as carefully as the results


## 9. Everything is synthetic

**Plainly:** there are no real documents, no real document reader, and no real underwriter corrections anywhere in this project. Every number in Part 2 — including the headline — is a property of a **simulated model of errors**, not of real underwriting. `[PARTIAL]`

**Technically:** the stream is generated by *data/synthetic.py*; the extractor is a documented stub (*extraction/stub.py*); reviewer corrections are simulated. The confidence–error relationship, the drift, the contradiction rate — all are dials we set. Nothing has been validated against a real corpus.

**To close it:** a real document corpus with gold-standard field values, a real extractor emitting per-field confidences, and a stream of real reviewer corrections to drive the online update. Until those exist, every figure stays `[PARTIAL]` at best.


## 10. The operating point was chosen

**Plainly:** we tuned the difficulty of the simulation so the demonstration would be well-posed — hard enough that the naive rule fails, easy enough that success is possible. On real data the gap between Verdict and the naive rule could be larger, smaller, or absent. `[PARTIAL]`

**Technically:** report.json records the exact choice — err_intercept = 0.05, err_latent_slope = 0.17 — selected so that r* = 0.05 is feasible and the finite-sample selection-bias effect (which is what makes the naive rule fail) is visible. This was a feasibility fix during the audit, not a number-rescue: with confidence held to correlation 0.70, the honest miscoverage was reported at its true value. But the *size* of the naive-vs-Verdict gap is a function of this chosen difficulty and must not be read as a discovered property of the world.

**To close it:** only real data can say what the true difficulty is. We do not estimate it here, on purpose.


## 11. The case-level decision has no guarantee

**Plainly:** the promise covers the individual numbers pulled from documents (the field layer). It does **not** cover the final approve/review/decline decision. That decision is shown for context, but it is not backed by any coverage claim. `[MEASURED]`

**Technically:** Loop B is instrumented only. A loan’s true outcome is a **selective, delayed label** — it arrives months later and only for loans that were approved (you never learn what would have happened to the ones you declined). That breaks the feedback the guarantee needs, so *case_loop.py* refuses to close the loop. Composing per-field guarantees into a case-level one is unsolved (see #13).

**To close it:** a principled theory of how field-level uncertainty composes into a case-level decision under selective labels — an open research problem, not an engineering gap.


## 12. Coverage is marginal, not per-segment

**Plainly:** the promise is an *average* over all fields. A weak segment — say, a particular industry — can perform worse than the average while the average still looks fine. For fair-lending purposes, an average is not a defense. `[MEASURED]`

**Technically:** ACI guarantees *marginal* miscoverage, not conditional-on-segment coverage. The realized figures make this concrete: overall coverage 76.1%, but the worst segment (NAICS 44) sits at 70.8%. The report surfaces the worst segment rather than hiding it in the mean, and the instrumented disparate-impact panel (Loop B) shows a worst-segment false-positive gap of 19.5% (NAICS 21) — flagged, explicitly not guaranteed.

**To close it:** per-segment conformal control (group-conditional coverage), which costs coverage and needs enough volume per segment — feasible, but not built here.


## 13. Uncertainty does not propagate to derived metrics

**Plainly:** even where a single number is trustworthy, combining several into a ratio (like a debt-service coverage ratio) and then into a decision loses the thread — we cannot yet say how confident to be in the *combination*. `[MEASURED]`

**Technically:** field confidence → derived-metric confidence → case-decision confidence is unsolved by any paper in the set; *derived/propagation.py* is a typed seam that raises rather than fabricate a propagated number. A derived metric whose inputs were routed is shown as **BLOCKED**, never given a made-up confidence.

**To close it:** a hierarchical uncertainty-propagation theory. Naming it as unsolved is the honest position; a plausible-looking propagated number would be exactly the confidently-wrong output this project exists to refuse.


## 14. The calibrator adds nothing on this data

**Plainly:** a component we expected to sharpen the confidence turned out useless here, and we say so. `[MEASURED]`

**Technically:** on the decoupled synthetic data the random-forest calibrator loses to raw softmax on risk-coverage AUC (0.0476 vs 0.0592), because this stub has no structural correctness signal beyond the softmax itself. On a real corpus with informative document structure (Kamath’s setting) it may win — the check is wired to re-decide automatically. Today it is off-path.

**To close it:** real documents whose structure carries correctness signal the calibrator can learn.


### What this is, and what it is not

**What it is:** an honest proof-of-concept for calibrated, field-level abstention — a working demonstration that a system can automate a defined fraction of extracted fields while holding a stated, distribution-free promise about how often it is wrong on the ones it keeps, and that the machinery survives an adversarial audit of its own claims. The guarantee is over the conformity score and holds for *any* extractor that produces one — that is the part that would transfer.

**What it is not:** a deployable underwriting system. It has never seen a real document or a real loan; its numbers describe a simulation whose difficulty we chose; its case-level decision carries no guarantee; and its fairness and propagation stories are named open problems, not solved ones. Read every number in this report as a property of a careful simulation, not a promise about real lending.
