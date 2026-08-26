"""Link extraction and the SSRF guards.

Link extraction is what lets the agent navigate at all — get_text() discards every
href, and the rankings cache supplies one URL per journal.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

import pagefetch

BASE = "https://www.journal.example/page"

HTML = """
<html><body>
  <nav><a href="/submissions">Submissions</a></nav>
  <a href="/about">About Us</a>
  <a href="https://journal.example/masthead">Masthead</a>
  <a href="https://twitter.com/journal">Twitter</a>
  <a href="https://elsewhere.example/x">Elsewhere</a>
  <a href="#section">Jump</a>
  <a href="mailto:eds@journal.example">Email</a>
  <a href="tel:+15551234">Call</a>
  <a href="/about/">About trailing slash</a>
  <a href="/donate">Donate</a>
  <a href="/icon-only"><img src="i.png"></a>
  <p>Body copy.</p>
</body></html>
"""


def _links(html=HTML, base=BASE):
    return pagefetch.extract_links(BeautifulSoup(html, "html.parser"), base)


class TestSameSite:
    def test_www_prefix_ignored(self):
        assert pagefetch.same_site("https://www.x.example/a", "https://x.example/b")

    def test_subdomain_is_not_same_site(self):
        assert not pagefetch.same_site("https://x.example/a", "https://sub.x.example/b")

    def test_different_host(self):
        assert not pagefetch.same_site("https://x.example/a", "https://y.example/b")

    def test_missing_host(self):
        assert not pagefetch.same_site("not-a-url", "https://x.example")


class TestExtractLinks:
    def test_keeps_same_site_links(self):
        hrefs = [h for _, h in _links()]
        assert "https://www.journal.example/submissions" in hrefs
        assert "https://www.journal.example/about" in hrefs

    def test_keeps_nav_links(self):
        """Must run before nav/header/footer are stripped — that's where the
        submissions link usually lives."""
        assert any("submissions" in h for _, h in _links())

    def test_drops_cross_host_social_and_schemes(self):
        hrefs = " ".join(h for _, h in _links())
        for unwanted in ("twitter", "elsewhere.example", "mailto", "tel:", "donate"):
            assert unwanted not in hrefs

    def test_drops_pure_fragment(self):
        assert not any(h.endswith("#section") for _, h in _links())

    def test_dedupes_trailing_slash_variant(self):
        hrefs = [h for _, h in _links()]
        assert hrefs.count("https://www.journal.example/about") == 1

    def test_drops_links_with_no_anchor_text(self):
        assert not any("icon-only" in h for _, h in _links())

    def test_respects_the_cap(self, monkeypatch):
        monkeypatch.setattr(pagefetch, "MAX_PAGE_LINKS", 2)
        assert len(_links()) == 2

    def test_labels_are_trimmed(self):
        labels = dict((h, l) for l, h in _links())
        assert labels["https://www.journal.example/about"] == "About Us"


class TestValidateUrl:
    def test_rejects_non_http_scheme(self):
        assert "non-http" in (pagefetch.validate_url("file:///etc/passwd") or "")

    def test_rejects_missing_host(self):
        assert pagefetch.validate_url("http://") is not None

    def test_unresolvable_host_says_so_rather_than_blaming_security(self):
        """A dead journal domain is ordinary. Reporting it as 'private or internal
        address' made every folded magazine look like a security block."""
        err = pagefetch.validate_url("https://this-domain-does-not-exist-9f3a1c.invalid/")
        assert err is not None
        assert "Could not resolve host" in err
        assert "private or internal" not in err

    def test_rejects_loopback(self):
        assert "private or internal" in (pagefetch.validate_url("http://127.0.0.1/x") or "")

    def test_rejects_private_range(self):
        assert "private or internal" in (pagefetch.validate_url("http://10.0.0.5/x") or "")

    def test_rejects_cloud_metadata_endpoint(self):
        assert "private or internal" in (pagefetch.validate_url("http://169.254.169.254/latest/meta-data") or "")

    def test_rejects_ipv6_loopback(self):
        assert pagefetch.validate_url("http://[::1]/x") is not None


class TestTransientRetry:
    """Small journals run on shared hosting that intermittently 500s or rate-limits.
    One flake was dropping the journal for an entire run; a 403 or 404, by contrast,
    says the same thing however many times it is asked."""

    def _responder(self, monkeypatch, statuses):
        """Serve the given status codes in order, counting attempts."""
        calls = {"n": 0}
        seq = list(statuses)

        class _Resp:
            is_redirect = False
            is_permanent_redirect = False

            def __init__(self, code):
                self.status_code = code
                self.text = "<html><body><p>Guidelines here.</p></body></html>"

            def raise_for_status(self):
                if self.status_code >= 400:
                    err = pagefetch.requests.HTTPError(f"{self.status_code} Client Error")
                    err.response = self
                    raise err

        def fake_get(*a, **k):
            calls["n"] += 1
            return _Resp(seq[min(calls["n"] - 1, len(seq) - 1)])

        monkeypatch.setattr(pagefetch, "validate_url", lambda u: None)
        monkeypatch.setattr(pagefetch.requests, "get", fake_get)
        monkeypatch.setattr(pagefetch.time, "sleep", lambda s: None)
        return calls

    def test_a_500_is_retried_and_can_succeed(self, monkeypatch):
        calls = self._responder(monkeypatch, [500, 200])
        result = pagefetch.fetch_page("https://mag.example/")
        assert calls["n"] == 2
        assert result.ok
        assert "Guidelines here." in result.text

    def test_rate_limit_is_retried(self, monkeypatch):
        calls = self._responder(monkeypatch, [429, 200])
        assert pagefetch.fetch_page("https://mag.example/").ok
        assert calls["n"] == 2

    def test_403_is_not_retried(self, monkeypatch):
        """A block is a decision, not a hiccup — retrying wastes time and looks rude."""
        calls = self._responder(monkeypatch, [403, 403])
        result = pagefetch.fetch_page("https://mag.example/")
        assert calls["n"] == 1
        assert not result.ok
        assert not result.transient

    def test_404_is_not_retried(self, monkeypatch):
        calls = self._responder(monkeypatch, [404, 404])
        assert pagefetch.fetch_page("https://mag.example/").ok is False
        assert calls["n"] == 1

    def test_a_persistent_500_gives_up_after_the_cap(self, monkeypatch):
        calls = self._responder(monkeypatch, [500, 500, 500])
        result = pagefetch.fetch_page("https://mag.example/")
        assert calls["n"] == pagefetch.MAX_ATTEMPTS
        assert not result.ok

    def test_timeout_is_treated_as_transient(self, monkeypatch):
        calls = {"n": 0}

        def fake_get(*a, **k):
            calls["n"] += 1
            raise pagefetch.requests.Timeout("timed out")

        monkeypatch.setattr(pagefetch, "validate_url", lambda u: None)
        monkeypatch.setattr(pagefetch.requests, "get", fake_get)
        monkeypatch.setattr(pagefetch.time, "sleep", lambda s: None)
        result = pagefetch.fetch_page("https://mag.example/")
        assert calls["n"] == pagefetch.MAX_ATTEMPTS
        assert result.transient

    def test_a_blocked_address_is_never_retried(self, monkeypatch):
        """SSRF rejection is a decision of ours; repeating it is pure waste."""
        calls = {"n": 0}

        def counting(u):
            calls["n"] += 1
            return "Refusing to fetch a private or internal address: x"

        monkeypatch.setattr(pagefetch, "validate_url", counting)
        result = pagefetch.fetch_page("http://10.0.0.1/")
        assert calls["n"] == 1
        assert not result.transient


class TestFetchPageErrors:
    def test_blocked_url_returns_error_not_exception(self):
        result = pagefetch.fetch_page("http://127.0.0.1/x")
        assert not result.ok
        assert result.error

    def test_error_renders_as_errored_tool_result(self):
        content, is_error = pagefetch.fetch_page("http://127.0.0.1/x").as_tool_result()
        assert is_error is True
        assert "private or internal" in content

    def test_redirect_to_internal_address_is_blocked(self, monkeypatch):
        """A public page must not be able to 302 the fetch onto an internal host."""
        class _Resp:
            is_redirect = True
            is_permanent_redirect = False
            headers = {"location": "http://169.254.169.254/latest/meta-data"}

        monkeypatch.setattr(pagefetch, "validate_url", lambda u: None if "external" in u else "blocked internal")
        monkeypatch.setattr(pagefetch.requests, "get", lambda *a, **k: _Resp())
        result = pagefetch.fetch_page("https://external.example/start")
        assert not result.ok
        assert "blocked internal" in result.error

    def test_success_appends_link_section(self, monkeypatch):
        class _Resp:
            is_redirect = False
            is_permanent_redirect = False
            text = HTML
            def raise_for_status(self): ...

        monkeypatch.setattr(pagefetch, "validate_url", lambda u: None)
        monkeypatch.setattr(pagefetch.requests, "get", lambda *a, **k: _Resp())
        content, is_error = pagefetch.fetch_page(BASE).as_tool_result()
        assert is_error is False
        assert "Body copy." in content
        assert "Links on this page (same site):" in content
        assert "About Us -> https://www.journal.example/about" in content

    def test_text_is_truncated_to_max_chars(self, monkeypatch):
        class _Resp:
            is_redirect = False
            is_permanent_redirect = False
            text = "<html><body><p>" + ("x" * 5000) + "</p></body></html>"
            def raise_for_status(self): ...

        monkeypatch.setattr(pagefetch, "validate_url", lambda u: None)
        monkeypatch.setattr(pagefetch.requests, "get", lambda *a, **k: _Resp())
        result = pagefetch.fetch_page(BASE, max_chars=100)
        assert len(result.text) == 100
