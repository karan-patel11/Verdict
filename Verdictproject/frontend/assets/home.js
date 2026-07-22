/* Homepage behavior — populate real numbers from the report, render a real (not decorative)
   memory-graph snapshot in the hero, and wire the workflow demo to the actual terminal +
   graph components running on recorded analysis data. */
(function () {
  "use strict";
  const V = window.Verdict;
  const el = V.el, icons = V.icons, engine = V.graphEngine;

  function init(report) {
    fillMetrics(report);
    renderHeroPreview(report);
    wireWorkflow(report);
  }

  /* ---- real hero + claim metrics --------------------------------------------------- */
  function fillMetrics(report) {
    const claim = report.claim || {};
    const cov = (report.coverage && report.coverage.overall) || {};
    const fc = report.forecast || {};
    set("m-automated", V.fmt.pct(cov.realized_coverage, 0));
    set("m-miscoverage", V.fmt.pct(claim.system_overall_marginal_miscoverage, 1));
    set("m-alpha", "≤ " + V.fmt.pct(report.meta && report.meta.alpha, 0));
    set("m-naive", V.fmt.pct(claim.naive_violation_rate, 0));
    set("m-forecast-fail", (fc.n_forecast_failures != null ? fc.n_forecast_failures : "0") +
      " / " + (fc.n_forecasts_scored != null ? fc.n_forecasts_scored : "0"));
    // trust/credibility inline numbers
    set("t-fields", (report.meta && report.meta.n_fields) ? report.meta.n_fields.toLocaleString() : "—");
    set("t-taxonomy", report.meta && report.meta.taxonomy_version);
    const worst = report.coverage && report.coverage.by_segment &&
      report.coverage.by_segment[report.coverage.worst_coverage_segment];
    if (worst) set("t-worst", "NAICS " + worst.segment + " · " + V.fmt.pct(worst.realized_coverage, 1));
  }
  function set(id, v) { const n = document.getElementById(id); if (n != null && v != null) n.textContent = v; }

  /* ---- hero preview: a real graph snapshot rendered as static SVG ------------------
     Uses the actual layout engine on a real analysis graph so the hero shows the true
     product, not a mockup. Picks the highest-severity completed analysis for visual interest. */
  function renderHeroPreview(report) {
    const host = document.getElementById("hero-graph");
    if (!host) return;
    const analyses = (report.analyses || []).filter((a) => a.graph);
    if (!analyses.length) return;
    const rank = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1, NONE: 0 };
    const a = analyses.slice().sort((x, y) =>
      rank[y.worst_severity] - rank[x.worst_severity])[0];
    const graph = a.graph;
    // Compact fixed node sizes for a legible thumbnail.
    const sizes = {};
    for (const n of graph.nodes) sizes[n.id] = { w: 128, h: 40 };
    const layout = engine.layoutGraph(graph, { sizes, orientation: "LR", colGap: 46, rowGap: 12 });
    const { width, height } = layout.size;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label",
      `Memory graph preview for ${a.file_label}: ${graph.nodes.length} nodes linking documents, fields, and findings to source evidence.`);

    const catColor = {
      FILE: "--cat-structure", SUMMARY: "--cat-structure", DOCUMENT: "--cat-structure",
      FIELD: "--cat-entity", CHECK: "--cat-check", EVIDENCE: "--cat-evidence",
      METRIC: "--cat-metric", ACTION: "--cat-insight",
    };
    const sevColor = { LOW: "--sev-low", MEDIUM: "--sev-med", HIGH: "--sev-high", CRITICAL: "--sev-crit" };

    for (const e of graph.edges) {
      const geo = engine.edgePath(layout.rects, e, "LR");
      if (!geo) continue;
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", geo.d);
      p.setAttribute("fill", "none");
      p.setAttribute("stroke", e.relation === "BLOCKS" ? "var(--sev-high)" : "var(--line-strong)");
      p.setAttribute("stroke-width", "1.2");
      if (e.relation === "BLOCKS") p.setAttribute("stroke-dasharray", "4 3");
      svg.append(p);
    }
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    for (const n of graph.nodes) {
      const r = layout.rects[n.id];
      const g = document.createElementNS(NS, "g");
      const isFinding = n.category === "FINDING";
      const accent = isFinding ? (sevColor[n.severity] || "--sev-low") : (catColor[n.category] || "--cat-structure");
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", r.x); rect.setAttribute("y", r.y);
      rect.setAttribute("width", r.w); rect.setAttribute("height", r.h);
      rect.setAttribute("rx", "7");
      rect.setAttribute("fill", isFinding ? `color-mix(in srgb, var(${accent}) 16%, var(--panel))` : "var(--panel)");
      rect.setAttribute("stroke", `var(${accent})`);
      rect.setAttribute("stroke-width", isFinding ? "1.4" : "1");
      svg.append(rect);
      const bar = document.createElementNS(NS, "rect");
      bar.setAttribute("x", r.x); bar.setAttribute("y", r.y);
      bar.setAttribute("width", "3.5"); bar.setAttribute("height", r.h);
      bar.setAttribute("rx", "2"); bar.setAttribute("fill", `var(${accent})`);
      svg.append(bar);
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", r.x + 11); label.setAttribute("y", r.y + 16);
      label.setAttribute("font-size", "10.5"); label.setAttribute("font-weight", "600");
      label.setAttribute("fill", "var(--ink)");
      label.setAttribute("font-family", "var(--font-mono)");
      label.textContent = truncate(n.label, 15);
      svg.append(label);
      const sub = document.createElementNS(NS, "text");
      sub.setAttribute("x", r.x + 11); sub.setAttribute("y", r.y + 30);
      sub.setAttribute("font-size", "8.5"); sub.setAttribute("fill", "var(--muted)");
      sub.textContent = truncate((V.CATEGORY_META[n.category] || {}).label || n.category, 18);
      svg.append(sub);
    }
    host.innerHTML = "";
    host.append(svg);
    const cap = document.getElementById("hero-preview-file");
    if (cap) cap.textContent = a.file_label;
    const tag = document.getElementById("hero-preview-sev");
    if (tag) {
      tag.className = "v-sev v-sev-" + a.worst_severity + " tag";
      tag.textContent = a.worst_severity === "NONE" ? "CLEAN" : a.worst_severity;
    }
  }
  function truncate(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  /* ---- workflow demo: real terminal + graph on selectable files -------------------- */
  function wireWorkflow(report) {
    const analyses = (report.analyses || []);
    const chipsEl = document.getElementById("flow-files");
    const termMount = document.getElementById("home-terminal");
    const graphMount = document.getElementById("home-graph");
    if (!chipsEl || !termMount || !graphMount) return;

    const terminal = new V.AnalysisTerminal(termMount, {
      autoplay: false,
      onComplete: (a) => { if (a === current) showGraph(a); },
    });
    const graph = new V.MemoryGraphView(graphMount, { orientation: "LR" });
    let current = null;

    function showGraph(a) {
      if (a.status === "FAILED" || !a.graph) {
        graph.setState("error", "This analysis failed before decisions were issued — no memory graph is published for a failed run.");
      } else graph.render(a.graph);
    }

    function pick(a, replay) {
      current = a;
      for (const c of chipsEl.querySelectorAll(".flow-chip"))
        c.setAttribute("aria-pressed", String(c.dataset.id === a.analysis_id));
      terminal.load(a, { autoplay: replay && !V.reducedMotion() });
      if (replay && !V.reducedMotion() && a.graph) graph.setState("loading", "Replaying the recorded analysis — the memory graph appears when it completes.");
      else showGraph(a);
    }

    // Prefer an interesting mix: default to the highest-severity completed analysis.
    const rank = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1, NONE: 0 };
    const ordered = analyses.slice();
    const def = ordered.filter((a) => a.graph).sort((x, y) => rank[y.worst_severity] - rank[x.worst_severity])[0] || ordered[0];

    for (const a of analyses) {
      const chip = el("button", { class: "flow-chip", type: "button", "data-id": a.analysis_id,
        "aria-pressed": "false" },
        el("span", { class: "v-dot " + dot(a.status) }), a.file_label.replace(".bundle", ""));
      chip.addEventListener("click", () => pick(a, true));
      chipsEl.append(chip);
    }
    if (def) pick(def, false);
  }
  function dot(s) {
    return ({ COMPLETED: "v-dot-ok", PARTIAL: "v-dot-warn", FAILED: "v-dot-err" })[s] || "v-dot-idle";
  }

  window.Verdict.initHome = init;
})();
