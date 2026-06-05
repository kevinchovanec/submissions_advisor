"""
Finds missing journal URLs via DuckDuckGo and writes them back
into the rankings cache so they're available for summary generation.
"""

import json
import time
from pathlib import Path
from typing import Generator

from ddgs import DDGS

RANKINGS_CACHE = Path(__file__).parent.parent / "data" / "rankings_cache.json"
REQUEST_DELAY = 1.0


def _search(query: str) -> str | None:
    """Return the first non-Wikipedia DuckDuckGo result URL, or None on failure."""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    for r in results:
        if "wikipedia.org" not in r["href"]:
            return r["href"]
    return None


def find_missing_urls(journals: list[dict]) -> Generator[str, None, None]:
    """
    For each journal with no URL, search DuckDuckGo for its website and update
    the rankings cache. Yields status strings for the UI.
    """
    if not RANKINGS_CACHE.exists():
        yield "Rankings cache not found — refresh rankings first."
        return

    with open(RANKINGS_CACHE, encoding="utf-8") as f:
        rankings = json.load(f)

    rankings_by_norm = {r["normalized_name"]: r for r in rankings}

    no_url = [
        j for j in journals
        if not (j.get("journal_url") or j.get("about_url") or j.get("submit_url"))
    ]

    if not no_url:
        yield "All journals already have URLs."
        return

    found = 0
    for i, journal in enumerate(no_url, 1):
        name = journal.get("display_name") or journal.get("name", "")
        yield f"Searching for {name} ({i}/{len(no_url)})..."

        try:
            query = f'{name} literary journal submissions'
            url = _search(query)
            if url:
                norm = journal["normalized_name"]
                if norm in rankings_by_norm:
                    rankings_by_norm[norm]["journal_url"] = url
                found += 1
                yield f"  Found: {url}"
            else:
                yield f"  No result found."
        except Exception as e:
            yield f"  Error: {e}"

        if i < len(no_url):
            time.sleep(REQUEST_DELAY)

    with open(RANKINGS_CACHE, "w", encoding="utf-8") as f:
        json.dump(rankings, f, indent=2, ensure_ascii=False)

    yield f"Done — found URLs for {found}/{len(no_url)} journals. Refresh rankings to apply."
