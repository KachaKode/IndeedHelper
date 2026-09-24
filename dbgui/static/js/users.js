/* Users list + Profile editor. */

import {
  api, el, mount, setTopbar, toast, confirmModal, card, field, fullField, emptyState,
} from './core.js';

export async function renderUsers(ctx) {
  const users = await api.get('/api/users');
  ctx.setCount('users', users.length);

  const addBtn = el('button', {
    class: 'btn btn--primary', text: 'Add user',
    onclick: async () => {
      const id = (await api.post('/api/users', {})).id;
      toast(`Created user #${id} (starts as Off)`);
      await ctx.selectUser(id);
      ctx.go('profile');
    },
  });
  setTopbar('Users', `${users.length} accounts`, [addBtn]);

  if (!users.length) {
    mount(card('Users', null, [emptyState('No users yet', 'Click "Add user" to create one.')]));
    return;
  }

  const rows = users.map((user) => {
    const active = String(user.Active || '').toUpperCase() === 'T';
    const tr = el('tr', {
      class: user.id === ctx.state.userId ? 'is-selected' : '',
      onclick: async () => { await ctx.selectUser(user.id); ctx.go('profile'); },
    }, [
      el('td', { class: 'table__num', text: user.id }),
      el('td', { text: `${user.FirstName || ''} ${user.LastName || ''}`.trim() || '(unnamed)' }),
      el('td', {}, [
        el('span', {
          class: `badge ${active ? 'badge--success' : 'badge--muted'}`,
          text: active ? 'Active' : 'Off',
        }),
      ]),
      el('td', { class: 'table__num', text: user.AppsLeft ?? 0 }),
      el('td', {}, [
        el('span', {
          class: `badge ${user._folderExists ? 'badge--muted' : 'badge--danger'}`,
          text: user._folderExists ? 'Folder OK' : 'Folder missing',
        }),
      ]),
      el('td', {}, [
        el('button', {
          class: 'btn btn--sm btn--ghost', text: 'Delete',
          onclick: async (e) => { e.stopPropagation(); await deleteUser(ctx, user); },
        }),
      ]),
    ]);
    return tr;
  });

  const table = el('div', { class: 'table-wrap' }, [
    el('table', { class: 'table' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: 'ID' }), el('th', { text: 'Name' }), el('th', { text: 'Status' }),
        el('th', { text: 'Apps left' }), el('th', { text: 'Bot folder' }), el('th', { text: '' }),
      ])]),
      el('tbody', {}, rows),
    ]),
  ]);

  mount(card('All users', 'Select a user to edit their profile, searches, and history.', [table], [], true));
}

async function deleteUser(ctx, user) {
  const orphans = await api.get(`/api/users/${user.id}/orphans`);
  const name = `${user.FirstName || ''} ${user.LastName || ''}`.trim() || `user ${user.id}`;
  const leftovers = Object.entries(orphans)
    .filter(([, n]) => n > 0)
    .map(([label, n]) => `${n} ${label}`)
    .join(', ');

  const ok = await confirmModal({
    title: `Delete ${name}?`,
    body: [
      el('p', { text: `This removes the users row for #${user.id}.` }),
      leftovers
        ? el('p', { style: 'margin-top:10px' }, [
            'These records are ', el('strong', { text: 'kept, not deleted' }), `: ${leftovers}. `,
            'Application history is a permanent record, so it is never cascaded.',
          ])
        : null,
    ],
    confirmLabel: 'Delete user',
    danger: true,
    requireText: name,
  });
  if (!ok) return;

  await api.del(`/api/users/${user.id}`);
  toast(`Deleted ${name}`);
  if (ctx.state.userId === user.id) await ctx.selectUser(null);
  ctx.go('users');
}

/* ------------------------------------------------------------------ profile */

export async function renderProfile(ctx) {
  const userId = ctx.state.userId;
  const user = await api.get(`/api/users/${userId}`);
  const issues = await api.get(`/api/users/${userId}/validate`);

  // Every control saves its own field on blur, matching Job Searches, Work
  // History and Education. There is no Save button and nothing to remember.
  const saveField = async (name, value) => {
    try {
      await api.put(`/api/users/${userId}`, { [name]: value });
      toast('Saved');
      // A name change moves the folder the bot writes to, so the checks panel
      // has to be re-read rather than left showing a stale result.
      if (name === 'FirstName' || name === 'LastName') {
        await ctx.refreshCounts();
        ctx.go('profile');
      }
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  const text = (name, extra = {}) => el('input', {
    class: 'input', type: 'text', value: user[name] ?? '',
    onchange: (e) => saveField(name, e.target.value), ...extra,
  });

  const area = (name, cls = '') => {
    const node = el('textarea', {
      class: `textarea ${cls}`.trim(),
      onchange: (e) => saveField(name, e.target.value),
    });
    node.value = user[name] ?? '';
    return node;
  };

  // Password: masked by default with an explicit reveal.
  const passInput = el('input', {
    class: 'input', type: 'password', value: user.IndeedPass ?? '',
    onchange: (e) => saveField('IndeedPass', e.target.value),
  });
  const revealBtn = el('button', {
    class: 'btn', text: 'Show',
    onclick: (e) => {
      e.preventDefault();
      const hidden = passInput.type === 'password';
      passInput.type = hidden ? 'text' : 'password';
      e.target.textContent = hidden ? 'Hide' : 'Show';
    },
  });

  const activeSelect = el('select', {
    class: 'select', onchange: (e) => saveField('Active', e.target.value),
  }, [
    el('option', { value: 'T', text: 'Active - bot will run this user' }),
    el('option', { value: 'F', text: 'Off' }),
  ]);
  activeSelect.value = String(user.Active || '').toUpperCase() === 'T' ? 'T' : 'F';

  const appsLeft = el('input', {
    class: 'input', type: 'number', min: '0', value: user.AppsLeft ?? 0,
    onchange: (e) => saveField('AppsLeft', e.target.value),
  });

  setTopbar(
    `${user.FirstName || ''} ${user.LastName || ''}`.trim() || `User ${userId}`,
    `User #${userId} - ${user._folderExists ? `Users/${user._folderName}` : 'bot folder missing'} - changes save as you go`,
    [],
  );

  const nodes = [];

  if (issues.length) {
    nodes.push(card(
      'Data checks',
      'Reported, never auto-corrected - changing these changes which jobs the bot applies to.',
      [el('div', { class: 'issues' }, issues.map((issue) => el('div', {
        class: `issue issue--${issue.severity}`,
      }, [
        el('span', { class: 'issue__where', text: issue.where }),
        el('span', { class: 'issue__msg', text: issue.message }),
        // Some issues carry a one-click fix; renaming the bot folder after a
        // name change is the only one so far.
        issue.action === 'renameFolder'
          ? el('button', {
              class: 'btn btn--sm', text: `Rename to "${issue.actionData.to}"`,
              onclick: async () => {
                try {
                  await api.post(`/api/users/${userId}/rename-folder`, issue.actionData);
                  toast('Folder renamed');
                  ctx.go('profile');
                } catch (err) { toast(err.message, 'error'); }
              },
            })
          : null,
      ])))],
    ));
  }

  nodes.push(card('Identity', 'Changing the name also changes the folder the bot writes to.', [
    el('div', { class: 'form-grid' }, [
      field('First name', text('FirstName')),
      field('Last name', text('LastName')),
      field('Phone number', text('PhoneNumber')),
      field('Email', text('email')),
      field('LinkedIn profile', text('LinkedInProfile'),
        'Used directly whenever a screener question asks for your LinkedIn profile.'),
      field('Street address', text('address')),
      field('City, State', text('areaSpec'), 'e.g. "Powder Springs, Ga"'),
      field('Country', text('country')),
      field('ZIP', text('zip')),
    ]),
  ]));

  nodes.push(card('Indeed account', null, [
    el('div', { class: 'form-grid' }, [
      field('Indeed email', text('IndeedEmail')),
      field('Indeed password', el('div', { class: 'input-group' }, [passInput, revealBtn])),
    ]),
  ]));

  nodes.push(card('Runtime', 'Controls how and whether the bot runs this user.', [
    el('div', { class: 'form-grid' }, [
      field('Status', activeSelect, 'Only "Active" is picked up by the bot.'),
      field('Applications left', appsLeft, 'Bot stops when this reaches 0.'),
      fullField('Chrome profile path', text('ProfilePath'),
        user.ProfilePath ? null : 'Empty - the bot needs a Chrome user-data directory.'),
      fullField('Home page URL pattern', text('homePagePattern'),
        'Regex used to recognise the search results tab.'),
    ]),
  ]));

  nodes.push(card('Employers to avoid', 'Checked against the scraped company name before any AI call is made for the job.', [
    el('div', { class: 'form-grid' }, [
      fullField('Avoid these employers', area('avoidEmployers'),
        'One employer name per line, exact match (case-insensitive) against the company '
        + 'name shown on the job listing. A match skips the job immediately, with no AI '
        + 'calls made at all.'),
    ]),
  ]));

  nodes.push(card('Content for generated applications', 'Used as source material when writing resumes and cover letters.', [
    el('div', { class: 'form-grid' }, [
      fullField('Position interests', area('PositionInterests'), 'One per line.'),
      fullField('Avoid these job characteristics', area('avoid'), 'One question per line; each is asked about the job description.'),
      fullField('Life summary', area('LifeSummary', 'textarea--tall'),
        'Projects, jobs and achievements. The cover letter and resume summary are '
        + 'built mainly from the skills you demonstrated here.'),
      fullField('Writing style sample', area('WritingSample', 'textarea--tall'),
        'A few paragraphs you actually wrote, in your own voice. Everything generated '
        + 'is matched to the sentence length, vocabulary and tone of this passage, so '
        + 'it reads like you rather than like a model. Anything is fine: an email, a '
        + 'post, a bit of a past cover letter.'),
    ]),
  ]));

  mount(el('div', {}, nodes));
}
