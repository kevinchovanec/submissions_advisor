"""
Generates and caches summaries of journal guidelines pages.

Two files, deliberately split (see the plan's distribution workstream):

  data/journal_summaries.json  — content, COMMITTED and shipped to cloud users.
  data/journal_cache_meta.json — checked_at / fingerprint, gitignored.
  data/journal_pages/*.txt     — normalized page text for change detection, gitignored.

The split exists so a run that changes nothing produces a zero-byte diff on the
committed file: `git diff --stat data/journal_summaries.json` is then exactly the list
of what to push. If checked_at lived in the committed file every run would dirty all
500-odd entries with timestamp noise.

Refresh is gated cheapest-first, because rewriting summary prose changes the bytes of
the largest cached block in the agent's prompt and silently costs the next
conversation a full-price prefix:

  Gate 0  checked_at within RECHECK_AFTER_DAYS   -> skip, no network
  Gate 1  page hash unchanged after normalizing  -> skip, no tokens
  Gate 2  page changed but details identical     -> keep prose byte-for-byte

Gate 1 is an exact hash rather than a similarity score on purpose — see
page_unchanged for why a threshold cannot work here. Gate 2 is what keeps a
false "changed" from costing anything but one model call.

Run from the command line for a full fill (it takes about an hour for ~500 journals,
which is a long time to hold a browser tab open):

    python src/summarize_journals.py --all --dry-run     # what would change, no tokens
    python src/summarize_journals.py --all               # the real thing
    python src/summarize_journals.py --only "new yorker" --force
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import anthropic

from models_config import EXTRACTION_THINKING, MODEL
from pagefetch import fetch_page

DATA_DIR = Path(__file__).parent.parent / "data"
SUMMARIES_PATH = DATA_DIR / "journal_summaries.json"
META_PATH = DATA_DIR / "journal_cache_meta.json"
PAGES_DIR = DATA_DIR / "journal_pages"

MAX_PAGE_CHARS = 6000
REQUEST_DELAY = 0.5

# Guidelines move on reading-period boundaries, not weekly.
RECHECK_AFTER_DAYS = 90
# Up to two follow-ups: one toward submission mechanics, one toward the journal's
# character. Enough to escape a contact page and still learn what the journal is like,
# cheap enough to run across hundreds of journals.
MAX_FOLLOW_LINKS = 1
MAX_PAGES_PER_JOURNAL = 2

# Two link vocabularies, because two different things are worth learning: the
# mechanics (limits, deadlines, fees) and the aesthetic (what the journal is like).
# Weighted so a plain "submissions" link beats an "about" page that happens to match
# several weak hints — unweighted scoring picked /about/masthead over /submissions.
_FOLLOW_HINTS = {
    "submission": 10, "submit": 10, "guideline": 10,
    "contribut": 5, "for writers": 5, "what we": 5, "looking for": 5,
    "write": 1,
}

# Where a journal reveals its sensibility when it has no mission statement.
_ABOUT_HINTS = {
    "about": 10, "what we": 8, "looking for": 8, "mission": 8, "manifesto": 8,
    "masthead": 5, "editor": 4, "current issue": 4, "issue": 3, "archive": 3,
    "read": 2, "fiction": 2, "poetry": 2, "stories": 2,
}

DETAIL_FIELDS = (
    "aesthetic",
    "word_limit",
    "reading_period",
    "response_time",
    "simultaneous_submissions",
    "multiple_submissions",
    "fee",
    "red_flags",
)

# The ranked list carries one of these per journal, so every character is paid for
# at the start of every conversation. Written to be scanned, not read.
INDEX_LINE_MAX_CHARS = 180

INDEX_LINE_PROMPT = """Write a single-line index entry for this literary journal.

A writer is scanning a list of 150 of these to decide which few deserve a closer
look. The line has to earn its place: it is loaded into the model's context for
every conversation, so filler is expensive.

Journal: {name}

What is known about it:
{summary}

Details:
{details}

Rules:
- At most {max_chars} characters. One line. No trailing period needed.
- Lead with what they publish and the sensibility - the specific thing that would
  make a writer think "that's my story" or "not for me". Be concrete: name forms,
  subjects, registers, or comparable writers where the source supports it.
- Cut anything a writer cannot act on: founding dates, print frequency, awards,
  editor names, circulation, university affiliation, self-praise like "prestigious"
  or "long-running", and any phrase that would be true of most journals.
- Add a constraint ONLY if it is unusual enough to rule the journal in or out at a
  glance - flash-only, novel excerpts welcome, currently closed, poetry only, a
  hard genre restriction, a large fee. Ordinary limits belong in the detail record,
  not here.
- If the source says almost nothing concrete, say that plainly and briefly rather
  than padding. "No stated aesthetic; general literary" is more useful than invention.

Reply with ONLY the line itself - no quotes, no JSON, no preamble."""

SUMMARY_PROMPT = """You are cataloguing a literary journal for a writer deciding where to send a story.

Below is text from one or more pages of the journal's own site. It may be a submission
guidelines page, an about page, a masthead, a table of contents, published work, or a
mix. Whatever it is, describe THE JOURNAL.

Reply with ONLY a JSON object, no prose around it:

{{
  "index_line": "ONE line, at most 180 characters, for a writer scanning a list of 150 journals. Lead with what they publish and the sensibility - the specific thing that makes a writer think 'that's my story'. Cut founding dates, frequency, awards, editor names, and any praise that would be true of most journals. Add a constraint only if it would rule the journal in or out at a glance (flash-only, poetry only, currently closed, a large fee).",
  "summary": "At most 3 sentences describing the journal: what it publishes and what its work feels like, then any practical limits worth knowing.",
  "found_guidelines": true,
  "details": {{
    "aesthetic": "What they publish - voice, themes, forms, sensibility. Be concrete and specific to this journal.",
    "word_limit": "e.g. 'up to 8000 words' or 'unknown'",
    "reading_period": "e.g. 'Aug 15 - May 15', 'year-round', or 'unknown'",
    "response_time": "e.g. '3-6 months' or 'unknown'",
    "simultaneous_submissions": "allowed / not allowed / unknown, plus any condition",
    "multiple_submissions": "whether more than one piece at a time is allowed, or unknown",
    "fee": "e.g. 'none', '$3', or 'unknown'",
    "red_flags": "Anything that would waste the writer's time, or 'none noted'"
  }}
}}

Rules:
- NEVER describe the web page itself. "This page is a contact form" is useless to a
  writer. Describe the journal, using whatever the text reveals about it.
- Aesthetic can be inferred from evidence other than a mission statement: the titles
  and subjects of published pieces, contributor names, how the journal talks about
  itself, the design of its issues. Say what you can, and say what it is grounded in.
- The mechanical fields are different: use the exact string "unknown" for any of them
  the text does not state. Never guess a word limit, deadline, or fee.
- Set "found_guidelines" to true only if the text stated at least one concrete
  submission mechanic (a limit, a reading period, a fee, a policy). Set it to false
  when you only learned what the journal is like — that is still a useful summary,
  it just means the agent should check specifics before submitting.
- If the text genuinely says nothing about any journal — a parked domain, an error
  page, an unrelated site — set "found_guidelines" false and say so plainly in one
  sentence. Only then is describing the page the right answer.

Page content:
{page_text}"""


# ---------------------------------------------------------------------------
# Cache files
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


def _load_cache() -> dict:
    return _load_json(SUMMARIES_PATH)


def _save_cache(cache: dict) -> None:
    _save_json(SUMMARIES_PATH, cache)


def _load_meta() -> dict:
    return _load_json(META_PATH)


def _save_meta(meta: dict) -> None:
    _save_json(META_PATH, meta)


def _page_path(norm: str) -> Path:
    """Sidecar path for a journal's normalized page text."""
    safe = re.sub(r"[^a-z0-9._-]+", "-", norm.lower()).strip("-") or "unnamed"
    return PAGES_DIR / f"{safe}.txt"


def _read_page_text(norm: str) -> str:
    path = _page_path(norm)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_page_text(norm: str, text: str) -> None:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _page_path(norm).write_text(text, encoding="utf-8")
    except OSError:
        pass  # Change detection degrades to "always re-summarize"; not fatal.


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

_VOLATILE_PATTERNS = (
    # "closes in 12 days", "3 hours left"
    re.compile(r"\b(?:in|within|after|for|next|last|only|just)?\s*\d+\s*(?:second|minute|hour|day|week|month|year)s?\b"),
    # ISO dates and slash dates
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"),
    # "August 15, 2026" / "15 August 2026"
    re.compile(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*(?:19|20)\d{2}\b"
        r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(?:19|20)\d{2}\b"
    ),
    # bare years (copyright lines, issue years)
    re.compile(r"\b(?:19|20)\d{2}\b"),
    # clock times
    re.compile(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b"),
)


def normalize_for_fingerprint(text: str) -> str:
    """Lowercase and collapse a page, removing only genuinely volatile chrome.

    Dates, clock times, bare years, and relative countdowns ("closes in 12 days") are
    removed because they change without the guidelines changing.

    Everything else — crucially, all other numbers — is kept. An earlier version
    stripped every digit, which made a word limit going from 8000 to 3000, or a newly
    added reading fee, completely invisible to change detection. Those are precisely
    the edits a writer needs to know about.
    """
    t = text.lower()
    for pattern in _VOLATILE_PATTERNS:
        t = pattern.sub(" ", t)
    t = re.sub(r"[^a-z0-9$£€\s]+", " ", t)
    return " ".join(t.split())


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_for_fingerprint(text).encode("utf-8")).hexdigest()


def page_unchanged(norm: str, new_text: str, stored_fingerprint: str | None) -> bool:
    """True only if the page is byte-identical after chrome normalization.

    Deliberately an exact match rather than a similarity threshold. Page-level
    similarity cannot separate a critical one-token edit — "8000 words" becoming
    "3000 words" — from ordinary noise: in a page of a few hundred tokens both score
    above 99. Any threshold loose enough to absorb a rotating sidebar is also loose
    enough to swallow a changed word limit.

    So the bias is deliberately toward re-summarizing. A false "changed" costs one
    model call, and Gate 2 then keeps the committed prose byte-for-byte, so nothing
    churns. A false "unchanged" would silently serve stale guidelines for 90 days.
    """
    if not stored_fingerprint:
        return False
    return fingerprint(new_text) == stored_fingerprint


def details_changed(old: dict | None, new: dict | None) -> bool:
    """Compare only the fields a writer would act on."""
    old = old or {}
    new = new or {}
    return any(
        (old.get(f) or "").strip().lower() != (new.get(f) or "").strip().lower()
        for f in DETAIL_FIELDS
    )


# ---------------------------------------------------------------------------
# Fetch + summarize
# ---------------------------------------------------------------------------

def _journal_url(j: dict) -> str:
    return j.get("journal_url") or j.get("about_url") or j.get("submit_url") or ""


def _pick_follow_link(
    links: list[tuple[str, str]],
    already: set[str],
    hints: dict[str, int] | None = None,
) -> str | None:
    """Choose the most promising same-site link to try next."""
    hints = hints or _FOLLOW_HINTS
    best, best_score = None, 0
    for label, href in links:
        if href in already:
            continue
        haystack = f"{label} {href}".lower()
        score = sum(weight for hint, weight in hints.items() if hint in haystack)
        if score > best_score:
            best, best_score = href, score
    return best


def _gather_pages(start_url: str) -> tuple[str, list[str], str | None]:
    """Fetch the start URL, then chase whichever kind of evidence is still missing.

    Returns (combined text, urls fetched, error).

    Two things are worth learning and they usually live on different pages: the
    mechanics (limits, deadlines, fees) on a guidelines page, and the aesthetic (what
    the journal actually publishes) on an about page, masthead, or issue listing. A
    journal with no reachable guidelines page is still worth summarizing — knowing a
    magazine's sensibility is what shortlisting runs on — so this chases both rather
    than giving up when there are no guidelines.
    """
    first = fetch_page(start_url, max_chars=MAX_PAGE_CHARS)
    if not first.ok:
        return "", [], first.error

    texts = [first.text]
    used = [first.url]
    links = list(first.links)

    def add(url: str | None) -> bool:
        if not url:
            return False
        extra = fetch_page(url, max_chars=MAX_PAGE_CHARS)
        if not (extra.ok and extra.text):
            return False
        texts.append(extra.text)
        used.append(extra.url)
        links.extend(extra.links)
        return True

    if _looks_thin(first.text):
        add(_pick_follow_link(links, set(used), _FOLLOW_HINTS))

    # Separately: if nothing so far says what the journal is like, go find that.
    if not _has_aesthetic("\n\n".join(texts)) and len(used) <= MAX_PAGES_PER_JOURNAL:
        add(_pick_follow_link(links, set(used), _ABOUT_HINTS))

    return "\n\n".join(texts), used, None


# Phrases that actually appear on a submissions page. Calibrated against the real
# pages of ~15 journals: pages with 3+ of these carried usable guidelines (Craft 10,
# Reed 10, One Story 8, Paris Review 7), while the ones worth following a link from
# scored 0-2 (A Public Space 0 despite 4,785 chars, Ploughshares 0, Hobart 1).
_GUIDELINE_SIGNALS = (
    "word count", "words", "maximum", "up to", "no more than", "reading period",
    "simultaneous", "response time", "we accept", "we publish", "we are looking",
    "guidelines", "previously published", "reading fee", "submittable", "manuscript",
    "double-spaced", "cover letter", "do not submit", "query",
)
MIN_GUIDELINE_SIGNALS = 3


# Words that indicate the text says something about what the journal publishes,
# rather than only how to submit to it.
_AESTHETIC_SIGNALS = (
    "we publish", "we are looking", "we want", "we seek", "we love", "we're drawn",
    "we are drawn", "founded", "our mission", "editor", "issue", "features",
    "interested in", "aesthetic", "voice", "stories", "poems", "essays", "fiction",
    "nonfiction", "writers", "contributors", "review", "anthology",
)
MIN_AESTHETIC_SIGNALS = 4


def _has_aesthetic(text: str) -> bool:
    """Does the text reveal anything about the journal's character?

    A bare guidelines page ("send DOC files, 5000 words max, $3 fee") tells a writer
    how to submit but nothing about whether they should — so when this is false it is
    worth spending one more request on an about page.
    """
    low = text.lower()
    return sum(1 for s in _AESTHETIC_SIGNALS if s in low) >= MIN_AESTHETIC_SIGNALS


def _looks_thin(text: str) -> bool:
    """Does this page lack actual submission guidelines, so a link is worth following?

    Signals only, no length rule — length is useless in both directions: a long "about
    the magazine" page has no guidelines, while a terse page can carry every policy. An
    empty or JS-rendered fetch scores zero signals and is caught anyway.

    Biased toward following: a false positive costs one HTTP request, a false negative
    leaves a useless cached summary in place for 90 days.
    """
    low = text.lower()
    return sum(1 for s in _GUIDELINE_SIGNALS if s in low) < MIN_GUIDELINE_SIGNALS


def _extract_json(raw: str) -> dict:
    """Parse the model's JSON reply, tolerating a ``` fence.

    Mirrors the parsing already used by the story-card route rather than relying on
    output_config, which isn't a safe bet on the pinned anthropic version.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    # strict=False permits literal newlines and tabs inside string values. The model
    # occasionally emits them when a journal's own text is multi-line, and the default
    # strict parser rejects the whole object over one raw control character.
    return json.loads(cleaned[start : end + 1], strict=False)


def _is_fatal_api_error(exc: Exception) -> bool:
    """Will this error hit every remaining journal, or just this one?

    A run of several hundred journals should stop the moment the account is the
    problem — otherwise an exhausted credit balance means fetching a page and failing
    a call for each of the ~250 journals left, which wastes time and buries the real
    cause in a wall of per-journal errors.
    """
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    # Credit exhaustion arrives as a 400 about the credit balance, not a typed error.
    message = str(exc).lower()
    return any(s in message for s in ("credit balance", "billing", "quota", "insufficient"))


def _summarize(page_text: str, client: anthropic.Anthropic) -> dict:
    response = client.messages.create(
        model=MODEL,
        # Headroom for the aesthetic field, which the reframed prompt asks to be
        # specific and evidence-backed; a truncated reply is a parse failure, not a
        # short summary.
        max_tokens=1500,
        thinking=EXTRACTION_THINKING,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(page_text=page_text)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    parsed = _extract_json(text)
    summary = (parsed.get("summary") or "").strip()
    if not summary:
        raise ValueError("model returned an empty summary")
    details = parsed.get("details") or {}
    return {
        "summary": summary,
        "index_line": (parsed.get("index_line") or "").strip().replace("\n", " "),
        "found_guidelines": bool(parsed.get("found_guidelines", True)),
        "details": {f: (details.get(f) or "unknown").strip() for f in DETAIL_FIELDS},
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _has_url(j: dict) -> bool:
    return bool(_journal_url(j))


def missing_summaries(journals: list[dict]) -> list[dict]:
    """Return journals that have a URL but no cached summary yet."""
    cache = _load_cache()
    return [j for j in journals if _has_url(j) and j["normalized_name"] not in cache]


def no_url_count(journals: list[dict]) -> int:
    """Count journals that have no summary and no URL to build one from."""
    cache = _load_cache()
    return sum(1 for j in journals if not _has_url(j) and j["normalized_name"] not in cache)


def status_for(journals: list[dict]) -> dict:
    """Counts for the UI. The three buckets are disjoint and sum to total."""
    cache = _load_cache()
    cached = missing = no_url = 0
    for j in journals:
        if j["normalized_name"] in cache:
            cached += 1
        elif _has_url(j):
            missing += 1
        else:
            no_url += 1
    return {"total": len(journals), "cached": cached, "missing": missing, "no_url": no_url}


def get_summary(normalized_name: str) -> str | None:
    """Return cached summary for a journal, or None if not yet generated."""
    entry = _load_cache().get(normalized_name)
    return entry.get("summary") if entry else None


def load_summaries_for(journals: list[dict]) -> dict[str, str]:
    """Return {normalized_name: full summary} for journals that have one."""
    cache = _load_cache()
    return {
        j["normalized_name"]: cache[j["normalized_name"]]["summary"]
        for j in journals
        if j["normalized_name"] in cache and cache[j["normalized_name"]].get("summary")
    }


def load_index_lines_for(journals: list[dict]) -> dict[str, str]:
    """Return {normalized_name: one-line ranked-list entry} where one exists.

    Kept separate from load_summaries_for because the two are used differently: an
    index line is already written to length and must be used whole, while a summary
    is prose the agent trims. Merging them would let the sentence trimmer cut an
    index line at its first period.
    """
    cache = _load_cache()
    out = {}
    for j in journals:
        line = (cache.get(j["normalized_name"], {}).get("index_line") or "").strip()
        if line:
            out[j["normalized_name"]] = line
    return out


def needs_index_line(journals: list[dict]) -> list[dict]:
    """Cached journals whose entry has no purpose-written index line yet."""
    cache = _load_cache()
    return [
        j for j in journals
        if j["normalized_name"] in cache
        and not (cache[j["normalized_name"]].get("index_line") or "").strip()
    ]


def _write_index_line(entry: dict, client: anthropic.Anthropic) -> str:
    """Condense a cached entry into one scannable line. No network, no page fetch."""
    details = entry.get("details") or {}
    detail_text = "\n".join(f"  {k}: {v}" for k, v in details.items() if v and v != "unknown")
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        thinking=EXTRACTION_THINKING,
        messages=[{"role": "user", "content": INDEX_LINE_PROMPT.format(
            name=entry.get("name", ""),
            summary=entry.get("summary", ""),
            details=detail_text or "  (none recorded)",
            max_chars=INDEX_LINE_MAX_CHARS,
        )}],
    )
    line = "".join(b.text for b in response.content if b.type == "text").strip()
    line = line.strip('"').strip().replace("\n", " ")
    if not line:
        raise ValueError("model returned an empty index line")
    return line


def condense_entries(
    journals: list[dict],
    api_key: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> Generator[str, None, None]:
    """Add a one-line index entry to cached summaries.

    Runs over text already in the cache rather than re-fetching pages, so it costs a
    fraction of a full summarize pass and touches no journal's website.
    """
    cache = _load_cache()
    targets = [j for j in journals if j["normalized_name"] in cache]
    if not force:
        targets = [j for j in targets
                   if not (cache[j["normalized_name"]].get("index_line") or "").strip()]
    if not targets:
        yield "Every cached journal already has an index line."
        return

    client = None if dry_run else anthropic.Anthropic(api_key=api_key)
    written = failed = 0
    for i, j in enumerate(targets, 1):
        norm = j["normalized_name"]
        entry = cache[norm]
        prefix = f"[{i}/{len(targets)}]"
        if dry_run:
            yield f"{prefix} WOULD condense {entry.get('name', norm)}"
            continue
        try:
            line = _write_index_line(entry, client)
        except Exception as e:
            if _is_fatal_api_error(e):
                yield f"STOPPED — the API rejected the request: {e}"
                break
            failed += 1
            yield f"{prefix}   could not condense {entry.get('name', norm)}: {e}"
            continue
        entry["index_line"] = line[:INDEX_LINE_MAX_CHARS * 2]
        cache[norm] = entry
        _save_cache(cache)  # incremental, so an interrupted run keeps its work
        written += 1
        yield f"{prefix} {entry.get('name', norm)}: {line}"

    yield f"Finished — {written} index lines written, {failed} failed."


def load_urls_for(journals: list[dict]) -> dict[str, str]:
    """Return {normalized_name: best known URL} from the cache.

    This is the page a summary was actually built from, which beats the rankings
    cache's URL — that one is sometimes a contact page. Once a journal is summarized,
    the agent stops guessing at paths for it.
    """
    cache = _load_cache()
    out: dict[str, str] = {}
    for j in journals:
        entry = cache.get(j["normalized_name"])
        if not entry:
            continue
        pages = entry.get("pages") or []
        best = pages[-1] if pages else entry.get("url")
        if best:
            out[j["normalized_name"]] = best
    return out


def load_details_for(journals: list[dict]) -> dict[str, dict]:
    """Return {normalized_name: details dict} for journals with structured detail."""
    cache = _load_cache()
    return {
        j["normalized_name"]: cache[j["normalized_name"]]["details"]
        for j in journals
        if j["normalized_name"] in cache and cache[j["normalized_name"]].get("details")
    }


def format_details(normalized_name: str) -> str | None:
    """Render one journal's structured detail for the get_journal_details tool."""
    entry = _load_cache().get(normalized_name)
    if not entry:
        return None
    details = entry.get("details")
    if not details:
        return None
    label = {
        "aesthetic": "Aesthetic",
        "word_limit": "Word limit",
        "reading_period": "Reading period",
        "response_time": "Response time",
        "simultaneous_submissions": "Simultaneous submissions",
        "multiple_submissions": "Multiple submissions",
        "fee": "Fee",
        "red_flags": "Red flags",
    }
    lines = [f"{entry.get('name', normalized_name)} — cached guidelines detail:"]
    for f in DETAIL_FIELDS:
        lines.append(f"  {label[f]}: {details.get(f, 'unknown')}")
    pages = entry.get("pages") or ([entry["url"]] if entry.get("url") else [])
    if pages:
        lines.append(f"  Source: {', '.join(pages)}")
    if entry.get("fetched_at"):
        lines.append(f"  Cached: {entry['fetched_at'][:10]}")
    if entry.get("found_guidelines") is False:
        lines.append(
            "  NOTE: this entry describes the journal but no submission mechanics were "
            "cached. Use fetch_page on its site for word limits, reading periods, or fees."
        )
    return "\n".join(lines)


def _url_changed(entry: dict | None, journal: dict) -> bool:
    """Was this summary built from a different URL than the rankings now hold?

    A corrected journal_url makes the cached summary stale no matter how recently it
    was checked — it describes a page we are no longer pointing at. Without this,
    fixing a URL would leave the old summary in place for the rest of the 90-day
    recheck window.
    """
    if not entry:
        return False
    return (entry.get("url") or "") != _journal_url(journal)


def _due_for_recheck(norm: str, meta: dict) -> bool:
    """Gate 0: has enough time passed to bother re-fetching?"""
    checked = (meta.get(norm) or {}).get("checked_at")
    if not checked:
        return True
    try:
        when = datetime.fromisoformat(checked)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > timedelta(days=RECHECK_AFTER_DAYS)


def generate_summaries(
    journals: list[dict],
    api_key: str | None = None,
    force_refresh: bool = False,
    dry_run: bool = False,
) -> Generator[str, None, None]:
    """Generate or refresh summaries, yielding status strings for the UI.

    api_key is passed in rather than read from the environment so this works with a
    per-user key. force_refresh skips gates 0 and 1; dry_run walks those gates and
    reports what would change without spending any tokens.
    """
    cache = _load_cache()
    meta = _load_meta()
    client = None if dry_run else anthropic.Anthropic(api_key=api_key)

    candidates = [j for j in journals if _has_url(j)]
    skipped_no_url = len(journals) - len(candidates)
    if not force_refresh:
        # Unsummarized first, then by rank: a partial run should leave the list
        # more useful than it found it.
        candidates.sort(key=lambda j: (j["normalized_name"] in cache, j.get("rank") or 10**6))

    if not candidates:
        yield "Nothing to do — no journals with a URL."
        return

    if not force_refresh:
        # Gate 0 skips silently, so without this the progress index looks like the run
        # started over from journal 1 when it actually resumed.
        already = sum(
            1 for j in candidates
            if j["normalized_name"] in cache
            and not _due_for_recheck(j["normalized_name"], meta)
            and not _url_changed(cache.get(j["normalized_name"]), j)
        )
        if already:
            yield (
                f"Resuming — {already} already summarized and up to date, "
                f"{len(candidates) - already} to process."
            )

    generated = refreshed = unchanged = failed = 0
    fatal: str | None = None
    now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

    for i, journal in enumerate(candidates, 1):
        norm = journal["normalized_name"]
        name = journal.get("display_name") or journal.get("name", norm)
        entry = cache.get(norm)
        prefix = f"[{i}/{len(candidates)}]"

        # Gate 0 — no network.
        if (
            entry
            and not force_refresh
            and not _due_for_recheck(norm, meta)
            and not _url_changed(entry, journal)
        ):
            unchanged += 1
            continue

        yield f"{prefix} {name}..."
        text, pages, error = _gather_pages(_journal_url(journal))
        if error:
            failed += 1
            yield f"{prefix}   could not read {name}: {error}"
            continue

        stored_fp = (meta.get(norm) or {}).get("fingerprint")

        # Gate 1 — no tokens.
        if entry and not force_refresh and page_unchanged(norm, text, stored_fp):
            unchanged += 1
            if not dry_run:
                meta.setdefault(norm, {})["checked_at"] = now()
                _save_meta(meta)
                if _url_changed(entry, journal):
                    # A corrected URL that happens to serve the same page: record the
                    # new one so it stops looking stale on every future run. No model
                    # call — the prose is still accurate.
                    entry["url"] = pages[0] if pages else _journal_url(journal)
                    entry["pages"] = pages
                    cache[norm] = entry
                    _save_cache(cache)
                    _write_page_text(norm, text)
            yield f"{prefix}   unchanged"
            continue

        if dry_run:
            if entry:
                refreshed += 1
            else:
                generated += 1
            yield f"{prefix}   WOULD {'refresh' if entry else 'generate'}"
            continue

        try:
            result = _summarize(text, client)
        except Exception as e:
            if _is_fatal_api_error(e):
                fatal = str(e)
                break
            failed += 1
            yield f"{prefix}   could not summarize {name}: {e}"
            continue

        # Gate 2 — no cache churn. Keeping the prose byte-identical means the agent's
        # big cached prompt block survives a refresh run.
        if entry and not details_changed(entry.get("details"), result["details"]):
            unchanged += 1
            meta[norm] = {"checked_at": now(), "fingerprint": fingerprint(text)}
            _write_page_text(norm, text)
            _save_meta(meta)
            yield f"{prefix}   details unchanged — kept existing summary"
            continue

        cache[norm] = {
            "name": name,
            # .get, not []: a model reply can omit the field, and an entry without an
            # index line still works — the agent falls back to trimming the summary,
            # and --condense fills it in later.
            "index_line": result.get("index_line", ""),
            "summary": result["summary"],
            "found_guidelines": result["found_guidelines"],
            "details": result["details"],
            "pages": pages,
            "url": pages[0] if pages else _journal_url(journal),
            "fetched_at": now(),
            "revision": (entry.get("revision", 1) + 1) if entry else 1,
        }
        meta[norm] = {"checked_at": now(), "fingerprint": fingerprint(text)}
        _write_page_text(norm, text)
        # Saved every iteration so an interrupted run keeps its work.
        _save_cache(cache)
        _save_meta(meta)

        if entry:
            refreshed += 1
            yield f"{prefix}   refreshed"
        else:
            generated += 1
            yield f"{prefix}   done"

        if i < len(candidates):
            time.sleep(REQUEST_DELAY)

    if fatal:
        yield f"STOPPED — the API rejected the request: {fatal}"
        yield (
            "No further journals were attempted. Fix the account, then re-run the same "
            "command: everything already summarized is saved and will be skipped."
        )

    verb = "would generate" if dry_run else "generated"
    yield (
        f"Finished — {generated} {verb}, {refreshed} refreshed, {unchanged} unchanged, "
        f"{failed} failed, {skipped_no_url} skipped (no URL)."
    )
    if not dry_run and (generated or refreshed):
        no_mechanics = sum(
            1 for e in _load_cache().values() if e.get("found_guidelines") is False
        )
        if no_mechanics:
            # Not a failure: these entries describe the journal, they just don't carry
            # word limits or deadlines. The agent fetches those for its finalists.
            yield (
                f"{no_mechanics} journals are summarized but have no submission "
                "mechanics cached (no word limit, reading period, or fee found). The "
                "agent will read their guidelines page when it needs specifics."
            )
        yield (
            "data/journal_summaries.json changed — commit and push it to share these "
            "summaries with the deployed app."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    """Command-line entry point. A full fill takes ~an hour, so it belongs in a
    terminal rather than an SSE stream held open by a browser tab."""
    import argparse
    import sys

    # Journal names and the progress lines contain em-dashes and accented characters;
    # the default Windows console codepage mangles them. errors="replace" keeps a
    # stray character from ever taking down an hour-long run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(
        prog="summarize_journals",
        description="Generate cached journal guideline summaries.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all", action="store_true",
                        help="every ranked journal that has a URL")
    source.add_argument("--only", metavar="NAME", nargs="+",
                        help="one or more journals by normalized name")
    source.add_argument("--repair", action="store_true",
                        help="re-do only the journals whose cached entry found no "
                             "submission mechanics (implies --force)")
    source.add_argument("--condense", action="store_true",
                        help="write the one-line ranked-list entry for cached journals "
                             "that lack one. Uses the cached text only — no page fetches")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without spending tokens")
    parser.add_argument("--force", action="store_true",
                        help="ignore the recheck window and the unchanged-page check")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after N journals (useful for sampling)")
    args = parser.parse_args(argv)

    import os

    from dotenv import load_dotenv
    from scrape_rankings import load_rankings

    load_dotenv(DATA_DIR.parent / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("ANTHROPIC_API_KEY not set (put it in .env or the environment).")
        return 1

    rankings = [j for j in load_rankings() if j.get("journal_url")]

    if args.condense:
        targets = rankings if args.force else needs_index_line(rankings)
        if args.limit is not None:
            targets = targets[: args.limit]
        if not args.dry_run:
            # Input is one cached summary, not a fetched page, so this is roughly a
            # tenth the cost of re-summarizing.
            print(f"{len(targets)} journals to condense, roughly "
                  f"${len(targets) * 0.0014:.2f}. Ctrl-C is safe.\n")
        try:
            for line in condense_entries(
                targets, api_key=api_key, force=args.force, dry_run=args.dry_run
            ):
                print(line, flush=True)
        except KeyboardInterrupt:
            print("\nStopped. Lines written so far are saved; re-run to continue.")
            return 130
        return 0

    if args.repair:
        cache = _load_cache()
        journals = [
            j for j in rankings
            if (cache.get(j["normalized_name"]) or {}).get("found_guidelines") is False
        ]
        args.force = True  # they're already cached; without this Gate 0 skips them
        if not journals:
            print("Nothing to repair — every cached entry found submission mechanics.")
            return 0
    elif args.only:
        wanted = {n.lower() for n in args.only}
        journals = [j for j in rankings if j["normalized_name"].lower() in wanted]
        missing = wanted - {j["normalized_name"].lower() for j in journals}
        if missing:
            print(f"Not found in rankings: {', '.join(sorted(missing))}")
        if not journals:
            return 1
    else:
        journals = rankings

    # `is not None`, not truthiness: --limit 0 must mean zero, not "unset".
    if args.limit is not None:
        journals = journals[: args.limit]

    status = status_for(journals)
    print(f"{len(journals)} journals — {status['cached']} cached, {status['missing']} missing")
    if not args.dry_run:
        # Existing entries predate structured details, so a plain --all refreshes them
        # too; make the real number of model calls explicit before it starts spending.
        calls = status["cached"] + status["missing"] if args.force else len(journals)
        print(f"Up to {calls} model calls, roughly ${calls * 0.0126:.2f}. Ctrl-C is safe — "
              f"progress is saved after each journal.\n")

    try:
        for line in generate_summaries(
            journals, api_key=api_key, force_refresh=args.force, dry_run=args.dry_run
        ):
            print(line, flush=True)
    except KeyboardInterrupt:
        print("\nStopped. Everything summarized so far is saved; re-run to continue.")
        return 130
    return 0


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).parent))
    raise SystemExit(_main())
