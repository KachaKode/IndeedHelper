/* Applications history -- READ ONLY.

   This is a permanent record of what the bot actually sent out, so there is no
   edit path here by design: the API exposes no write route for these tables,
   and every field below renders as static text or a readonly control. */

import { api, el, mount, reveal, setTopbar, toast, card, emptyState, readonlyTag } from './core.js';
import { applicationBody } from './appdetail.js';

const COLUMNS = 6;

const state = { page: 1, search: '', userId: '', selectedId: null };

export async function renderApplications(ctx) {
  const params = new URLSearchParams({ page: String(state.page) });
  if (state.search) params.set('search', state.search);
  if (state.userId) params.set('user_id', state.userId);

  const data = await api.get(`/api/applications?${params}`);
  ctx.setCount('apps', data.total);

  setTopbar('Applications', `${data.total.toLocaleString()} sent`,
            [readonlyTag('Read only - history')], ctx.userLabel());

  const searchBox = el('input', {
    class: 'input search-input', type: 'search', value: state.search,
    placeholder: 'Search company, job title, name, date...',
    onchange: (e) => { state.search = e.target.value; state.page = 1; ctx.go('applications'); },
  });

  const userFilter = el('select', { class: 'select', style: 'width:auto', onchange: (e) => {
    state.userId = e.target.value; state.page = 1; ctx.go('applications');
  } }, [
    el('option', { value: '', text: 'All users' }),
    ...ctx.state.users.map((u) => el('option', {
      value: String(u.id),
      text: `${u.FirstName || ''} ${u.LastName || ''}`.trim() || `User ${u.id}`,
    })),
  ]);
  userFilter.value = state.userId;

  const nodes = [];
  nodes.push(el('div', { class: 'card' }, [
    el('div', { class: 'card__body' }, [
      el('div', { class: 'toolbar' }, [searchBox, userFilter, el('span', { class: 'toolbar__spacer' })]),
    ]),
  ]));

  if (!data.rows.length) {
    nodes.push(card('Results', null, [emptyState('No applications match', 'Try clearing the search or user filter.')]));
    mount(el('div', {}, nodes));
    return;
  }

  const rows = data.rows.map((row) => {
    const caret = el('span', { class: 'caret', text: '›' });
    const tr = el('tr', {}, [
      el('td', { class: 'table__num' }, [caret, ` ${row.id}`]),
      el('td', { text: (row.DateTime || '').slice(0, 16) }),
      el('td', { class: 'table__truncate', text: row.companyName || '' }),
      el('td', { class: 'table__truncate', text: row.jobTitle || '' }),
      el('td', { text: row.fullName || '' }),
      el('td', { class: 'table__truncate', text: row.searchLabel || '' }),
    ]);
    tr.addEventListener('click', () => toggleRow(row, tr));
    return tr;
  });

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: 'ID' }), el('th', { text: 'Date' }), el('th', { text: 'Company' }),
        el('th', { text: 'Job title' }), el('th', { text: 'Applied as' }),
        el('th', { text: 'Job search' }),
      ])]),
      el('tbody', {}, rows),
    ]),
  ]);

  const pager = el('div', { class: 'pager' }, [
    el('span', { class: 'pager__info', text: `Page ${data.page} of ${data.pages} - ${data.total.toLocaleString()} total` }),
    el('div', { class: 'pager__controls' }, [
      el('button', {
        class: 'btn btn--sm', text: 'Previous', disabled: data.page <= 1 ? true : null,
        onclick: () => { state.page = Math.max(1, state.page - 1); ctx.go('applications'); },
      }),
      el('button', {
        class: 'btn btn--sm', text: 'Next', disabled: data.page >= data.pages ? true : null,
        onclick: () => { state.page = Math.min(data.pages, state.page + 1); ctx.go('applications'); },
      }),
    ]),
  ]);

  const listCard = el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [
        el('h2', { class: 'card__title', text: 'Sent applications' }),
        el('p', { class: 'card__hint', text: 'Click a row to see the full record.' }),
      ]),
      readonlyTag(),
    ]),
    el('div', { class: 'card__body card__body--flush' }, [table]),
    pager,
  ]);
  nodes.push(listCard);

  mount(el('div', {}, nodes));
}

/* Expand the record IN PLACE, as a row directly beneath the one clicked.
   It used to be appended below the whole table, which meant scrolling past 50
   rows to read it and back up again to pick the next one. Nothing is re-fetched
   or re-rendered here, so the list does not move under the pointer. */
async function toggleRow(row, tr) {
  const open = tr.nextElementSibling;
  const isOpenForThisRow = open && open.classList.contains('row-detail')
                           && open.dataset.for === String(row.id);

  // Only one open at a time: collapsing first keeps the list short enough to
  // scan, which is the point of expanding in place.
  const table = tr.closest('table');
  table.querySelectorAll('tr.row-detail').forEach((n) => n.remove());
  table.querySelectorAll('tr.is-selected').forEach((n) => n.classList.remove('is-selected'));

  if (isOpenForThisRow) {
    state.selectedId = null;
    return;
  }

  state.selectedId = row.id;
  tr.classList.add('is-selected');

  const host = el('td', { colspan: String(COLUMNS) }, [
    el('div', { class: 'row-detail__inner' }, [el('div', { class: 'muted', text: 'Loading…' })]),
  ]);
  const detailRow = el('tr', { class: 'row-detail', dataset: { for: String(row.id) } }, [host]);
  tr.after(detailRow);

  try {
    const record = await api.get(`/api/applications/${row.id}`);
    // The row may have been collapsed again while the request was in flight.
    if (!detailRow.isConnected) return;
    host.replaceChildren(el('div', { class: 'row-detail__inner' }, [
      el('div', { class: 'row-detail__head' }, [
        el('h3', { class: 'row-detail__title', text: `Application #${record.id}` }),
        readonlyTag(),
      ]),
      applicationBody(record),
    ]));
    // Only nudge if the expansion pushed itself off-screen.
    revealIfBelowFold(detailRow);
  } catch (err) {
    if (detailRow.isConnected) {
      host.replaceChildren(el('div', { class: 'row-detail__inner' }, [
        el('div', { class: 'muted', text: err.message }),
      ]));
    }
    toast(err.message, 'error');
  }
}

/** Scroll only when the freshly opened record starts below the visible area --
 *  expanding a row near the top should not move the page at all. */
function revealIfBelowFold(node) {
  requestAnimationFrame(() => {
    const top = node.getBoundingClientRect().top;
    if (top > window.innerHeight - 80) reveal(node);
  });
}

/* ------------------------------------------------------------------ legacy */

export async function renderApplicationsOld(ctx) {
  const rows = await api.get('/api/applications-old');
  ctx.setCount('apps-old', rows.length);
  setTopbar('Legacy Applications', `${rows.length} records from the older schema`,
            [readonlyTag('Read only - history')], ctx.userLabel());

  if (!rows.length) {
    mount(card('Legacy applications', null, [emptyState('Nothing here', 'The applicationsOld table is empty.')]));
    return;
  }

  // Expanded in place, like the main table. This one is not paginated at all,
  // so a record shown below the list landed 3000px down.
  const tableRows = rows.map((row) => {
    const caret = el('span', { class: 'caret', text: '›' });
    const tr = el('tr', {}, [
      el('td', { class: 'table__num' }, [caret, ` ${row.id}`]),
      el('td', { class: 'table__num', text: row.user_id }),
      el('td', { class: 'table__truncate', text: (row.opening_info || '').slice(0, 140) }),
    ]);
    tr.addEventListener('click', () => toggleLegacyRow(row, tr));
    return tr;
  });

  mount(el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [el('h2', { class: 'card__title', text: 'Legacy applications' })]),
      readonlyTag(),
    ]),
    el('div', { class: 'card__body card__body--flush' }, [
      el('div', { class: 'table-wrap' }, [
        el('table', { class: 'table' }, [
          el('thead', {}, [el('tr', {}, [
            el('th', { text: 'ID' }), el('th', { text: 'User' }), el('th', { text: 'Opening info' }),
          ])]),
          el('tbody', {}, tableRows),
        ]),
      ]),
    ]),
  ]));
}

const LEGACY_FIELDS = [
  ['opening_info', 'Opening info'],
  ['resume', 'Resume'],
  ['cover_letter', 'Cover letter'],
];

function toggleLegacyRow(row, tr) {
  const open = tr.nextElementSibling;
  const isOpenForThisRow = open && open.classList.contains('row-detail')
                           && open.dataset.for === String(row.id);

  const table = tr.closest('table');
  table.querySelectorAll('tr.row-detail').forEach((n) => n.remove());
  table.querySelectorAll('tr.is-selected').forEach((n) => n.classList.remove('is-selected'));
  if (isOpenForThisRow) return;

  tr.classList.add('is-selected');
  const detailRow = el('tr', { class: 'row-detail', dataset: { for: String(row.id) } }, [
    el('td', { colspan: '3' }, [
      el('div', { class: 'row-detail__inner' }, [
        el('div', { class: 'row-detail__head' }, [
          el('h3', { class: 'row-detail__title', text: `Legacy record #${row.id}` }),
          readonlyTag(),
        ]),
        el('div', { class: 'detail-list' },
          LEGACY_FIELDS.filter(([k]) => (row[k] || '').trim()).map(([k, label]) =>
            el('div', { class: 'detail-row' }, [
              el('span', { class: 'detail-row__label', text: label }),
              el('div', { class: 'detail-row__value', text: row[k] }),
            ]))),
      ]),
    ]),
  ]);
  tr.after(detailRow);
  revealIfBelowFold(detailRow);
}
