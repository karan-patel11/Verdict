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
})();
