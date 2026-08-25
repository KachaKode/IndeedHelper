/* Applications history -- READ ONLY.

   This is a permanent record of what the bot actually sent out, so there is no
   edit path here by design: the API exposes no write route for these tables,
   and every field below renders as static text or a readonly control. */

import { api, el, mount, setTopbar, toast, card, emptyState, readonlyTag } from './core.js';

const LONG_FIELDS = [
  ['headline', 'Headline'],
  ['resumeSummary', 'Resume summary'],
  ['skills', 'Skills'],
  ['jobHist', 'Job history used'],
  ['eduHist', 'Education used'],
  ['QsAndAs', 'Screening questions and answers'],
  ['cover_letter', 'Cover letter'],
  ['JobDescriptionText', 'Original job description'],
];

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

  const rows = data.rows.map((row) => el('tr', {
    class: row.id === state.selectedId ? 'is-selected' : '',
    onclick: async () => { state.selectedId = row.id; ctx.go('applications'); },
  }, [
    el('td', { class: 'table__num', text: row.id }),
    el('td', { text: (row.DateTime || '').slice(0, 16) }),
    el('td', { class: 'table__truncate', text: row.companyName || '' }),
    el('td', { class: 'table__truncate', text: row.jobTitle || '' }),
    el('td', { text: row.fullName || '' }),
  ]));

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: 'ID' }), el('th', { text: 'Date' }), el('th', { text: 'Company' }),
        el('th', { text: 'Job title' }), el('th', { text: 'Applied as' }),
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

  if (state.selectedId != null) {
    try {
      const record = await api.get(`/api/applications/${state.selectedId}`);
      nodes.push(renderDetail(record));
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  mount(el('div', {}, nodes));
}

function renderDetail(record) {
  const summary = el('div', { class: 'form-grid' }, [
    detailRow('Application ID', String(record.id)),
    detailRow('Date', record.DateTime || ''),
    detailRow('Platform', record.Platform || ''),
    detailRow('Applied as', record.fullName || ''),
    detailRow('Company', record.companyName || ''),
    detailRow('Job title', record.jobTitle || ''),
  ]);

  const longNodes = LONG_FIELDS
    .filter(([key]) => (record[key] || '').toString().trim())
    .map(([key, label]) => el('div', { class: 'detail-row' }, [
      el('span', { class: 'detail-row__label', text: label }),
      el('div', { class: 'detail-row__value', text: String(record[key]) }),
    ]));

  return el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [
        el('h2', { class: 'card__title', text: `Application #${record.id}` }),
        el('p', { class: 'card__hint', text: `${record.companyName || ''} - ${record.jobTitle || ''}` }),
      ]),
      readonlyTag(),
    ]),
    el('div', { class: 'card__body' }, [
      summary,
      el('div', { class: 'detail-list', style: 'margin-top:24px' }, longNodes),
    ]),
  ]);
}

function detailRow(label, value) {
  return el('div', { class: 'detail-row' }, [
    el('span', { class: 'detail-row__label', text: label }),
    el('div', { class: 'detail-row__value detail-row__value--inline', text: value }),
  ]);
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

  let selected = null;
  const body = el('div', {});

  const draw = () => {
    const table = el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'ID' }), el('th', { text: 'User' }), el('th', { text: 'Opening info' }),
        ])]),
        el('tbody', {}, rows.map((row) => el('tr', {
          class: row.id === (selected && selected.id) ? 'is-selected' : '',
          onclick: () => { selected = row; draw(); },
        }, [
          el('td', { class: 'table__num', text: row.id }),
          el('td', { class: 'table__num', text: row.user_id }),
          el('td', { class: 'table__truncate', text: (row.opening_info || '').slice(0, 140) }),
        ]))),
      ]),
    ]);

    const nodes = [el('div', { class: 'card' }, [
      el('div', { class: 'card__header' }, [
        el('div', {}, [el('h2', { class: 'card__title', text: 'Legacy applications' })]),
        readonlyTag(),
      ]),
      el('div', { class: 'card__body card__body--flush' }, [table]),
    ])];

    if (selected) {
      nodes.push(card(`Legacy record #${selected.id}`, null, [
        el('div', { class: 'detail-list' }, [
          ['opening_info', 'Opening info'], ['resume', 'Resume'], ['cover_letter', 'Cover letter'],
        ].filter(([k]) => (selected[k] || '').trim()).map(([k, label]) => el('div', { class: 'detail-row' }, [
          el('span', { class: 'detail-row__label', text: label }),
          el('div', { class: 'detail-row__value', text: selected[k] }),
        ]))),
      ], [readonlyTag()]));
    }

    body.replaceChildren(...nodes);
  };

  draw();
  mount(body);
}
