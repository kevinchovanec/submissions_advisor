"""
Generates and caches brief summaries of journal guidelines pages.
Summaries are stored in data/journal_summaries.json, keyed by normalized_name.
Generated incrementally — only missing journals are fetched and summarized.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import anthropic
import requests
from bs4 import BeautifulSoup

MODEL = "claude-sonnet-4-6"
SUMMARIES_PATH = Path(__file__).parent.parent / "data" / "journal_summaries.json"
MAX_PAGE_CHARS = 4000
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.5

SUMMARY_PROMPT = """You are summarizing a literary journal's submission guidelines for a writer.
Read the page content below and write a summary of exactly 3 sentences covering:
1. The journal's aesthetic focus — what kind of writing, voice, or themes they tend to publish
2. Practical limits — word count range, reading periods, response time if mentioned
3. Any notable restrictions, preferences, or red flags a writer should know

Be specific and direct. If the page doesn't have useful guidelines content, say so briefly.

Page content:
{page_text}"""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if SUMMARIES_PATH.exists():
        with open(SUMMARIES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    SUMMARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARIES_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Fetch + summarize
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> str:
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "submissions-advisor/1.0"},
        allow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())[:MAX_PAGE_CHARS]


def _generate_summary(page_text: str, client: anthropic.Anthropic) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": SUMMARY_PROMPT.format(page_text=page_text),
        }],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _has_url(j: dict) -> bool:
    return bool(j.get("journal_url") or j.get("about_url") or j.get("submit_url"))


def missing_summaries(journals: list[dict]) -> list[dict]:
    """Return journals that have a URL but no cached summary yet."""
    cache = _load_cache()
    return [j for j in journals if _has_url(j) and j["normalized_name"] not in cache]


def no_url_count(journals: list[dict]) -> int:
    """Return count of journals that can't be summarized due to missing URL."""
    cache = _load_cache()
    return sum(1 for j in journals if not _has_url(j) and j["normalized_name"] not in cache)


def get_summary(normalized_name: str) -> str | None:
    """Return cached summary for a journal, or None if not yet generated."""
    cache = _load_cache()
    entry = cache.get(normalized_name)
    return entry["summary"] if entry else None


def generate_summaries(
    journals: list[dict],
    force_refresh: bool = False,
) -> Generator[str, None, None]:
    """
    Generate summaries for journals that don't have one yet.
    Yields status strings for display in the UI.
    Skips journals with no URL.
    """
    cache = _load_cache()
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    to_process = [
        j for j in journals
        if (force_refresh or j["normalized_name"] not in cache)
        and (j.get("journal_url") or j.get("about_url") or j.get("submit_url"))
    ]

    if not to_process:
        yield "All summaries up to date."
        return

    updated = 0
    for i, journal in enumerate(to_process, 1):
        name = journal.get("display_name") or journal.get("name", "")
        url = journal.get("journal_url") or journal.get("about_url") or journal.get("submit_url")
        yield f"Summarizing {name} ({i}/{len(to_process)})..."

        try:
            page_text = _fetch_page(url)
            summary = _generate_summary(page_text, client)
            cache[journal["normalized_name"]] = {
                "name": name,
                "summary": summary,
                "url": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            updated += 1
        except Exception as e:
            yield f"  Could not summarize {name}: {e}"

        if i < len(to_process):
            time.sleep(REQUEST_DELAY)

    _save_cache(cache)
    yield f"Done — {updated} summaries generated."


def load_summaries_for(journals: list[dict]) -> dict[str, str]:
    """Return {normalized_name: summary} for all journals that have one."""
    cache = _load_cache()
    return {
        j["normalized_name"]: cache[j["normalized_name"]]["summary"]
        for j in journals
        if j["normalized_name"] in cache
    }
