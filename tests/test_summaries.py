"""The refresh gates.

Gate 2 is the subtle one: when a page changed but the extracted fields did not, the
stored prose must be preserved byte-for-byte, because that text sits in the largest
cached block of the agent's prompt and rewriting it silently costs the next
conversation a full-price prefix.
"""

from __future__ import annotations

import json

# A production-scale guidelines page. Similarity is length-sensitive, so tests that
# assert on drift tolerance have to use a realistic page or the ratios mislead.
REALISTIC_PAGE = (
    "Submission guidelines. We read literary fiction, essays, and poetry year round, "
    "with a reading period from August 15 through May 15. Prose should not exceed 8000 "
    "words; we prefer work between 2000 and 6000 words and rarely publish anything "
    "shorter than 1000. Send one story or up to five poems at a time, as a single "
    "attached document with your name and contact details on the first page. We accept "
    "simultaneous submissions and ask only that you withdraw the piece promptly if it is "
    "placed elsewhere. There is no reading fee. Response time is typically three to six "
    "months and we do our best to reply to everything, though during heavy months it can "
    "run longer. We are drawn to voice-driven work with a strong sense of place, and we "
    "have a soft spot for comedy that earns its darkness. We do not publish genre fiction, "
    "fan fiction, or work that has appeared anywhere else, including personal blogs. "
    "Payment is a small honorarium on publication plus two contributor copies. Queries "
    "about work in progress are not necessary. Please read a recent issue before sending."
)


class TestFingerprintNormalization:
    """Only volatile chrome is normalized away. Everything a writer would act on —
    especially numbers — must survive, or Gate 1 hides the change."""

    def test_relative_countdown_is_ignored(self, isolated_summaries):
        sj = isolated_summaries
        a = "Submissions close in 12 days. Up to 8000 words."
        b = "Submissions close in 3 days. Up to 8000 words."
        assert sj.fingerprint(a) == sj.fingerprint(b)

    def test_dates_and_years_are_ignored(self, isolated_summaries):
        sj = isolated_summaries
        a = "Copyright 2025. Updated August 15, 2025. Reading now."
        b = "Copyright 2026. Updated August 13, 2026. Reading now."
        assert sj.fingerprint(a) == sj.fingerprint(b)

    def test_clock_times_are_ignored(self, isolated_summaries):
        sj = isolated_summaries
        assert sj.fingerprint("Deadline 11:59 pm tonight") == sj.fingerprint("Deadline 5:00 pm tonight")

    def test_word_limit_change_is_detected(self, isolated_summaries):
        """Regression: stripping every digit made this invisible, which is the single
        most important field on the page."""
        sj = isolated_summaries
        assert sj.fingerprint("Send prose up to 8000 words.") != sj.fingerprint("Send prose up to 3000 words.")

    def test_added_fee_is_detected(self, isolated_summaries):
        sj = isolated_summaries
        a = "There is no reading fee."
        b = "There is now a $3 reading fee."
        assert sj.fingerprint(a) != sj.fingerprint(b)

    def test_real_wording_change_does_count(self, isolated_summaries):
        sj = isolated_summaries
        a = "We accept literary fiction up to 8000 words."
        b = "We accept poetry only. No fiction."
        assert sj.fingerprint(a) != sj.fingerprint(b)

    def test_case_and_whitespace_are_ignored(self, isolated_summaries):
        sj = isolated_summaries
        assert sj.fingerprint("Up To EIGHT thousand   words") == sj.fingerprint("up to eight thousand words")


class TestDetailsChanged:
    FIELDS = {
        "aesthetic": "lyric realism", "word_limit": "8000", "reading_period": "Aug-May",
        "response_time": "3 months", "simultaneous_submissions": "allowed",
        "multiple_submissions": "one at a time", "fee": "none", "red_flags": "none noted",
    }

    def test_identical_is_unchanged(self, isolated_summaries):
        assert not isolated_summaries.details_changed(self.FIELDS, dict(self.FIELDS))

    def test_case_and_padding_only_is_unchanged(self, isolated_summaries):
        other = dict(self.FIELDS, aesthetic="  LYRIC REALISM ")
        assert not isolated_summaries.details_changed(self.FIELDS, other)

    def test_word_limit_change_is_a_change(self, isolated_summaries):
        assert isolated_summaries.details_changed(self.FIELDS, dict(self.FIELDS, word_limit="5000"))

    def test_missing_old_details_counts_as_changed(self, isolated_summaries):
        """Legacy entries have no details, so the first run must fill them in."""
        assert isolated_summaries.details_changed(None, self.FIELDS)


class TestPageUnchanged:
    def test_exact_match_after_normalization_is_unchanged(self, isolated_summaries):
        sj = isolated_summaries
        text = REALISTIC_PAGE
        assert sj.page_unchanged("x", text, sj.fingerprint(text))

    def test_chrome_only_drift_is_unchanged(self, isolated_summaries):
        """A refreshed copyright year and countdown must not trigger a re-summarize."""
        sj = isolated_summaries
        before = "Copyright 2025. Closes in 12 days. " + REALISTIC_PAGE
        after = "Copyright 2026. Closes in 4 days. " + REALISTIC_PAGE
        assert sj.page_unchanged("mag", after, sj.fingerprint(before))

    def test_no_stored_fingerprint_means_changed(self, isolated_summaries):
        assert not isolated_summaries.page_unchanged("never-seen", "anything", None)

    def test_added_closure_notice_is_detected(self, isolated_summaries):
        """A page that only *adds* text must still count as changed — the earlier
        similarity gate scored appends as identical."""
        sj = isolated_summaries
        closed = REALISTIC_PAGE + (
            " IMPORTANT UPDATE: we are now permanently closed to unsolicited submissions."
        )
        assert not sj.page_unchanged("mag", closed, sj.fingerprint(REALISTIC_PAGE))

    def test_single_token_limit_change_is_detected(self, isolated_summaries):
        """The case no similarity threshold can catch: one number in a long page."""
        sj = isolated_summaries
        changed = REALISTIC_PAGE.replace("8000", "3000")
        assert not sj.page_unchanged("mag", changed, sj.fingerprint(REALISTIC_PAGE))

    def test_substantive_rewrite_is_detected(self, isolated_summaries):
        sj = isolated_summaries
        assert not sj.page_unchanged(
            "mag", "We are permanently closed and no longer read work.", sj.fingerprint(REALISTIC_PAGE)
        )


class TestStatusCounts:
    def test_buckets_are_disjoint_and_sum_to_total(self, isolated_summaries):
        sj = isolated_summaries
        sj._save_cache({"cached one": {"summary": "s"}})
        journals = [
            {"normalized_name": "cached one", "journal_url": "https://a.example"},
            {"normalized_name": "missing one", "journal_url": "https://b.example"},
            {"normalized_name": "no url one"},
        ]
        s = sj.status_for(journals)
        assert s == {"total": 3, "cached": 1, "missing": 1, "no_url": 1}
        assert s["cached"] + s["missing"] + s["no_url"] == s["total"]


class TestBackCompat:
    def test_legacy_entry_without_details_still_loads(self, isolated_summaries):
        """The committed cache predates structured details; it must keep working."""
        sj = isolated_summaries
        sj._save_cache({"old mag": {"name": "Old Mag", "summary": "Three sentences.", "url": "https://o.example"}})
        journals = [{"normalized_name": "old mag"}]
        assert sj.load_summaries_for(journals) == {"old mag": "Three sentences."}
        assert sj.load_details_for(journals) == {}
        assert sj.format_details("old mag") is None
        assert sj.load_urls_for(journals) == {"old mag": "https://o.example"}

    def test_pages_list_wins_over_url_for_best_url(self, isolated_summaries):
        sj = isolated_summaries
        sj._save_cache({"mag": {
            "summary": "s", "url": "https://mag.example/about/contact",
            "pages": ["https://mag.example/about/contact", "https://mag.example/submissions"],
        }})
        assert sj.load_urls_for([{"normalized_name": "mag"}]) == {"mag": "https://mag.example/submissions"}


class TestGateCascade:
    """generate_summaries walks gates 0-2. These drive it with a stubbed fetch and
    a stubbed model so no network or API key is involved."""

    JOURNAL = {"normalized_name": "mag", "display_name": "Mag", "journal_url": "https://mag.example/sub", "rank": 1}
    PAGE = REALISTIC_PAGE
    DETAILS = {
        "aesthetic": "literary fiction", "word_limit": "8000", "reading_period": "Aug-May",
        "response_time": "unknown", "simultaneous_submissions": "unknown",
        "multiple_submissions": "unknown", "fee": "none", "red_flags": "none noted",
    }

    def _stub(self, sj, monkeypatch, page=None, details=None, summary="A summary."):
        calls = {"fetch": 0, "model": 0}

        def fake_gather(url):
            calls["fetch"] += 1
            return (page if page is not None else self.PAGE), [url], None

        def fake_summarize(text, client):
            calls["model"] += 1
            return {
                "summary": summary,
                "index_line": f"{summary[:60]} index line",
                "found_guidelines": True,
                "details": details if details is not None else dict(self.DETAILS),
            }

        monkeypatch.setattr(sj, "_gather_pages", fake_gather)
        monkeypatch.setattr(sj, "_summarize", fake_summarize)
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        monkeypatch.setattr(sj.time, "sleep", lambda s: None)
        return calls

    def _run(self, sj, **kw):
        return list(sj.generate_summaries([self.JOURNAL], api_key="unused", **kw))

    def test_first_run_generates(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        out = "\n".join(self._run(sj))
        assert calls["model"] == 1
        assert "1 generated" in out
        assert sj._load_cache()["mag"]["details"]["word_limit"] == "8000"
        assert sj._load_cache()["mag"]["revision"] == 1

    def test_gate0_skips_without_touching_the_network(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        self._run(sj)
        calls["fetch"] = calls["model"] = 0
        out = "\n".join(self._run(sj))
        assert calls["fetch"] == 0, "Gate 0 must not re-fetch inside the recheck window"
        assert calls["model"] == 0
        assert "1 unchanged" in out

    def test_gate1_skips_model_when_page_is_identical(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        self._run(sj)
        # Expire gate 0 so gate 1 is the one under test.
        meta = sj._load_meta(); meta["mag"]["checked_at"] = "2000-01-01T00:00:00+00:00"; sj._save_meta(meta)
        calls["fetch"] = calls["model"] = 0
        out = "\n".join(self._run(sj))
        assert calls["fetch"] == 1
        assert calls["model"] == 0, "Gate 1 must not spend tokens on an unchanged page"
        assert "unchanged" in out

    def test_gate2_preserves_prose_when_details_are_identical(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        self._stub(sj, monkeypatch, summary="ORIGINAL PROSE.")
        self._run(sj)
        before = json.dumps(sj._load_cache(), sort_keys=True)

        # Page changes (so Gate 1 says "changed"), but nothing a writer would act on:
        # a masthead block, with limits, fees, dates, and policy untouched.
        changed_page = self.PAGE + (
            " Masthead. Founding editor: A. Person. Fiction editors: B. Person and C. Person. "
            "Interns are credited on the masthead and attend editorial meetings."
        )
        self._stub(sj, monkeypatch, page=changed_page, summary="COMPLETELY DIFFERENT PROSE.")
        meta = sj._load_meta(); meta["mag"]["checked_at"] = "2000-01-01T00:00:00+00:00"; sj._save_meta(meta)
        out = "\n".join(self._run(sj))

        entry = sj._load_cache()["mag"]
        assert entry["summary"] == "ORIGINAL PROSE.", "Gate 2 must keep the cached prose"
        assert entry["revision"] == 1
        assert "kept existing summary" in out
        assert json.dumps(sj._load_cache(), sort_keys=True) == before, "committed file must be untouched"

    def test_real_field_change_rewrites_and_bumps_revision(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        self._stub(sj, monkeypatch, summary="OLD.")
        self._run(sj)
        self._stub(
            sj, monkeypatch,
            page="We now cap submissions at 5000 words and charge a reading fee.",
            details=dict(self.DETAILS, word_limit="5000", fee="$3"),
            summary="NEW.",
        )
        meta = sj._load_meta(); meta["mag"]["checked_at"] = "2000-01-01T00:00:00+00:00"; sj._save_meta(meta)
        out = "\n".join(self._run(sj))
        entry = sj._load_cache()["mag"]
        assert entry["summary"] == "NEW."
        assert entry["details"]["word_limit"] == "5000"
        assert entry["revision"] == 2
        assert "1 refreshed" in out

    def test_a_corrected_url_invalidates_the_cached_entry(self, isolated_summaries, monkeypatch):
        """Fixing a wrong journal_url must re-summarize, even inside the 90-day
        recheck window — the cached text describes a page we no longer point at."""
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch, summary="FROM THE OLD URL.")
        self._run(sj)
        assert calls["model"] == 1

        # A corrected URL points somewhere genuinely different.
        moved = dict(self.JOURNAL, journal_url="https://mag.example/new-submissions")
        calls = self._stub(
            sj, monkeypatch,
            page="Entirely different guidelines page. Send up to 3000 words, $5 fee.",
            details=dict(self.DETAILS, word_limit="3000", fee="$5"),
            summary="FROM THE CORRECTED URL.",
        )
        out = "\n".join(sj.generate_summaries([moved], api_key="unused"))
        assert calls["model"] == 1, "a changed URL must not be skipped by Gate 0"
        assert "refreshed" in out
        entry = sj._load_cache()["mag"]
        assert entry["summary"] == "FROM THE CORRECTED URL."
        assert entry["url"] == "https://mag.example/new-submissions"

    def test_corrected_url_serving_the_same_page_updates_without_a_model_call(
        self, isolated_summaries, monkeypatch
    ):
        """Edge case: the URL was fixed but resolves to identical content. Record the
        new URL so it stops looking stale every run, but don't pay to re-summarize."""
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch, summary="ORIGINAL.")
        self._run(sj)
        moved = dict(self.JOURNAL, journal_url="https://mag.example/moved")
        calls["fetch"] = calls["model"] = 0
        list(sj.generate_summaries([moved], api_key="unused"))
        entry = sj._load_cache()["mag"]
        assert calls["fetch"] == 1
        assert calls["model"] == 0, "identical page needs no new summary"
        assert entry["url"] == "https://mag.example/moved"
        assert entry["summary"] == "ORIGINAL."

    def test_unchanged_url_still_skips(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        self._run(sj)
        calls["fetch"] = calls["model"] = 0
        self._run(sj)
        assert calls["fetch"] == 0 and calls["model"] == 0

    def test_force_refresh_bypasses_gates_0_and_1(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        self._run(sj)
        calls["fetch"] = calls["model"] = 0
        self._run(sj, force_refresh=True)
        assert calls["fetch"] == 1
        assert calls["model"] == 1

    def test_dry_run_spends_nothing_and_writes_nothing(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        calls = self._stub(sj, monkeypatch)
        out = "\n".join(self._run(sj, dry_run=True))
        assert calls["model"] == 0, "dry run must not call the model"
        assert sj._load_cache() == {}, "dry run must not write the committed file"
        assert "WOULD generate" in out
        assert "1 would generate" in out

    def test_bookkeeping_stays_out_of_the_committed_file(self, isolated_summaries, monkeypatch):
        """checked_at/fingerprint live in the gitignored meta file so a no-op run
        leaves a zero-byte diff on data/journal_summaries.json."""
        sj = isolated_summaries
        self._stub(sj, monkeypatch)
        self._run(sj)
        entry = sj._load_cache()["mag"]
        assert "checked_at" not in entry
        assert "fingerprint" not in entry
        assert set(sj._load_meta()["mag"]) == {"checked_at", "fingerprint"}

    def test_credit_exhaustion_stops_the_whole_run(self, isolated_summaries, monkeypatch):
        """A dead account must not mean fetching a page and failing a call for each of
        the hundreds of journals left."""
        sj = isolated_summaries
        attempts = {"fetch": 0}

        def fake_gather(url):
            attempts["fetch"] += 1
            return self.PAGE, [url], None

        def broke(text, client):
            raise Exception("Your credit balance is too low to access the Anthropic API")

        monkeypatch.setattr(sj, "_gather_pages", fake_gather)
        monkeypatch.setattr(sj, "_summarize", broke)
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        monkeypatch.setattr(sj.time, "sleep", lambda s: None)

        journals = [
            {"normalized_name": f"mag{i}", "display_name": f"Mag {i}",
             "journal_url": f"https://mag{i}.example", "rank": i}
            for i in range(8)
        ]
        out = "\n".join(sj.generate_summaries(journals, api_key="unused"))
        assert attempts["fetch"] == 1, "must stop after the first fatal error, not grind on"
        assert "STOPPED" in out
        assert "re-run the same command" in out

    def test_auth_error_stops_the_run(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        monkeypatch.setattr(sj, "_gather_pages", lambda url: (self.PAGE, [url], None))

        import httpx

        def broke(text, client):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise sj.anthropic.AuthenticationError(
                "bad key", response=httpx.Response(401, request=request), body=None
            )

        monkeypatch.setattr(sj, "_summarize", broke)
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        journals = [{"normalized_name": "m", "display_name": "M", "journal_url": "https://m.example", "rank": 1}]
        assert "STOPPED" in "\n".join(sj.generate_summaries(journals, api_key="unused"))

    def test_ordinary_failure_still_continues(self, isolated_summaries, monkeypatch):
        """A single bad page must not abort the run — only account-level errors do."""
        sj = isolated_summaries
        calls = {"n": 0}

        def flaky(text, client):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("no JSON object in model reply")
            return {"summary": "ok", "index_line": "ok line", "found_guidelines": True, "details": dict(self.DETAILS)}

        monkeypatch.setattr(sj, "_gather_pages", lambda url: (self.PAGE, [url], None))
        monkeypatch.setattr(sj, "_summarize", flaky)
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        monkeypatch.setattr(sj.time, "sleep", lambda s: None)
        journals = [
            {"normalized_name": "a", "display_name": "A", "journal_url": "https://a.example", "rank": 1},
            {"normalized_name": "b", "display_name": "B", "journal_url": "https://b.example", "rank": 2},
        ]
        out = "\n".join(sj.generate_summaries(journals, api_key="unused"))
        assert "STOPPED" not in out
        assert "1 generated" in out and "1 failed" in out

    def test_fetch_failure_is_reported_not_raised(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        monkeypatch.setattr(sj, "_gather_pages", lambda url: ("", [], "Could not fetch page: boom"))
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        out = "\n".join(self._run(sj))
        assert "could not read Mag" in out
        assert "1 failed" in out
        assert sj._load_cache() == {}

    def test_unsummarized_journals_are_processed_before_cached_ones(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"cached": {"summary": "s", "details": dict(self.DETAILS)}})
        order = []
        monkeypatch.setattr(sj, "_gather_pages", lambda url: (order.append(url), (self.PAGE, [url], None))[1])
        monkeypatch.setattr(sj, "_summarize", lambda t, c: {"summary": "x", "index_line": "x line", "found_guidelines": True, "details": dict(self.DETAILS)})
        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: object())
        monkeypatch.setattr(sj.time, "sleep", lambda s: None)
        journals = [
            {"normalized_name": "cached", "display_name": "Cached", "journal_url": "https://cached.example", "rank": 1},
            {"normalized_name": "fresh", "display_name": "Fresh", "journal_url": "https://fresh.example", "rank": 9},
        ]
        list(sj.generate_summaries(journals, api_key="unused"))
        assert order[0] == "https://fresh.example", "unsummarized journals come first"


class TestThinPageDetection:
    """Calibrated against real journal pages: signal density separates a guidelines
    page from an about page, where length does not."""

    GUIDELINES = (
        "Submission guidelines. We accept prose up to 8000 words during our reading "
        "period. Simultaneous submissions are fine. Response time is three months. "
        "No reading fee. Send via Submittable with a short cover letter."
    )
    ABOUT = (
        "Founded in 1998, the magazine has published many fine writers over the years "
        "and continues to appear three times annually. Our editors live in several "
        "cities and meet regularly. We host an annual event each autumn, and our "
        "fellowship programme supports emerging voices from across the region. "
    ) * 6

    def test_real_guidelines_page_is_not_thin(self, isolated_summaries):
        assert not isolated_summaries._looks_thin(self.GUIDELINES)

    def test_long_about_page_with_no_guidelines_is_thin(self, isolated_summaries):
        """A Public Space's page is 4,785 chars with zero guideline signals — length
        alone would wrongly clear it."""
        assert len(self.ABOUT) > 1000
        assert isolated_summaries._looks_thin(self.ABOUT)

    def test_very_short_page_is_thin(self, isolated_summaries):
        assert isolated_summaries._looks_thin("Contact us at eds@example.com")

    def test_empty_fetch_is_thin(self, isolated_summaries):
        """A JS-rendered page yields almost no text; signals catch it without a
        length rule."""
        assert isolated_summaries._looks_thin("")

    def test_short_page_with_full_policies_is_not_thin(self, isolated_summaries):
        """Terse but complete. A length rule would have wrongly sent us chasing links."""
        assert len(self.GUIDELINES) < 400
        assert not isolated_summaries._looks_thin(self.GUIDELINES)


class TestFollowLinkPicker:
    def test_submissions_link_beats_about_and_masthead(self, isolated_summaries):
        links = [
            ("About", "https://m.example/about"),
            ("Masthead", "https://m.example/about/masthead"),
            ("Submissions", "https://m.example/submissions"),
        ]
        assert isolated_summaries._pick_follow_link(links, set()) == "https://m.example/submissions"

    def test_skips_already_visited_landing_page(self, isolated_summaries):
        """The best link is often the page we already fetched — take the runner-up."""
        links = [
            ("Submissions", "https://m.example/submissions"),
            ("Submission guidelines", "https://m.example/guidelines"),
        ]
        picked = isolated_summaries._pick_follow_link(links, {"https://m.example/submissions"})
        assert picked == "https://m.example/guidelines"

    def test_returns_none_when_nothing_promising(self, isolated_summaries):
        links = [("Upcoming Events", "https://m.example/events"), ("Shop", "https://m.example/shop")]
        assert isolated_summaries._pick_follow_link(links, set()) is None

    def test_masthead_is_an_about_candidate_not_a_guidelines_one(self, isolated_summaries):
        """Two vocabularies: a masthead tells you what the journal is like, not how to
        submit, so it must not compete with a real guidelines link."""
        sj = isolated_summaries
        links = [("Masthead", "https://m.example/about/masthead")]
        assert sj._pick_follow_link(links, set(), sj._FOLLOW_HINTS) is None
        assert sj._pick_follow_link(links, set(), sj._ABOUT_HINTS) == "https://m.example/about/masthead"

    def test_about_pass_prefers_about_over_an_issue_listing(self, isolated_summaries):
        sj = isolated_summaries
        links = [
            ("Winter 2026 issue", "https://m.example/issue/winter-2026"),
            ("About the magazine", "https://m.example/about"),
        ]
        assert sj._pick_follow_link(links, set(), sj._ABOUT_HINTS) == "https://m.example/about"


class TestAestheticDetection:
    def test_bare_mechanics_page_has_no_aesthetic(self, isolated_summaries):
        """Knowing how to submit isn't knowing whether you should — that's when it's
        worth spending a request on an about page."""
        mechanics_only = (
            "Send submissions as a DOC file. Maximum 5000 words. Reading fee $3. "
            "Response within 90 days. No simultaneous submissions. Use Submittable."
        )
        assert not isolated_summaries._has_aesthetic(mechanics_only)

    def test_about_text_has_aesthetic(self, isolated_summaries):
        about = (
            "Founded in 1998, we publish stories and essays by writers who take risks. "
            "Our editors are interested in voice above all. Recent issue features "
            "fiction and nonfiction from contributors across the country."
        )
        assert isolated_summaries._has_aesthetic(about)


class TestIndexLines:
    """The ranked list carries one line per journal. Truncating a 3-sentence summary
    keeps whatever the first sentence happens to be — which is often a founding date
    or, worse, a description of the web page. A purpose-written line is denser and
    more decision-relevant, and costs a tenth of re-summarizing because it condenses
    text already cached rather than re-fetching a site."""

    def test_index_line_is_preferred_over_the_summary(self, isolated_summaries):
        sj = isolated_summaries
        sj._save_cache({"mag": {"summary": "Founded in 1998. Publishes flash.",
                                "index_line": "Flash-only, hybrid-friendly; closed until autumn"}})
        j = [{"normalized_name": "mag"}]
        assert sj.load_index_lines_for(j) == {"mag": "Flash-only, hybrid-friendly; closed until autumn"}

    def test_summary_still_available_separately(self, isolated_summaries):
        """Kept apart so the agent's sentence trimmer can't cut an index line at its
        first period."""
        sj = isolated_summaries
        sj._save_cache({"mag": {"summary": "Founded in 1998. Publishes flash.",
                                "index_line": "Flash-only. Closed until autumn."}})
        j = [{"normalized_name": "mag"}]
        assert sj.load_summaries_for(j)["mag"].startswith("Founded")
        assert sj.load_index_lines_for(j)["mag"] == "Flash-only. Closed until autumn."

    def test_blank_index_line_falls_back(self, isolated_summaries):
        sj = isolated_summaries
        sj._save_cache({"mag": {"summary": "Publishes flash.", "index_line": "   "}})
        assert sj.load_index_lines_for([{"normalized_name": "mag"}]) == {}

    def test_needs_index_line_finds_only_entries_lacking_one(self, isolated_summaries):
        sj = isolated_summaries
        sj._save_cache({
            "has": {"summary": "s", "index_line": "a line"},
            "lacks": {"summary": "s"},
            "blank": {"summary": "s", "index_line": ""},
        })
        journals = [{"normalized_name": n} for n in ("has", "lacks", "blank", "uncached")]
        assert {j["normalized_name"] for j in sj.needs_index_line(journals)} == {"lacks", "blank"}

    def _stub_condense(self, sj, monkeypatch, line="Dense one-liner"):
        calls = {"n": 0}

        class _M:
            def create(self, **kw):
                calls["n"] += 1
                b = type("B", (), {"type": "text", "text": line})()
                return type("R", (), {"content": [b]})()

        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: type("C", (), {"messages": _M()})())
        return calls

    def test_condense_writes_lines_without_fetching_pages(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"mag": {"name": "Mag", "summary": "Long prose.", "details": {}}})
        monkeypatch.setattr(sj, "_gather_pages", lambda url: (_ for _ in ()).throw(
            AssertionError("condense must not fetch pages")))
        calls = self._stub_condense(sj, monkeypatch)
        list(sj.condense_entries([{"normalized_name": "mag"}], api_key="unused"))
        assert calls["n"] == 1
        assert sj._load_cache()["mag"]["index_line"] == "Dense one-liner"

    def test_condense_skips_entries_that_already_have_one(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"mag": {"name": "Mag", "summary": "s", "index_line": "existing"}})
        calls = self._stub_condense(sj, monkeypatch)
        out = "\n".join(sj.condense_entries([{"normalized_name": "mag"}], api_key="unused"))
        assert calls["n"] == 0
        assert "already has an index line" in out

    def test_force_rewrites_existing_lines(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"mag": {"name": "Mag", "summary": "s", "index_line": "old"}})
        self._stub_condense(sj, monkeypatch, line="new and better")
        list(sj.condense_entries([{"normalized_name": "mag"}], api_key="unused", force=True))
        assert sj._load_cache()["mag"]["index_line"] == "new and better"

    def test_quotes_and_newlines_are_stripped(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"mag": {"name": "Mag", "summary": "s"}})
        self._stub_condense(sj, monkeypatch, line='"Flash only,\nno fees"')
        list(sj.condense_entries([{"normalized_name": "mag"}], api_key="unused"))
        line = sj._load_cache()["mag"]["index_line"]
        assert "\n" not in line and not line.startswith('"')

    def test_dry_run_writes_nothing(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({"mag": {"name": "Mag", "summary": "s"}})
        calls = self._stub_condense(sj, monkeypatch)
        list(sj.condense_entries([{"normalized_name": "mag"}], api_key="unused", dry_run=True))
        assert calls["n"] == 0
        assert "index_line" not in sj._load_cache()["mag"]

    def test_credit_exhaustion_stops_condensing(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        sj._save_cache({f"m{i}": {"name": f"M{i}", "summary": "s"} for i in range(5)})

        class _M:
            def create(self, **kw):
                raise Exception("Your credit balance is too low")

        monkeypatch.setattr(sj.anthropic, "Anthropic", lambda **k: type("C", (), {"messages": _M()})())
        out = "\n".join(sj.condense_entries(
            [{"normalized_name": f"m{i}"} for i in range(5)], api_key="unused"))
        assert "STOPPED" in out


class TestCli:
    """The CLI is how a full ~1-hour fill is actually run, so its guards matter."""

    def test_requires_a_source(self, isolated_summaries):
        import pytest
        with pytest.raises(SystemExit) as e:
            isolated_summaries._main([])
        assert e.value.code == 2  # argparse usage error

    def test_all_and_only_are_mutually_exclusive(self, isolated_summaries):
        import pytest
        with pytest.raises(SystemExit):
            isolated_summaries._main(["--all", "--only", "x"])

    def test_unknown_journal_exits_nonzero(self, isolated_summaries, capsys):
        assert isolated_summaries._main(["--only", "definitely not a journal"]) == 1
        assert "Not found in rankings" in capsys.readouterr().out

    def test_dry_run_needs_no_api_key(self, isolated_summaries, monkeypatch, capsys):
        """generate_summaries is stubbed: the real one makes HTTP requests even in
        dry-run mode, which would put the network in the unit suite."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(isolated_summaries, "generate_summaries", lambda *a, **k: iter([]))
        assert isolated_summaries._main(["--all", "--limit", "2", "--dry-run"]) == 0

    def test_missing_key_is_refused_for_a_real_run(self, isolated_summaries, monkeypatch, capsys):
        # load_dotenv must be stubbed too, or it restores the key from the real .env.
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(isolated_summaries, "generate_summaries", lambda *a, **k: iter([]))
        assert isolated_summaries._main(["--all", "--limit", "2"]) == 1
        assert "ANTHROPIC_API_KEY not set" in capsys.readouterr().out

    def test_limit_is_applied(self, isolated_summaries, monkeypatch, capsys):
        monkeypatch.setattr(isolated_summaries, "generate_summaries", lambda *a, **k: iter([]))
        isolated_summaries._main(["--all", "--limit", "3", "--dry-run"])
        assert "3 journals" in capsys.readouterr().out

    def test_limit_zero_means_zero(self, isolated_summaries, monkeypatch, capsys):
        """Regression: `if args.limit:` treated --limit 0 as unset and ran all 519."""
        monkeypatch.setattr(isolated_summaries, "generate_summaries", lambda *a, **k: iter([]))
        isolated_summaries._main(["--all", "--limit", "0", "--dry-run"])
        assert "0 journals" in capsys.readouterr().out


class TestExtractionRequestShape:
    """Structured extraction runs against a tight token budget, and on Sonnet 5 an
    omitted `thinking` field means thinking runs and competes for that budget — which
    truncates the JSON and fails the parse outright."""

    def test_thinking_is_disabled_and_budget_has_headroom(self, isolated_summaries, monkeypatch):
        sj = isolated_summaries
        captured = {}

        class _FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                block = type("B", (), {"type": "text", "text": '{"summary":"s","details":{}}'})()
                return type("R", (), {"content": [block]})()

        client = type("C", (), {"messages": _FakeMessages()})()
        sj._summarize("some page text", client)
        assert captured["thinking"] == {"type": "disabled"}
        assert captured["max_tokens"] >= 1500

    def test_extraction_and_agent_configs_differ(self, isolated_summaries):
        import models_config
        assert models_config.EXTRACTION_THINKING != models_config.AGENT_THINKING


class TestJsonExtraction:
    def test_parses_fenced_json(self, isolated_summaries):
        raw = '```json\n{"summary": "s", "details": {}}\n```'
        assert isolated_summaries._extract_json(raw)["summary"] == "s"

    def test_parses_bare_json(self, isolated_summaries):
        assert isolated_summaries._extract_json('{"summary": "s"}')["summary"] == "s"

    def test_tolerates_surrounding_prose(self, isolated_summaries):
        raw = 'Here you go:\n{"summary": "s"}\nHope that helps.'
        assert isolated_summaries._extract_json(raw)["summary"] == "s"

    def test_raises_without_json(self, isolated_summaries):
        import pytest
        with pytest.raises(ValueError):
            isolated_summaries._extract_json("no object here")

    def test_tolerates_a_literal_newline_inside_a_string(self, isolated_summaries):
        """The model emits raw control characters when a journal's own text is
        multi-line; strict parsing rejected the whole object over one of them."""
        raw = '{"summary": "First line.\nSecond line.", "details": {}}'
        assert isolated_summaries._extract_json(raw)["summary"].startswith("First line.")

    def test_tolerates_a_literal_tab(self, isolated_summaries):
        raw = '{"summary": "Fiction\tPoetry", "details": {}}'
        assert "Poetry" in isolated_summaries._extract_json(raw)["summary"]
