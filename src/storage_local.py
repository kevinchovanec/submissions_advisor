"""
Local file-based storage backend.

Stories → data/stories/*.md (Markdown + YAML frontmatter)
Templates → data/cover_letter_templates/*.md

When the Excel tracker exists, log_submission and update_outcome mirror writes
to it so the spreadsheet stays in sync.
"""

from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path

import frontmatter

from storage import StorageBackend

_ROOT = Path(__file__).parent.parent
STORIES_DIR = _ROOT / "data" / "stories"
TEMPLATES_DIR = _ROOT / "data" / "cover_letter_templates"


def _slug(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")


def _story_path(slug: str) -> Path:
    return STORIES_DIR / f"{slug}.md"


def _post_to_dict(slug: str, post: frontmatter.Post) -> dict:
    return {
        "slug": slug,
        "title": post.get("title", slug),
        "word_count": post.get("word_count"),
        "style": post.get("style", ""),
        "description": post.content,
        "submitted_to": post.get("submitted_to", []),
    }


def _save_post(path: Path, post: frontmatter.Post) -> None:
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


class StorageLocal(StorageBackend):
    """File-based backend. Optionally mirrors submission writes to the Excel tracker."""

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    def list_stories(self) -> list[dict]:
        STORIES_DIR.mkdir(parents=True, exist_ok=True)
        stories = []
        for path in sorted(STORIES_DIR.glob("*.md")):
            post = frontmatter.load(str(path))
            stories.append({
                "slug": path.stem,
                "title": post.get("title", path.stem),
                "word_count": post.get("word_count"),
                "style": post.get("style", ""),
                "submission_count": len(post.get("submitted_to", [])),
            })
        return sorted(stories, key=lambda s: s["title"].lower())

    def load_story(self, slug: str) -> dict | None:
        path = _story_path(slug)
        if not path.exists():
            return None
        post = frontmatter.load(str(path))
        return _post_to_dict(slug, post)

    def create_story(self, title: str, word_count: int | None, style: str, description: str) -> str:
        slug = _slug(title)
        STORIES_DIR.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            content=description,
            title=title,
            word_count=word_count,
            style=style,
            submitted_to=[],
        )
        _save_post(_story_path(slug), post)
        return slug

    def update_story(self, slug: str, word_count: int | None, style: str, description: str) -> None:
        path = _story_path(slug)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {slug}")
        post = frontmatter.load(str(path))
        post["word_count"] = word_count
        post["style"] = style
        post.content = description
        _save_post(path, post)

    # ------------------------------------------------------------------
    # Submissions
    # ------------------------------------------------------------------

    def log_submission(
        self,
        slug: str,
        journal: str,
        outcome: str = "pending",
        notes: str = "",
        sub_date: str | None = None,
    ) -> None:
        path = _story_path(slug)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {slug}")
        post = frontmatter.load(str(path))
        submissions = post.get("submitted_to", [])
        submissions.append({
            "journal": journal,
            "date": sub_date or _date.today().isoformat(),
            "outcome": outcome,
            "notes": notes,
        })
        post["submitted_to"] = submissions
        _save_post(path, post)
        self._mirror_add_submission(journal, post.get("title", slug), sub_date)

    def update_outcome(self, slug: str, journal: str, outcome: str, notes: str = "") -> None:
        path = _story_path(slug)
        if not path.exists():
            raise FileNotFoundError(f"Story not found: {slug}")
        post = frontmatter.load(str(path))
        submissions = post.get("submitted_to", [])
        for entry in reversed(submissions):
            if entry["journal"].lower() == journal.lower():
                entry["outcome"] = outcome
                if notes:
                    entry["notes"] = notes
                break
        post["submitted_to"] = submissions
        _save_post(path, post)
        self._mirror_update_outcome(journal, post.get("title", slug), outcome)

    def submitted_journals(self, slug: str) -> list[str]:
        path = _story_path(slug)
        if not path.exists():
            return []
        post = frontmatter.load(str(path))
        return [s["journal"] for s in post.get("submitted_to", [])]

    def list_all_pending(self) -> list[dict]:
        STORIES_DIR.mkdir(parents=True, exist_ok=True)
        pending = []
        for path in STORIES_DIR.glob("*.md"):
            post = frontmatter.load(str(path))
            title = post.get("title", path.stem)
            for s in post.get("submitted_to", []):
                if s.get("outcome") == "pending":
                    pending.append({
                        "story_title": title,
                        "slug": path.stem,
                        "journal": s["journal"],
                    })
        return pending

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def list_templates(self) -> list[dict]:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        templates = []
        for path in sorted(TEMPLATES_DIR.glob("*.md")):
            post = frontmatter.load(str(path))
            templates.append({
                "name": post.get("name", path.stem),
                "description": post.get("description", ""),
            })
        return templates

    def load_template(self, name: str) -> str | None:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMPLATES_DIR / f"{name}.md"
        if not path.exists():
            return None
        post = frontmatter.load(str(path))
        return post.content

    def save_template(self, name: str, content: str, description: str = "") -> None:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMPLATES_DIR / f"{name}.md"
        if path.exists():
            post = frontmatter.load(str(path))
            post.content = content
            if description:
                post["description"] = description
        else:
            post = frontmatter.Post(content=content, name=name, description=description)
        _save_post(path, post)

    # ------------------------------------------------------------------
    # Excel mirroring (local-only, no-ops if workbook absent)
    # ------------------------------------------------------------------

    def _workbook_path(self) -> Path | None:
        from workbook import WORKBOOK_PATH
        return WORKBOOK_PATH if WORKBOOK_PATH.exists() else None

    def _mirror_add_submission(self, journal: str, story_title: str, sub_date) -> None:
        wb_path = self._workbook_path()
        if wb_path is None:
            return
        try:
            from workbook import add_submission as wb_add
            wb_add(wb_path, journal, story_title, sub_date or _date.today())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Editor feedback (delegates to workbook when available)
    # ------------------------------------------------------------------

    def list_feedback(self) -> list[dict]:
        wb_path = self._workbook_path()
        if wb_path is None:
            return []
        try:
            from workbook import load as wb_load
            data = wb_load(wb_path)
            return [
                {
                    "journal": f.get("journal", ""),
                    "story": f.get("story", ""),
                    "date": f.get("date"),
                    "text": f.get("text", ""),
                }
                for f in data.get("feedback", [])
            ]
        except Exception:
            return []

    def add_feedback(self, journal: str, story: str, feedback_date, text: str) -> None:
        wb_path = self._workbook_path()
        if wb_path is None:
            raise FileNotFoundError("No workbook found — upload a submissions Excel file first.")
        from workbook import add_feedback as wb_add_fb
        wb_add_fb(wb_path, journal, story, text, feedback_date)

    def _mirror_update_outcome(self, journal: str, story_title: str, outcome: str) -> None:
        wb_path = self._workbook_path()
        if wb_path is None:
            return
        _raw_map = {
            "rejected": "Nope",
            "accepted": "Yep",
            "withdrawn": "Withdrawn",
        }
        raw_val = _raw_map.get(outcome)
        if raw_val is None:
            return
        try:
            from workbook import update_outcome as wb_update, add_submission as wb_add
            try:
                wb_update(wb_path, journal, story_title, raw_val)
            except ValueError:
                wb_add(wb_path, journal, story_title, _date.today(), raw_val)
        except Exception:
            pass
