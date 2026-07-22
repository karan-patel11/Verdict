/* MemoryGraphView — renders one MemoryGraph into a mount element and owns its interaction
   state (viewport transform, selection, filters). A class is warranted here: persistent
   state + a lifecycle (mount → measure → layout → render → destroy) + event-listener
   cleanup. Layout/validation math lives in the pure engine (memory-graph.js); this file is
   DOM + interaction only.

   Rendering order that keeps every edge visibly connected:
     1. render nodes into the DOM at rough positions,
     2. MEASURE their real box sizes,
     3. run the layered layout with those measured sizes,
     4. place nodes and route SVG edges to the measured geometry,
     5. fit to viewport.
   Re-layout runs only when the graph data or orientation changes, never on pan/zoom. */
(function () {
  "use strict";
  const V = window.Verdict;
  const engine = V.graphEngine;
  const el = V.el;
  const icons = V.icons;
  const CAT = V.CATEGORY_META;

  const MIN_SCALE = 0.25, MAX_SCALE = 2.4, FIT_PAD = 48;

  class MemoryGraphView {
    constructor(mount, options) {
      this.mount = typeof mount === "string" ? document.querySelector(mount) : mount;
      this.opts = Object.assign({ orientation: "auto", onSelect: null }, options || {});
      this.graph = null;
      this.view = { nodes: [], edges: [] };
      this.layout = null;
      this.nodeEls = new Map();
      this.edgeEls = new Map();
      this.arrowEls = new Map();
      this.nodePos = new Map(); // id → positioning wrapper (owns the layout transform)
      this.selected = null;
      this.filters = { minSeverity: "NONE", affectedOnly: false };
      this.transform = { x: 0, y: 0, k: 1 };
      this.orientation = "LR";
      this._userAdjusted = false; // true once the user zooms/pans; suspends auto-refit
      this._cleanup = [];
      this._raf = 0;
      this._resizeObserver = null;
      this._resizeTimer = 0;
    }

    /* ---- lifecycle --------------------------------------------------------------- */
    setState(state, message) {
      this._teardownListeners();
      this.mount.innerHTML = "";
      this.mount.classList.remove("mg");
      const map = {
        loading: { icon: icons.spinner, h: "Analyzing file", p: message || "The agent is working through the bundle. The memory graph appears when the analysis completes." },
        empty: { icon: icons.file, h: "No graph yet", p: message || "Select a completed analysis to view its memory graph." },
        error: { icon: icons.error, h: "Graph unavailable", p: message || "This analysis did not finish, so no memory graph was published." },
      };
      const s = map[state] || map.empty;
      this.mount.append(
        el("div", { class: "mg mg-state" },
          el("div", { class: "v-empty", role: "status" },
            el("div", { html: s.icon }),
            el("h3", {}, s.h),
            el("p", {}, s.p)))
      );
    }

    render(graph) {
      const problems = engine.validateGraph(graph);
      if (problems.length) {
        // Dev-time surfacing; a malformed graph must never render as broken edges.
        console.warn("[MemoryGraphView] invalid graph — refusing to render:\n" + problems.join("\n"));
        this.setState("error", "The graph data failed validation and was not rendered.");
        return;
      }
      this.graph = graph;
      this._decideOrientation();
      this._buildChrome();
      this._applyFiltersAndLayout({ animate: true, fit: true });
    }

    destroy() {
      this._teardownListeners();
      if (this._resizeObserver) this._resizeObserver.disconnect();
      cancelAnimationFrame(this._raf);
      this.mount.innerHTML = "";
    }

    _teardownListeners() {
      this._cleanup.forEach((fn) => fn());
      this._cleanup = [];
    }
    _on(target, ev, fn, opts) {
      target.addEventListener(ev, fn, opts);
      this._cleanup.push(() => target.removeEventListener(ev, fn, opts));
    }

    _decideOrientation() {
      if (this.opts.orientation === "LR" || this.opts.orientation === "TB") {
        this.orientation = this.opts.orientation;
      } else {
        // Auto: wide viewports read left-to-right; narrow ones stack top-to-bottom.
        this.orientation = (this.mount.clientWidth || window.innerWidth) < 640 ? "TB" : "LR";
      }
    }

    /* ---- chrome (toolbar, viewport, legend) -------------------------------------- */
    _buildChrome() {
      this._teardownListeners();
      this.mount.className = "mg";
      this.mount.innerHTML = "";
      this.nodeEls.clear();
      this.nodePos.clear();
      this.edgeEls.clear();
      this.arrowEls.clear();

      const worstSev = this.graph.metadata.worst_severity;
      this.toolbar = el("div", { class: "mg-toolbar" },
        el("div", { class: "mg-title" },
          el("span", { html: icons.metric }),
          el("span", {}, "Memory graph"),
          worstSev && worstSev !== "NONE"
            ? el("span", { class: "v-sev v-sev-" + worstSev, title: "Worst finding severity" }, worstSev)
            : el("span", { class: "v-sev v-sev-NONE" }, "CLEAN")),
        el("div", { class: "mg-toolbar-spacer" }),
        this._buildSearch(),
        this._buildFilters(),
        this._buildControls());

      this.viewport = el("div", {
        class: "mg-viewport", tabindex: "0", role: "application",
        "aria-label": "Memory graph. Arrow keys pan, plus and minus zoom, F fits to view.",
      });
      this.world = el("div", { class: "mg-world" });
      this.edgeLayer = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      this.edgeLayer.setAttribute("class", "mg-edges");
      this.edgeLayer.setAttribute("aria-hidden", "true");
      this.world.append(this.edgeLayer);
      this.viewport.append(this.world);

      this.panel = el("aside", { class: "mg-panel", hidden: true, "aria-label": "Node details" });

      this.stage = el("div", { class: "mg-stage" }, this.viewport, this.panel);
      this.legend = this._buildLegend();
      this.mount.append(this.toolbar, this.stage, this.legend);

      this._wireViewport();
      this._wireKeyboard();
    }

    _buildSearch() {
      const input = el("input", {
        type: "search", placeholder: "Search nodes…", "aria-label": "Search graph nodes",
        autocomplete: "off", spellcheck: "false",
      });
      this._searchInput = input;
      this._on(input, "input", () => this._runSearch(input.value));
      this._on(input, "keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); this._selectFirstSearchHit(); }
      });
      return el("div", { class: "mg-search" }, el("span", { html: icons.search }), input);
    }

    _buildFilters() {
      const sev = el("select", { class: "mg-select", "aria-label": "Filter by minimum severity" },
        ...[["NONE", "All severities"], ["LOW", "Low +"], ["MEDIUM", "Medium +"],
            ["HIGH", "High +"], ["CRITICAL", "Critical only"]]
          .map(([v, t]) => el("option", { value: v }, t)));
      this._on(sev, "change", () => {
        this.filters.minSeverity = sev.value;
        this._applyFiltersAndLayout({ animate: false, fit: true });
      });
      const affected = el("button", {
        class: "mg-iconbtn", type: "button", "aria-pressed": "false",
        title: "Show only findings and the nodes they touch", "aria-label": "Show affected nodes only",
        html: icons.finding,
      });
      this._on(affected, "click", () => {
        this.filters.affectedOnly = !this.filters.affectedOnly;
        affected.setAttribute("aria-pressed", String(this.filters.affectedOnly));
        this._applyFiltersAndLayout({ animate: false, fit: true });
      });
      return el("div", { class: "mg-controls" }, sev, affected);
    }

    _buildControls() {
      const btn = (icon, label, fn, extra) => {
        const b = el("button", Object.assign({ class: "mg-iconbtn", type: "button", title: label, "aria-label": label, html: icons[icon] }, extra || {}));
        this._on(b, "click", fn);
        return b;
      };
      this._zoomLabel = el("span", { class: "mg-zoom-label", "aria-live": "off" }, "100%");
      this._orientBtn = btn(this.orientation === "LR" ? "chevron" : "down",
        "Toggle graph orientation", () => this._toggleOrientation());
      return el("div", { class: "mg-controls" },
        btn("zoomout", "Zoom out", () => this._zoomBy(1 / 1.2)),
        this._zoomLabel,
        btn("zoomin", "Zoom in", () => this._zoomBy(1.2)),
        btn("fit", "Fit to view", () => this.fit(true)),
        btn("reset", "Reset view", () => this._reset()),
        this._orientBtn);
    }

    _buildLegend() {
      const swatch = (varname) => el("span", { class: "mg-legend-sw", style: `background:var(${varname})` });
      const item = (varname, label) => el("span", { class: "mg-legend-item" }, swatch(varname), label);
      return el("div", { class: "mg-legend", role: "group", "aria-label": "Legend" },
        el("div", { class: "mg-legend-group" },
          item("--cat-structure", "Structure"),
          item("--cat-entity", "Field"),
          item("--cat-check", "Check"),
          item("--cat-insight", "Recommendation"),
          item("--cat-metric", "Derived (Loop B)")),
        el("span", { class: "mg-legend-sep" }),
        el("div", { class: "mg-legend-group" },
          item("--sev-low", "Low"),
          item("--sev-med", "Medium"),
          item("--sev-high", "High"),
          item("--sev-crit", "Critical")));
    }

    /* ---- filter → layout → render ------------------------------------------------ */
    _applyFiltersAndLayout({ animate, fit }) {
      this.view = engine.filterGraph(this.graph, this.filters);
      this._renderNodes(animate);
      // Measure after the browser has laid the nodes out, then route edges to real geometry.
      this._raf = requestAnimationFrame(() => {
        const sizes = this._measureNodes();
        this.layout = engine.layoutGraph(this.view, {
          sizes, orientation: this.orientation,
          colGap: this.orientation === "LR" ? 84 : 64,
          rowGap: this.orientation === "LR" ? 20 : 26,
        });
        this._placeNodes();
        this._renderEdges();
        if (fit) {
          this.fit(false);
          // Re-fit once the surrounding grid has finished reflowing (fonts, rail placement),
          // so the initial view uses the settled viewport rather than a mid-layout width.
          requestAnimationFrame(() => { if (!this._userAdjusted) this.fit(false); });
          setTimeout(() => { if (!this._userAdjusted) this.fit(false); }, 90);
        } else {
          this._applyTransform();
        }
        if (this.selected && !this.nodeEls.has(this.selected)) this._closePanel();
        this._refreshHighlight();
      });
    }

    _renderNodes(animate) {
      // Remove nodes no longer in view (drop their positioning wrapper).
      for (const [id, node] of this.nodeEls) {
        if (!this.view.nodes.find((n) => n.id === id)) {
          const pos = this.nodePos.get(id);
          if (pos) pos.remove(); else node.remove();
          this.nodeEls.delete(id); this.nodePos.delete(id);
        }
      }
      for (const n of this.view.nodes) {
        if (this.nodeEls.has(n.id)) continue;
        const node = this._nodeElement(n);
        if (animate && !V.reducedMotion()) node.classList.add("mg-node-entrance");
        const pos = el("div", { class: "mg-node-pos" }, node);
        this.world.append(pos);
        this.nodeEls.set(n.id, node);
        this.nodePos.set(n.id, pos);
      }
    }

    _nodeElement(n) {
      const meta = CAT[n.category] || { label: n.category, icon: "info", tone: "structure" };
      const statusLabel = this._statusText(n);
      const node = el("button", {
        class: "mg-node", type: "button", "data-id": n.id, "data-category": n.category,
        "data-tone": meta.tone, "data-severity": n.severity, "data-status": n.status,
        "aria-label": `${meta.label}: ${n.label}. ${statusLabel}. ${n.summary || ""}`,
      },
        el("div", { class: "mg-node-head" },
          el("span", { class: "mg-node-cat" }, el("span", { html: icons[meta.icon] }), meta.label),
          n.category === "FINDING"
            ? el("span", { class: "mg-node-sev v-sev v-sev-" + n.severity }, n.severity)
            : null),
        el("div", { class: "mg-node-label" }, n.label),
        n.summary ? el("div", { class: "mg-node-summary", html: this._summaryHtml(n) }) : null,
        el("div", { class: "mg-node-status" }, el("span", { class: "v-dot " + this._statusDot(n) }), statusLabel));
      this._on(node, "click", (e) => { e.stopPropagation(); this.select(n.id); });
      this._on(node, "mouseenter", () => { if (!this.selected) this._highlight(n.id); });
      this._on(node, "mouseleave", () => { if (!this.selected) this._clearHighlight(); });
      return node;
    }

    _summaryHtml(n) {
      // Render a leading quoted verbatim span in monospace so format artifacts stay visible.
      const s = n.summary || "";
      const m = s.match(/^“([^”]*)”\s*(.*)$/);
      if (m) return `<span class="v-mono">“${V.esc(m[1])}”</span> ${V.esc(m[2])}`;
      return V.esc(s);
    }

    _statusText(n) {
      return ({
        VALIDATED: "Automated", NEEDS_REVIEW: "Needs review", BLOCKED: "Blocked",
        FAILED: "Failed", RECOMMENDED: "Recommended", INFO: n.category === "METRIC" ? "Instrumented" : "Structural",
      })[n.status] || n.status;
    }
    _statusDot(n) {
      return ({ VALIDATED: "v-dot-ok", NEEDS_REVIEW: "v-dot-warn", BLOCKED: "v-dot-warn",
        FAILED: "v-dot-err", RECOMMENDED: "v-dot-run", INFO: "v-dot-idle" })[n.status] || "v-dot-idle";
    }

    _measureNodes() {
      // Measure the card's real box; positioning lives on the wrapper, so this is unaffected
      // by the card's own hover/entrance transforms.
      const sizes = {};
      for (const [id, node] of this.nodeEls) sizes[id] = { w: node.offsetWidth, h: node.offsetHeight };
      return sizes;
    }

    _placeNodes() {
      const { rects } = this.layout;
      for (const [id, pos] of this.nodePos) {
        const r = rects[id];
        if (!r) continue;
        pos.style.transform = `translate(${r.x}px, ${r.y}px)`;
      }
      this.edgeLayer.setAttribute("width", this.layout.size.width);
      this.edgeLayer.setAttribute("height", this.layout.size.height);
      this.mount.dataset.orientation = this.orientation; // for verification + CSS hooks
    }

    _renderEdges() {
      const NS = "http://www.w3.org/2000/svg";
      // Rebuild the edge layer; edges are cheap and always re-derived from measured geometry.
      while (this.edgeLayer.firstChild) this.edgeLayer.removeChild(this.edgeLayer.firstChild);
      this.edgeEls.clear();
      this.arrowEls.clear();
      const defs = document.createElementNS(NS, "defs");
      this.edgeLayer.append(defs);
      for (const e of this.view.edges) {
        const geo = engine.edgePath(this.layout.rects, e, this.orientation);
        if (!geo) continue;
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", geo.d);
        path.setAttribute("class", "mg-edge" + (e.relation === "BLOCKS" ? " is-blocks" : ""));
        path.setAttribute("data-source", e.source);
        path.setAttribute("data-target", e.target);
        this.edgeLayer.append(path);
        this.edgeEls.set(e.id, path);
        // Arrowhead as a small triangle oriented along the tangent at the target.
        const arrow = this._arrowMarker(geo, e);
        this.edgeLayer.append(arrow);
        this.arrowEls.set(e.id, { arrow, edge: e });
      }
    }

    _arrowMarker(geo, e) {
      const NS = "http://www.w3.org/2000/svg";
      const size = 5;
      let angle;
      if (this.orientation === "LR") angle = 0;
      else angle = 90;
      // Approximate incoming tangent using the last control direction.
      const dx = geo.x2 - geo.mx, dy = geo.y2 - geo.my;
      angle = (Math.atan2(dy, dx) * 180) / Math.PI;
      const tri = document.createElementNS(NS, "path");
      tri.setAttribute("d", `M0,0 L${-size * 1.6},${-size} L${-size * 1.6},${size} Z`);
      tri.setAttribute("transform", `translate(${geo.x2},${geo.y2}) rotate(${angle})`);
      tri.setAttribute("class", "mg-edge-arrow" + (e.relation === "BLOCKS" ? " is-blocks" : ""));
      tri.setAttribute("data-source", e.source);
      tri.setAttribute("data-target", e.target);
      return tri;
    }

    /* ---- viewport transform ------------------------------------------------------ */
    _applyTransform() {
      const t = this.transform;
      this.world.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.k})`;
      if (this._zoomLabel) this._zoomLabel.textContent = Math.round(t.k * 100) + "%";
    }
    _zoomBy(factor, cx, cy) {
      this._userAdjusted = true;
      const t = this.transform;
      const k = Math.min(MAX_SCALE, Math.max(MIN_SCALE, t.k * factor));
      const rect = this.viewport.getBoundingClientRect();
      const px = cx == null ? rect.width / 2 : cx;
      const py = cy == null ? rect.height / 2 : cy;
      // Zoom about the pointer so content under the cursor stays put.
      t.x = px - (px - t.x) * (k / t.k);
      t.y = py - (py - t.y) * (k / t.k);
      t.k = k;
      this._applyTransform();
    }
    fit(animate) {
      if (!this.layout) return;
      const rect = this.viewport.getBoundingClientRect();
      const { width, height } = this.layout.size;
      if (!width || !height || !rect.width || !rect.height) return;
      const k = Math.min(MAX_SCALE, Math.max(MIN_SCALE,
        Math.min((rect.width - FIT_PAD) / width, (rect.height - FIT_PAD) / height, 1.4)));
      this.transform.k = k;
      this.transform.x = (rect.width - width * k) / 2;
      this.transform.y = (rect.height - height * k) / 2;
      this._userAdjusted = false;
      if (animate && !V.reducedMotion()) {
        this.world.style.transition = "transform var(--dur-3) var(--ease)";
        setTimeout(() => { this.world.style.transition = ""; }, 380);
      }
      this._applyTransform();
    }
    _reset() {
      this.filters = { minSeverity: "NONE", affectedOnly: false };
      if (this._searchInput) this._searchInput.value = "";
      this._closePanel();
      this._clearHighlight();
      this.mount.querySelectorAll(".mg-select").forEach((s) => (s.value = "NONE"));
      this.mount.querySelectorAll('.mg-controls [aria-pressed="true"]').forEach((b) => b.setAttribute("aria-pressed", "false"));
      this._applyFiltersAndLayout({ animate: false, fit: true });
    }
    _toggleOrientation() {
      this.orientation = this.orientation === "LR" ? "TB" : "LR";
      this._orientBtn.innerHTML = this.orientation === "LR" ? icons.chevron : icons.down;
      this._applyFiltersAndLayout({ animate: false, fit: true });
    }

    _wireViewport() {
      let panning = false, sx = 0, sy = 0, ox = 0, oy = 0, moved = false;
      this._on(this.viewport, "pointerdown", (e) => {
        if (e.target.closest(".mg-node")) return;
        panning = true; moved = false;
        sx = e.clientX; sy = e.clientY; ox = this.transform.x; oy = this.transform.y;
        this.viewport.classList.add("is-panning");
        this.viewport.setPointerCapture(e.pointerId);
      });
      this._on(this.viewport, "pointermove", (e) => {
        if (!panning) return;
        this.transform.x = ox + (e.clientX - sx);
        this.transform.y = oy + (e.clientY - sy);
        if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 3) { moved = true; this._userAdjusted = true; }
        this._applyTransform();
      });
      const end = (e) => {
        if (!panning) return;
        panning = false; this.viewport.classList.remove("is-panning");
        try { this.viewport.releasePointerCapture(e.pointerId); } catch (_) {}
      };
      this._on(this.viewport, "pointerup", end);
      this._on(this.viewport, "pointercancel", end);
      this._on(this.viewport, "click", (e) => {
        if (!moved && !e.target.closest(".mg-node")) { this._closePanel(); this._clearHighlight(); }
      });
      this._on(this.viewport, "wheel", (e) => {
        e.preventDefault();
        const rect = this.viewport.getBoundingClientRect();
        this._zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - rect.left, e.clientY - rect.top);
      }, { passive: false });
      // On container resize: flip orientation if the auto breakpoint crossed (full re-layout),
      // otherwise keep the graph fit-to-view unless the user has manually zoomed or panned.
      // Debounced so a drag-resize doesn't thrash layout.
      if (window.ResizeObserver) {
        this._resizeObserver = new ResizeObserver(() => {
          clearTimeout(this._resizeTimer);
          this._resizeTimer = setTimeout(() => {
            if (!this.layout) return;
            if (this.opts.orientation === "auto") {
              const want = this.viewport.clientWidth < 640 ? "TB" : "LR";
              if (want !== this.orientation) {
                this.orientation = want;
                this._userAdjusted = false;
                this._applyFiltersAndLayout({ animate: false, fit: true });
                return;
              }
            }
            if (!this._userAdjusted) this.fit(false);
          }, 120);
        });
        this._resizeObserver.observe(this.viewport);
      }
    }

    _wireKeyboard() {
      this._on(this.viewport, "keydown", (e) => {
        const step = 48;
        const acts = {
          ArrowUp: () => (this.transform.y += step),
          ArrowDown: () => (this.transform.y -= step),
          ArrowLeft: () => (this.transform.x += step),
          ArrowRight: () => (this.transform.x -= step),
          "+": () => this._zoomBy(1.2), "=": () => this._zoomBy(1.2),
          "-": () => this._zoomBy(1 / 1.2), _: () => this._zoomBy(1 / 1.2),
          f: () => this.fit(true), F: () => this.fit(true),
          Escape: () => { this._closePanel(); this._clearHighlight(); },
        };
        if (acts[e.key]) { e.preventDefault(); acts[e.key](); if (!"fF".includes(e.key)) this._applyTransform(); }
      });
    }

    /* ---- selection + highlight --------------------------------------------------- */
    select(id) {
      const n = this.view.nodes.find((x) => x.id === id) || this.graph.nodes.find((x) => x.id === id);
      if (!n) return;
      this.selected = id;
      this._highlight(id);
      this._openPanel(n);
      for (const [nid, node] of this.nodeEls) node.classList.toggle("selected", nid === id);
      this._ensureVisible(id);
      if (typeof this.opts.onSelect === "function") this.opts.onSelect(n);
    }

    _highlight(id) {
      const conn = engine.connectedIds(this.view, id);
      for (const [nid, node] of this.nodeEls) {
        const on = conn.all.has(nid);
        node.classList.toggle("dim", !on);
        node.classList.toggle("hot", on && nid !== id);
      }
      for (const [eid, path] of this.edgeEls) {
        const e = this.view.edges.find((x) => x.id === eid);
        const on = conn.all.has(e.source) && conn.all.has(e.target);
        path.classList.toggle("dim", !on);
        path.classList.toggle("hot", on);
        const a = this.arrowEls.get(eid);
        if (a) { a.arrow.classList.toggle("dim", !on); a.arrow.classList.toggle("hot", on); }
      }
    }
    _clearHighlight() {
      if (this.selected) return;
      for (const node of this.nodeEls.values()) node.classList.remove("dim", "hot");
      for (const path of this.edgeEls.values()) path.classList.remove("dim", "hot");
      for (const a of this.arrowEls.values()) a.arrow.classList.remove("dim", "hot");
    }
    _refreshHighlight() {
      if (this.selected && this.nodeEls.has(this.selected)) this._highlight(this.selected);
      else this._clearHighlight();
    }

    _ensureVisible(id) {
      const r = this.layout && this.layout.rects[id];
      if (!r) return;
      const rect = this.viewport.getBoundingClientRect();
      const t = this.transform;
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      const sx = cx * t.k + t.x, sy = cy * t.k + t.y;
      const m = 40;
      if (sx < m) t.x += m - sx; else if (sx > rect.width - m) t.x -= sx - (rect.width - m);
      if (sy < m) t.y += m - sy; else if (sy > rect.height - m) t.y -= sy - (rect.height - m);
      this._applyTransform();
    }

    /* ---- details panel ----------------------------------------------------------- */
    _openPanel(n) {
      const meta = CAT[n.category] || { label: n.category, icon: "info" };
      const rows = [];
      const row = (h, body) => rows.push(el("div", { class: "mg-panel-row" }, el("h4", {}, h), body));

      if (n.summary) row("Summary", el("p", { html: this._summaryHtml(n) }));
      if (n.description) row("Detail", el("p", {}, n.description));

      const meta2 = [];
      const md = (dt, dd) => { meta2.push(el("dt", {}, dt), el("dd", { class: dd.mono ? "v-mono" : "" }, dd.text)); };
      md("Type", { text: meta.label });
      md("Status", { text: this._statusText(n) });
      if (n.severity && n.severity !== "NONE") meta2.push(el("dt", {}, "Severity"), el("dd", {}, el("span", { class: "v-sev v-sev-" + n.severity }, n.severity)));
      if (n.confidence != null) md("Confidence", { text: n.confidence.toFixed(3) + (n.reviewer_accuracy != null ? ` vs reviewer ${n.reviewer_accuracy.toFixed(2)}` : ""), mono: true });
      if (n.metadata && n.metadata.reason) md("Reason code", { text: n.metadata.reason, mono: true });
      if (n.metadata && n.metadata.loop) md("Loop", { text: n.metadata.loop + (n.metadata.guaranteed === false ? " — instrumented" : "") });
      if (meta2.length) row("Attributes", el("dl", { class: "mg-meta-grid" }, ...meta2));

      if (n.source && n.source.doc_id) {
        row("Source", this._evidenceCard(n.source));
      }
      if (n.remediation) row("Recommended action", el("div", { class: "mg-remediation" }, n.remediation));

      // Related nodes: direct neighbors, grouped, clickable.
      const related = this._relatedNodes(n.id);
      if (related.length) {
        row("Connected", el("div", { class: "mg-related" },
          ...related.map((r) => {
            const b = el("button", { type: "button" },
              el("span", { html: icons[(CAT[r.category] || {}).icon || "info"] }),
              el("span", {}, r.label),
              el("span", { class: "cat" }, (CAT[r.category] || {}).label || r.category));
            this._on(b, "click", () => this.select(r.id));
            return b;
          })));
      }

      this.panel.innerHTML = "";
      const close = el("button", { class: "mg-panel-close", type: "button", "aria-label": "Close details", html: icons.error });
      this._on(close, "click", () => this._closePanel());
      this.panel.append(
        el("div", { class: "mg-panel-head" },
          el("div", { style: "flex:1" },
            el("div", { class: "mg-node-cat", style: "margin-bottom:4px" }, el("span", { html: icons[meta.icon] }), meta.label),
            el("div", { class: "mg-panel-title" }, n.label)),
          close),
        el("div", { class: "mg-panel-body" }, ...rows));
      this.panel.hidden = false;
      this.mount.setAttribute("data-panel-open", "true");
      close.focus();
    }

    _evidenceCard(src) {
      const loc = src.page ? `${src.archetype || "document"} · p.${src.page}` : (src.archetype || "document");
      return el("div", { class: "mg-evidence" },
        el("div", { class: "doc" }, src.doc_id),
        el("div", { class: "loc" }, loc),
        src.raw_span ? el("div", { class: "span" }, "“" + src.raw_span + "”") : el("div", { class: "loc" }, "no verbatim span — field not located in this document"));
    }

    _relatedNodes(id) {
      const ids = new Set();
      for (const e of this.view.edges) {
        if (e.source === id) ids.add(e.target);
        if (e.target === id) ids.add(e.source);
      }
      return [...ids].map((x) => this.view.nodes.find((n) => n.id === x)).filter(Boolean);
    }

    _closePanel() {
      this.selected = null;
      this.panel.hidden = true;
      this.mount.removeAttribute("data-panel-open");
      for (const node of this.nodeEls.values()) node.classList.remove("selected");
      this._clearHighlight();
    }

    /* ---- search ------------------------------------------------------------------ */
    _runSearch(q) {
      this._searchHits = engine.searchNodes(this.view, q);
      const hitset = new Set(this._searchHits);
      const active = q.trim().length > 0;
      for (const [id, node] of this.nodeEls) {
        node.classList.toggle("dim", active && !hitset.has(id));
        node.classList.toggle("hot", active && hitset.has(id));
      }
      if (!active) this._refreshHighlight();
    }
    _selectFirstSearchHit() {
      if (this._searchHits && this._searchHits.length) this.select(this._searchHits[0]);
    }
  }

  V.MemoryGraphView = MemoryGraphView;
})();
