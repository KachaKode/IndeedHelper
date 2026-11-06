/* The OpenAI credit banner above every tab.

   App-shell state, not view state: it has to stay visible no matter which nav
   item is active, so it lives outside VIEWS/go() entirely and keeps polling in
   the background. Three states:

     ok         hidden.
     exhausted  a real call failed with insufficient_quota. Re-checked every
                30 seconds, and again the moment the window regains focus --
                the person has just come back from OpenAI's billing page in
                another tab. A call that fails for lack of credit is not
                billed, so polling this often costs nothing.
     restored   credits work again. Stays up until the person says how much
                they added (or dismisses it), because that amount is what lets
                the Admin tab keep an estimate of what is left. Typing it is
                optional, but this is the one moment it is easy to ask for.

   While healthy it polls only every 10 minutes: a successful probe spends a
   fraction of a cent, and the Admin tab gives an on-demand check anyway. */

import { api, toast } from './core.js';

const BILLING_URL = 'https://platform.openai.com/settings/organization/billing/overview';
const POLL_MS = { ok: 10 * 60 * 1000, exhausted: 30 * 1000, restored: 10 * 60 * 1000 };
const MIN_GAP_BETWEEN_CHECKS_MS = 3000;

let state = 'ok';
let sawExhausted = false;   // true from the first 'exhausted' until the banner is put away
let checking = false;
let lastCheckAt = 0;
let timer = null;
let onBalanceChange = () => {};

const node = (id) => document.getElementById(id);

function show(next, message) {
  state = next;
  if (next === 'exhausted') sawExhausted = true;
  node('credit-alert-text').textContent = message;
  const banner = node('credit-alert');
  banner.dataset.state = next;
  banner.hidden = false;
}

function hide() {
  state = 'ok';
  sawExhausted = false;
  node('credit-alert-amount').value = '';
  node('credit-alert').hidden = true;
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(() => checkCredits(), POLL_MS[state]);
}

/** Record the typed top-up (if any) and put the banner away. */
async function saveAmount() {
  const raw = node('credit-alert-amount').value.trim();
  if (raw === '') { hide(); return; }

  const amount = parseFloat(raw);
  if (!(amount > 0)) { toast('Enter an amount above 0, or leave it blank', 'warning'); return; }

  try {
    const { grant } = await api.post('/api/admin/refill', { amount, wasExhausted: sawExhausted });
    const balance = `~$${grant.amount.toFixed(2)}`;
    if (!grant.carriedKnown) {
      toast(`Added $${amount.toFixed(2)}. Estimated balance ${balance} -- the earlier balance `
        + 'could not be looked up, so it was not carried over.', 'warning');
    } else if (grant.carried > 0) {
      toast(`Added $${amount.toFixed(2)} to ~$${grant.carried.toFixed(2)} left: estimated balance ${balance}`);
    } else {
      toast(`Added $${amount.toFixed(2)}: estimated balance ${balance}`);
    }
    hide();
    onBalanceChange();
  } catch (err) {
    toast(err.message, 'error');
  }
}

/** Probe OpenAI and move the banner to match.
 *
 *  `manual` is the person pressing "I've refilled", or the Admin tab asking
 *  for a fresh look: it speaks up when the answer is still "no credits", and
 *  records a typed amount straight away instead of asking for it.
 *
 *  `recorded` means the top-up was already entered somewhere else (the Admin
 *  tab), so working credits just clear the banner instead of asking again. */
export async function checkCredits({ manual = false, recorded = false } = {}) {
  if (checking && !manual) return;
  checking = true;
  let probe;
  try {
    probe = await api.get('/api/admin/probe');
  } catch (err) {
    // Our own server being unreachable is not an OpenAI problem to alarm about.
    probe = { error: err.message };
  } finally {
    checking = false;
    lastCheckAt = Date.now();
  }

  if (probe.error) {
    if (manual) toast(`Could not check: ${probe.error}`, 'warning');
  } else if (probe.exhausted) {
    show('exhausted', `OpenAI credits are exhausted: ${probe.message || 'no credits remaining.'}`);
    if (manual) {
      toast('OpenAI still reports no credits. A new top-up can take a minute to apply -- '
        + 'this checks again every 30 seconds.', 'warning');
    }
  } else if (probe.ok) {
    if (state === 'exhausted' && recorded) {
      hide();
    } else if (state === 'exhausted') {
      show('restored', 'OpenAI credits are back. How much did you add? (optional)');
      if (manual && node('credit-alert-amount').value.trim() !== '') await saveAmount();
    }
  } else if (manual) {
    // Neither working nor out of credit: a bad key, a rate limit, no network.
    toast(probe.message || 'Could not check OpenAI.', 'warning');
  }
  schedule();
}

/** `onChange` runs after a top-up is recorded, so a view showing the balance
 *  (the Admin tab) can redraw. */
export function wireCreditAlert({ onChange } = {}) {
  if (onChange) onBalanceChange = onChange;

  node('credit-alert-goto').addEventListener('click', () => window.open(BILLING_URL, '_blank'));
  node('credit-alert-refilled').addEventListener('click', () => checkCredits({ manual: true }));
  node('credit-alert-save').addEventListener('click', saveAmount);
  node('credit-alert-dismiss').addEventListener('click', hide);
  node('credit-alert-amount').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (state === 'restored') saveAmount(); else checkCredits({ manual: true });
  });

  // Back from the billing tab: look straight away rather than waiting out the
  // poll. Both events fire on a tab switch in most browsers; the gap check
  // stops that becoming two calls.
  const recheckOnReturn = () => {
    if (state === 'exhausted' && !document.hidden
        && Date.now() - lastCheckAt > MIN_GAP_BETWEEN_CHECKS_MS) {
      checkCredits();
    }
  };
  window.addEventListener('focus', recheckOnReturn);
  document.addEventListener('visibilitychange', recheckOnReturn);

  checkCredits();
}
