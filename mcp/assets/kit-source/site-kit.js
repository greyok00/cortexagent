


(function themeSwitcher() {
  const STORAGE_KEY = 'el-theme';
  const VALID = new Set([
    'neutral', 'polaroid', 'cockpit', 'cockpit-paper', 'console',
    'compact', 'casebook', 'agent-paper', 'agent-pulse',
    'agent-history', 'terminal', 'swiss',
    'bespoke', 'torque', 'umami', 'aurora'
  ]);
  const DEFAULT = 'polaroid';  // kit default (doc paper)

  function readInitial() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && VALID.has(stored)) return stored;
    } catch (_) {  }
    const hash = (location.hash || '').match(/theme=([a-z\-]+)/);
    if (hash && VALID.has(hash[1])) return hash[1];
    return DEFAULT;
  }

  function apply(slug) {
    if (!VALID.has(slug)) slug = DEFAULT;
    document.documentElement.dataset.theme = slug;
    try { localStorage.setItem(STORAGE_KEY, slug); } catch (_) {}
    
    document.querySelectorAll('[data-theme-picker], #theme-picker').forEach(el => {
      if (el.value !== slug) el.value = slug;
    });
  }

  function wire() {
    
    document.querySelectorAll('[data-theme-picker], #theme-picker').forEach(el => {
      el.addEventListener('change', () => apply(el.value));
    });
    
    document.querySelectorAll('[data-set-theme]').forEach(el => {
      el.addEventListener('click', () => apply(el.dataset.setTheme));
    });
    
    window.addEventListener('hashchange', () => {
      const m = (location.hash || '').match(/theme=([a-z\-]+)/);
      if (m && VALID.has(m[1])) apply(m[1]);
    });
  }

  
  window.elTheme = { apply, list: () => Array.from(VALID), DEFAULT };

  document.addEventListener('DOMContentLoaded', () => {
    apply(readInitial());
    wire();
  });
  
  if (document.readyState !== 'loading') {
    apply(readInitial());
    wire();
  }
})();


/* ── kit add-ons, appended to the framework's switcher ────────────────────────
   1. A picker that injects itself. The kit is inlined into hundreds of generated pages,
      so nothing may depend on hand-editing each one: if the page has the nav the kit
      expects, the picker appears in it, and every page of every site gains the switcher
      at once.
   2. Figure numbering. The reference page numbered its figures ("Figure 2") because a
      caption is much easier to refer to when it has a name. Numbers are assigned in
      document order at load, so a page that gains a figure renumbers itself.          */
(function () {
  function picker() {
    // Fall through the shapes a site actually has. The study and the kit's own pages use
    // <nav class="main">, but a site that never went through the kit often has a bare
    // <nav> or only a <header>; without the fallbacks the picker would silently not appear
    // on exactly the sites the kit is being added to. Last resort is a small fixed chip,
    // which is worse-looking but never invisible.
    var nav = document.querySelector('nav.main .wrap') || document.querySelector('nav.main')
           || document.querySelector('header nav') || document.querySelector('nav')
           || document.querySelector('header') || document.body;
    if (!nav || nav.querySelector('.themepick')) return;
    var float = (nav === document.body);
    var wrap = document.createElement('span');
    wrap.className = 'themepick' + (float ? ' float' : '');
    var lab = document.createElement('label');
    lab.className = 'vhide';
    lab.textContent = 'Theme';
    var sel = document.createElement('select');
    sel.id = 'theme-picker';
    sel.setAttribute('aria-label', 'Theme');
    (window.elTheme ? elTheme.list() : ['neutral']).forEach(function (t) {
      var o = document.createElement('option');
      o.value = t; o.textContent = t;
      sel.appendChild(o);
    });
    sel.value = (document.documentElement.dataset.theme || 'neutral');
    sel.addEventListener('change', function () { elTheme.apply(sel.value); });
    wrap.appendChild(lab); wrap.appendChild(sel);
    nav.appendChild(wrap);
  }
  function numberFigures() {
    var i = 0;
    document.querySelectorAll('figure').forEach(function (f) {
      if (f.querySelector(':scope > .fignum')) return;
      i++;
      var s = document.createElement('span');
      s.className = 'fignum';
      s.textContent = 'Figure ' + i;
      f.insertBefore(s, f.firstChild);
    });
  }
  function run() { picker(); numberFigures(); }
  document.addEventListener('DOMContentLoaded', run);
  if (document.readyState !== 'loading') run();
})();
