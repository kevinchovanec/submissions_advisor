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
        Each dict: {slug, title, word_count, style, submission_count}
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

def format_story_for_agent(story: dict) -> str:
    """Format a story dict as the agent's opening context block."""
    lines = [
        f"## Active story: {story['title']}",
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
        "Journals with a submission currently under review (any story — "
        "do not suggest these unless the writer explicitly asks about them):"
    ]
    for p in pending:
        lines.append(f"  - {p['journal']} ({p['story_title']})")
    return "\n".join(lines)
