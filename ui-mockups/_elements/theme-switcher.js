/* ──────────────────────────────────────────────────────────
   THEME SWITCHER — localStorage + URL hash bridge
   ──────────────────────────────────────────────────────────
   1. Read `localStorage['el-theme']` on load (default: 'neutral')
   2. Fall back to URL hash `#theme=<slug>`
   3. Set `document.documentElement.dataset.theme = <slug>`
   4. Wire any `<select id="theme-picker">` to update + persist

   Add a picker to any page:
     <select id="theme-picker">
       <option value="neutral">neutral</option>
       <option value="polaroid">polaroid</option>
       ...
     </select>

   No deps. Drop in anywhere.
*/

(function themeSwitcher() {
  const STORAGE_KEY = 'el-theme';
  const VALID = new Set([
    'neutral', 'polaroid', 'cockpit', 'cockpit-paper', 'console',
    'compact', 'casebook', 'agent-paper', 'agent-pulse',
    'agent-history', 'terminal', 'swiss'
  ]);
  const DEFAULT = 'neutral';

  function readInitial() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && VALID.has(stored)) return stored;
    } catch (_) { /* localStorage disabled */ }
    const hash = (location.hash || '').match(/theme=([a-z\-]+)/);
    if (hash && VALID.has(hash[1])) return hash[1];
    return DEFAULT;
  }

  function apply(slug) {
    if (!VALID.has(slug)) slug = DEFAULT;
    document.documentElement.dataset.theme = slug;
    try { localStorage.setItem(STORAGE_KEY, slug); } catch (_) {}
    // sync any picker on the page
    document.querySelectorAll('[data-theme-picker], #theme-picker').forEach(el => {
      if (el.value !== slug) el.value = slug;
    });
  }

  function wire() {
    // picker <select>
    document.querySelectorAll('[data-theme-picker], #theme-picker').forEach(el => {
      el.addEventListener('change', () => apply(el.value));
    });
    // clickable theme chips [data-set-theme="<slug>"]
    document.querySelectorAll('[data-set-theme]').forEach(el => {
      el.addEventListener('click', () => apply(el.dataset.setTheme));
    });
    // listen for hashchange
    window.addEventListener('hashchange', () => {
      const m = (location.hash || '').match(/theme=([a-z\-]+)/);
      if (m && VALID.has(m[1])) apply(m[1]);
    });
  }

  // expose for programmatic use
  window.elTheme = { apply, list: () => Array.from(VALID), DEFAULT };

  document.addEventListener('DOMContentLoaded', () => {
    apply(readInitial());
    wire();
  });
  // also run now in case DOMContentLoaded already fired
  if (document.readyState !== 'loading') {
    apply(readInitial());
    wire();
  }
})();
