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

  // Every poll rebuilds this whole view, including a brand-new log box per
  // run -- which would always start at scrollTop 0. Capture where the user
  // was reading (per run, by userId) before the old boxes are torn out, then
  // put each new box back in the same place: pinned to the bottom if they
  // were already there, held in place if they had scrolled up to read.
  const priorScroll = new Map();
  document.querySelectorAll('[data-run-log]').forEach((box) => {
    priorScroll.set(box.dataset.runLog, {
      top: box.scrollTop,
      atBottom: box.scrollHeight - box.scrollTop - box.clientHeight < 40,
    });
  });

  mount(el('div', {}, nodes));

  document.querySelectorAll('[data-run-log]').forEach((box) => {
    const prior = priorScroll.get(box.dataset.runLog);
    box.scrollTop = (!prior || prior.atBottom) ? box.scrollHeight : prior.top;
  });

  // Poll only while something is alive; stop as soon as everything settles.
  stopPolling();
  if (anyRunning && ctx.state.view === 'run') {
    poller = setInterval(() => {
      if (ctx.state.view !== 'run') { stopPolling(); return; }
      // Re-rendering rebuilds the DOM, which would drop whatever the user is
      // part-way through highlighting. Hold still until they let go.
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;
      renderRun(ctx).catch(() => {});
    }, 3000);
  }
}

function renderRunCard(ctx, run) {
  const tone = {
    running: 'success', starting: 'warning', paused: 'info',
    attention: 'warning', error: 'danger', stopped: 'muted',
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
    const needsYou = run.state === 'attention';
    const reason = (run.attentionReason || '').toLowerCase();
    const note = reason.includes('unknown')
      ? 'The bot hit a page it does not recognise and paused. Look at the browser window '
        + '(and save the page HTML if you want it handled), then press Start applying.'
      : 'Indeed put up a bot check and the run is paused. Solve it in the browser window, '
        + 'then press Start applying.';

    body.push(el('div', { class: `runbar${needsYou ? ' runbar--alert' : ''}` }, [
      el('span', {
        class: `badge badge--${needsYou ? 'warning' : isPaused ? 'info' : 'success'}`,
        text: needsYou
          ? `${run.attentionReason || 'Needs you'} - needs you`
          : isPaused ? 'Paused - not applying' : 'Applying',
      }),
      needsYou ? el('span', { class: 'runbar__note', text: note }) : null,
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

  const logText = run.lines.length ? run.lines.join('\n') : 'No output yet.';
  const logBox = el('div', {
    class: 'detail-row__value textarea--mono is-selectable',
    style: 'margin-top:8px; max-height:260px; font-size:12px;',
    'data-run-log': run.userId,
  }, run.lines.length ? logLines(run.lines) : [el('span', { text: logText })]);
  // Scroll position (stay at bottom, or hold where the user scrolled to) is
  // restored by renderRun() after it remounts this box -- see priorScroll there.

  // Copy hands back the COMPLETE log from the server, not the displayed tail.
  // The box only shows the last 200 lines for speed, but a truncated log is
  // useless for working out what went wrong at the start of a run.
  const copyBtn = el('button', {
    class: 'btn btn--sm btn--ghost', text: 'Copy full log',
    onclick: async (e) => {
      const button = e.target;
      const original = button.textContent;
      button.textContent = 'Copying...';
      try {
        const res = await fetch(`/api/run/log/${run.userId}`);
        const full = await res.text();
        const text = full.trim() ? full : logText;
        try {
          await navigator.clipboard.writeText(text);
          toast(`Copied the full log (${text.split('\n').length} lines)`);
        } catch {
          // Clipboard refused: drop it into the box and select it so Ctrl+C works.
          logBox.textContent = text;
          const range = document.createRange();
          range.selectNodeContents(logBox);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          toast('Full log selected - press Ctrl+C to copy', 'warning');
        }
      } catch (err) {
        toast(`Could not fetch the full log: ${err.message}`, 'error');
      } finally {
        button.textContent = original;
      }
    },
  });

  body.push(el('div', { class: 'detail-row', style: 'margin-top:16px' }, [
    el('div', { class: 'log-head' }, [
      el('span', { class: 'detail-row__label', text: `Recent output (last ${run.lines.length} lines)` }),
      copyBtn,
    ]),
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

// main3.py's ct_section()/ct_print() write plain-text markers (">>> PAGE:",
// ">>> QUESTION:", a "---" rule, "| ERROR |", "NEEDS ATTENTION" /
// "ATTENTION CLEARED", "reportAction |") specifically so the trace stays
// readable in a plain-text log file too -- this just recognises the same
// markers here and colors them, rather than duplicating the log format.
function logLines(lines) {
  return lines.map((line) => {
    let cls = 'log-line';
    if (line.includes('>>> PAGE:')) cls += ' log-line--page';
    else if (line.includes('>>> QUESTION:')) cls += ' log-line--question';
    else if (line.includes('| ERROR |')) cls += ' log-line--error';
    else if (line.includes('NEEDS ATTENTION') || line.includes('ATTENTION CLEARED')) cls += ' log-line--attention';
    else if (/-{10,}/.test(line)) cls += ' log-line--rule';
    else if (line.includes('reportAction |')) cls += ' log-line--action';
    return el('div', { class: cls, text: line.length ? line : ' ' });
  });
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
