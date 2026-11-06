/* Keyword Based Information.

   Each entry is one piece of information plus the keywords that trigger it.
   When ANY of an entry's keywords appears in a job description, the bot adds
   that information to what it tells the model while writing the cover letter,
   work history, summary, headline, skills and screener answers.

   Entries are created blank and every control saves as you edit, like Work
   History. A blank entry has no keywords, so it can never match anything. */

import { api, el, mount, setTopbar, toast, card, fullField, emptyState, confirmModal, reveal } from './core.js';

/** Split pasted or typed text on commas into trimmed, non-empty keywords. */
function splitKeywords(text) {
  return String(text).split(',').map((part) => part.trim().replace(/\s+/g, ' ')).filter(Boolean);
}

/** The chip row plus its add box. `onChange(words)` fires after every change. */
function keywordEditor(initial, onChange) {
  let words = [...initial];
  const chips = el('div', { class: 'kw-chips' });
  const input = el('input', {
    class: 'input kw-add__input', type: 'text',
    placeholder: 'Type a keyword and press Enter, or paste a comma separated list',
  });

  const redraw = () => {
    chips.replaceChildren(...words.map((word, index) => el('span', { class: 'kw-chip' }, [
      el('span', { class: 'kw-chip__text', text: word }),
      el('button', {
        class: 'kw-chip__remove', type: 'button', title: `Remove "${word}"`,
        'aria-label': `Remove ${word}`, text: '×',
        onclick: () => {
          words.splice(index, 1);
          redraw();
          onChange(words);
        },
      }),
    ])));
  };

  const add = (candidates) => {
    let changed = false;
    for (const candidate of candidates) {
      if (words.some((w) => w.toLowerCase() === candidate.toLowerCase())) continue;
      words.push(candidate);
      changed = true;
    }
    if (changed) {
      redraw();
      onChange(words);
    }
  };

  const commit = () => {
    const candidates = splitKeywords(input.value);
    input.value = '';
    add(candidates);
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
  });
  // Typing or pasting a comma turns everything before it into chips at once.
  input.addEventListener('input', () => {
    if (!input.value.includes(',')) return;
    const parts = input.value.split(',');
    const rest = parts.pop();
    input.value = rest.trimStart();
    add(parts.map((p) => p.trim().replace(/\s+/g, ' ')).filter(Boolean));
  });

  redraw();
  const node = el('div', { class: 'kw-editor' }, [
    chips,
    el('div', { class: 'kw-add' }, [
      input,
      el('button', { class: 'btn btn--sm', type: 'button', text: 'Add keyword', onclick: commit }),
    ]),
  ]);
  return { node, input };
}

function statusText(words, info) {
  if (!words.length) return 'Add at least one keyword: this entry is never used until you do.';
  if (!info.trim()) return 'Add the information to pass along: an entry with no text is never used.';
  return 'Used whenever the job description contains any one of these keywords.';
}

function titleFor(words) {
  if (!words.length) return 'New entry (no keywords yet)';
  const shown = words.slice(0, 4).join(', ');
  return words.length > 4 ? `${shown} +${words.length - 4} more` : shown;
}

export async function renderKeywords(ctx, options = {}) {
  const userId = ctx.state.userId;
  const entries = await api.get(`/api/users/${userId}/keyword-info`);
  ctx.setCount('keywords', entries.length);

  const addBtn = el('button', {
    class: 'btn btn--primary', text: 'Add keyword info',
    onclick: async () => {
      try {
        const created = await api.post(`/api/users/${userId}/keyword-info`, {});
        await renderKeywords(ctx, { focusId: created.id });
      } catch (err) { toast(err.message, 'error'); }
    },
  });
  setTopbar('Keyword Based Information',
            `${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}`,
            [addBtn], ctx.userLabel());

  if (!entries.length) {
    mount(card('Keyword Based Information',
               'Information to pass to the writer whenever a keyword shows up in a job description.',
               [emptyState('No entries yet', 'Click "Add keyword info" to add one.')]));
    return;
  }

  let focusInput = null;
  let focusCard = null;

  const cards = entries.map((entry) => {
    let words = [...entry.keywords];
    let info = entry.info || '';

    const status = el('span', { class: 'field__hint', text: statusText(words, info) });
    let cardNode = null;

    const save = async (fields) => {
      try {
        await api.put(`/api/keyword-info/${entry.id}`, fields);
        toast('Saved');
      } catch (err) { toast(err.message, 'error'); }
    };

    const editor = keywordEditor(words, (next) => {
      words = [...next];
      status.textContent = statusText(words, info);
      const title = cardNode && cardNode.querySelector('.card__title');
      if (title) title.textContent = titleFor(words);
      save({ keywords: words });
    });

    const infoBox = el('textarea', {
      class: 'textarea textarea--tall',
      placeholder: 'What the writer should know when one of these keywords is in the job description.',
      onchange: (e) => {
        info = e.target.value;
        status.textContent = statusText(words, info);
        save({ info });
      },
    });
    infoBox.value = info;

    const deleteBtn = el('button', {
      class: 'btn btn--sm btn--ghost', text: 'Delete',
      onclick: async () => {
        const ok = await confirmModal({
          title: 'Delete this entry?',
          body: words.length ? `Keywords: ${words.join(', ')}` : 'This entry will be removed.',
          confirmLabel: 'Delete',
          danger: true,
        });
        if (!ok) return;
        try {
          await api.del(`/api/keyword-info/${entry.id}`);
          toast('Entry deleted');
          await renderKeywords(ctx);
        } catch (err) { toast(err.message, 'error'); }
      },
    });

    cardNode = card(titleFor(words), null, [
      el('div', { class: 'form-grid' }, [
        fullField('Keywords', editor.node, 'Matching ignores case and needs the whole word or phrase, '
          + 'so "Java" does not match "JavaScript". Add both forms if you want both.'),
        fullField('Information', infoBox),
      ]),
      status,
    ], [deleteBtn]);

    if (entry.id === options.focusId) {
      focusInput = editor.input;
      focusCard = cardNode;
    }
    return cardNode;
  });

  mount(el('div', {}, cards));
  if (focusCard) {
    reveal(focusCard);
    setTimeout(() => focusInput && focusInput.focus(), 60);
  }
}
