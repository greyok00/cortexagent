/* greyok-ui-framework v0.2.0 - workflow behaviors (stage, inspector, assistant).
   Same contract as elements.js: no timers except streaming cadence opt-in,
   no network, honors prefers-reduced-motion. */
(function () {
  'use strict';

  var REDUCED = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : { matches: false };

  /* ── stage rail / ladder: data-state → is-* classes ─────────────────────── */
  var STATES = ['queued', 'running', 'active', 'done', 'stale'];

  function applyStage(el) {
    var state = el.getAttribute('data-state') || '';
    el.classList.remove('is-queued', 'is-running', 'is-active', 'is-done', 'is-stale');
    if (STATES.indexOf(state) >= 0) el.classList.add('is-' + state);
  }

  function initStages(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll('.el-stage, .el-ladder-step, .el-pt-chunk');
    Array.prototype.forEach.call(nodes, applyStage);
  }

  function setStage(sel, state) {
    var el = document.querySelector(sel);
    if (!el) return false;
    el.setAttribute('data-state', state);
    applyStage(el);
    return true;
  }

  /* ── inspector: open/close in place, scrim shared per document ──────────── */
  function ensureScrim() {
    var scrim = document.querySelector('.el-inspector-scrim');
    if (!scrim) {
      scrim = document.createElement('div');
      scrim.className = 'el-inspector-scrim';
      document.body.appendChild(scrim);
    }
    return scrim;
  }

  function openInspector(sel) {
    var panel = document.querySelector(sel);
    if (!panel) return false;
    if (!panel.classList.contains('is-docked')) ensureScrim().classList.add('is-open');
    panel.classList.add('is-open');
    var focusables = panel.querySelector('button, [href], input, select, textarea');
    if (focusables) focusables.focus();
    return true;
  }

  function closeInspector(sel) {
    var panel = document.querySelector(sel);
    if (!panel) return false;
    panel.classList.remove('is-open');
    var scrim = document.querySelector('.el-inspector-scrim');
    if (scrim) scrim.classList.remove('is-open');
    return true;
  }

  /* ── assistant: plan-first + streaming cadence helpers ──────────────────── */
  function setPlan(sel, steps) {
    var plan = document.querySelector(sel);
    if (!plan) return false;
    var rail = plan.querySelector('.el-stage-rail, .el-ladder');
    if (!rail) return false;
    Array.prototype.forEach.call(rail.children, function (row, i) {
      var state = (steps && steps[i]) || 'queued';
      row.setAttribute('data-state', state);
      applyStage(row);
    });
    return true;
  }

  function setStreaming(msgEl, on) {
    if (!msgEl) return false;
    if (REDUCED.matches) return true; /* cadence is the one optional motion */
    msgEl.classList.toggle('is-streaming', !!on);
    return true;
  }

  window.ElWorkflow = {
    initStages: initStages,
    setStage: setStage,
    openInspector: openInspector,
    closeInspector: closeInspector,
    setPlan: setPlan,
    setStreaming: setStreaming,
    reducedMotion: function () { return REDUCED.matches; }
  };

  if (document.readyState !== 'loading') initStages(document);
  else document.addEventListener('DOMContentLoaded', function () { initStages(document); });
})();