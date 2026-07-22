/* Analysis workspace orchestrator — wires the file rail, terminal, and memory graph to the
   real analysis lifecycle: select a file → terminal replays the recorded run → the memory
   graph becomes available only when the analysis reaches a terminal state → it fits to view.
   A FAILED analysis publishes no graph and the graph pane says so. */
(function () {
  "use strict";
  const V = window.Verdict;
  const el = V.el, icons = V.icons;

  function severityChip(sev) {
    if (!sev || sev === "NONE") return el("span", { class: "v-sev v-sev-NONE ws-file-sev" }, "CLEAN");
    return el("span", { class: "v-sev v-sev-" + sev + " ws-file-sev" }, sev);
  }

  function init(report) {
    const analyses = (report.analyses || []).slice();
    const railEl = document.getElementById("ws-files");
    const terminalMount = document.getElementById("ws-terminal");
    const graphMount = document.getElementById("ws-graph");
    if (!railEl || !terminalMount || !graphMount) return;

    // KPIs from the real report.
    const done = analyses.filter((a) => a.status !== "FAILED").length;
    setText("ws-kpi-files", analyses.length);
    setText("ws-kpi-graphs", analyses.filter((a) => a.graph).length);
    const cov = report.coverage && report.coverage.overall;
    if (cov) setText("ws-kpi-auto", V.fmt.pct(cov.realized_coverage, 0));

    const terminal = new V.AnalysisTerminal(terminalMount, {
      onComplete: (a) => showGraph(a),
    });
    const graph = new V.MemoryGraphView(graphMount, { orientation: "auto" });

    let current = null;

    function showGraph(a) {
      if (a !== current) return;
      if (a.status === "FAILED" || !a.graph) {
        graph.setState("error", "This analysis failed before any decisions were issued, so no memory graph was published. Resolve the document fault and re-run.");
        return;
      }
      graph.render(a.graph);
    }

    function select(a, { autoplay } = {}) {
      current = a;
      for (const btn of railEl.querySelectorAll(".ws-file"))
        btn.setAttribute("aria-current", String(btn.dataset.id === a.analysis_id));
      terminal.load(a, { autoplay });
      if (autoplay === false || V.reducedMotion()) showGraph(a);
      else graph.setState("loading", "The terminal is replaying the analysis. The memory graph appears the moment it completes.");
    }

    // Build the rail.
    for (const a of analyses) {
      const btn = el("button", { class: "ws-file", type: "button", "data-id": a.analysis_id,
        "aria-current": "false" },
        el("div", { class: "ws-file-top" }, el("span", { html: icons.file }),
          el("span", { class: "ws-file-name" }, a.file_label)),
        el("div", { class: "ws-file-sub" },
          el("span", { class: "ws-file-badge", "data-state": a.status }, a.status),
          el("span", {}, a.n_automated + "/" + a.n_fields + " auto"),
          severityChip(a.worst_severity)));
      btn.addEventListener("click", () => select(a, { autoplay: true }));
      railEl.append(btn);
    }

    // Deep-link support (?file=an-...), else the first analysis, rendered without autoplay so
    // the page is immediately useful; subsequent clicks replay.
    const params = new URLSearchParams(location.search);
    const wanted = params.get("file");
    const first = analyses.find((a) => a.analysis_id === wanted) || analyses[0];
    if (first) select(first, { autoplay: false });
    else {
      terminal.setState("empty");
      graph.setState("empty");
    }
  }

  function setText(id, v) { const n = document.getElementById(id); if (n) n.textContent = v; }

  window.Verdict.initWorkspace = init;
})();
