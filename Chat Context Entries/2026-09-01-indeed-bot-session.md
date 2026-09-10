# IndeedHelper — session handoff (through 2026-09-01)

Read this before touching anything. It is the accumulated context from a long
debugging session: what the system is, what was wrong with it, what was fixed
and how it was proved, and what is still open.

---

## 1. What the project is

An automated Indeed job-application bot for **Tommy Orok (user id 9)**, plus a
desktop GUI for the database behind it.

| Piece | What it is |
|---|---|
| `main3.py` (~5000 lines) | The bot. Playwright driving real Chrome over CDP. |
| `myGPT2.py` | OpenAI wrapper. Prompt files, retries, timeouts. |
| `prompts/*.txt` | Prompt templates with positional placeholders. |
| `config/ExpectedEnvironments.txt` | Which pages the bot recognises. |
| `config/StateTransitions.txt` | What to do on each page, per state. |
| `dbgui/` | Flask + pywebview desktop GUI over `IndHelperDB.db`. |
| `db_admin.py` | GUI launcher. **This is the entry point**, not `main3.py`. |
| `tools/test_*.py` | 17 test suites. Plain scripts, no pytest. |
| `HTMLz/*.html` | Saved page captures. The ground truth for every selector. |
| `Logs/log*.txt` | Run logs the user supplies when reporting a problem. |

### Running things

```
venv\Scripts\python.exe db_admin.py            # the GUI (start here)
venv\Scripts\python.exe tools\test_x.py        # any suite; exit 0 = pass
venv\Scripts\python.exe tools\list_models.py   # what the API key can reach
```

Suites take 1–5 minutes each; several browser suites together exceed a
10-minute shell timeout, so **run them in batches of 4–6**.

---

## 2. How the bot is structured

A **state machine** keyed on the environment string `"<url>|<title>"`.

- `ExpectedEnvironments.txt` lists recognised pages as escaped regexes.
- `StateTransitions.txt` maps `(page, current_state) -> (function, next_state)`.
- **The two files must agree** or `validate_files` raises `ConfigMismatch`
  (`tools/test_config_validation.py` enforces this).
- `envIsValid` resolves ties by **longest matching pattern wins**. This makes
  rules sensitive to each other; `tools/test_env_routing.py` pins the routing
  so a new pattern cannot silently shadow an existing page.

### Config escape syntax

Text between `((` and `))` is kept as raw regex; everything else is escaped.
So `resume((([/?].*)?))|((.*))` means "resume, optionally followed by / or ?".

### Prompt placeholder system — read this before editing any prompt

`myGPT2.setAllPlaceVals` fills `PLACE&&HOLDER&&` by **popping values off the
front, in file order**. Comment lines (`//`) and the two lines after `&&CHECK&&`
are skipped before substitution, so a raw grep over-counts.

**Adding one placeholder shifts every later value into the wrong slot.**
`tools/test_writing_style.py` asserts the counts match the call sites. Current:

| prompt | placeholders |
|---|---|
| `cover_letter_prompts2.txt` | 13 |
| `summary_prompts2.txt` | 3 |
| `job_desc_prompts2.txt` | 8 |
| `free_response_question_prompts.txt` | 8 |
| `skills_prompts2.txt` | 3 |
| `headline_prompts2.txt` | 1 |

---

## 3. The Selenium→Playwright compatibility layer

`_DriverCompat` / `_ElementCompat` make Playwright quack like Selenium so the
original business logic runs unchanged. Two traps live here:

**Missing methods are crashes.** `_ElementCompat` implements only what has been
needed so far. `is_selected()` was missing and every screener answer died on it
for months, hidden by a bare `except`. `is_selected`/`is_displayed`/`is_enabled`
now exist. If you use another Selenium method, check it exists first.

**Wrappers have no identity.** Every `find_elements()` call builds fresh
`_ElementCompat` objects and the class defines no `__eq__`, so two wrappers
around the *same DOM node* compare unequal. **Never put them in a set and
subtract.** That bug made six questions look like thirty-six.

---

## 4. Recurring bug patterns — check for these first

These have each bitten more than once. When something is stuck, suspect them.

1. **`nohang=True` means "do not wait at all"**, ignoring `timeLimit`. Fine for
   a probe; wrong for anything that renders after a click.
2. **Unguarded `[0]` / `[1]` on a lookup result.** `findClosestRelatives(...)[0]`
   and `split("The answer is:")[1]` both took down whole runs.
3. **Unbounded `while` loops.** Several existed (`waitForever`,
   `ensureQualityOfDropDownAns`, the `extractQuestionInfo` handler). All are
   gone; if you add a retry loop, bound it.
4. **Positional xpath.** `generate_full_xpath` builds `/html/body[1]/div[3]/...`.
   Any DOM change above the element invalidates it. `smartClick(element=...)`
   now clicks the handle directly and must stay that way.
5. **Structural heuristics about DOM nesting.** e.g. "the second child of the
   first child has children". Indeed renests and they break. Test for the thing
   you actually care about (does this item contain a control?).
6. **Silent failure.** Bare `except`, unflushed prints, swallowed tracebacks.
   Every failure path should `reportAction` something a person can read.
7. **Indeed's hashed CSS classes and test ids rotate.** `data-testid` is usually
   stable, but the questions page uses a *hashed* one. `aria-label` is the most
   reliable, then structural selectors.

---

## 5. Page-flow knowledge that is not obvious

**The resume editor loses its way back.** It opens as
`/resume?co=US&hl=en_US&continue=<application url>`. Indeed **drops that query
string** as soon as anything inside the editor navigates (saving a work
experience does). After that the page is the standalone profile editor: its
footer says "Delete resume" instead of "Continue applying" and there is no way
onward. `rememberApplicationUrl()` captures the `continue=` value from within
`getCurrentEnv` (every state-machine loop passes through there) and
`finishResume` navigates straight back to it.

**"Go back" is not a safe fallback.** From a URL that still has `continue=` it
returns to the application. From bare `/resume` it goes to the Indeed *profile
home*, which is outside the application entirely (`profile_resume_indeed.html`).

**Deleting an entry inserts a "X removed / Undo" banner** rather than removing
the row immediately, and the list reads as *empty* for a moment while the
section re-renders. Never believe the first empty read (`_settledEntries`).

**Skills are not shaped like work/education.** They are chips on the resume page
(`data-testid="edit-chip-*"`, `aria-label="Edit <skill name>"` — the word
"skill" is not in the label). The only delete controls live in a modal reached
by clicking any chip. `"Delete resume"` also starts with `"Delete "` and must be
excluded, or clicking it destroys the resume.

**One question can hold several inputs**, and later ones may not exist until an
earlier one is answered (Country reveals State). `answerLinkedInputs` handles
this for dropdowns. **Not yet handled: a question mixing types** (e.g. a select
plus a text box) — deliberately left until there is a real capture of one.

**The review page arrives as a spinner and then navigates.** Waiting for the
spinner to clear is not enough; wait for the page's own controls
(`waitForReviewPage`).

**Not every review page offers a resume edit.** `review_application.html` has
only "Submit your application". That is healthy, not broken.

---

## 6. Current configuration

- **Models:** `input/model.txt` = `gpt-5` (prose), `input/model_fast.txt` =
  `gpt-5-mini` (fixed-choice questions; measured 2.3× faster on a real prompt).
  Overridable by `$INDEEDHELPER_MODEL` / `$INDEEDHELPER_FAST_MODEL`.
- **SDK is `openai==0.28.1`** (legacy `openai.ChatCompletion.create`). Verified
  it can call gpt-5, gpt-4.1 and gpt-4o. `request_timeout` is supported and is
  what actually bounds a hung call.
- `chatTimeOut=90`, `MAX_TIMEOUT_RETRIES=3`, `RETRY_PAUSE=5` → worst case ~280s.
- Tuning constants in `main3.py`: `PAGE_LOAD_LIMIT=45`, `ENTRY_LIST_SETTLE=4`,
  `MAX_STALE_RETRIES=6`, `RERENDER_SETTLE=0.6`, `MAX_QUESTIONS_PER_PAGE=40`,
  `MAX_LINKED_INPUTS=6`, `CHOICE_MATCH_FLOOR=0.30`, `ANSWER_RETRIES=4`.

### Writing style requirements (user's, explicit)

- **No em dashes or en dashes, ever.** Asked for in `styleGuide()` *and*
  enforced on output by `stripDashes()`, because asking is not reliable.
- A named list of AI tells is banned outright ("proven track record",
  "passionate about", "leverage", "seamlessly", "spearheaded", ~20 more).
- **Relevance is decided once, in the cover letter**: pick only the projects
  matching *this* job description. The resume summary then treats the cover
  letter as its scope and may not reintroduce projects the letter dropped; it
  uses the life details only to get concrete detail right.
- Screener answers must be built on the **closest-fitting real project**, leading
  with true details, filling in unstated specifics (team size, budget, duration)
  plausibly. Only inventing a *whole project or employer* is off limits.
- `users.WritingSample` is a new column and a Profile-tab field: a passage the
  applicant actually wrote, injected into the prose prompts to imitate voice.
  **The user has offered to supply a real sample and has not yet sent it** — ask.

---

## 7. Working agreements with this user

- **Diagnose from evidence, never guess.** They supply a log and/or an HTML
  capture; profile and query them before proposing a cause. Several confident
  guesses in this session were wrong and the data disproved them. Say so plainly
  when that happens.
- **Never test against the live database.** `IndHelperDB.db` holds plaintext
  Indeed passwords and PII. Copy it first. (A live-app test once corrupted real
  rows; they were restored from backup.)
- Every fix gets a regression test that **fails without the fix**. Verify that,
  don't assume it.
- Tests carry a comment explaining the real failure they pin, so the reason
  survives.
- The user reads the code. Explain the actual mechanism, not a summary.
- Do not start a real run: clicking Start submits genuine applications under
  their name. That is their action.

---

## 8. State as of this handoff

**All 17 suites pass.** Nothing is known-broken.

Verified working end to end in a live run at some point: job search → apply →
resume selection → resume edit (contact, summary, work, education, skills) →
continue → documents/cover letter → submit. **One application was successfully
submitted** (log8). Later runs got further each time.

### Fixed this session (each with a regression test)

Crashes that closed the browser: `IndexError` in `hitEditFromReviewPage`,
`None.strip()` on a missing transition, `generate_full_xpath` on a detached
element, `findFillMoveOn(None)`, `submitApp` scrolling a `None`.

Loops and hangs: the whole resume rebuilt five times, `waitForever`,
`ensureQualityOfDropDownAns`, the `extractQuestionInfo` error handler (which
also rebound `t`, the `time` module, to the integer 3), a GPT call that never
returned (the `with ThreadPoolExecutor` block was waiting for the very request
it had declared hung).

Silent no-ops: skills never deleted (wrong selectors), summary never written
(blank summary has no Edit button, only `summary-empty-state`), screener answers
computed but never ticked (`is_selected` missing), every question skipped (DOM
nesting heuristic), questions answered six times each (wrapper identity),
cover-letter step dead (rebuilt page), work entry never deleted (positional
xpath after banners shifted the DOM).

Wrong behaviour: answer matching that got *harder* the longer the reply
(threshold rose with answer length), year-only dates discarded entirely,
`"Android"` mangled to `"oid"`, both country and state dropdowns needed but only
the first was set.

GUI: application rows expand **inline beneath the clicked row** (they used to
render ~2500px below the fold, which looked like nothing happening); stored
Python-repr columns are parsed server-side with `ast.literal_eval` and rendered
as chips/entries/Q&A pairs.

### Open threads

1. **The writing sample.** User offered it; not yet supplied. Paste into the
   Profile tab's "Writing style sample" field.
2. **A question mixing input types** — not handled, waiting for a capture.
3. **`ensureQualityOfFreeRespAns` still has an unbounded `while` loop.** Not
   implicated in any observed failure (profiling showed it was never entered),
   left alone deliberately. Bound it if it ever bites.
4. **Speed.** Roughly 8–12 minutes per application. The floor is `sendAll`
   making a **separate API round trip per prompt block** (3 per question).
   Collapsing those would cut ~a third but changes what the model sees, so it
   should be done deliberately, not as part of a bug fix.
5. **Tailored-resume page and the `Add supporting documents` flow** are
   implemented and unit-tested against captures but have **not** been through a
   live run.

### Useful throwaway scripts

Written to the scratchpad this session and worth recreating: a `[CT]` log
profiler (sums the per-event millisecond deltas by component/selector) and a GPT
call timer (parses the `starting:` / `done...` wall-clock stamps). The second
one is what proved 23 calls finished in 12.7 minutes while a 24th never
returned. `[CT]` deltas do **not** cover GPT time — those lines are plain
prints — so profile both ways or the arithmetic misleads.
