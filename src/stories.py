"""
Story memory: reads and writes per-story Markdown files with YAML frontmatter.
Files live in data/stories/, one per story, named by slug.

File format:
---
title: "The Glass Wall"
word_count: 4200
style: "lyric realism, second person"
submitted_to:
  - journal: "The Sun"
    date: "2026-01-15"
    outcome: pending   # pending | rejected | accepted | withdrawn
    notes: ""
---

Free-prose description of the story...
"""

import re
from datetime import date
from pathlib import Path

import frontmatter

STORIES_DIR = Path(__file__).parent.parent / "data" / "stories"
OUTCOMES = ["pending", "rejected", "accepted", "withdrawn"]


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _slug(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")


def _empty_story(title: str) -> frontmatter.Post:
    post = frontmatter.Post(
        content="",
        title=title,
        word_count=None,
        style="",
        submitted_to=[],
    )
    return post


def _story_path(slug: str) -> Path:
    return STORIES_DIR / f"{slug}.md"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_stories() -> list[dict]:
    """Return summary dicts for all stories, sorted by title."""
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


def load_story(slug: str) -> frontmatter.Post | None:
    path = _story_path(slug)
    if not path.exists():
        return None
    return frontmatter.load(str(path))


def save_story(slug: str, post: frontmatter.Post) -> None:
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    with open(_story_path(slug), "wb") as f:
        frontmatter.dump(post, f)


def create_story(title: str, word_count: int | None, style: str, description: str) -> str:
    """Create a new story file. Returns the slug."""
    slug = _slug(title)
    post = frontmatter.Post(
        content=description,
        title=title,
        word_count=word_count,
        style=style,
        submitted_to=[],
    )
    save_story(slug, post)
    return slug


def update_story(slug: str, word_count: int | None, style: str, description: str) -> None:
    post = load_story(slug)
    if post is None:
        raise FileNotFoundError(f"Story not found: {slug}")
    post["word_count"] = word_count
    post["style"] = style
    post.content = description
    save_story(slug, post)


def log_submission(slug: str, journal: str, outcome: str = "pending", notes: str = "") -> None:
    """Append a submission record to a story file."""
    post = load_story(slug)
    if post is None:
        raise FileNotFoundError(f"Story not found: {slug}")
    submissions = post.get("submitted_to", [])
    submissions.append({
        "journal": journal,
        "date": date.today().isoformat(),
        "outcome": outcome,
        "notes": notes,
    })
    post["submitted_to"] = submissions
    save_story(slug, post)


def update_submission_outcome(slug: str, journal: str, outcome: str, notes: str = "") -> None:
    """Update the outcome of the most recent submission to a given journal."""
    post = load_story(slug)
    if post is None:
        raise FileNotFoundError(f"Story not found: {slug}")
    submissions = post.get("submitted_to", [])
    # Update the most recent entry for this journal
    for entry in reversed(submissions):
        if entry["journal"].lower() == journal.lower():
            entry["outcome"] = outcome
            if notes:
                entry["notes"] = notes
            break
    post["submitted_to"] = submissions
    save_story(slug, post)


def sync_from_tracker(slug: str, tracker_subs: list[dict]) -> int:
    """
    Merge tracker submission records into a Markdown story file.
    Matches by journal name (case-insensitive) to avoid duplicates.
    tracker_subs: list of {journal, date, outcome} dicts from workbook.story_view().
    Returns count of newly added submissions.
    """
    post = load_story(slug)
    if post is None:
        return 0
    existing = post.get("submitted_to", [])
    existing_lower = {s["journal"].strip().lower() for s in existing}
    added = 0
    for sub in tracker_subs:
        if sub["journal"].strip().lower() in existing_lower:
            continue
        d = sub.get("date")
        if hasattr(d, "date"):
            date_str = d.date().isoformat()
        elif d:
            date_str = str(d)[:10]
        else:
            date_str = date.today().isoformat()
        existing.append({
            "journal": sub["journal"],
            "date": date_str,
            "outcome": sub["outcome"],
            "notes": "",
        })
        existing_lower.add(sub["journal"].strip().lower())
        added += 1
    if added:
        post["submitted_to"] = existing
        save_story(slug, post)
    return added


def submitted_journals(slug: str) -> list[str]:
    """Return journal names this story has been submitted to."""
    post = load_story(slug)
    if post is None:
        return []
    return [s["journal"] for s in post.get("submitted_to", [])]


def format_for_agent(slug: str) -> str:
    """Format story info as a context block for the agent."""
    post = load_story(slug)
    if post is None:
        return ""

    lines = [
        f"## Active story: {post.get('title')}",
        f"Story slug (use this when calling log_submission): {slug}",
        f"Word count: {post.get('word_count') or 'unknown'}",
        f"Style: {post.get('style') or 'not specified'}",
        "",
        "Description:",
        post.content.strip() or "(no description)",
    ]

    submissions = post.get("submitted_to", [])
    if submissions:
        lines += ["", "Previous submissions (do not suggest these journals):"]
        for s in submissions:
            note = f" — {s['notes']}" if s.get("notes") else ""
            lines.append(f"  - {s['journal']} ({s['date']}, {s['outcome']}){note}")

    return "\n".join(lines)
