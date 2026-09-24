/* Vetted Questions -- a per-user bank of screener-question answers the bot
   checks (exact match, then as LLM context) before answering from scratch.

   No add/create action here: rows only ever come from tools/seed_vetted_
   questions.py or the bot's own runtime hook, never a manual "add a vetted
   question" affordance. Editing the answer promotes the row to 'vetted'
   server-side (save_vetted_question), so there is no separate "vet this"
   step beyond picking a different answer -- the status control is only
   needed to demote a row back to 'unvetted', or to vet one without changing
   its answer. */

import { api, el, mount, setTopbar, toast, card, emptyState, confirmModal } from './core.js';

const TYPE_LABELS = {
  free_response: 'Free response',
  free_response_long: 'Free response (long)',
  mult_choice: 'Multiple choice',
  select_applicable: 'Select all that apply',
  drop_down: 'Dropdown',
  search_select: 'Searchable select',
  select_applicable_combobox: 'Select all that apply (dropdown)',
};

const NO_BANK_HINT = 'No answer choices on file for this question (likely seeded from history) '
  + '-- showing the stored answer as plain text. You can still edit it and mark it vetted.';

const state = { status: '', sort: 'default' };

/** One radio/checkbox choice row. */
function choiceRow(inputProps, label) {
  return el('label', { class: 'vq-choice' }, [el('input', inputProps), el('span', { text: label })]);
}

/** Type-aware editor for one vetted row's answer. Calls onChange(newAnswer)
 *  with the answer in the same shape the row already stores it in. */
function renderAnswerEditor(row, onChange) {
  const { question_type: type, answer, answer_bank: bank } = row;
  const isMultiSelect = type === 'select_applicable' || type === 'select_applicable_combobox';

  // Choice-based type with no bank on file: seeded from history (which never
  // recorded the offered options) or some other defensive gap. Degrade to a
  // free-text fallback rather than a picklist we cannot actually build.
  if (type !== 'free_response' && type !== 'free_response_long' && !bank) {
    const text = Array.isArray(answer) ? answer.join(', ') : (answer ?? '');
    return el('div', {}, [
      el('input', {
        class: 'input', type: 'text', value: text,
        onchange: (e) => onChange(isMultiSelect
          ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
          : e.target.value),
      }),
      el('span', { class: 'field__hint', text: NO_BANK_HINT }),
    ]);
  }

  if (type === 'free_response_long') {
    const node = el('textarea', { class: 'textarea', onchange: (e) => onChange(e.target.value) });
    node.value = answer ?? '';
    return node;
  }

  if (type === 'free_response') {
    return el('input', {
      class: 'input', type: 'text', value: answer ?? '',
      onchange: (e) => onChange(e.target.value),
    });
  }

  if (type === 'mult_choice' || type === 'search_select') {
    const name = `vq-${row.id}`;
    return el('div', { class: 'vq-choices' }, bank.map((choice) => choiceRow({
      type: 'radio', name, checked: answer === choice,
      onchange: () => onChange(choice),
    }, choice)));
  }

  if (isMultiSelect) {
    const current = new Set(Array.isArray(answer) ? answer : []);
    return el('div', { class: 'vq-choices' }, bank.map((choice) => choiceRow({
      type: 'checkbox', checked: current.has(choice),
      onchange: (e) => {
        if (e.target.checked) current.add(choice); else current.delete(choice);
        onChange(Array.from(current));
      },
    }, choice)));
  }

  if (type === 'drop_down') {
    // bank: array of arrays, one per linked select; answer: array of chosen
    // strings, index-aligned. Original per-select labels (Country/State) are
    // not captured, so groups are labeled positionally.
    const current = Array.isArray(answer) ? [...answer] : [];
    const groups = bank.map((options, index) => el('div', { class: 'vq-choices' }, [
      el('div', { class: 'field__hint', text: `Select ${index + 1}` }),
      ...options.map((choice) => choiceRow({
        type: 'radio', name: `vq-${row.id}-${index}`, checked: current[index] === choice,
        onchange: () => { current[index] = choice; onChange([...current]); },
      }, choice)),
    ]));
    return el('div', {}, groups);
  }

  // Shouldn't happen (DateFill never reaches this table), but fail visibly
  // rather than silently rendering nothing.
  return el('span', { class: 'field__hint', text: `Unrecognized question type: ${type}` });
}

export async function renderVettedQuestions(ctx) {
  const userId = ctx.state.userId;
  const params = new URLSearchParams();
  if (state.status) params.set('status', state.status);
  if (state.sort !== 'default') params.set('sort', state.sort);
  const rows = await api.get(`/api/users/${userId}/vetted-questions?${params}`);
  ctx.setCount('vetted', rows.length);

  setTopbar('Vetted Questions',
    `${rows.length} question(s) on file - checked before the bot asks the AI`,
    [], ctx.userLabel());

  const statusFilter = el('select', { class: 'select', style: 'width:auto', onchange: (e) => {
    state.status = e.target.value; ctx.go('vetted');
  } }, [
    el('option', { value: '', text: 'All statuses' }),
    el('option', { value: 'vetted', text: 'Vetted only' }),
    el('option', { value: 'unvetted', text: 'Unvetted only' }),
  ]);
  statusFilter.value = state.status;

  const sortSelect = el('select', { class: 'select', style: 'width:auto', onchange: (e) => {
    state.sort = e.target.value; ctx.go('vetted');
  } }, [
    el('option', { value: 'default', text: 'Default order' }),
    el('option', { value: 'alpha', text: 'Alphabetical' }),
    el('option', { value: 'date_asc', text: 'Date (oldest first)' }),
    el('option', { value: 'date_desc', text: 'Date (newest first)' }),
  ]);
  sortSelect.value = state.sort;

  const filterLabel = state.status === 'vetted' ? 'vetted' : state.status === 'unvetted' ? 'unvetted' : 'all';
  const clearAllBtn = el('button', {
    class: 'btn btn--sm btn--danger', text: `Delete ${filterLabel}`,
    disabled: !rows.length,
    onclick: async () => {
      const ok = await confirmModal({
        title: `Delete ${filterLabel} vetted questions?`,
        body: `This permanently deletes ${rows.length} question(s) for this user.`,
        confirmLabel: 'Delete',
        danger: true,
        requireText: 'DELETE',
      });
      if (!ok) return;
      const delParams = state.status ? `?status=${state.status}` : '';
      await api.del(`/api/users/${userId}/vetted-questions${delParams}`);
      toast('Deleted');
      ctx.go('vetted');
    },
  });

  const toolbar = el('div', { class: 'card' }, [
    el('div', { class: 'card__body' }, [
      el('div', { class: 'toolbar' }, [
        statusFilter, sortSelect, el('span', { class: 'toolbar__spacer' }), clearAllBtn,
      ]),
    ]),
  ]);

  if (!rows.length) {
    mount(el('div', {}, [toolbar, card('Vetted questions', null, [
      state.status
        ? emptyState('No vetted questions match this filter', 'Try switching the status filter back to "All statuses".')
        : emptyState('No vetted questions yet',
          'Run tools/seed_vetted_questions.py to populate this user\'s application history, '
          + 'or run the bot once to start collecting new questions automatically.'),
    ])]));
    return;
  }

  const saveStatus = async (id, status) => {
    try {
      await api.post(`/api/vetted-questions/${id}/status`, { status });
      toast(status === 'vetted' ? 'Marked vetted' : 'Marked unvetted');
      ctx.go('vetted');
    } catch (err) { toast(err.message, 'error'); }
  };

  const saveAnswer = async (id, answer) => {
    try {
      await api.put(`/api/vetted-questions/${id}`, { answer });
      toast('Saved and marked vetted');
      ctx.go('vetted');
    } catch (err) { toast(err.message, 'error'); }
  };

  const rowNodes = rows.map((row) => {
    const statusSelect = el('select', {
      class: 'select', onchange: (e) => saveStatus(row.id, e.target.value),
    }, [
      el('option', { value: 'unvetted', text: 'Unvetted' }),
      el('option', { value: 'vetted', text: 'Vetted' }),
    ]);
    statusSelect.value = row.status;

    return el('tr', {}, [
      el('td', { text: row.question_text, title: row.question_text, style: 'max-width:320px' }),
      el('td', {}, [el('span', {
        class: 'badge badge--muted', text: TYPE_LABELS[row.question_type] || row.question_type,
      })]),
      el('td', {}, [statusSelect]),
      el('td', {}, [renderAnswerEditor(row, (answer) => saveAnswer(row.id, answer))]),
      el('td', {}, [el('button', {
        class: 'btn btn--sm btn--ghost', text: 'Delete',
        onclick: async () => {
          const ok = await confirmModal({
            title: 'Delete this vetted question?',
            body: row.question_text,
            confirmLabel: 'Delete',
            danger: true,
          });
          if (!ok) return;
          await api.del(`/api/vetted-questions/${row.id}`);
          toast('Deleted');
          ctx.go('vetted');
        },
      })]),
    ]);
  });

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table table--static' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: 'Question' }),
        el('th', { text: 'Type' }),
        el('th', { text: 'Status' }),
        el('th', { text: 'Answer' }),
        el('th', { text: '' }),
      ])]),
      el('tbody', {}, rowNodes),
    ]),
  ]);

  mount(el('div', {}, [toolbar, card(
    'Vetted questions',
    'The bot checks this bank for an exact match before calling the AI, and always gives the AI '
    + 'the whole vetted list as context otherwise. Choosing a different answer marks a question vetted.',
    [table], [], true,
  )]));
}
