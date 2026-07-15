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


def _safe_name(name: str) -> str:
    """Reject names that could escape the data directory via path traversal.

    Blocks path separators, '..', and null bytes — so a slug or template name
    coming from a URL can never resolve outside STORIES_DIR / TEMPLATES_DIR.
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(f"Invalid name: {name!r}")
    return name


def _story_path(slug: str) -> Path:
    return STORIES_DIR / f"{_safe_name(slug)}.md"


def _tracker_date(d) -> str:
    """Normalize a tracker date cell (datetime, date, or string) to an ISO date string."""
    if hasattr(d, "date"):
        return d.date().isoformat()
    if d:
        return str(d)[:10]
    return _date.today().isoformat()


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

    def update_outcome(self, slug: str, journal: str, outcome: str, notes: str = "", sub_date: str | None = None) -> None:
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
                if sub_date:
                    entry["date"] = sub_date
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
    # Tracker sync
    # ------------------------------------------------------------------

    def sync_from_tracker(self) -> dict:
        """Merge the Excel tracker into the story files.

        First creates cards for tracker stories that have none (word count and
        genre come from the Stories sheet when present), then merges submission
        history into every card. Matches stories by title and submissions by
        journal name (both case-insensitive), so re-running only adds what's
        missing. Returns {"created": n, "added": m}.
        """
        wb_path = self._workbook_path()
        if wb_path is None:
            raise FileNotFoundError("No workbook found — add a submissions Excel file to data/ first.")
        from workbook import load as wb_load, story_view

        data = wb_load(wb_path)
        view = story_view(data["journals"])
        STORIES_DIR.mkdir(parents=True, exist_ok=True)

        # Create cards for tracker stories that don't have one yet.
        existing_titles = {
            str(frontmatter.load(str(p)).get("title", p.stem)).strip().lower()
            for p in STORIES_DIR.glob("*.md")
        }
        sheet_rows = {s["title"].strip().lower(): s for s in data["stories"]}
        tracker_titles: dict[str, str] = {}  # normalized → display title
        for s in data["stories"]:
            tracker_titles.setdefault(s["title"].strip().lower(), s["title"])
        for title in view:
            tracker_titles.setdefault(title.strip().lower(), title)
        created_total = 0
        for norm, title in tracker_titles.items():
            slug = _slug(title)
            if norm in existing_titles or not slug or _story_path(slug).exists():
                continue
            row = sheet_rows.get(norm, {})
            word_count = row.get("word_count")
            try:
                word_count = int(word_count) if word_count is not None else None
            except (TypeError, ValueError):
                word_count = None
            self.create_story(title, word_count, row.get("genre") or "", "")
            existing_titles.add(norm)
            created_total += 1

        added_total = 0
        for path in STORIES_DIR.glob("*.md"):
            post = frontmatter.load(str(path))
            title = post.get("title", path.stem)
            story_subs = view.get(title) or next(
                (v for k, v in view.items() if k.strip().lower() == title.strip().lower()), None
            )
            if not story_subs:
                continue
            existing = post.get("submitted_to", [])
            seen = {s["journal"].strip().lower() for s in existing}
            added = 0
            for outcome, entries in story_subs.items():
                for e in entries:
                    if e["journal"].strip().lower() in seen:
                        continue
                    existing.append({
                        "journal": e["journal"],
                        "date": _tracker_date(e.get("date")),
                        "outcome": outcome,
                        "notes": "",
                    })
                    seen.add(e["journal"].strip().lower())
                    added += 1
            if added:
                post["submitted_to"] = existing
                _save_post(path, post)
                added_total += added
        return {"created": created_total, "added": added_total}

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
        path = TEMPLATES_DIR / f"{_safe_name(name)}.md"
        if not path.exists():
            return None
        post = frontmatter.load(str(path))
        return post.content

    def save_template(self, name: str, content: str, description: str = "") -> None:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMPLATES_DIR / f"{_safe_name(name)}.md"
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
                    "id": str(i),
                    "journal": f.get("journal", ""),
                    "story": f.get("story", ""),
                    "date": f.get("date"),
                    "text": f.get("text", ""),
                }
                for i, f in enumerate(data.get("feedback", []))
            ]
        except Exception:
            return []

    def add_feedback(self, journal: str, story: str, feedback_date, text: str) -> None:
        wb_path = self._workbook_path()
        if wb_path is None:
            raise FileNotFoundError("No workbook found — upload a submissions Excel file first.")
        from workbook import add_feedback as wb_add_fb
        wb_add_fb(wb_path, journal, story, text, feedback_date)

    def update_feedback(self, feedback_id: str, journal: str, story: str, feedback_date, text: str) -> None:
        raise NotImplementedError("Feedback editing is not supported in local mode.")

    def delete_feedback(self, feedback_id: str) -> None:
        raise NotImplementedError("Feedback deletion is not supported in local mode.")

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_story(self, slug: str) -> None:
        path = _story_path(slug)
        if path.exists():
            path.unlink()

    def delete_submission(self, slug: str, journal: str) -> None:
        path = _story_path(slug)
        if not path.exists():
            return
        post = frontmatter.load(str(path))
        submissions = post.get("submitted_to", [])
        for i in range(len(submissions) - 1, -1, -1):
            if submissions[i]["journal"].lower() == journal.lower():
                submissions.pop(i)
                break
        post["submitted_to"] = submissions
        _save_post(path, post)

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
