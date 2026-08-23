/* ──────────────────────────────────────────────────────────
   ELEMENTS.JS — interactive hooks for el-* primitives
   ──────────────────────────────────────────────────────────
   Drop-in. No deps. Each hook is mounted once on DOMContentLoaded
   and only attaches handlers to elements currently on the page.
*/

(function Elements() {
  'use strict';

  // ── helpers ──
  const $  = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const on = (el, ev, fn, opts) => el && el.addEventListener(ev, fn, opts);
  const fire = (el, name, detail) => el && el.dispatchEvent(new CustomEvent(name, { detail, bubbles: true }));

  // ────────────────────────────────────────────────────────────
  // 1.  Theme bridge — sync any [data-theme-picker] not wired by
  //     theme-switcher.js (e.g. radio chips). Already covered above.
  // ────────────────────────────────────────────────────────────
  // (theme-switcher.js handles <select>, [data-set-theme], and hashchange)

  // ────────────────────────────────────────────────────────────
  // 2.  Tabs — three flavors: .el-tabs-h, .el-tabs-v, .el-tabs-pill
  //     Markup: <button class="tab" data-target="#panel-id">Label</button>
  // ────────────────────────────────────────────────────────────
  function wireTabs(root) {
    ['.el-tabs-h', '.el-tabs-v', '.el-tabs-pill'].forEach(cls => {
      $$(`${cls} [data-target]`, root).forEach(tab => {
        if (tab.__wired) return; tab.__wired = true;
        on(tab, 'click', () => {
          const group = tab.closest(cls);
          $$('[data-target]', group).forEach(t => t.classList.remove('on'));
          tab.classList.add('on');
          const tgt = document.querySelector(tab.dataset.target);
          if (!tgt) return;
          // sibling panel visibility
          const panels = $$(`.${cls}-panel[data-for="${group.id || ''}"]`, document);
          // simpler: hide all panels whose id starts with group.id, then show target
          const groupId = group.id;
          if (groupId) {
            $$(`[data-tabpanel][data-group="${groupId}"]`, document).forEach(p => p.hidden = (p.id !== tab.dataset.target.replace('#', '')));
          }
          fire(tgt, 'el:tab', { tab });
        });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 3.  Accordion — exclusive mode (only one open at a time)
  //     Markup: .el-accordion > details > summary
  //     Optional: [data-exclusive]
  // ────────────────────────────────────────────────────────────
  function wireAccordion(root) {
    $$('.el-accordion', root).forEach(acc => {
      if (acc.__wired) return; acc.__wired = true;
      const exclusive = acc.hasAttribute('data-exclusive');
      $$('details', acc).forEach(d => {
        on(d, 'toggle', () => {
          if (exclusive && d.open) {
            $$('details', acc).forEach(o => { if (o !== d) o.open = false; });
          }
        });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 4.  Segmented control — buttons sharing the same parent
  //     Markup: <div class="el-segmented"><button>…</button></div>
  // ────────────────────────────────────────────────────────────
  function wireSegmented(root) {
    $$('.el-segmented', root).forEach(seg => {
      if (seg.__wired) return; seg.__wired = true;
      $$('button', seg).forEach(b => {
        on(b, 'click', () => {
          $$('button', seg).forEach(o => o.classList.remove('on'));
          b.classList.add('on');
          fire(seg, 'el:segmented', { value: b.textContent.trim(), button: b });
        });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 5.  Toggle / Switch / Check / Radio — click toggles .on
  // ────────────────────────────────────────────────────────────
  function wireToggles(root) {
    ['.el-toggle', '.el-switch', '.el-check'].forEach(cls => {
      $$(cls, root).forEach(el => {
        if (el.__wired) return; el.__wired = true;
        on(el, 'click', () => {
          el.classList.toggle('on');
          fire(el, 'el:toggle', { on: el.classList.contains('on') });
        });
      });
    });
    // radio groups: <input name="x"> wrapped by .el-radio
    $$('.el-radio input[type="radio"]', root).forEach(inp => {
      if (inp.__wired) return; inp.__wired = true;
      on(inp, 'change', () => {
        const name = inp.name;
        $$(`.el-radio input[name="${name}"]`).forEach(o => {
          o.checked = (o === inp);
          o.parentElement.classList.toggle('on', o.checked);
        });
        fire(inp.closest('.el-radio'), 'el:radio', { value: inp.value });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 6.  Hover-card — click locks open
  //     Markup: .el-hover-card[data-lock-target]
  // ────────────────────────────────────────────────────────────
  function wireHoverCard(root) {
    $$('.el-hover-card', root).forEach(card => {
      if (card.__wired) return; card.__wired = true;
      on(card, 'click', () => card.classList.toggle('locked'));
    });
  }

  // ────────────────────────────────────────────────────────────
  // 7.  Tree-list — click .toggle to collapse
  //     Markup: .el-tree-list > li > .node > .toggle + ul
  // ────────────────────────────────────────────────────────────
  function wireTreeList(root) {
    $$('.el-tree-list .node', root).forEach(node => {
      if (node.__wired) return; node.__wired = true;
      const toggle = $('.toggle', node);
      if (!toggle) return;
      on(toggle, 'click', (e) => {
        e.stopPropagation();
        node.parentElement.classList.toggle('collapsed');
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 8.  Drag / Drop — reorder lists
  //     Markup: [data-draggable] inside [data-target-list]
  // ────────────────────────────────────────────────────────────
  function wireDragDrop(root) {
    $$('[data-draggable]', root).forEach(el => {
      if (el.__wired) return; el.__wired = true;
      el.draggable = true;
      on(el, 'dragstart', e => {
        el.classList.add('dragging');
        e.dataTransfer.setData('text/plain', el.dataset.dragLabel || el.textContent.trim());
        e.dataTransfer.effectAllowed = 'move';
      });
      on(el, 'dragend', () => el.classList.remove('dragging'));
    });
    $$('[data-target-list]', root).forEach(list => {
      if (list.__wired) return; list.__wired = true;
      on(list, 'dragover', e => {
        e.preventDefault();
        list.classList.add('drop-target');
      });
      on(list, 'dragleave', () => list.classList.remove('drop-target'));
      on(list, 'drop', e => {
        e.preventDefault();
        list.classList.remove('drop-target');
        const dragged = document.querySelector('.dragging');
        if (dragged) {
          list.appendChild(dragged);
          fire(list, 'el:drop', { item: dragged });
        }
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 9.  Combobox — filter menu items by typed input
  //     Markup: .el-combobox > input + .menu > .opt[data-value]
  // ────────────────────────────────────────────────────────────
  function wireCombobox(root) {
    $$('.el-combobox', root).forEach(cb => {
      if (cb.__wired) return; cb.__wired = true;
      const input = $('input', cb);
      const menu  = $('.menu', cb);
      const opts  = $$('.opt', menu);
      on(input, 'focus', () => cb.classList.add('open'));
      on(input, 'blur', () => setTimeout(() => cb.classList.remove('open'), 120));
      on(input, 'input', () => {
        const q = input.value.toLowerCase();
        opts.forEach(o => {
          o.hidden = !o.textContent.toLowerCase().includes(q);
        });
      });
      opts.forEach(o => on(o, 'click', () => {
        input.value = o.textContent.trim();
        cb.classList.remove('open');
        fire(cb, 'el:select', { value: o.dataset.value || o.textContent.trim() });
      }));
    });
  }

  // ────────────────────────────────────────────────────────────
  // 10. Multi-select pills — type to add, click × to remove
  // ────────────────────────────────────────────────────────────
  function wireMultiSelect(root) {
    $$('.el-multi-select', root).forEach(ms => {
      if (ms.__wired) return; ms.__wired = true;
      let input = $('input', ms);
      if (!input) {
        input = document.createElement('input');
        ms.appendChild(input);
      }
      on(input, 'keydown', (e) => {
        if (e.key === 'Enter' && input.value.trim()) {
          e.preventDefault();
          const pill = document.createElement('span');
          pill.className = 'pill';
          pill.innerHTML = `${input.value.trim()}<span class="x">×</span>`;
          ms.insertBefore(pill, input);
          input.value = '';
          fire(ms, 'el:add', { value: pill.textContent.replace('×', '').trim() });
        } else if (e.key === 'Backspace' && !input.value) {
          const pills = $$('.pill', ms);
          if (pills.length) pills[pills.length - 1].remove();
        }
      });
      on(ms, 'click', (e) => {
        if (e.target.classList.contains('x')) {
          e.target.parentElement.remove();
          fire(ms, 'el:remove', { value: e.target.parentElement.textContent.replace('×', '').trim() });
        }
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 11. Dropdown-menu — click .trigger to toggle .open
  // ────────────────────────────────────────────────────────────
  function wireDropdownMenu(root) {
    $$('.el-dropdown-menu', root).forEach(dm => {
      if (dm.__wired) return; dm.__wired = true;
      const trig = $('.trigger', dm);
      on(trig, 'click', () => dm.classList.toggle('open'));
      on(document, 'click', (e) => {
        if (!dm.contains(e.target)) dm.classList.remove('open');
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 12. Context menu — right-click .el-context-target to show
  // ────────────────────────────────────────────────────────────
  function wireContextMenu(root) {
    $$('[data-context-target]', root).forEach(t => {
      if (t.__wired) return; t.__wired = true;
      const menu = document.querySelector(t.dataset.contextTarget);
      if (!menu) return;
      on(t, 'contextmenu', (e) => {
        e.preventDefault();
        menu.style.left = e.clientX + 'px';
        menu.style.top  = e.clientY + 'px';
        menu.classList.add('open');
      });
    });
    $$('.el-context-menu', root).forEach(m => {
      if (m.__wired) return; m.__wired = true;
      on(document, 'click', () => m.classList.remove('open'));
      on(m, 'click', (e) => {
        if (e.target.classList.contains('item')) {
          fire(m, 'el:context', { item: e.target.textContent.trim() });
        }
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 13. Tooltip positioning — for el-tooltip[data-tip]
  //     (CSS handles basic; this only adds dynamic positioning
  //      if data-tip-placement is set)
  // ────────────────────────────────────────────────────────────
  function wireTooltip(root) {
    $$('.el-tooltip[data-tip-placement]', root).forEach(t => {
      if (t.__wired) return; t.__wired = true;
      on(t, 'mouseenter', () => {
        // CSS handles positioning via [data-tip-placement=…] selectors if needed
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 14. Popover — click .el-popover to toggle .open
  // ────────────────────────────────────────────────────────────
  function wirePopover(root) {
    $$('.el-popover', root).forEach(p => {
      if (p.__wired) return; p.__wired = true;
      const trig = $(':scope > *:not(.el-pop)', p);
      on(trig, 'click', (e) => {
        e.stopPropagation();
        $$('.el-popover.open').forEach(o => { if (o !== p) o.classList.remove('open'); });
        p.classList.toggle('open');
      });
    });
    on(document, 'click', () => $$('.el-popover.open').forEach(o => o.classList.remove('open')));
  }

  // ────────────────────────────────────────────────────────────
  // 15. Modal — [data-modal-open="<id>"] opens, [data-modal-close] closes
  // ────────────────────────────────────────────────────────────
  function wireModal(root) {
    $$('[data-modal-open]', root).forEach(btn => {
      if (btn.__wired) return; btn.__wired = true;
      on(btn, 'click', () => {
        const m = document.getElementById(btn.dataset.modalOpen);
        if (m) m.classList.add('open');
      });
    });
    $$('[data-modal-close]', root).forEach(btn => {
      if (btn.__wired) return; btn.__wired = true;
      on(btn, 'click', () => {
        const m = btn.closest('.el-modal-backdrop');
        if (m) m.classList.remove('open');
      });
    });
    $$('.el-modal-backdrop', root).forEach(bd => {
      if (bd.__wired) return; bd.__wired = true;
      on(bd, 'click', (e) => { if (e.target === bd) bd.classList.remove('open'); });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 16. Drawer — [data-drawer-open="<id>"] / [data-drawer-close]
  // ────────────────────────────────────────────────────────────
  function wireDrawer(root) {
    $$('[data-drawer-open]', root).forEach(btn => {
      if (btn.__wired) return; btn.__wired = true;
      on(btn, 'click', () => {
        const d = document.getElementById(btn.dataset.drawerOpen);
        if (d) d.classList.add('open');
      });
    });
    $$('[data-drawer-close]', root).forEach(btn => {
      if (btn.__wired) return; btn.__wired = true;
      on(btn, 'click', () => btn.closest('.el-drawer').classList.remove('open'));
    });
  }

  // ────────────────────────────────────────────────────────────
  // 17. Toast queue — call elToast.push(msg, variant?) to enqueue
  // ────────────────────────────────────────────────────────────
  function ensureToastRegion() {
    let r = $('.el-toast-region');
    if (!r) {
      r = document.createElement('div');
      r.className = 'el-toast-region';
      document.body.appendChild(r);
    }
    return r;
  }
  function pushToast(msg, variant) {
    const r = ensureToastRegion();
    const t = document.createElement('div');
    t.className = `el-toast ${variant || ''}`;
    t.innerHTML = `<span>${msg}</span><span class="close">×</span>`;
    r.appendChild(t);
    $('.close', t).addEventListener('click', () => t.remove());
    setTimeout(() => t.remove(), 4000);
  }
  window.elToast = { push: pushToast };

  // ────────────────────────────────────────────────────────────
  // 18. Pagination — client-side paging of [data-page-source]
  //     Markup: <ul data-page-source="#list">…
  //             <div class="el-pagination" data-page-size="5">
  // ────────────────────────────────────────────────────────────
  function wirePagination(root) {
    $$('.el-pagination[data-page-source]', root).forEach(pag => {
      if (pag.__wired) return; pag.__wired = true;
      const list = document.querySelector(pag.dataset.pageSource);
      if (!list) return;
      const items = $$(':scope > *', list);
      const size  = parseInt(pag.dataset.pageSize || '5', 10);
      let page    = 1;
      const total = Math.ceil(items.length / size);
      const render = () => {
        items.forEach((it, i) => {
          it.hidden = !(i >= (page - 1) * size && i < page * size);
        });
        const info = $('.info', pag);
        if (info) info.textContent = `${page} / ${total}`;
      };
      $$('.page', pag).forEach(btn => {
        on(btn, 'click', () => {
          if (btn.classList.contains('disabled')) return;
          const action = btn.dataset.action;
          if (action === 'first') page = 1;
          else if (action === 'prev') page = Math.max(1, page - 1);
          else if (action === 'next') page = Math.min(total, page + 1);
          else if (action === 'last') page = total;
          else page = parseInt(btn.textContent, 10) || 1;
          render();
        });
      });
      render();
    });
  }

  // ────────────────────────────────────────────────────────────
  // 19. Breadcrumb collapse — if > 5 segments, show "..."
  //     Markup: .el-breadcrumb[data-collapse-after="4"]
  // ────────────────────────────────────────────────────────────
  function wireBreadcrumb(root) {
    $$('.el-breadcrumb[data-collapse-after]', root).forEach(bc => {
      if (bc.__wired) return; bc.__wired = true;
      const children = Array.from(bc.children).filter(c => !c.classList.contains('sep'));
      const after = parseInt(bc.dataset.collapseAfter, 10);
      if (children.length <= after + 1) return;
      children.slice(after, -1).forEach(c => c.hidden = true);
      const dots = document.createElement('span');
      dots.className = 'sep';
      dots.textContent = '…';
      children[after - 1].after(dots);
    });
  }

  // ────────────────────────────────────────────────────────────
  // 20. Scroll-shadow — IntersectionObserver to update data-shadow
  //     Markup: .el-scroll-shadow
  // ────────────────────────────────────────────────────────────
  function wireScrollShadow(root) {
    if (!('IntersectionObserver' in window)) return;
    $$('.el-scroll-shadow', root).forEach(s => {
      if (s.__wired) return; s.__wired = true;
      const top = document.createElement('div');
      const bot = document.createElement('div');
      top.style.cssText = 'position:absolute;top:0;left:0;right:0;height:1px;';
      bot.style.cssText = 'position:absolute;bottom:0;left:0;right:0;height:1px;';
      s.style.position = 'relative';
      s.appendChild(top); s.appendChild(bot);
      const obs = new IntersectionObserver(es => {
        s.dataset.shadowTop  = es.find(e => e.target === top).isIntersecting ? '' : 'on';
        s.dataset.shadowBot  = es.find(e => e.target === bot).isIntersecting ? '' : 'on';
      });
      obs.observe(top); obs.observe(bot);
    });
  }

  // ────────────────────────────────────────────────────────────
  // 21. Chip toggle — click .el-chip to toggle .added
  // ────────────────────────────────────────────────────────────
  function wireChips(root) {
    $$('.el-chip', root).forEach(c => {
      if (c.__wired) return; c.__wired = true;
      on(c, 'click', () => c.classList.toggle('added'));
    });
  }

  // ────────────────────────────────────────────────────────────
  // 22. Table sort — click th to toggle data-sort-dir on tbody
  // ────────────────────────────────────────────────────────────
  function wireTable(root) {
    $$('.el-table', root).forEach(tbl => {
      const ths = $$('thead th', tbl);
      ths.forEach((th, i) => {
        if (th.__wired) return; th.__wired = true;
        on(th, 'click', () => {
          const dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
          ths.forEach(o => o.dataset.sortDir = '');
          th.dataset.sortDir = dir;
          const rows = $$('tbody tr', tbl);
          rows.sort((a, b) => {
            const x = a.children[i].textContent.trim();
            const y = b.children[i].textContent.trim();
            return dir === 'asc' ? x.localeCompare(y) : y.localeCompare(x);
          });
          const tb = $('tbody', tbl);
          rows.forEach(r => tb.appendChild(r));
        });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 23. Palette filter — type into .el-palette .input to filter rows
  // ────────────────────────────────────────────────────────────
  function wirePalette(root) {
    $$('.el-palette .input', root).forEach(input => {
      if (input.__wired) return; input.__wired = true;
      const palette = input.closest('.el-palette');
      on(input, 'input', () => {
        const q = input.value.toLowerCase();
        $$('.row', palette).forEach(r => {
          r.hidden = !r.textContent.toLowerCase().includes(q);
        });
      });
    });
  }

  // ────────────────────────────────────────────────────────────
  // 24. Anchor-nav — IntersectionObserver to mark active link
  // ────────────────────────────────────────────────────────────
  function wireAnchorNav(root) {
    if (!('IntersectionObserver' in window)) return;
    $$('.el-anchor-nav', root).forEach(nav => {
      const links = $$('a[href^="#"]', nav);
      if (!links.length) return;
      const targets = links.map(l => document.querySelector(l.getAttribute('href'))).filter(Boolean);
      if (!targets.length) return;
      const obs = new IntersectionObserver(es => {
        es.forEach(e => {
          if (e.isIntersecting) {
            links.forEach(l => l.classList.remove('active'));
            const link = links.find(l => l.getAttribute('href') === '#' + e.target.id);
            if (link) link.classList.add('active');
          }
        });
      }, { rootMargin: '-30% 0px -60% 0px' });
      targets.forEach(t => obs.observe(t));
    });
  }

  // ────────────────────────────────────────────────────────────
  // Master init — run all hooks on load + on dynamic content
  // ────────────────────────────────────────────────────────────
  function init(root) {
    root = root || document;
    wireTabs(root);
    wireAccordion(root);
    wireSegmented(root);
    wireToggles(root);
    wireHoverCard(root);
    wireTreeList(root);
    wireDragDrop(root);
    wireCombobox(root);
    wireMultiSelect(root);
    wireDropdownMenu(root);
    wireContextMenu(root);
    wireTooltip(root);
    wirePopover(root);
    wireModal(root);
    wireDrawer(root);
    wirePagination(root);
    wireBreadcrumb(root);
    wireScrollShadow(root);
    wireChips(root);
    wireTable(root);
    wirePalette(root);
    wireAnchorNav(root);
    // interactive stubs (real behavior for every element)
    wireSignaturePad(root);
    wireAudioWaveform(root);
    wireFileUpload(root);
    wireCodeBlock(root);
    wireKbdInput(root);
    wireRating(root);
    wireProgressAnimate(root);
    wireToastDismiss(root);
    wirePaletteKeyboard(root);
    wireComboboxKeyboard(root);
    wireTabsKeyboard(root);
    wireAccordionKeyboard(root);
    wireTreeListKeyboard(root);
    wireToggleKeyboard(root);
    wireModalKeyboard(root);
    wireDrawerKeyboard(root);
    wireSlider(root);
    wireSearchBar(root);
    wirePrompt(root);
    wireClipboard(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ────────────────────────────────────────────────────────────
  // STUBS — real interactive behavior for every element
  // ────────────────────────────────────────────────────────────

  // Signature pad — pointer/touch draw
  function wireSignaturePad(root) {
    $$('.el-signature-pad', root).forEach(canvas => {
      if (canvas.__wired) return; canvas.__wired = true;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue('--el-ink').trim() || '#000';
      ctx.lineWidth = 2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      let drawing = false, lastX = 0, lastY = 0;
      const start = (x, y) => { drawing = true; lastX = x; lastY = y; };
      const move = (x, y) => {
        if (!drawing) return;
        ctx.beginPath(); ctx.moveTo(lastX, lastY); ctx.lineTo(x, y); ctx.stroke();
        lastX = x; lastY = y;
      };
      const stop = () => { drawing = false; };
      on(canvas, 'pointerdown', e => { canvas.setPointerCapture(e.pointerId); start(e.offsetX, e.offsetY); });
      on(canvas, 'pointermove', e => move(e.offsetX, e.offsetY));
      on(canvas, 'pointerup',   stop);
      on(canvas, 'pointerleave', stop);
      // double-click to clear
      on(canvas, 'dblclick', () => ctx.clearRect(0, 0, canvas.width, canvas.height));
    });
  }

  // Audio waveform — click to seek + play button
  function wireAudioWaveform(root) {
    $$('.el-audio-waveform', root).forEach(w => {
      if (w.__wired) return; w.__wired = true;
      const bars = $$('.bar', w);
      const total = bars.length;
      let playing = false;
      let pos = 0;
      let timer = null;
      const render = () => {
        bars.forEach((b, i) => b.classList.toggle('played', i < pos));
      };
      on(w, 'click', e => {
        const rect = w.getBoundingClientRect();
        const x = e.clientX - rect.left;
        pos = Math.round((x / rect.width) * total);
        render();
        fire(w, 'el:seek', { position: pos });
      });
      const play = () => {
        playing = true;
        if (timer) clearInterval(timer);
        timer = setInterval(() => {
          if (pos < total) { pos++; render(); }
          else { pause(); }
        }, 120);
      };
      const pause = () => { playing = false; if (timer) clearInterval(timer); };
      // double-click to play/pause
      on(w, 'dblclick', () => playing ? pause() : play());
    });
  }

  // File upload — drag/drop + click to pick
  function wireFileUpload(root) {
    $$('.el-file-upload', root).forEach(fu => {
      if (fu.__wired) return; fu.__wired = true;
      const input = document.createElement('input');
      input.type = 'file'; input.multiple = true; input.style.display = 'none';
      fu.appendChild(input);
      on(fu, 'click', () => input.click());
      on(input, 'change', () => {
        const names = Array.from(input.files).map(f => f.name).join(', ');
        if (names) {
          const hint = $('.hint', fu);
          if (hint) hint.textContent = `Selected: ${names}`;
          fire(fu, 'el:upload', { files: input.files });
        }
      });
      ['dragenter', 'dragover'].forEach(ev => on(fu, ev, e => { e.preventDefault(); fu.classList.add('over'); }));
      ['dragleave', 'drop'].forEach(ev => on(fu, ev, e => { e.preventDefault(); fu.classList.remove('over'); }));
      on(fu, 'drop', e => {
        const dt = e.dataTransfer;
        if (dt && dt.files.length) {
          const names = Array.from(dt.files).map(f => f.name).join(', ');
          const hint = $('.hint', fu);
          if (hint) hint.textContent = `Dropped: ${names}`;
          fire(fu, 'el:upload', { files: dt.files });
        }
      });
    });
  }

  // Code block — line numbers + click-to-copy button
  function wireCodeBlock(root) {
    $$('.el-code-block', root).forEach(cb => {
      if (cb.__wired) return; cb.__wired = true;
      // add line numbers
      const text = cb.textContent.replace(/\n$/, '');
      const lines = text.split('\n');
      cb.innerHTML = '';
      lines.forEach((line, i) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.gap = 'var(--el-space-3)';
        const num = document.createElement('span');
        num.textContent = (i + 1).toString().padStart(2, ' ');
        num.style.color = 'var(--el-mute)';
        num.style.userSelect = 'none';
        num.style.minWidth = '2ch';
        num.style.textAlign = 'right';
        const code = document.createElement('span');
        code.innerHTML = line || '&nbsp;';
        row.appendChild(num); row.appendChild(code);
        cb.appendChild(row);
      });
      // copy button
      const btn = document.createElement('button');
      btn.textContent = 'Copy';
      btn.style.cssText = 'position:absolute;top:8px;right:8px;font:11px var(--el-font-mono);padding:2px 8px;border:1px solid var(--el-line);background:var(--el-panel);color:var(--el-ink);border-radius:4px;cursor:pointer;';
      cb.style.position = 'relative';
      cb.appendChild(btn);
      on(btn, 'click', () => {
        const t = lines.join('\n');
        if (navigator.clipboard) navigator.clipboard.writeText(t);
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 1200);
        fire(cb, 'el:copy', { text: t });
      });
    });
  }

  // Kbd input — capture next keystroke
  function wireKbdInput(root) {
    $$('.el-kbd-input', root).forEach(inp => {
      if (inp.__wired) return; inp.__wired = true;
      on(inp, 'focus', () => inp.value = '');
      on(inp, 'blur', () => { if (!inp.value) inp.value = '⌘K'; });
      on(inp, 'keydown', e => {
        e.preventDefault();
        const parts = [];
        if (e.metaKey || e.ctrlKey) parts.push('⌘');
        if (e.shiftKey) parts.push('⇧');
        if (e.altKey) parts.push('⌥');
        let key = e.key;
        if (key === ' ') key = 'Space';
        else if (key.length === 1) key = key.toUpperCase();
        parts.push(key);
        inp.value = parts.join('+');
        fire(inp, 'el:kbd', { combo: inp.value });
      });
    });
  }

  // Rating — click stars to set
  function wireRating(root) {
    $$('.el-rating', root).forEach(r => {
      if (r.__wired) return; r.__wired = true;
      const stars = $$('.star', r);
      stars.forEach((s, i) => {
        on(s, 'click', () => {
          const on = i + 1;
          stars.forEach((o, j) => o.classList.toggle('on', j < on));
          fire(r, 'el:rate', { value: on });
        });
        on(s, 'mouseenter', () => {
          stars.forEach((o, j) => o.classList.toggle('on', j <= i));
        });
        on(r, 'mouseleave', () => {
          const cur = stars.filter(o => o.classList.contains('on')).length;
          stars.forEach((o, j) => o.classList.toggle('on', j < cur));
        });
      });
    });
  }

  // Progress — animate to data-target
  function wireProgressAnimate(root) {
    $$('.el-progress[data-animate-to]', root).forEach(p => {
      if (p.__wired) return; p.__wired = true;
      const fill = $('.fill', p);
      if (!fill) return;
      const target = parseFloat(p.dataset.animateTo);
      const dur = parseInt(p.dataset.animateDuration || '1200', 10);
      fill.style.transition = `width ${dur}ms cubic-bezier(.4,0,.2,1)`;
      requestAnimationFrame(() => fill.style.width = target + '%');
    });
  }

  // Toast — click × to dismiss
  function wireToastDismiss(root) {
    on(root, 'click', e => {
      if (e.target.classList.contains('close') && e.target.closest('.el-toast')) {
        e.target.closest('.el-toast').remove();
      }
    });
  }

  // Palette — ↑/↓/Enter keyboard nav
  function wirePaletteKeyboard(root) {
    $$('.el-palette', root).forEach(pal => {
      if (pal.__wired) return; pal.__wired = true;
      const input = $('.input', pal);
      if (!input) return;
      on(input, 'keydown', e => {
        const rows = $$('.row:not([hidden])', pal);
        if (!rows.length) return;
        const sel = rows.find(r => r.classList.contains('sel'));
        let idx = rows.indexOf(sel);
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          idx = Math.min(rows.length - 1, (idx < 0 ? 0 : idx + 1));
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          idx = Math.max(0, (idx < 0 ? 0 : idx - 1));
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (sel) fire(pal, 'el:run', { row: sel });
          return;
        } else return;
        rows.forEach(r => r.classList.remove('sel'));
        rows[idx].classList.add('sel');
        rows[idx].scrollIntoView({ block: 'nearest' });
      });
    });
  }

  // Combobox — ↑/↓/Enter/Esc
  function wireComboboxKeyboard(root) {
    $$('.el-combobox', root).forEach(cb => {
      if (cb.__wired) return; cb.__wired = true;
      const input = $('input', cb);
      on(input, 'keydown', e => {
        const opts = $$('.opt:not([hidden])', cb);
        if (!opts.length) return;
        const sel = opts.find(o => o.classList.contains('sel'));
        let idx = opts.indexOf(sel);
        if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(opts.length - 1, (idx < 0 ? 0 : idx + 1)); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(0, (idx < 0 ? 0 : idx - 1)); }
        else if (e.key === 'Enter') { e.preventDefault(); if (sel) sel.click(); return; }
        else if (e.key === 'Escape') { cb.classList.remove('open'); return; }
        else return;
        opts.forEach(o => o.classList.remove('sel'));
        opts[idx].classList.add('sel');
      });
    });
  }

  // Tabs — ←/→ keyboard
  function wireTabsKeyboard(root) {
    ['.el-tabs-h', '.el-tabs-v', '.el-tabs-pill'].forEach(cls => {
      $$(cls, root).forEach(group => {
        if (group.__wired) return; group.__wired = true;
        on(group, 'keydown', e => {
          if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
          const tabs = $$('[data-target]', group);
          const cur = tabs.findIndex(t => t.classList.contains('on'));
          let next = cur;
          if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (cur + 1) % tabs.length;
          else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (cur - 1 + tabs.length) % tabs.length;
          tabs[next].focus();
          tabs[next].click();
        });
      });
    });
  }

  // Accordion — Enter/Space to toggle
  function wireAccordionKeyboard(root) {
    $$('.el-accordion summary', root).forEach(s => {
      if (s.__wired) return; s.__wired = true;
      s.tabIndex = 0;
      on(s, 'keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          s.parentElement.open = !s.parentElement.open;
        }
      });
    });
  }

  // Tree-list — ←/→ collapse/expand
  function wireTreeListKeyboard(root) {
    $$('.el-tree-list .node', root).forEach(n => {
      if (n.__wired) return; n.__wired = true;
      const toggle = $('.toggle', n);
      if (!toggle || !toggle.textContent.trim().match(/[▾▸]/)) return;
      n.tabIndex = 0;
      on(n, 'keydown', e => {
        if (e.key === 'ArrowRight') { e.preventDefault(); n.parentElement.classList.remove('collapsed'); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); n.parentElement.classList.add('collapsed'); }
      });
    });
  }

  // Toggle/Switch/Check — Space/Enter to flip
  function wireToggleKeyboard(root) {
    ['.el-toggle', '.el-switch', '.el-check'].forEach(cls => {
      $$(cls, root).forEach(el => {
        if (el.__wired) return; el.__wired = true;
        el.tabIndex = 0;
        on(el, 'keydown', e => {
          if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            el.click();
          }
        });
      });
    });
  }

  // Modal — Esc closes, focus trap
  function wireModalKeyboard(root) {
    $$('.el-modal-backdrop', root).forEach(bd => {
      if (bd.__wired) return; bd.__wired = true;
      on(bd, 'keydown', e => {
        if (e.key === 'Escape') {
          e.preventDefault();
          bd.classList.remove('open');
        }
      });
    });
  }

  // Drawer — Esc closes
  function wireDrawerKeyboard(root) {
    $$('.el-drawer', root).forEach(d => {
      if (d.__wired) return; d.__wired = true;
      on(d, 'keydown', e => {
        if (e.key === 'Escape') { e.preventDefault(); d.classList.remove('open'); }
      });
    });
  }

  // Slider — show live value next to it
  function wireSlider(root) {
    $$('.el-slider', root).forEach(s => {
      if (s.__wired) return; s.__wired = true;
      const update = () => {
        const val = s.value;
        const parent = s.parentElement;
        if (parent && parent.classList.contains('el-range')) {
          const out = $('.val', parent);
          if (out) out.textContent = val;
        }
        fire(s, 'el:slide', { value: val });
      };
      on(s, 'input', update);
      update();
    });
  }

  // Search bar — Enter fires search event
  function wireSearchBar(root) {
    $$('.el-search', root).forEach(s => {
      if (s.__wired) return; s.__wired = true;
      on(s, 'keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          fire(s.closest('.el-search-bar') || s, 'el:search', { query: s.value });
        }
      });
    });
  }

  // Prompt — Cmd/Ctrl+Enter submits
  function wirePrompt(root) {
    $$('.el-prompt', root).forEach(p => {
      if (p.__wired) return; p.__wired = true;
      on(p, 'keydown', e => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          fire(p, 'el:submit', { text: p.value });
          p.value = '';
        }
      });
    });
  }

  // Clipboard — anything with [data-copy] copies its text on click
  function wireClipboard(root) {
    $$('[data-copy]', root).forEach(el => {
      if (el.__wired) return; el.__wired = true;
      el.style.cursor = 'pointer';
      on(el, 'click', () => {
        const text = el.dataset.copy;
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text).then(() => {
            const orig = el.textContent;
            el.textContent = 'Copied!';
            setTimeout(() => el.textContent = orig, 1000);
          });
        }
        fire(el, 'el:copy', { text });
      });
    });
  }

  // expose for re-init after dynamic HTML insertion
  window.elInit = init;
})();
