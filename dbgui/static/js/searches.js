/* Job Searches -- CRUD over the job_searches table.

   Row order is functional, not cosmetic: the bot starts on position 0 and
   cycles from there, so drag-to-reorder changes which search runs first. */

import { api, el, mount, setTopbar, toast, card, emptyState, confirmModal } from './core.js';
import { pickList, jobOptions, eduOptions } from './picklist.js';

/** Mirror of migrations.position_from_url: derive a label from the `q` term. */
function positionFromUrl(url) {
  try {
    const term = (new URL(url).searchParams.get('q') || '').trim();
    return term.replace(/\b\w/g, (c) => c.toUpperCase());
  } catch {
    return '';
  }
}

export async function renderSearches(ctx) {
  const userId = ctx.state.userId;
  const [searches, jobs, edus] = await Promise.all([
    api.get(`/api/users/${userId}/searches`),
    api.get(`/api/users/${userId}/jobs`),
    api.get(`/api/users/${userId}/edu`),
  ]);
  const jobOpts = jobOptions(jobs);
  const eduOpts = eduOptions(edus);
  ctx.setCount('searches', searches.length);

  const addBtn = el('button', {
    class: 'btn btn--primary', text: 'Add search',
    onclick: async () => {
      await api.post(`/api/users/${userId}/searches`, { url: '', job_nums: '', edu_nums: '' });
      toast('Search added');
      ctx.go('searches');
    },
  });
  setTopbar('Job Searches', `${searches.length} configured - the bot starts with the first one`,
            [addBtn], ctx.userLabel());

  if (!searches.length) {
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

  const rows = searches.map((row, index) => {
    const targetInput = el('input', {
      class: 'input', type: 'text', value: row.target_position || '',
      placeholder: 'e.g. Customer Service Rep', style: 'min-width:180px',
      onchange: (e) => saveField(row.id, 'target_position', e.target.value),
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

    const tr = el('tr', { draggable: 'true', dataset: { id: row.id } }, [
      el('td', {}, [el('span', { class: 'drag-handle', text: '⠿', title: 'Drag to reorder' })]),
      el('td', { class: 'table__num', text: index + 1 }),
      el('td', {}, [targetInput]),
      el('td', {}, [urlInput]),
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
      el('td', {}, [el('button', {
        class: 'btn btn--sm btn--ghost', text: 'Delete',
        onclick: async () => {
          const ok = await confirmModal({
            title: 'Delete this job search?',
            body: row.url ? `"${row.url.slice(0, 90)}"` : 'This empty search row will be removed.',
            confirmLabel: 'Delete',
            danger: true,
          });
          if (!ok) return;
          await api.del(`/api/searches/${row.id}`);
          toast('Search deleted');
          ctx.go('searches');
        },
      })]),
    ]);

    tr.addEventListener('dragstart', () => { dragId = row.id; tr.classList.add('is-dragging'); });
    tr.addEventListener('dragend', () => { dragId = null; tr.classList.remove('is-dragging'); document.querySelectorAll('tr.is-drop-target').forEach((n) => n.classList.remove('is-drop-target')); });
    tr.addEventListener('dragover', (e) => { e.preventDefault(); if (dragId !== row.id) tr.classList.add('is-drop-target'); });
    tr.addEventListener('dragleave', () => tr.classList.remove('is-drop-target'));
    tr.addEventListener('drop', async (e) => {
      e.preventDefault();
      tr.classList.remove('is-drop-target');
      if (dragId === null || dragId === row.id) return;
      const ids = searches.map((s) => s.id);
      const from = ids.indexOf(dragId);
      const to = ids.indexOf(row.id);
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      await api.post(`/api/users/${userId}/searches/reorder`, { ids });
      toast('Order updated - this changes which search runs first');
      ctx.go('searches');
    });

    return tr;
  });

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table table--static' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '' }),
        el('th', { text: 'Order' }),
        el('th', { text: 'Target position' }),
        el('th', { text: 'Search URL' }),
        el('th', { text: 'Work history used' }),
        el('th', { text: 'Education used' }),
        el('th', { text: '' }),
      ])]),
      el('tbody', {}, rows),
    ]),
  ]);

  mount(card(
    'Job searches',
    'Each search can use a subset of this user\'s work history and education. Pick the records from the lists; leaving a list untouched means the bot uses all of them. Changes save immediately.',
    [table], [], true,
  ));
}
