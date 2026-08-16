"""Shared fixtures. Nothing here touches the network or the Anthropic API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from storage import StorageBackend  # noqa: E402


class FakeStorage(StorageBackend):
    """In-memory backend so agent behaviour can be tested without files or Supabase."""

    def __init__(self, stories: list[dict] | None = None, templates: list[dict] | None = None):
        self._stories = {s["slug"]: s for s in (stories or [])}
        self._templates = templates if templates is not None else [
            {"name": "short", "description": "Short and plain"},
        ]
        self.logged: list[tuple[str, str, str, str]] = []
        self.log_should_raise = False

    # --- stories -------------------------------------------------------
    def list_stories(self) -> list[dict]:
        return sorted(
            (
                {
                    "slug": s["slug"],
                    "title": s["title"],
                    "word_count": s.get("word_count"),
                    "style": s.get("style", ""),
                    "description": s.get("description", ""),
                    "submission_count": len(s.get("submitted_to", [])),
                }
                for s in self._stories.values()
            ),
            key=lambda s: s["title"].lower(),
        )

    def load_story(self, slug: str) -> dict | None:
        return self._stories.get(slug)

    def create_story(self, title, word_count, style, description) -> str:
        slug = title.lower().replace(" ", "-")
        self._stories[slug] = {
            "slug": slug, "title": title, "word_count": word_count,
            "style": style, "description": description, "submitted_to": [],
        }
        return slug

    def update_story(self, slug, word_count, style, description) -> None:
        self._stories[slug].update(
            word_count=word_count, style=style, description=description
        )

    # --- submissions ---------------------------------------------------
    def log_submission(self, slug, journal, outcome="pending", notes="", sub_date=None) -> None:
        if self.log_should_raise:
            raise RuntimeError("disk on fire")
        self.logged.append((slug, journal, outcome, notes))
        self._stories[slug].setdefault("submitted_to", []).append(
            {"journal": journal, "date": sub_date or "2026-08-11", "outcome": outcome, "notes": notes}
        )

    def update_outcome(self, slug, journal, outcome, notes="", sub_date=None) -> None:
        for s in reversed(self._stories[slug].get("submitted_to", [])):
            if s["journal"].lower() == journal.lower():
                s.update(outcome=outcome, notes=notes)
                return

    def submitted_journals(self, slug) -> list[str]:
        return [s["journal"] for s in self._stories.get(slug, {}).get("submitted_to", [])]

    def list_all_pending(self) -> list[dict]:
        out = []
        for s in self._stories.values():
            for sub in s.get("submitted_to", []):
                if sub.get("outcome") == "pending":
                    out.append({"story_title": s["title"], "slug": s["slug"], "journal": sub["journal"]})
        return out

    # --- templates -----------------------------------------------------
    def list_templates(self) -> list[dict]:
        return self._templates

    def load_template(self, name) -> str | None:
        return "Dear editors," if any(t["name"] == name for t in self._templates) else None

    def save_template(self, name, content, description="") -> None:
        self._templates.append({"name": name, "description": description})

    # --- feedback ------------------------------------------------------
    def list_feedback(self) -> list[dict]:
        return []

    def add_feedback(self, journal, story, feedback_date, text) -> None: ...
    def update_feedback(self, feedback_id, journal, story, feedback_date, text) -> None: ...
    def delete_feedback(self, feedback_id) -> None: ...

    # --- deletion ------------------------------------------------------
    def delete_story(self, slug) -> None:
        self._stories.pop(slug, None)

    def delete_submission(self, slug, journal) -> None: ...


@pytest.fixture
def stories() -> list[dict]:
    """Three stories: one out on submission, one clean, one long."""
    return [
        {
            "slug": "mediocrity", "title": "A Mediocrity of Virtue", "word_count": 3988,
            "style": "dry domestic realism", "description": "Caleb has a bad day.",
            "submitted_to": [
                {"journal": "Georgia Review", "date": "2025-12-09", "outcome": "pending", "notes": ""},
                {"journal": "New England Review", "date": "2026-03-20", "outcome": "rejected", "notes": ""},
            ],
        },
        {
            "slug": "what-was-left", "title": "What Was Left", "word_count": 1200,
            "style": "flash", "description": "A short one.", "submitted_to": [],
        },
        {
            "slug": "staging", "title": "All the World is Staging", "word_count": 9500,
            "style": "maximalist comedy", "description": "A long one.", "submitted_to": [],
        },
    ]


@pytest.fixture
def storage(stories) -> FakeStorage:
    return FakeStorage(stories)


@pytest.fixture
def journals() -> list[dict]:
    """Ranked journals. 'The Georgia Review' differs from the pending entry's
    'Georgia Review' so normalization is exercised."""
    return [
        {
            "rank": 1, "normalized_name": "georgia review", "display_name": "The Georgia Review",
            "journal_url": "https://garev.example/submissions", "score": 92, "tier": "Tier 1",
        },
        {
            "rank": 2, "normalized_name": "other mag", "display_name": "Other Mag",
            "journal_url": "https://othermag.example/", "score": 55, "tier": "Tier 2",
        },
        {
            "rank": 3, "normalized_name": "third place", "display_name": "Third Place",
            "journal_url": "", "score": 30, "tier": "Tier 3",
        },
    ]


@pytest.fixture
def isolated_summaries(tmp_path, monkeypatch):
    """Point the summary cache at a temp dir so tests never touch data/."""
    import summarize_journals as sj

    monkeypatch.setattr(sj, "SUMMARIES_PATH", tmp_path / "journal_summaries.json")
    monkeypatch.setattr(sj, "META_PATH", tmp_path / "journal_cache_meta.json")
    monkeypatch.setattr(sj, "PAGES_DIR", tmp_path / "journal_pages")
    return sj
