/* AnalysisTerminal — replays one file analysis's recorded event log as a live-feeling but
   honest timeline. The events are user-facing execution summaries produced server-side
   (experiment/file_analysis.py); this component never invents reasoning, it only paces and
   styles what the analysis actually recorded.

   A class is warranted: playback position, follow-scroll state, timers, and a mount/destroy
   lifecycle with listener cleanup. Handles long logs by capping the animated tail and
   rendering older rows immediately. */
(function () {
  "use strict";
  const V = window.Verdict;
  const el = V.el, icons = V.icons;
  const KIND = V.EVENT_KIND_META, STAGE_LABEL = V.STAGE_LABEL, STAGES = V.STAGES;

  // Deterministic per-stage pacing (ms) — a plausible cadence, seeded only by the event log.
  const STAGE_BASE = { QUEUE: 0, LOAD: 180, EXTRACT: 520, SCORE: 1400, DECIDE: 1750,
    RECONCILE: 2600, DERIVE: 2950, GRAPH: 3250, DONE: 3600 };

  class AnalysisTerminal {
    constructor(mount, options) {
      this.mount = typeof mount === "string" ? document.querySelector(mount) : mount;
      this.opts = Object.assign({ autoplay: true, speed: 1, onComplete: null, onStage: null }, options || {});
      this.analysis = null;
      this.timeline = [];
      this.index = 0;
      this.follow = true;
      this.playing = false;
      this._timer = 0;
      this._cleanup = [];
    }

    setState(state, message) {
      this._stop();
      this.mount.innerHTML = "";
      this.mount.className = "term term-state";
      const map = {
        empty: { icon: icons.system, h: "No analysis selected", p: message || "Choose a file to watch its analysis." },
        loading: { icon: icons.spinner, h: "Preparing analysis", p: message || "Loading the recorded run…" },
      };
      const s = map[state] || map.empty;
      this.mount.append(el("div", { class: "v-empty", role: "status" },
        el("div", { html: s.icon }), el("h3", {}, s.h), el("p", {}, s.p)));
    }

    load(analysis, { autoplay } = {}) {
      this._stop();
      this.analysis = analysis;
      this.timeline = this._buildTimeline(analysis.events);
      this.index = 0;
      this.follow = true;
      this._buildChrome();
      const play = autoplay != null ? autoplay : this.opts.autoplay;
      if (play && !V.reducedMotion()) this.play();
      else this._renderAll();
    }

    _buildTimeline(events) {
      // Assign each event a deterministic elapsed offset: stage base + a per-event step within
      // the stage, so timestamps read monotonically and match the stage rail.
      const perStage = {};
      return events.map((e) => {
        perStage[e.stage] = (perStage[e.stage] || 0) + 1;
        const within = perStage[e.stage] - 1;
        const t = (STAGE_BASE[e.stage] || 0) + within * 95;
        return Object.assign({}, e, { t });
      });
    }

    /* ---- chrome ------------------------------------------------------------------ */
    _buildChrome() {
      this._teardown();
      this.mount.className = "term";
      this.mount.innerHTML = "";
      const a = this.analysis;

      this.statusEl = el("span", { class: "term-status", "data-state": a.status },
        el("span", { class: "v-dot " + this._statusDot(a.status) }), a.status);

      this.copyBtn = el("button", { class: "v-btn v-btn-ghost v-btn-sm", type: "button",
        title: "Copy the analysis log", html: icons.copy + "<span>Copy log</span>" });
      this._on(this.copyBtn, "click", () => this._copyLog());
      this.skipBtn = el("button", { class: "mg-iconbtn", type: "button", title: "Skip to end",
        "aria-label": "Skip to end of log", html: icons.skip });
      this._on(this.skipBtn, "click", () => this._skipToEnd());

      const docs = a.documents || [];
      this.stageCur = el("span", { class: "cur" }, STAGE_LABEL[a.events[0] ? a.events[0].stage : "QUEUE"]);
      this.stagePct = el("span", {}, "0%");
      this.progressFill = el("div", { class: "term-progress-fill", "data-state": a.status });

      this.head = el("div", { class: "term-head" },
        el("div", { class: "term-head-top" },
          el("div", { class: "term-file" }, el("span", { html: icons.file }),
            el("span", { class: "name" }, a.file_label)),
          this.statusEl,
          el("div", { class: "term-head-spacer" }),
          el("div", { class: "term-actions" }, this.skipBtn, this.copyBtn)),
        el("div", { class: "term-meta" },
          el("span", {}, el("b", {}, String(docs.length)), " documents"),
          el("span", {}, el("b", {}, String(a.n_fields)), " target fields"),
          el("span", {}, "batch ", el("span", { class: "v-mono" }, a.batch_id || "—")),
          a.tau != null ? el("span", {}, "τ ", el("span", { class: "v-mono" }, a.tau.toFixed(3))) : null,
          a.segment ? el("span", {}, "NAICS ", el("span", { class: "v-mono" }, a.segment.naics2),
            " · ", a.segment.state) : null),
        el("div", { class: "term-progress" },
          el("div", { class: "term-stage-label" },
            el("span", {}, "Stage: ", this.stageCur), this.stagePct),
          el("div", { class: "term-progress-bar" }, this.progressFill)));

      this.log = el("div", { class: "term-log", role: "log", "aria-label": "Analysis log",
        "aria-live": "polite", "aria-relevant": "additions", tabindex: "0" });
      this.jump = el("button", { class: "term-jump", type: "button", html: icons.down + "<span>Latest</span>" });
      this._on(this.jump, "click", () => { this.follow = true; this._scrollToEnd(); this._updateJump(); });

      this.countEl = el("span", { class: "count" }, "0 / " + this.timeline.length);
      this.liveEl = el("span", { class: "live" });
      this.foot = el("div", { class: "term-foot" }, this.countEl,
        el("span", {}, "recorded run — replayed"), this.liveEl);

      const logWrap = el("div", { style: "position:relative; display:flex; flex-direction:column; min-height:0; flex:1" }, this.log, this.jump);
      this.mount.append(this.head, logWrap, this.foot);

      // Following pauses when the user scrolls up; resumes when they return to the tail.
      this._on(this.log, "scroll", () => {
        const nearBottom = this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 40;
        this.follow = nearBottom;
        this._updateJump();
      });
    }

    /* ---- playback ---------------------------------------------------------------- */
    play() {
      if (this.index >= this.timeline.length) return this._finish();
      this.playing = true;
      this._setLive(true);
      const step = () => {
        if (!this.playing) return;
        if (this.index >= this.timeline.length) return this._finish();
        const ev = this.timeline[this.index];
        const prev = this.index > 0 ? this.timeline[this.index - 1].t : 0;
        this._appendRow(ev, true);
        this.index++;
        this._updateProgress(ev);
        if (this.index >= this.timeline.length) return this._finish();
        const gap = Math.max(90, Math.min(520, (this.timeline[this.index].t - prev))) / (this.opts.speed || 1);
        this._timer = setTimeout(step, gap);
      };
      step();
    }

    _renderAll() {
      for (; this.index < this.timeline.length; this.index++)
        this._appendRow(this.timeline[this.index], false);
      this._updateProgress(this.timeline[this.timeline.length - 1]);
      this._finish(true);
    }

    _skipToEnd() {
      this._stop();
      for (; this.index < this.timeline.length; this.index++)
        this._appendRow(this.timeline[this.index], false);
      this._updateProgress(this.timeline[this.timeline.length - 1]);
      this.follow = true; this._scrollToEnd();
      this._finish(true);
    }

    _finish(silent) {
      this._stop();
      this._setLive(false);
      if (this.skipBtn) this.skipBtn.style.display = "none";
      if (!silent && typeof this.opts.onStage === "function") this.opts.onStage("DONE", this.analysis);
      if (typeof this.opts.onComplete === "function") this.opts.onComplete(this.analysis);
    }

    _stop() { this.playing = false; clearTimeout(this._timer); this._timer = 0; }

    /* ---- rows -------------------------------------------------------------------- */
    _appendRow(ev, animate) {
      const meta = KIND[ev.kind] || KIND.info;
      const msg = el("span", { class: "msg" });
      msg.append(el("span", { class: "stage-tag" }, ev.stage));
      msg.append(this._decorate(ev.text, ev.field));
      if (ev.severity) msg.append(el("span", { class: "sev v-sev-" + ev.severity }, ev.severity));
      const row = el("div", { class: "term-row " + meta.cls + (animate && !V.reducedMotion() ? " term-row-appear" : "") },
        el("span", { class: "t" }, V.fmt.secs(ev.t)),
        el("span", { class: "ic", html: icons[meta.icon] }),
        msg);
      this.log.append(row);
      this.countEl.textContent = (this.index + 1) + " / " + this.timeline.length;
      if (this.follow) this._scrollToEnd();
      // Cap animated DOM growth: strip the appear class from rows beyond the visible tail.
      if (this.log.childElementCount > 60) {
        const old = this.log.children[this.log.childElementCount - 61];
        if (old) old.classList.remove("term-row-appear");
      }
    }

    _decorate(text, field) {
      // Bold the field name where the event names one; keep everything else literal.
      const frag = document.createDocumentFragment();
      if (field && text.includes(field)) {
        const parts = text.split(field);
        parts.forEach((p, i) => {
          if (p) frag.append(document.createTextNode(p));
          if (i < parts.length - 1) frag.append(el("span", { class: "field" }, field));
        });
      } else {
        frag.append(document.createTextNode(text));
      }
      return frag;
    }

    _updateProgress(ev) {
      if (!ev) return;
      const idx = STAGES.indexOf(ev.stage);
      const pct = Math.round(((idx + 1) / STAGES.length) * 100);
      this.progressFill.style.width = pct + "%";
      this.stagePct.textContent = pct + "%";
      this.stageCur.textContent = STAGE_LABEL[ev.stage] || ev.stage;
      if (typeof this.opts.onStage === "function") this.opts.onStage(ev.stage, this.analysis);
    }

    _scrollToEnd() { this.log.scrollTop = this.log.scrollHeight; }
    _updateJump() { this.jump.classList.toggle("show", !this.follow); }
    _setLive(on) {
      this.liveEl.innerHTML = "";
      if (on) this.liveEl.append(el("span", { class: "v-dot v-dot-run" }), "live");
    }
    _statusDot(s) {
      return ({ RUNNING: "v-dot-run", COMPLETED: "v-dot-ok", PARTIAL: "v-dot-warn",
        FAILED: "v-dot-err", QUEUED: "v-dot-idle" })[s] || "v-dot-idle";
    }

    _copyLog() {
      const text = this.timeline.map((e) =>
        `${V.fmt.secs(e.t)}  ${e.stage.padEnd(9)}  ${(KIND[e.kind] || KIND.info).label.toUpperCase().padEnd(7)}  ${e.text}`
      ).join("\n");
      const done = () => {
        this.copyBtn.innerHTML = icons.success + "<span>Copied</span>";
        setTimeout(() => { this.copyBtn.innerHTML = icons.copy + "<span>Copy log</span>"; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => this._fallbackCopy(text, done));
      } else this._fallbackCopy(text, done);
    }
    _fallbackCopy(text, done) {
      const ta = el("textarea", { style: "position:fixed;opacity:0" });
      ta.value = text; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (_) {}
      ta.remove();
    }

    destroy() { this._stop(); this._teardown(); this.mount.innerHTML = ""; }
    _teardown() { this._cleanup.forEach((fn) => fn()); this._cleanup = []; }
    _on(t, ev, fn, opts) { t.addEventListener(ev, fn, opts); this._cleanup.push(() => t.removeEventListener(ev, fn, opts)); }
  }

  V.AnalysisTerminal = AnalysisTerminal;
})();
