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

class ChatRequest(BaseModel):
    message: str
    api_history: list[dict[str, Any]] = []
    journals: list[dict[str, Any]] = []
    story_context: str | None = None
    editor_feedback: list[dict[str, Any]] | None = None
    pending_context: str = ""
    genre_mode: str = "Literary"
    story_slug: str | None = None
