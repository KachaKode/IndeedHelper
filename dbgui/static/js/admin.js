/* Admin tab: OpenAI account status.
   Re-fetches from the server every time this view is entered -- there is no
   "remaining balance" OpenAI will hand over via API (confirmed by hand: every
   /v1/dashboard/billing/* route refuses a secret key), so what is shown here
   is a live probe (the one fact that can actually be known FOR CERTAIN) plus
   spend since the last entered top-up, clearly labelled as an estimate
   rather than a real balance. */

import { api, el, mount, setTopbar, toast, card, field } from './core.js';

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

function statusCard(probe) {
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
  ], [copyBillingUrlButton()]);
}

function spendChart(series) {
  const max = Math.max(0.0001, ...series.map((d) => d.amount));
  return el('div', { class: 'spend-chart' }, series.map((d) => el('div', {
    class: 'spend-chart__bar',
    style: `height:${Math.max(2, Math.round((d.amount / max) * 90))}px`,
    title: `${d.date}: $${d.amount.toFixed(4)}`,
  })));
}

function spendCard(costs, grant, onGrantSaved) {
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
    // The server sums from the grant's own saved-at timestamp when one is on
    // file, so this number and "estimated remaining" below are on the same
    // clock. With no grant yet it falls back to a trailing window just so
    // the tab is not empty.
    const sinceLabel = grant
      ? `spent since your last top-up (${new Date(grant.at).toLocaleString()})`
      : 'spent in the last 30 days -- enter your last purchase below to track from there instead';
    body.push(el('div', { class: 'status-line' }, [
      el('strong', { text: `$${costs.totalSpend.toFixed(2)}` }),
      el('span', { class: 'muted', text: sinceLabel }),
    ]));
    if (costs.series.length) body.push(spendChart(costs.series));
  }

  const grantInput = el('input', {
    class: 'input', type: 'number', min: '0', step: '0.01',
    placeholder: 'e.g. 20.00',
    value: grant == null ? '' : String(grant.amount),
  });
  const saveGrant = el('button', {
    class: 'btn btn--sm', text: 'Save',
    onclick: async () => {
      const amount = parseFloat(grantInput.value);
      if (Number.isNaN(amount) || amount < 0) { toast('Enter a number, 0 or more', 'warning'); return; }
      try {
        await api.put('/api/admin/grant', { amount });
        toast('Saved -- spend will be counted from right now');
        onGrantSaved();
      } catch (err) { toast(err.message, 'error'); }
    },
  });

  body.push(el('div', { class: 'grant-row', style: 'margin-top:16px' }, [
    field('Last amount purchased ($)', grantInput,
          'Enter this right after you top up -- spend only ever counts from the moment you save it, not before.'),
    saveGrant,
  ]));

  if (grant != null && costs.configured && !costs.error) {
    const remaining = grant.amount - costs.totalSpend;
    body.push(el('div', { class: 'status-line', style: 'margin-top:16px' }, [
      el('strong', { text: `~$${remaining.toFixed(2)}` }),
      el('span', { class: 'muted', text: 'estimated remaining (last purchase minus spend since then -- not an official figure)' }),
    ]));
  }

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
    statusCard(status.probe),
    spendCard(status.costs, status.grant, rerender),
  ]));
}
