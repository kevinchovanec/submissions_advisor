"""Collapsing one journal pasted under several spellings.

Pasting from Duotrope and The Submission Grinder lists the same journal twice, and
both spellings resolve to one ranked entry with one normalized_name. The Matcher
then had two rows it couldn't tell apart, and Reject removed the wrong ones.
"""

from __future__ import annotations

from ingest import normalize_name
from match import collapse_duplicates, match, ranked_only

RANKINGS = [
    {"rank": 1, "name": "Georgia Review, The", "normalized_name": normalize_name("Georgia Review, The")},
    {"rank": 2, "name": "Ploughshares", "normalized_name": normalize_name("Ploughshares")},
]


def _pasted(*names: str) -> list[dict]:
    return [{"display_name": n, "normalized_name": normalize_name(n)} for n in names]


def test_confident_spellings_collapse_to_one_row():
    matched = ranked_only(match(_pasted("Ploughshare", "Georgia Review, The", "Ploughshares"), RANKINGS))
    rows = collapse_duplicates(matched)
    assert [r["display_name"] for r in rows] == ["Georgia Review, The", "Ploughshares"]


def test_low_confidence_spelling_stays_reviewable():
    # 87.5 against "Georgia Review, The": probably the same journal, but not certain.
    matched = ranked_only(match(_pasted("Georgia Review", "Georgia Review, The"), RANKINGS))
    assert len(collapse_duplicates(matched)) == 2


def test_keeps_highest_confidence_and_low_confidence_duplicates():
    rows = collapse_duplicates([
        {"display_name": "Georgia Revue", "normalized_name": "georgia review", "match_confidence": 88.0},
        {"display_name": "Georgia Review", "normalized_name": "georgia review", "match_confidence": 100.0},
        {"display_name": "Georgia Reviews", "normalized_name": "georgia review", "match_confidence": 97.0},
    ])
    # The exact match wins; the 97 is the same journal and goes; the 88 might be a
    # different journal entirely, so it stays where the writer can reject it.
    assert [r["display_name"] for r in rows] == ["Georgia Revue", "Georgia Review"]
