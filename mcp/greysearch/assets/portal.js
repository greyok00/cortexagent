/* Greysearch portal - presentation layer.
   Reads the real stage events the legacy inline script already receives
   (a single __gsStage hook), paints the run ladder from those events.
   It never invents a stage: with no events the ladder stays at step one
   and says "waiting". One theme only: the night console ships fixed in
   index.html (data-theme="master"); the old light/dark toggle is gone. */
(function () {
  "use strict";

  var D = document;
  try { localStorage.removeItem("greysearch-ui-theme"); } catch (e) { /* private mode */ }

  /* ---- the run ladder --------------------------------------------------- */
  var ladder = D.getElementById("stages");
  if (!ladder) return;
  var items = [].slice.call(ladder.querySelectorAll("li[data-stage]"));
  var order = items.map(function (li) { return li.getAttribute("data-stage"); });
  var index = {};

  function detail(stage, d) {
    d = d || {};
    if (stage === "start") return d.query ? String(d.query).slice(0, 70) : "query sent";
    if (stage === "search_done") return (d.pool != null ? d.pool : "?") + " promising sources";
    if (stage === "scraped") {
      var n = d.n != null ? "source " + d.n : "reading";
      var t = d.title ? " · " + String(d.title).slice(0, 54) : "";
      return n + t;
    }
    if (stage === "judged") {
      var kept = d.accepted_so_far != null ? d.accepted_so_far : "?";
      var seen = d.judged_so_far != null ? d.judged_so_far : 0;
      var of = d.of != null ? d.of : "?";
      return kept + " kept · " + seen + " of " + of + " judged";
    }
    if (stage === "images") return typeof d.count === "number" ? d.count + " candidates" : "gathering";
    if (stage === "audit") return "checking the draft";
    if (stage === "guide") return "assembling the document";
    return "";
  }

  function paint(stage, data) {
    var at = order.indexOf(stage);
    if (at < 0) return;
    items.forEach(function (li, i) {
      var state = i < at ? "done" : i === at ? "active" : "";
      li.setAttribute("data-state", state);
      li.removeAttribute("aria-current");
      if (state === "active") li.setAttribute("aria-current", "step");
      var slot = li.querySelector(".st-d");
      if (slot) {
        if (i === at) slot.textContent = detail(stage, data);
        else if (i < at) slot.textContent = "done";
        else slot.textContent = "";
      }
    });
  }

  function reset() {
    items.forEach(function (li) {
      li.removeAttribute("data-state");
      li.removeAttribute("aria-current");
      var slot = li.querySelector(".st-d");
      if (slot) slot.textContent = "";
    });
  }

  function finish() {
    items.forEach(function (li) {
      li.setAttribute("data-state", "done");
      li.removeAttribute("aria-current");
      var slot = li.querySelector(".st-d");
      if (slot) slot.textContent = "done";
    });
  }

  /* the one hook the legacy stream handler calls, with the real event */
  window.__gsStage = function (ev) {
    if (!ev || !ev.stage) return;
    if (ev.stage === "__end__") { finish(); return; }
    if (ev.stage === "error") {
      var active = ladder.querySelector('li[data-state="active"]');
      if (active) {
        active.setAttribute("data-state", "failed");
        var slot = active.querySelector(".st-d");
        if (slot) slot.textContent = "stopped";
      }
      return;
    }
    paint(ev.stage, ev.data);
  };

  var form = D.getElementById("f");
  if (form) {
    form.addEventListener("submit", function () {
      var q = D.getElementById("q");
      if (q && q.value.trim()) {
        reset();
        paint("start", { query: q.value.trim() });
      }
    });
  }

  /* the guide path is a run detail, not an address book: show only the
     file's place under guides/, never the machine's absolute path */
  var pathLine = D.getElementById("path");
  if (pathLine) {
    new MutationObserver(function () {
      var txt = (pathLine.textContent || "").replace(/^guide:\s*/, "").trim();
      if (!txt) return;
      var parts = txt.split("/").filter(Boolean);
      var tail = parts.slice(-2).join("/");
      var want = "guide: guides/" + tail;
      if (pathLine.textContent !== want) pathLine.textContent = want;
    }).observe(pathLine, { childList: true, characterData: true, subtree: true });
  }

  var stage = D.getElementById("stage");
  if (stage) {
    stage.setAttribute("aria-live", "polite");
    new MutationObserver(function () {
      var txt = stage.textContent || "";
      if (/Run failed/i.test(txt)) {
        var active = ladder.querySelector('li[data-state="active"]');
        if (active) {
          active.setAttribute("data-state", "failed");
          var slot = active.querySelector(".st-d");
          if (slot) slot.textContent = "stopped";
        }
      }
    }).observe(stage, { childList: true, characterData: true, subtree: true });
  }
})();
