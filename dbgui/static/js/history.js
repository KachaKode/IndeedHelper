/* Work History (Job) and Education (Edu) editors.

   Both tables lack a primary key and Job actually contains duplicate
   (userID, jobNum) pairs, so every row is addressed by its SQLite rowid --
   never by jobNum -- which the API exposes as _rowid. */

import { api, el, mount, setTopbar, toast, card, field, fullField, emptyState, confirmModal } from './core.js';

const YES_NO = [['Yes', 'Yes'], ['No', 'No']];

function selectControl(value, options, onchange) {
  const node = el('select', { class: 'select', onchange }, options.map(([label, val]) =>
    el('option', { value: val, text: label })));
  node.value = value ?? '';
  if (node.selectedIndex === -1) node.selectedIndex = options.length - 1;
  return node;
}

/** Shared renderer for the two structurally-similar history tables. */
async function renderRecords(ctx, config) {
  const userId = ctx.state.userId;
  const records = await api.get(`/api/users/${userId}/${config.path}`);
  ctx.setCount(config.countKey, records.length);

  const addBtn = el('button', {
    class: 'btn btn--primary', text: config.addLabel,
    onclick: async () => {
      await api.post(`/api/users/${userId}/${config.path}`, {});
      toast(`${config.noun} added`);
      ctx.go(config.view);
    },
  });
  setTopbar(config.title,
            `${records.length} ${records.length === 1 ? config.noun.toLowerCase() : config.pluralNoun}`,
            [addBtn], ctx.userLabel());

  if (!records.length) {
    mount(card(config.title, null, [emptyState(`No ${config.pluralNoun} yet`, `Click "${config.addLabel}" to add one.`)]));
    return;
  }

  const save = async (rowid, key, value) => {
    try {
      await api.put(`/api/${config.path}/${rowid}`, { [key]: value });
      toast('Saved');
    } catch (err) { toast(err.message, 'error'); }
  };

  const cards = records.map((record) => {
    const rowid = record._rowid;
    const text = (name, extra = {}) => el('input', {
      class: 'input', type: 'text', value: record[name] ?? '',
      onchange: (e) => save(rowid, name, e.target.value), ...extra,
    });

    const deleteBtn = el('button', {
      class: 'btn btn--sm btn--ghost', text: 'Delete',
      onclick: async () => {
        const ok = await confirmModal({
          title: `Delete this ${config.noun.toLowerCase()}?`,
          body: config.describe(record) || 'This record will be removed.',
          confirmLabel: 'Delete',
          danger: true,
        });
        if (!ok) return;
        await api.del(`/api/${config.path}/${rowid}`);
        toast(`${config.noun} deleted`);
        ctx.go(config.view);
      },
    });

    return card(
      config.describe(record) || `${config.noun} #${record[config.numField]}`,
      `${config.numField} ${record[config.numField]} - referenced by that number in Job Searches`,
      [el('div', { class: 'form-grid' }, config.fields(record, text, save, rowid))],
      [deleteBtn],
    );
  });

  mount(el('div', {}, cards));
}

export function renderJobs(ctx) {
  return renderRecords(ctx, {
    path: 'jobs',
    view: 'jobs',
    countKey: 'jobs',
    title: 'Work History',
    noun: 'Job',
    pluralNoun: 'jobs',
    addLabel: 'Add job',
    numField: 'jobNum',
    describe: (r) => [r.JobTitle, r.CompanyName].filter(Boolean).join(' - '),
    fields: (record, text, save, rowid) => [
      field('Job number', text('jobNum'), 'How Job Searches refer to this record.'),
      field('Job title', text('JobTitle')),
      field('Company name', text('CompanyName')),
      field('Company type', text('CompanyType')),
      field('City, State', text('areaSpec')),
      field('Country', text('country')),
      field('Current position', selectControl(record.currentPosition, YES_NO,
        (e) => save(rowid, 'currentPosition', e.target.value))),
      field('From', text('From'), 'e.g. "January 2024"'),
      field('To', text('To'), 'Leave blank if this is the current job.'),
      fullField('Description', (() => {
        const node = el('textarea', {
          class: 'textarea textarea--tall',
          onchange: (e) => save(rowid, 'Description', e.target.value),
        });
        node.value = record.Description ?? '';
        return node;
      })(), 'Bullet points describing the role; used as source material for generated resumes.'),
    ],
  });
}

export function renderEdu(ctx) {
  return renderRecords(ctx, {
    path: 'edu',
    view: 'edu',
    countKey: 'edu',
    title: 'Education',
    noun: 'Education record',
    pluralNoun: 'education records',
    addLabel: 'Add education',
    numField: 'eduNum',
    describe: (r) => [r.level, r.SchoolName].filter(Boolean).join(' - '),
    fields: (record, text, save, rowid) => [
      field('Education number', text('eduNum'), 'How Job Searches refer to this record.'),
      field('Level', text('level'), 'e.g. "Bachelor\'s Degree"'),
      field('Field of study', text('fieldOfStudy')),
      field('School name', text('SchoolName')),
      field('City, State', text('areaSpec')),
      field('Country', text('country')),
      field('Currently enrolled', selectControl(record.currentlyEnrolled, YES_NO,
        (e) => save(rowid, 'currentlyEnrolled', e.target.value))),
      field('From', text('From')),
      field('To', text('To')),
    ],
  });
}
