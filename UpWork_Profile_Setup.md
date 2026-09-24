# Upwork Profile Setup — Tommy Orok

Fill-in guide for the Upwork "Add your profile details" glidepath page
(`HTMLz/UpWorkSetUp.html`). Every value below is drawn from the IndeedHelper
database (`IndHelperDB.db`, user ID 9): the `users`, `Job`, `Edu`, and
`job_searches` tables.

The page has five cards, in this order:

1. About you — photo, **Title**, **Introduction**
2. Hourly rate
3. Employment history
4. Education
5. Language

Everything in a code block is ready to copy verbatim.

---

## 1. About you

### 1a. Profile photo

The uploader currently shows the initials placeholder `TO`. Upwork ranks
photo-less profiles lower and clients skip them. Upload a real headshot — face
filling most of the frame, plain background, no logo, no group shot. This is the
one field on the page the database can't fill for you.

### 1b. Title

Upwork caps this at **70 characters**. The field is currently erroring with
"Enter a title with at least 4 characters."

**Recommended (61 chars):**

```
Full-Stack & Automation Engineer | Python, Node, AI Workflows
```

Why this one: it leads with the two things the database has the most recent and
most sellable evidence for — automation/scraping systems and full-stack product
work — and names the three keywords Upwork's search actually indexes. It is
deliberately *not* "Software Engineer," which is the most crowded phrase on the
platform.

**Alternates**, depending on which niche you want to compete in:

| Title | Chars | Use when |
|---|---|---|
| `Full-Stack Engineer \| Python, Node.js, AI Automation & Scrapers` | 63 | You want scraping leads specifically |
| `Web Scraping & Automation Expert \| Python, Playwright, Selenium` | 63 | Narrowest, highest win-rate niche for a new profile |
| `Senior Software Engineer \| FinTech, Trading Systems, C++ & Python` | 65 | You want the high-rate FinTech lane |
| `AI Engineer \| LLM Workflows, Automation & Full-Stack Development` | 64 | You want to sell the Kacha Inc multi-LLM process |

Pick one lane and keep the Introduction consistent with it. A title that tries
to cover all four reads as a generalist and prices like one.

### 1c. Introduction (Overview)

Minimum 100 characters; Upwork's ceiling is 5,000. The draft below is 2,758
characters, leaving plenty of room to add a portfolio line later.

```
I build the systems that do the work while you sleep — web scrapers, automation bots, AI-assisted pipelines, and the full-stack apps around them.

Columbia University CS, and roughly a decade shipping production software across three worlds that rarely overlap.

AUTOMATION & WEB SCRAPING
Playwright, Selenium and Cheerio scrapers that survive real websites — anti-bot handling, session and browser-profile management, retries with exponential backoff, and per-host rate limiting. Recent builds: a multi-retailer luxury inventory aggregator (Nordstrom, Neiman Marcus, Saks, Bloomingdale's) that normalizes every store into one canonical schema with cross-source dedupe, change detection and keyword alerting; and an automated job-application engine that parses postings, tailors a resume per opening, answers screening questions and logs every submission.

AI / LLM ENGINEERING
I run a worker-LLM / reviewer-LLM workflow: one model plans and implements, a second audits and scores it out of 10, and the two argue until the score clears 9 — before a human reviews anything. Paired with a persistent decision log and transcribed client calls, every feature traces back to a specific, verifiable request, and no bug gets re-introduced twice.

FULL-STACK PRODUCT
Node.js / Express / MongoDB and Next.js / React / TypeScript / PostgreSQL / Prisma. I built and still maintain a rental-and-payments platform running Square checkout, saved cards, scheduled installments, refunds, sales-tax reporting and settlement reconciliation — plus inventory reservation logic that made double-booking impossible for a business that was bleeding money on refunds.

LOW-LATENCY & FINTECH
C++ against the CME: FIX 4.2/4.4 session work, HMAC-SHA-256 logon signing, MDP 3.0 multicast market data, and the Linux/IGMP/firewall debugging it took to get the packets actually arriving. An event-driven Python asyncio trading engine with adaptive rolling statistical bands and explicit order state machines. On the ML side, PyTorch models on AWS SageMaker with walk-forward validation, drift monitoring and automated retraining.

HOW I WORK
Most of my value isn't the typing — it's telling you when what you asked for isn't what will actually solve your problem, then building the thing that does. I write plainly, I estimate honestly (including when my last estimate was wrong), and I ship in pieces you can test as they land instead of one big reveal at the end.

Stack: Python, JavaScript, TypeScript, C++, Java, Node.js, Express, Next.js, React, MongoDB, PostgreSQL, Prisma, Playwright, Selenium, BeautifulSoup, Cheerio, AWS (SageMaker, S3, CloudWatch), Vercel, Square API, Auth.js, Docker, Git.

Send me the messy version of your problem and I'll tell you what it will actually take.
```

Two notes on the draft:

- The first line is the only part most clients read before deciding whether to
  expand it. It is a promise, not a job title.
- The "HOW I WORK" block comes from your own words in the `Job` record for Ivy
  Kode ("convincing the client that what they asked for isn't actually what they
  need") and the tone of your `WritingSample`. It is the part of the profile no
  competitor can copy, so don't cut it for length.

---

## 2. Hourly rate

The field accepts $3.00–$999.00 and the widget computes
`your rate − Upwork service fee = total earnings`. Upwork's fee is currently a
flat 10% on most contracts — trust whatever the widget renders over this table.

| Listed rate | Fee (10%) | You keep | Read |
|---|---|---|---|
| $65 | $6.50 | $58.50 | Too low for a Columbia CS grad with CME/C++ on the profile |
| $75 | $7.50 | $67.50 | Safe floor while you collect your first three reviews |
| **$85** | **$8.50** | **$76.50** | **Recommended** |
| $95 | $9.50 | $85.50 | Fine if you lead with the FinTech title |
| $110+ | $11.00+ | $99.00+ | Wait for a Job Success Score and 2–3 five-star reviews |

**Enter: `85`**

Reasoning: you have roughly ten years of experience and a genuinely rare
combination — exchange connectivity, payments, ML, and scraping — but a brand
new profile has no Job Success Score, so clients discount you on risk rather than
on skill. $85 clears the "cheap offshore" filter without inviting the scrutiny
that $150 does. Raise it $10–15 after each batch of good reviews. Upwork lets you
set a different rate per contract anyway, so this number is a signal, not a
commitment.

---

## 3. Employment history

Four records in the database. Add them in this order — Upwork displays newest
first, so entering them this way keeps the card readable as you go.

### Entry 1 — Kacha Inc

| Field | Value |
|---|---|
| Company | `Kacha Inc` |
| City / Country | `Atlanta, GA` / `United States` |
| Title | `AI Consultant` |
| Period | `August 2023` – tick **"I currently work here"** |

```
AI-augmented software consulting. I deliver full-stack features using a dual-LLM workflow: a worker model plans and implements, a reviewer model audits and scores the work, and the cycle repeats until it clears 9/10 before a human ever reviews it.

- Built and run the plan-review-defend-rescore cycle that catches design, security and backward-compatibility problems before implementation starts
- Maintain an enhancement and bug-fix tracker plus persistent project memory, so context survives across months and sessions — no regressions, no re-trying approaches that already failed
- Record and transcribe client meetings into a queryable knowledge base, so every shipped feature traces back to a verifiable client quote rather than someone's recollection
- Enforce implementation discipline: no file over 1,000 lines, no duplicated logic, validation at the frontend, API and database layers, and every schema migration shipped with preview, dry-run and confirm modes
- Deliver across the whole stack — schema, API, frontend, migrations and documentation
```

### Entry 2 — Ivy Kode

| Field | Value |
|---|---|
| Company | `Ivy Kode` |
| City / Country | `Atlanta, GA` / `United States` |
| Title | `Software Consultant` |
| Period | `January 2019` – `December 2025` (see flag #4) |

```
Independent software consulting across staff-augmentation and specialist project engagements — hands-on development roughly 95% of the time.

- Brought in as technical rescue on projects that had stalled from staff turnover, failed offshoring or internal political deadlock
- Led agile modernization work migrating legacy systems onto modern stacks
- Ran stakeholder interviews and requirements gathering; frequently the most valuable deliverable was showing a client that what they had asked for was not what would solve their problem
- Mentored students and working professionals in Python, C++ and Java — concept instruction and live debugging
- Operated as a leader-doer: owned the technical direction while writing the code
```

### Entry 3 — 21st Century Realty

| Field | Value |
|---|---|
| Company | `21st Century Realty` |
| City / Country | `Austell, GA` / `United States` |
| Title | `Software Developer` |
| Period | `October 2017` – `May 2020` |

```
Full-stack developer on a rental, contract, payments and operations platform built with Node.js, Express and MongoDB, deployed on Vercel serverless functions.

- Built customer, owner and admin portals with role and permission-based access, Auth.js credential sessions, JWTs and Argon2id password hashing
- Implemented Square checkout end to end: card tokenization, saved cards, charges, refunds, scheduled installments, invoices and tokenized payment links
- Designed the inventory reservation model and resource calendar that made same-day overbooking impossible, directly eliminating the refund losses that prompted the project
- Built the financial reporting layer: partner settlement workbooks, sales dashboards, sales-tax exports, and Square payment reconciliation with variance and adjustment handling
- Added transactional safety with checkout idempotency keys, MongoDB transactions and Redis-backed distributed locks, so duplicate submissions cannot create duplicate charges
```

### Entry 4 — Gryphus Trading

| Field | Value |
|---|---|
| Company | `Gryphus Trading` |
| City / Country | `New York, NY` / `United States` |
| Title | `Head Systems Engineer` |
| Period | `December 2015` – `August 2019` |

```
Lead infrastructure and integration engineer at a quantitative hedge fund, building the firm's automated trading pipeline from the ground up against the Chicago Mercantile Exchange.

- Implemented FIX 4.2/4.4 connectivity to CME production, injecting CME's custom logon tags and generating dynamic HMAC-SHA-256 signatures with Crypto++ inside the OnixS engine's outbound session callback
- Brought up CME MDP 3.0 multicast market data: diagnosed weeks of zero inbound data with tcpdump, traced IGMP join packets being dropped at the ASA firewall and the upstream ISP router, and drove the PIM configuration with the network team
- Wrote the C++ normalization layer converting CME mantissa/exponent prices and DisplayFactor into strategy-usable values, and fixed the object-lifecycle and threading bugs that were silently killing asynchronous callbacks
- Built an event-driven Python asyncio relative-value engine: synthetic cross-market signal, adaptive rolling statistical bands, tiered entry state machines with sequencing guards, partial-fill handling and human-override detection
- Developed ML mean-reversion models in PyTorch on AWS SageMaker with walk-forward validation, Sharpe/drawdown/turnover evaluation, Model Monitor drift detection and automated retraining pipelines
- Acted as technical liaison to the software vendor and colocation provider, escalating through JIRA and independently verifying support recommendations before acting on them
```

---

## 4. Education

One record in the database.

| Field | Value |
|---|---|
| School | `Columbia University` |
| Dates attended | `2012` – `2016` |
| Degree | `Bachelor's Degree` |
| Area of study | `Computer Science` |

Description (optional field, but fill it):

```
Led a four-person team building a food delivery application as my senior capstone project. Built a custom web server in C in four hours at a campus hackathon. Wrote my first production automation the summer after freshman year — a Craigslist monitor that alerted me to underpriced iPhones fast enough to be the first buyer.
```

Upwork education descriptions are usually left blank, which wastes a slot. Yours
is doing work: it converts a 2016 degree into evidence that you were already
shipping.

---

## 5. Language

The card pre-fills `English (required)` and disables the name field. Only the
proficiency dropdown ("My level is") needs an answer.

| Field | Value |
|---|---|
| Language | `English (required)` — locked |
| Proficiency | **`Native or Bilingual`** |

Do not add a second language from this database. See flag #6.

---

## Flags — resolve these before you submit

1. **Kacha Inc's end date contradicts itself.** The record has
   `currentPosition = Yes` but `To = August 2026`, and today is September 2026.
   Either tick "I currently work here" and drop the end date (recommended, and
   what the guide above assumes), or set a real end date and stop calling it
   current.

2. **Two pairs of overlapping dates.** Gryphus (Dec 2015 – Aug 2019) overlaps
   21st Century Realty (Oct 2017 – May 2020); Ivy Kode (2019 – 2025) overlaps
   Kacha (2023 – present). On Upwork this is normal for contract and consulting
   work, but a client *will* ask — have the one-sentence answer ready
   ("consulting engagements ran concurrently with employment").

3. **Gryphus starts seven months before you graduate.** Dec 2015 start vs. May
   2016 graduation. Fine if it began part-time or as a student role — just tell
   it the same way every time.

4. **Ivy Kode has year-only dates.** The database stores `2019` and `2025`;
   Upwork wants month and year. I used January 2019 – December 2025 above as a
   placeholder. Replace with the real months.

5. **The 21st Century Realty record contains the beach-rental platform
   write-up.** The stored `Description` for a company categorized "Real Estate"
   in Austell, GA is the Redfish rental/payments platform, while your
   `LifeSummary` separately describes building that site for "a beach rental
   service business." Confirm which employer that work actually belongs to
   before it goes on a public profile. The description I wrote is accurate
   either way — it never names Redfish or a beach — but the attribution should
   be right.

6. **There is no language-proficiency data in this database.** The `homePage`
   field contains Indeed searches for `mandarin` and `french`, but those are
   *job searches* — evidence you were looking at bilingual roles, not evidence
   you speak either language. Only add a second language if you are genuinely
   conversational; Upwork clients hire on that basis and will find out on the
   first call.

7. **Your Indeed avoid-rules don't carry over.** `avoidEmployers`
   (DataAnnotation, Indeed) and the three `avoid` screening questions
   (commission-only pay, mandatory in-office, required certificate) are
   IndeedHelper bot settings. This page has no equivalent and Upwork has no
   employer blocklist — apply them by hand when choosing which jobs to bid on.

---

## Appendix — data for the steps after this page

Upwork's glidepath continues past this card. These values are already in the
database and will be asked for:

| Upwork field | Value from DB |
|---|---|
| Full name | Tommy Orok |
| Email | tommyorok43@gmail.com |
| Phone | (770) 383-5362 |
| Street address | 448 Schofield Dr |
| City / State | Powder Springs, GA |
| ZIP | 30127 |
| Country | United States |
| LinkedIn | https://www.linkedin.com/in/tommy-orok-8273ab120/ |

**Skills (Upwork allows 10 on the main profile).** Chosen to match the
recommended title, not the raw frequency counts in `applications` — those are
dominated by an older run of customer-service and marketing job searches and do
not represent you:

```
Python, JavaScript, TypeScript, Node.js, React, Web Scraping,
Automation, PostgreSQL, MongoDB, API Integration
```

Swap `Web Scraping` and `Automation` for `C++`, `FIX Protocol` and
`Machine Learning` if you go with the FinTech title instead.

**Portfolio pieces**, in the order they will win work — all four are documented
in `users.LifeSummary`:

1. **Luxury Discount Aggregation Site ("My Wife's Assistant")** — Next.js 16,
   React 19, TypeScript, Tailwind 4, PostgreSQL, Prisma 7, Playwright, Cheerio.
   Multi-retailer scraping, canonical cross-store schema, two-dimensional
   price/discount browsing, saved-search email alerts. Your single best proof
   for the scraping niche.
2. **Redfish rental & payments platform** — the money-handling one. Square,
   reconciliation, settlement, tax reporting.
3. **Tommy Planner** — a recursive planning web component with cycles,
   synchronized reflections and cross-plan groups. Proves front-end depth and
   original product thinking.
4. **Automated Relative-Value Trading Engine** — Python asyncio, explicit state
   machines, kill switches. Proves you can be trusted with systems where a bug
   costs money.

Your `WritingSample` — the client follow-up email about lend/borrow blocking
rules — is the strongest communication artifact in the database. If a client
asks for a writing sample, or you need a proposal template, start from that. It
is already better than anything written for the occasion.
