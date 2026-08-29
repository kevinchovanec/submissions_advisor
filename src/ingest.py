"""
Duotrope data ingest. Accepts a CSV file path or raw HTML string copied from
Duotrope search results and returns a normalized list of journal dicts.
"""

import csv
import re
import sys
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^the\s+", "", name)
    name = re.sub(r"&", "and", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _parse_deadline(raw: str) -> str:
    raw = raw.strip()
    if not raw or raw.lower() in ("rolling", "ongoing", "open", ""):
        return "rolling"
    # Try common date formats
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw  # return as-is if unparseable


def _parse_response_days(raw: str) -> Optional[int]:
    raw = raw.strip()
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# CSV ingest
# ---------------------------------------------------------------------------

# Map flexible column name variants to canonical field names.
_COLUMN_MAP = {
    "name": "display_name",
    "journal": "display_name",
    "journal name": "display_name",
    "publication": "display_name",
    "deadline": "deadline",
    "closes": "deadline",
    "close date": "deadline",
    "response": "response_days",
    "response time": "response_days",
    "avg response": "response_days",
    "submit url": "submit_url",
    "submission url": "submit_url",
    "url": "submit_url",
    "link": "submit_url",
    "pay": "pay_rate",
    "pay rate": "pay_rate",
    "payment": "pay_rate",
}


def _map_header(raw_header: str) -> str:
    return _COLUMN_MAP.get(raw_header.lower().strip(), raw_header.lower().strip())


def _row_to_journal(row: dict) -> dict:
    display_name = row.get("display_name", "").strip()
    return {
        "display_name": display_name,
        "normalized_name": normalize_name(display_name),
        "deadline": _parse_deadline(row.get("deadline", "")),
        "response_days": _parse_response_days(row.get("response_days", "")),
        "submit_url": row.get("submit_url", "").strip(),
        "pay_rate": row.get("pay_rate", "").strip(),
    }


def from_csv(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Duotrope CSV not found: {path}")

    journals = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        mapped_fields = {field: _map_header(field) for field in reader.fieldnames}
        for raw_row in reader:
            row = {mapped_fields[k]: v for k, v in raw_row.items()}
            if row.get("display_name"):
                journals.append(_row_to_journal(row))
    return journals


# ---------------------------------------------------------------------------
# HTML ingest (copy-paste from Duotrope results table)
# ---------------------------------------------------------------------------

def from_html(html: str) -> list[dict]:
    if not _BS4_AVAILABLE:
        raise ImportError("beautifulsoup4 is required for HTML parsing: pip install beautifulsoup4")

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("No <table> found in the provided HTML.")

    headers = [_map_header(th.get_text()) for th in table.find_all("th")]
    if not headers:
        # Try first row as header
        first_row = table.find("tr")
        headers = [_map_header(td.get_text()) for td in first_row.find_all(["td", "th"])]

    journals = []
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        row = dict(zip(headers, cells))
        # Pull href from submit link if present
        link_tags = tr.find_all("a")
        for a in link_tags:
            href = a.get("href", "")
            if href.startswith("http") and "submit_url" not in row:
                row["submit_url"] = href
        if row.get("display_name"):
            journals.append(_row_to_journal(row))
    return journals


# ---------------------------------------------------------------------------
# Plain-text (tab-separated) ingest — copy-paste from Duotrope results
# ---------------------------------------------------------------------------

def _make_journal(name: str) -> dict:
    name = name.strip()
    return {
        "display_name": name,
        "normalized_name": normalize_name(name),
        "deadline": "rolling",
        "response_days": None,
        "submit_url": "",
        "pay_rate": "",
    }


# A market's status, on its own line, is how The Submission Grinder separates one
# record from the next. Duotrope pastes contain none of these, so keying on them
# costs nothing there.
_STATUS_LINES = frozenset({
    "open", "closed", "temporarily closed", "permanently closed", "opening soon",
    "closing soon", "sporadic", "hiatus", "on hiatus", "by invitation only",
    "invitation only", "reprints only", "unknown", "dead",
})

_HEADER_LINES = frozenset({
    "title", "name", "journal", "market", "genres", "genre", "lengths", "length",
    "payment", "media", "response", "status",
})


def from_text(text: str) -> list[dict]:
    """Parse plain tab-separated text pasted from a submissions database.

    Duotrope puts one market per line with the title first, so the first column is
    the name. The Submission Grinder spreads each market over three lines:

        Sheltering Tree Media
        Open
        GeneralMystery/CrimeYoung Adult<TAB>Novel<TAB>Unknown<TAB>...

    Reading the first column of every line turned that into three journals — the
    real one, a market called "Open", and one called "GeneralMystery/CrimeYoung
    Adult". The status line is the anchor: when one appears, it and the metadata row
    that follows it both belong to the market named on the line before.
    """
    journals = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        name = lines[i].split("\t")[0].strip()
        i += 1
        if not name:
            continue
        lowered = name.lower()
        if lowered in _HEADER_LINES:
            continue
        if lowered in _STATUS_LINES:
            # Skip the status itself and the metadata row belonging to the market
            # named on the previous line, which is already recorded.
            i += 1
            continue
        journals.append(_make_journal(name))
    return journals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load(source: str) -> list[dict]:
    """Load from a CSV path, HTML string, or tab-separated plain text."""
    p = Path(source)
    if p.exists() and p.suffix.lower() == ".csv":
        return from_csv(p)
    if "<" in source and ">" in source:
        return from_html(source)
    return from_text(source)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <duotrope_export.csv>")
        sys.exit(1)

    journals = load(sys.argv[1])
    print(f"Loaded {len(journals)} journals")
    for j in journals[:5]:
        print(j)
