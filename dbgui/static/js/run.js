/* Run screen: pick users, preflight, start/stop, watch live status.

   Ticking a user writes the Active column (one source of truth), so a later
   `python main3.py` with no arguments runs exactly the same set. */

import { api, el, mount, setTopbar, toast, card, emptyState, confirmModal } from './core.js';

let poller = null;
const selection = new Set();
let selectionSeeded = false;

export function stopPolling() {
  if (poller) { clearInterval(poller); poller = null; }
}

export async function renderRun(ctx) {
  const users = await api.get('/api/users');
  ctx.state.users = users;

  // Seed from whoever is already Active, once per session.
  if (!selectionSeeded) {
    users.filter((u) => String(u.Active || '').toUpperCase() === 'T')
         .forEach((u) => selection.add(u.id));
    selectionSeeded = true;
  }

  const status = await api.get('/api/run/status');
  const running = new Map(status.runs.map((r) => [r.userId, r]));
  const anyRunning = status.anyRunning;

  const startBtn = el('button', {
    class: 'btn btn--primary', text: 'Start automation',
    disabled: selection.size === 0 ? true : null,
    onclick: () => start(ctx),
  });
  const stopBtn = el('button', {
    class: 'btn btn--danger', text: 'Stop all',
    disabled: anyRunning ? null : true,
    onclick: async () => {
      const ok = await confirmModal({
        title: 'Stop all running automation?',
        body: 'Each browser will be closed. Work already saved to the database is kept.',
        confirmLabel: 'Stop all', danger: true,
      });
      if (!ok) return;
      await api.post('/api/run/stop', { all: true });
      toast('Stopping...');
      ctx.go('run');
    },
  });

  setTopbar('Run Automation',
    anyRunning ? `${status.runs.filter((r) => r.alive).length} running` : 'Nothing running',
    [stopBtn, startBtn]);

  const nodes = [];

  /* --------------------------------------------------------- selection --- */

  const rows = users.map((user) => {
    const isRunning = running.get(user.id)?.alive;
    const checkbox = el('input', {
      type: 'checkbox', checked: selection.has(user.id) ? true : null,
      disabled: isRunning ? true : null,
      onchange: async (e) => {
        if (e.target.checked) selection.add(user.id); else selection.delete(user.id);
        await api.post('/api/run/selection', { userIds: [...selection] });
        ctx.go('run');
      },
    });

    return el('tr', { class: 'table--static' }, [
      el('td', {}, [checkbox]),
      el('td', { class: 'table__num', text: user.id }),
      el('td', { text: `${user.FirstName || ''} ${user.LastName || ''}`.trim() || '(unnamed)' }),
      el('td', { class: 'table__num', text: user.AppsLeft ?? 0 }),
      el('td', { class: 'table__truncate', text: (user.ProfilePath || '').split('\\').pop() || '(none)' }),
      el('td', {}, [
        isRunning
          ? el('span', { class: 'badge badge--success', text: 'Running' })
          : el('span', { class: 'badge badge--muted', text: 'Idle' }),
      ]),
    ]);
  });

  nodes.push(el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [
        el('h2', { class: 'card__title', text: 'Who should run' }),
        el('p', { class: 'card__hint', text: 'Ticking a user also sets their status to Active, so running main3.py directly uses the same set.' }),
      ]),
      el('span', { class: 'badge badge--info', text: `${selection.size} selected` }),
    ]),
    el('div', { class: 'card__body card__body--flush' }, [
      el('div', { class: 'table-wrap' }, [
        el('table', { class: 'table table--static' }, [
          el('thead', {}, [el('tr', {}, [
            el('th', { text: '' }), el('th', { text: 'ID' }), el('th', { text: 'Name' }),
            el('th', { text: 'Apps left' }), el('th', { text: 'Chrome profile' }), el('th', { text: '' }),
          ])]),
          el('tbody', {}, rows),
        ]),
      ]),
    ]),
  ]));

  /* --------------------------------------------------------- preflight --- */

  if (selection.size) {
    try {
      const problems = await api.get(`/api/run/preflight?user_ids=${[...selection].join(',')}`);
      const blocking = problems.filter((p) => p.blocking);
      if (problems.length) {
        nodes.push(card(
          blocking.length ? 'Cannot start yet' : 'Warnings',
          blocking.length ? 'These must be fixed before the automation can start.' : null,
          [el('div', { class: 'issues' }, problems.map((p) => el('div', {
            class: `issue issue--${p.blocking ? 'error' : 'warning'}`,
          }, [el('span', { class: 'issue__msg', text: p.message })])))],
        ));
        if (blocking.length) startBtn.disabled = true;
      }
    } catch (err) { toast(err.message, 'error'); }
  }

  /* ------------------------------------------------------------ status --- */

  if (status.runs.length) {
    nodes.push(...status.runs.map((run) => renderRunCard(ctx, run)));
  } else {
    nodes.push(card('Live status', null, [
      emptyState('Nothing has run yet', 'Select users above and click "Start automation".'),
    ]));
  }

  mount(el('div', {}, nodes));

  // Poll only while something is alive; stop as soon as everything settles.
  stopPolling();
  if (anyRunning && ctx.state.view === 'run') {
    poller = setInterval(() => {
      if (ctx.state.view !== 'run') { stopPolling(); return; }
      renderRun(ctx).catch(() => {});
    }, 3000);
  }
}

function renderRunCard(ctx, run) {
  const tone = {
    running: 'success', starting: 'warning', paused: 'info',
    error: 'danger', stopped: 'muted',
  }[run.state] || 'muted';
  const mins = Math.floor(run.uptimeSeconds / 60);
  const uptime = mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m ${run.uptimeSeconds % 60}s`;

  const command = async (action, note) => {
    try {
      await api.post('/api/run/command', { userId: run.userId, action });
      toast(note);
      ctx.go('run');
    } catch (err) { toast(err.message, 'error'); }
  };

  const isPaused = run.mode !== 'running';
  const controls = run.alive
    ? [
        el('button', {
          class: 'btn btn--sm', text: 'Go to home page',
          onclick: () => command('home', `${run.label}: going to the home page`),
        }),
        isPaused
          ? el('button', {
              class: 'btn btn--sm btn--primary', text: 'Start applying',
              onclick: () => command('resume', `${run.label}: applying`),
            })
          : el('button', {
              class: 'btn btn--sm', text: 'Pause applications',
              onclick: () => command('pause', `${run.label}: pausing after the current step`),
            }),
      ]
    : [];

  const stopBtn = run.alive
    ? el('button', {
        class: 'btn btn--sm', text: 'Stop',
        onclick: async () => {
          await api.post('/api/run/stop', { userId: run.userId });
          toast(`Stopping ${run.label}`);
          ctx.go('run');
        },
      })
    : null;

  const stats = el('div', { class: 'form-grid' }, [
    statBlock('State', run.state.toUpperCase()),
    statBlock('Uptime', uptime),
    statBlock('Applications this run', String(run.applicationsThisRun)),
    statBlock('Started', run.startedAt.replace('T', ' ')),
  ]);

  const body = [];
  if (run.alive) {
    body.push(el('div', { class: 'runbar' }, [
      el('span', {
        class: `badge badge--${isPaused ? 'info' : 'success'}`,
        text: isPaused ? 'Paused - not applying' : 'Applying',
      }),
      el('span', { class: 'toolbar__spacer' }),
      ...controls,
    ]));
  }
  body.push(stats);

  if (run.lastActivity) {
    body.push(el('div', { class: 'detail-row', style: 'margin-top:20px' }, [
      el('span', { class: 'detail-row__label', text: 'Last activity' }),
      el('div', { class: 'detail-row__value detail-row__value--inline', text: run.lastActivity }),
    ]));
  }
  if (run.lastError) {
    body.push(el('div', { class: 'issue issue--error', style: 'margin-top:16px' }, [
      el('span', { class: 'issue__where', text: 'Last error' }),
      el('span', { class: 'issue__msg', text: run.lastError }),
    ]));
  }

  const logBox = el('div', {
    class: 'detail-row__value textarea--mono',
    style: 'margin-top:16px; max-height:260px; font-size:12px;',
    text: run.lines.length ? run.lines.join('\n') : 'No output yet.',
  });
  // Keep the newest line in view, the way a terminal would.
  setTimeout(() => { logBox.scrollTop = logBox.scrollHeight; }, 0);

  body.push(el('div', { class: 'detail-row', style: 'margin-top:16px' }, [
    el('span', { class: 'detail-row__label', text: `Recent output (last ${run.lines.length} lines)` }),
    logBox,
  ]));

  return el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [
        el('h2', { class: 'card__title', text: run.label }),
        el('p', { class: 'card__hint', text: `User #${run.userId}` }),
      ]),
      el('div', { class: 'toolbar' }, [
        el('span', { class: `badge badge--${tone}`, text: run.state }),
        stopBtn,
      ]),
    ]),
    el('div', { class: 'card__body' }, body),
  ]);
}

function statBlock(label, value) {
  return el('div', { class: 'detail-row' }, [
    el('span', { class: 'detail-row__label', text: label }),
    el('div', { class: 'detail-row__value detail-row__value--inline', text: value }),
  ]);
}

async function start(ctx) {
  try {
    const result = await api.post('/api/run/start', { userIds: [...selection] });
    toast(`Started ${result.started.length} browser${result.started.length === 1 ? '' : 's'}`);
  } catch (err) {
    toast(err.message, 'error');
  }
  ctx.go('run');
}
