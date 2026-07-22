/* Memory-graph engine — validation + deterministic layered layout. Pure functions, no DOM.
   Mirrors src/abstention/memory (schema ranks + validator invariants) so a served report
   that fails the Python contract also fails loudly here instead of rendering broken edges.
   UMD-ish export: usable from the browser pages and from `node --test`. */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else {
    root.Verdict = root.Verdict || {};
    root.Verdict.graphEngine = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const CATEGORY_RANK = {
    FILE: 0, SUMMARY: 1, DOCUMENT: 1, FIELD: 2, CHECK: 3,
    FINDING: 4, EVIDENCE: 5, METRIC: 6, ACTION: 7,
  };
  const RELATION_ENDPOINTS = {
    SUMMARIZED_BY: ["FILE", "SUMMARY"],
    CONTAINS: ["FILE", "DOCUMENT"],
    EXTRACTED: ["DOCUMENT", "FIELD"],
    CHECKED_BY: ["FIELD", "CHECK"],
    RAISED: ["CHECK", "FINDING"],
    AFFECTED_BY: ["FIELD", "FINDING"],
    EVIDENCED_BY: ["FINDING", "EVIDENCE"],
    FEEDS: ["FIELD", "METRIC"],
    BLOCKS: ["FINDING", "METRIC"],
    RESOLVED_BY: ["FINDING", "ACTION"],
  };
  const SEVERITY_ORDER = { NONE: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 };

  const rankOf = (n) => (typeof n.rank === "number" ? n.rank : CATEGORY_RANK[n.category] ?? 0);
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  function appendTo(map, key, value) {
    let arr = map.get(key);
    if (!arr) map.set(key, (arr = []));
    arr.push(value);
  }

  /* ---- validation (mirror of memory/validator.py) --------------------------------- */
  function validateGraph(graph) {
    const problems = [];
    if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
      return ["graph payload is not an object with nodes[] and edges[]"];
    }
    const byId = new Map();
    for (const n of graph.nodes) {
      if (byId.has(n.id)) problems.push(`duplicate node id ${n.id}`);
      byId.set(n.id, n);
      if (!(n.category in CATEGORY_RANK))
        problems.push(`node ${n.id}: unknown category ${n.category}`);
      if (!(n.severity in SEVERITY_ORDER))
        problems.push(`node ${n.id}: unknown severity ${n.severity}`);
    }
    const edgeIds = new Set();
    const incomingRel = new Map(), outgoingRel = new Map(), children = new Map();
    for (const e of graph.edges) {
      if (edgeIds.has(e.id)) problems.push(`duplicate edge id ${e.id}`);
      edgeIds.add(e.id);
      const s = byId.get(e.source), t = byId.get(e.target);
      if (!s || !t) {
        problems.push(`edge ${e.id} references missing node(s)`);
        continue;
      }
      const want = RELATION_ENDPOINTS[e.relation];
      if (!want) problems.push(`edge ${e.id}: unknown relation ${e.relation}`);
      else if (s.category !== want[0] || t.category !== want[1])
        problems.push(`edge ${e.id}: ${e.relation} must connect ${want[0]}→${want[1]}`);
      if (rankOf(t) <= rankOf(s)) problems.push(`edge ${e.id} flows backward`);
      appendTo(incomingRel, e.target, e.relation);
      appendTo(outgoingRel, e.source, e.relation);
      appendTo(children, e.source, e.target);
    }
    const files = graph.nodes.filter((n) => n.category === "FILE");
    if (files.length !== 1)
      problems.push(`expected exactly one FILE root, found ${files.length}`);
    if (graph.nodes.filter((n) => n.category === "SUMMARY").length !== 1)
      problems.push("expected exactly one SUMMARY node");
    for (const n of graph.nodes) {
      if (n.category !== "FINDING") continue;
      const inc = incomingRel.get(n.id) || [];
      if (!inc.includes("AFFECTED_BY"))
        problems.push(`finding ${n.id} not connected to an affected FIELD`);
      if (!inc.includes("RAISED")) problems.push(`finding ${n.id} has no raising CHECK`);
      if (!(outgoingRel.get(n.id) || []).includes("EVIDENCED_BY"))
        problems.push(`finding ${n.id} has no EVIDENCE`);
    }
    if (files.length === 1) {
      const seen = new Set([files[0].id]);
      const stack = [files[0].id];
      while (stack.length) {
        for (const nxt of children.get(stack.pop()) || []) {
          if (!seen.has(nxt)) { seen.add(nxt); stack.push(nxt); }
        }
      }
      for (const n of graph.nodes)
        if (!seen.has(n.id)) problems.push(`node ${n.id} unreachable from FILE root`);
    }
    return problems;
  }

  /* ---- deterministic layered layout ------------------------------------------------
     Columns come from the canonical category rank; ordering inside a column is settled by
     barycenter sweeps over the real edges; coordinates come from MEASURED node sizes passed
     in by the view. Identical graph + identical sizes ⇒ identical positions. */
  function layoutGraph(graph, opts) {
    const o = Object.assign(
      { sizes: {}, defaultSize: { w: 180, h: 56 }, orientation: "LR", colGap: 72, rowGap: 18 },
      opts || {}
    );
    const LR = o.orientation !== "TB";
    // flow-space dimensions: du along the rank axis, dv along the stacking axis.
    const dims = new Map();
    for (const n of graph.nodes) {
      const s = o.sizes[n.id] || o.defaultSize;
      dims.set(n.id, { w: s.w, h: s.h, du: LR ? s.w : s.h, dv: LR ? s.h : s.w });
    }
    const du = (id) => dims.get(id).du;
    const dv = (id) => dims.get(id).dv;

    // 1. columns from sorted unique ranks (no empty columns).
    const ranks = [...new Set(graph.nodes.map(rankOf))].sort((a, b) => a - b);
    const colIndex = new Map(ranks.map((r, i) => [r, i]));
    const columns = ranks.map(() => []);
    for (const n of graph.nodes) columns[colIndex.get(rankOf(n))].push(n);

    // 2. neighbor maps over the real edges.
    const inN = new Map(), outN = new Map();
    for (const e of graph.edges) {
      appendTo(inN, e.target, e.source);
      appendTo(outN, e.source, e.target);
    }

    // 3. ordering: seed by (category, id), then 4 barycenter sweeps (forward sweeps read
    // in-neighbors, backward sweeps read out-neighbors). Stable + fixed ⇒ deterministic.
    const catOrder = Object.fromEntries(Object.keys(CATEGORY_RANK).map((c, i) => [c, i]));
    for (const col of columns)
      col.sort((a, b) => catOrder[a.category] - catOrder[b.category] || cmp(a.id, b.id));
    const normPos = new Map(); // id → normalized stacking position (0..1)
    const refreshNorm = () =>
      columns.forEach((col) => col.forEach((n, i) => normPos.set(n.id, (i + 0.5) / col.length)));
    refreshNorm();
    for (let sweep = 0; sweep < 4; sweep++) {
      const forward = sweep % 2 === 0;
      for (const col of forward ? columns : [...columns].reverse()) {
        const score = new Map(col.map((n) => {
          const nbrs = (forward ? inN : outN).get(n.id) || [];
          const bc = nbrs.length
            ? nbrs.reduce((s, id) => s + normPos.get(id), 0) / nbrs.length
            : normPos.get(n.id);
          return [n.id, bc];
        }));
        col.sort((a, b) => score.get(a.id) - score.get(b.id) || cmp(a.id, b.id));
        refreshNorm();
      }
    }

    // 4. flow-axis offsets per column from the widest member.
    const colU = [], colExtent = [];
    let uCursor = 0;
    columns.forEach((col, i) => {
      colU[i] = uCursor;
      colExtent[i] = Math.max(...col.map((n) => du(n.id)));
      uCursor += colExtent[i] + o.colGap;
    });

    // 5. stacking axis: initial stack, then alignment passes toward neighbor centers that
    // preserve order and minimum gaps (place sequentially with a moving floor).
    const vPos = new Map();
    columns.forEach((col) => {
      let v = 0;
      for (const n of col) { vPos.set(n.id, v); v += dv(n.id) + o.rowGap; }
    });
    const centerOf = (id) => vPos.get(id) + dv(id) / 2;
    for (let pass = 0; pass < 3; pass++) {
      const forward = pass % 2 === 0;
      for (const col of forward ? columns : [...columns].reverse()) {
        const nbrMap = forward ? inN : outN;
        const desired = col.map((n) => {
          const nbrs = nbrMap.get(n.id) || [];
          return nbrs.length
            ? nbrs.reduce((s, id) => s + centerOf(id), 0) / nbrs.length
            : centerOf(n.id);
        });
        let floor = -Infinity;
        col.forEach((n, i) => {
          const v = Math.max(desired[i] - dv(n.id) / 2, floor);
          vPos.set(n.id, v);
          floor = v + dv(n.id) + o.rowGap;
        });
      }
    }

    // 6. normalize to the origin and emit screen-space rects.
    let minV = Infinity;
    for (const n of graph.nodes) minV = Math.min(minV, vPos.get(n.id));
    const rects = {};
    let maxU = 0, maxV = 0;
    columns.forEach((col, i) => {
      for (const n of col) {
        const d = dims.get(n.id);
        const uu = colU[i];
        const vv = vPos.get(n.id) - minV;
        rects[n.id] = LR
          ? { x: uu, y: vv, w: d.w, h: d.h }
          : { x: vv, y: uu, w: d.w, h: d.h };
        maxU = Math.max(maxU, uu + d.du);
        maxV = Math.max(maxV, vv + d.dv);
      }
    });
    return {
      rects,
      size: LR ? { width: maxU, height: maxV } : { width: maxV, height: maxU },
      columns: columns.map((col) => col.map((n) => n.id)),
      orientation: LR ? "LR" : "TB",
    };
  }

  /* ---- edge geometry from measured rects ------------------------------------------ */
  function edgePath(rects, edge, orientation) {
    const s = rects[edge.source], t = rects[edge.target];
    if (!s || !t) return null;
    let x1, y1, x2, y2, d;
    if (orientation !== "TB") {
      x1 = s.x + s.w; y1 = s.y + s.h / 2;
      x2 = t.x; y2 = t.y + t.h / 2;
      const c = Math.min(140, Math.max(36, (x2 - x1) * 0.42));
      d = `M ${r(x1)} ${r(y1)} C ${r(x1 + c)} ${r(y1)}, ${r(x2 - c)} ${r(y2)}, ${r(x2)} ${r(y2)}`;
    } else {
      x1 = s.x + s.w / 2; y1 = s.y + s.h;
      x2 = t.x + t.w / 2; y2 = t.y;
      const c = Math.min(120, Math.max(30, (y2 - y1) * 0.42));
      d = `M ${r(x1)} ${r(y1)} C ${r(x1)} ${r(y1 + c)}, ${r(x2)} ${r(y2 - c)}, ${r(x2)} ${r(y2)}`;
    }
    return { d, x1, y1, x2, y2, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
    function r(v) { return Math.round(v * 100) / 100; }
  }

  /* ---- filtering that preserves valid connections ---------------------------------- */
  function filterGraph(graph, opts) {
    const o = Object.assign({ minSeverity: "NONE", affectedOnly: false }, opts || {});
    const min = SEVERITY_ORDER[o.minSeverity] ?? 0;
    if (!o.affectedOnly && min === 0) {
      return { nodes: graph.nodes.slice(), edges: graph.edges.slice() };
    }
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const keep = new Set();
    for (const n of graph.nodes)
      if (n.category === "FINDING" && SEVERITY_ORDER[n.severity] >= Math.max(min, 1))
        keep.add(n.id);
    // everything a kept finding touches travels with it (field, check, evidence, metric, action)
    for (const e of graph.edges) {
      if (keep.has(e.source)) keep.add(e.target);
      if (keep.has(e.target)) keep.add(e.source);
    }
    // ancestors so the graph stays rooted
    let grew = true;
    while (grew) {
      grew = false;
      for (const id of [...keep]) {
        const parent = byId.get(id) && byId.get(id).parent_id;
        if (parent && byId.has(parent) && !keep.has(parent)) { keep.add(parent); grew = true; }
      }
    }
    for (const n of graph.nodes)
      if (n.category === "FILE" || n.category === "SUMMARY") keep.add(n.id);
    return {
      nodes: graph.nodes.filter((n) => keep.has(n.id)),
      edges: graph.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }

  function searchNodes(graph, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return [];
    return graph.nodes
      .filter((n) => [n.label, n.summary, n.id, n.category]
        .some((s) => String(s || "").toLowerCase().includes(q)))
      .map((n) => n.id);
  }

  function connectedIds(graph, id) {
    const inE = new Map(), outE = new Map();
    for (const e of graph.edges) {
      appendTo(inE, e.target, e.source);
      appendTo(outE, e.source, e.target);
    }
    const up = walk(id, inE), down = walk(id, outE);
    return { up, down, all: new Set([id, ...up, ...down]) };
    function walk(start, map) {
      const acc = new Set(), stack = [start];
      while (stack.length) {
        for (const nxt of map.get(stack.pop()) || []) {
          if (!acc.has(nxt)) { acc.add(nxt); stack.push(nxt); }
        }
      }
      return acc;
    }
  }

  return {
    CATEGORY_RANK, RELATION_ENDPOINTS, SEVERITY_ORDER,
    validateGraph, layoutGraph, edgePath, filterGraph, searchNodes, connectedIds,
  };
});
