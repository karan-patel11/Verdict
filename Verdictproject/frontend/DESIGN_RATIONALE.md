# Reviewer Queue — Design Rationale

**Two audiences, one thesis.** The screen serves a credit reviewer clearing a queue under time
pressure, and a compliance examiner reconstructing a decision 24 months later. The reviewer's
accuracy is not a UX nicety — it is a **modeled input to the routing rule** (invariant 5:
defer iff calibrated confidence < reviewer accuracy). Friction that degrades that accuracy
degrades the system's guarantee. So the design goal is **legibility of uncertainty, not
innovation signaling.** A screen that looks like a trading terminal invites the reviewer to
trust numbers that carry no guarantee — that is fair-lending exposure expressed as CSS. Every
decision below follows from legibility, and each is tied to the invariant or finding that
forces it.

**1. No bare confidence numbers.** Each item leads with a DECISION and a closed-enum RouteReason,
never "87%." A bare percentage implies the conditional coverage the system does not have. The
raw confidence appears only *inside* the provenance panel, contextualized against the reviewer
accuracy it was compared to. (Part 7 §1; taxonomy invariant 12.)

**2. Guaranteed and instrumented surfaces never share a treatment — the most important decision
on the page.** Loop A (field coverage) carries a solid accent and a `GUARANTEED` marker; Loop B
(case decisions, fairness) carries a dashed/hatched border, a muted field, and an
`INSTRUMENTED — not guaranteed` marker. If a reviewer can't tell at a glance which claims are
backed, the two-loop architecture is decorative. The distinction is encoded three ways — border
style, label text, and icon — never by color alone.

**3. The three paths are visually distinct because they demand different actions.** ABSENT ("find
it or confirm it isn't there"), UNCERTAIN ("check the extracted value"), and CONTRADICTED
("reconcile two sources") get different icons, labels, and left-accents. Collapsing them into
one "needs review" state discards the taxonomy (invariant 11; Kamath §5.7). CONTRADICTED shows
*both* sources and states plainly that high confidence on both is irrelevant.

**4. Abstention is partial work, not failure.** Following Mohri & Hashimoto's MATH result, each
routed item shows what *was* established — located, normalized, scored — and then the specific
step where it stopped. Never a blank "unable to determine." This is what lets the reviewer
resume rather than restart. (Part 7 §6.)

**5. Provenance is one click from every value.** Document, page, bounding box, and the *verbatim*
raw span. Verbatim spans render in monospace so `1,234.00` and `1234` are unmistakable — Kamath
§5.6 found 62% of the worst overconfidence errors were span/normalization artifacts, most of the
error mass. A reviewer who can't see the artifact marks it an error and poisons the calibrator.
(Invariant 9.)

**6. The reviewer budget is finite and always visible, with burn.** A reviewer who doesn't know
the budget cannot triage. The header carries a burn bar (Part 7 §4).

**7. Per-segment coverage is a first-class panel with the worst segment pinned to the top.** ACI
gives marginal coverage; realized coverage wanders (~σ 0.09). A portfolio average that masks a
weak segment is not an ECOA defense, so the worst segment is surfaced always, never averaged
away (non-goals; Part 7 §3).

**8. No animation on uncertainty.** Motion is reserved for state changes the reviewer *causes*
(expanding a row). Animated confidence figures read as certainty theater (Part 7 §8).

**Type, space, color — each chosen, not defaulted.** UI text is `system-ui` (zero-load, familiar,
legible at small sizes — the reviewer reads this for hours). Numeric values and spans are
monospace (makes format artifacts visible — §5, load-bearing, not cosmetic). Color is a
restrained near-neutral base with three low-saturation accents; it is always paired with an icon
and text so it never carries meaning alone (WCAG AA — a colorblind reviewer whose accuracy drops
is an invariant-5 violation, not an accessibility ticket, §9). Spacing is deliberately generous:
one item's full context beats six items skimmed.

**What restraint costs — the real tradeoff.** Generous spacing and per-item context mean **fewer
items on screen and more scrolling** — lower raw throughput than a dense grid. That is a genuine
cost, not a free virtue. We pay it on purpose: the routing guarantee is only as good as the
reviewer accuracy it assumes, and density that raises misread rates would quietly erode the one
property the whole system exists to provide. Throughput we can buy with more reviewers; a
corrupted calibrator we cannot buy back.
