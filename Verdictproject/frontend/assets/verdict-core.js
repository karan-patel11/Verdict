/* Verdict core — report loading, DOM helpers, iconography, shared semantic maps.
   Classic script (no build step, works over file://). Everything lives under window.Verdict. */
(function () {
  "use strict";
  const Verdict = (window.Verdict = window.Verdict || {});

  /* ---- report loading: fetch a served report.json, fall back to the embedded snapshot */
  Verdict.loadReport = function loadReport() {
    const embedded = () => {
      const el = document.getElementById("report");
      if (!el) throw new Error("no embedded report snapshot on this page");
      return JSON.parse(el.textContent);
    };
    return fetch("report.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("http " + r.status))))
      .catch(() => embedded());
  };

  /* ---- tiny DOM builder ---------------------------------------------------------- */
  Verdict.el = function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v; // trusted, builder-side strings only
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k.startsWith("on") && typeof v === "function")
        node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, String(v));
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      node.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return node;
  };

  Verdict.esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    })[c]);

  Verdict.fmt = {
    pct: (x, d = 1) => (x == null ? "n/a" : (x * 100).toFixed(d) + "%"),
    num: (x, d = 3) => (x == null ? "—" : Number(x).toFixed(d)),
    secs: (ms) => "t+" + (ms / 1000).toFixed(2) + "s",
  };

  Verdict.reducedMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- icons: 14×14 stroke glyphs, inherit currentColor --------------------------- */
  const I = (path, extra) =>
    '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    (extra || "") + ">" + path + "</svg>";
  Verdict.icons = {
    file: I('<path d="M3.5 1.5h5l3 3v8h-8v-11z"/><path d="M8.5 1.5v3h3"/>'),
    document: I('<path d="M2.5 1.5h9v11h-9z"/><path d="M4.5 4.5h5M4.5 7h5M4.5 9.5h3"/>'),
    summary: I('<path d="M2.5 3.5h9M2.5 7h9M2.5 10.5h5.5"/>'),
    field: I('<path d="M5.5 1.5h-3v3M8.5 1.5h3v3M12.5 9.5v3h-3M2.5 9.5v3h3"/><circle cx="7" cy="7" r="1.6"/>'),
    check: I('<path d="M7 1.5l4.5 1.8v3.4c0 2.9-1.9 4.6-4.5 5.8C4.4 11.3 2.5 9.6 2.5 6.7V3.3z"/><path d="M5 7l1.4 1.4L9.2 5.6"/>'),
    finding: I('<path d="M7 2l5.6 9.6H1.4z"/><path d="M7 5.6v2.8"/><circle cx="7" cy="10" r=".4" fill="currentColor"/>'),
    evidence: I('<path d="M2.5 8.5c0-3.4 1.2-5.6 3-6.5M8 8.5c0-3.4 1.2-5.6 3-6.5"/><path d="M2.5 8.5h2.6v3H2.5zM8 8.5h2.6v3H8z"/>'),
    metric: I('<path d="M11 3.2H4.2L7.6 7l-3.4 3.8H11"/>'),
    action: I('<circle cx="7" cy="7" r="5.5"/><path d="M4.6 7h4.4M7.4 5.2L9.2 7l-1.8 1.8"/>'),
    success: I('<path d="M2.5 7.6l3 3 6-7.4"/>'),
    warning: I('<path d="M7 2l5.6 9.6H1.4z"/><path d="M7 5.6v2.8"/><circle cx="7" cy="10" r=".4" fill="currentColor"/>'),
    error: I('<path d="M3.2 3.2l7.6 7.6M10.8 3.2l-7.6 7.6"/>'),
    info: I('<circle cx="7" cy="7" r="5.5"/><path d="M7 6.4v3.4"/><circle cx="7" cy="4.2" r=".5" fill="currentColor"/>'),
    system: I('<path d="M2.5 3.5l3.2 3.2-3.2 3.2M7.2 10.8h4.3"/>'),
    agent: I('<path d="M7 1.6l1.5 3.7L12.4 7 8.5 8.5 7 12.4 5.5 8.5 1.6 7l3.9-1.7z"/>'),
    play: I('<path d="M4.7 2.8l6.4 4.2-6.4 4.2z"/>'),
    skip: I('<path d="M3 2.8l5 4.2-5 4.2zM10.6 2.8v8.4"/>'),
    copy: I('<rect x="4.6" y="4.6" width="7" height="7" rx="1"/><path d="M9.4 2.6H3.6a1 1 0 0 0-1 1v5.8"/>'),
    fit: I('<path d="M1.8 4.6V1.8h2.8M9.4 1.8h2.8v2.8M12.2 9.4v2.8H9.4M4.6 12.2H1.8V9.4"/>'),
    zoomin: I('<circle cx="6" cy="6" r="4.4"/><path d="M9.4 9.4l2.8 2.8M4.2 6h3.6M6 4.2v3.6"/>'),
    zoomout: I('<circle cx="6" cy="6" r="4.4"/><path d="M9.4 9.4l2.8 2.8M4.2 6h3.6"/>'),
    search: I('<circle cx="6" cy="6" r="4.4"/><path d="M9.4 9.4l2.8 2.8"/>'),
    reset: I('<path d="M12 7a5 5 0 1 1-1.7-3.8"/><path d="M12 1.6v2.6H9.4"/>'),
    lock: I('<rect x="3" y="6.2" width="8" height="6" rx="1.2"/><path d="M4.8 6V4.2a2.2 2.2 0 0 1 4.4 0V6"/>'),
    chevron: I('<path d="M5 3.2L8.8 7 5 10.8"/>'),
    down: I('<path d="M3.2 5L7 8.8 10.8 5"/>'),
    external: I('<path d="M5.5 2.5H2.5v9h9V8.5"/><path d="M8 2h4v4M12 2L6.8 7.2"/>'),
    spinner: '<svg class="v-spin" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><circle cx="7" cy="7" r="5.2" stroke="currentColor" stroke-opacity=".25" stroke-width="1.6"/><path d="M12.2 7A5.2 5.2 0 0 0 7 1.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  };

  /* Wordmark: a precision "V" built from two weighted strokes — geometric, not decorative. */
  Verdict.logo = (size = 22) =>
    '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<rect x="1" y="1" width="22" height="22" rx="6" fill="var(--accent)"/>' +
    '<path d="M7 6.5l5 11 5-11" stroke="var(--accent-ink)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="17.5" r="1.15" fill="var(--accent-ink)"/></svg>';

  /* ---- semantic maps shared by terminal + graph ----------------------------------- */
  Verdict.CATEGORY_META = {
    FILE: { label: "File", icon: "file", tone: "structure" },
    SUMMARY: { label: "Summary", icon: "summary", tone: "structure" },
    DOCUMENT: { label: "Document", icon: "document", tone: "structure" },
    FIELD: { label: "Field", icon: "field", tone: "entity" },
    CHECK: { label: "Check", icon: "check", tone: "check" },
    FINDING: { label: "Finding", icon: "finding", tone: "finding" },
    EVIDENCE: { label: "Evidence", icon: "evidence", tone: "evidence" },
    METRIC: { label: "Derived metric", icon: "metric", tone: "metric" },
    ACTION: { label: "Recommended action", icon: "action", tone: "insight" },
  };
  Verdict.SEVERITY_ORDER = { NONE: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 };
  Verdict.STAGES = ["QUEUE", "LOAD", "EXTRACT", "SCORE", "DECIDE", "RECONCILE", "DERIVE", "GRAPH", "DONE"];
  Verdict.STAGE_LABEL = {
    QUEUE: "Queued", LOAD: "Loading bundle", EXTRACT: "Extracting fields",
    SCORE: "Scoring conformity", DECIDE: "Routing decisions", RECONCILE: "Reconciling sources",
    DERIVE: "Derived metrics", GRAPH: "Assembling memory graph", DONE: "Finished",
  };
  Verdict.EVENT_KIND_META = {
    system: { icon: "system", cls: "k-system", label: "system" },
    file: { icon: "document", cls: "k-file", label: "file" },
    agent: { icon: "agent", cls: "k-agent", label: "agent" },
    info: { icon: "info", cls: "k-info", label: "info" },
    success: { icon: "success", cls: "k-success", label: "ok" },
    warning: { icon: "warning", cls: "k-warning", label: "warn" },
    error: { icon: "error", cls: "k-error", label: "error" },
    finding: { icon: "finding", cls: "k-finding", label: "finding" },
  };

  /* ---- glossary: expansion + why-it-matters-HERE, grounded in this project ---------- */
  /* Each entry is { term, full, why }. `why` is one sentence about the role the term plays
     in Verdict specifically — not a textbook definition. Consumed by initGlossary() and by
     the <button class="v-gl" data-gl="KEY"> pattern usable directly in static markup. */
  Verdict.glossary = {
    ACI: { term: "ACI", full: "Adaptive Conformal Inference",
      why: "Gibbs & Candès' online update that nudges the abstention threshold αₜ after each reviewer correction, so the field layer's coverage guarantee survives documents drifting away from anything seen in training." },
    AURC: { term: "AURC", full: "Area Under the Risk–Coverage curve",
      why: "The one number that decides whether the Kamath calibrator earns a place on the routing path — here its 0.059 loses to raw softmax's 0.048, so it is held off-path." },
    DSCR: { term: "DSCR", full: "Debt-Service Coverage Ratio",
      why: "Operating income over debt service. A derived metric Verdict refuses to compute until every field it depends on has been reviewed — an unresolved input blocks it." },
    OOD: { term: "OOD", full: "Out-of-distribution",
      why: "A document archetype or industry the extractor was never calibrated on. The guarantee is built to survive exactly these; the stream's OOD rate is tracked window by window." },
    ECOA: { term: "ECOA", full: "Equal Credit Opportunity Act",
      why: "The U.S. fair-lending rule that turns per-segment disparate-impact telemetry into a compliance obligation — which is why the worst-served segment is shown, never averaged away." },
    NAICS: { term: "NAICS", full: "North American Industry Classification System",
      why: "The 2-digit industry code Verdict segments coverage and fairness by, so the worst industry is surfaced instead of hidden inside an aggregate." },
    SGR: { term: "SGR", full: "Selective Guaranteed Risk (Gascuel–Caraux bound)",
      why: "The risk-controlled threshold Verdict uses to hold conditional selective risk at r* — it violates on 15% of windows where the naive max-coverage rule violates on 57%." },
    "r*": { term: "r*", full: "Target conditional selective risk",
      why: "The maximum error rate (here 0.05) Verdict promises among the field values it automates. The naive rule breaks this promise on a majority of held-out windows." },
    ALPHA: { term: "α", full: "Target marginal miscoverage",
      why: "The fraction of all fields (here 0.10) that may be automated-and-wrong. This is the distribution-free quantity Loop A's ACI update actually guarantees — not conditional risk." },
    MARGINAL: { term: "marginal miscoverage", full: "Automated-and-wrong ÷ all fields",
      why: "The exact quantity Loop A guarantees at α. It is deliberately not conditional selective risk — Verdict reports that separately and never conflates the two." },
    CONFORMITY: { term: "conformity score", full: "Distribution-free nonconformity score",
      why: "The scale-normalized score the guarantee is defined over; it holds for any extractor that produces one, which is why the promise attaches to the score, not the model." },
    LOOPA: { term: "Loop A", full: "Field-extraction loop (GUARANTEED)",
      why: "Extract → score → calibrate → route or accept → observe correction → update αₜ. Reviewer corrections give fast feedback, so ACI applies and the coverage guarantee holds here." },
    LOOPB: { term: "Loop B", full: "Case-decision loop (INSTRUMENTED)",
      why: "Aggregates fields into a case verdict. It runs no ACI update and makes no coverage claim — labels are delayed and selective, so it is measured, never guaranteed." },
    NOI: { term: "NOI", full: "Net Operating Income",
      why: "A representative extracted value whose provenance the Evidence Inspector traces all the way down to source document, page, section, and row." },
    ADB: { term: "ADB", full: "Average Daily Balance",
      why: "A bank-statement field Verdict extracts with its verbatim span; its ratio is blocked whenever a required input is still under review." },
    "MEASURED": { term: "[MEASURED]", full: "From a passing test or report.json",
      why: "An observed property of the run — a number the code actually produced, not a claim about the world." },
    "PARTIAL": { term: "[PARTIAL]", full: "Measured but caveated",
      why: "A real number, but on synthetic data or at a chosen operating point — read the stated limitation before quoting it." },
  };

  /* Turn every <button class="v-gl" data-gl="KEY">…</button> under `root` into an accessible
     hover-AND-focus tooltip: injects the definition popup, links it with aria-describedby, and
     wires Escape to dismiss. Idempotent. */
  Verdict.initGlossary = function initGlossary(root) {
    root = root || document;
    const nodes = root.querySelectorAll("button.v-gl[data-gl]:not([data-gl-ready])");
    nodes.forEach((btn, i) => {
      const key = btn.getAttribute("data-gl");
      const g = Verdict.glossary[key];
      if (!g) return;
      btn.setAttribute("data-gl-ready", "");
      btn.setAttribute("type", "button");
      const id =
        "gl-" + key.replace(/[^a-z0-9]/gi, "") + "-" + Math.random().toString(36).slice(2, 7);
      const pop = Verdict.el(
        "span",
        { class: "v-gl-pop", role: "tooltip", id: id },
        Verdict.el("span", { class: "v-gl-term" }, g.full),
        Verdict.el("span", { class: "v-gl-why" }, g.why)
      );
      btn.setAttribute("aria-describedby", id);
      btn.append(pop);
      // flip the popup to the right edge when the term sits in the right part of the viewport,
      // so the tooltip never runs off-screen on narrow layouts
      const place = () => {
        const r = btn.getBoundingClientRect();
        btn.classList.toggle("gl-right", r.left > window.innerWidth * 0.55);
      };
      btn.addEventListener("mouseenter", place);
      btn.addEventListener("focus", place);
      btn.addEventListener("keydown", (e) => {
        if (e.key === "Escape") btn.blur();
      });
    });
  };
})();
