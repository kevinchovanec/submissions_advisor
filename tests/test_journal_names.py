"""One display name per journal, whatever spelling the writer typed.

"Dr. T. J. Eckleburg Review", "T J Eckleburg Review" and "Eckleburg" all showed up
as separate journals in Notes and the Tracker. They resolve to the ranked spelling
for display; the stored name is left alone so edits still find the submission.
"""

from __future__ import annotations

import pytest

import match
from ingest import normalize_name
from journal_names import JournalNameResolver
from match import match as run_match
from scrape_rankings import _strip_markers, load_rankings

RANKED = ["Dr. T.J. Eckleburg Review", "Paris Review, The", "*Joyland", "Southern Review", "*The Boiler"]
# As load_rankings serves them: the source's asterisks stripped from the name, the
# stored key left as the scraper normalized it - with the asterisk still on.
RANKINGS = [
    {"rank": i + 1, "name": _strip_markers(n), "normalized_name": normalize_name(n)}
    for i, n in enumerate(RANKED)
]


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    overrides = tmp_path / "manual_overrides.csv"
    overrides.write_text("duotrope_name,krouse_name\nEckleburg,Dr. T.J. Eckleburg Review\n", encoding="utf-8")
    monkeypatch.setattr(match, "OVERRIDES_PATH", overrides)
    return JournalNameResolver(RANKINGS)


@pytest.mark.parametrize("typed", [
    "Dr. T. J. Eckleburg Review",   # initials spaced differently
    "Dr. T.J. Eckleburg Review",    # exact
    "Eckleburg",                    # override, written un-normalized
])
def test_spellings_resolve_to_ranked_name(resolver, typed):
    assert resolver.display(typed) == "Dr. T.J. Eckleburg Review"


def test_leading_the_and_markers_resolve(resolver):
    assert resolver.display("Paris Review, The") == "Paris Review, The"
    assert resolver.display("Joyland") == "Joyland"
    # Keyed "the boiler" because the asterisk hid the leading "The" from normalize_name.
    assert resolver.display("The Boiler") == "The Boiler"
    assert resolver.display("Boiler") == "The Boiler"


def test_matcher_finds_journal_whose_key_kept_its_the(resolver):
    [hit] = run_match([{"display_name": "The Boiler", "normalized_name": normalize_name("The Boiler")}], RANKINGS)
    assert hit["matched_name"] == "The Boiler"
    assert hit["match_confidence"] == 100.0
    assert hit["normalized_name"] == "the boiler"  # the key the summary cache uses


def test_shipped_rankings_have_no_asterisks():
    assert not [r["name"] for r in load_rankings() if "*" in r["name"]]


def test_unranked_and_uncertain_names_are_left_as_typed(resolver):
    assert resolver.display("Some Tiny Zine") == "Some Tiny Zine"
    # Shares a word with a ranked journal but isn't one; a wrong guess would relabel history.
    assert resolver.display("Southern Humanities Review") == "Southern Humanities Review"
    assert resolver.display("") == ""
