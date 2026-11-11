/*assist.js — the local thinking layer for the curation pane.
 *
 * Two stages, both optional, both local to the browser:
 *   1. Heuristic ranking: the portal ranks every paragraph against the
 *      run's question (term coverage, phrases, density, position). This
 *      module paints the scores, marks the suggested keep-set, and offers
 *      "adopt suggestions" to tick them.
 *   2. An optional small LLM (WebLLM on the browser's GPU, or a CPU/wasm
 *      fallback) re-judges a shortlist of paragraphs. Advisory only; a
 *      drop that lands mid-review never interrupts scoring.
 */
(function () {
  "use strict";

  /* ---- tiny dom helpers (same conventions as curate.js) ---------------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  var rank = null;        // last /api/rank payload for this run
  var rankRid = null;
  var modelVerdicts = {}; // pid -> {verdict, why}
  var running = false;

  /* ---- API -------------------------------------------------------------- */
  function fetchRank(rid, force) {
    if (!rid) return Promise.resolve(null);
    if (!force && rankRid === rid && rank) return Promise.resolve(rank);
    return fetch("/api/rank/" + encodeURIComponent(rid), { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.error) { rank = null; rankRid = null; return null; }
        rank = j; rankRid = rid;
        return j;
      })
      .catch(function () { return null; });
  }

  /* score chip class: heat by score */
  function chipCls(s) {
    if (s >= 2) return "gs-rankchip hot";
    if (s >= 0.6) return "gs-rankchip warm";
    if (s > 0) return "gs-rankchip cool";
    return "gs-rankchip";
  }

  /* decorate the pane after every (re)paint */
  function decorate() {
    if (!rank) return;
    var box = $("cur-paras");
    if (!box) return;
    var byPid = {};
    (rank.pages || []).forEach(function (p) {
      (p.paras || []).forEach(function (pp) { byPid[pp.pid] = pp; });
    });
    var rows = box.querySelectorAll("[data-pid]");
    [].forEach.call(rows, function (row) {
      var pid = row.getAttribute("data-pid");
      var para = byPid[pid];
      if (!para) return;
      if (row.querySelector(".gs-rankchip")) return;
      var chip = el("span", chipCls(para.score), "•" + para.score);
      chip.title = (para.score >= 0.6 ? "suggested keep — " : "score ") +
        para.why;
      var v = modelVerdicts[pid];
      if (v) {
        chip.classList.add(v.verdict === "keep" ? "vkeep"
          : v.verdict === "burn" ? "vburn" : "vmaybe");
        chip.title = "local model: " + v.verdict +
          (v.why ? " — " + v.why : "");
      }
      var txt = row.querySelector(".gs-curtext");
      if (txt) row.insertBefore(chip, txt);
      else row.appendChild(chip);
      if (para.score >= 0.6) row.classList.add("gs-suggest");
    });
    /* suggested-keep banner on top of the pane */
    if ((rank.suggested || []).length && !$("assist-note")) {
      var n = el("button", "gs-tact gs-assist-adopt",
                 "adopt the " + rank.suggested.length + " suggested keeps");
      n.id = "assist-note";
      n.type = "button";
      n.addEventListener("click", function () { adopt(); });
      box.insertBefore(n, box.firstChild);
    }
  }

  function adopt() {
    if (!rank) return;
    var byPid = {};
    (rank.pages || []).forEach(function (p) {
      (p.paras || []).forEach(function (pp) { byPid[pp.pid] = pp; });
    });
    (rank.suggested || []).forEach(function (pid) {
      var para = byPid[pid];
      if (!para) return;
      var grp = String(pid).split("#", 1)[0];
      var key = null;
      var rows = document.querySelectorAll("[data-pid]");
      [].forEach.call(rows, function (row) {
        if (row.getAttribute("data-pid") !== pid || key) return;
        key = row.getAttribute("data-para");
      });
      if (!key || !window.__curTogglePara) return;
      if (!window.__curIsPicked(key, pid)) window.__curTogglePara(key, pid, true);
    });
    var b = $("assist-note");
    if (b) b.textContent = "suggestions ticked — review them above, then Save research";
  }

  /* expose the toggle used by adopt(); defined here to avoid touching
     curate.js's closure internals beyond the two hooks it registers. */
  window.__assistPick = { mark: function (key, pid, on) { /* set below */ } };

  /* ---- the local model pass -------------------------------------------- */
  function modelAvailable() {
    return !!window.GSAssistModel;
  }

  function runModel(btn) {
    if (running || !rank || !modelAvailable()) return;
    running = true;
    btn.disabled = true;
    var orig = btn.textContent;
    var out = $("assist-out");
    if (out) out.textContent = "loading the local model…";
    var onProg = function (p, text) {
      if (out) out.textContent = (text || "loading…") + " (" +
        Math.round((p || 0) * 100) + "%)";
      btn.textContent = orig + " · " + Math.round((p || 0) * 100) + "%";
    };
    window.GSAssistModel.on(onProg);
    window.GSAssistModel.load().then(function (st) {
      var items = (rank.model_shortlist || []).map(function (s) {
        var para = findPara(s.pid);
        return { pid: s.pid, score: s.score, text: para ? para.text : "" };
      }).filter(function (it) { return it.text; }).slice(0, 12);
      if (out) out.textContent = "judging " + items.length +
        " shortlisted paragraphs with " + (st.note || "the local model") + "…";
      var verdicts = [];
      // WebGPU (360M) handles the batch "N=keep" format with reasons;
      // the CPU fallback (135M) gets the per-note YES/NO it can follow.
      var isSmall = st.kind === "cpu";
      var q = rank.question || "";
      var task = isSmall
        ? window.GSAssistModel.judgeYesNo(
            items.map(function (it) { return it.text; }), q,
            function (r) {
              var it = items[r.index];
              if (it) modelVerdicts[it.pid] = {
                pid: it.pid, verdict: r.keep ? "keep" : "burn", why: "" };
              redecorate();
            })
        : window.GSAssistModel.judge(items, q, null);
      return task.then(function (v) {
        running = false;
        btn.disabled = false;
        btn.textContent = orig;
        if (!isSmall) {
          (v || []).forEach(function (x) {
            if (x && x.pid) modelVerdicts[x.pid] = x;
          });
          redecorate();
        }
        var n = Object.keys(modelVerdicts).length;
        if (out) out.textContent = n
          ? "local model judged " + n + " paragraphs — verdict chips added (advisory: the heuristic score stays)"
          : "the model ran but its output was not parseable — heuristic guidance stands";
      });
    }).catch(function (e) {
      running = false;
      btn.disabled = false;
      btn.textContent = orig;
      if (out) out.textContent = "the local model did not load (" +
        String(e && e.message || e).slice(0, 80) + ") — heuristic guidance stands";
    });
  }

  function findPara(pid) {
    var byPid = null;
    if (!rank) return null;
    var pg = (rank.pages || []).filter(function (p) {
      return (p.paras || []).some(function (pp) { return pp.pid === pid; });
    })[0];
    if (!pg) return null;
    return (pg.paras.filter(function (pp) { return pp.pid === pid; })[0]) || null;
  }

  function redecorate() {
    if (!rank) return;
    var box = $("cur-paras");
    if (box) [].forEach.call(box.querySelectorAll(".gs-rankchip"),
                             function (c) { c.remove(); });
    [].forEach.call(document.querySelectorAll(".gs-suggest"),
                    function (r) { r.classList.remove("gs-suggest"); });
    decorate();
  }

  /* ---- the assist strip, injected under the curation tabs --------------- */
  function ensureStrip() {
    var section = $("curate");
    if (!section || $("assist-strip")) return;
    var bar = el("div", "gs-assistbar");
    bar.id = "assist-strip";
    var b1 = el("button", "gs-tact", "Rank against the question");
    b1.type = "button"; b1.id = "assist-rank";
    b1.addEventListener("click", function () {
      b1.disabled = true;
      fetchRank(window.__curRid ? window.__curRid() : "", true).then(function (j) {
        b1.disabled = false;
        if (!j) {
          $("assist-out").textContent =
            "no ranking came back — this run may predate the curation record";
          return;
        }
        redecorate();
        var t = $("assist-target");
        if (t) t.textContent = "suggested: " + j.suggested.length +
          " of " + (rank.pages || []).reduce(function (a, p) {
            return a + (p.n || 0); }, 0) + " paragraphs";
      });
    });
    var b2 = el("button", "gs-tact", "Local model pass");
    b2.type = "button"; b2.id = "assist-model";
    b2.addEventListener("click", function () { runModel(b2); });
    var t = el("span", "src", ""); t.id = "assist-target";
    var out = el("span", "src", ""); out.id = "assist-out";
    bar.appendChild(b1);
    bar.appendChild(b2);
    bar.appendChild(t);
    bar.appendChild(out);
    var tabs = section.querySelector(".gs-tabs");
    if (tabs && tabs.nextSibling) section.insertBefore(bar, tabs.nextSibling);
    else if (tabs) tabs.parentNode.appendChild(bar);
    else section.appendChild(bar);
    if (out) out.textContent =
      "heuristic ranks are server-side and quiet; the model pass runs in your browser (WebGPU, CPU fallback) — the server's GPU is never used";
  }

  /* ---- boot: watch for pane repaints (curate.js repaints in place) ------ */
  var mo = new MutationObserver(function () { decorate(); });
  var pane = $("cur-paras");
  if (pane) {
    mo.observe(pane, { childList: true, subtree: false });
    ensureStrip();
  } else {
    var bodyMo = new MutationObserver(function () {
      var p = $("cur-paras");
      if (p) {
        bodyMo.disconnect();
        mo.observe(p, { childList: true });
        ensureStrip();
      }
    });
    bodyMo.observe(document.body, { childList: true, subtree: true });
  }
  window.__assistPick = {
    rank: fetchRank,
    decorate: decorate,
    verdicts: function () { return modelVerdicts; },
  };
  /* per-run reset: curation.js calls this when the pane switches runs */
  window.__assistReset = function () {
    rank = null; rankRid = null; modelVerdicts = {}; running = false;
    redecorate();
    var out = $("assist-out");
    if (out) out.textContent = "";
    var t = $("assist-target");
    if (t) t.textContent = "";
  };
})();
