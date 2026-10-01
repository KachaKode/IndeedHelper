/* Outcomes: record what happened after an application, and settle anything the
 * automated capture could not match on its own.
 *
 * Recording is built for entering SEVERAL in a row, because that is how it will
 * actually be used -- you sit down having heard from four employers, not one. So
 * the flow is: search once, click an application, then click stage buttons. The
 * selection survives each save, so recording "they replied" and then "they set up
 * a screen" on the same application is two clicks, not two searches.
 *
 * The review queue is empty until a capture source is running. That is the
 * correct empty state, not an error, and it says so.
 */

import { api, el, mount, setTopbar, toast, card, emptyState, confirmModal, reveal } from './core.js';

// The search endpoint pages at 50. Showing all of them buries the stage buttons
// below the fold, and you only ever need to spot the one you mean.
const MAX_RESULTS = 12;

const state = {
  query: '',
  results: [],
  selected: null,      // the application being recorded against
  selectedEvents: [],
  date: '',
  note: '',
  types: null,         // cached /api/outcome-types
};

const dateOnly = (stamp) => (stamp || '').slice(0, 10);

function todayISO() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

async function loadSelection(ctx, row) {
  state.selected = row;
  state.selectedEvents = await api.get(`/api/applications/${row.id}/events`);
  // The results list is long; without this the stage buttons are off-screen.
  state.revealRecorder = true;
  ctx.go('outcomes');
}

async function record(ctx, eventType) {
  if (!state.selected) return;
  try {
    await api.post(`/api/applications/${state.selected.id}/events`, {
      event_type: eventType,
      occurred_at: state.date || todayISO(),
      note: state.note,
    });
    toast('Outcome recorded');
    // Keep the selection: the next stage for the same application is one click.
    state.selectedEvents = await api.get(`/api/applications/${state.selected.id}/events`);
    ctx.go('outcomes');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function searchCard(ctx) {
  const input = el('input', {
    class: 'input', type: 'text', value: state.query,
    placeholder: 'Company or job title',
  });
  const run = async () => {
    state.query = input.value.trim();
    try {
      const page = await api.get(
        `/api/applications?user_id=${ctx.state.userId}&search=${encodeURIComponent(state.query)}&page=1`);
      state.results = page.rows;
      ctx.go('outcomes');
    } catch (err) {
      toast(err.message, 'error');
    }
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

  const body = [
    el('div', { class: 'toolbar' }, [
      input,
      el('button', { class: 'btn btn--primary btn--sm', text: 'Search', onclick: run }),
    ]),
  ];

  if (state.results.length) {
    const shown = state.results.slice(0, MAX_RESULTS);
    if (state.results.length > MAX_RESULTS) {
      body.push(el('p', { class: 'muted', text:
        `Showing ${MAX_RESULTS} of ${state.results.length} matches — narrow the search to see others.` }));
    }
    body.push(el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'Company' }), el('th', { text: 'Role' }),
          el('th', { text: 'Applied' }),
        ])]),
        el('tbody', {}, shown.map((row) => el('tr', {
          class: state.selected && state.selected.id === row.id ? 'is-selected' : '',
          onclick: () => loadSelection(ctx, row),
        }, [
          el('td', { class: 'table__truncate', title: row.companyName, text: row.companyName || '-' }),
          el('td', { class: 'table__truncate', title: row.jobTitle, text: row.jobTitle || '-' }),
          el('td', { class: 'table__num', text: dateOnly(row.DateTime) }),
        ]))),
      ]),
    ]));
  } else if (state.query) {
    body.push(emptyState('No matches', `Nothing found for "${state.query}".`));
  }

  return card('Find the application', 'Search this user\'s applications, then pick one.',
              body, [], state.results.length > 0);
}

function recorderCard(ctx) {
  if (!state.selected) {
    return card('Record an outcome', null, [
      emptyState('Pick an application first',
                 'Search above and click a row to record what happened.'),
    ]);
  }

  const chosen = state.selected;
  const dateInput = el('input', {
    class: 'input', type: 'text', style: 'max-width:140px',
    value: state.date || todayISO(), placeholder: 'YYYY-MM-DD',
    onchange: (e) => { state.date = e.target.value.trim(); },
  });
  const noteInput = el('input', {
    class: 'input', type: 'text', placeholder: 'Optional note',
    value: state.note,
    onchange: (e) => { state.note = e.target.value; },
  });

  const ladder = state.types.filter((t) => !t.terminal);
  const terminal = state.types.filter((t) => t.terminal);

  const already = new Set(state.selectedEvents.map((e) => e.event_type));
  const button = (type) => el('button', {
    class: `btn btn--sm${already.has(type.value) ? '' : ' btn--primary'}`,
    text: already.has(type.value) ? `${type.label} ✓` : type.label,
    title: already.has(type.value)
      ? 'Already recorded — click to record it again with this date'
      : `Record "${type.label}"`,
    onclick: () => record(ctx, type.value),
  });

  const recorded = state.selectedEvents.length
    ? el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table table--static' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'Recorded' }), el('th', { text: 'When' }),
          el('th', { text: 'Source' }), el('th', { text: '' }),
        ])]),
        el('tbody', {}, state.selectedEvents.map((ev) => el('tr', {}, [
          el('td', { text: ev.label }),
          el('td', { class: 'table__num', text: dateOnly(ev.occurred_at) }),
          el('td', {}, [el('span', { class: 'badge badge--muted', text: ev.source })]),
          el('td', {}, [el('button', {
            class: 'btn btn--sm btn--ghost', text: 'Remove',
            onclick: async () => {
              await api.del(`/api/application-events/${ev.id}`);
              state.selectedEvents = await api.get(`/api/applications/${chosen.id}/events`);
              toast('Removed');
              ctx.go('outcomes');
            },
          })]),
        ]))),
      ]),
    ])
    : el('p', { class: 'muted', text: 'Nothing recorded for this application yet.' });

  return card(
    `${chosen.companyName || 'Unknown company'} — ${chosen.jobTitle || 'Unknown role'}`,
    `Applied ${dateOnly(chosen.DateTime)}. Click a stage to record it on the date below.`,
    [
      el('div', { class: 'toolbar' }, [
        el('span', { class: 'muted', text: 'Date' }), dateInput, noteInput,
      ]),
      el('div', { class: 'chips', style: 'margin-top:var(--sp-3)' }, ladder.map(button)),
      el('div', { class: 'chips', style: 'margin-top:var(--sp-2)' }, terminal.map(button)),
      el('div', { style: 'margin-top:var(--sp-4)' }, [recorded]),
    ],
    [el('button', {
      class: 'btn btn--sm btn--ghost', text: 'Clear',
      onclick: () => { state.selected = null; state.selectedEvents = []; ctx.go('outcomes'); },
    })]);
}

function reviewCard(ctx, review, counts) {
  if (!review.length) {
    return card('Review queue', 'Captured items that could not be matched automatically.', [
      emptyState(
        counts.open ? 'Nothing open' : 'Nothing to review',
        'This fills once automated capture is running. Anything it cannot tie to an '
        + 'application with confidence lands here instead of being guessed into the log.'),
    ]);
  }

  const rows = review.map((item) => el('tr', {}, [
    el('td', { class: 'table__num', text: dateOnly(item.observed_at) }),
    el('td', { class: 'table__truncate', title: item.subject || item.company,
               text: item.subject || item.company || '-' }),
    el('td', {}, [el('span', { class: 'badge badge--warning', text: item.match_state })]),
    el('td', { text: item.classified_type || '-' }),
    el('td', {}, [
      el('button', {
        class: 'btn btn--sm btn--ghost', text: 'Ignore',
        onclick: async () => {
          try {
            await api.post(`/api/capture-items/${item.id}/resolve`, { ignore: true });
            toast('Ignored');
            ctx.go('outcomes');
          } catch (err) { toast(err.message, 'error'); }
        },
      }),
    ]),
  ]));

  return card('Review queue',
              `${review.length} item(s) need a decision.`, [
    el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table table--static' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'Seen' }), el('th', { text: 'What' }), el('th', { text: 'State' }),
          el('th', { text: 'Reads as' }), el('th', { text: '' }),
        ])]),
        el('tbody', {}, rows),
      ]),
    ]),
  ], [], true);
}

function recentCard(ctx, events) {
  if (!events.length) {
    return card('Recorded outcomes', null, [
      emptyState('Nothing recorded yet',
                 'Every rate on the Stats page stays empty until outcomes exist here.'),
    ]);
  }

  const rows = events.map((ev) => el('tr', {}, [
    el('td', { class: 'table__num', text: dateOnly(ev.occurred_at) }),
    el('td', { class: 'table__truncate', title: ev.companyName || '',
               text: ev.companyName || '(unattributed)' }),
    el('td', { class: 'table__truncate', title: ev.jobTitle || '', text: ev.jobTitle || '-' }),
    el('td', { text: ev.label }),
    el('td', {}, [el('span', { class: 'badge badge--muted', text: ev.source })]),
    el('td', {}, [el('button', {
      class: 'btn btn--sm btn--ghost', text: 'Remove',
      onclick: async () => {
        const ok = await confirmModal({
          title: 'Remove this outcome?',
          body: `${ev.label} for ${ev.companyName || 'an unattributed item'} on ${dateOnly(ev.occurred_at)}.`,
          confirmLabel: 'Remove', danger: true,
        });
        if (!ok) return;
        try {
          await api.del(`/api/application-events/${ev.id}`);
          toast('Removed');
          ctx.go('outcomes');
        } catch (err) { toast(err.message, 'error'); }
      },
    })]),
  ]));

  return card('Recorded outcomes', `${events.length} most recent.`, [
    el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table table--static' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'When' }), el('th', { text: 'Company' }), el('th', { text: 'Role' }),
          el('th', { text: 'Outcome' }), el('th', { text: 'Source' }), el('th', { text: '' }),
        ])]),
        el('tbody', {}, rows),
      ]),
    ]),
  ], [], true);
}

export async function renderOutcomes(ctx) {
  const userId = ctx.state.userId;
  setTopbar('Outcomes', 'What happened after each application.', [], ctx.userLabel());
  mount(el('div', { class: 'muted', text: 'Loading...' }));

  if (!state.types) state.types = await api.get('/api/outcome-types');
  const data = await api.get(`/api/users/${userId}/outcomes`);
  ctx.setCount('outcomes', data.events.length || null);

  const recorder = recorderCard(ctx);
  mount(el('div', {}, [
    el('div', { class: 'stats-note' }, [
      'Recording an outcome never touches the application itself — outcomes live in '
      + 'a separate log. An acknowledgement or a "viewed" is recorded but ',
      el('strong', { text: 'does not count as a response' }),
      ' on the Stats page; a real response starts at "Real response".',
    ]),
    searchCard(ctx),
    recorder,
    reviewCard(ctx, data.review, data.counts),
    recentCard(ctx, data.events),
  ]));

  if (state.revealRecorder) {
    state.revealRecorder = false;
    reveal(recorder);
  }
}
