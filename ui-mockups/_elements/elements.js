/* ──────────────────────────────────────────────────────────
   ELEMENT LIBRARY — shared JS hooks
   References data-attributes (data-draggable, data-hover-detail)
   so consumers don't have to write any inline JS for these.
   ──────────────────────────────────────────────────────────
*/

// ── drag-and-drop (row → drop zone) ────────────────────
(function setupDragDrop() {
  let dragEl = null;
  document.querySelectorAll('[data-draggable]').forEach(el => {
    el.addEventListener('dragstart', e => {
      dragEl = el;
      el.classList.add('dragging');
      e.dataTransfer.setData('text/plain',
        el.dataset.dragLabel || el.textContent.trim().slice(0, 60));
    });
    el.addEventListener('dragend', () => {
      el.classList.remove('dragging');
      dragEl = null;
    });
  });
  document.querySelectorAll('.drop-zone').forEach(zone => {
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('over');
      const txt = e.dataTransfer.getData('text/plain');
      const ulId = zone.dataset.targetList;
      if (ulId) {
        const ul = document.getElementById(ulId);
        if (ul) {
          const li = document.createElement('li');
          li.innerHTML = `<span class="el-badge">DROP</span><span>${txt}</span><span class="x">×</span>`;
          ul.appendChild(li);
        }
      } else {
        const note = document.createElement('div');
        note.style.cssText = 'padding:4px 8px;font:11px var(--el-font-mono);color:var(--el-ink);margin-top:6px;background:var(--el-panel-2);';
        note.textContent = '+ ' + txt;
        zone.appendChild(note);
      }
    });
  });
  // delete from saved list
  document.addEventListener('click', e => {
    if (e.target.classList && e.target.classList.contains('x')) {
      const li = e.target.closest('li');
      if (li) li.remove();
    }
  });
})();

// ── chip toggle ────────────────────────────────────────
document.addEventListener('click', e => {
  const chip = e.target.closest('.el-chip[data-toggle]');
  if (chip) chip.classList.toggle('added');
});

// ─- row select ─────────────────────────────────────────
document.addEventListener('click', e => {
  const row = e.target.closest('.el-row[data-group]');
  if (!row) return;
  const grp = row.dataset.group;
  document.querySelectorAll(`.el-row[data-group="${grp}"]`).forEach(r => r.classList.remove('sel'));
  row.classList.add('sel');
  const detailId = row.dataset.detail;
  if (detailId) {
    const detail = document.getElementById(detailId);
    if (detail && row.dataset.detailHtml) detail.innerHTML = row.dataset.detailHtml;
  }
});

// ─- tabs ──────────────────────────────────────────────
document.querySelectorAll('.el-tabs').forEach(tabs => {
  const nav = tabs.querySelectorAll('.nav button');
  const body = tabs.querySelector('.body');
  nav.forEach(b => b.addEventListener('click', () => {
    nav.forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    const htmlId = b.dataset.bodyId;
    if (htmlId) {
      const src = document.getElementById(htmlId);
      if (src) body.innerHTML = src.innerHTML;
    }
  }));
});

// ─- command palette ───────────────────────────────────
document.querySelectorAll('.el-palette').forEach(palette => {
  const input = palette.querySelector('.input');
  const results = palette.querySelector('.results');
  const rows = Array.from(results.querySelectorAll('.row'));
  if (input) {
    input.addEventListener('input', () => {
      const q = input.value.toLowerCase();
      rows.forEach(r => {
        const hit = r.textContent.toLowerCase().includes(q);
        r.style.display = hit ? '' : 'none';
      });
      rows[0] && rows[0].classList.add('sel');
    });
    rows.forEach((r, i) => {
      r.addEventListener('click', () => {
        rows.forEach(x => x.classList.remove('sel'));
        r.classList.add('sel');
        const cb = palette.dataset.onSelect;
        if (cb) window[cb] && window[cb](r);
      });
    });
  }
});

// ─- accordion auto-close siblings ─────────────────────
document.querySelectorAll('.el-accordion[data-exclusive] details').forEach(d => {
  d.addEventListener('toggle', () => {
    if (d.open) {
      d.parentElement.querySelectorAll('details').forEach(o => {
        if (o !== d) o.removeAttribute('open');
      });
    }
  });
});

// ─- table sort (click header) ─────────────────────────
document.querySelectorAll('.el-table[data-sortable]').forEach(table => {
  const tbody = table.querySelector('tbody');
  table.querySelectorAll('thead th[data-sort-key]').forEach((th, idx) => {
    th.addEventListener('click', () => {
      const dir = th.dataset.sortDir === 'desc' ? 'desc' : 'asc';
      th.dataset.sortDir = dir;
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const isNum = rows.every(r => !isNaN(parseFloat(r.children[idx].textContent)));
      rows.sort((a, b) => {
        const av = a.children[idx].textContent.trim();
        const bv = b.children[idx].textContent.trim();
        if (isNum) return dir === 'asc' ? parseFloat(av) - parseFloat(bv) : parseFloat(bv) - parseFloat(av);
        return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
});

// ─- hover-card sync (click to lock the open state) ────
document.querySelectorAll('.el-hover-card').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('.el-hover-card').forEach(o => o.classList.remove('locked'));
    c.classList.toggle('locked');
  });
});

// ─- gauge radial (svg) demo ───────────────────────────
document.querySelectorAll('.el-gauge.radial').forEach(g => {
  const v = parseFloat(g.dataset.value || 0);
  const c = 2 * Math.PI * 18;
  const off = c * (1 - Math.min(1, Math.max(0, v)));
  g.insertAdjacentHTML('beforeend',
    `<svg viewBox="0 0 40 40" style="width:36px;height:36px;">
       <circle cx="20" cy="20" r="18" stroke="var(--el-panel-2)" stroke-width="4" fill="none"/>
       <circle cx="20" cy="20" r="18" stroke="var(--el-accent)" stroke-width="4" fill="none"
               stroke-dasharray="${c}" stroke-dashoffset="${off}" stroke-linecap="round"
               transform="rotate(-90 20 20)"/>
     </svg>`);
});
