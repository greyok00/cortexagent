/* screens.ui.js — built guide site: floating pill + section menu.
   The pill appears once the reader scrolls past the title area (slides up),
   the menu offers Back to top plus the page's section headings (cap 12,
   "and N more" note below). All styling in screens.ui.css; both shipped by
   ensure_kit at wiring time. */
(function () {
  "use strict";

  var pill = document.createElement("button");
  pill.type = "button";
  pill.className = "el-screens-pill";
  pill.setAttribute("aria-label", "Sections menu");
  pill.innerHTML = '<span class="ring"></span>' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round">' +
    '<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/>' +
    '<circle cx="12" cy="19" r="1.6"/></svg>';
  document.body.appendChild(pill);

  var menu = document.createElement("nav");
  menu.className = "el-screens-menu";
  menu.setAttribute("aria-label", "In this guide");
  menu.hidden = true;
  document.body.appendChild(menu);

  function headText(h) {
    return (h.textContent || "").replace(/\s+/g, " ").trim();
  }

  function buildMenu() {
    menu.innerHTML = "";
    var top = document.createElement("button");
    top.type = "button";
    top.className = "totop";
    top.textContent = "Back to top";
    top.addEventListener("click", function () {
      var reduce = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduce ? "instant" : "smooth" });
      menu.classList.remove("open");
    });
    menu.appendChild(top);
    var heads = Array.prototype.slice.call(
      document.querySelectorAll("main h2, .col h2, h2")).slice(0, 12);
    heads.forEach(function (h) {
      var sec = h.closest("section, [id]");
      var target = (sec && sec.id) ? "#" + sec.id : null;
      var b = document.createElement("button");
      b.type = "button";
      var label = headText(h).slice(0, 64);
      if (!label) return;
      b.textContent = label;
      b.addEventListener("click", function () {
        var t = target ? document.querySelector(target) : h;
        if (!t) return;
        var reduce = window.matchMedia &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        t.scrollIntoView({ behavior: reduce ? "instant" : "smooth",
                           block: "start" });
        menu.classList.remove("open");
      });
      menu.appendChild(b);
    });
    var all = document.querySelectorAll("main h2, .col h2, h2");
    if (all.length > 12) {
      var note = document.createElement("div");
      note.style.cssText = "font:500 .78rem var(--sans);opacity:.7;" +
        "padding:4px 12px 8px";
      note.textContent = "and " + (all.length - 12) + " more sections";
      menu.appendChild(note);
    }
  }

  buildMenu();
  menu.hidden = false;

  // the pill arrives after the title area scrolls away (240ms slide).
  // A plain scroll signal: IntersectionObserver over full-page containers
  // (main/.col) is always intersecting and misreports on some layout shapes;
  // scrollY past the h1's bottom is a robust, cheap rule.
  var scrollArmed = false;
  function pillOnScroll() {
    var on = window.scrollY > 480; // past masthead/lede on any layout
    if (on !== scrollArmed) {
      scrollArmed = on;
      pill.classList.toggle("on", on);
    }
  }
  window.addEventListener("scroll", pillOnScroll, { passive: true });
  pillOnScroll();

  pill.addEventListener("click", function (e) {
    e.stopPropagation();
    menu.classList.toggle("open");
  });
  document.addEventListener("click", function (e) {
    if (!menu.contains(e.target) && e.target !== pill) {
      menu.classList.remove("open");
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") menu.classList.remove("open");
  });
})();