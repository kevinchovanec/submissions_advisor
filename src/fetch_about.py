"""
Fetches about/guidelines pages for matched journals and caches results.
Cache lives at data/about_pages_cache.json, keyed by normalized_name.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CACHE_PATH = Path(__file__).parent.parent / "data" / "about_pages_cache.json"
REQUEST_DELAY = 1.0  # polite delay between requests (seconds)
ABOUT_TEXT_MAX_CHARS = 2000
TIMEOUT = 10


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> tuple[str, str]:
    """Returns (resolved_url, extracted_text). Follows redirects."""
    resp = requests.get(
        url,
        timeout=TIMEOUT,
        headers={"User-Agent": "submissions-advisor/1.0"},
        allow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = " ".join(text.split())[:ABOUT_TEXT_MAX_CHARS]
    return resp.url, text


def _find_about_url(submit_url: str) -> str | None:
    """
    Try to find an about/guidelines page from the journal's submit URL.
    Many journals use Submittable or Duosuma — we use the submit URL as-is
    since it typically lands on the guidelines page.
    """
    if not submit_url:
        return None
    return submit_url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_about_pages(journals: list[dict], force_refresh: bool = False) -> list[dict]:
    """
    For each journal with a submit_url, fetch and cache the about/guidelines page.
    Returns journals list with about_url and about_text fields added.
    """
    cache = _load_cache()
    updated = False
    results = []
    total = len([j for j in journals if j.get("submit_url")])
    fetched = 0

    for journal in journals:
        norm = journal["normalized_name"]
        entry = dict(journal)

        if not journal.get("submit_url"):
            entry.update({"about_url": None, "about_text": None})
            results.append(entry)
            continue

        if not force_refresh and norm in cache:
            cached = cache[norm]
            entry.update({"about_url": cached["about_url"], "about_text": cached["about_text"]})
            results.append(entry)
            continue

        url = _find_about_url(journal["submit_url"])
        try:
            fetched += 1
            print(f"  [{fetched}/{total}] Fetching {journal['display_name']}...", flush=True)
            resolved_url, text = _fetch_page(url)
            cache[norm] = {
                "about_url": resolved_url,
                "about_text": text,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            entry.update({"about_url": resolved_url, "about_text": text})
            updated = True
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    Warning: could not fetch {url}: {e}")
            entry.update({"about_url": url, "about_text": None})

        results.append(entry)

    if updated:
        _save_cache(cache)
        print(f"About page cache updated: {CACHE_PATH}")

    return results
