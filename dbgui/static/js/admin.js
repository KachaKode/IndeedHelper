/* Admin tab: OpenAI account status.
   Re-fetches from the server every time this view is entered -- there is no
   "remaining balance" OpenAI will hand over via API (confirmed by hand: every
   /v1/dashboard/billing/* route refuses a secret key), so what is shown here
   is a live probe (the one fact that can actually be known FOR CERTAIN) plus
   spend since the last entered top-up, clearly labelled as an estimate
   rather than a real balance. */

import { api, el, mount, setTopbar, toast, card } from './core.js';
import { checkCredits } from './credits.js';

const BILLING_URL = 'https://platform.openai.com/settings/organization/billing/overview';

function copyBillingUrlButton() {
  return el('button', {
    class: 'btn btn--sm', text: 'Copy OpenAI billing link',
    onclick: async () => {
      try {
        await navigator.clipboard.writeText(BILLING_URL);
        toast('Billing URL copied');
      } catch {
        toast(BILLING_URL, 'warning');
      }
    },
  });
}

/* Re-probe on demand, and let the app-wide banner catch up with what this tab
   finds -- otherwise the two could disagree until the banner's next poll. */
function recheckButton(onRecheck) {
  return el('button', {
    class: 'btn btn--sm', text: 'Check again',
    onclick: async () => {
      await checkCredits({ manual: true });
      onRecheck();
    },
  });
}

function statusCard(probe, onRecheck) {
  const tone = probe.ok ? 'success' : probe.exhausted ? 'danger' : 'warning';
  const label = probe.ok
    ? 'Working'
    : probe.exhausted
      ? 'Credits exhausted'
      : 'Could not check';

  return card('API status', 'A trivial real call, made just now, against input/api_key.txt.', [
    el('div', { class: 'status-line' }, [
      el('span', { class: `badge badge--${tone}`, text: label }),
      probe.message ? el('span', { class: 'muted', text: probe.message }) : null,
    ]),
  ], [recheckButton(onRecheck), copyBillingUrlButton()]);
}

function spendChart(series) {
  const max = Math.max(0.0001, ...series.map((d) => d.amount));
  return el('div', { class: 'spend-chart' }, series.map((d) => el('div', {
    class: 'spend-chart__bar',
    style: `height:${Math.max(2, Math.round((d.amount / max) * 90))}px`,
    title: `${d.date}: $${d.amount.toFixed(4)}`,
  })));
}

/* A labelled number input with its own button, used for both entries below. */
function amountRow(label, hint, buttonText, onSubmit, initial = '') {
  const input = el('input', {
    class: 'input', type: 'number', min: '0', step: '0.01',
    placeholder: 'e.g. 20.00', value: initial, style: 'flex:0 0 160px',
  });
  const button = el('button', {
    class: 'btn btn--sm', text: buttonText,
    onclick: async () => {
      const amount = parseFloat(input.value);
      if (Number.isNaN(amount) || amount < 0) { toast('Enter a number, 0 or more', 'warning'); return; }
      button.disabled = true;
      try { await onSubmit(amount); } catch (err) { toast(err.message, 'error'); }
      button.disabled = false;
    },
  });
  // The hint sits under the input and button as a pair; wrapped inside the
  // input's own narrow column it ran six lines tall and left the button
  // floating beside its last line.
  return el('div', { class: 'field', style: 'margin-top:16px;max-width:480px' }, [
    el('label', { class: 'field__label', text: label }),
    el('div', { class: 'input-group' }, [input, button]),
    el('span', { class: 'field__hint', text: hint }),
  ]);
}

function lastTopUpLine(grant) {
  if (grant.added == null) return null;
  const carried = grant.carried > 0 ? `, plus ~$${grant.carried.toFixed(2)} that was left` : '';
  return el('p', { class: 'muted', style: 'margin:8px 0 0' },
    [`Last top-up: +$${grant.added.toFixed(2)}${carried} (${new Date(grant.at).toLocaleString()})`]);
}

function spendCard(costs, grant, probe, onChanged) {
  const body = [];

  if (!costs.configured) {
    body.push(el('p', { class: 'muted' }, [
      'Not configured. Generate an Admin API key (org settings, with the ',
      el('code', { text: 'api.usage.read' }),
      ' scope) and save it to ',
      el('code', { text: 'input/admin_api_key.txt' }),
      '.',
    ]));
  } else if (costs.error) {
    body.push(el('p', { class: 'issue issue--error' }, [
      el('span', { class: 'issue__msg', text: costs.error }),
    ]));
  } else {
    // The server sums from the baseline's own saved-at timestamp when one is
    // on file, so this number and "estimated remaining" below are on the same
    // clock. With no baseline yet it falls back to a trailing window just so
    // the tab is not empty.
    const sinceLabel = grant
      ? `spent since your last update (${new Date(grant.at).toLocaleString()})`
      : 'spent in the last 30 days -- record a top-up below to track from there instead';
    body.push(el('div', { class: 'status-line' }, [
      el('strong', { text: `$${costs.totalSpend.toFixed(2)}` }),
      el('span', { class: 'muted', text: sinceLabel }),
    ]));
    if (costs.series.length) body.push(spendChart(costs.series));
  }

  if (grant != null && costs.configured && !costs.error) {
    const remaining = Math.max(0, grant.amount - costs.totalSpend);
    body.push(el('div', { class: 'status-line', style: 'margin-top:16px' }, [
      el('strong', { text: `~$${remaining.toFixed(2)}` }),
      el('span', { class: 'muted', text: 'estimated remaining (balance when last updated, minus spend since -- not an official figure)' }),
    ]));
  }
  if (grant != null) body.push(lastTopUpLine(grant));

  body.push(amountRow(
    'Add a top-up ($)',
    'Enter this right after you add credits. It is added to what was estimated to be left, and spend is counted from the moment you save.',
    'Add',
    async (amount) => {
      const { grant: saved } = await api.post('/api/admin/refill', {
        amount, wasExhausted: probe.exhausted === true,
      });
      toast(saved.carriedKnown
        ? `Added $${amount.toFixed(2)}: estimated balance ~$${saved.amount.toFixed(2)}`
        : `Added $${amount.toFixed(2)}. The earlier balance could not be looked up, so it was not carried over.`,
      saved.carriedKnown ? 'success' : 'warning');
      onChanged();
    },
  ));

  body.push(amountRow(
    'Correct the balance ($)',
    "Type the balance OpenAI's billing page shows to reset the estimate to it. This replaces the baseline instead of adding to it.",
    'Set',
    async (amount) => {
      await api.put('/api/admin/grant', { amount });
      toast('Saved -- spend will be counted from right now');
      onChanged();
    },
    grant == null ? '' : String(grant.amount),
  ));

  return card('Spend', 'From the Admin Costs API, when configured.', body);
}

export async function renderAdmin(ctx) {
  setTopbar('Admin', 'OpenAI account status', []);
  mount(el('div', { class: 'muted' }, ['Loading...']));

  let status;
  try {
    status = await api.get('/api/admin/status');
  } catch (err) {
    toast(err.message, 'error');
    mount(el('div', { class: 'card' }, [el('div', { class: 'card__body' }, [
      el('p', { text: `Could not load admin status: ${err.message}` }),
    ])]));
    return;
  }

  const rerender = () => renderAdmin(ctx);
  mount(el('div', {}, [
    statusCard(status.probe, rerender),
    spendCard(status.costs, status.grant, status.probe, async () => {
      await checkCredits({ recorded: true });
      rerender();
    }),
  ]));
}
