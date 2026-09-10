/* Shared plumbing: API client, DOM builder, toasts, modals, dirty-state.
   Everything user-supplied goes in via textContent / value -- never innerHTML --
   so resume text or job descriptions containing markup can't break the page. */

/* ------------------------------------------------------------------- API */

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const text = await res.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { error: text }; }
  }
  if (!res.ok) {
    throw new Error((payload && payload.error) || `${method} ${url} failed (${res.status})`);
  }
  return payload;
}

export const api = {
  get:  (url) => request('GET', url),
  post: (url, body) => request('POST', url, body),
  put:  (url, body) => request('PUT', url, body),
  del:  (url) => request('DELETE', url),
};

/* ------------------------------------------------------------------- DOM */

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;      // only for trusted literals
    else if (key === 'value') node.value = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, value);
    }
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

export function mount(node) {
  const root = document.getElementById('view-root');
  clear(root);
  root.append(node);
}

/** Scroll a freshly rendered node into view.
 *
 *  Views scroll inside `.content`, not the document, and re-rendering resets
 *  that scroll to the top. A detail pane appended below a 50-row table lands
 *  around 1600px below the fold, so clicking a row rendered the record
 *  perfectly and looked like it had done nothing at all.
 *
 *  Called after mount(), so it waits a frame for layout to settle. */
export function reveal(node) {
  if (!node) return;
  requestAnimationFrame(() => {
    try {
      node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      node.scrollIntoView(true);   // older engines take no options object
    }
  });
}

/** `userLabel` names whose data is on screen. Every user-scoped view passes it so
 *  it is always obvious which person you are editing. */
export function setTopbar(title, subtitle, actions = [], userLabel = null) {
  const titleHost = document.getElementById('view-title');
  clear(titleHost);
  titleHost.append(document.createTextNode(title));
  if (userLabel) {
    titleHost.append(el('span', { class: 'topbar__user', text: userLabel }));
  }
  document.getElementById('view-sub').textContent = subtitle || '';
  const host = document.getElementById('view-actions');
  clear(host);
  actions.filter(Boolean).forEach((a) => host.append(a));
}

/* ---------------------------------------------------------------- toasts */

export function toast(message, kind = 'success') {
  const host = document.getElementById('toasts');
  const node = el('div', { class: `toast toast--${kind}` }, [message]);
  host.append(node);
  setTimeout(() => {
    node.style.transition = 'opacity .2s ease';
    node.style.opacity = '0';
    setTimeout(() => node.remove(), 220);
  }, kind === 'error' ? 6000 : 2800);
}

/* ---------------------------------------------------------------- modals */

/** Promise<boolean>. When requireText is set the confirm button stays disabled
 *  until the user types that exact string -- used for destructive actions. */
export function confirmModal({ title, body, confirmLabel = 'Confirm', danger = false, requireText = null }) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    const confirmBtn = el('button', {
      class: `btn ${danger ? 'btn--danger' : 'btn--primary'}`,
      text: confirmLabel,
      disabled: requireText ? true : null,
    });

    const bodyNodes = Array.isArray(body) ? body : [body];
    if (requireText) {
      const input = el('input', {
        class: 'input',
        placeholder: requireText,
        oninput: (e) => { confirmBtn.disabled = e.target.value.trim() !== requireText; },
      });
      bodyNodes.push(el('div', { class: 'field', style: 'margin-top:16px' }, [
        el('label', { class: 'field__label', text: `Type "${requireText}" to confirm` }),
        input,
      ]));
      setTimeout(() => input.focus(), 30);
    }

    const close = (result) => { root.firstChild?.remove(); resolve(result); };
    confirmBtn.addEventListener('click', () => close(true));

    const backdrop = el('div', { class: 'modal-backdrop' }, [
      el('div', { class: 'modal' }, [
        el('div', { class: 'modal__header' }, [el('h2', { class: 'modal__title', text: title })]),
        el('div', { class: 'modal__body' }, bodyNodes),
        el('div', { class: 'modal__footer' }, [
          el('button', { class: 'btn', text: 'Cancel', onclick: () => close(false) }),
          confirmBtn,
        ]),
      ]),
    ]);
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(false); });
    clear(root);
    root.append(backdrop);
  });
}

/* --------------------------------------------------------------- helpers */

export function field(label, control, hint) {
  return el('div', { class: 'field' }, [
    el('label', { class: 'field__label', text: label }),
    control,
    hint ? el('span', { class: 'field__hint', text: hint }) : null,
  ]);
}

export function fullField(label, control, hint) {
  const node = field(label, control, hint);
  node.classList.add('field--full');
  return node;
}

export function card(title, hint, bodyChildren, headerActions = [], flush = false) {
  return el('div', { class: 'card' }, [
    el('div', { class: 'card__header' }, [
      el('div', {}, [
        el('h2', { class: 'card__title', text: title }),
        hint ? el('p', { class: 'card__hint', text: hint }) : null,
      ]),
      el('div', { class: 'toolbar' }, headerActions.filter(Boolean)),
    ]),
    el('div', { class: `card__body${flush ? ' card__body--flush' : ''}` }, bodyChildren),
  ]);
}

export function emptyState(title, hint) {
  return el('div', { class: 'empty' }, [
    el('div', { class: 'empty__title', text: title }),
    hint ? el('div', { class: 'empty__hint', text: hint }) : null,
  ]);
}

export function readonlyTag(text = 'Read only') {
  return el('span', { class: 'readonly-tag', text });
}
