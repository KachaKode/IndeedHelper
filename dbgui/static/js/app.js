/* Shell: nav, view routing, and the shared context each view receives. */

import { api, toast, el, mount, setTopbar } from './core.js';
import { renderUsers, renderProfile } from './users.js';
import { renderSearches } from './searches.js';
import { renderJobs, renderEdu } from './history.js';
import { renderApplications, renderApplicationsOld } from './applications.js';
import { renderRun, stopPolling } from './run.js';
import { renderAdmin } from './admin.js';

const state = { view: 'run', userId: null, users: [] };

const VIEWS = {
  'run':              renderRun,
  'users':            renderUsers,
  'profile':          renderProfile,
  'searches':         renderSearches,
  'jobs':             renderJobs,
  'edu':              renderEdu,
  'applications':     renderApplications,
  'applications-old': renderApplicationsOld,
  'admin':            renderAdmin,
};

const NEEDS_USER = new Set(['profile', 'searches', 'jobs', 'edu']);

/** Display name of the user currently in context, or null if none is selected. */
function userLabel() {
  const user = state.users.find((u) => u.id === state.userId);
  if (!user) return null;
  return `${user.FirstName || ''} ${user.LastName || ''}`.trim() || `User ${user.id}`;
}

const ctx = {
  state,
  go,
  selectUser,
  setCount,
  refreshCounts,
  userLabel,
};

function setCount(key, value) {
  const node = document.getElementById(`count-${key}`);
  if (node) node.textContent = value === null || value === undefined ? '-' : String(value);
}

async function selectUser(userId) {
  state.userId = userId;
  syncNav();
  await refreshCounts();
}

async function refreshCounts() {
  try {
    state.users = await api.get('/api/users');
    setCount('users', state.users.length);
    if (state.userId != null) {
      const [searches, jobs, edu] = await Promise.all([
        api.get(`/api/users/${state.userId}/searches`),
        api.get(`/api/users/${state.userId}/jobs`),
        api.get(`/api/users/${state.userId}/edu`),
      ]);
      setCount('searches', searches.length);
      setCount('jobs', jobs.length);
      setCount('edu', edu.length);
    } else {
      ['searches', 'jobs', 'edu'].forEach((k) => setCount(k, null));
    }
  } catch (err) {
    toast(err.message, 'error');
  }
}

function syncNav() {
  document.querySelectorAll('.nav-item').forEach((btn) => {
    const view = btn.dataset.view;
    btn.classList.toggle('is-active', view === state.view);
    if (btn.hasAttribute('data-needs-user')) btn.disabled = state.userId == null;
  });
}

async function go(view) {
  if (NEEDS_USER.has(view) && state.userId == null) {
    toast('Select a user first', 'warning');
    view = 'users';
  }
  // Leaving the Run screen must cancel its status poll, or it keeps
  // re-rendering over whatever view replaced it.
  if (state.view === 'run' && view !== 'run') stopPolling();

  state.view = view;
  syncNav();
  try {
    await VIEWS[view](ctx);
  } catch (err) {
    console.error(err);
    setTopbar('Something went wrong', '');
    mount(el('div', { class: 'card' }, [
      el('div', { class: 'card__body' }, [
        el('p', { text: err.message }),
      ]),
    ]));
    toast(err.message, 'error');
  }
}

/* ---------------------------------------------------- credit-exhausted banner
   App-shell state, not view state: it has to stay visible no matter which
   nav item is active, so it lives outside VIEWS/go() entirely and just keeps
   polling in the background. A trivial real call costs a fraction of a cent,
   so this is deliberately infrequent -- the Admin tab itself gives an
   on-demand, always-fresh check for anyone who wants to know right now. */
const CREDIT_POLL_INTERVAL_MS = 10 * 60 * 1000;

async function checkCredits() {
  const banner = document.getElementById('credit-alert');
  const text = document.getElementById('credit-alert-text');
  if (!banner || !text) return;
  try {
    const probe = await api.get('/api/admin/probe');
    if (probe.exhausted) {
      text.textContent = `OpenAI credits are exhausted: ${probe.message || 'no credits remaining.'}`;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch {
    // A network hiccup checking this is not itself something to alarm about.
  }
}

function wireCreditAlert() {
  const goto = document.getElementById('credit-alert-goto');
  if (goto) {
    goto.addEventListener('click', () => {
      window.open('https://platform.openai.com/settings/organization/billing/overview', '_blank');
    });
  }
  checkCredits();
  setInterval(checkCredits, CREDIT_POLL_INTERVAL_MS);
}

function wireNav() {
  // Every view saves as you edit, so navigation never needs to guard anything.
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      go(btn.dataset.view);
    });
  });
}

async function boot() {
  wireNav();
  wireCreditAlert();
  await refreshCounts();

  // Preselect the active user so the app opens on something useful. Counts are
  // refreshed again afterwards, since the first pass ran before a user existed.
  const active = state.users.find((u) => String(u.Active || '').toUpperCase() === 'T');
  if (active) {
    state.userId = active.id;
    await refreshCounts();
  }

  try {
    const apps = await api.get('/api/applications?page=1');
    setCount('apps', apps.total);
    const old = await api.get('/api/applications-old');
    setCount('apps-old', old.length);
    const status = await api.get('/api/run/status');
    setCount('running', status.runs.filter((r) => r.alive).length || null);
  } catch { /* counts are cosmetic; the views report real errors */ }

  syncNav();
  await go('run');
}

boot();
