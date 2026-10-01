/* Shared "what's different" URL comparison, used by both the Job Searches tab
   (searches.js: alternate-URL sub-rows, and reapplying a variation onto a
   different search) and the Applications history detail view (appdetail.js:
   showing which variant, if any, produced a past application).

   Purely a display/derivation helper -- computed client-side from two URLs
   already on screen or already fetched, never itself stored, never read by
   the bot. Wrong or missing here costs nothing beyond a less helpful hint,
   which is why a best-effort decode of Indeed's packed `sc=` filter blob is
   worth attempting even though its exact format isn't documented anywhere
   official. */

export const URL_PARAM_LABELS = {
  q: 'Keywords', l: 'Location', radius: 'Radius (mi)', fromage: 'Posted within (days)',
  jt: 'Job type', explvl: 'Experience level', sort: 'Sort', salary: 'Salary',
  remotejob: 'Remote filter',
};

// Pagination/session noise, not a meaningful search variant -- a URL copied
// mid-pagination would otherwise show a bogus "Page start" diff every time.
export const URL_PARAM_IGNORE = new Set(['start', 'vjk', 'advn']);

/** Indeed packs several filters (salary, job type, remote, experience level, ...)
 *  into one opaque `sc=0kf:key(value)key2(value2);` blob rather than separate
 *  query params. Splits it into raw "key(value)" chunks for a best-effort diff --
 *  never claims to know what an unrecognized key means, just surfaces it. */
export function splitFilterBlob(raw) {
  if (!raw) return [];
  let text = raw;
  try { text = decodeURIComponent(raw.replace(/\+/g, ' ')); } catch { /* use as-is */ }
  const parts = [];
  const re = /([A-Za-z_]+)\(([^)]*)\)/g;
  let m;
  while ((m = re.exec(text))) parts.push(`${m[1]}(${m[2]})`);
  return parts;
}

export function humanizeFilterPart(part) {
  const m = /^([A-Za-z_]+)\(([^)]*)\)$/.exec(part);
  if (!m) return part;
  return `${m[1]}: ${m[2].replace(/_/g, ' ').toLowerCase()}`;
}

/** Every query-string key that differs between two URLSearchParams, skipping
 *  URL_PARAM_IGNORE. subVal/parentVal are null (not '') when the key is
 *  absent on that side -- callers that need to distinguish "removed" from
 *  "set to empty string" (applyUrlDiff) depend on that distinction. */
export function diffParams(subParams, parentParams) {
  const keys = new Set([...subParams.keys(), ...parentParams.keys()]);
  const changes = [];
  for (const key of keys) {
    if (URL_PARAM_IGNORE.has(key)) continue;
    const subVal = subParams.get(key);
    const parentVal = parentParams.get(key);
    if (subVal === parentVal) continue;
    changes.push({ key, subVal, parentVal });
  }
  return changes;
}

/** @returns string[] of human-readable diffs, [] if no meaningful difference,
 *  or null if either URL doesn't parse. */
export function summarizeUrlDiff(subUrl, parentUrl) {
  let sub, parent;
  try {
    sub = new URL(subUrl);
    parent = new URL(parentUrl);
  } catch {
    return null;
  }

  const diffs = [];
  if (sub.origin !== parent.origin || sub.pathname !== parent.pathname) {
    diffs.push('Different site or page than the main search');
  }

  for (const { key, subVal, parentVal } of diffParams(sub.searchParams, parent.searchParams)) {
    if (key === 'sc') {
      const subParts = new Set(splitFilterBlob(subVal || ''));
      const parentParts = new Set(splitFilterBlob(parentVal || ''));
      const added = [...subParts].filter((p) => !parentParts.has(p)).map(humanizeFilterPart);
      const removed = [...parentParts].filter((p) => !subParts.has(p)).map(humanizeFilterPart);
      if (added.length || removed.length) {
        diffs.push(`Filters: ${[...added.map((p) => `+${p}`), ...removed.map((p) => `-${p}`)].join(', ')}`);
      }
      continue;
    }

    const label = URL_PARAM_LABELS[key] || key;
    if (!subVal) diffs.push(`${label}: removed (was "${parentVal}")`);
    else if (!parentVal) diffs.push(`${label}: "${subVal}" (added)`);
    else diffs.push(`${label}: "${subVal}" (main search: "${parentVal}")`);
  }

  return diffs;
}

/* --------------------------------------------------- copy variation across rows --
   Reapplies a sub-row's own diff (vs. its own parent) onto a DIFFERENT main
   row's URL, so a filter variation crafted under one search can be reused
   under another without retyping it. `q` (keywords) is deliberately never
   reapplied -- a sub-row is always the same target position as its parent,
   so the copy must keep using the TARGET row's own keywords, never the
   source row's. Origin/pathname are never touched either; only the query
   string changes. */
export function applyUrlDiff(targetBaseUrl, sourceSubUrl, sourceParentUrl) {
  let target, sourceSub, sourceParent;
  try {
    target = new URL(targetBaseUrl);
    sourceSub = new URL(sourceSubUrl);
    sourceParent = new URL(sourceParentUrl);
  } catch {
    return null;
  }

  for (const { key, subVal } of diffParams(sourceSub.searchParams, sourceParent.searchParams)) {
    if (key === 'q') continue;
    if (subVal === null) target.searchParams.delete(key);
    else target.searchParams.set(key, subVal);
  }

  return target.toString();
}
