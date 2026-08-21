"""
Conversational agent for story-to-journal matching.
Uses Claude with tool use for on-demand page fetching and editor feedback lookup.
"""

import os
from typing import Generator

import anthropic

from ingest import normalize_name
from models_config import AGENT_THINKING, MODEL
from pagefetch import fetch_page
from storage import StorageBackend, format_pending_for_context, format_story_for_agent
from summarize_journals import format_details, load_summaries_for, load_urls_for
from workbook import format_feedback_brief, get_feedback_for_journal

MAX_PAGE_CHARS = 8000

# The tool loop is driven by the model, so it needs hard stops: without them a
# model that keeps calling fetch_page bills the user's own API key indefinitely.
MAX_TOOL_ITERATIONS = 12
MAX_FETCHES_PER_TURN = 8

SYSTEM_PROMPT = """You are a literary advisor helping a writer find the best journals for their short fiction.

You have access to a ranked list of literary journals that are currently open for submissions, \
ordered by a weighted prestige score (prize wins, circulation, and pay). Higher rank = more prestigious.

When making recommendations:
- NEVER recommend a journal where the writer already has a submission under review. These are \
  marked "⛔ UNDER REVIEW" in the journal list and enumerated in the opening context. Before naming \
  any journal, re-check it against that list — suggesting one wastes a simultaneous-submission slot \
  and can burn the writer's standing with that editor. Mention such a journal only if the writer \
  explicitly asks about it.
- Some journal entries include a cached summary of their guidelines — use those to shortlist. Most \
  entries have no summary yet, so for those the ranked list gives you only a name and a URL.
- Use the fetch_page tool to verify the 2-3 journals you're seriously considering, not for every journal
- If a journal appears in the editor feedback list, call get_editor_feedback before recommending it \
  so you can factor in what the editor actually said
- Focus on fit: aesthetic match, thematic alignment, length requirements, any red flags
- Be honest about reach vs. likelihood — Tier 1 journals are worth trying but competition is fierce
- Ask follow-up questions if you need more about the story to give good advice
- You can discuss submission strategy, style comparisons, comp titles, or anything else useful

Reading a journal's site:
- Call get_journal_details FIRST for any journal you're seriously considering. It's far cheaper \
  than fetching a page, and for summarized journals it already has the word limit, reading \
  period, response time, and submission policies.
- The URL in the ranked list is often the guidelines page, but not always — some are bare \
  homepages and a few point at a contact page. Every page you fetch ends with a list of same-site \
  links; follow them when the page you landed on doesn't answer the question.
- If the page doesn't establish both the aesthetic and the length limits, follow up to two of \
  those links. Prefer anything named submissions, guidelines, about, masthead, or "what we're \
  looking for". Stop as soon as you can state the length limit and the aesthetic.
- You have a budget of a few page fetches per turn. Spend it on the finalists, and say so plainly \
  if you couldn't establish something rather than guessing at it.
- Do not invent URLs by pattern. Use the links you were given, or the URL from the ranked list.

Working across several stories:
- Several stories may be loaded at once, each with a full card. Stories in the portfolio roster \
  are listed one line each — call get_story to read one properly before recommending journals for it.
- NEVER send two stories to the same journal in the same round. Most journals forbid concurrent \
  submissions from one author, so a slate must give each journal at most one story.
- When placing several stories, don't try to cover every story exhaustively. Lead with the \
  matches you're most confident about and say which stories you'd hold back and why.
- If a roster story fits a journal better than any loaded story, say so and offer to load it.
- log_submission only works for stories loaded in this conversation. Don't attempt it for a \
  roster story — ask the writer to load it first.

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


GET_JOURNAL_DETAILS_TOOL = {
    "name": "get_journal_details",
    "description": (
        "Look up cached structured detail for a journal: word limit, reading period, "
        "response time, simultaneous- and multiple-submission policy, fee, and red flags. "
        "Much cheaper than fetch_page, so try this first for any journal you're seriously "
        "considering. Returns nothing if the journal hasn't been summarized yet, in which "
        "case use fetch_page."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "journal": {
                "type": "string",
                "description": "Journal name as it appears in the ranked list",
            },
        },
        "required": ["journal"],
    },
}

GET_STORY_TOOL = {
    "name": "get_story",
    "description": (
        "Fetch the full card for one of the writer's stories — description, word count, "
        "style, and complete submission history. The stories loaded into this conversation "
        "are already described in full; use this to read a story listed in the portfolio "
        "roster before recommending journals for it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Story slug exactly as shown in the roster"},
        },
        "required": ["slug"],
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


def _fetch_page(url: str) -> tuple[str, bool]:
    """Fetch a page for the model. Returns (content, is_error).

    Content ends with the page's same-site links, which is the only way the model can
    navigate: get_text() drops every href, and the rankings cache gives one URL per
    journal. SSRF validation and per-hop redirect re-checking live in pagefetch.
    """
    return fetch_page(url, max_chars=MAX_PAGE_CHARS).as_tool_result()


def _format_journal_list(
    journals: list[dict],
    summaries: dict[str, str],
    pending_by_norm: dict[str, str] | None = None,
    best_urls: dict[str, str] | None = None,
) -> str:
    lines = []
    pending_by_norm = pending_by_norm or {}
    best_urls = best_urls or {}
    for j in sorted(journals, key=lambda x: x["rank"]):
        # Prefer the page a cached summary was actually built from: the rankings URL is
        # sometimes a contact page, and the summarizer records where it found the real
        # guidelines. about_url/submit_url are unpopulated in practice but kept as
        # fallbacks in case a CSV/HTML import supplies them.
        url = (
            best_urls.get(j["normalized_name"])
            or j.get("journal_url")
            or j.get("about_url")
            or j.get("submit_url")
            or "no URL"
        )
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


def _build_journal_context(
    journals: list[dict],
    pending: list[dict],
    genre_mode: str = "Literary",
) -> str:
    """The large, story-independent block: the ranked journal list.

    Kept separate from story context and placed first in the opening message so it
    can carry the cache breakpoint — changing the story selection must not
    invalidate it.
    """
    summaries = load_summaries_for(journals)
    best_urls = load_urls_for(journals)
    summarized = sum(1 for j in journals if j["normalized_name"] in summaries)
    # Flag pending-submission journals inline in the ranked list, where the
    # model reads candidates — the separate pending block alone gets overlooked.
    pending_by_norm = {
        normalize_name(p["journal"]): p["story_title"] for p in pending
    }
    journal_list = _format_journal_list(journals, summaries, pending_by_norm, best_urls)
    note = f" ({summarized} with cached summaries)" if summarized else ""
    genre_note = f" [Genre mode: {genre_mode}]"
    return (
        f"Here are the {len(journals)} {genre_mode.lower()} journals currently open for "
        f"submissions{note}{genre_note}, ranked by prestige score:\n\n{journal_list}"
    )


def _build_story_context(
    storage: StorageBackend,
    story_context: str,
    roster_context: str,
    pending: list[dict],
    editor_feedback: list[dict],
) -> str:
    """The smaller, selection-dependent block: stories, pending, feedback, templates.

    Placed after the journal block so a change here leaves that cache entry intact.
    """
    parts = []
    if story_context:
        parts.append(story_context)
    if roster_context:
        parts.append(roster_context)
    pending_block = format_pending_for_context(pending)
    if pending_block:
        parts.append(pending_block)
    feedback_brief = format_feedback_brief(editor_feedback) if editor_feedback else ""
    if feedback_brief:
        parts.append(feedback_brief)
    templates = storage.list_templates()
    if templates:
        tmpl_lines = ["Cover letter templates available (call get_cover_letter_template to fetch):"]
        for t in templates:
            tmpl_lines.append(f"- {t['name']}: {t['description']}")
        parts.append("\n".join(tmpl_lines))
    parts.append(
        "What would you like to discuss? Tell me about your story and I'll help you "
        "find the best matches."
    )
    return "\n\n".join(parts)


def stream_response(
    api_history: list[dict],
    new_user_message: str,
    journals: list[dict],
    storage: StorageBackend,
    story_context: str | None = None,
    roster_context: str = "",
    pending: list[dict] | None = None,
    editor_feedback: list[dict] | None = None,
    genre_mode: str = "Literary",
    api_key: str | None = None,
    allowed_slugs: set[str] | None = None,
) -> Generator[str, None, tuple[list[dict], dict]]:
    """
    Stream Claude's response. Handles multi-turn tool use internally.
    Yields text chunks for display. Returns the updated full API history.

    api_history:    full message history from previous turns (sent by the client).
    journals:       matched ranked journals (used only on first turn).
    story_context:  full cards for the selected stories (storage.format_selected_stories).
    roster_context: one-line-per-story roster of everything not selected.
    pending:        raw cross-story pending list; drives both the inline ⛔ markers in
                    the ranked list and the standalone warning block, so those two
                    can't disagree.
    editor_feedback: raw feedback list (first turn: brief list in context; on demand:
                    full text via get_editor_feedback).
    allowed_slugs:  slugs log_submission may write to — the selected set. Anything
                    else is rejected so a misattributed submission can't be written
                    to the wrong story.
    """
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    _feedback = editor_feedback or []
    _pending = pending or []
    _allowed = allowed_slugs if allowed_slugs is not None else None

    if not api_history:
        journal_block = _build_journal_context(journals, _pending, genre_mode)
        story_block = _build_story_context(
            storage, story_context or "", roster_context, _pending, _feedback
        )
        ack = (
            "I've loaded your story details and the open journal list. "
            "I can see what you've already submitted to and won't suggest those. "
            "What would you like to work on?"
            if story_context
            else "I've got your journal list — I can see the open submissions ranked by "
            "prestige score. Tell me about your story and I'll help you find the best matches."
        )
        # Two blocks, journal list first: it is the large, story-independent one, so
        # it carries the cache breakpoint and survives a change of story selection.
        # The 1h TTL covers the long think-time gaps typical of a Discuss session.
        api_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": journal_block,
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    },
                    {"type": "text", "text": f"---\n\n{story_block}"},
                ],
            },
            {"role": "assistant", "content": ack},
        ]

    full_messages = api_history + [{"role": "user", "content": new_user_message}]
    # No cache_control here: render order is tools -> system -> messages, so the
    # breakpoint on the journal block already covers the system prompt. A separate
    # breakpoint would also never create an entry — the prompt is under the
    # 1024-token minimum cacheable prefix.
    system = SYSTEM_PROMPT
    tools = [
        FETCH_TOOL,
        GET_JOURNAL_DETAILS_TOOL,
        GET_EDITOR_FEEDBACK_TOOL,
        LOG_SUBMISSION_TOOL,
        GET_COVER_LETTER_TEMPLATE_TOOL,
        GET_STORY_TOOL,
    ]

    # Accumulated token usage across every model call in this turn (incl. tool loops).
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    fetches_used = 0
    wrote_data = False

    for _iteration in range(MAX_TOOL_ITERATIONS):
        # Streaming, not messages.create: text is yielded token-by-token as it
        # generates, instead of a whole paragraph landing at once when the block
        # completes. get_final_message() then gives the assembled message for the
        # tool_use blocks, usage, and stop_reason.
        with client.messages.stream(
            model=MODEL,
            # Thinking shares this budget with the reply, so it is set well above what
            # the visible answer needs. Streaming means a large ceiling costs nothing
            # in latency or timeout risk — only tokens actually generated are billed.
            max_tokens=16000,
            thinking=AGENT_THINKING,
            system=system,
            tools=tools,
            messages=full_messages,
        ) as stream:
            # Iterating raw events rather than stream.text_stream so thinking can be
            # announced. Thinking blocks stream with empty text by default, so
            # text_stream yields nothing at all while the model reasons — which reads
            # as a frozen UI for several seconds on the first turn, when the whole
            # journal list is also being written to cache.
            announced_thinking = False
            for event in stream:
                if (
                    event.type == "content_block_start"
                    and getattr(event.content_block, "type", None) == "thinking"
                    and not announced_thinking
                ):
                    announced_thinking = True
                    yield "\n*Thinking...*\n"
                elif (
                    event.type == "content_block_delta"
                    and getattr(event.delta, "type", None) == "text_delta"
                ):
                    yield event.delta.text
            response = stream.get_final_message()

        u = response.usage
        usage["input_tokens"] += u.input_tokens or 0
        usage["output_tokens"] += u.output_tokens or 0
        usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        # Text was already streamed above; only the tool calls still need collecting.
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        # Plain dicts, not SDK block objects: the history is JSON-serialized
        # into the SSE done event and round-tripped through the client.
        content_dicts = [block.model_dump(mode="json", exclude_none=True) for block in response.content]
        full_messages = full_messages + [{"role": "assistant", "content": content_dicts}]

        if response.stop_reason == "max_tokens":
            yield "\n\n*(Response hit the length limit and was cut off — ask me to continue.)*\n"
            break

        if not tool_uses:
            break

        tool_results = []
        for tool_use in tool_uses:
            is_error = False

            if tool_use.name == "fetch_page":
                url = tool_use.input.get("url", "")
                journal_name = tool_use.input.get("journal_name", url)
                if fetches_used >= MAX_FETCHES_PER_TURN:
                    result = (
                        f"Page-fetch budget for this turn is used up "
                        f"({MAX_FETCHES_PER_TURN} pages). Work from what you've already read, "
                        "or ask the writer which journal to look at next."
                    )
                    is_error = True
                    yield f"\n*Fetch budget reached ({MAX_FETCHES_PER_TURN} pages).*\n"
                else:
                    fetches_used += 1
                    yield f"\n*Reading {journal_name} ({fetches_used}/{MAX_FETCHES_PER_TURN})...*\n"
                    result, is_error = _fetch_page(url)

            elif tool_use.name == "get_journal_details":
                journal = tool_use.input.get("journal", "")
                yield f"\n*Checking cached guidelines for {journal}...*\n"
                result = format_details(normalize_name(journal))
                if result is None:
                    result = (
                        f"No cached guidelines detail for '{journal}'. Use fetch_page on its "
                        "URL from the ranked list, then follow a same-site link if that page "
                        "doesn't cover length limits and aesthetic."
                    )
                    is_error = True

            elif tool_use.name == "get_editor_feedback":
                journal = tool_use.input.get("journal", "")
                yield f"\n*Checking editor notes for {journal}...*\n"
                result = get_feedback_for_journal(_feedback, journal)

            elif tool_use.name == "get_story":
                slug = tool_use.input.get("slug", "")
                yield f"\n*Reading story card for '{slug}'...*\n"
                story = storage.load_story(slug)
                if story is None:
                    result = (
                        f"No story with slug '{slug}'. Use a slug exactly as it appears "
                        "in the portfolio roster."
                    )
                    is_error = True
                else:
                    result = format_story_for_agent(story, heading="Story")

            elif tool_use.name == "log_submission":
                slug = tool_use.input.get("story_slug", "")
                journal = tool_use.input.get("journal", "")
                notes = tool_use.input.get("notes", "")
                if _allowed is not None and slug not in _allowed:
                    # Guards against a misattributed submission being written to the
                    # wrong story file when several stories are in context.
                    result = (
                        f"'{slug}' is not one of the stories loaded in this conversation, so "
                        "nothing was logged. Loaded stories: "
                        f"{', '.join(sorted(_allowed)) or '(none)'}. Ask the writer to load "
                        "that story before logging a submission for it."
                    )
                    is_error = True
                    yield f"\n*Not logged — '{slug}' isn't loaded in this conversation.*\n"
                else:
                    try:
                        storage.log_submission(slug, journal, outcome="pending", notes=notes)
                        result = f"Logged: '{journal}' saved to story file as pending."
                        wrote_data = True
                    except Exception as e:
                        result = f"Could not log submission: {e}"
                        is_error = True
                    yield f"\n*{result}*\n"

            elif tool_use.name == "get_cover_letter_template":
                tmpl_name = tool_use.input.get("name", "")
                yield f"\n*Loading '{tmpl_name}' cover letter template...*\n"
                tmpl = storage.load_template(tmpl_name)
                if tmpl:
                    result = tmpl
                else:
                    result = f"Template '{tmpl_name}' not found. Available: short, bio, ai."
                    is_error = True

            else:
                result = f"Unknown tool: {tool_use.name}"
                is_error = True

            block = {
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            }
            if is_error:
                # Without this the model can't tell a failed fetch from a page whose
                # text happens to say it couldn't be read.
                block["is_error"] = True
            tool_results.append(block)

        full_messages = full_messages + [{"role": "user", "content": tool_results}]
    else:
        yield (
            f"\n\n*(Stopped after {MAX_TOOL_ITERATIONS} tool rounds to avoid running away. "
            "Ask me to continue if I hadn't finished.)*\n"
        )

    usage["wrote_data"] = wrote_data
    return full_messages, usage
