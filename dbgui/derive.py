"""Job attributes derived on demand from text already in the applications table.

The bot never scraped salary, location, work mode or job type -- getPositionInfo()
reads exactly company, title and description, and deliberately steps over Indeed's
Pay/Job-type summary block. Adding columns for those would only ever describe
applications submitted from now on, leaving the 5,000+ historical rows blank.

Deriving them from jobTitle and JobDescriptionText instead works retroactively on
every row ever saved, which is the whole point: the useful history is ~1,500
applications from 2024 that no scrape change can reach.

Every function returns None rather than a guess when the text does not say. None
is surfaced as an explicit "Unspecified" bucket with its own count, so coverage
stays visible instead of quietly biasing a rate. Measured coverage over user 9's
~1,760 applications, which is why these four and not others:

    salary      65.6%   a $ amount is present
    job type    66.2%   full-time / contract / part-time / temporary / internship
    work mode   66.9%   but ~65% of that is "Remote", see work_mode() -- almost no
                        variance, so it explains very little
    seniority   ~23%    77% of titles carry no seniority word at all, so there is
                        no seniority function here: title_cluster() groups on the
                        titles that actually occur instead of forcing an invented
                        taxonomy onto data that does not carry one

PERFORMANCE. These run over every application on every page load: ~1,760 rows of
~3.8 KB is 6.8 MB per pass. A first cut that made ~8 case-insensitive regex passes
per field took 1.8s for employment type and 2.1s for work mode. So the text is
lowercased once per call and a cheap literal `in`/`str.find` test gates every
expensive regex -- `in` is a C-level substring search, far cheaper than a regex
scan, and most descriptions contain none of the phrasings being looked for.

These are pure functions over strings: no DB, no I/O, no Selenium.
"""

from __future__ import annotations

import re
from statistics import median

# --------------------------------------------------------------------------
# salary
# --------------------------------------------------------------------------

# A dollar amount, optionally with a K suffix ("$80K") or cents ("$25.50").
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s*([kK])?")

# How often that amount is paid. Searched in a short window AFTER the amount,
# which is where Indeed puts it ("$25.00 - $30.00 per hour").
_PERIODS = (
    ("hour", re.compile(r"(?i)per\s+hour|an?\s+hour|hourly|/\s*hr\b|\bhr\b|\bhours?\b")),
    ("year", re.compile(
        r"(?i)per\s+year|a\s+year|annually|annual|per\s+annum|/\s*yr\b|\byears?\b|\byr\b")),
    ("month", re.compile(r"(?i)per\s+month|a\s+month|monthly|/\s*mo\b|\bmonths?\b")),
    ("week", re.compile(r"(?i)per\s+week|a\s+week|weekly|/\s*wk\b|\bweeks?\b")),
)

# 40 hours x 52 weeks, the convention Indeed itself uses to show an annual figure.
_ANNUALIZE = {"hour": 2080.0, "week": 52.0, "month": 12.0, "year": 1.0}

_PERIOD_WINDOW = 45

# Anything outside this band is not this job's pay: below it are signing bonuses,
# 401k match caps and "$500 referral"; above it are revenue and funding figures.
_MIN_ANNUAL = 15_000.0
_MAX_ANNUAL = 900_000.0

# A bare amount with no period attached is only trusted at the two magnitudes
# that cannot plausibly mean anything else.
_BARE_HOURLY_MAX = 200.0
_BARE_YEARLY_MIN = 15_000.0

_SALARY_BANDS = (
    (40_000, "Under $40k"),
    (60_000, "$40k-$60k"),
    (80_000, "$60k-$80k"),
    (100_000, "$80k-$100k"),
    (130_000, "$100k-$130k"),
    (160_000, "$130k-$160k"),
)
_TOP_BAND = "$160k+"


def annual_salaries(text: str) -> list[float]:
    """Every dollar amount in `text` that plausibly describes this job's pay,
    normalised to an annual figure.

    Each amount takes its period from the ~45 characters after it, so
    "$25.00 - $30.00 per hour" annualises BOTH ends of the range even though only
    the second carries the words. An amount with no period nearby is kept only
    when its magnitude is unambiguous (<= $200 reads as hourly, >= $15,000 as
    annual) and dropped otherwise, which is what keeps bonuses out.
    """
    if not text or "$" not in text:
        return []

    values: list[float] = []
    for match in _MONEY.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            continue
        if match.group(2):  # the K in "$80K"
            amount *= 1000.0

        window = text[match.end():match.end() + _PERIOD_WINDOW]
        period = None
        earliest = len(window) + 1
        for name, pattern in _PERIODS:
            found = pattern.search(window)
            if found and found.start() < earliest:
                earliest, period = found.start(), name

        if period is None:
            if amount <= _BARE_HOURLY_MAX:
                period = "hour"
            elif amount >= _BARE_YEARLY_MIN:
                period = "year"
            else:
                continue

        annual = amount * _ANNUALIZE[period]
        if _MIN_ANNUAL <= annual <= _MAX_ANNUAL:
            values.append(annual)

    return values


def salary_midpoint(text: str) -> float | None:
    """One representative annual figure for a description, or None.

    The median, not the mean or the max: a description that quotes a range plus an
    unrelated figure ("$80,000 - $100,000 ... $5,000 sign-on") should land on the
    range, and the median is what resists the stray value.
    """
    values = annual_salaries(text)
    if not values:
        return None
    return float(median(values))


def salary_band(text: str) -> str | None:
    """A coarse band label for grouping, or None when the text quotes no pay."""
    midpoint = salary_midpoint(text)
    if midpoint is None:
        return None
    for ceiling, label in _SALARY_BANDS:
        if midpoint < ceiling:
            return label
    return _TOP_BAND


SALARY_BAND_ORDER = [label for _, label in _SALARY_BANDS] + [_TOP_BAND]


# --------------------------------------------------------------------------
# labelled lines -- "Job type: Full-time", "Work Location: Remote"
# --------------------------------------------------------------------------

def labelled_value(text: str, labels: tuple[str, ...], window: int = 60) -> str | None:
    """The text just after a "<label>:" heading, if one is present.

    Indeed renders its structured facts as short labelled lines, so when one is
    present it is far better evidence than a keyword anywhere in the prose.

    No regex: str.find over a lowercased copy is enough, and this is called twice
    per application per page load.
    """
    if not text:
        return None
    lowered = text.lower()
    for label in labels:
        index = lowered.find(label)
        if index == -1:
            continue
        start = index + len(label)
        chunk = text[start:start + window + 4]
        # Stop at the line end. These are single line items, and reading past one
        # pulls in whatever sentence follows -- enough to make a description whose
        # Job type line says Full-time, but whose next sentence mentions a
        # contract team, come back as Contract.
        for break_at in ("\r", "\n"):
            cut = chunk.find(break_at)
            if cut != -1:
                chunk = chunk[:cut]
        return chunk.lstrip(" \t:").strip()
    return None


# --------------------------------------------------------------------------
# employment type
# --------------------------------------------------------------------------

_TYPE_LABELS = ("job type", "employment type", "job types", "position type")

# (name, cheap literal gates, precise pattern). Order is priority, not preference:
# a posting that says "full-time contract" is a contract, and "temporary
# full-time" is temporary. The narrower fact wins.
#
# The literal gates exist purely for speed -- the pattern is what decides. Every
# pattern is matched against already-lowercased text, so none need re.IGNORECASE.
_TYPE_RULES: tuple[tuple[str, tuple[str, ...], re.Pattern], ...] = (
    ("Contract",
     ("contract", "w2", "w-2", "c2c", "corp to corp", "corp-to-corp", "1099"),
     re.compile(r"contract|contractor|\bw-?2\b|\bc2c\b|corp.to.corp|\b1099\b")),
    ("Internship", ("intern",), re.compile(r"\binternships?\b|\binterns?\b")),
    ("Temporary", ("temp", "seasonal"),
     re.compile(r"\btemporary\b|\btemp\b|\bseasonal\b")),
    ("Part-time", ("part-time", "part time", "parttime"), re.compile(r"part[\s-]?time")),
    ("Full-time", ("full-time", "full time", "fulltime"), re.compile(r"full[\s-]?time")),
)


def _type_from(lowered: str) -> str | None:
    for name, literals, pattern in _TYPE_RULES:
        for literal in literals:
            if literal in lowered:
                if pattern.search(lowered):
                    return name
                break
    return None


def employment_type(text: str) -> str | None:
    """Full-time / Part-time / Contract / Temporary / Internship, or None.

    A labelled "Job type:" line is consulted first and answered from alone when it
    matches, because prose elsewhere routinely mentions other arrangements ("this
    is not a part-time role", "contract negotiation experience").
    """
    if not text:
        return None

    labelled = labelled_value(text, _TYPE_LABELS)
    if labelled:
        found = _type_from(labelled.lower())
        if found:
            return found

    return _type_from(text.lower())


EMPLOYMENT_TYPE_ORDER = [name for name, _, _ in _TYPE_RULES]


# --------------------------------------------------------------------------
# work mode -- deliberately conservative
# --------------------------------------------------------------------------

_MODE_LABELS = ("work location", "work setting", "location type", "remote status")

_HYBRID = re.compile(r"\bhybrid\b")
_ONSITE = re.compile(r"\bon[\s-]?site\b|\bin[\s-]?office\b|\bin[\s-]?person\b")
_REMOTE = re.compile(r"\bremote\b|work from home|\bwfh\b|telecommut")

# "remote" appears in 81.6% of descriptions, so a bare mention proves nothing.
# Only these phrasings are treated as the posting actually stating the mode.
_REMOTE_STRONG = re.compile(
    r"fully[\s-]remote|100%\s*remote|remote[\s-]first|this is a remote|"
    r"remote position|remote role|work from home position"
)
_NOT_REMOTE = re.compile(
    r"not\s+a\s+remote|no\s+remote|not\s+remote|must\s+be\s+on[\s-]?site|"
    r"required\s+to\s+work\s+on[\s-]?site|this\s+is\s+not\s+a\s+work\s+from\s+home"
)


def work_mode(text: str, search_url: str | None = None) -> str | None:
    """Remote / Hybrid / On-site, or None when the posting does not clearly say.

    LOW CONFIDENCE BY CONSTRUCTION, and a large Unspecified bucket is the correct
    outcome here rather than a failure: the searches themselves filter on
    l=Remote, so nearly every description mentions the word without the posting
    being remote-only. Bare mentions are ignored; only a labelled line, an
    explicit phrase, or a negation counts.

    Even so, measured on real data this comes out ~65% Remote / ~2% Hybrid / ~0%
    On-site. That is almost no variance, which makes it a weak dimension for
    explaining differences in outcome -- it is presented as such, not as a
    headline cut.

    `search_url` is accepted so a caller can note that a search targeted remote
    work, but it never decides the answer -- that would label every application
    from a remote search "Remote" and turn the dimension into a restatement of
    which search ran.
    """
    if not text:
        return None

    lowered = text.lower()

    labelled = labelled_value(text, _MODE_LABELS, window=40)
    if labelled:
        low_label = labelled.lower()
        if "hybrid" in low_label:
            return "Hybrid"
        if _REMOTE.search(low_label):
            return "Remote"
        if _ONSITE.search(low_label):
            return "On-site"

    # Literal gate first: most descriptions contain none of these phrasings, and
    # skipping the scan entirely is the whole point.
    if ("not" in lowered or "must be" in lowered or "required" in lowered):
        if _NOT_REMOTE.search(lowered):
            return "On-site"
    if "hybrid" in lowered and _HYBRID.search(lowered):
        return "Hybrid"
    if "remote" in lowered or "work from home" in lowered:
        if _REMOTE_STRONG.search(lowered):
            return "Remote"
    return None


WORK_MODE_ORDER = ["Remote", "Hybrid", "On-site"]


# --------------------------------------------------------------------------
# title clustering
# --------------------------------------------------------------------------

# Stripped before clustering so "Senior Data Analyst" and "Data Analyst II" land
# in the same bucket. This is NOT a seniority taxonomy -- 77% of titles carry no
# seniority word, so grouping BY seniority would bucket three quarters of the data
# into one meaningless pile. These words are removed, not measured.
_TITLE_NOISE = re.compile(
    r"(?i)\b(senior|sr|junior|jr|lead|principal|staff|entry[\s-]?level|mid[\s-]?level|"
    r"experienced|associate|i{1,3}|iv|v|\d+)\b"
)
_TITLE_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_TITLE_SPLIT = re.compile(r"\s*[/|,–—]\s*|\s+-\s+")
_TITLE_PUNCT = re.compile(r"[^a-z0-9\s+#]")
_WHITESPACE = re.compile(r"\s+")


def _normalise_segment(segment: str, *, strip_noise: bool) -> str:
    text = _TITLE_PUNCT.sub(" ", segment.lower())
    if strip_noise:
        text = _TITLE_NOISE.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def title_cluster(title: str) -> str | None:
    """A normalised grouping key for a job title, or None if nothing is left.

    Indeed titles routinely bolt extras onto the real job: a leading tag
    ("[Volunteer] Grant Writer"), a trailing location or req number, or two roles
    joined by a slash. So bracketed asides are dropped, the rest is split, and the
    LONGEST surviving segment wins -- not the first, which would reduce
    "$15/Hour - Healthcare Sales Associate" to "hour" and
    "Senior/Lead Forward Deployed AI Engineer" to nothing at all.

    Noise words are stripped so "Senior Data Analyst" and "Data Analyst II" group
    together, but a title made ENTIRELY of them ("Associate, Marketing") falls
    back to keeping them rather than vanishing -- returning None there would
    silently drop the row from the cut.
    """
    if not title:
        return None

    stripped = _TITLE_BRACKETED.sub(" ", title).strip() or title.strip()
    segments = [seg for seg in _TITLE_SPLIT.split(stripped) if seg and seg.strip()]
    if not segments:
        segments = [stripped]

    for strip_noise in (True, False):
        best = ""
        for segment in segments:
            cleaned = _normalise_segment(segment, strip_noise=strip_noise)
            if len(cleaned.split()) > len(best.split()):
                best = cleaned
        if best:
            return best
    return None


def title_tokens(title: str) -> list[str]:
    """The significant words of a title, for looser keyword grouping."""
    cluster = title_cluster(title)
    return cluster.split() if cluster else []
