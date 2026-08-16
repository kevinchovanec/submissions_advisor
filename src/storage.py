"""
Abstract storage backend interface.

Local mode (default): files in data/stories/, templates in data/cover_letter_templates/.
Cloud mode (Phase C): Supabase tables, activated when SUPABASE_URL + SUPABASE_KEY are set.
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Uniform interface over file-based and cloud storage."""

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    @abstractmethod
    def list_stories(self) -> list[dict]:
        """Return summary dicts sorted by title.
        Each dict: {slug, title, word_count, style, description, submission_count}
        """

    @abstractmethod
    def load_story(self, slug: str) -> dict | None:
        """Return full story dict or None if not found.
        Dict keys: slug, title, word_count, style, description, submitted_to
        submitted_to entries: {journal, date, outcome, notes}
        """

    @abstractmethod
    def create_story(self, title: str, word_count: int | None, style: str, description: str) -> str:
        """Create a new story and return its slug."""

    @abstractmethod
    def update_story(self, slug: str, word_count: int | None, style: str, description: str) -> None:
        """Update metadata and description of an existing story."""

    # ------------------------------------------------------------------
    # Submissions
    # ------------------------------------------------------------------

    @abstractmethod
    def log_submission(
        self,
        slug: str,
        journal: str,
        outcome: str = "pending",
        notes: str = "",
        sub_date: str | None = None,
    ) -> None:
        """Append a submission record. sub_date: ISO string; defaults to today."""

    @abstractmethod
    def update_outcome(self, slug: str, journal: str, outcome: str, notes: str = "", sub_date: str | None = None) -> None:
        """Update the most recent submission to journal for slug."""

    @abstractmethod
    def submitted_journals(self, slug: str) -> list[str]:
        """Return journal names this story has been submitted to."""

    @abstractmethod
    def list_all_pending(self) -> list[dict]:
        """Return all pending submissions across every story.
        Each dict: {story_title, slug, journal}
        """

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @abstractmethod
    def list_templates(self) -> list[dict]:
        """Return [{name, description}] for all available templates."""

    @abstractmethod
    def load_template(self, name: str) -> str | None:
        """Return template body text, or None if not found."""

    @abstractmethod
    def save_template(self, name: str, content: str, description: str = "") -> None:
        """Create or overwrite a named template."""

    # ------------------------------------------------------------------
    # Editor feedback
    # ------------------------------------------------------------------

    @abstractmethod
    def list_feedback(self) -> list[dict]:
        """Return all editor feedback notes.
        Each dict: {journal, story, date, text}
        """

    @abstractmethod
    def add_feedback(self, journal: str, story: str, feedback_date, text: str) -> None:
        """Append an editor feedback note."""

    @abstractmethod
    def update_feedback(self, feedback_id: str, journal: str, story: str, feedback_date, text: str) -> None:
        """Update an existing feedback note by id."""

    @abstractmethod
    def delete_feedback(self, feedback_id: str) -> None:
        """Delete a feedback note by id."""

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    @abstractmethod
    def delete_story(self, slug: str) -> None:
        """Delete a story and all its submissions."""

    @abstractmethod
    def delete_submission(self, slug: str, journal: str) -> None:
        """Delete the most recent submission to journal for story slug."""

    # ------------------------------------------------------------------
    # Tracker sync (local mode only)
    # ------------------------------------------------------------------

    def sync_from_tracker(self) -> dict:
        """Merge the local Excel tracker into story records.

        Creates story records for tracker stories that have none, then merges
        submission history into all of them. Matches stories by title and
        submissions by journal name (both case-insensitive), so re-running only
        adds what's missing. Returns {"created": n, "added": m}. Available in
        local mode only.
        """
        raise NotImplementedError("Tracker sync is only available in local mode.")


# ---------------------------------------------------------------------------
# Agent context formatting helpers (pure functions, not backend-specific)
# ---------------------------------------------------------------------------

def format_story_for_agent(story: dict, heading: str = "Active story") -> str:
    """Format a story dict as the agent's opening context block."""
    lines = [
        f"## {heading}: {story['title']}",
        f"Story slug (use this when calling log_submission): {story['slug']}",
        f"Word count: {story.get('word_count') or 'unknown'}",
        f"Style: {story.get('style') or 'not specified'}",
        "",
        "Description:",
        story.get("description", "").strip() or "(no description)",
    ]
    submissions = story.get("submitted_to", [])
    if submissions:
        lines += ["", "Previous submissions (do not suggest these journals):"]
        for s in submissions:
            note = f" — {s['notes']}" if s.get("notes") else ""
            lines.append(f"  - {s['journal']} ({s['date']}, {s['outcome']}){note}")
    return "\n".join(lines)


def format_pending_for_context(pending: list[dict]) -> str:
    """Format all-pending list as the agent's cross-story context block."""
    if not pending:
        return ""
    lines = [
        "IMPORTANT — journals with a submission currently under review. NEVER recommend "
        "any of these (for any story) unless the writer explicitly asks about them. "
        "Re-check every recommendation you make against this list:"
    ]
    for p in pending:
        lines.append(f"  - {p['journal']} ({p['story_title']})")
    return "\n".join(lines)


def format_selected_stories(stories: list[dict], primary_slug: str | None = None) -> str:
    """Format the in-context working set: one full card per selected story.

    A single story renders exactly as `format_story_for_agent` did, so one-story
    conversations are unchanged. Multiple stories get a header naming the primary,
    which is the log_submission default and the conversation-save key.
    """
    if not stories:
        return ""
    if len(stories) == 1:
        return format_story_for_agent(stories[0])

    primary = primary_slug or stories[0]["slug"]
    parts = [
        f"## {len(stories)} stories are loaded for this conversation "
        f"(primary: {primary}).\n"
        "Each is described in full below. When you recommend journals, treat these as a "
        "set: no journal may take two of them in the same round."
    ]
    parts.extend(format_story_for_agent(s, heading="Story") for s in stories)
    return "\n\n".join(parts)


def format_story_roster(
    stories: list[dict],
    pending: list[dict],
    exclude_slugs: set[str] | None = None,
) -> str:
    """Format the one-line-per-story roster of everything *not* loaded in full.

    Deliberately carries submission counts and pending journals only, never full
    history — that keeps this block O(stories) rather than O(submissions), which
    matters because submission history only ever grows.
    """
    exclude_slugs = exclude_slugs or set()
    rows = [s for s in stories if s["slug"] not in exclude_slugs]
    if not rows:
        return ""

    out_by_slug: dict[str, list[str]] = {}
    for p in pending:
        out_by_slug.setdefault(p["slug"], []).append(p["journal"])

    lines = [
        "## Other stories in the writer's portfolio (summary only)",
        "These are NOT loaded in full. Use them to suggest a better-suited story than the "
        "ones loaded — call get_story to read one properly before recommending journals for "
        "it, and never log a submission against a story that isn't loaded.",
        "",
    ]
    for s in rows:
        wc = f"{s['word_count']:,}w" if s.get("word_count") else "length unknown"
        style = s.get("style") or "style not specified"
        desc = (s.get("description") or "").strip().replace("\n", " ") or "(no description)"
        line = f"- {s['slug']} | \"{s['title']}\" ({wc}; {style}) — {desc}"
        sent = s.get("submission_count") or 0
        if sent:
            line += f" [{sent} sent]"
        out = out_by_slug.get(s["slug"])
        if out:
            line += f" [OUT NOW: {', '.join(out)}]"
        lines.append(line)
    return "\n".join(lines)
