/* Shell: nav, view routing, and the shared context each view receives. */

import { api, toast, el, mount, setTopbar } from './core.js';
import { renderUsers, renderProfile } from './users.js';
import { renderSearches, stopSearchesPolling } from './searches.js';
import { renderJobs, renderEdu } from './history.js';
import { renderVettedQuestions } from './vetted.js';
import { renderKeywords } from './keywords.js';
import { renderApplications, renderApplicationsOld } from './applications.js';
import { renderRun, stopPolling } from './run.js';
import { renderAdmin } from './admin.js';
import { wireCreditAlert } from './credits.js';
import { renderStats } from './stats.js';
import { renderOutcomes } from './outcomes.js';

const state = { view: 'run', userId: null, users: [] };

const VIEWS = {
  'run':              renderRun,
  'users':            renderUsers,
  'profile':          renderProfile,
  'searches':         renderSearches,
  'jobs':             renderJobs,
  'edu':              renderEdu,
  'vetted':           renderVettedQuestions,
  'keywords':         renderKeywords,
  'applications':     renderApplications,
  'applications-old': renderApplicationsOld,
  'admin':            renderAdmin,
  'stats':            renderStats,
  'outcomes':         renderOutcomes,
};

const NEEDS_USER = new Set(['profile', 'searches', 'jobs', 'edu', 'vetted', 'keywords', 'stats', 'outcomes']);

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
      const [searches, jobs, edu, vetted, keywordInfo] = await Promise.all([
        api.get(`/api/users/${state.userId}/searches`),
        api.get(`/api/users/${state.userId}/jobs`),
        api.get(`/api/users/${state.userId}/edu`),
        api.get(`/api/users/${state.userId}/vetted-questions`),
        api.get(`/api/users/${state.userId}/keyword-info`),
      ]);
      // Alternate-URL sub-rows (parent_id set) are not separate searches --
      // count only main rows, matching what the Job Searches view itself counts.
      setCount('searches', searches.filter((s) => s.parent_id == null).length);
      setCount('jobs', jobs.length);
      setCount('edu', edu.length);
      setCount('vetted', vetted.length);
      setCount('keywords', keywordInfo.length);
    } else {
      ['searches', 'jobs', 'edu', 'vetted', 'keywords'].forEach((k) => setCount(k, null));
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
  // Same idea for the Searches page's "this session" count poll.
  if (state.view === 'searches' && view !== 'searches') stopSearchesPolling();

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

/* The credit banner lives in credits.js. A recorded top-up changes what the
   Admin tab shows, so redraw it if that is the tab on screen. */
function wireBanner() {
  wireCreditAlert({ onChange: () => { if (state.view === 'admin') go('admin'); } });
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
  wireBanner();
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
