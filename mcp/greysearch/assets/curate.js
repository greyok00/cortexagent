/* Greysearch curation + research-set draft flow.
   Renders the engine's per-run curation record - every page the run
   actually read with its FULL paragraphs, keywords, and images the engine
   pulled out of each, and the gate verdict shown, not hidden. Material is
   picked by clicking it (no checkbox swarms): a paragraph chip, keyword
   chip, or image card toggles selected on click; toggles carry
   role="checkbox" + aria-checked so keyboard users keep the same
   affordance. The Draft pane saves the picked material into a research
   set, composes a deterministic markdown draft, and the draft itself is an
   editable markdown document - edits are a per-set override the server
   serves verbatim on compose/export until reset.
   Rendering contract: untrusted web content only reaches the page
   as DOM text nodes (textContent) or protocol-checked hrefs; liteMd() is
   the one sanctioned markup renderer and it escapes & and < first. */
(function () {
  "use strict";
  var D = document;
  var $ = function (id) { return D.getElementById(id); };
  var HTTP_URL = /^https?:\/\//i;
  var cur = null, lastRid = null;
  var sel = { paragraphs: {}, keywords: [], images: [] };
  var lastPaintSig = "";
  var imgObj = {};
  var activeSet = "";
  var lastMd = "", lastComp = null, editOpen = false,
      lastSetFor = "";
  /* live-results pane: when the user opens results for a still-running
     run, `cur` holds the live preview; poke() repaints it as pages land */
  var liveMode = false;
  /* uncommitted picks replay from the run's event journal (visualcompanion
     events contract): every selection click appends one JSON event; the
     armed state of fetch-on-command candidates joins it */
  var armedU = {};

  function tnode(t) { return D.createTextNode(t); }
  function el(tag, cls, txt) {
    var e = D.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function hrefEl(url, label) {
    var a = D.createElement("a");
    var u = String(url || "");
    if (HTTP_URL.test(u)) {
      a.href = u; a.target = "_blank"; a.rel = "noopener";
      a.textContent = label || u;
    } else if (u) { a.textContent = label || u; }
    return a;
  }
  function domain(u) {
    return String(u || "").replace(/^https?:\/\//i, "").split("/")[0];
  }
  function imgHrefFromFile(f) {
    var tail = String(f || "").replace(/^.*guides\//, "");
    if (!tail || tail.split("/").some(function (s) {
      return !s || s === "." || s === "..";
    })) return "";
    return "/imgcand/" + tail.split("/").map(encodeURIComponent).join("/");
  }

  /* liteMd() comes from /assets/lite-md.js, the one sanctioned renderer.
     This file only consumes it. */

  /* ---- selection state ----------------------------------------------- */
  function parasTotal() {
    var n = 0, k;
    for (k in sel.paragraphs) n += sel.paragraphs[k].length;
    return n;
  }
  function unit(n, one, many) {
    return n + " " + (n === 1 ? one : many);
  }
  function countLine() {
    return unit(parasTotal(), "paragraph", "paragraphs") + " · " +
      unit(sel.keywords.length, "keyword", "keywords") + " · " +
      unit(sel.images.length, "image", "images") + " checked";
  }
  function toggleIn(arr, v) {
    var i = arr.indexOf(v);
    if (i >= 0) arr.splice(i, 1); else arr.push(v);
  }
  function imgKeyOf(o) { return o && (o.file ? "f:" + o.file : "u:" + o.url); }
  function buildImgObj() {
    imgObj = {};
    (cur.image_candidates || []).forEach(function (c) {
      if (c && c.file) {
        imgObj["f:" + c.file] = { file: c.file, title: c.title || "",
                                  license: c.license || "" };
      }
    });
    (cur.pages || []).forEach(function (p) {
      (p.images || []).forEach(function (im) {
        if (im && HTTP_URL.test(String(im.src || ""))) {
          imgObj["u:" + im.src] = { url: im.src, title: im.title || "",
                                    page: p.url || "",
                                    gated: im.gated === true,
                                    gate_reason: im.gate_reason || "" };
        }
      });
    });
  }

  /* ---- painting ------------------------------------------------------- */
  function chip(decision) {
    var d = el("span");
    var v = String(decision || "").toLowerCase();
    d.className = "gs-chip " +
      (v.indexOf("acc") === 0 || v.indexOf("manual") === 0 ? "ok"
       : v.indexOf("quar") === 0 ? "warn"
       : v ? "fail" : "quiet");
    d.textContent = v || "unjudged";
    return d;
  }

  function paintParas() {
    var box = $("cur-paras");
    box.replaceChildren();
    var pages = (cur && cur.pages) || [];
    if (!pages.length && cur && cur.live) {
      /* opened before the first page landed: the run is seconds old - the
         pane stands and fills as pages land, with the honest live note */
      box.appendChild(el("p", "gs-note",
        "The run is still reading more pages - this pane updates as they " +
        "land, and the whole record arrives when the run finishes."));
      return;
    }
    if (!pages.length) {
      box.appendChild(el("p", "gs-note",
        "No readable paragraphs came out of this run - the pages it read " +
        "had no extractable body text."));
      return;
    }
    if (cur && cur.live) {
      box.appendChild(el("p", "gs-note",
        "The run is still reading more pages - this pane updates as they " +
        "land, and the whole record arrives when the run finishes."));
    }
    pages.forEach(function (p, i) {
      var pg = el("div", "gs-curpage");
      /* selections are namespaced by run: page ids collide per record
         ("pg0" everywhere), so the stored key is runId + ":" + page id */
      var key = lastRid + ":" + p.id;
      var head = el("div", "gs-curpage-h");
      var plist = (p.paragraphs || []);
      var allPicked = !!(sel.paragraphs[key]) &&
        sel.paragraphs[key].length === plist.length;
      if (plist.length) {
        var all = el("button", "gs-curall", allPicked
          ? "drop all of this page" : "keep all of this page");
        all.type = "button";
        all.setAttribute("aria-pressed", String(!!allPicked));
        all.setAttribute("data-pgall", key);
        all.setAttribute("data-u", p.url || "");
        head.appendChild(all);
      }
      if (p.title) head.appendChild(el("h4", null, p.title));
      if (p.url) head.appendChild(hrefEl(p.url, domain(p.url)));
      head.appendChild(chip(p.decision));
      if (p.reason) head.appendChild(el("span", "gs-chip-reason", p.reason));
      pg.appendChild(head);
      plist.forEach(function (q) {
        var on = (sel.paragraphs[key] || []).indexOf(q.id) >= 0;
        var row = el("div", "gs-currow" + (on ? " sel" : ""));
        row.setAttribute("role", "checkbox");
        row.setAttribute("tabindex", "0");
        row.setAttribute("aria-checked", String(!!on));
        row.setAttribute("data-para", key);
        row.setAttribute("data-pid", q.id);
        row.setAttribute("data-u", p.url || "");
        row.appendChild(el("span", "gs-curtext", q.text || ""));
        pg.appendChild(row);
      });
      if (!plist.length) {
        pg.appendChild(el("p", "gs-note", "no paragraphs extracted"));
      }
      if (p.paragraphs_truncated) {
        pg.appendChild(el("p", "gs-note", (cur && cur.live)
          ? "showing the first " + plist.length + " of " +
            (p.paragraphs_total || plist.length) + " paragraphs - the " +
            "full page lands when the run finishes"
          : "paragraph list truncated - the full body is in the run's evidence"));
      }
      box.appendChild(pg);
    });
  }

  function kwChip(k) {
    var on = sel.keywords.indexOf(k) >= 0;
    var b = el("button", "gs-kw", String(k));
    b.type = "button";
    b.setAttribute("aria-pressed", String(!!on));
    if (on) b.classList.add("sel");
    b.setAttribute("data-kw", String(k));
    return b;
  }
  function paintKws() {
    var box = $("cur-kws");
    box.replaceChildren();
    var qk = (cur && cur.query_keywords) || [];
    var pages = (cur && cur.pages) || [];
    var pageKws = 0;
    pages.forEach(function (p) {
      pageKws += (p.keywords || []).length;
    });
    if (qk.length) {
      box.appendChild(el("div", "gs-imgs-h",
        "built from your question - the search terms the engine used"));
      var wp = el("div", "gs-kws");
      qk.forEach(function (k) { wp.appendChild(kwChip(k)); });
      box.appendChild(wp);
    }
    pages.forEach(function (p) {
      if (!(p.keywords || []).length) return;
      var hh = el("div", "gs-curpage-h");
      hh.appendChild(el("h4", null, p.title || p.url || p.id));
      hh.appendChild(chip(p.decision));
      box.appendChild(hh);
      var wrap = el("div", "gs-kws");
      (p.keywords || []).forEach(function (k) { wrap.appendChild(kwChip(k)); });
      box.appendChild(wrap);
    });
    if (!qk.length && !pageKws) {
      box.appendChild(el("p", "gs-note", "no keywords were distilled this run."));
    }
  }

  function imgCardC(key) {
    var o = imgObj[key] || {};
    var on = sel.images.indexOf(key) >= 0;
    var l = el("button", "gs-imgck" + (on ? " sel" : ""));
    l.type = "button";
    l.setAttribute("role", "checkbox");
    l.setAttribute("aria-checked", String(!!on));
    l.setAttribute("data-imgk", key);
    if (o.file) {
      var href = imgHrefFromFile(o.file);
      if (href) {
        var im = D.createElement("img");
        im.alt = ""; im.loading = "lazy"; im.src = href;
        l.appendChild(im);
      }
    } else if (HTTP_URL.test(String(o.url || ""))) {
      var im2 = D.createElement("img");
      im2.alt = ""; im2.loading = "lazy"; im2.src = o.url;
      l.appendChild(im2);
    }
    var sm = D.createElement("small");
    sm.textContent = o.title || o.file || o.url || "";
    l.appendChild(sm);
    if (o.license) {
      var ln = D.createElement("small");
      ln.textContent = o.license;
      l.appendChild(ln);
    }
    if (o.gated) {
      var gt = D.createElement("small");
      var b = D.createElement("b");
      b.textContent = "gate flagged";
      gt.appendChild(b);
      if (o.gate_reason) gt.appendChild(tnode(" - " + o.gate_reason));
      gt.appendChild(tnode(" - use it anyway if it reads right"));
      l.appendChild(gt);
    }
    return l;
  }
  function paintImgs() {
    var box = $("cur-imgs");
    box.replaceChildren();
    var cands = (cur && cur.image_candidates) || [];
    var pgImgs = 0;
    (cur && cur.pages || []).forEach(function (p) {
      (p.images || []).forEach(function (im) {
        if (im && HTTP_URL.test(String(im.src || ""))) pgImgs += 1;
      });
    });
    if (cands.length) {
      box.appendChild(el("div", "gs-imgs-h",
        "licensed image candidates - cleared through the image gate"));
      var g1 = el("div", "gs-imgs");
      cands.forEach(function (c) {
        if (c && c.file && imgObj["f:" + c.file]) {
          g1.appendChild(imgCardC("f:" + c.file));
        }
      });
      box.appendChild(g1);
    }
    if (pgImgs) {
      box.appendChild(el("div", "gs-imgs-h",
        "images found in the pages the run read (unlicensed - no gate provenance)"));
      (cur.pages || []).forEach(function (p) {
        var listed = (p.images || []).filter(function (im) {
          return im && HTTP_URL.test(String(im.src || ""));
        });
        // gate-cleared images lead; flagged logos/tracking sink to the end
        // (the flagged ones still render - the user decides).
        listed.sort(function (a, b) { return (a.gated ? 1 : 0) - (b.gated ? 1 : 0); });
        if (!listed.length) return;
        var hh = el("div", "gs-curpage-h");
        hh.appendChild(el("h4", null, p.title || p.url || p.id));
        box.appendChild(hh);
        var g = el("div", "gs-imgs");
        listed.forEach(function (im) { g.appendChild(imgCardC("u:" + im.src)); });
        box.appendChild(g);
      });
    }
    if (!cands.length && !pgImgs) {
      box.appendChild(el("p", "gs-note",
        "no images found for this topic - the research ships text-only."));
    }
  }

  function paint() {
    var counts = (cur && cur.counts) || {};
    var meta = "read " + unit(counts.pages || 0, "page", "pages") +
      " · gate kept " + (counts.accepted || 0) + " · quarantined " +
      (counts.quarantined || 0) + " · turned away " + (counts.rejected || 0);
    if (counts.unscraped_candidates) {
      meta += " · " + unit(counts.unscraped_candidates,
        "candidate", "candidates") + " never opened";
    }
    if (counts.live_unjudged) {
      meta += " · " + counts.live_unjudged + " not checked yet";
    }
    $("cur-meta").textContent = meta;
    /* paint-on-signature-change hardening: a poller re-fetch of a record
       the page already shows replaces the material panes mid-work - rows
       the user is clicking vanish under the pointer (the add-run flake).
       Repaint only when the record actually differs (a different run, a
       follow-up fetch, changed counts); for an identical record refresh
       only the cheap lines and keep every row where it is. */
    var sig = JSON.stringify([
      lastRid, !!(cur && cur.live), counts,
      ((cur && cur.pages) || []).map(function (p) {
        return [p.id, p.title || "", p.url || "",
                (p.paragraphs || []).map(function (q) { return q.id; }),
                (p.keywords || []).length, (p.images || []).length];
      }),
      (((cur && cur.image_candidates) || []).map(function (c) {
        return c && c.file;
      })),
      (((cur && cur.unscraped_candidates) || []).map(function (u) {
        return (u && u.url) || String(u || "");
      }).slice(0, 400)),
    ]);
    if (sig === lastPaintSig && $("cur-paras").childElementCount > 0) {
      $("cur-count").textContent = countLine();
      $("curate").hidden = false;
      return;
    }
    lastPaintSig = sig;
    paintParas();
    paintKws();
    paintImgs();
    paintUnscraped();
    $("cur-count").textContent = countLine();
    $("curate").hidden = false;
  }

  /* ---- unopened candidates you can order fetched in a follow-up pass --- */
  function paintUnscraped() {
    var box = $("cur-unscraped");
    if (!box) return;
    box.replaceChildren();
    var entries = [];
    var nArmed = 0;
    ((cur && cur.unscraped_candidates) || []).forEach(function (u) {
      var o = (u && typeof u === "object") ? u : {url: String(u || "")};
      if (String(o.url || "")) {
        entries.push(o);
        if (armedU[String(o.url)]) nArmed += 1;
      }
    });
    if (!entries.length) {
      box.appendChild(el("p", "gs-note",
        "Every promising candidate this run surfaced was opened and read " +
        "- nothing is waiting here."));
      return;
    }
    box.appendChild(el("p", "gs-note",
      "The search surfaced these but this run never opened them. Click any " +
      "and press Fetch selected - the engine reads them right away and " +
      "adds their text to this record."));
    var bar = el("div", "gs-ubar");
    var btn = el("button", "gs-tact", "Fetch selected");
    btn.type = "button";
    btn.setAttribute("data-fetchu", "1");
    btn.disabled = nArmed === 0;
    bar.appendChild(btn);
    var status = el("span", "src", "");
    status.setAttribute("data-ustatus", "1");
    bar.appendChild(status);
    box.appendChild(bar);
    if (nArmed) status.textContent = nArmed +
      " picked - fetch them into this record";
    entries.forEach(function (o) {
      var urlv = String(o.url);
      var onU = !!armedU[urlv];
      var row = el("div", "gs-currow gs-cururow");
      row.setAttribute("role", "checkbox");
      row.setAttribute("tabindex", "0");
      row.setAttribute("aria-checked", String(onU));
      row.classList.toggle("sel", onU);
      row.setAttribute("data-uurl", urlv);
      if (HTTP_URL.test(urlv)) row.appendChild(hrefEl(urlv, domain(urlv)));
      else row.appendChild(tnode(urlv));
      if (o.decision) row.appendChild(el("span", "gs-chip quiet",
        String(o.decision)));
      if (o.reason) row.appendChild(el("span", "gs-chip-reason",
        String(o.reason)));
      box.appendChild(row);
    });
  }

  function fetchSelected(btn) {
    if (!cur || !lastRid) return;
    var box = $("cur-unscraped");
    var picked = [].map.call(
      box.querySelectorAll("[data-uurl].sel"),
      function (r) { return r.getAttribute("data-uurl"); });
    if (!picked.length) return;
    var status = box.querySelector("[data-ustatus]");
    btn.disabled = true;
    if (status) {
      status.textContent = "fetching " + picked.length + " page" +
        (picked.length === 1 ? "" : "s") + " in the run's browser…";
    }
    jfetch("/api/fetch-urls/" + encodeURIComponent(lastRid),
      payload("POST", {urls: picked})).then(function (j) {
      var okN = j.fetched || 0;
      var failN = (j.failed || []).length;
      return __curLoad(lastRid, true).then(function () {
        if (status && failN) status.textContent = "";
        if (okN) {
          msg("Fetched " + okN + " page" + (okN === 1 ? "" : "s") +
            " - they're in the record now. Click and save to add them to " +
            "your research set." +
            (failN ? " (" + failN + " not reachable this time.)" : ""));
        } else {
          msg("None of those pages could be fetched this time - they're " +
            "still waiting in the list.");
        }
      });
    }).catch(function (err) {
      btn.disabled = false;
      if (status) status.textContent = "";
      msg("Fetch failed: " + err.message);
    });
  }

  /* ---- events (delegated: the panels are repainted per run) ------------ */
  var section = $("curate");
  var PANES = { paras: "cur-paras", kws: "cur-kws", imgs: "cur-imgs",
                unscraped: "cur-unscraped" };

  function refreshRowVisual(node, on) {
    node.classList.toggle("sel", !!on);
    if (node.getAttribute("role") === "checkbox") {
      node.setAttribute("aria-checked", String(!!on));
    } else if (node.hasAttribute("aria-pressed")) {
      node.setAttribute("aria-pressed", String(!!on));
    }
    var ck = node.closest(".gs-imgck") || node;
    if (ck.classList.contains("gs-imgck")) ck.classList.toggle("sel", !!on);
  }

  function togglePara(key, pid, on) {
    var arr = (sel.paragraphs[key] = sel.paragraphs[key] || []);
    if (on && arr.indexOf(pid) < 0) arr.push(pid);
    if (!on) {
      var i = arr.indexOf(pid);
      if (i >= 0) arr.splice(i, 1);
    }
    if (!arr.length) delete sel.paragraphs[key];
  }

  /* assist.js hooks: the local thinking layer ticks suggestions through
     the same toggle + fires the row visuals + records the click, exactly
     as a manual pick would (visualcompanion journal stays truthful). */
  window.__curTogglePara = function (key, pid, on) {
    togglePara(key, pid, on);
    var node = document.querySelector(
      '[data-para="' + CSS.escape(key) + '"][data-pid="' +
      CSS.escape(pid) + '"]');
    if (node) {
      refreshRowVisual(node, on);
      emitEvent("para", {pid: pid,
                         u: node.getAttribute("data-u") || "", on: on});
    }
    $("cur-count").textContent = countLine();
  };
  window.__curIsPicked = function (key, pid) {
    return ((sel.paragraphs[key] || []).indexOf(pid) >= 0);
  };
  window.__curRid = function () { return lastRid; };

  /* ---- interaction journal: uncommitted picks survive a reload --------
     Every selection click appends one JSON event (visualcompanion events
     contract, ported natively: no iframe, no protocol doc - the run's
     journal IS the contract). Batches of >=8 or after 350ms post to the
     run's journal; failures re-queue the batch (oldest dropped past 256)
     and never surface as an error - the journal must not break curating. */
  var eq = [], eqT = null, eqIn = false;
  function emitEvent(type, extra) {
    if (!lastRid) return;
    var ev = { type: type };
    for (var k in (extra || {})) ev[k] = extra[k];
    eq.push(ev);
    flushEvents();
  }
  function flushEvents(keepalive) {
    if (!eq.length || !lastRid || eqIn) return;
    if (eq.length < 8 && !keepalive) {
      if (eqT) return;
      eqT = window.setTimeout(function () {
        eqT = null;
        flushEvents(true);
      }, 350);
      return;
    }
    if (eqT) { window.clearTimeout(eqT); eqT = null; }
    var batch = eq.splice(0, 64);
    eqIn = true;
    fetch("/api/events/" + encodeURIComponent(lastRid),
      { method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({events: batch}),
        keepalive: !!keepalive }).then(function () {
      eqIn = false;
      if (eq.length >= 8) flushEvents(true);
    }).catch(function () {
      eqIn = false;
      eq = batch.concat(eq).slice(-256);
    });
  }
  window.addEventListener("beforeunload", function () {
    if (eq.length) flushEvents(true);
  });
  D.addEventListener("visibilitychange", function () {
    if (D.visibilityState === "hidden" && eq.length) flushEvents(true);
  });

  function act(node) {
    var before = parasTotal() + sel.keywords.length + sel.images.length;
    if (node.hasAttribute("data-para")) {
      var key = node.getAttribute("data-para");
      var on = !(node.getAttribute("aria-checked") === "true");
      togglePara(key, node.getAttribute("data-pid"), on);
      refreshRowVisual(node, on);
      emitEvent("para", {pid: node.getAttribute("data-pid"),
                         u: node.getAttribute("data-u") || "", on: on});
    } else if (node.hasAttribute("data-kw")) {
      var k = node.getAttribute("data-kw");
      var onK = sel.keywords.indexOf(k) < 0;
      toggleIn(sel.keywords, k);
      refreshRowVisual(node, onK);
      emitEvent("kw", {value: k, on: onK});
    } else if (node.hasAttribute("data-imgk")) {
      var keyI = node.getAttribute("data-imgk");
      var onI = sel.images.indexOf(keyI) < 0;
      toggleIn(sel.images, keyI);
      refreshRowVisual(node, onI);
      emitEvent("img", {key: keyI, on: onI});
    } else if (node.hasAttribute("data-uurl")) {
      /* clicking a candidate only arms Fetch - the URL joins the record
         when the server confirms the page was actually read */
      var onU = node.getAttribute("aria-checked") !== "true";
      node.setAttribute("aria-checked", String(onU));
      node.classList.toggle("sel", onU);
      armedU[node.getAttribute("data-uurl")] = onU;
      emitEvent("uurl", {u: node.getAttribute("data-uurl"), on: onU});
      var ubox = $("cur-unscraped");
      var ubtn = ubox.querySelector("[data-fetchu]");
      var n = ubox.querySelectorAll("[data-uurl].sel").length;
      if (ubtn) ubtn.disabled = !n;
      var ustat = ubox.querySelector("[data-ustatus]");
      if (ustat) ustat.textContent =
        n ? (n + " picked - fetch them into this record") : "";
      return;
    } else if (node.hasAttribute("data-pgall")) {
      var pgidAll = node.getAttribute("data-pgall");
      var bareId = String(pgidAll).split(":").slice(1).join(":");
      var page = ((cur && cur.pages) || []).filter(function (x) {
        return x.id === bareId;
      })[0];
      var onAll = !(node.getAttribute("aria-pressed") === "true");
      var ids = page ? (page.paragraphs || []).map(function (q) {
        return q.id;
      }) : [];
      if (onAll) sel.paragraphs[pgidAll] = ids.slice();
      else delete sel.paragraphs[pgidAll];
      node.setAttribute("aria-pressed", String(onAll));
      node.textContent = onAll ? "drop all of this page"
                               : "keep all of this page";
      emitEvent("para-all", {pid: bareId, u: (page && page.url) || "",
                             on: onAll});
      var box = $("cur-paras");
      var pgNode = node.closest(".gs-curpage");
      [].forEach.call(pgNode.querySelectorAll("[data-para]"), function (r) {
        r.setAttribute("aria-checked", String(onAll));
        r.classList.toggle("sel", onAll);
      });
    } else { return; }
    $("cur-count").textContent = countLine();
    /* the payoff must be visible at the moment of the first pick: slide
       the draft drawer open by itself so "what does selecting do?" is
       answered live, not after a hunt through the top menu */
    if (before === 0 &&
        parasTotal() + sel.keywords.length + sel.images.length > 0 &&
        !$("outrail").classList.contains("open")) {
      openDraftDrawer();
      drawerEmptyHint();
    }
  }

  section.addEventListener("click", function (e) {
    var tab = e.target.closest("[data-curtab]");
    if (tab) {
      [].forEach.call(section.querySelectorAll("[data-curtab]"), function (b) {
        var on = b === tab;
        b.classList.toggle("sel", on);
        b.setAttribute("aria-selected", String(on));
        $(PANES[b.getAttribute("data-curtab")]).hidden = !on;
      });
      return;
    }
    var fb = e.target.closest("[data-fetchu]");
    if (fb) {
      e.preventDefault();
      fetchSelected(fb);
      return;
    }
    if (e.target.closest("a")) return;   /* links inside a row never toggle */
    var node = e.target.closest(
      "[data-para],[data-kw],[data-imgk],[data-uurl],[data-pgall]");
    if (node) act(node);
  });
  section.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var node = e.target.closest(
      "[data-para],[data-kw],[data-imgk],[data-uurl],[data-pgall]");
    if (!node) return;
    e.preventDefault();
    act(node);
  });

  /* ---- research sets: save / append / compose / export ----------------- */
  function msg(t) { $("savemsg").textContent = t; }

  function jfetch(url, opt) {
    return fetch(url, opt).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error((j && j.error) || "the server said " + r.status);
        return j;
      });
    });
  }
  function payload(method, body) {
    return { method: method, headers: { "Content-Type": "application/json" },
             body: JSON.stringify(body || {}) };
  }

  function imgSelPayload() {
    return sel.images.map(function (k) { return imgObj[k] || null; })
      .filter(Boolean);
  }
  function mergeSel(base) {
    var out = { paragraphs: {}, keywords: (base.keywords || []).slice(),
                images: (base.images || []).slice() };
    var pg;
    for (pg in (base.paragraphs || {})) out.paragraphs[pg] = base.paragraphs[pg].slice();
    for (pg in sel.paragraphs) {
      var arr = out.paragraphs[pg] || (out.paragraphs[pg] = []);
      sel.paragraphs[pg].forEach(function (pid) {
        if (arr.indexOf(pid) < 0) arr.push(pid);
      });
    }
    sel.keywords.forEach(function (k) {
      if (out.keywords.indexOf(k) < 0) out.keywords.push(k);
    });
    var have = {};
    out.images.forEach(function (im) { if (im) have[im.file || im.url] = 1; });
    imgSelPayload().forEach(function (im) {
      if (!have[im.file || im.url]) { out.images.push(im); have[im.file || im.url] = 1; }
    });
    out.images = out.images.slice(0, 4000);
    return out;
  }

  /* ---- draft editor: the composed markdown is an editable document -----
     An applied edit is stored on the set (draft_md) and the server serves
     it verbatim on compose/export, so manual deletions hold. "reset to
     selections" clears the override and falls back to the deterministic
     compose from the saved selections. */
  function editorBtn(label, fn) {
    var b = el("button", "gs-tact", label);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }
  function renderOut(setId, comp, name) {
    comp = comp || {};
    lastComp = comp;
    lastMd = String(comp.markdown || "");
    lastSetFor = String(setId);
    var od = $("outdoc"), ed = $("outedit");
    od.hidden = editOpen;
    ed.hidden = !editOpen;
    if (!editOpen) {
      od.innerHTML = window.liteMd(lastMd || "nothing composed");
    } else if (document.activeElement !== ed && ed.value !== lastMd) {
      ed.value = lastMd;
    }
    /* the one publish reveal: research is kept first, so Publish only
       lights up once something was actually saved */
    D.body.classList.add("gs-saved");
    $("pubmenu").hidden = false;
    var act = $("outactions");
    act.replaceChildren();
    if (!editOpen) {
      act.appendChild(editorBtn("edit markdown", openEditor));
    } else {
      act.appendChild(editorBtn("apply edits", applyEditor));
      act.appendChild(editorBtn("discard edits", discardEditor));
    }
    if (comp.draft_override) {
      act.appendChild(editorBtn("reset to selections", resetDraft));
    }
    var again = el("button", "gs-tact", "recompose");
    again.type = "button";
    again.addEventListener("click", saveSet);
    act.appendChild(again);
    var exp = D.createElement("a");
    exp.className = "gs-tact";
    exp.href = "/api/sets/" + encodeURIComponent(String(setId)) + "/export.md";
    exp.setAttribute("download", "");
    exp.textContent = "export .md";
    act.appendChild(exp);
    $("outmeta").textContent = "set: " + (name || setId) +
      (comp.draft_override ? " · hand-edited draft - new selections stay out " +
        "until you press reset" : "");
  }
  function openEditor() {
    editOpen = true;
    renderOut(lastSetFor, lastComp, $("outmeta").textContent
      .replace(/^set: /, "").replace(/ · hand-edited.*$/, ""));
  }
  function applyEditor() {
    var ed = $("outedit");
    var id = lastSetFor || activeSet;
    if (!id) { msg("Apply needs a saved set."); return; }
    var btns = $("outactions");
    [].forEach.call(btns.querySelectorAll("button"), function (b) {
      b.disabled = true;
    });
    msg("Saving your edit…");
    jfetch("/api/sets/" + encodeURIComponent(id),
      payload("PATCH", { draft_md: ed.value })).then(function () {
      return jfetch("/api/sets/" + encodeURIComponent(id) + "/compose",
        payload("POST", {}));
    }).then(function (comp) {
      editOpen = false;
      msg("Edit saved - this draft is what export and publish use now. " +
        "New clicks stay out of it until you press reset.");
      var named = ($("outmeta").textContent
        .replace(/^set: /, "").replace(/ · hand-edited.*$/, "")) || id;
      renderOut(id, comp, named);
    }).catch(function (err) {
      msg("Edit save failed: " + err.message);
      [].forEach.call(btns.querySelectorAll("button"), function (b) {
        b.disabled = false;
      });
    });
  }
  function discardEditor() {
    editOpen = false;
    renderOut(lastSetFor, lastComp, $("outmeta").textContent
      .replace(/^set: /, "").replace(/ · hand-edited.*$/, ""));
    msg("Edits discarded - the draft shows the last applied version.");
  }
  function resetDraft() {
    var id = lastSetFor || activeSet;
    if (!id) return;
    msg("Resetting to your saved selections…");
    jfetch("/api/sets/" + encodeURIComponent(id),
      payload("PATCH", { draft_md: "" })).then(function () {
      return jfetch("/api/sets/" + encodeURIComponent(id) + "/compose",
        payload("POST", {}));
    }).then(function (comp) {
      editOpen = false;
      msg("Draft reset - it is composed from your saved selections again.");
      var named = ($("outmeta").textContent
        .replace(/^set: /, "").replace(/ · hand-edited.*$/, "")) || id;
      renderOut(id, comp, named);
    }).catch(function (err) { msg("Reset failed: " + err.message); });
  }

  async function paintSets() {
    try {
      var j = await jfetch("/api/sets");
      var list = j.sets || [];
      var s = $("setsel");
      var keep = s.value;
      s.replaceChildren();
      s.appendChild(el("option", "", ""));
      s.firstChild.textContent = "new set";
      list.forEach(function (st) {
        var o = D.createElement("option");
        o.value = String(st.set_id || "");
        o.textContent = (st.name || st.set_id) + " (" + (st.runs || 0) + " runs)";
        s.appendChild(o);
      });
      s.value = keep && list.some(function (st) { return st.set_id === keep; })
        ? keep : "";
    } catch (e) { /* the set picker stays a bare "new set" without it */ }
  }

  async function saveSet() {
    if (!cur || !lastRid) {
      msg("Save needs a finished run - its curation record is what gets kept.");
      return;
    }
    if (!sel.images.length && !sel.keywords.length && !parasTotal()) {
      msg("Click at least one paragraph, keyword, or image first.");
      return;
    }
    /* a still-running run has no curation record yet - the honest answer
       is "the moment it finishes", not a bare 404 */
    try {
      var state = await jfetch("/api/run/" + encodeURIComponent(lastRid));
      if (state.status === "running") {
        msg("This run is still reading pages - the record lands the moment " +
            "it finishes, then Save keeps your picks.");
        return;
      }
    } catch (e) { /* unknown run: the save attempt reports honestly */ }
    var btn = $("savebtn");
    btn.disabled = true;
    msg("Saving…");
    var target = $("setsel").value;
    var nameV = ($("setname").value || "").trim();
    /* research keeps expanding: same name = the same set. A save with no
       picker pick but a named set already on disk appends to it instead of
       minting a twin. */
    if (!target && nameV) {
      try {
        var all = await jfetch("/api/sets");
        var same = (all.sets || []).filter(function (s) {
          return String(s.name || "") === nameV;
        });
        if (same.length) target = String(same[0].set_id || "");
      } catch (e) { /* picker-only then */ }
    }
    try {
      if (target) {
        var got = await jfetch("/api/sets/" + encodeURIComponent(target));
        var merged = mergeSel((got.set && got.set.selections) || {});
        await jfetch("/api/sets/" + encodeURIComponent(target) + "/add-run",
          payload("POST", { run_id: lastRid, query: cur.query }));
        await jfetch("/api/sets/" + encodeURIComponent(target),
          payload("PATCH", { selections: merged, run_id: lastRid }));
        activeSet = target;
      } else {
        var made = await jfetch("/api/sets", payload("POST", {
          run_id: lastRid, query: cur.query,
          name: nameV || cur.query || "",
          selections: { paragraphs: sel.paragraphs,
                        keywords: sel.keywords,
                        images: imgSelPayload() }
        }));
        activeSet = String(made.set_id);
        target = activeSet;
      }
      /* an open editor holds unapplied markdown - flush it so nothing the
         user typed is lost on save */
      if (editOpen && target) {
        await jfetch("/api/sets/" + encodeURIComponent(target),
          payload("PATCH", { draft_md: $("outedit").value }));
      }
      var comp = await jfetch("/api/sets/" + encodeURIComponent(target) + "/compose",
        payload("POST", {}));
      editOpen = false;
      var setName = nameV;
      if (!setName) {
        try {
          var again = await jfetch("/api/sets/" + encodeURIComponent(target));
          setName = (again.set && again.set.name) || target;
        } catch (e2) { setName = target; }
      }
      renderOut(target, comp, setName);
      openDraftDrawer();
      msg("Saved. " +
        (comp.draft_override
          ? "Your hand-edited draft is what export uses - new clicks join " +
            "the set, not the draft, until you press reset."
          : "Draft composed from " + (comp.paragraphs_used || 0) +
            " clicked paragraphs. Keep clicking or run more searches into " +
            "this set, or press edit markdown."));
      await paintSets();
      $("setsel").value = target;
    } catch (err) {
      msg("Save failed: " + err.message);
    } finally {
      btn.disabled = false;
    }
  }

  /* opening a set from the picker recomposes it so the rail shows it */
  $("setsel").addEventListener("change", async function () {
    var id = this.value;
    if (!id) return;
    activeSet = id;
    editOpen = false;
    try {
      var comp = await jfetch("/api/sets/" + encodeURIComponent(id) + "/compose",
        payload("POST", {}));
      var named = id;
      try {
        var got = await jfetch("/api/sets/" + encodeURIComponent(id));
        named = (got.set && got.set.name) || id;
      } catch (e) { /* id is fine as the label */ }
      renderOut(id, comp, named);
      msg(comp.draft_override
        ? "Set opened - it carries a hand-edited draft, and that draft is " +
          "what export uses. Clicking material and saving still adds it to " +
          "the set data."
        : "Set opened - its saved selections are what compose. Clicking " +
          "material from THIS run and saving again adds it to the set.");
    } catch (err) {
      msg("Could not open the set: " + err.message);
    }
  });
  $("savebtn").addEventListener("click", function () { saveSet(); });

  /* ---- draft drawer: a hidden right-side menu --------------------------- */
  /* The composed draft is not a squeezed side pane; it slides in full height
     from the top menu's Draft button. A save slides it open - the composed
     draft is the payoff of clicking material. */
  $("drawbtn").addEventListener("click", function (e) {
    e.stopPropagation();
    var dr = $("outrail");
    if (!dr.classList.contains("open")) {
      if (!dr.classList.contains("preopen")) {
        dr.classList.add("preopen");
        void dr.offsetWidth;   /* paint the unslid frame so the slide runs */
      }
      dr.classList.add("open");
      this.setAttribute("aria-expanded", "true");
      dr.scrollTop = 0;
      drawerEmptyHint();
    } else {
      dr.classList.remove("open");
      this.setAttribute("aria-expanded", "false");
    }
  });
  /* the slide is done - retire the preopened frame so the closed drawer
     leaves zero geometry behind */
  $("outrail").addEventListener("transitionend", function (ev) {
    if (ev.target === this && ev.propertyName === "transform" &&
        !this.classList.contains("open")) {
      this.classList.remove("preopen");
    }
  });
  function drawerEmptyHint() {
    if (!lastComp && !editOpen) {
      msg("Select material, then press Save research - the composed draft " +
          "appears here. Sets you already saved open from the picker.");
    }
  }
  function openDraftDrawer() {
    var dr = $("outrail");
    if (dr.classList.contains("open")) return;
    dr.classList.add("preopen");
    void dr.offsetWidth;
    dr.classList.add("open");
    $("drawbtn").setAttribute("aria-expanded", "true");
  }
  function closeDraft() {
    var dr = $("outrail");
    if (dr && dr.classList.contains("open")) {
      dr.classList.remove("open");
      $("drawbtn").setAttribute("aria-expanded", "false");
      /* reduced-motion kills the transition, so transitionend never fires;
         retire the frame at once there, otherwise the fallback window */
      var rm = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.setTimeout(function () { dr.classList.remove("preopen"); },
        rm ? 0 : 260);
    }
  }

  /* ---- new search: leave this run for a fresh form ---------------------- */
  /* The results screen reattaches to the latest run on every load, so the
     only route back to the search screen used to be the brand-pill menu -
     nothing discoverable said "start over". The header button flips the
     screens state machine (screens.js owns it) and puts the cursor in the
     query field, typing ready; the search screen keeps the recent-search
     history, which is what "save this one for later" really is. */
  $("newsearchbtn").addEventListener("click", function () {
    if (window.__grSetScreen) window.__grSetScreen("search");
    window.setTimeout(function () {
      var q = $("q");
      if (q) { q.focus(); if (q.value) q.select(); }
    }, 0);
  });
  /* the draft drawer stays open while you work the list - unlike the
     transient publish drawer, closing is explicit: the Draft button or
     Escape, never a stray click on a paragraph row */
  D.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeDraft();
  });

  /* ---- publish: top-menu drawer ---------------------------------------- */
  /* Build never lives in the document flow - it is one click away in the
     top menu once research was actually saved. */
  $("pubmenu").addEventListener("click", function (e) {
    e.stopPropagation();
    var pr = $("pubrail");
    var open = !pr.classList.contains("open");
    pr.classList.toggle("open", open);
    this.setAttribute("aria-expanded", String(open));
    if (open) closeDraft();
  });
  function closePub() {
    var pr = $("pubrail");
    if (pr) pr.classList.remove("open");
    $("pubmenu").setAttribute("aria-expanded", "false");
  }
  D.addEventListener("click", function (e) {
    var pr = $("pubrail");
    if (!pr || !pr.classList.contains("open")) return;
    if (!pr.contains(e.target) && !e.target.closest("#pubmenu")) closePub();
  });
  D.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePub();
  });

  /* ---- run hookup ------------------------------------------------------ */
  function pageByUrl(u) {
    var url = String(u || "");
    if (!url) return null;
    var cps = (cur && cur.pages) || [];
    for (var i = 0; i < cps.length; i++) {
      if (String(cps[i].url || "") === url) return cps[i];
    }
    return null;
  }

  /* Replay the run's journal onto the loaded record: everything after the
     last save marker, as ABSOLUTE states (idempotent - applying the tail
     twice lands in the same place). Paragraph events recorded against the
     live preview resolve through the page URL, so the final record can
     renumber pages without losing a pick; paragraph position comes from
     the recorded pid's "#p" index. Keyboard-driven picks emit through the
     same act() path. */
  function replayEvents(events) {
    if (!Array.isArray(events) || !events.length || !lastRid || !cur) return;
    var start = 0;
    for (var i = events.length - 1; i >= 0; i--) {
      if (events[i] && events[i].type === "save") { start = i + 1; break; }
    }
    for (i = start; i < events.length; i++) {
      var ev = events[i];
      if (!ev || typeof ev !== "object") continue;
      var t = typeof ev.type === "string" ? ev.type : "";
      if (t === "para" || t === "para-all") {
        var pg = pageByUrl(ev.u);
        if (!pg) continue;
        var n = parseInt(String(ev.pid || "").split("#p")[1], 10);
        if (!(n >= 0)) continue;
        var key = lastRid + ":" + pg.id;
        var pid = pg.id + "#p" + n;
        var arr = sel.paragraphs[key] || (sel.paragraphs[key] = []);
        if (t === "para") {
          var at = arr.indexOf(pid);
          if (ev.on && at < 0) arr.push(pid);
          if (!ev.on && at >= 0) arr.splice(at, 1);
          if (!arr.length) delete sel.paragraphs[key];
        } else if (ev.on) {
          sel.paragraphs[key] = (pg.paragraphs || []).map(function (q) {
            return q.id;
          });
        } else delete sel.paragraphs[key];
      } else if (t === "kw") {
        var k = String(ev.value || "");
        if (!k) continue;
        var ik = sel.keywords.indexOf(k);
        if (ev.on && ik < 0) sel.keywords.push(k);
        if (!ev.on && ik >= 0) sel.keywords.splice(ik, 1);
      } else if (t === "img") {
        var kk = String(ev.key || "");
        if (!/^[fu]:/.test(kk)) continue;
        var ik2 = sel.images.indexOf(kk);
        if (ev.on && ik2 < 0) sel.images.push(kk);
        if (!ev.on && ik2 >= 0) sel.images.splice(ik2, 1);
      } else if (t === "uurl") {
        var u = String(ev.u || "");
        if (!HTTP_URL.test(u)) continue;
        armedU[u] = !!ev.on;
      }
      /* stage lines replay as nothing - they are the run's story; unknown
         types (save markers, capped) also apply as nothing */
    }
  }

  function loadCurPaint(rid, isRetry) {
    var cFetch = fetch("/api/curation/" + encodeURIComponent(rid))
      .then(function (r) { return r.json(); });
    var jFetch = fetch("/api/events/" + encodeURIComponent(rid))
      .then(function (r) { return r.json(); })
      .catch(function () { return null; });
    return Promise.all([cFetch, jFetch]).then(function (pair) {
      var j = pair[0], evj = pair[1];
      if (j && j.exists) {
        cur = j.curation || {};
        liveMode = false;
        if (evj && evj.exists && evj.events && evj.events.length) {
          replayEvents(evj.events);
        }
        buildImgObj();
        paint();
        paintSets();
        return;
      }
      /* a still-running run: the live preview buffer is the pane */
      if (window.__curLive && window.__curLive.open(String(rid))) return;
      /* one retry: right after a portal restart the record can briefly
         read as missing while the server warms up - never show that to a
         user as "the run predates capture" */
      if (!isRetry) {
        window.setTimeout(function () { loadCurPaint(rid, true); }, 2000);
        return;
      }
      cur = null;
      $("cur-meta").textContent = "";
      $("cur-count").textContent = "no curation record for this run - it " +
        "predates the capture; rerun the question to keep its research";
      $("curate").hidden = false;
    }).catch(function () {
      $("curate").hidden = false;
      $("cur-meta").textContent = "";
      $("cur-count").textContent = "curation could not be loaded for this run";
    });
  }
  function resetForRun() {
    activeSet = $("setsel").value || "";
    sel = { paragraphs: {}, keywords: [], images: [] };
    cur = null;
    armedU = {};
    liveMode = false;
    editOpen = false;
    $("outactions").replaceChildren();
  }

  /* ---- the live pane: results build up while the run keeps reading -----
     The inline script holds the data-only buffer (window.__gsLive, fed by
     the stage stream); this side owns the paint, so selection state and
     the journal flow stay in one place. A live pane REPLACES the record
     the moment the final one lands (__curLoad force), and a pick made
     against a live page replays onto the final record by page URL + "#p"
     index. */
  function buildLiveCur() {
    var ls = window.__gsLive;
    var pages = [], acc = 0, qua = 0, rej = 0;
    (ls.pages || []).forEach(function (p) {
      var pp = {};
      for (var k in p) pp[k] = p[k];
      var di = parseInt(String(pp.id || "").replace(/^pg/, ""), 10);
      var dec = (ls.dec && ls.dec[di]) || "";
      if (dec) pp.decision = dec;
      if (dec === "accept") acc += 1;
      else if (dec === "quarantine") qua += 1;
      else if (dec === "reject") rej += 1;
      pages.push(pp);
    });
    return {
      live: true,
      query: ls.query || "",
      counts: {pages: pages.length, accepted: acc, quarantined: qua,
               rejected: rej,
               live_unjudged: Math.max(0, pages.length - acc - qua - rej)},
      pages: pages,
      unscraped_candidates: [],
      image_candidates: [],
    };
  }
  function paintLive(withSets) {
    cur = buildLiveCur();
    buildImgObj();
    paint();
    if (withSets) paintSets();
  }
  window.__curLive = {
    poke: function () {
      if (liveMode && lastRid) paintLive(false);
    },
    isLive: function (rid) {
      return !!liveMode && lastRid === rid;
    },
    open: function (rid) {
      rid = String(rid || "");
      var ls = window.__gsLive;
      if (!ls || ls.rid !== rid) return false;
      /* rid-matched but still-empty buffers OPEN too: the user clicked
         "open results so far" seconds into a run - the pane must stand and
         fill as pages land, never strand an empty results screen while
         the first scrape is still seconds away */
      if (rid !== lastRid) resetForRun();
      lastRid = rid;
      liveMode = true;
      paintLive(true);
      return true;
    },
  };

  window.__curLoad = function (rid, force) {
    if (!rid) return Promise.resolve();
    if (rid === lastRid && cur && !force) {
      $("cur-count").textContent = countLine();
      return Promise.resolve();
    }
    var sameRun = rid === lastRid && cur;
    lastRid = rid;
    if (!sameRun) {
      resetForRun();
      /* the thinking layer's state is per-run: verdicts and paints must
         never leak onto the next run's paragraphs */
      if (window.__assistReset) window.__assistReset();
    }
    return loadCurPaint(rid, false);
  };
  if (window.__curWant) {
    var want = window.__curWant;
    window.__curWant = null;
    window.__curLoad(want);
  }
})();