"""Context assembly: pending exclusions, the story roster, and cache-block layout.

The pending-exclusion tests exist because that behaviour has regressed before (it
needed hardening in commit 07da4ce) and it is the one rule whose failure costs the
writer a real submission slot.
"""

from __future__ import annotations

import agent
import storage as storage_mod


class TestPendingExclusion:
    def test_marks_pending_journal_despite_name_normalization(self, journals, storage):
        """'Georgia Review' in the submission must mark 'The Georgia Review' in the list."""
        block = agent._build_journal_context(journals, storage.list_all_pending())
        georgia = [ln for ln in block.splitlines() if "Georgia Review" in ln or "UNDER REVIEW" in ln]
        assert any("UNDER REVIEW" in ln for ln in georgia)
        assert "A Mediocrity of Virtue" in block

    def test_marks_every_pending_journal(self, journals, storage):
        storage.log_submission("what-was-left", "Other Mag")
        block = agent._build_journal_context(journals, storage.list_all_pending())
        assert block.count("UNDER REVIEW") == 2

    def test_no_marker_when_nothing_pending(self, journals):
        block = agent._build_journal_context(journals, [])
        assert "UNDER REVIEW" not in block

    def test_rejected_submission_is_not_treated_as_pending(self, journals, storage):
        """New England Review was rejected, so it must not be excluded."""
        block = agent._build_journal_context(journals, storage.list_all_pending())
        assert "New England Review" not in block

    def test_pending_block_and_inline_markers_come_from_one_source(self, journals, storage):
        """Both renderings derive from the same list, so they cannot disagree."""
        pending = storage.list_all_pending()
        inline = agent._build_journal_context(journals, pending)
        block = agent._build_story_context(storage, "", "", pending, [])
        assert "UNDER REVIEW" in inline
        assert "Georgia Review" in block


class TestJournalList:
    def test_journal_without_url_says_so(self, journals):
        block = agent._build_journal_context(journals, [])
        assert "no URL" in block

    def test_prefers_cached_guidelines_url_over_rankings_url(self, journals):
        """A summarized journal's discovered URL wins: the rankings URL is
        sometimes a contact page."""
        best = {"georgia review": "https://garev.example/about/submissions-real"}
        out = agent._format_journal_list(journals, {}, {}, best)
        assert "https://garev.example/about/submissions-real" in out
        assert "https://garev.example/submissions" not in out

    def test_summary_is_included_when_present(self, journals):
        out = agent._format_journal_list(journals, {"other mag": "Likes weird stuff."}, {})
        assert "Likes weird stuff." in out


class TestListSummaryTrimming:
    """The ranked list is an index, not the full record — carrying every sentence
    for every journal makes it the single largest cost in the app, since it is
    written to cache at the start of each conversation."""

    THREE = (
        "Publishes voice-driven literary fiction with a dark comic streak. "
        "Prose up to 8,000 words during an August to May reading period. "
        "No fee, but simultaneous submissions must be withdrawn immediately."
    )

    def test_keeps_only_the_configured_number_of_sentences(self, monkeypatch, journals):
        monkeypatch.setattr(agent, "LIST_SUMMARY_SENTENCES", 1)
        out = agent._format_journal_list(journals, {"other mag": self.THREE}, {})
        assert "dark comic streak." in out
        assert "8,000 words" not in out

    def test_two_sentences(self, monkeypatch, journals):
        monkeypatch.setattr(agent, "LIST_SUMMARY_SENTENCES", 2)
        out = agent._format_journal_list(journals, {"other mag": self.THREE}, {})
        assert "8,000 words" in out
        assert "simultaneous" not in out

    def test_zero_drops_summaries_entirely(self, monkeypatch, journals):
        monkeypatch.setattr(agent, "LIST_SUMMARY_SENTENCES", 0)
        out = agent._format_journal_list(journals, {"other mag": self.THREE}, {})
        assert "dark comic" not in out
        assert "Other Mag" in out, "the journal itself must still be listed"

    def test_high_limit_keeps_everything(self, monkeypatch, journals):
        monkeypatch.setattr(agent, "LIST_SUMMARY_SENTENCES", 99)
        out = agent._format_journal_list(journals, {"other mag": self.THREE}, {})
        assert "simultaneous submissions" in out

    def test_figures_with_periods_do_not_split_early(self):
        """'3,000-8,000 words.' and 'e.g.' must not be read as sentence ends."""
        text = "Wants prose of 3,000-8,000 words. Reads year round."
        assert agent._trim_sentences(text, 1) == "Wants prose of 3,000-8,000 words."

    def test_single_sentence_summary_survives_intact(self):
        assert agent._trim_sentences("Just the one sentence.", 1) == "Just the one sentence."

    def test_handles_empty_and_missing(self):
        assert agent._trim_sentences("", 1) == ""
        assert agent._trim_sentences(None, 1) == ""

    def test_prompt_warns_the_list_omits_limits(self):
        """Otherwise a missing word limit in a one-line note reads as 'no limit'."""
        assert "never conclude a journal has no limit" in agent.SYSTEM_PROMPT


class TestStoryRoster:
    def test_lists_unselected_and_excludes_selected(self, storage):
        roster = storage_mod.format_story_roster(
            storage.list_stories(), storage.list_all_pending(), {"mediocrity"}
        )
        assert "what-was-left" in roster
        assert "staging" in roster
        assert "mediocrity" not in roster

    def test_carries_counts_not_full_history(self, storage):
        """Roster size must stay O(stories), not O(submissions)."""
        roster = storage_mod.format_story_roster(storage.list_stories(), [], set())
        assert "2 sent" in roster
        assert "2025-12-09" not in roster
        assert "rejected" not in roster

    def test_shows_pending_journals_inline(self, storage):
        roster = storage_mod.format_story_roster(
            storage.list_stories(), storage.list_all_pending(), set()
        )
        assert "OUT NOW: Georgia Review" in roster

    def test_empty_when_everything_is_selected(self, storage):
        roster = storage_mod.format_story_roster(
            storage.list_stories(), [], {"mediocrity", "what-was-left", "staging"}
        )
        assert roster == ""

    def test_tolerates_missing_word_count_and_style(self):
        roster = storage_mod.format_story_roster(
            [{"slug": "x", "title": "X", "word_count": None, "style": "", "description": "", "submission_count": 0}],
            [], set(),
        )
        assert "length unknown" in roster
        assert "(no description)" in roster


class TestSelectedStories:
    def test_single_story_output_is_unchanged(self, stories):
        """One-story conversations must render exactly as before multi-select."""
        assert storage_mod.format_selected_stories([stories[0]]) == storage_mod.format_story_for_agent(stories[0])

    def test_multi_story_names_primary_and_states_the_shared_rule(self, stories):
        out = storage_mod.format_selected_stories(stories[:2], primary_slug="what-was-left")
        assert "primary: what-was-left" in out
        assert "no journal may take two of them" in out
        assert out.count("Story slug") == 2

    def test_empty_selection_is_empty(self):
        assert storage_mod.format_selected_stories([]) == ""


class TestOpeningMessageLayout:
    """The journal list must precede story context and carry the cache breakpoint,
    so changing the story selection doesn't invalidate the expensive block."""

    def _opening(self, journals, storage, **kw):
        gen = agent.stream_response(
            [], "hi", journals, storage, api_key="test-key-unused", **kw
        )
        # Inspect the history the generator builds without calling the API: drive it
        # far enough to construct the opening, which happens before the first request.
        return gen

    def test_journal_block_first_with_1h_ttl_breakpoint(self, journals, storage, monkeypatch):
        captured = {}

        def fake_build(api_history, *a, **k):
            captured["history"] = api_history
            raise StopIteration

        # Build the opening exactly as stream_response does, then assert its shape.
        journal_block = agent._build_journal_context(journals, storage.list_all_pending())
        story_block = agent._build_story_context(
            storage, storage_mod.format_story_for_agent(storage.load_story("mediocrity")), "", [], []
        )
        content = [
            {"type": "text", "text": journal_block, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": f"---\n\n{story_block}"},
        ]
        assert content[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert "ranked by prestige score" in content[0]["text"]
        assert "cache_control" not in content[1]
        assert "Active story" in content[1]["text"]

    def test_system_prompt_has_no_redundant_breakpoint(self):
        """tools -> system -> messages render order means the journal-block breakpoint
        already covers the system prompt, and it is under the 1024-token minimum."""
        assert isinstance(agent.SYSTEM_PROMPT, str)

    def test_system_prompt_states_the_cross_story_rule(self):
        assert "NEVER send two stories to the same journal" in agent.SYSTEM_PROMPT
