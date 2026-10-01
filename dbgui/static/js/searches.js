/* Job Searches -- CRUD over the job_searches table.

   Row order is functional, not cosmetic: the bot starts on position 0 and
   cycles from there, so drag-to-reorder changes which search runs first.

   A main row can have alternate-URL sub-rows nested under it -- the same
   target position, a different search URL. The bot runs a main row's active
   sub-rows immediately after it, in order, before moving to the next main
   row (see dbgui/data.py: list_searches_for_bot). A sub-row only ever owns
   its own URL, active flag, and applications-this-session count; everything
   else (target position, work history, education, session cap) is always
   the parent's. */

import { api, el, mount, setTopbar, toast, card, emptyState, confirmModal } from './core.js';
import { pickList, jobOptions, eduOptions } from './picklist.js';
import { summarizeUrlDiff, applyUrlDiff } from './urldiff.js';

/** Mirror of migrations.position_from_url: derive a label from the `q` term. */
function positionFromUrl(url) {
  try {
    const term = (new URL(url).searchParams.get('q') || '').trim();
    return term.replace(/\b\w/g, (c) => c.toUpperCase());
  } catch {
    return '';
  }
}

let poller = null;

// Which main rows have their alternate-URL sub-rows collapsed. Module-level
// (not per-render state) so a collapse choice survives the re-renders that
// follow every save/add/delete in this view, and is keyed by search id so it
// also survives switching away to another tab and back.
const collapsedMainRows = new Set();

export function stopSearchesPolling() {
  if (poller) { clearInterval(poller); poller = null; }
}

export async function renderSearches(ctx) {
  stopSearchesPolling();
  const userId = ctx.state.userId;
  const [searches, jobs, edus] = await Promise.all([
    api.get(`/api/users/${userId}/searches`),
    api.get(`/api/users/${userId}/jobs`),
    api.get(`/api/users/${userId}/edu`),
  ]);
  const jobOpts = jobOptions(jobs);
  const eduOpts = eduOptions(edus);

  const mainRows = searches.filter((r) => r.parent_id == null);
  const subRowsByParent = new Map();
  searches.forEach((row) => {
    if (row.parent_id == null) return;
    if (!subRowsByParent.has(row.parent_id)) subRowsByParent.set(row.parent_id, []);
    subRowsByParent.get(row.parent_id).push(row);
  });
  const subCount = searches.length - mainRows.length;
  ctx.setCount('searches', mainRows.length);

  const addBtn = el('button', {
    class: 'btn btn--primary', text: 'Add search',
    onclick: async () => {
      await api.post(`/api/users/${userId}/searches`, { url: '', job_nums: '', edu_nums: '' });
      toast('Search added');
      ctx.go('searches');
    },
  });
  const subtitle = subCount
    ? `${mainRows.length} configured (+${subCount} alternate URL${subCount === 1 ? '' : 's'}) - the bot starts with the first one`
    : `${mainRows.length} configured - the bot starts with the first one`;
  setTopbar('Job Searches', subtitle, [addBtn], ctx.userLabel());

  if (!mainRows.length) {
    mount(card('Job searches', null, [
      emptyState('No job searches', 'The bot refuses to run a user with no searches. Add one to get started.'),
    ]));
    return;
  }

  let dragId = null;

  const saveField = async (id, key, value) => {
    try {
      await api.put(`/api/searches/${id}`, { [key]: value });
      toast('Saved');
    } catch (err) { toast(err.message, 'error'); }
  };

  // Keyed by search id (main rows AND sub-rows) so the poller below can patch
  // counts in place -- never re-rendering the table, which would otherwise
  // blow away whatever the user is mid-way through typing in target/URL inputs.
  const sessionCountSpans = new Map();

  const sessionSpan = (row) => {
    const span = el('span', {
      text: String(row.sessionApplications ?? 0),
      title: 'Applications submitted from this search in the current bot run. '
             + 'Only moves while that user\'s bot is actively running.',
    });
    sessionCountSpans.set(row.id, span);
    return span;
  };

  const sameAsAbove = () => el('span', {
    class: 'table__muted', text: 'Same as above',
    title: 'Alternate URLs always use the parent search\'s target position, work history, '
           + 'education, and session cap.',
  });

  /** Lets a main row pull in a URL variation that was manually added under a
   *  DIFFERENT main row -- reapplies that source sub-row's own diff onto this
   *  row's own URL (see applyUrlDiff) rather than copying the URL verbatim. */
  const openCopyVariationsModal = async (currentRow) => {
    const groups = mainRows
      .filter((m) => m.id !== currentRow.id)
      .map((m) => ({ parent: m, subs: subRowsByParent.get(m.id) || [] }))
      .filter((g) => g.subs.length);

    if (!groups.length) {
      toast('No alternate URLs exist under any other search yet', 'error');
      return;
    }

    const selected = new Set();
    const intro = el('p', { class: 'table__muted', style: 'margin:0 0 10px' },
      ['Check off the variations to bring in. Each one reapplies its own difference '
       + '(location, radius, filters, ...) onto this search\'s own URL -- keywords always '
       + `stay "${currentRow.target_position || positionFromUrl(currentRow.url) || 'this search'}".`]);

    // Scrolls on its own (rather than relying on .modal, which clips rather
    // than scrolls) so a user with many searches/variations doesn't lose the
    // footer buttons off the bottom of the screen.
    const picker = el('div', { class: 'variation-picker' });
    groups.forEach(({ parent, subs }) => {
      picker.append(el('div', { class: 'variation-list__group' },
        [parent.target_position || parent.url || 'Untitled search']));
      const list = el('div', { class: 'variation-list' });
      subs.forEach((sub) => {
        const diffs = summarizeUrlDiff(sub.url, parent.url);
        const canApply = applyUrlDiff(currentRow.url, sub.url, parent.url) !== null;
        const label = !canApply
          ? 'Can\'t copy -- invalid URL'
          : (diffs && diffs.length ? diffs.join(' · ') : 'No difference from its own main search');

        const checkbox = el('input', {
          type: 'checkbox', disabled: !canApply,
          onchange: (e) => {
            if (e.target.checked) selected.add(sub.id);
            else selected.delete(sub.id);
          },
        });
        list.append(el('label', { class: `variation-option${canApply ? '' : ' variation-option--disabled'}` }, [
          checkbox,
          el('span', {}, [
            label,
            sub.active ? '' : ' (inactive)',
          ]),
        ]));
      });
      picker.append(list);
    });

    const ok = await confirmModal({
      title: `Copy variations into "${currentRow.target_position || currentRow.url || 'this search'}"`,
      body: [intro, picker],
      confirmLabel: 'Add selected',
    });
    if (!ok) return;

    if (!selected.size) {
      toast('Select at least one variation to copy', 'error');
      return;
    }

    const byId = new Map();
    groups.forEach(({ parent, subs }) => subs.forEach((sub) => byId.set(sub.id, { sub, parent })));

    let added = 0;
    for (const id of selected) {
      const entry = byId.get(id);
      if (!entry) continue;
      const newUrl = applyUrlDiff(currentRow.url, entry.sub.url, entry.parent.url);
      if (newUrl === null) continue;
      // Sequential, not Promise.all: add_subsearch picks its position from
      // MAX(position)+1 for this parent, which would race under concurrent
      // inserts to the same parent.
      await api.post(`/api/searches/${currentRow.id}/subsearches`, { url: newUrl });
      added += 1;
    }

    toast(`Copied ${added} variation${added === 1 ? '' : 's'}`);
    ctx.go('searches');
  };

  const buildSubRow = (row, parentRow) => {
    const diffList = el('ul', { class: 'diff-list' });
    const renderDiff = (subUrl) => {
      diffList.replaceChildren();
      const diffs = summarizeUrlDiff(subUrl, parentRow.url);
      if (diffs === null) {
        diffList.append(el('li', { class: 'table__muted', text: 'Enter a valid URL to compare' }));
      } else if (!diffs.length) {
        diffList.append(el('li', { class: 'table__muted', text: 'No difference from main search' }));
      } else {
        diffs.forEach((d) => diffList.append(el('li', { text: d })));
      }
    };
    renderDiff(row.url);

    const urlInput = el('input', {
      class: 'input', type: 'text', value: row.url || '',
      placeholder: 'https://www.indeed.com/jobs?q=...',
      onchange: (e) => saveField(row.id, 'url', e.target.value),
    });
    urlInput.addEventListener('input', (e) => renderDiff(e.target.value));

    const activeCheckbox = el('input', {
      type: 'checkbox', checked: !!row.active,
      title: 'Uncheck to skip this alternate URL without deleting it.',
      onchange: async (e) => {
        await saveField(row.id, 'active', e.target.checked);
        tr.classList.toggle('is-inactive', !e.target.checked);
      },
    });

    const tr = el('tr', { class: `is-subrow${row.active ? '' : ' is-inactive'}`, dataset: { id: row.id } }, [
      el('td', {}, [el('span', { class: 'subrow-marker', text: '↳', title: 'Alternate URL' })]),
      el('td', {}),
      el('td', {}, [sameAsAbove()]),
      el('td', {}, [urlInput]),
      el('td', {}, [diffList]),
      el('td', {}, [sameAsAbove()]),
      el('td', {}, [sameAsAbove()]),
      el('td', {}, [sameAsAbove()]),
      el('td', { class: 'table__num' }, [sessionSpan(row)]),
      el('td', {}, [el('div', { class: 'table__actions' }, [
        el('label', { class: 'checkbox-label' }, [activeCheckbox, ' Active']),
        el('button', {
          class: 'btn btn--sm btn--ghost', text: 'Delete',
          onclick: async () => {
            const ok = await confirmModal({
              title: 'Delete this alternate URL?',
              body: row.url ? `"${row.url.slice(0, 90)}"` : 'This empty alternate URL will be removed.',
              confirmLabel: 'Delete',
              danger: true,
            });
            if (!ok) return;
            await api.del(`/api/searches/${row.id}`);
            toast('Alternate URL deleted');
            ctx.go('searches');
          },
        }),
      ])]),
    ]);

    return tr;
  };

  const rows = [];

  mainRows.forEach((row, index) => {
    const targetInput = el('input', {
      class: 'input', type: 'text', value: row.target_position || '',
      placeholder: 'e.g. Customer Service Rep', style: 'min-width:180px',
      onchange: (e) => saveField(row.id, 'target_position', e.target.value),
    });

    const maxAppsInput = el('input', {
      class: 'input', type: 'number', min: '0', step: '1',
      value: row.max_applications ? String(row.max_applications) : '',
      placeholder: 'No limit', style: 'width:100px',
      title: 'Switch to the next search after this many applications this session, even if '
             + 'result pages remain. Leave blank/0 for no limit (switch only when out of pages). '
             + 'Alternate URLs under this search share this same cap.',
      onchange: (e) => {
        const n = Math.max(0, parseInt(e.target.value, 10) || 0);
        e.target.value = n ? String(n) : '';
        saveField(row.id, 'max_applications', n);
      },
    });

    const urlInput = el('input', {
      class: 'input', type: 'text', value: row.url || '',
      placeholder: 'https://www.indeed.com/jobs?q=...',
      onchange: (e) => {
        saveField(row.id, 'url', e.target.value);
        // Fill the label in from the search term, but only when it is still
        // blank -- never overwrite a name that was typed by hand.
        if (!targetInput.value.trim()) {
          const derived = positionFromUrl(e.target.value);
          if (derived) {
            targetInput.value = derived;
            saveField(row.id, 'target_position', derived);
          }
        }
      },
    });

    const addAltUrlBtn = el('button', {
      class: 'btn btn--sm btn--ghost', text: '+ Alt URL',
      title: 'Add another search URL for this same target position. It runs right after this '
             + 'search, before the bot moves on to the next one.',
      onclick: async () => {
        await api.post(`/api/searches/${row.id}/subsearches`, { url: '' });
        toast('Alternate URL added');
        ctx.go('searches');
      },
    });

    let hasValidUrl = true;
    try { new URL(row.url); } catch { hasValidUrl = false; }
    const copyVariationBtn = el('button', {
      class: 'btn btn--sm btn--ghost', text: '+ Copy variation',
      disabled: !hasValidUrl,
      title: hasValidUrl
        ? 'Bring in a URL variation that was manually added under a different search -- '
          + 'reapplies that same location/radius/filter change onto this search\'s own URL.'
        : 'Set this search\'s own URL first.',
      onclick: () => openCopyVariationsModal(row),
    });

    // Built before the row itself so the collapse toggle below can flip
    // these <tr>s' visibility directly -- no re-render needed, which would
    // otherwise blow away in-progress edits elsewhere in the table.
    const subTrs = (subRowsByParent.get(row.id) || []).map((sub) => buildSubRow(sub, row));
    let collapsed = collapsedMainRows.has(row.id);
    if (collapsed) subTrs.forEach((subTr) => { subTr.style.display = 'none'; });

    const toggleBtn = subTrs.length
      ? el('button', {
          class: 'row-toggle', type: 'button', text: collapsed ? '▸' : '▾',
          title: collapsed
            ? `Show ${subTrs.length} alternate URL${subTrs.length === 1 ? '' : 's'}`
            : 'Hide alternate URLs',
          onclick: () => {
            collapsed = !collapsed;
            if (collapsed) collapsedMainRows.add(row.id); else collapsedMainRows.delete(row.id);
            toggleBtn.textContent = collapsed ? '▸' : '▾';
            toggleBtn.title = collapsed
              ? `Show ${subTrs.length} alternate URL${subTrs.length === 1 ? '' : 's'}`
              : 'Hide alternate URLs';
            subTrs.forEach((subTr) => { subTr.style.display = collapsed ? 'none' : ''; });
          },
        })
      : el('span', { class: 'row-toggle row-toggle--empty' });

    const tr = el('tr', { draggable: 'true', dataset: { id: row.id } }, [
      el('td', {}, [el('div', { class: 'table__row-lead' }, [
        toggleBtn,
        el('span', { class: 'drag-handle', text: '⠿', title: 'Drag to reorder' }),
      ])]),
      el('td', { class: 'table__num', text: index + 1 }),
      el('td', {}, [targetInput]),
      el('td', {}, [urlInput]),
      el('td', {}),
      el('td', {}, [pickList({
        options: jobOpts,
        value: row.job_nums,
        noun: 'job',
        allLabel: `All jobs (${jobOpts.length})`,
        onChange: (next) => saveField(row.id, 'job_nums', next),
      })]),
      el('td', {}, [pickList({
        options: eduOpts,
        value: row.edu_nums,
        noun: 'education record',
        allLabel: `All education (${eduOpts.length})`,
        onChange: (next) => saveField(row.id, 'edu_nums', next),
      })]),
      el('td', {}, [maxAppsInput]),
      el('td', { class: 'table__num' }, [sessionSpan(row)]),
      el('td', {}, [el('div', { class: 'table__actions' }, [
        addAltUrlBtn,
        copyVariationBtn,
        el('button', {
          class: 'btn btn--sm btn--ghost', text: 'Delete',
          onclick: async () => {
            const subs = subRowsByParent.get(row.id) || [];
            const ok = await confirmModal({
              title: 'Delete this job search?',
              body: [
                row.url ? `"${row.url.slice(0, 90)}"` : 'This empty search row will be removed.',
                subs.length ? `Its ${subs.length} alternate URL${subs.length === 1 ? '' : 's'} will be deleted too.` : null,
              ].filter(Boolean),
              confirmLabel: 'Delete',
              danger: true,
            });
            if (!ok) return;
            await api.del(`/api/searches/${row.id}`);
            toast('Search deleted');
            ctx.go('searches');
          },
        }),
      ])]),
    ]);

    tr.addEventListener('dragstart', () => { dragId = row.id; tr.classList.add('is-dragging'); });
    tr.addEventListener('dragend', () => { dragId = null; tr.classList.remove('is-dragging'); document.querySelectorAll('tr.is-drop-target').forEach((n) => n.classList.remove('is-drop-target')); });
    tr.addEventListener('dragover', (e) => { e.preventDefault(); if (dragId !== row.id) tr.classList.add('is-drop-target'); });
    tr.addEventListener('dragleave', () => tr.classList.remove('is-drop-target'));
    tr.addEventListener('drop', async (e) => {
      e.preventDefault();
      tr.classList.remove('is-drop-target');
      if (dragId === null || dragId === row.id) return;
      const ids = mainRows.map((s) => s.id);
      const from = ids.indexOf(dragId);
      const to = ids.indexOf(row.id);
      if (from === -1 || to === -1) return;   // dragged a sub-row onto a main row; not supported
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      await api.post(`/api/users/${userId}/searches/reorder`, { ids });
      toast('Order updated - this changes which search runs first');
      ctx.go('searches');
    });

    rows.push(tr);
    subTrs.forEach((subTr) => rows.push(subTr));
  });

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table table--static' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '' }),
        el('th', { text: 'Order' }),
        el('th', { text: 'Target position' }),
        el('th', { text: 'Search URL' }),
        el('th', { text: "What's different" }),
        el('th', { text: 'Work history used' }),
        el('th', { text: 'Education used' }),
        el('th', { text: 'Session cap' }),
        el('th', { text: 'This session' }),
        el('th', { text: '' }),
      ])]),
      el('tbody', {}, rows),
    ]),
  ]);

  mount(card(
    'Job searches',
    'Each search can use a subset of this user\'s work history and education. Pick the records from the lists; leaving a list untouched means the bot uses all of them. Session cap limits how many applications the bot submits from a search before rotating to the next one, even if pages remain -- leave it blank for no limit, so the bot only rotates once a search runs out of pages. Use "+ Alt URL" to add another search URL for the same target position -- the bot runs a search\'s alternate URLs right after it, in order, before moving to the next search. "+ Copy variation" brings in a URL variation that was added under a DIFFERENT search, reapplying its same location/radius/filter change onto this search\'s own URL and keywords. "What\'s different" is computed automatically from the two URLs (location, radius, salary, job type, and other filters); it\'s a display hint only, not something you fill in. "This session" shows live counts while that user\'s bot is running. Changes save immediately.',
    [table], [], true,
  ));

  // Only worth polling while this user actually has a run going -- otherwise
  // every row is staying at 0 and there is nothing to refresh.
  const status = await api.get('/api/run/status');
  if (status.runs.some((r) => r.userId === userId && r.alive)) {
    poller = setInterval(async () => {
      if (ctx.state.view !== 'searches' || ctx.state.userId !== userId) { stopSearchesPolling(); return; }
      try {
        const [freshStatus, freshSearches] = await Promise.all([
          api.get('/api/run/status'),
          api.get(`/api/users/${userId}/searches`),
        ]);
        freshSearches.forEach((freshRow) => {
          const span = sessionCountSpans.get(freshRow.id);
          if (span) span.textContent = String(freshRow.sessionApplications ?? 0);
        });
        if (!freshStatus.runs.some((r) => r.userId === userId && r.alive)) stopSearchesPolling();
      } catch { /* a missed tick is not worth surfacing */ }
    }, 3000);
  }
}
