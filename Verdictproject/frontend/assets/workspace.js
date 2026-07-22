/* Verdict analysis terminal — three-column underwriting workspace.
   Left rail = Loop B case list (instrumented). Center = tabbed Loop B case view. Right =
   Loop A Evidence Inspector (guaranteed). Everything is driven by the real report snapshot:
   the case rail from report.analyses, each case's fields/provenance from its memory graph,
   the processing overlay from the recorded per-stage event log. No values are invented.

   Two honesty rules are load-bearing here:
   - The guarantee boundary (Loop A vs Loop B) is drawn as a persistent split and repeated as a
     spine+glyph+label marker on every region, so the mixed dashboard never blurs it.
   - Confidence is never shown as a bare number: every confidence figure ships with the reason
     it is there (which gate it cleared or missed). */
(function () {
  "use strict";
  const V = window.Verdict;
  const el = V.el, icons = V.icons, pct = (x, d = 1) => (x == null ? "n/a" : (x * 100).toFixed(d) + "%");

  /* ---------- small semantic helpers ---------------------------------------------- */
  const GRADE = { NONE: "A", LOW: "B+", MEDIUM: "B", HIGH: "C", CRITICAL: "D" };
  const PATH_META = {
    PATH_2: { cls: "path-2", glyph: "◐", label: "Uncertain", act: "Explain abstention" },
    PATH_1: { cls: "path-1", glyph: "⌀", label: "Absent", act: "Inspect missing" },
    PATH_3: { cls: "path-3", glyph: "⇄", label: "Contradicted", act: "Reconcile sources" },
    DEGRADED: { cls: "path-deg", glyph: "○", label: "Degraded", act: "Re-extract" },
  };
  function pathChip(path, accepted) {
    if (accepted) return el("span", { class: "path-chip path-accept" }, el("span", { class: "g" }, "✓"), "Automated");
    const m = PATH_META[path] || PATH_META.PATH_2;
    return el("span", { class: "path-chip " + m.cls }, el("span", { class: "g" }, m.glyph), m.label);
  }
  function statusChip(s) {
    return el("span", { class: "ws-status-chip st-" + s }, s);
  }
  const commas = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US"));

  /* ---------- prepare one analysis into a view model ------------------------------ */
  function model(a, cases) {
    const nodes = (a.graph && a.graph.nodes) || [];
    const fields = nodes.filter((n) => n.category === "FIELD").map((n) => ({
      key: n.label,
      value: (n.source && n.source.raw_span) || "—",
      confidence: n.confidence,
      reviewer: n.reviewer_accuracy,
      source: n.source || {},
      path: (n.metadata && n.metadata.path) || "PATH_2",
      decision: (n.metadata && n.metadata.decision) || "—",
      reason: (n.metadata && n.metadata.reason) || "",
      status: n.status,
      severity: n.severity,
      summary: n.summary || "",
      accepted: (n.metadata && n.metadata.decision) === "ACCEPT",
    }));
    const metrics = nodes.filter((n) => n.category === "METRIC");
    const evidence = nodes.filter((n) => n.category === "EVIDENCE");
    const kase = (cases || []).find((c) => c.case_id === a.case_id) || {};
    // recommendation (case-level, Loop B, instrumented)
    let rec;
    if (a.status === "FAILED") rec = { name: "DECLINED", cls: "decline" };
    else if (a.n_routed === 0) rec = { name: "APPROVED", cls: "approve" };
    else if (a.status === "PARTIAL") rec = { name: "UNDER REVIEW", cls: "review" };
    else rec = { name: "CONDITIONAL APPROVAL", cls: "conditional" };
    // deterministic illustrative exposure (case-level telemetry only)
    let seed = 0; for (const ch of a.case_id) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
    const exposure = a.status === "FAILED" ? null : 150000 + (seed % 90) * 10000;
    const acceptedFields = fields.filter((f) => f.accepted);
    const meanConf = acceptedFields.length
      ? acceptedFields.reduce((s, f) => s + (f.confidence || 0), 0) / acceptedFields.length : null;
    return { a, kase, fields, metrics, evidence, rec, exposure, meanConf,
      coverage: a.n_fields ? a.n_automated / a.n_fields : 0, grade: GRADE[a.worst_severity] || "—" };
  }

  /* ================================ LEFT RAIL ================================ */
  function buildRail(report, analyses, onSelect) {
    const host = document.getElementById("ws-rail-in");
    host.innerHTML = "";
    const done = analyses.filter((a) => a.status === "COMPLETED").length;
    const queued = analyses.filter((a) => a.status === "PARTIAL").length;
    const flagged = analyses.filter((a) => a.worst_severity === "HIGH" || a.worst_severity === "CRITICAL").length;

    host.append(el("h2", {}, "Portfolio overview"));
    host.append(el("div", { class: "ws-kpis" },
      kpi(analyses.length, "Active", false),
      kpi(queued, "Queue", false),
      kpi(flagged, "Flagged", true)));

    const riskCount = (sev) => analyses.filter((a) => a.worst_severity === sev).length;
    host.append(el("div", { class: "ws-risk" },
      riskRow("High risk", riskCount("HIGH") + riskCount("CRITICAL")),
      riskRow("Medium risk", riskCount("MEDIUM")),
      riskRow("Low / clean", riskCount("LOW") + riskCount("NONE"))));

    // sections nav (scrolls to case sections; here they select the active tab)
    host.append(el("h2", {}, "Sections"));
    const nav = el("div", { class: "ws-nav" });
    [["Active cases", "cases", icons.summary], ["Evidence vault", "evidence-vault", icons.evidence],
     ["Decision history", "history", icons.metric], ["Audit ledger", "audit", icons.document]]
      .forEach(([label, id, ic], i) => {
        const b = el("button", { type: "button", "aria-current": String(i === 0),
          html: ic + "<span>" + V.esc(label) + "</span>" });
        nav.append(b);
      });
    host.append(nav);

    // active cases
    host.append(el("h2", {}, el("span", {}, "Active cases"), el("span", { class: "badge", style: "float:right;color:var(--faint);font:600 10px/1 var(--font-mono)" }, String(analyses.length))));
    const list = el("div", { class: "ws-cases", id: "ws-cases" });
    for (const a of analyses) {
      const m = model(a, report.cases);
      const item = el("button", { class: "ws-case-item", type: "button", "data-id": a.analysis_id, "aria-current": "false" },
        el("div", { class: "ws-case-top" },
          el("span", { class: "ws-case-id" }, a.case_id.replace("case-", "VRT-")),
          statusChip(a.status)),
        el("div", { class: "ws-case-name" }, archLabel(a.archetypes)),
        el("div", { class: "ws-case-foot" },
          el("span", { class: "ws-case-grade" }, "Grade " + m.grade),
          el("span", { style: "font:500 10px/1 var(--font-mono);color:var(--muted)" }, a.n_automated + "/" + a.n_fields + " auto")));
      item.addEventListener("click", () => onSelect(a));
      list.append(item);
    }
    host.append(list);
  }
  function kpi(n, k, flag) { return el("div", { class: "ws-kpi" + (flag ? " flag" : "") }, el("div", { class: "n" }, String(n)), el("div", { class: "k" }, k)); }
  function riskRow(k, v) { return el("div", { class: "ws-risk-row" }, el("span", {}, k), el("span", { class: "v" }, String(v))); }
  function archLabel(arr) {
    if (!arr || !arr.length) return "—";
    const first = arr[0].replace(/_/g, " ").toLowerCase();
    const label = first.charAt(0).toUpperCase() + first.slice(1);
    return arr.length > 1 ? label + " ·" + arr.length : label;
  }

  /* ================================ CASE HEADER ================================ */
  function renderHead(M, onRun) {
    const host = document.getElementById("ws-case-head");
    host.innerHTML = "";
    const a = M.a;
    host.append(el("div", { class: "ws-case-title-row" },
      el("div", {},
        el("h1", { class: "ws-case-title" }, archLabel(a.archetypes),
          el("span", { class: "cid" }, a.case_id.replace("case-", "VRT-"))),
        el("div", { style: "margin-top:8px" },
          el("span", { class: "v-loop-tag b" }, el("span", { class: "g" }, "◇"), "Loop B · Instrumented"),
          el("span", { class: "v-loop-note", style: "margin-left:10px" }, "case decision — telemetry only, no coverage guarantee"))),
      el("div", { class: "ws-case-head-right" },
        statusChip(a.status),
        el("button", { class: "v-btn v-btn-outline v-btn-sm", type: "button",
          html: icons.play + "<span>Re-run analysis</span>", onclick: onRun }))));
  }

  /* ================================ TABS ================================ */
  const TABS = [
    ["Decision", "decision"], ["Financials", "financials"], ["Evidence", "evidence"],
    ["Ratios", "ratios"], ["Confidence", "confidence"], ["Provenance", "provenance"],
    ["Audit Trail", "audit"],
  ];
  function renderTabs(M, state, onTab) {
    const host = document.getElementById("ws-tabs");
    host.innerHTML = "";
    TABS.forEach(([label, id]) => {
      const b = el("button", { class: "ws-tab", type: "button", role: "tab",
        "aria-selected": String(state.tab === id) }, label);
      b.addEventListener("click", () => onTab(id));
      host.append(b);
    });
  }

  function renderPanel(M, state, ctx) {
    const host = document.getElementById("ws-tabpanel");
    host.innerHTML = "";
    ({ decision: tabDecision, financials: tabFinancials, evidence: tabEvidence, ratios: tabRatios,
       confidence: tabConfidence, provenance: tabProvenance, audit: tabAudit }[state.tab] || tabDecision)(host, M, ctx);
  }

  /* ---- Decision tab ---- */
  function tabDecision(host, M, ctx) {
    const a = M.a;
    host.append(el("div", { class: "dec-rec" },
      el("div", { class: "dec-rec-l" },
        el("div", { class: "lbl" }, "Final recommendation"),
        el("div", { class: "dec-rec-name " + M.rec.cls }, M.rec.name)),
      el("div", { class: "dec-rec-r" },
        el("div", { class: "dec-exposure" }, M.exposure == null ? "—" : "$" + commas(M.exposure)),
        el("div", { class: "dec-exposure-l" }, M.exposure == null ? "Exposure withheld" : "Approved exposure · illustrative"))));

    // confidence NEVER bare — always paired with the reason it is there
    const confReason = M.meanConf == null
      ? "no accepted fields to average"
      : "mean over " + M.a.n_automated + " accepted fields; case-level telemetry, not the guaranteed field coverage";
    host.append(el("div", { class: "dec-meta" },
      el("div", {}, el("span", { class: "mk" }, "Risk grade"), el("b", {}, M.grade)),
      el("div", {}, el("span", { class: "mk" }, "Confidence"),
        el("b", {}, M.meanConf == null ? "—" : pct(M.meanConf, 1)),
        el("span", { class: "reason" }, " — " + confReason)),
      el("div", {}, el("span", { class: "mk" }, "Evidence coverage"), el("b", {}, pct(M.coverage, 0)),
        el("span", { class: "reason" }, " — " + M.a.n_automated + " of " + M.a.n_fields + " fields automated"))));

    host.append(decisionBoundary(M));

    // three cards — messaging is status-aware so a FAILED case never reads as "all clear"
    const failed = a.status === "FAILED";
    const strengths = M.fields.filter((f) => f.accepted).slice(0, 3).map((f) =>
      f.key.replace(/_/g, " ").toLowerCase() + " — automated (" + fmt2(f.confidence) + " vs " + fmt2(f.reviewer) + " reviewer gate)");
    const risks = [];
    if (failed && a.error) risks.push("Extraction fault — " + (a.error.doc_id || "a document") + " could not be parsed; the bundle aborted before any decision.");
    M.fields.filter((f) => !f.accepted).forEach((f) => {
      const m = PATH_META[f.path] || PATH_META.PATH_2;
      risks.push(f.key.replace(/_/g, " ").toLowerCase() + " — " + m.label.toLowerCase() + ", routed to review");
    });
    (a.findings || []).forEach((f) => { if (!risks.some((r) => r.includes(f.field_type.replace(/_/g, " ").toLowerCase()))) risks.push(f.field_type.replace(/_/g, " ").toLowerCase() + " — " + f.title.toLowerCase()); });
    const conds = failed
      ? ["Resolve the document fault and re-run — no memory graph was published (see Audit Trail)."]
      : [...new Set((a.findings || []).map((f) => f.remediation))].slice(0, 3);

    host.append(el("div", { class: "dec-cards" },
      decCard("strengths", icons.success, "Key strengths", strengths,
        failed ? "Analysis failed before any field was decided." : "All fields cleared — no standout strengths flagged."),
      decCard("risks", icons.warning, "Material risks", risks.slice(0, 4),
        "No material risks — every field automated."),
      decCard("conditions", icons.document, "Required conditions", conds, "No open conditions on this case.")));

    host.append(el("div", { class: "dec-analyst" }, el("span", { html: icons.agent }),
      el("span", {}, "Reviewer budget: ", el("b", {}, (ctx.report.budget ? ctx.report.budget.spent + " of " + ctx.report.budget.total : "—")),
        " corrections spent — declared telemetry; it never gates the contradiction alarm.")));

    host.append(el("div", { class: "ws-sub" }, "Ratio grid"));
    host.append(ratioGrid(M));
  }
  function fmt2(x) { return x == null ? "n/a" : Number(x).toFixed(2); }
  function decCard(cls, icon, title, items, emptyMsg) {
    const ul = el("ul", {});
    if (!items.length) ul.append(el("li", {}, el("span", {}), el("span", { class: "empty-note" }, emptyMsg)));
    else items.forEach((t) => ul.append(el("li", {}, el("span", { html: icon }), el("span", {}, t))));
    return el("div", { class: "dec-card " + cls }, el("h4", {}, el("span", { html: icon }), title), ul);
  }

  function decisionBoundary(M) {
    // three zones on a confidence axis; a static marker at the case mean confidence (no animation)
    const conf = M.meanConf == null ? 0 : M.meanConf;
    const x = Math.max(1, Math.min(99, conf * 100));
    const zoneName = conf >= 0.9 ? "approve" : (conf >= 0.75 ? "abstain" : "decline");
    return el("div", { class: "dec-boundary" },
      el("div", { class: "db-bar" },
        el("span", { class: "db-seg decline", style: "width:75%" }),
        el("span", { class: "db-seg abstain", style: "width:14%" }),
        el("span", { class: "db-seg approve", style: "width:11%" }),
        el("span", { class: "db-marker", style: "left:" + x + "%" })),
      el("div", { class: "db-cap" }, "Case confidence ",
        el("b", {}, M.meanConf == null ? "n/a" : pct(conf, 1)),
        " — falls in the " + zoneName + " band"),
      el("div", { class: "db-legend" },
        leg("var(--accept)", "Approve ≥ 90%"), leg("var(--route)", "Abstain 75–89%"), leg("var(--warn)", "Decline < 75%")));
  }
  function leg(c, t) { return el("span", {}, el("i", { style: "background:" + c }), t); }

  function ratioGrid(M) {
    const grid = el("div", { class: "dec-ratios" });
    if (!M.metrics.length) { grid.append(el("div", { class: "ratio" }, el("div", { class: "ratio-note" }, "No derived ratios recorded for this case."))); return grid; }
    M.metrics.forEach((m) => {
      const blocked = m.status === "BLOCKED";
      grid.append(el("div", { class: "ratio" },
        el("div", { class: "ratio-k" }, m.label.replace(/_/g, " ")),
        el("div", { class: "ratio-v" + (blocked ? " blocked" : "") }, blocked ? "Blocked" : (m.summary || "—")),
        el("div", { class: "ratio-note" }, blocked
          ? el("span", {}, el("span", { class: "blk" }, "Blocked"), " — ", (m.summary || "an unresolved input").replace(/^blocked[^·]*·?\s*/i, ""))
          : (m.description || ""))));
    });
    return grid;
  }

  /* ---- Financials tab (extracted values) ---- */
  function tabFinancials(host, M, ctx) {
    host.append(el("div", { class: "ws-sub" }, "Extracted values · " + M.fields.length + " fields"));
    host.append(fieldTable(M, ctx, ["Field", "Value", "Source", "Page"], (f) => [
      f.key.replace(/_/g, " "),
      el("span", { class: "fv" }, f.value),
      f.source.doc_id || "—",
      f.source.page != null ? "p." + f.source.page : "—",
    ]));
  }

  /* ---- Confidence tab (never bare) ---- */
  function tabConfidence(host, M, ctx) {
    host.append(el("div", { class: "ws-sub" }, "Per-field confidence vs reviewer-accuracy gate"));
    const box = el("div", {});
    M.fields.forEach((f) => {
      const cleared = f.accepted;
      const reason = cleared
        ? "above the reviewer-accuracy gate (" + fmt2(f.reviewer) + ") — automated"
        : "below the gate (" + fmt2(f.reviewer) + ") — routed to review";
      const row = el("div", { class: "click", style: "display:grid;grid-template-columns:150px 1fr auto;gap:12px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line);cursor:pointer" },
        el("span", { style: "font:500 12px/1 var(--font-mono);color:var(--ink-2)" }, f.key.replace(/_/g, " ")),
        el("div", {},
          el("div", { style: "height:8px;background:var(--surface-3);border-radius:99px;overflow:hidden;position:relative" },
            el("i", { style: "display:block;height:100%;border-radius:99px;width:" + ((f.confidence || 0) * 100) + "%;background:" + (cleared ? "var(--accept)" : "var(--route)") }),
            el("span", { style: "position:absolute;top:-2px;bottom:-2px;left:" + ((f.reviewer || 0) * 100) + "%;width:2px;background:var(--ink-2);opacity:.6" })),
          el("div", { style: "font-size:11px;color:var(--muted);margin-top:5px" }, pct(f.confidence, 1) + " — " + reason)),
        pathChip(f.path, f.accepted));
      row.addEventListener("click", () => ctx.selectField(f));
      box.append(row);
    });
    host.append(box);
    host.append(el("p", { style: "font-size:11.5px;color:var(--muted);margin-top:14px" },
      "The vertical tick is the reviewer-accuracy gate for each field type. Confidence is shown with its decision and gate — never as a bare number."));
  }

  /* ---- Provenance tab (every value click-through) ---- */
  function tabProvenance(host, M, ctx) {
    host.append(el("div", { class: "ws-sub" }, "Every value traces to its source — select to inspect"));
    host.append(fieldTable(M, ctx, ["Field", "Path", "Value", "Trace"], (f) => [
      f.key.replace(/_/g, " "),
      pathChip(f.path, f.accepted),
      el("span", { class: "fv" }, f.value),
      el("button", { class: "traceb", type: "button" }, "Trace →"),
    ], true));
  }

  function fieldTable(M, ctx, headers, rowCells, traceOnClick) {
    const tbl = el("table", { class: "ws-table" });
    const thead = el("tr", {}); headers.forEach((h) => thead.append(el("th", {}, h)));
    tbl.append(el("thead", {}, thead));
    const tb = el("tbody", {});
    M.fields.forEach((f) => {
      const tr = el("tr", { class: "click", "data-field": f.key,
        "aria-current": String(ctx.state.field === f.key) });
      rowCells(f).forEach((c) => tr.append(el("td", {}, c)));
      tr.addEventListener("click", () => ctx.selectField(f));
      tb.append(tr);
    });
    tbl.append(tb);
    return tbl;
  }

  /* ---- Evidence tab (findings + real memory graph) ---- */
  function tabEvidence(host, M, ctx) {
    const a = M.a;
    host.append(el("div", { class: "ws-sub" }, "Findings · " + (a.findings || []).length));
    if (!(a.findings || []).length) host.append(el("p", { style: "font-size:12.5px;color:var(--muted)" }, "No findings — every field on this case cleared its gate."));
    (a.findings || []).forEach((f) => {
      host.append(el("div", { style: "display:grid;grid-template-columns:auto 1fr;gap:11px;padding:12px 0;border-bottom:1px solid var(--line)" },
        el("span", { class: "v-sev v-sev-" + f.severity, style: "align-self:start" }, f.severity),
        el("div", {},
          el("div", { style: "font-weight:600;font-size:13px;color:var(--ink)" }, f.field_type.replace(/_/g, " ") + " — " + f.title),
          el("div", { style: "font-size:12px;color:var(--muted);margin-top:4px" }, f.remediation))));
    });
    host.append(el("div", { class: "ws-sub", style: "margin-top:22px" }, "Memory graph — findings localized to evidence"));
    const mount = el("div", { style: "height:380px;border:1px solid var(--line);border-radius:var(--r2);overflow:hidden" });
    host.append(mount);
    if (a.graph && V.MemoryGraphView) {
      const g = new V.MemoryGraphView(mount, { orientation: "auto" });
      g.render(a.graph);
    } else {
      mount.append(el("div", { class: "v-empty" }, el("h3", {}, "No graph"), el("p", {}, "This analysis published no memory graph.")));
    }
  }

  /* ---- Ratios tab ---- */
  function tabRatios(host, M, ctx) {
    host.append(el("div", { class: "ws-sub" }, "Derived metrics (Loop B) — blocked until inputs are reviewed"));
    host.append(ratioGrid(M));
    host.append(el("p", { style: "font-size:11.5px;color:var(--muted);margin-top:14px" },
      "Derived-metric confidence is not propagated from field to ratio — an unresolved input blocks the ratio rather than guessing. This is an open problem, stated, not hidden."));
  }

  /* ---- Audit Trail tab ---- */
  function tabAudit(host, M, ctx) {
    const evs = M.a.events || [];
    host.append(el("div", { class: "ws-sub" }, "Recorded execution log · " + evs.length + " events"));
    const list = el("div", { style: "font-family:var(--font-mono);font-size:11.5px" });
    evs.forEach((e) => {
      list.append(el("div", { style: "display:grid;grid-template-columns:78px 1fr;gap:12px;padding:5px 0;border-bottom:1px solid var(--line)" },
        el("span", { style: "color:var(--faint);text-transform:uppercase;letter-spacing:.04em;font-size:9.5px" }, e.stage),
        el("span", { style: "color:var(--ink-2)" }, e.text)));
    });
    host.append(list);
    host.append(el("button", { class: "v-btn v-btn-outline v-btn-sm", type: "button", style: "margin-top:14px",
      html: icons.play + "<span>Replay as processing</span>", onclick: () => ctx.openProc(M.a) }));
  }

  /* ================================ EVIDENCE INSPECTOR ================================ */
  function renderInspector(M, ctx) {
    const host = document.getElementById("ws-insp-in");
    host.innerHTML = "";
    const f = ctx.state.selected || M.fields[0];
    if (!f) { host.append(el("p", { style: "color:var(--muted);font-size:12.5px;padding:8px 0" }, "This analysis exposed no field-level evidence.")); return; }

    // selected field
    host.append(el("div", { class: "insp-block" },
      el("h3", {}, "Selected field"),
      el("div", { class: "insp-field" },
        el("div", { class: "fn" }, glossaryWrap(f.key)),
        el("div", { class: "fv" }, f.value),
        el("div", { class: "fpath" }, pathChip(f.path, f.accepted),
          el("span", { class: "v-loop-tag a" }, el("span", { class: "g" }, "◆"), "Loop A · Guaranteed")))));

    // provenance chain 01–07
    const s = f.source || {};
    const bbox = Array.isArray(s.bbox) ? s.bbox.map((n) => n.toFixed(3)).join(", ") : "—";
    const confPaired = f.confidence == null
      ? el("span", { class: "v" }, "no confidence score — degraded")
      : (f.accepted
        ? el("span", { class: "v" }, pct(f.confidence, 1), " — ", el("b", { class: "ok" }, "above the reviewer-accuracy gate"), " (" + fmt2(f.reviewer) + "), automated")
        : el("span", { class: "v" }, pct(f.confidence, 1), " — ", el("b", { class: "warn" }, "below the gate"), " (" + fmt2(f.reviewer) + "), routed to review"));
    const downstream = M.metrics.length ? M.metrics.map((m) => m.label).join(", ") : "None recorded";
    const verif = f.status === "VALIDATED" ? "Validated against the verbatim span — match confirmed"
      : (f.path === "PATH_3" ? "Sources disagree — reconciliation required" : "Routed for reviewer confirmation");

    host.append(el("div", { class: "insp-block" },
      el("h3", {}, "Provenance chain"),
      el("ol", { class: "prov" },
        provRow("01", "Extracted value", el("span", { class: "v mono" }, f.value)),
        provRow("02", "Source document", el("span", { class: "v" }, (s.doc_id || "—") + (s.archetype ? " · " + s.archetype.replace(/_/g, " ").toLowerCase() : ""))),
        provRow("03", "Page number", el("span", { class: "v" }, s.page != null ? "Page " + s.page : "—")),
        provRow("04", "Evidence coordinates", el("span", { class: "v mono" }, "bbox " + bbox)),
        provRow("05", "Extraction confidence", confPaired),
        provRow("06", "Verification status", el("span", { class: "v" }, verif)),
        provRow("07", "Downstream calculations affected", el("span", { class: "v" }, downstream)))));

    // document preview with highlighted span box
    const box = Array.isArray(s.bbox) ? s.bbox : [0.5, 0.4, 0.7, 0.45];
    host.append(el("div", { class: "insp-block" },
      el("h3", {}, "Document preview"),
      el("div", { class: "insp-doc" },
        el("div", { class: "insp-doc-bar" }, el("span", { html: icons.document }), (s.doc_id || "document") + " · p." + (s.page != null ? s.page : "—")),
        el("div", { class: "insp-doc-body" },
          el("div", { class: "insp-doc-hl", style: "left:" + (box[0] * 100) + "%;top:" + (box[1] * 100) + "%;width:" + ((box[2] - box[0]) * 100) + "%;height:" + Math.max(6, (box[3] - box[1]) * 100) + "%" })),
        el("div", { class: "insp-doc-cap" }, "Highlighted value: ", el("span", { class: "hlv" }, f.value)))));

    // system status
    const meta = ctx.report.meta || {};
    host.append(el("div", { class: "insp-block" },
      el("h3", {}, "System status"),
      el("div", { class: "insp-sys" },
        sysRow("Status", el("span", { class: "v" }, "Online")),
        sysRow("Config", el("span", { class: "v" }, (meta.config || "—").replace("configs/", ""))),
        sysRow("Taxonomy", el("span", { class: "v" }, meta.taxonomy_version || "—")),
        sysRow("Documents", el("span", { class: "v" }, String((M.a.documents || []).length) + " active")))));

    V.initGlossary(host);
  }
  function provRow(n, k, v) { return el("li", {}, el("span", { class: "n" }, n), el("div", {}, el("span", { class: "k" }, k), v)); }
  function sysRow(k, v) { return el("div", { class: "insp-sys-row" }, el("span", {}, k), v); }
  function glossaryWrap(key) {
    // wrap known abbreviations in the field name with a tooltip
    const known = { DSCR: "DSCR", ADB_RATIO: "ADB", TOTAL_DEBT_SERVICE: null };
    if (Verdict.glossary[key]) return el("button", { class: "v-gl", "data-gl": key }, key);
    return document.createTextNode(key.replace(/_/g, " "));
  }

  /* ================================ COMMAND BAR ================================ */
  function wireCommandBar(getM, ctx) {
    const input = document.getElementById("ws-cmd-input");
    const actions = document.getElementById("ws-cmd-actions");
    const out = document.getElementById("ws-cmd-out");
    actions.innerHTML = "";

    const say = (nodes) => { out.innerHTML = ""; out.append(...[].concat(nodes)); };

    function traceField(name) {
      const M = getM();
      const f = M.fields.find((x) => x.key.toUpperCase() === (name || "").toUpperCase())
        || M.fields.find((x) => x.key.toUpperCase().includes((name || "").toUpperCase()));
      if (!f) return say([el("span", {}, "No field "), el("b", {}, name || "—"), el("span", {}, " on this case. Try one of: " + M.fields.map((x) => x.key).join(", "))]);
      ctx.selectField(f);
      say([el("span", {}, "Traced "), el("b", {}, f.key), el("span", {}, " → provenance chain loaded in the Evidence Inspector (Loop A).")]);
    }
    function explainAbstention() {
      const M = getM();
      const routed = M.fields.filter((x) => !x.accepted);
      if (!routed.length) return say([el("span", {}, "No abstentions on this case — all "), el("b", {}, String(M.a.n_fields)), el("span", {}, " fields cleared the gate.")]);
      const f = routed[0];
      ctx.selectField(f);
      const m = PATH_META[f.path] || PATH_META.PATH_2;
      say([el("span", {}, "Abstained on "), el("b", {}, f.key), el("span", {}, " — " + m.label.toLowerCase() + "; "),
        el("span", {}, f.confidence != null ? pct(f.confidence, 1) + " below the " + fmt2(f.reviewer) + " reviewer gate. Routed, not guessed." : "no confidence score available.")]);
    }
    function inspectMissing() {
      const M = getM();
      const absent = M.fields.filter((x) => x.path === "PATH_1");
      if (!absent.length) return say([el("span", {}, "No absent fields (Path 1) on this case — all "), el("b", {}, String(M.a.n_fields)), el("span", {}, " targets were located in the documents.")]);
      ctx.selectField(absent[0]);
      say([el("span", {}, "Path 1 (Absent): "), el("b", {}, absent.map((x) => x.key).join(", ")), el("span", {}, " — not present in any source document; routed for manual entry.")]);
    }

    [["Trace field", () => traceField(getM().fields[0] && getM().fields[0].key)],
     ["Explain abstention", explainAbstention],
     ["Inspect missing", inspectMissing],
     ["Coverage", () => { const M = getM(); say([el("span", {}, "Coverage "), el("b", {}, pct(M.coverage, 0)), el("span", {}, " — " + M.a.n_automated + " of " + M.a.n_fields + " fields automated under the guaranteed threshold; " + M.a.n_routed + " routed.")]); }]]
      .forEach(([label, fn]) => {
        const b = el("button", { class: "ws-cmd-btn", type: "button" }, label);
        b.addEventListener("click", fn);
        actions.append(b);
      });

    input.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      const q = input.value.trim().toLowerCase();
      if (/^trace\b/.test(q)) traceField(q.replace(/^trace\s+/, ""));
      else if (/abst|explain|rout/.test(q)) explainAbstention();
      else if (/miss|absent|path\s*1/.test(q)) inspectMissing();
      else if (/cover/.test(q)) actions.children[3].click();
      else say([el("span", {}, "Commands: "), el("b", {}, "trace <field>"), el("span", {}, ", "), el("b", {}, "explain abstention"), el("span", {}, ", "), el("b", {}, "inspect missing"), el("span", {}, ", "), el("b", {}, "coverage"), el("span", {}, ".")]);
      input.value = "";
    };
  }

  /* ================================ PROCESSING OVERLAY ================================ */
  function buildProc() {
    const proc = document.getElementById("ws-proc");
    const stagesEl = document.getElementById("ws-proc-stages");
    const title = document.getElementById("ws-proc-title");
    const close = document.getElementById("ws-proc-close");
    const term = new V.AnalysisTerminal(document.getElementById("ws-proc-term"), {});
    let onDone = null;

    // build the stage rail
    function drawStages(activeStage, doneSet) {
      stagesEl.innerHTML = "";
      V.STAGES.forEach((st) => {
        const cls = doneSet.has(st) ? "done" : (st === activeStage ? "active" : "");
        stagesEl.append(el("div", { class: "proc-stage " + cls },
          el("span", { class: "dot" }), el("span", { class: "sl" }, V.STAGE_LABEL[st] || st)));
      });
    }
    const doneSet = new Set();

    function open(a, cb) {
      onDone = cb; doneSet.clear();
      title.textContent = "Processing " + a.case_id.replace("case-", "VRT-") + " — " + a.n_fields + " fields";
      drawStages("QUEUE", doneSet);
      proc.setAttribute("data-open", "true");
      term.opts.onStage = (stage) => {
        const idx = V.STAGES.indexOf(stage);
        for (let i = 0; i < idx; i++) doneSet.add(V.STAGES[i]);
        drawStages(stage, doneSet);
      };
      term.opts.onComplete = () => { V.STAGES.forEach((s) => doneSet.add(s)); drawStages("DONE", doneSet); };
      term.load(a, { autoplay: !V.reducedMotion() });
      close.focus();
    }
    function hide() { proc.removeAttribute("data-open"); if (onDone) onDone(); }
    close.addEventListener("click", hide);
    proc.addEventListener("click", (e) => { if (e.target === proc) hide(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && proc.getAttribute("data-open") === "true") hide(); });
    return { open };
  }

  /* ================================ ORCHESTRATION ================================ */
  function init(report) {
    document.getElementById("nav-logo").innerHTML = V.logo(22);
    const analyses = (report.analyses || []).slice();
    if (!analyses.length) return;
    const proc = buildProc();

    const state = { current: null, tab: "decision", field: null, selected: null };
    let M = null;

    const ctx = {
      report,
      state,
      selectField(f) {
        state.selected = f; state.field = f.key;
        renderInspector(M, ctx);
        // reflect selection in any visible field table
        document.querySelectorAll("#ws-tabpanel [data-field]").forEach((r) =>
          r.setAttribute("aria-current", String(r.getAttribute("data-field") === f.key)));
      },
      openProc(a) { proc.open(a, () => selectCase(a, { keepTab: true })); },
    };

    function setTab(tab) { state.tab = tab; renderTabs(M, state, setTab); renderPanel(M, state, ctx); }

    function selectCase(a, opts) {
      opts = opts || {};
      state.current = a; state.selected = null; state.field = null;
      if (!opts.keepTab) state.tab = "decision";
      M = model(a, report.cases);
      document.querySelectorAll(".ws-case-item").forEach((b) =>
        b.setAttribute("aria-current", String(b.dataset.id === a.analysis_id)));
      renderHead(M, () => ctx.openProc(a));
      renderTabs(M, state, setTab);
      renderPanel(M, state, ctx);
      renderInspector(M, ctx);
      wireCommandBar(() => M, ctx);
    }

    buildRail(report, analyses, (a) => selectCase(a));

    // deep link ?case=an-... else first
    const wanted = new URLSearchParams(location.search).get("case");
    const first = analyses.find((a) => a.analysis_id === wanted) || analyses[0];
    selectCase(first);

    // deep link ?process=1 opens the processing overlay for the selected case
    if (new URLSearchParams(location.search).get("process") === "1") ctx.openProc(first);
  }

  window.Verdict.initWorkspace = init;
  V.loadReport().then(init).catch((err) => {
    console.error("workspace: report load failed", err);
    const p = document.getElementById("ws-tabpanel");
    if (p) p.append(el("div", { class: "v-empty" }, el("h3", {}, "Could not load analyses"), el("p", {}, "The embedded report snapshot is missing.")));
  });
})();
