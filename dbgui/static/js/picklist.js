/* Multi-select pick list used by Job Searches.

   job_searches still stores what it always did -- a comma-separated string of
   record numbers ("1,2,3", empty meaning "use every record"). This only changes
   how that string is produced, so nothing downstream of the database changes.

   Two data realities it must not paper over:
     * a number can be ambiguous (Job has duplicate jobNum values for a user),
     * a number can be dangling (the search references a record that no longer
       exists). Dropping those silently would quietly change which history the
       bot submits, so both stay visible and are only removed deliberately.
*/

import { el } from './core.js';

let openPanel = null;
let ownerSeq = 0;

function closeOpenPanel() {
  if (openPanel) { openPanel.remove(); openPanel = null; }
}

// A panel is torn out of the page when the view re-renders under it.
window.addEventListener('resize', closeOpenPanel);

document.addEventListener('click', (e) => {
  if (openPanel && !openPanel.contains(e.target) && !e.target.closest('.picker__trigger')) {
    closeOpenPanel();
  }
});

function parseNums(raw) {
  return (raw || '').split(',').map((s) => s.trim()).filter(Boolean);
}

/**
 * @param options  [{ value:'1', label:'Customer Service Rep', sub:'Ivy Kode', ambiguous:false }]
 * @param value    current comma-separated string
 * @param onChange (newCommaSeparatedString) => void
 * @param noun     'job' | 'education record'
 */
export function pickList({ options, value, onChange, noun, allLabel }) {
  const selected = new Set(parseNums(value));
  const known = new Set(options.map((o) => o.value));
  const dangling = [...selected].filter((v) => !known.has(v));
  const ownerId = `pick-${++ownerSeq}`;

  const trigger = el('button', { class: 'picker__trigger', type: 'button' });

  function summaryText() {
    if (selected.size === 0) return allLabel || `All ${noun}s`;
    const parts = [...selected].sort((a, b) => Number(a) - Number(b)).map((n) => `#${n}`);
    return parts.length <= 4 ? parts.join(', ') : `${parts.slice(0, 4).join(', ')} +${parts.length - 4}`;
  }

  function refreshTrigger() {
    trigger.replaceChildren();
    const isAll = selected.size === 0;
    trigger.append(el('span', {
      class: `picker__summary${isAll ? ' picker__summary--all' : ''}`,
      text: summaryText(),
    }));
    const problems = [...selected].filter((v) => !known.has(v)).length;
    if (problems) {
      trigger.append(el('span', {
        class: 'picker__warn', text: `${problems} missing`,
        title: `${problems} selected ${noun}${problems === 1 ? '' : 's'} no longer exist`,
      }));
    }
    trigger.append(el('span', { class: 'picker__caret', text: '▾' }));
  }

  function commit() {
    const ordered = [...selected].sort((a, b) => Number(a) - Number(b));
    refreshTrigger();
    onChange(ordered.join(','));
  }

  function buildPanel() {
    const panel = el('div', { class: 'picker__panel' });

    panel.append(el('div', { class: 'picker__hint', text:
      `Nothing ticked means the bot uses every ${noun} for this search.` }));

    const list = el('div', { class: 'picker__list' });

    options.forEach((opt) => {
      const box = el('input', {
        type: 'checkbox', checked: selected.has(opt.value) ? true : null,
        onchange: (e) => {
          if (e.target.checked) selected.add(opt.value); else selected.delete(opt.value);
          commit();
        },
      });
      list.append(el('label', { class: 'picker__option' }, [
        box,
        el('span', { class: 'picker__option-body' }, [
          el('span', { class: 'picker__option-label' }, [
            el('span', { class: 'picker__num', text: `#${opt.value}` }),
            opt.label || '(untitled)',
          ]),
          opt.sub ? el('span', { class: 'picker__option-sub', text: opt.sub }) : null,
          opt.ambiguous
            ? el('span', { class: 'picker__option-warn', text:
                `Two records share #${opt.value} - the bot cannot tell them apart` })
            : null,
        ]),
      ]));
    });

    // Dangling references: shown so they can be seen and removed on purpose.
    dangling.forEach((num) => {
      if (!selected.has(num)) return;
      list.append(el('label', { class: 'picker__option picker__option--missing' }, [
        el('input', {
          type: 'checkbox', checked: true,
          onchange: () => { selected.delete(num); commit(); rebuild(); },
        }),
        el('span', { class: 'picker__option-body' }, [
          el('span', { class: 'picker__option-label' }, [
            el('span', { class: 'picker__num', text: `#${num}` }),
            'No such record',
          ]),
          el('span', { class: 'picker__option-warn', text:
            `This search references ${noun} #${num}, which does not exist. Untick to remove it.` }),
        ]),
      ]));
    });

    if (!options.length && !dangling.length) {
      list.append(el('div', { class: 'picker__empty', text: `This user has no ${noun}s yet.` }));
    }

    panel.append(list);
    panel.append(el('div', { class: 'picker__footer' }, [
      el('button', {
        class: 'btn btn--sm btn--ghost', type: 'button', text: `Use all ${noun}s`,
        onclick: () => { selected.clear(); commit(); rebuild(); },
      }),
      el('button', {
        class: 'btn btn--sm', type: 'button', text: 'Done',
        onclick: () => closeOpenPanel(),
      }),
    ]));
    return panel;
  }

  function rebuild() {
    if (!openPanel || openPanel.dataset.owner !== ownerId) return;
    const fresh = buildPanel();
    fresh.dataset.owner = ownerId;
    openPanel.replaceWith(fresh);
    openPanel = fresh;
    place(fresh);
  }

  // The panel lives on <body> with fixed positioning rather than inside the
  // cell: the searches table is a horizontal scroll container, which would
  // otherwise clip the dropdown.
  function place(panel) {
    const r = trigger.getBoundingClientRect();
    panel.style.left = `${Math.min(r.left, window.innerWidth - 352)}px`;
    const room = window.innerHeight - r.bottom;
    if (room < 260 && r.top > room) {
      panel.style.bottom = `${window.innerHeight - r.top + 5}px`;
      panel.style.top = 'auto';
    } else {
      panel.style.top = `${r.bottom + 5}px`;
      panel.style.bottom = 'auto';
    }
  }

  trigger.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const wasMine = openPanel && openPanel.dataset.owner === ownerId;
    closeOpenPanel();
    if (wasMine) return;
    openPanel = buildPanel();
    openPanel.dataset.owner = ownerId;
    document.body.append(openPanel);
    place(openPanel);
  });

  const wrapper = el('div', { class: 'picker' }, [trigger]);
  refreshTrigger();
  return wrapper;
}

/** Build picker options from Job rows, flagging numbers shared by two records. */
export function jobOptions(jobs) {
  const counts = {};
  jobs.forEach((j) => { counts[j.jobNum] = (counts[j.jobNum] || 0) + 1; });
  const seen = new Set();
  return jobs
    .filter((j) => {
      const key = String(j.jobNum);
      if (seen.has(key)) return false;   // one entry per number; ambiguity is flagged instead
      seen.add(key);
      return true;
    })
    .sort((a, b) => Number(a.jobNum) - Number(b.jobNum))
    .map((j) => ({
      value: String(j.jobNum),
      label: j.JobTitle || '(untitled job)',
      sub: j.CompanyName || '',
      ambiguous: counts[j.jobNum] > 1,
    }));
}

export function eduOptions(edus) {
  return edus
    .slice()
    .sort((a, b) => Number(a.eduNum) - Number(b.eduNum))
    .map((e) => ({
      value: String(e.eduNum),
      label: e.level || '(no level)',
      sub: [e.fieldOfStudy, e.SchoolName].filter(Boolean).join(' - '),
      ambiguous: false,
    }));
}
