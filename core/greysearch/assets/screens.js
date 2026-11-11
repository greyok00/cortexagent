/* screens.js — portal screen state machine + floating pill.
   Pairs with screens.css. Wraps the legacy panels (#prog, #res, and the
   search zone) into stacked screens at load; reparenting preserves every
   event listener, so submit / SSE / history / build handlers keep working.
   Sets body[data-screen] = search|progress|results; screens.css owns the
   visuals. The legacy display writes stay untouched (screens.css pins the
   panels with !important, an author-important rule beats inline styles). */
(function () {
  "use strict";

  var SCREENS = ["search", "progress", "results"];

  function $(id) { return document.getElementById(id); }

  // ---- wrap the three zones (idempotent; safe on double include) --------
  function wrap(screenName, anchorIds, host) {
    if (host.querySelector(':scope > .screen[data-screen="' + screenName + '"]')) return;
    var sec = document.createElement("div");
    sec.className = "screen";
    sec.dataset.screen = screenName;
    var nodes = [];
    anchorIds.forEach(function (sel) {
      Array.prototype.forEach.call(host.querySelectorAll(sel), function (n) {
        if (!n.closest(".screen")) nodes.push(n);
      });
    });
    if (!nodes.length) return;
    // insert the screen AT the anchor's position FIRST (node identity is
    // preserved by reparenting; the listener set never moves)
    host.insertBefore(sec, nodes[0]);
    nodes.forEach(function (n) { sec.appendChild(n); });
    return sec;
  }

  var host = document.querySelector(".wrap") || document.body;
  wrap("search", [".brand", ".tag", "#f", ".depth-row", "#hist"], host);
  wrap("progress", ["#prog"], host);
  wrap("results", ["#res"], host);
  var screensHost = host.querySelector(".screens") ? host
    : (function () {
        // screens.css needs the .screens grid wrapper around all screens
        var g = document.createElement("div");
        g.className = "screens";
        host.insertBefore(g, host.firstChild);
        g.appendChild(host.querySelector(".screen[data-screen=search]"));
        g.appendChild(host.querySelector(".screen[data-screen=progress]"));
        g.appendChild(host.querySelector(".screen[data-screen=results]"));
        return g;
      })();

  // ---- run-in-flight hold (pass-10 D1 fix) --------------------------------
  // A user submit (Research click or history rerun — the history item
  // dispatches the same form submit event) starts a NEW run. While that run
  // is in flight, a stale "done" snapshot from the legacy reattach blocks in
  // portal/index.html (one copy is re-executed by addHist() on every submit)
  // must NOT flip the body back to results or repaint the old run: that
  // snapshot predates the submit. index.html consults this hold through
  // window.__grHoldResults; the hold clears only when the run's own finish
  // signal ("Guide finished.") or a failure ("Run failed.") lands in #stage.
  var runStartedAt = 0;
  window.__grHoldResults = function () { return runStartedAt > 0; };

  // ---- state ------------------------------------------------------------
  function setScreen(name) {
    if (SCREENS.indexOf(name) < 0) return;
    document.body.dataset.screen = name;
    paintPill();
  }

  function runRunning() {
    // the legacy submit handler sets #fill working while a run is live
    var fill = document.querySelector(".fill");
    return fill ? fill.classList.contains("working") : false;
  }

  // ---- pill -------------------------------------------------------------
  var pill = document.createElement("button");
  pill.id = "gr-pill";
  pill.type = "button";
  pill.setAttribute("aria-label", "Screens menu");
  pill.innerHTML =
    '<span class="ring"></span>' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round">' +
    '<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/>' +
    '<circle cx="12" cy="19" r="1.6"/></svg>';
  document.body.appendChild(pill);

  var menu = document.createElement("div");
  menu.id = "gr-pillmenu";
  menu.setAttribute("role", "menu");
  document.body.appendChild(menu);

  function item(label, screenName, active) {
    var b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.className = active ? "active" : "";
    b.innerHTML = '<span class="dot"></span>' + label;
    if (screenName) {
      b.addEventListener("click", function () {
        setScreen(screenName);
        toggleMenu(false);
      });
    }
    return b;
  }

  function screenLabel(s) {
    if (s === "search") return runRunning() ? "Search (run in flight)" : "Search";
    return s === "progress" ? "Progress" : "Results";
  }

  function paintPill() {
    var cur = document.body.dataset.screen || "search";
    pill.dataset.live = cur === "progress" ? "run" : "1";
    menu.innerHTML = "";
    // Search always; Progress only while a run is live or in flight;
    // Results only once a run has landed (this load or a reattach).
    SCREENS.forEach(function (s) {
      if (s === "progress" && cur !== "progress" && !runRunning()) return;
      if (s === "results" && !lastRunLanded) return;
      menu.appendChild(item(screenLabel(s), s, s === cur));
    });
  }

  var lastRunLanded = false;

  function toggleMenu(force) {
    var open = typeof force === "boolean"
      ? force : !menu.classList.contains("open");
    menu.classList.toggle("open", open);
    if (open) paintPill();
  }
  pill.addEventListener("click", function (e) {
    e.stopPropagation();
    toggleMenu();
  });
  document.addEventListener("click", function (e) {
    if (!menu.contains(e.target)) toggleMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") toggleMenu(false);
  });

  // ---- signals ------------------------------------------------------------
  // any submit (Research click or history click) -> progress screen
  var form = $("f");
  if (form) form.addEventListener("submit", function () {
    /* pass-10 D4: an EMPTY query is rejected by the legacy submit handler
       in portal/index.html (hint into #stage, early return, no run) — but
       this listener fires on the same submit event and would still flip
       body[data-screen] to "progress", stranding the user on an idle
       progress screen with no run. Mirror the legacy validation condition
       here and bail first: an empty query means no screen change, no hold
       stamp, no landing-state reset. A non-empty query (Research click or
       history rerun, which fills the input first) reaches the flip below. */
    var q = document.getElementById("q");
    if (!q || !q.value.trim()) return;
    /* pass-10 D1: a new run is starting — hold the progress screen against
       stale done-run reattach answers until this run's own finish lands */
    runStartedAt = Date.now();
    lastRunLanded = false;
    setScreen("progress");
  });

  // guide-finished signal: the legacy SSE handler writes "Guide finished."
  // into #stage — watch it instead of duplicating SSE plumbing.
  var stage = $("stage");
  if (stage) {
    new MutationObserver(function () {
      var txt = stage.textContent || "";
      if (/Guide finished/i.test(txt)) {
        // the run's own finish signal — safe to land on results now
        lastRunLanded = true;
        runStartedAt = 0;   /* run over: drop the hold (pass-10 D1) */
        paintPill();
        setScreen("results");
      } else if (/Run failed/i.test(txt)) {
        // dead run: drop the hold so a later reattach can land normally
        runStartedAt = 0;
      }
    }).observe(stage, { childList: true, characterData: true, subtree: true });
  }

  // ---- initial state ------------------------------------------------------
  // Reattach like the portal does: an in-flight run -> progress; a done run
  // -> results; otherwise the search screen.
  fetch("/api/latest").then(function (r) { return r.json(); })
    .then(function (j) {
      if (j && j.exists && j.status === "running") {
        setScreen("progress");
      } else if (j && j.exists && j.status === "done") {
        // a reattach of a finished run keeps today's behavior: results
        // visible; the pill is the way back to the search screen
        lastRunLanded = true;
        paintPill();
        setScreen("results");
      } else {
        setScreen("search");
      }
    })
    .catch(function () { setScreen("search"); });
})();