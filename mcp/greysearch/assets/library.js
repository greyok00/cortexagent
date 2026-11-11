/* Greysearch library logic — loads /api/library, paints cards, opens records
   in the house inspector drawer, searches via /api/library/search, browses
   via /api/library/records, exports record markdown/JSON. No framework. */
(function () {
  "use strict";
  var D = document;
  var $ = function (s) { return D.querySelector(s); };

  var state = { dbs: [], cat: "", q: "" };

  var CATS = {
    "security": ["linux-hardening", "firewalls", "malware-defense", "endpoint-security", "python-security", "devsecops", "crypto-vault", "network-vitals", "malware-lab"],
    "ir": ["ir-playbook"],
    "threat": ["apt-threats", "pentest", "pentest-tools"],
    "mobile": ["android-malware"],
    "game": ["gamebuild", "game-sim-design", "game-3d-pipeline"],
    "web": ["web-design", "ui-ux"],
    "ai": ["llm-ops", "prompt-ops", "heuristics-2", "image-gen"],
    "legal": ["az-legal-rights", "az-courts"]
  };

  function catFor(name) {
    for (var c in CATS) if (CATS[c].indexOf(name) >= 0) return c;
    return "";
  }

  function hostList(hosts) {
    return Object.keys(hosts).sort(function (a, b) { return hosts[b] - hosts[a]; }).slice(0, 4);
  }

  /* ---------- record reader (house inspector drawer) ---------- */
  function recordMarkdown(r, dbName) {
    return "# " + (r.t || "record") + "\n\n" +
      "- db: " + (r.db || dbName || "?") + "\n" +
      "- id: " + r.i + "\n" +
      "- source: " + (r.u || r.src || "local") + "\n" +
      "- verdict: " + (r.band || "n/a") + "\n\n" + (r.x || "") + "\n";
  }

  function openRecord(dbName, r) {
    var body = $("#gs-libinsp-body");
    $("#gs-libinsp-title").textContent =
      (r.t || "record").slice(0, 64) + " · " + (r.db || dbName);
    var src = r.u || r.src || "local";
    var isHttp = /^https?:\/\//.test(src);
    var meta = '<div class="lib-meta">id ' + r.i + " · " + (r.src || "web") +
      " · cos " + (r.cos != null ? r.cos : "—") +
      (r.band ? " · band " + r.band : "") + "<br>src: " +
      (isHttp
        ? '<a href="' + src + '" target="_blank" rel="noopener">' + String(src).slice(0, 88) + "</a>"
        : String(src).slice(0, 88)) + "</div>";
    var doc = D.createElement("div");
    doc.className = "gs-lib-doc";
    doc.innerHTML = meta + '<h4>Excerpt</h4><div class="lib-body"></div>';
    doc.querySelector(".lib-body").textContent = String(r.x || "").slice(0, 2600);
    body.innerHTML = "";
    body.appendChild(doc);

    var mdText = recordMarkdown(r, dbName);
    var mdBtn = $("#lib-md"), cpBtn = $("#lib-copy"), jsA = $("#lib-json");
    mdBtn.hidden = cpBtn.hidden = jsA.hidden = false;
    jsA.href = "data:application/json;charset=utf-8," +
      encodeURIComponent(JSON.stringify(r, null, 2));
    jsA.download = (r.db || dbName) + "-" + (r.i || "rec") + ".json";
    mdBtn.onclick = function () {
      var blob = new Blob([mdText], { type: "text/markdown" });
      var a = D.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (r.db || dbName) + "-" + (r.i || "rec") + ".md";
      a.click();
      URL.revokeObjectURL(a.href);
    };
    cpBtn.onclick = function () {
      if (navigator.clipboard) navigator.clipboard.writeText(mdText);
    };
    if (window.ElWorkflow) ElWorkflow.openInspector("#gs-libinsp");
  }

  /* ---------- cards + record panes ---------- */
  function dbCard(d) {
    var el = D.createElement("article");
    el.className = "gs-lib-card";
    el.setAttribute("data-db", d.name);
    var h = D.createElement("h3");
    var a = D.createElement("a");
    a.href = "#";
    a.textContent = d.name;
    h.appendChild(a);
    var n = D.createElement("div");
    n.className = "gs-lib-n";
    n.textContent = d.n + " records · " + Object.keys(d.hosts).length + " sources";
    var hosts = D.createElement("div");
    hosts.className = "gs-lib-hosts";
    hostList(d.hosts).forEach(function (hn) {
      var c = D.createElement("span");
      c.className = "gs-lib-chip";
      c.textContent = hn;
      c.title = d.hosts[hn] + " records";
      hosts.appendChild(c);
    });
    var open = D.createElement("button");
    open.className = "gs-lib-open";
    open.type = "button";
    open.textContent = "Browse records";
    open.setAttribute("aria-expanded", "false");
    open.setAttribute("aria-controls", "librecs-" + d.name.replace(/[^a-z0-9-]/g, "_"));
    var pane = D.createElement("div");
    pane.className = "gs-lib-recs";
    pane.id = "librecs-" + d.name.replace(/[^a-z0-9-]/g, "_");
    open.addEventListener("click", function () {
      var shown = pane.classList.toggle("is-open");
      open.setAttribute("aria-expanded", shown ? "true" : "false");
      if (shown && !pane.dataset.loaded) {
        pane.dataset.loaded = "1";
        fillRecords(pane, d.name);
      }
    });
    el.appendChild(h); el.appendChild(n); el.appendChild(hosts);
    el.appendChild(open); el.appendChild(pane);
    return el;
  }

  function recordRow(dbName, r) {
    var b = D.createElement("button");
    b.className = "gs-lib-rec";
    b.type = "button";
    var title = D.createElement("b");
    title.textContent = (r.t || "").slice(0, 110) || "(untitled record)";
    var meta = D.createElement("small");
    meta.textContent = r.i + " · " + (r.src || "web");
    b.appendChild(title); b.appendChild(meta);
    b.addEventListener("click", function () { openRecord(dbName, r); });
    return b;
  }

  function fillRecords(pane, dbName) {
    fetch("/api/library/records?db=" + encodeURIComponent(dbName) + "&offset=0&limit=30")
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) throw new Error(j.error);
        pane.innerHTML = "";
        (j.records || []).forEach(function (r) {
          pane.appendChild(recordRow(dbName, r));
        });
        if (!(j.records || []).length) {
          pane.innerHTML = '<span class="src">no records</span>';
        }
      })
      .catch(function (e) {
        pane.innerHTML = '<span class="src">load failed: ' + String(e).slice(0, 70) + "</span>";
      });
  }

  /* ---------- search ---------- */
  function runSearch(q) {
    state.q = q;
    fetch("/api/library/search?k=14&q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) throw new Error(j.error);
        paintHits(j.hits || [], j.q || q);
      })
      .catch(function (e) { paintHitsErr(String(e).slice(0, 120)); });
  }

  function paintHits(hits, q) {
    var box = $("#lib-hitsbox");
    var sec = $("#lib-hits");
    $("#lib-hitsmeta").textContent = hits.length + " hits · q: " + q;
    box.innerHTML = "";
    hits.forEach(function (h) {
      var el = D.createElement("div");
      el.className = "gs-lib-hit";
      var band = D.createElement("div");
      band.className = "lib-band";
      band.setAttribute("data-band", h.band || "lex-only");
      band.textContent = h.i + " · " + (h.db || "?") +
        " · cos " + (h.cos != null ? h.cos : "—") + " · " + (h.band || "lex-only");
      var t = D.createElement("h4");
      t.textContent = h.t || "(untitled)";
      var x = D.createElement("p");
      x.textContent = String(h.x || "").slice(0, 320);
      el.appendChild(band); el.appendChild(t); el.appendChild(x);
      el.addEventListener("click", function () { openRecord(h.db, h); });
      box.appendChild(el);
    });
    sec.hidden = !hits.length;
  }

  function paintHitsErr(msg) {
    var sec = $("#lib-hits"), box = $("#lib-hitsbox");
    sec.hidden = false;
    $("#lib-hitsmeta").textContent = "";
    box.innerHTML = '<p class="gs-note">search failed: ' + msg + "</p>";
  }

  /* ---------- boot ---------- */
  function paintLibrary() {
    fetch("/api/library")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        if (!Array.isArray(list)) throw new Error(list.error || "bad payload");
        state.dbs = list;
        var grid = $("#lib-grid");
        grid.innerHTML = "";
        $("#lib-empty").hidden = list.length > 0;
        list.filter(function (d) {
          return !state.cat || (CATS[state.cat] || []).indexOf(d.name) >= 0;
        }).forEach(function (d) { grid.appendChild(dbCard(d)); });
      })
      .catch(function (e) {
        $("#lib-empty").hidden = false;
        $("#lib-empty").innerHTML = "<p>Library unavailable: " + String(e).slice(0, 90) + "</p>";
      });
  }

  D.querySelectorAll(".gs-lib-cat").forEach(function (b) {
    b.addEventListener("click", function () {
      D.querySelectorAll(".gs-lib-cat").forEach(function (x) { x.classList.remove("sel"); });
      b.classList.add("sel");
      state.cat = b.getAttribute("data-libcat") || "";
      paintLibrary();
      if (state.q) runSearch(state.q);
    });
  });

  $("#lib-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = $("#lib-q").value.trim();
    if (q) runSearch(q);
  });

  paintLibrary();
})();
