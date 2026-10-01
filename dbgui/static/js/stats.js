/* Stats: the application funnel and what predicts it, computed on demand.
 *
 * Two things on this page are deliberate and must not be "tidied away", because
 * they are the difference between a useful tool and a flattering one:
 *
 *   1. The maturity window is stated in plain text at the top, along with how
 *      many applications it held back. Every rate below is over mature
 *      applications only. Hiding that would let a burst of recent applications
 *      silently halve every percentage on the page.
 *
 *   2. A cell whose sample is too small shows its COUNT, never a percentage, and
 *      every rate that is shown carries its 95% confidence interval. At a few
 *      percent response rate, a ten-way split leaves single digits per bucket,
 *      where noise is indistinguishable from insight.
 *
 * No chart library: the bars are the same hand-rolled flexbox idiom admin.js
 * already uses for spend. The app is served from 127.0.0.1 inside a pywebview
 * window with no network guarantee, so a CDN is not an option.
 */

import { api, el, mount, setTopbar, toast, card, emptyState } from './core.js';

// Persist across visits so returning to the page keeps your framing.
const state = {
  maturity: null,   // null = use the server default
  minN: null,
  since: '',
};

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const int = (value) => Number(value || 0).toLocaleString();

function statTile(value, label, sub, muted = false) {
  return el('div', { class: 'stat' }, [
    el('div', { class: `stat__value${muted ? ' stat__value--muted' : ''}`, text: value }),
    el('div', { class: 'stat__label', text: label }),
    sub ? el('div', { class: 'stat__sub', text: sub }) : null,
  ]);
}

/** A bar per point. `format` renders the hover title. */
function barChart(series, format) {
  if (!series.length) return el('p', { class: 'muted', text: 'No applications in this range.' });
  const max = Math.max(1, ...series.map((d) => d.count));
  return el('div', {}, [
    el('div', { class: 'bar-chart' }, series.map((d) => el('div', {
      class: `bar-chart__bar${d.count ? '' : ' bar-chart__bar--empty'}`,
      style: `height:${Math.max(2, Math.round((d.count / max) * 94))}px`,
      title: format(d),
    }))),
    el('div', { class: 'bar-chart-axis' }, [
      el('span', { text: series[0].label }),
      el('span', { text: `peak ${int(max)}` }),
      el('span', { text: series[series.length - 1].label }),
    ]),
  ]);
}

function funnel(data) {
  const top = data.applied || 1;
  const rows = [
    { label: 'Applied', count: data.applied, note: '' },
    ...data.stages.map((s) => ({
      label: s.label,
      count: s.count,
      note: s.count ? `${pct(s.ofApplied)} of applied` : '',
    })),
  ];
  return el('div', { class: 'funnel' }, rows.map((row) => el('div', { class: 'funnel__row' }, [
    el('div', { class: 'funnel__label', text: row.label }),
    el('div', { class: 'funnel__track' }, [
      el('div', {
        class: `funnel__fill${row.count ? '' : ' funnel__fill--zero'}`,
        style: `width:${Math.max(0, (row.count / top) * 100)}%`,
      }),
    ]),
    el('div', { class: 'funnel__count', text: row.note ? `${int(row.count)} · ${row.note}` : int(row.count) }),
  ])));
}

/**
 * One dimension as a table. `scale` is the largest rate in this table, so the
 * interval bars are readable: scaling to 100% would flatten single-digit rates
 * into nothing.
 */
function dimensionTable(rows, minN) {
  if (!rows.length) return emptyState('Nothing to group', 'No mature applications in this range.');
  const scale = Math.max(0.01, ...rows.filter((r) => r.enough).map((r) => r.ciHigh));

  const body = rows.map((row) => {
    let rateCell;
    if (!row.enough) {
      // Too few to rate. Show what we actually know: the raw counts.
      rateCell = el('div', { class: 'rate rate--thin' }, [
        el('span', { class: 'rate__pct', text: `${row.responded}/${row.n}` }),
        el('span', { class: 'muted', text: `needs ${minN}` }),
      ]);
    } else {
      const left = Math.min(100, (row.ciLow / scale) * 100);
      const width = Math.max(1, ((row.ciHigh - row.ciLow) / scale) * 100);
      rateCell = el('div', { class: 'rate' }, [
        el('span', { class: 'rate__pct', text: pct(row.rate) }),
        el('span', {
          class: 'rate__track',
          title: `95% confidence: ${pct(row.ciLow)} to ${pct(row.ciHigh)} (${row.responded} of ${row.n})`,
        }, [
          el('span', { class: 'rate__ci', style: `left:${left}%;width:${width}%` }),
          el('span', { class: 'rate__dot', style: `left:${Math.min(99, (row.rate / scale) * 100)}%` }),
        ]),
      ]);
    }

    return el('tr', {}, [
      el('td', { class: 'table__truncate', title: row.label, text: row.label }),
      el('td', { class: 'table__num', text: int(row.n) }),
      el('td', {}, [rateCell]),
      el('td', { class: 'table__num', text: row.interviewed ? int(row.interviewed) : '-' }),
    ]);
  });

  return el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table table--static' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: 'Group' }),
        el('th', { class: 'table__num', text: 'Applied' }),
        el('th', { text: 'Response rate (95% CI)' }),
        el('th', { class: 'table__num', text: 'Interviews' }),
      ])]),
      el('tbody', {}, body),
    ]),
  ]);
}

function dimensionCard(title, hint, rows, minN, coverage) {
  const actions = coverage === undefined ? [] : [
    el('span', { class: 'coverage-tag', text: `${pct(coverage)} of rows classified` }),
  ];
  return card(title, hint, [dimensionTable(rows, minN)], actions, true);
}

function controls(ctx, meta) {
  const maturityInput = el('input', {
    class: 'input', type: 'number', min: '0', step: '1',
    style: 'max-width:90px',
    value: String(meta.maturityDays),
  });
  const minNInput = el('input', {
    class: 'input', type: 'number', min: '1', step: '1',
    style: 'max-width:90px',
    value: String(meta.minN),
  });
  const sinceInput = el('input', {
    class: 'input', type: 'text', placeholder: 'YYYY-MM-DD',
    style: 'max-width:130px',
    value: state.since,
  });

  const apply = el('button', {
    class: 'btn btn--sm btn--primary', text: 'Apply',
    onclick: () => {
      state.maturity = parseInt(maturityInput.value, 10);
      state.minN = parseInt(minNInput.value, 10);
      state.since = (sinceInput.value || '').trim();
      ctx.go('stats');
    },
  });

  return el('div', { class: 'toolbar' }, [
    el('span', { class: 'muted', text: 'Mature after' }), maturityInput,
    el('span', { class: 'muted', text: 'days · min sample' }), minNInput,
    el('span', { class: 'muted', text: '· from' }), sinceInput,
    apply,
  ]);
}

export async function renderStats(ctx) {
  const userId = ctx.state.userId;
  setTopbar('Stats', 'Computed fresh on every load, never stored.', [], ctx.userLabel());
  // A cold load derives dimensions for every application, so say something first.
  mount(el('div', { class: 'muted', text: 'Computing...' }));

  const params = new URLSearchParams();
  if (state.maturity !== null && !Number.isNaN(state.maturity)) params.set('maturity', state.maturity);
  if (state.minN !== null && !Number.isNaN(state.minN)) params.set('minN', state.minN);
  if (state.since) params.set('since', state.since);

  let data;
  try {
    data = await api.get(`/api/users/${userId}/stats?${params}`);
  } catch (err) {
    toast(err.message, 'error');
    mount(card('Stats unavailable', null, [
      el('p', { class: 'muted', text: err.message }),
    ]));
    return;
  }

  const { meta, funnel: f, timing, pipeline, volume, coverage } = data;

  if (!meta.totalApplications) {
    mount(el('div', {}, [
      controls(ctx, meta),
      card('No applications', null, [emptyState(
        'Nothing to measure yet',
        'This user has no applications in the selected range.')]),
    ]));
    return;
  }

  // Stated, not buried: every rate below excludes these.
  const note = el('div', { class: 'stats-note' }, [
    el('strong', { text: `${int(meta.mature)} of ${int(meta.totalApplications)} applications` }),
    ` are old enough to judge (${meta.maturityDays}+ days). The other `,
    el('strong', { text: int(meta.excludedTooRecent) }),
    ' are excluded from every rate below — too recent to call a non-response a rejection. ',
    meta.eventCount
      ? `${int(meta.eventCount)} outcome events recorded.`
      : 'No outcome events recorded yet, so every stage past "Applied" reads zero — that is missing data, not a 0% response rate.',
    // Without this, recording a reply on a recent application looks like it did
    // nothing at all.
    meta.excludedWithOutcome
      ? el('span', {}, [
        ' ',
        el('strong', { text: int(meta.excludedWithOutcome) }),
        ` of the excluded already have a recorded response — they start counting once they pass ${meta.maturityDays} days. `
        + 'Counting them now while recent non-responses stay out would bias the rate upward.',
      ])
      : null,
  ]);

  const headline = el('div', { class: 'stat-grid' }, [
    statTile(int(meta.totalApplications), 'Applications', `${int(volume.uniqueCompanies)} companies`),
    meta.eventCount
      ? statTile(pct(f.responseRate), 'Response rate',
                 `95% CI ${pct(f.responseCiLow)}–${pct(f.responseCiHigh)}`)
      : statTile('—', 'Response rate', 'needs outcome data', true),
    meta.eventCount
      ? statTile(int(f.stages.find((s) => s.key === 'interviewed')?.count || 0), 'Interviews',
                 `${int(f.stages.find((s) => s.key === 'offer')?.count || 0)} offers`)
      : statTile('—', 'Interviews', 'needs outcome data', true),
    timing.response.n
      ? statTile(`${timing.response.median.toFixed(1)}d`, 'Median time to response',
                 `p90 ${timing.response.p90.toFixed(1)}d · n=${timing.response.n}`)
      : statTile('—', 'Median time to response', 'needs outcome data', true),
    statTile(int(pipeline.awaitingResponse), 'Awaiting response',
             `${int(pipeline.open)} still open`),
    statTile(int(volume.repeatApplications), 'Repeat companies',
             'applied more than once'),
  ]);

  const funnelHint = meta.eventCount
    ? 'Acknowledgements and "viewed" are shown but do NOT count as a response — a real response starts at "Real response".'
    : 'Stages past "Applied" fill in once outcome capture is running. Acknowledgements and "viewed" will never count as a response.';

  const funnelCard = card('Funnel', funnelHint, [
    funnel(f),
    // With no events recorded, "ghosted" would read 100% -- which is not a
    // finding, it is the absence of one. Show nothing rather than a number that
    // invites being believed.
    el('div', { class: 'stat-grid', style: 'margin-top:var(--sp-4)' }, meta.eventCount ? [
      statTile(int(f.ghosted), 'No reply at all', f.applied ? pct(f.ghostRate) : ''),
      statTile(int(f.rejected), 'Explicit rejections', ''),
      statTile(int(f.withdrawn), 'Withdrawn', ''),
    ] : [
      statTile('—', 'No reply at all', 'needs outcome data', true),
      statTile('—', 'Explicit rejections', 'needs outcome data', true),
      statTile('—', 'Withdrawn', 'needs outcome data', true),
    ]),
  ]);

  const pipelineCard = card('Open pipeline', 'Applications with no rejection, withdrawal or offer yet, by age.', [
    el('div', { class: 'table-wrap' }, [
      el('table', { class: 'table table--static' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'Age' }), el('th', { class: 'table__num', text: 'Open' }),
        ])]),
        el('tbody', {}, pipeline.byAge.map((b) => el('tr', {}, [
          el('td', { text: b.label }),
          el('td', { class: 'table__num', text: int(b.count) }),
        ]))),
      ]),
    ]),
  ], [], true);

  const volumeCard = card('Applications over time', 'One bar per month.', [
    barChart(volume.byMonth, (d) => `${d.label}: ${d.count} applications`),
  ]);

  mount(el('div', {}, [
    controls(ctx, meta),
    note,
    headline,
    el('div', { style: 'height:var(--sp-4)' }),
    funnelCard,
    el('div', { class: 'stats-grid' }, [
      volumeCard,
      pipelineCard,
    ]),
    dimensionCard('By job search', 'Which search produced the application.',
                  data.bySearch, meta.minN, coverage.searchAttributed),
    el('div', { class: 'stats-grid' }, [
      dimensionCard('By salary band', 'Annualised from the pay quoted in the description.',
                    data.bySalaryBand, meta.minN, coverage.salaryBand),
      dimensionCard('By job type', null, data.byEmploymentType, meta.minN, coverage.employmentType),
      dimensionCard('By job title', 'Titles normalised and grouped.', data.byTitle, meta.minN),
      dimensionCard('By employer', 'Most-applied-to companies.', data.byCompany, meta.minN),
      dimensionCard('By screener questions', 'How many questions the application asked.',
                    data.byQuestionCount, meta.minN),
      dimensionCard('By cover letter length', null, data.byCoverLetter, meta.minN),
      dimensionCard('By weekday applied', null, data.byWeekday, meta.minN),
      dimensionCard('By work mode',
                    'Weak dimension: the searches already filter for remote, so there is little variation to explain.',
                    data.byWorkMode, meta.minN, coverage.workMode),
    ]),
  ]));
}
