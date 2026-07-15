"""
Conversational agent for story-to-journal matching.
Uses Claude with tool use for on-demand page fetching and editor feedback lookup.
"""

import ipaddress
import os
import socket
from typing import Generator
from urllib.parse import urljoin, urlparse

import anthropic
import requests
from bs4 import BeautifulSoup

from ingest import normalize_name
from storage import StorageBackend
from summarize_journals import load_summaries_for
from workbook import format_feedback_brief, get_feedback_for_journal

MODEL = "claude-sonnet-4-6"
MAX_PAGE_CHARS = 3000
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 4

SYSTEM_PROMPT = """You are a literary advisor helping a writer find the best journals for their short fiction.

You have access to a ranked list of literary journals that are currently open for submissions, \
ordered by a weighted prestige score (prize wins, circulation, and pay). Higher rank = more prestigious.

When making recommendations:
- NEVER recommend a journal where the writer already has a submission under review. These are \
  marked "⛔ UNDER REVIEW" in the journal list and enumerated in the opening context. Before naming \
  any journal, re-check it against that list — suggesting one wastes a simultaneous-submission slot \
  and can burn the writer's standing with that editor. Mention such a journal only if the writer \
  explicitly asks about it.
- Each journal entry includes a summary of its guidelines — use these to shortlist candidates
- Use the fetch_page tool only to verify the 2-3 journals you're seriously considering, not for every journal
- If a journal appears in the editor feedback list, call get_editor_feedback before recommending it \
  so you can factor in what the editor actually said
- Focus on fit: aesthetic match, thematic alignment, length requirements, any red flags
- Be honest about reach vs. likelihood — Tier 1 journals are worth trying but competition is fierce
- Ask follow-up questions if you need more about the story to give good advice
- You can discuss submission strategy, style comparisons, comp titles, or anything else useful

When asked to draft a cover letter:
- Ask which template the writer wants if they haven't specified (short, bio, or ai)
- Call get_cover_letter_template to fetch the template text
- Fill in all placeholders you know from context: story title, word count, journal name, style
- Round word count to the nearest 100 (e.g. 4,200 words, not 4,187)
- For the bio template, ask for publication credits and bio details before drafting if not already provided
- For the ai template, follow its instructions — personalize the opening to the specific journal, using fetch_page if you need more detail on the journal's aesthetic
- Present the finished letter in a code block so it's easy to copy
- IMPORTANT: treat the template as the complete letter. Do not add sentences, paragraphs, or sections that aren't in the template. Do not embellish, expand, or improve on it. Fill in the placeholders and stop. The writer has deliberately chosen this wording.

When the writer decides to submit to a journal:
- Confirm the journal name with them before logging
- Use the log_submission tool to record it in their story file
- After logging, confirm it was saved

The writer can share as much or as little as they want: a summary, an excerpt, a theme, the first paragraph.
You don't need the full story to give useful advice."""


FETCH_TOOL = {
    "name": "fetch_page",
    "description": (
        "Fetch the text content of a journal's submission guidelines or about page. "
        "Use this before recommending a journal to check length limits, reading periods, "
        "aesthetic preferences, and any restrictions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL of the page to fetch"},
            "journal_name": {"type": "string", "description": "Name of the journal (for display)"},
        },
        "required": ["url"],
    },
}

GET_EDITOR_FEEDBACK_TOOL = {
    "name": "get_editor_feedback",
    "description": (
        "Retrieve the full editor feedback message(s) for a specific journal. "
        "Use this when a journal appears in the encouraging-notes list to understand "
        "what the editor said before deciding whether to recommend it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "journal": {"type": "string", "description": "Exact journal name as listed in the feedback summary"},
        },
        "required": ["journal"],
    },
}

LOG_SUBMISSION_TOOL = {
    "name": "log_submission",
    "description": (
        "Record that the writer has decided to submit their story to a journal. "
        "Only call this after the writer has explicitly confirmed they want to submit. "
        "This saves the submission to their story file so it won't be suggested again."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "story_slug": {"type": "string", "description": "The story slug from the active story context"},
            "journal": {"type": "string", "description": "The exact journal name as it appears in the ranked list"},
            "notes": {"type": "string", "description": "Optional notes about the submission"},
        },
        "required": ["story_slug", "journal"],
    },
}


GET_COVER_LETTER_TEMPLATE_TOOL = {
    "name": "get_cover_letter_template",
    "description": (
        "Fetch a cover letter template by name. Available templates are listed in the context. "
        "Call this when the writer asks for a cover letter draft."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Template slug: 'short', 'bio', or 'ai'"},
        },
        "required": ["name"],
    },
}


def _is_public_host(hostname: str) -> bool:
    """Resolve a hostname and return True only if every resolved address is public.

    Blocks loopback, private, link-local (incl. cloud metadata 169.254.169.254),
    reserved, multicast, and unspecified ranges — for both IPv4 and IPv6 — so the
    fetch_page tool can't be used to reach internal services (SSRF).
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
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
            return False
    return True


def _validate_url(url: str) -> str | None:
    """Return an error message if the URL is unsafe to fetch, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Refusing to fetch non-http(s) URL: {url}"
    if not parsed.hostname:
        return f"Invalid URL: {url}"
    if not _is_public_host(parsed.hostname):
        return f"Refusing to fetch a private or internal address: {parsed.hostname}"
    return None


def _fetch_page(url: str) -> str:
    try:
        # Follow redirects manually, re-validating each hop, so a public page
        # can't 302 the request onto an internal address.
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            err = _validate_url(current)
            if err:
                return err
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
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())
            return text[:MAX_PAGE_CHARS]
        return f"Too many redirects fetching: {url}"
    except Exception as e:
        return f"Could not fetch page: {e}"


def _format_journal_list(
    journals: list[dict],
    summaries: dict[str, str],
    pending_by_norm: dict[str, str] | None = None,
) -> str:
    lines = []
    pending_by_norm = pending_by_norm or {}
    for j in sorted(journals, key=lambda x: x["rank"]):
        url = j.get("journal_url") or j.get("about_url") or j.get("submit_url") or "no URL"
        name = j.get("display_name") or j.get("name", "")
        summary = summaries.get(j["normalized_name"], "")
        entry = f"#{j['rank']} {name} (score: {j.get('score', 'N/A')}, tier: {j.get('tier', 'N/A')}) — {url}"
        pending_story = pending_by_norm.get(j["normalized_name"])
        if pending_story:
            entry += f"\n  ⛔ UNDER REVIEW — '{pending_story}' is currently submitted here; do NOT recommend"
        if summary:
            entry += f"\n  {summary}"
        lines.append(entry)
    return "\n".join(lines)


def _build_initial_context(
    journals: list[dict],
    storage: StorageBackend,
    editor_feedback: list[dict],
    pending_context: str = "",
    genre_mode: str = "Literary",
) -> str:
    summaries = load_summaries_for(journals)
    summarized = sum(1 for j in journals if j["normalized_name"] in summaries)
    # Flag pending-submission journals inline in the ranked list, where the
    # model reads candidates — the separate pending block alone gets overlooked.
    try:
        pending_by_norm = {
            normalize_name(p["journal"]): p["story_title"]
            for p in storage.list_all_pending()
        }
    except Exception:
        pending_by_norm = {}
    journal_list = _format_journal_list(journals, summaries, pending_by_norm)
    note = f" ({summarized} with cached summaries)" if summarized else ""

    genre_note = f" [Genre mode: {genre_mode}]"
    parts = [
        f"Here are the {len(journals)} {genre_mode.lower()} journals currently open for submissions{note}{genre_note}, "
        f"ranked by prestige score:\n\n{journal_list}"
    ]
    if pending_context:
        parts.append(pending_context)
    feedback_brief = format_feedback_brief(editor_feedback) if editor_feedback else ""
    if feedback_brief:
        parts.append(feedback_brief)
    templates = storage.list_templates()
    if templates:
        tmpl_lines = ["Cover letter templates available (call get_cover_letter_template to fetch):"]
        for t in templates:
            tmpl_lines.append(f"- {t['name']}: {t['description']}")
        parts.append("\n".join(tmpl_lines))
    parts.append("What would you like to discuss? Tell me about your story and I'll help you find the best matches.")
    return "\n\n".join(parts)


def stream_response(
    api_history: list[dict],
    new_user_message: str,
    journals: list[dict],
    storage: StorageBackend,
    story_context: str | None = None,
    editor_feedback: list[dict] | None = None,
    pending_context: str = "",
    genre_mode: str = "Literary",
    api_key: str | None = None,
) -> Generator[str, None, tuple[list[dict], dict]]:
    """
    Stream Claude's response. Handles multi-turn tool use internally.
    Yields text chunks for display. Returns the updated full API history.

    api_history: full message history from previous turns (sent by the client in the request).
    new_user_message: the user's latest input.
    journals: matched ranked journals (used only on first turn).
    story_context: formatted story info from storage.format_story_for_agent() (first turn only).
    editor_feedback: raw feedback list from workbook (first turn: brief list in context;
                     on demand: full text via get_editor_feedback tool).
    """
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    _feedback = editor_feedback or []

    if not api_history:
        journal_context = _build_initial_context(journals, storage, _feedback, pending_context, genre_mode)
        if story_context:
            opening = f"{story_context}\n\n---\n\n{journal_context}"
            ack = (
                "I've loaded your story details and the open journal list. "
                "I can see what you've already submitted to and won't suggest those. "
                "What would you like to work on?"
            )
        else:
            opening = journal_context
            ack = (
                "I've got your journal list — I can see the open submissions ranked by prestige score. "
                "Tell me about your story and I'll help you find the best matches."
            )
        api_history = [
            {
                "role": "user",
                "content": [{"type": "text", "text": opening, "cache_control": {"type": "ephemeral"}}],
            },
            {"role": "assistant", "content": ack},
        ]

    full_messages = api_history + [{"role": "user", "content": new_user_message}]
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    tools = [FETCH_TOOL, GET_EDITOR_FEEDBACK_TOOL, LOG_SUBMISSION_TOOL, GET_COVER_LETTER_TEMPLATE_TOOL]

    # Accumulated token usage across every model call in this turn (incl. tool loops).
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=full_messages,
        )

        u = response.usage
        usage["input_tokens"] += u.input_tokens or 0
        usage["output_tokens"] += u.output_tokens or 0
        usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        tool_uses = []
        for block in response.content:
            if block.type == "text":
                yield block.text
            elif block.type == "tool_use":
                tool_uses.append(block)

        # Plain dicts, not SDK block objects: the history is JSON-serialized
        # into the SSE done event and round-tripped through the client.
        content_dicts = [block.model_dump(mode="json", exclude_none=True) for block in response.content]
        full_messages = full_messages + [{"role": "assistant", "content": content_dicts}]

        if not tool_uses:
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "fetch_page":
                url = tool_use.input.get("url", "")
                journal_name = tool_use.input.get("journal_name", url)
                yield f"\n*Reading {journal_name} guidelines...*\n"
                result = _fetch_page(url)

            elif tool_use.name == "get_editor_feedback":
                journal = tool_use.input.get("journal", "")
                yield f"\n*Checking editor notes for {journal}...*\n"
                result = get_feedback_for_journal(_feedback, journal)

            elif tool_use.name == "log_submission":
                slug = tool_use.input.get("story_slug", "")
                journal = tool_use.input.get("journal", "")
                notes = tool_use.input.get("notes", "")
                try:
                    storage.log_submission(slug, journal, outcome="pending", notes=notes)
                    result = f"Logged: '{journal}' saved to story file as pending."
                except Exception as e:
                    result = f"Could not log submission: {e}"
                yield f"\n*{result}*\n"

            elif tool_use.name == "get_cover_letter_template":
                tmpl_name = tool_use.input.get("name", "")
                yield f"\n*Loading '{tmpl_name}' cover letter template...*\n"
                tmpl = storage.load_template(tmpl_name)
                result = tmpl if tmpl else f"Template '{tmpl_name}' not found. Available: short, bio, ai."

            else:
                result = f"Unknown tool: {tool_use.name}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        full_messages = full_messages + [{"role": "user", "content": tool_results}]

    return full_messages, usage
