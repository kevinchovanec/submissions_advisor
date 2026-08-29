"""Parsing pasted market lists.

The two sources differ in shape: Duotrope puts one market per line, The Submission
Grinder spreads each over three. Reading the first column of every line worked for
the first and produced three journals per market for the second — the real one, a
market called "Open", and one called "GeneralMystery/CrimeYoung Adult".
"""

from __future__ import annotations

from ingest import from_text, normalize_name

# Verbatim from a Submission Grinder results page.
GRINDER = (
    "Sheltering Tree Media\t\n"
    "Open\n"
    "GeneralMystery/CrimeYoung AdultChildrenMiddle Grade\tNovel\tUnknown\tNo Data\t"
    "No Limited Demographic (anyone may submit)\tYou must log in to make private notes about a market.\t\n"
    "! Exclamation Mark\t\n"
    "Open\n"
    "General\tFlashShort Story\t0\t0 days\tNo Limited Demographic (anyone may submit)\t"
    "You must log in to make private notes about a market.\t\n"
    "100 Word Project\t\n"
    "Open\n"
    "General\tFlash\t1\t16 days\tNo Limited Demographic (anyone may submit)\t"
    "You must log in to make private notes about a market.\t\n"
    "3Elements Review\t\n"
    "Open\n"
    "GeneralLiterary\tFlashShort Story\t0\t4 days\tNo Limited Demographic (anyone may submit)\t"
    "You must log in to make private notes about a market.\t\n"
    "4LPH4NUM3R1C (ALPHANUMERIC)\t\n"
    "Open\n"
    "General\tFlashShort Story\t1\t23 days\tNo Limited Demographic (anyone may submit)\t"
    "You must log in to make private notes about a market.\t\n"
)

DUOTROPE = (
    "Title\tGenre\tResponse\n"
    "The Georgia Review\tLiterary\t45 days\n"
    "Ploughshares\tLiterary\t60 days\n"
    "One Story\tFiction\t30 days\n"
)


class TestSubmissionGrinder:
    def test_one_journal_per_market(self):
        assert len(from_text(GRINDER)) == 5

    def test_names_are_the_markets(self):
        assert [j["display_name"] for j in from_text(GRINDER)] == [
            "Sheltering Tree Media",
            "! Exclamation Mark",
            "100 Word Project",
            "3Elements Review",
            "4LPH4NUM3R1C (ALPHANUMERIC)",
        ]

    def test_genre_blob_is_not_a_journal(self):
        names = [j["display_name"] for j in from_text(GRINDER)]
        assert not any(n.startswith("General") for n in names)

    def test_status_is_not_a_journal(self):
        assert "Open" not in [j["display_name"] for j in from_text(GRINDER)]

    def test_awkward_names_survive(self):
        """A filter aggressive enough to drop the genre blob would eat these."""
        names = [j["display_name"] for j in from_text(GRINDER)]
        for odd in ("! Exclamation Mark", "100 Word Project", "4LPH4NUM3R1C (ALPHANUMERIC)"):
            assert odd in names

    def test_other_statuses_are_handled(self):
        text = (
            "Alpha Review\t\nClosed\nGeneral\tShort Story\t0\t1 day\t\n"
            "Beta Quarterly\t\nTemporarily Closed\nLiterary\tFlash\t0\t2 days\t\n"
            "Gamma Journal\t\nOpening Soon\nGeneral\tNovel\t0\t3 days\t\n"
        )
        assert [j["display_name"] for j in from_text(text)] == [
            "Alpha Review", "Beta Quarterly", "Gamma Journal",
        ]


class TestDuotrope:
    def test_one_line_per_market_still_parses(self):
        assert [j["display_name"] for j in from_text(DUOTROPE)] == [
            "The Georgia Review", "Ploughshares", "One Story",
        ]

    def test_header_row_is_skipped(self):
        assert "Title" not in [j["display_name"] for j in from_text(DUOTROPE)]

    def test_extra_columns_are_ignored(self):
        assert "Literary" not in [j["display_name"] for j in from_text(DUOTROPE)]


class TestGeneral:
    def test_blank_lines_are_skipped(self):
        assert len(from_text("Alpha\n\n\nBeta\n")) == 2

    def test_empty_input(self):
        assert from_text("") == []

    def test_normalized_name_is_populated(self):
        j = from_text("The Georgia Review\n")[0]
        assert j["normalized_name"] == normalize_name("The Georgia Review")

    def test_trailing_tabs_do_not_leak_into_the_name(self):
        assert from_text("Sheltering Tree Media\t\n")[0]["display_name"] == "Sheltering Tree Media"

    def test_a_paste_starting_mid_record_does_not_crash(self):
        """A partial copy can begin on a status line."""
        text = "Open\nGeneral\tFlash\t0\t1 day\t\nReal Journal\t\nOpen\nGeneral\tFlash\t0\t2 days\t\n"
        assert [j["display_name"] for j in from_text(text)] == ["Real Journal"]
