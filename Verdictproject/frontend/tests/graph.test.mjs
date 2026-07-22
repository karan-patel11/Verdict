/* Engine tests for the memory-graph layout + validation (run via `node --test`).
   The same invariants the Python validator enforces must hold here, and layout must be
   deterministic, overlap-free, and forward-flowing at any orientation. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const engine = require(join(here, "../assets/memory-graph.js"));

function miniGraph() {
  const N = (id, category, extra = {}) => ({
    id, category, rank: engine.CATEGORY_RANK[category], label: id, summary: "",
    severity: "NONE", parent_id: null, ...extra,
  });
  const E = (source, target, relation, extra = {}) => ({
    id: `${source}~${relation}~${target}`, source, target, relation, ...extra,
  });
  return {
    nodes: [
      N("file", "FILE"),
      N("summary", "SUMMARY", { parent_id: "file" }),
      N("doc:a", "DOCUMENT", { parent_id: "file" }),
      N("field:0:REV", "FIELD", { parent_id: "doc:a" }),
      N("field:1:NI", "FIELD", { parent_id: "doc:a" }),
      N("check:gate", "CHECK"),
      N("finding:1:NI", "FINDING", { severity: "HIGH", parent_id: "field:1:NI" }),
      N("evidence:1:NI:0", "EVIDENCE", { parent_id: "finding:1:NI" }),
      N("metric:DSCR", "METRIC"),
      N("action:verify", "ACTION"),
    ],
    edges: [
      E("file", "summary", "SUMMARIZED_BY"),
      E("file", "doc:a", "CONTAINS"),
      E("doc:a", "field:0:REV", "EXTRACTED"),
      E("doc:a", "field:1:NI", "EXTRACTED"),
      E("field:0:REV", "check:gate", "CHECKED_BY"),
      E("field:1:NI", "check:gate", "CHECKED_BY"),
      E("check:gate", "finding:1:NI", "RAISED"),
      E("field:1:NI", "finding:1:NI", "AFFECTED_BY"),
      E("finding:1:NI", "evidence:1:NI:0", "EVIDENCED_BY"),
      E("field:1:NI", "metric:DSCR", "FEEDS"),
      E("finding:1:NI", "metric:DSCR", "BLOCKS", { propagates_issue: true }),
      E("finding:1:NI", "action:verify", "RESOLVED_BY"),
    ],
  };
}

const noOverlap = (a, b) =>
  a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;

test("valid graph produces no validation problems", () => {
  assert.deepEqual(engine.validateGraph(miniGraph()), []);
});

test("invalid edge references are rejected", () => {
  const g = miniGraph();
  g.edges.push({ id: "bad", source: "file", target: "ghost", relation: "CONTAINS" });
  assert.ok(engine.validateGraph(g).some((p) => p.includes("missing node")));
});

test("duplicate ids are detected", () => {
  const g = miniGraph();
  g.nodes.push({ ...g.nodes[3] });
  assert.ok(engine.validateGraph(g).some((p) => p.includes("duplicate node id")));
  const h = miniGraph();
  h.edges.push({ ...h.edges[0] });
  assert.ok(engine.validateGraph(h).some((p) => p.includes("duplicate edge id")));
});

test("a finding disconnected from its field fails validation", () => {
  const g = miniGraph();
  g.edges = g.edges.filter((e) => e.relation !== "AFFECTED_BY");
  assert.ok(engine.validateGraph(g).some((p) => p.includes("affected FIELD")));
});

test("wrong endpoint categories fail validation", () => {
  const g = miniGraph();
  g.edges.push({ id: "x", source: "summary", target: "metric:DSCR", relation: "FEEDS" });
  assert.ok(engine.validateGraph(g).some((p) => p.includes("must connect FIELD→METRIC")));
});

test("identical input produces identical layout (determinism)", () => {
  const a = engine.layoutGraph(miniGraph(), { orientation: "LR" });
  const b = engine.layoutGraph(miniGraph(), { orientation: "LR" });
  assert.deepEqual(a, b);
});

test("layout yields finite positions and no node overlap", () => {
  const { rects } = engine.layoutGraph(miniGraph());
  const list = Object.values(rects);
  for (const r of list)
    for (const v of [r.x, r.y, r.w, r.h]) assert.ok(Number.isFinite(v));
  for (let i = 0; i < list.length; i++)
    for (let j = i + 1; j < list.length; j++)
      assert.ok(noOverlap(list[i], list[j]), `nodes ${i} and ${j} overlap`);
});

test("every edge flows forward geometrically in both orientations", () => {
  const g = miniGraph();
  const lr = engine.layoutGraph(g, { orientation: "LR" });
  for (const e of g.edges)
    assert.ok(lr.rects[e.target].x >= lr.rects[e.source].x + lr.rects[e.source].w,
      `LR edge ${e.id} does not flow forward`);
  const tb = engine.layoutGraph(g, { orientation: "TB" });
  for (const e of g.edges)
    assert.ok(tb.rects[e.target].y >= tb.rects[e.source].y + tb.rects[e.source].h,
      `TB edge ${e.id} does not flow forward`);
});

test("edge paths anchor exactly on node borders", () => {
  const g = miniGraph();
  const { rects } = engine.layoutGraph(g, { orientation: "LR" });
  for (const e of g.edges) {
    const p = engine.edgePath(rects, e, "LR");
    const s = rects[e.source], t = rects[e.target];
    assert.equal(p.x1, s.x + s.w);
    assert.equal(p.y1, s.y + s.h / 2);
    assert.equal(p.x2, t.x);
    assert.equal(p.y2, t.y + t.h / 2);
  }
});

test("measured sizes are honored", () => {
  const sizes = { file: { w: 260, h: 90 } };
  const { rects } = engine.layoutGraph(miniGraph(), { sizes });
  assert.equal(rects.file.w, 260);
  assert.equal(rects.file.h, 90);
});

test("single-node graph lays out at the origin", () => {
  const g = { nodes: [{ id: "file", category: "FILE", rank: 0, severity: "NONE" }], edges: [] };
  const { rects, size } = engine.layoutGraph(g, { defaultSize: { w: 100, h: 40 } });
  assert.deepEqual(rects.file, { x: 0, y: 0, w: 100, h: 40 });
  assert.deepEqual(size, { width: 100, height: 40 });
});

test("large graphs lay out without overlap or NaN", () => {
  const nodes = [{ id: "file", category: "FILE", rank: 0, severity: "NONE" }];
  const edges = [];
  nodes.push({ id: "summary", category: "SUMMARY", rank: 1, severity: "NONE" });
  edges.push({ id: "e-s", source: "file", target: "summary", relation: "SUMMARIZED_BY" });
  for (let d = 0; d < 8; d++) {
    const doc = `doc:${d}`;
    nodes.push({ id: doc, category: "DOCUMENT", rank: 1, severity: "NONE" });
    edges.push({ id: `e-d${d}`, source: "file", target: doc, relation: "CONTAINS" });
    for (let f = 0; f < 30; f++) {
      const fid = `field:${d}:${f}`;
      nodes.push({ id: fid, category: "FIELD", rank: 2, severity: "NONE" });
      edges.push({ id: `e-f${d}-${f}`, source: doc, target: fid, relation: "EXTRACTED" });
    }
  }
  const t0 = process.hrtime.bigint();
  const { rects } = engine.layoutGraph({ nodes, edges });
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  assert.ok(ms < 500, `layout of ${nodes.length} nodes took ${ms}ms`);
  const list = Object.values(rects);
  assert.equal(list.length, nodes.length);
  for (const r of list) for (const v of [r.x, r.y]) assert.ok(Number.isFinite(v));
  for (let i = 0; i < list.length; i++)
    for (let j = i + 1; j < list.length; j++)
      assert.ok(noOverlap(list[i], list[j]));
});

test("severity filter keeps connections valid and ancestors rooted", () => {
  const g = miniGraph();
  const filtered = engine.filterGraph(g, { minSeverity: "HIGH" });
  const kept = new Set(filtered.nodes.map((n) => n.id));
  assert.ok(kept.has("finding:1:NI"));
  assert.ok(kept.has("field:1:NI"));   // the affected node travels with the finding
  assert.ok(kept.has("evidence:1:NI:0"));
  assert.ok(kept.has("file") && kept.has("summary"));
  for (const e of filtered.edges)
    assert.ok(kept.has(e.source) && kept.has(e.target), `edge ${e.id} dangles after filter`);
  const none = engine.filterGraph(g, { minSeverity: "CRITICAL" });
  assert.ok(!none.nodes.some((n) => n.category === "FINDING"));
});

test("affected-only filter drops clean branches", () => {
  const g = miniGraph();
  const filtered = engine.filterGraph(g, { affectedOnly: true });
  const kept = new Set(filtered.nodes.map((n) => n.id));
  assert.ok(!kept.has("field:0:REV"), "clean field should be hidden");
  assert.ok(kept.has("field:1:NI"));
});

test("search matches labels case-insensitively", () => {
  const hits = engine.searchNodes(miniGraph(), "dscr");
  assert.deepEqual(hits, ["metric:DSCR"]);
});

test("connected ids split upstream and downstream correctly", () => {
  const g = miniGraph();
  const c = engine.connectedIds(g, "finding:1:NI");
  assert.ok(c.up.has("field:1:NI") && c.up.has("doc:a") && c.up.has("file"));
  assert.ok(c.down.has("evidence:1:NI:0") && c.down.has("metric:DSCR") && c.down.has("action:verify"));
  assert.ok(!c.down.has("summary") && !c.up.has("action:verify"));
});

test("missing optional metadata does not break layout or validation", () => {
  const g = miniGraph();
  for (const n of g.nodes) { delete n.rank; delete n.parent_id; }
  assert.deepEqual(engine.validateGraph(g), []);
  const { rects } = engine.layoutGraph(g);
  assert.equal(Object.keys(rects).length, g.nodes.length);
});

/* ---- integration against the real generated report ------------------------------- */
const reportPath = join(here, "../report.json");
test("every published graph in report.json validates and lays out deterministically",
  { skip: !existsSync(reportPath) }, () => {
    const report = JSON.parse(readFileSync(reportPath, "utf8"));
    const analyses = report.analyses || [];
    assert.ok(analyses.length >= 5, "expected showcase analyses in the report");
    let checked = 0;
    for (const a of analyses) {
      if (a.status === "FAILED") { assert.equal(a.graph, null); continue; }
      const problems = engine.validateGraph(a.graph);
      assert.deepEqual(problems, [], `graph for ${a.analysis_id} invalid`);
      const l1 = engine.layoutGraph(a.graph);
      const l2 = engine.layoutGraph(a.graph);
      assert.deepEqual(l1, l2);
      const list = Object.values(l1.rects);
      for (let i = 0; i < list.length; i++)
        for (let j = i + 1; j < list.length; j++)
          assert.ok(noOverlap(list[i], list[j]), `overlap in ${a.analysis_id}`);
      checked++;
    }
    assert.ok(checked >= 4);
  });
