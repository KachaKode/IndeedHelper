/* Rendering for one stored application record.

   The columns hold Python repr, not JSON -- `['a', 'b']`, `[{'title': ...}]` --
   so the server parses them with ast.literal_eval and hands us real arrays in
   `_parsed`. Anything it could not parse is absent from `_parsed`, and we fall
   back to showing the raw text rather than blanking the field.

   Nothing here uses innerHTML: application records contain job descriptions and
   cover letters written by other people. */

import { el } from './core.js';

/* Keys the bot writes for each work-history entry, in the order a resume reads.
   Several spellings exist across older rows (frmDate vs fromDate), so each
   field lists its aliases. */
const JOB_KEYS = {
  title:    ['title', 'jobTitle'],
  company:  ['comp', 'company', 'companyName'],
  kind:     ['compType'],
  place:    ['cityState', 'location'],
  from:     ['fromDate', 'frmDate', 'From'],
  to:       ['toDate', 'To'],
  current:  ['current', 'currentPosition'],
  country:  ['country'],
  desc:     ['desc', 'description', 'Description'],
};

const EDU_KEYS = {
  level:    ['educationLevel', 'level'],
  study:    ['fieldOfStudy'],
  school:   ['school', 'SchoolName'],
  place:    ['cityState', 'areaSpec'],
  from:     ['fromDate', 'frmDate', 'From'],
  to:       ['toDate', 'To'],
  current:  ['current', 'currentlyEnrolled'],
  country:  ['country'],
};

function pick(obj, names) {
  for (const name of names) {
    const v = obj[name];
    if (v !== undefined && v !== null && String(v).trim() !== '') return String(v).trim();
  }
  return '';
}

function isCurrent(value) {
  return /^(yes|true|y)$/i.test(value);
}

/** "October 2017 - May 2020", or "August 2023 - Present" when it is the current one. */
function dateRange(from, to, current) {
  const end = isCurrent(current) ? 'Present' : to;
  if (from && end) return `${from} – ${end}`;
  return from || end || '';
}

/** Descriptions arrive as newline-separated lines, most already bulleted. */
function bulletList(text) {
  const lines = String(text).split('\n')
    .map((l) => l.replace(/^\s*[-•*]\s*/, '').trim())
    .filter(Boolean);
  if (!lines.length) return null;
  return el('ul', { class: 'bullets' }, lines.map((l) => el('li', { text: l })));
}

/* --------------------------------------------------------------- sections */

function skillChips(skills) {
  return el('div', { class: 'chips' },
    skills.map((s) => el('span', { class: 'chip', text: String(s) })));
}

function jobEntries(jobs) {
  return el('div', { class: 'entries' }, jobs.map((job) => {
    const title = pick(job, JOB_KEYS.title);
    const company = pick(job, JOB_KEYS.company);
    const place = pick(job, JOB_KEYS.place);
    const kind = pick(job, JOB_KEYS.kind);
    const range = dateRange(pick(job, JOB_KEYS.from), pick(job, JOB_KEYS.to),
                            pick(job, JOB_KEYS.current));
    const desc = pick(job, JOB_KEYS.desc);

    return el('div', { class: 'entry' }, [
      el('div', { class: 'entry__head' }, [
        el('span', { class: 'entry__title', text: title || '(untitled role)' }),
        range ? el('span', { class: 'entry__dates', text: range }) : null,
      ]),
      el('div', { class: 'entry__meta', text: [company, place, kind].filter(Boolean).join(' · ') }),
      desc ? bulletList(desc) : null,
    ]);
  }));
}

function eduEntries(edus) {
  return el('div', { class: 'entries' }, edus.map((edu) => {
    const level = pick(edu, EDU_KEYS.level);
    const study = pick(edu, EDU_KEYS.study);
    const school = pick(edu, EDU_KEYS.school);
    const place = pick(edu, EDU_KEYS.place);
    const range = dateRange(pick(edu, EDU_KEYS.from), pick(edu, EDU_KEYS.to),
                            pick(edu, EDU_KEYS.current));
    const heading = study ? `${level} in ${study}` : level;

    return el('div', { class: 'entry' }, [
      el('div', { class: 'entry__head' }, [
        el('span', { class: 'entry__title', text: heading || '(no level recorded)' }),
        range ? el('span', { class: 'entry__dates', text: range }) : null,
      ]),
      el('div', { class: 'entry__meta', text: [school, place].filter(Boolean).join(' · ') }),
    ]);
  }));
}

function qaList(pairs) {
  return el('div', { class: 'qa' }, pairs.map((pair) => el('div', { class: 'qa__item' }, [
    el('div', { class: 'qa__q', text: pick(pair, ['Question', 'question', 'q']) }),
    el('div', { class: 'qa__a', text: pick(pair, ['Answer', 'answer', 'a']) || '(no answer recorded)' }),
  ])));
}

function textBlock(value) {
  return el('div', { class: 'detail-row__value', text: String(value) });
}

function section(label, body) {
  return el('div', { class: 'detail-row' }, [
    el('span', { class: 'detail-row__label', text: label }),
    body,
  ]);
}

/* Long fields in the order they make sense to read: who we said we were, then
   what we said, then what the employer asked, then the posting itself. */
const PLAIN_FIELDS = [
  ['headline', 'Headline'],
  ['resumeSummary', 'Resume summary'],
  ['cover_letter', 'Cover letter'],
  ['JobDescriptionText', 'Original job description'],
];

/** The body of one application record. Used inline in the table row. */
export function applicationBody(record) {
  const parsed = record._parsed || {};
  const nodes = [];

  const facts = [
    ['Date', record.DateTime],
    ['Platform', record.Platform],
    ['Applied as', record.fullName],
    ['Company', record.companyName],
    ['Job title', record.jobTitle],
    ['Job search', record.searchLabel],
  ].filter(([, v]) => String(v || '').trim());

  nodes.push(el('dl', { class: 'facts' }, facts.flatMap(([k, v]) => [
    el('dt', { text: k }),
    el('dd', { text: String(v) }),
  ])));

  if (String(record.headline || '').trim()) {
    nodes.push(section('Headline', el('div', { class: 'lede', text: record.headline })));
  }
  if (String(record.resumeSummary || '').trim()) {
    nodes.push(section('Resume summary', textBlock(record.resumeSummary)));
  }

  // Structured fields: real lists when the server could parse them, the stored
  // text when it could not, so a surprising value is visible rather than lost.
  if (Array.isArray(parsed.skills) && parsed.skills.length) {
    nodes.push(section(`Skills (${parsed.skills.length})`, skillChips(parsed.skills)));
  } else if (String(record.skills || '').trim()) {
    nodes.push(section('Skills', textBlock(record.skills)));
  }

  if (Array.isArray(parsed.jobHist) && parsed.jobHist.length) {
    nodes.push(section(`Work history used (${parsed.jobHist.length})`, jobEntries(parsed.jobHist)));
  } else if (String(record.jobHist || '').trim()) {
    nodes.push(section('Work history used', textBlock(record.jobHist)));
  }

  if (Array.isArray(parsed.eduHist) && parsed.eduHist.length) {
    nodes.push(section(`Education used (${parsed.eduHist.length})`, eduEntries(parsed.eduHist)));
  } else if (String(record.eduHist || '').trim()) {
    nodes.push(section('Education used', textBlock(record.eduHist)));
  }

  if (Array.isArray(parsed.QsAndAs) && parsed.QsAndAs.length) {
    nodes.push(section(`Screening questions (${parsed.QsAndAs.length})`, qaList(parsed.QsAndAs)));
  } else if (String(record.QsAndAs || '').trim() && String(record.QsAndAs).trim() !== '[]') {
    nodes.push(section('Screening questions', textBlock(record.QsAndAs)));
  }

  for (const [key, label] of PLAIN_FIELDS) {
    if (key === 'headline' || key === 'resumeSummary') continue;   // shown above
    if (String(record[key] || '').trim()) {
      nodes.push(section(label, textBlock(record[key])));
    }
  }

  return el('div', { class: 'detail-list app-detail' }, nodes);
}
