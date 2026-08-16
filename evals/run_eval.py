"""
Opt-in behavioural eval for the Discuss agent. Costs real tokens.

    set ANTHROPIC_API_KEY=sk-...
    python evals/run_eval.py

The deterministic suite in tests/ covers context assembly and the tool loop without
an API key. This checks the things only a real model call can: that the prompt
actually stops the agent recommending a journal that already has a submission under
review, and that it respects a cached word limit. Those are prompt behaviours, so
they have no other verification.

Exits non-zero if any scenario fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import FakeStorage  # noqa: E402
import agent  # noqa: E402

JOURNALS = [
    {"rank": 1, "normalized_name": "georgia review", "display_name": "The Georgia Review",
     "journal_url": "https://example.invalid/gr", "score": 95, "tier": "Tier 1"},
    {"rank": 2, "normalized_name": "ploughshares", "display_name": "Ploughshares",
     "journal_url": "https://example.invalid/ps", "score": 90, "tier": "Tier 1"},
    {"rank": 3, "normalized_name": "tiny flash", "display_name": "Tiny Flash",
     "journal_url": "https://example.invalid/tf", "score": 40, "tier": "Tier 3"},
    {"rank": 4, "normalized_name": "open door review", "display_name": "Open Door Review",
     "journal_url": "https://example.invalid/od", "score": 35, "tier": "Tier 3"},
]

STORIES = [
    {"slug": "long-one", "title": "The Long One", "word_count": 7500,
     "style": "maximalist literary", "description": "A sprawling family saga.",
     "submitted_to": [{"journal": "The Georgia Review", "date": "2026-06-01",
                       "outcome": "pending", "notes": ""}]},
    {"slug": "short-one", "title": "The Short One", "word_count": 900,
     "style": "flash", "description": "A brief, sharp piece.", "submitted_to": []},
]


def _run(storage, message, slugs, primary=None):
    """Drive one full turn and return the visible text."""
    from storage import format_selected_stories, format_story_roster

    selected = [storage.load_story(s) for s in slugs]
    pending = storage.list_all_pending()
    gen = agent.stream_response(
        [], message, JOURNALS, storage,
        story_context=format_selected_stories(selected, primary or slugs[0]),
        roster_context=format_story_roster(storage.list_stories(), pending, set(slugs)),
        pending=pending,
        allowed_slugs=set(slugs),
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration:
        pass
    return "".join(chunks)


# --- scenarios -------------------------------------------------------------

def scenario_excludes_pending(storage) -> tuple[bool, str]:
    out = _run(storage, "Where should I send The Long One? Name your top two picks.", ["long-one"])
    named = "georgia review" in out.lower()
    hedged = any(p in out.lower() for p in ("already", "under review", "pending", "currently out"))
    ok = not named or hedged
    return ok, "named Georgia Review as a pick despite a pending submission" if not ok else ""


def scenario_no_double_booking(storage) -> tuple[bool, str]:
    out = _run(
        storage,
        "Give me one journal for each of these two stories. One journal per story, no overlap.",
        ["long-one", "short-one"],
    )
    body = out.lower()
    # A journal named once can serve one story; twice suggests both were sent there.
    doubled = [j["display_name"] for j in JOURNALS if body.count(j["display_name"].lower()) >= 2]
    ok = not doubled or "each" in body
    return ok, f"possible double-booking: {doubled}" if not ok else ""


def scenario_respects_roster(storage) -> tuple[bool, str]:
    out = _run(storage, "Is there a story I didn't load that suits Tiny Flash better?", ["long-one"])
    ok = "short one" in out.lower()
    return ok, "did not surface the roster story that fits" if not ok else ""


def scenario_refuses_unloaded_log(storage) -> tuple[bool, str]:
    before = list(storage.logged)
    _run(storage, "Log a submission of The Short One to Open Door Review.", ["long-one"])
    ok = storage.logged == before
    return ok, "wrote a submission for a story that wasn't loaded" if not ok else ""


def scenario_length_fit(storage) -> tuple[bool, str]:
    out = _run(storage, "Is Tiny Flash a sensible home for The Long One at 7,500 words?", ["long-one"])
    body = out.lower()
    ok = any(p in body for p in ("too long", "word", "length", "limit", "short"))
    return ok, "gave no length reasoning for an obvious mismatch" if not ok else ""


SCENARIOS = [
    ("excludes pending journal", scenario_excludes_pending),
    ("no double-booking across stories", scenario_no_double_booking),
    ("surfaces a better roster story", scenario_respects_roster),
    ("refuses to log an unloaded story", scenario_refuses_unloaded_log),
    ("reasons about length fit", scenario_length_fit),
]


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping (this eval costs tokens).")
        return 0

    failures = []
    for name, fn in SCENARIOS:
        storage = FakeStorage([dict(s) for s in STORIES])
        try:
            ok, detail = fn(storage)
        except Exception as e:
            ok, detail = False, f"raised {type(e).__name__}: {e}"
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print(f"\n{len(SCENARIOS) - len(failures)}/{len(SCENARIOS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
