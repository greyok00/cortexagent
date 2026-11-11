/* portal-v2.js - v0.2.0 workflow adaptation, additive over the legacy code.
   Decorates each cited source row with a "preview" affordance and opens the
   framework inspector with that source's distilled read from Evidence read.
   Plain source links behave exactly as before; the legacy render handlers
   are untouched (a MutationObserver re-decorates after each render). */
(function () {
  "use strict";

  var list = document.getElementById("srcs");
  var panel = document.getElementById("gs-insp");
  var body = document.getElementById("gs-insp-body");
  var title = document.getElementById("gs-insp-title");
  if (!list || !panel || !body || !title || !window.ElWorkflow) return;

  function norm(u) {
    return String(u || "").replace(/^https?:\/\//i, "").replace(/\/+$/, "").toLowerCase();
  }

  // source URL → its Evidence read block (the renders share hrefs)
  function evidenceMap() {
    var map = {};
    [].forEach.call(document.querySelectorAll("#researchtext .rtsrc"), function (blk) {
      var a = blk.querySelector(".src a[href]");
      if (a) map[norm(a.getAttribute("href"))] = blk;
    });
    return map;
  }

  function decorate() {
    [].forEach.call(list.children, function (li) {
      if (!li.querySelector("a[href]")) return;
      if (li.querySelector("button.el-src-preview")) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "el-src-preview";
      btn.textContent = "Preview";
      btn.setAttribute("aria-label", "Preview the distilled read for this source");
      li.appendChild(btn);
    });
  }

  function close() { window.ElWorkflow.closeInspector("#gs-insp"); }

  function open(li) {
    var a = li.querySelector("a[href]");
    var href = a ? a.getAttribute("href") : "";
    var blk = evidenceMap()[norm(href)];
    title.textContent = blk && blk.querySelector("h4")
      ? blk.querySelector("h4").textContent
      : (a ? a.textContent : "Source preview");
    body.textContent = "";
    if (blk) {
      body.appendChild(blk.cloneNode(true));
    } else {
      var note = document.createElement("p");
      note.className = "el-inspector-empty";
      note.textContent = "No distilled read for this source yet - the engine " +
        "ranked it for the guide but the read view did not include it.";
      body.appendChild(note);
    }
    window.ElWorkflow.openInspector("#gs-insp");
  }

  list.addEventListener("click", function (ev) {
    var btn = ev.target.closest("button.el-src-preview");
    if (btn) open(btn.closest("li"));
  });

  var closer = panel.querySelector("[data-el-inspector-close]");
  if (closer) closer.addEventListener("click", close);
  var scrim = document.querySelector(".el-inspector-scrim");
  if (scrim) scrim.addEventListener("click", close);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && panel.classList.contains("is-open")) close();
  });

  decorate();
  new MutationObserver(decorate).observe(list, { childList: true });
})();