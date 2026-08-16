"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str

class SignupRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Stories
# ---------------------------------------------------------------------------

class StoryCreate(BaseModel):
    title: str
    word_count: int | None = None
    style: str = ""
    description: str = ""

class StoryUpdate(BaseModel):
    word_count: int | None = None
    style: str = ""
    description: str = ""

class GenerateCardRequest(BaseModel):
    story_text: str


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class SubmissionCreate(BaseModel):
    journal: str
    outcome: str = "pending"
    notes: str = ""
    sub_date: str | None = None

class OutcomeUpdate(BaseModel):
    outcome: str
    notes: str = ""
    sub_date: str | None = None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateUpsert(BaseModel):
    content: str
    description: str = ""


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackCreate(BaseModel):
    journal: str
    story: str = ""
    feedback_date: str | None = None
    text: str

class FeedbackUpdate(BaseModel):
    journal: str
    story: str = ""
    feedback_date: str | None = None
    text: str


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str
    content: str

class ConversationSave(BaseModel):
    messages: list[Message]


# ---------------------------------------------------------------------------
# Match / Agent
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    text: str
    genre_mode: str = "Literary"
    custom_rankings: list[dict[str, Any]] | None = None

class SummariesStatusRequest(BaseModel):
    journals: list[dict[str, Any]] = []


class SummariesGenerateRequest(BaseModel):
    """`scope='paste'` summarizes only the matched journals sent here; `scope='all'`
    ignores them and walks every ranked journal with a URL, for producing the
    committed artifact."""

    journals: list[dict[str, Any]] = []
    scope: str = "paste"
    force_refresh: bool = False
    dry_run: bool = False


class ChatRequest(BaseModel):
    """Chat turn input.

    Story/pending/feedback context is assembled server-side from storage — the
    client sends slugs, not prose. `primary_slug` is the story saved conversations
    key on and the default target for log_submission.
    """

    message: str
    api_history: list[dict[str, Any]] = []
    journals: list[dict[str, Any]] = []
    genre_mode: str = "Literary"
    story_slugs: list[str] = []
    primary_slug: str | None = None
