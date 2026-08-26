"""
Shared page fetcher for the agent and the journal summarizer.

Both need the same two things: SSRF-safe fetching, and the list of same-site links
on a page. Links matter because BeautifulSoup's get_text() discards every href, and
the rankings cache supplies only one URL per journal (about_url/submit_url are
unpopulated), so without them neither caller can navigate off the page it landed on.

Previously only the agent validated URLs; the summarizer fetched unchecked. Sharing
this module closes that gap.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 4
MAX_PAGE_LINKS = 30
DEFAULT_MAX_CHARS = 8000

# One retry for failures that are about the moment rather than the page. Small
# journals run on shared hosting that intermittently 500s or rate-limits, and a
# single flake was dropping the journal for the whole run.
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRY_DELAY = 2.0
MAX_ATTEMPTS = 2

# Links whose URL contains one of these are never offered: they lead off the
# editorial part of a journal's site and waste the caller's fetch budget.
SKIP_LINK_WORDS = (
    "facebook", "twitter", "x.com", "instagram", "tiktok", "youtube", "linkedin",
    "patreon", "paypal", "donate", "cart", "login", "signin", "sign-in", "register",
)


@dataclass
class PageFetch:
    """Result of one fetch. `error` is None on success."""

    url: str
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    transient: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_tool_result(self) -> tuple[str, bool]:
        """Render for a tool_result block: (content, is_error)."""
        if self.error:
            return self.error, True
        body = self.text
        if self.links:
            listing = "\n".join(f"- {label} -> {href}" for label, href in self.links)
            body += f"\n\nLinks on this page (same site):\n{listing}"
        return body, False


def _check_host(hostname: str) -> str | None:
    """Return an error message if the host is unresolvable or not public, else None.

    Resolution failure and a blocked address are reported separately: a dead domain is
    ordinary (journals fold, sites move) while a private address means something is
    genuinely wrong. Collapsing both into "refusing to fetch a private or internal
    address" made every dead journal look like a security block.

    Blocks loopback, private, link-local (incl. cloud metadata 169.254.169.254),
    reserved, multicast, and unspecified ranges — for both IPv4 and IPv6 — so page
    fetching can't be used to reach internal services (SSRF).
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return f"Could not resolve host: {hostname}"
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return f"Refusing to fetch an unparseable address for: {hostname}"
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is not None:
            addr = mapped
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return f"Refusing to fetch a private or internal address: {hostname}"
    return None


def _is_public_host(hostname: str) -> bool:
    """Back-compat boolean form of _check_host."""
    return _check_host(hostname) is None


def validate_url(url: str) -> str | None:
    """Return an error message if the URL can't or shouldn't be fetched, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Refusing to fetch non-http(s) URL: {url}"
    if not parsed.hostname:
        return f"Invalid URL: {url}"
    return _check_host(parsed.hostname)


def same_site(a: str, b: str) -> bool:
    """True if two URLs share a host, ignoring a leading 'www.'.

    Host equality rather than registrable-domain matching: it needs no public-suffix
    list, and a journal's guidelines and about pages virtually always live on one
    host. Cross-host links are simply not offered.
    """
    ha = (urlparse(a).hostname or "").lower().removeprefix("www.")
    hb = (urlparse(b).hostname or "").lower().removeprefix("www.")
    return bool(ha) and ha == hb


def extract_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Collect same-site links as (anchor text, absolute url), deduped by url.

    Must run before nav/header/footer are stripped — that is exactly where a
    journal's submissions link usually lives.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href).split("#")[0].rstrip("/")
        if not absolute or absolute in seen:
            continue
        if not same_site(absolute, base_url):
            continue
        if any(w in absolute.lower() for w in SKIP_LINK_WORDS):
            continue
        label = " ".join(a.get_text(separator=" ", strip=True).split())[:80]
        if not label:
            continue
        seen.add(absolute)
        out.append((label, absolute))
        if len(out) >= MAX_PAGE_LINKS:
            break
    return out


def fetch_page(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> PageFetch:
    """Fetch a page, returning flattened text plus its same-site links.

    Retries once on transient failures — a rate limit, a 5xx, a timeout — but not on
    a 403 or 404, which will say the same thing however many times they are asked.

    Never raises — failures come back as `error` so callers can surface them to the
    model as an errored tool result rather than crashing the turn.
    """
    result = _fetch_once(url, max_chars)
    for _ in range(MAX_ATTEMPTS - 1):
        if result.ok or not result.transient:
            break
        time.sleep(RETRY_DELAY)
        result = _fetch_once(url, max_chars)
    return result


def _fetch_once(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> PageFetch:
    try:
        # Follow redirects manually, re-validating each hop, so a public page
        # can't 302 the request onto an internal address.
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            err = validate_url(current)
            if err:
                return PageFetch(url=url, error=err)
            resp = requests.get(
                current,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "submissions-advisor/1.0"},
                allow_redirects=False,
            )
            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("location")
                if not location:
                    break
                current = urljoin(current, location)
                continue
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            links = extract_links(soup, current)
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = " ".join(soup.get_text(separator=" ", strip=True).split())
            return PageFetch(url=current, text=text[:max_chars], links=links)
        return PageFetch(url=url, error=f"Too many redirects fetching: {url}")
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        return PageFetch(url=url, error=f"Could not fetch page: {e}",
                         transient=status in TRANSIENT_STATUSES)
    except (requests.Timeout, requests.ConnectionError) as e:
        # A refused connection or a timeout is usually the moment, not the address.
        return PageFetch(url=url, error=f"Could not fetch page: {e}", transient=True)
    except Exception as e:
        return PageFetch(url=url, error=f"Could not fetch page: {e}")
