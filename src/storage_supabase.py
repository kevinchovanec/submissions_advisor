"""
Supabase storage backend.

Activated when SUPABASE_URL + SUPABASE_KEY env vars are present.
All queries are scoped to the authenticated user's user_id; row-level
security in Supabase enforces this at the database level as well.
"""

from __future__ import annotations

from datetime import date as _date

from storage import StorageBackend


class StorageSupabase(StorageBackend):
    """Cloud backend — stories, submissions, templates, and feedback in Supabase."""

    def __init__(self, client, user_id: str):
        self._client = client
        self._user_id = user_id

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    def list_stories(self) -> list[dict]:
        stories_res = (
            self._client.table("stories")
            .select("slug, title, word_count, style")
            .eq("user_id", self._user_id)
            .execute()
        )
        subs_res = (
            self._client.table("submissions")
            .select("story_slug")
            .eq("user_id", self._user_id)
            .execute()
        )
        counts: dict[str, int] = {}
        for s in subs_res.data:
            counts[s["story_slug"]] = counts.get(s["story_slug"], 0) + 1

        stories = [
            {
                "slug": s["slug"],
                "title": s["title"],
                "word_count": s.get("word_count"),
                "style": s.get("style", ""),
                "submission_count": counts.get(s["slug"], 0),
            }
            for s in stories_res.data
        ]
        return sorted(stories, key=lambda s: s["title"].lower())

    def load_story(self, slug: str) -> dict | None:
        story_res = (
            self._client.table("stories")
            .select("*")
            .eq("user_id", self._user_id)
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        if not story_res.data:
            return None
        s = story_res.data[0]

        subs_res = (
            self._client.table("submissions")
            .select("*")
            .eq("user_id", self._user_id)
            .eq("story_slug", slug)
            .order("sub_date")
            .execute()
        )
        return {
            "slug": s["slug"],
            "title": s["title"],
            "word_count": s.get("word_count"),
            "style": s.get("style", ""),
            "description": s.get("description", ""),
            "submitted_to": [
                {
                    "journal": sub["journal"],
                    "date": str(sub["sub_date"]),
                    "outcome": sub["outcome"],
                    "notes": sub.get("notes", ""),
                }
                for sub in subs_res.data
            ],
        }

    def create_story(self, title: str, word_count: int | None, style: str, description: str) -> str:
        slug = _make_slug(title)
        self._client.table("stories").insert({
            "user_id": self._user_id,
            "slug": slug,
            "title": title,
            "word_count": word_count,
            "style": style,
            "description": description,
        }).execute()
        return slug

    def update_story(self, slug: str, word_count: int | None, style: str, description: str) -> None:
        self._client.table("stories").update({
            "word_count": word_count,
            "style": style,
            "description": description,
        }).eq("user_id", self._user_id).eq("slug", slug).execute()

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
        self._client.table("submissions").insert({
            "user_id": self._user_id,
            "story_slug": slug,
            "journal": journal,
            "sub_date": sub_date or _date.today().isoformat(),
            "outcome": outcome,
            "notes": notes,
        }).execute()

    def update_outcome(self, slug: str, journal: str, outcome: str, notes: str = "", sub_date: str | None = None) -> None:
        res = (
            self._client.table("submissions")
            .select("id")
            .eq("user_id", self._user_id)
            .eq("story_slug", slug)
            .ilike("journal", journal)
            .order("sub_date", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return
        update: dict = {"outcome": outcome}
        if notes:
            update["notes"] = notes
        if sub_date:
            update["sub_date"] = sub_date
        self._client.table("submissions").update(update).eq("id", res.data[0]["id"]).execute()

    def submitted_journals(self, slug: str) -> list[str]:
        res = (
            self._client.table("submissions")
            .select("journal")
            .eq("user_id", self._user_id)
            .eq("story_slug", slug)
            .execute()
        )
        return [s["journal"] for s in res.data]

    def list_all_pending(self) -> list[dict]:
        subs_res = (
            self._client.table("submissions")
            .select("story_slug, journal")
            .eq("user_id", self._user_id)
            .eq("outcome", "pending")
            .execute()
        )
        story_titles = {s["slug"]: s["title"] for s in self.list_stories()}
        return [
            {
                "story_title": story_titles.get(s["story_slug"], s["story_slug"]),
                "slug": s["story_slug"],
                "journal": s["journal"],
            }
            for s in subs_res.data
        ]

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def list_templates(self) -> list[dict]:
        # Repo defaults (committed files — shared by all users)
        from cover_letters import list_templates as _repo_templates
        repo = {t["name"]: t for t in _repo_templates()}

        # User-saved templates in Supabase override repo defaults
        res = (
            self._client.table("templates")
            .select("name, description")
            .eq("user_id", self._user_id)
            .execute()
        )
        for t in res.data:
            repo[t["name"]] = {"name": t["name"], "description": t.get("description", "")}

        return sorted(repo.values(), key=lambda t: t["name"])

    def load_template(self, name: str) -> str | None:
        # User-saved template takes precedence
        res = (
            self._client.table("templates")
            .select("content")
            .eq("user_id", self._user_id)
            .eq("name", name)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["content"]
        # Fall back to committed repo default
        from cover_letters import load_template as _repo_load
        return _repo_load(name)

    def save_template(self, name: str, content: str, description: str = "") -> None:
        self._client.table("templates").upsert({
            "user_id": self._user_id,
            "name": name,
            "description": description,
            "content": content,
        }).execute()

    # ------------------------------------------------------------------
    # Editor feedback
    # ------------------------------------------------------------------

    def list_feedback(self) -> list[dict]:
        res = (
            self._client.table("feedback")
            .select("*")
            .eq("user_id", self._user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [
            {
                "journal": f["journal"],
                "story": f.get("story", ""),
                "date": f.get("feedback_date"),
                "text": f.get("feedback_text", ""),
            }
            for f in res.data
        ]

    def add_feedback(self, journal: str, story: str, feedback_date, text: str) -> None:
        self._client.table("feedback").insert({
            "user_id": self._user_id,
            "journal": journal,
            "story": story,
            "feedback_date": str(feedback_date) if feedback_date else None,
            "feedback_text": text,
        }).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slug(title: str) -> str:
    import re
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")
