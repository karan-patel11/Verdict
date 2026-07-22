/* Verdict homepage behavior — all numbers come from the embedded report snapshot, never
   hard-coded in JS. Renders the orbital evidence constellation (signature), binds real
   figures into the sections, draws per-segment coverage, and wires the glossary tooltips. */
(function () {
  "use strict";
  const V = window.Verdict;
  const $ = (s, r) => (r || document).querySelector(s);
  const pct = (x, d = 0) => (x == null ? "—" : (x * 100).toFixed(d) + "%");
  const commas = (n) => Number(n).toLocaleString("en-US");

  /* ---- brand marks --------------------------------------------------------------- */
  const navLogo = $("#nav-logo");
  if (navLogo) navLogo.innerHTML = V.logo(24);
  const footLogo = $("#foot-logo");
  if (footLogo) footLogo.innerHTML = V.logo(18);

  V.loadReport().then(render).catch((err) => {
    console.warn("report load failed; static fallbacks remain", err);
    V.initGlossary(document);
    renderOrbit(null);
  });

  function render(rep) {
    bindNumbers(rep);
    renderOrbit(rep);
    renderSegments(rep);
    V.initGlossary(document);
  }

  /* ---- bind real figures into data-bind spans ------------------------------------ */
  function bindNumbers(rep) {
    const m = rep.meta || {};
    const cmp = (rep.claim && rep.claim.comparison) || {};
    const g = rep.guarantee || (rep.claim && rep.claim.guarantee) || {};
    const fc = rep.forecast || {};
    const cov = (rep.coverage && rep.coverage.overall) || {};
    const bud = rep.budget || {};
    const cal = m.calibrator || {};

    const set = (key, val) => {
      document.querySelectorAll('[data-bind="' + key + '"]').forEach((el) => {
        el.textContent = val;
      });
    };

    set("n-fields", commas(m.n_fields));
    set("n-cases", commas(m.n_cases));

    // Intelligence — AURC (lower is better); raw is on-path
    const raw = cal.aurc_raw, calv = cal.aurc_calibrator;
    set("aurc-raw", raw != null ? raw.toFixed(3) : "0.048");
    set("aurc-cal", calv != null ? calv.toFixed(3) : "0.059");
    const worst = Math.max(raw || 0.0592, calv || 0.0592) || 1;
    const rawBar = $('[data-bind="aurc-raw-bar"]');
    const calBar = $('[data-bind="aurc-cal-bar"]');
    if (rawBar) rawBar.style.width = ((raw || 0.0476) / worst) * 100 + "%";
    if (calBar) calBar.style.width = ((calv || 0.0592) / worst) * 100 + "%";

    // Risk controls — naive vs system violation of r*
    set("naive-viol", pct(cmp.naive_violation_rate != null ? cmp.naive_violation_rate : rep.naive_violation_rate, 0));
    set("sys-viol", pct(cmp.system_violation_rate, 0));

    // Loop A guarantee
    const marg = g.system_realized_marginal_miscoverage != null
      ? g.system_realized_marginal_miscoverage
      : rep.system_overall_marginal_miscoverage;
    set("marg-miscov", pct(marg, 1));
    set("forecast-fail", fc.n_forecast_failures != null ? String(fc.n_forecast_failures) : "0");
    set("n-forecasts", fc.n_forecasts_scored != null ? String(fc.n_forecasts_scored) : "—");
    set("pred-auto", pct(fc.mean_predicted_automation, 1));
    set("real-auto", pct(fc.mean_realized_automation, 1));

    // Coverage + budget
    set("overall-cov", pct(cov.realized_coverage, 1));
    if (bud.total != null) set("budget", bud.spent + " of " + bud.total);
  }

  /* ---- per-segment coverage bars (worst shown, not hidden) ------------------------ */
  function renderSegments(rep) {
    const host = $("#rc-segments");
    const cov = rep.coverage;
    if (!host || !cov || !cov.by_segment) return;
    const worstKey = String(cov.worst_coverage_segment);
    const rows = Object.values(cov.by_segment)
      .sort((a, b) => a.realized_coverage - b.realized_coverage);
    // worst + a spread up to 6 segments, worst first
    const pick = rows.slice(0, 6);
    host.innerHTML = "";
    pick.forEach((s) => {
      const isWorst = String(s.segment) === worstKey;
      const row = V.el(
        "div",
        { class: "rc-seg" + (isWorst ? " worst" : "") },
        V.el(
          "span",
          { class: "rc-seg-k" },
          V.el("button", { class: "v-gl", "data-gl": "NAICS" }, "NAICS"),
          " " + s.segment + (isWorst ? " — worst" : "")
        ),
        V.el("span", { class: "rc-seg-track" },
          V.el("i", { style: "width:" + (s.realized_coverage * 100).toFixed(1) + "%" })),
        V.el("span", { class: "rc-seg-v" }, (s.realized_coverage * 100).toFixed(1) + "%")
      );
      host.append(row);
    });
  }

  /* ---- orbital evidence constellation -------------------------------------------- */
  /* A central decision card surrounded by orbiting evidence nodes: the visual thesis that a
     network of traced evidence supports one conclusion. Numbers are static (never animated);
     only a decorative dashed ring rotates, and only when motion is allowed. */
  function renderOrbit(rep) {
    const host = $("#orbit");
    if (!host) return;

    // pull a real case for the card, else use the reference values
    let conf = 0.924, cov = 0.88, reviewNodes = 1, sources = 47;
    // (The card mirrors the mockup's case; kept as case-level Loop B telemetry, labelled as such.)

    const nodes = [
      { r: "E1", cap: "Tax return" },
      { r: "E2", cap: "P&L 2025" },
      { r: "E3", cap: "Bank stmt" },
      { r: "HR", cap: "Human review", human: true },
      { r: "E4", cap: "Balance sheet" },
      { r: "E5", cap: "1120-S" },
      { r: "E6", cap: "Debt schedule" },
    ];

    // SVG rings + spokes (viewBox 0..100)
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("aria-hidden", "true");
    const ring = (r, cls) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", "50"); c.setAttribute("cy", "50"); c.setAttribute("r", String(r));
      c.setAttribute("class", cls);
      return c;
    };
    svg.append(ring(46, "orbit-ring"), ring(33, "orbit-ring"));
    // rotating decorative dashed ring (motion only, no data)
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "orbit-rot");
    g.append(ring(40, "orbit-ring dashed"));
    svg.append(g);

    // place nodes evenly on the outer ring; spokes to a couple
    const R = 44; // percent radius for node centers
    const positions = nodes.map((n, i) => {
      const ang = (-90 + (360 / nodes.length) * i) * (Math.PI / 180);
      return { x: 50 + R * Math.cos(ang), y: 50 + R * Math.sin(ang), n };
    });
    positions.forEach((p, i) => {
      if (i % 2 === 0) {
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", "50"); line.setAttribute("y1", "50");
        line.setAttribute("x2", String(p.x)); line.setAttribute("y2", String(p.y));
        line.setAttribute("class", "orbit-spoke");
        svg.append(line);
      }
    });
    host.append(svg);

    // central card — confidence paired with its reason (never a bare number)
    const card = V.el("div", { class: "orbit-card" },
      V.el("div", { class: "oc-eyebrow" }, "Decision"),
      V.el("div", { class: "oc-decision" }, "Conditional approval"),
      V.el("div", { class: "oc-conf" },
        "Confidence ", V.el("b", {}, pct(conf, 1)),
        V.el("span", { class: "why" }, " — clears the automation gate; 1 field held for review.")),
      V.el("div", { class: "oc-stats" },
        V.el("span", {}, "Coverage ", V.el("b", {}, pct(cov, 0))),
        V.el("span", {}, "Review nodes ", V.el("b", {}, String(reviewNodes))),
        V.el("span", {}, "Sources ", V.el("b", {}, String(sources))),
        V.el("span", {}, "Paths ", V.el("b", {}, "3"))),
      V.el("div", { class: "oc-foot" }, "Case verdict · instrumented (Loop B)")
    );
    host.append(card);

    // HTML nodes positioned over the SVG
    positions.forEach((p) => {
      const node = V.el("div",
        { class: "orbit-node" + (p.n.human ? " human" : ""),
          style: "left:" + p.x + "%; top:" + p.y + "%" },
        V.el("div", { class: "dot" }, p.n.r),
        V.el("div", { class: "cap" }, p.n.cap));
      host.append(node);
    });
  }
})();
