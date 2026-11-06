"""
FastAPI backend for Submissions Advisor.

Local mode:  uvicorn api.main:app --reload
Cloud mode:  set SUPABASE_URL + SUPABASE_ANON_KEY (+ optional SUPABASE_SERVICE_KEY
             for account deletion), then same command.

Static files (React dist/) are served from frontend/dist/ when that directory exists.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import csv
import zipfile

import anthropic as _anthropic
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent import stream_response
from .dependencies import (
    CLOUD_MODE,
    anon_client,
    get_authed,
    get_storage,
    get_user_id,
    service_client,
)
from ingest import from_text, normalize_name
from .models import (
    ChatRequest,
    ConversationSave,
    FeedbackCreate,
    FeedbackUpdate,
    GenerateCardRequest,
    LoginRequest,
    MatchRequest,
    OutcomeUpdate,
    RefreshRequest,
    SignupRequest,
    StoryCreate,
    StoryUpdate,
    SubmissionCreate,
    SummariesGenerateRequest,
    SummariesStatusRequest,
    TemplateUpsert,
)
from scrape_rankings import load_rankings
from journal_names import JournalNameResolver
from match import collapse_duplicates, match as run_match, ranked_only
from models_config import EXTRACTION_THINKING, MODEL
from storage import format_selected_stories, format_story_roster
from summarize_journals import generate_summaries, status_for

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Submissions Advisor API")

# The SPA is served by this app (and the Vite dev server proxies /api here), so
# normal use is same-origin and needs no CORS. Cross-origin access is opt-in via
# a comma-separated ALLOWED_ORIGINS env var; empty by default. Auth uses the
# Authorization header (not cookies), so credentials are not enabled.
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=10)

# Ceiling on stories loaded into one chat turn. Each costs a load_story call and a
# full card in the prompt, so this bounds both the work and the context per request.
MAX_SELECTED_STORIES = 16


# ---------------------------------------------------------------------------
# Auth  (cloud mode only)
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
def auth_login(req: LoginRequest, sb=Depends(anon_client)):
    try:
        resp = sb.auth.sign_in_with_password({"email": req.email, "password": req.password})
        return {
            "user_id": resp.user.id,
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
        }
    except Exception:
        # Generic message — avoids leaking internals and user-enumeration hints.
        raise HTTPException(status_code=401, detail="Invalid email or password")


@app.post("/api/auth/signup")
def auth_signup(req: SignupRequest, sb=Depends(anon_client)):
    try:
        sb.auth.sign_up({"email": req.email, "password": req.password})
        return {"message": "Account created — check your email to confirm."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/refresh")
def auth_refresh(req: RefreshRequest, sb=Depends(anon_client)):
    try:
        resp = sb.auth.refresh_session(req.refresh_token)
        return {
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
            "user_id": resp.user.id,
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")


@app.post("/api/auth/logout")
def auth_logout(authed=Depends(get_authed)):
    # Best-effort server-side revocation; the client also drops its stored tokens.
    client, _ = authed
    try:
        client.auth.sign_out()
    except Exception:
        pass
    return {"message": "Logged out"}


@app.delete("/api/auth/account")
def delete_account(authed=Depends(get_authed)):
    """Delete all user data, then remove the auth account.

    Data deletion runs through the security-definer delete_user_data() RPC under
    the caller's own identity. Removing the auth account itself needs the
    service-role key (auth.admin.delete_user).
    """
    client, user_id = authed
    try:
        client.rpc("delete_user_data", {}).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete your data: {e}")

    service = service_client()
    if service is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "Your submission data was deleted, but the auth account could not be removed "
                "because no service-role key is configured. Set SUPABASE_SERVICE_KEY to enable "
                "full account deletion."
            ),
        )
    try:
        service.auth.admin.delete_user(user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Your data was deleted, but the auth account could not be removed: {e}",
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Stories
# ---------------------------------------------------------------------------

@app.get("/api/stories")
def list_stories(storage=Depends(get_storage)):
    return storage.list_stories()


@app.post("/api/stories", status_code=201)
def create_story(req: StoryCreate, storage=Depends(get_storage)):
    slug = storage.create_story(req.title, req.word_count, req.style, req.description)
    return {"slug": slug}


@app.get("/api/stories/{slug}")
def get_story(slug: str, storage=Depends(get_storage)):
    story = storage.load_story(slug)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    names = JournalNameResolver(load_rankings())
    for sub in story.get("submitted_to", []):
        sub["journal_display"] = names.display(sub.get("journal", ""))
    return story


@app.put("/api/stories/{slug}")
def update_story(slug: str, req: StoryUpdate, storage=Depends(get_storage)):
    storage.update_story(slug, req.word_count, req.style, req.description)
    return {"ok": True}


@app.delete("/api/stories/{slug}")
def delete_story(slug: str, storage=Depends(get_storage)):
    storage.delete_story(slug)
    return {"ok": True}


@app.post("/api/stories/generate-card")
def generate_card(
    req: GenerateCardRequest,
    x_anthropic_key: str | None = Header(default=None),
    user_id: str = Depends(get_user_id),
):
    effective_key = x_anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not effective_key:
        raise HTTPException(status_code=400, detail="No API key — provide X-Anthropic-Key header or set ANTHROPIC_API_KEY in .env")
    client = _anthropic.Anthropic(api_key=effective_key)
    word_count = len(req.story_text.split())
    prompt = (
        "Read this story and return a JSON object with exactly these keys:\n"
        '- "title": a suggested working title (string, or null if not obvious)\n'
        '- "style": brief aesthetic description, 3-8 words'
        ' (e.g. "lyric realism, second person")\n'
        '- "description": 2-3 sentence summary suitable for submission tracking\n\n'
        "Return only valid JSON, no other text.\n\n"
        f"Story:\n{req.story_text[:6000]}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=800,
            thinking=EXTRACTION_THINKING,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())
        data = json.loads(raw)
        return {
            "title": data.get("title") or "",
            "word_count": word_count,
            "style": data.get("style") or "",
            "description": data.get("description") or "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@app.post("/api/stories/sync-tracker")
def sync_tracker(storage=Depends(get_storage)):
    """Create missing story cards and merge submission history from the local Excel tracker (local mode only)."""
    try:
        result = storage.sync_from_tracker()
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

@app.post("/api/stories/{slug}/submissions", status_code=201)
def log_submission(slug: str, req: SubmissionCreate, storage=Depends(get_storage)):
    storage.log_submission(slug, req.journal, req.outcome, req.notes, req.sub_date)
    return {"ok": True}


@app.put("/api/stories/{slug}/submissions/{journal}")
def update_outcome(slug: str, journal: str, req: OutcomeUpdate, storage=Depends(get_storage)):
    storage.update_outcome(slug, journal, req.outcome, req.notes, req.sub_date)
    return {"ok": True}


@app.delete("/api/stories/{slug}/submissions/{journal}")
def delete_submission(slug: str, journal: str, storage=Depends(get_storage)):
    storage.delete_submission(slug, journal)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@app.get("/api/templates")
def list_templates(storage=Depends(get_storage)):
    return storage.list_templates()


@app.get("/api/templates/{name}")
def get_template(name: str, storage=Depends(get_storage)):
    content = storage.load_template(name)
    if content is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"name": name, "content": content}


@app.put("/api/templates/{name}")
def save_template(name: str, req: TemplateUpsert, storage=Depends(get_storage)):
    storage.save_template(name, req.content, req.description)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Editor feedback
# ---------------------------------------------------------------------------

@app.get("/api/feedback")
def list_feedback(storage=Depends(get_storage)):
    names = JournalNameResolver(load_rankings())
    return [{**f, "journal_display": names.display(f.get("journal", ""))} for f in storage.list_feedback()]


@app.post("/api/feedback", status_code=201)
def add_feedback(req: FeedbackCreate, storage=Depends(get_storage)):
    storage.add_feedback(req.journal, req.story, req.feedback_date, req.text)
    return {"ok": True}


@app.put("/api/feedback/{feedback_id}")
def update_feedback(feedback_id: str, req: FeedbackUpdate, storage=Depends(get_storage)):
    try:
        storage.update_feedback(feedback_id, req.journal, req.story, req.feedback_date, req.text)
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.delete("/api/feedback/{feedback_id}")
def delete_feedback(feedback_id: str, storage=Depends(get_storage)):
    try:
        storage.delete_feedback(feedback_id)
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Conversations  (cloud mode — stored in Supabase)
# ---------------------------------------------------------------------------

def _require_cloud():
    if not CLOUD_MODE:
        raise HTTPException(status_code=404, detail="Conversations not available in local mode")


@app.get("/api/conversations/{story_slug}")
def list_conversations(story_slug: str, authed=Depends(get_authed)):
    _require_cloud()
    sb, user_id = authed
    res = (
        sb.table("conversations")
        .select("id, story_slug, started_at, messages")
        .eq("user_id", user_id)
        .eq("story_slug", story_slug)
        .order("started_at", desc=True)
        .execute()
    )
    return res.data


@app.post("/api/conversations/{story_slug}", status_code=201)
def save_conversation(story_slug: str, req: ConversationSave, authed=Depends(get_authed)):
    _require_cloud()
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")
    sb, user_id = authed
    sb.table("conversations").insert({
        "user_id": user_id,
        "story_slug": story_slug,
        "messages": [m.model_dump() for m in req.messages],
    }).execute()
    return {"ok": True}


@app.delete("/api/conversations/{story_slug}/{conv_id}")
def delete_conversation(story_slug: str, conv_id: str, authed=Depends(get_authed)):
    _require_cloud()
    sb, user_id = authed
    sb.table("conversations").delete().eq("id", conv_id).eq("user_id", user_id).execute()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Journal matching
# ---------------------------------------------------------------------------

@app.post("/api/rankings/upload")
async def upload_rankings(file: UploadFile = File(...)):
    """Parse a user-supplied Excel or CSV rankings file and return the rankings as JSON."""
    try:
        import math
        import pandas as pd

        content = await file.read()
        filename = file.filename or ""
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        df.columns = [str(c).strip().lower() for c in df.columns]
        required = {"rank", "name", "journal_url"}
        missing = required - set(df.columns)
        if missing:
            raise HTTPException(status_code=400, detail=f"File is missing required columns: {', '.join(sorted(missing))}")

        rankings = []
        for _, row in df.iterrows():
            name = str(row["name"]).strip()
            if not name or name.lower() == "nan":
                continue
            try:
                rank = int(row["rank"])
            except (ValueError, TypeError):
                continue

            raw_score = row.get("score") if "score" in df.columns else None
            score = None
            if raw_score is not None:
                try:
                    v = float(raw_score)
                    score = None if math.isnan(v) else v
                except (ValueError, TypeError):
                    pass

            raw_url = row.get("journal_url") if "journal_url" in df.columns else None
            journal_url = str(raw_url).strip() if raw_url and str(raw_url) != "nan" else None

            raw_tier = row.get("tier") if "tier" in df.columns else None
            if raw_tier is None or (isinstance(raw_tier, float) and math.isnan(raw_tier)):
                tier = "T1" if rank <= 50 else "T2" if rank <= 150 else "T3" if rank <= 300 else "T4"
            else:
                tier = str(raw_tier)

            rankings.append({
                "rank": rank,
                "name": name,
                "normalized_name": normalize_name(name),
                "score": score,
                "tier": tier,
                "journal_url": journal_url,
                "about_url": None,
                "submit_url": None,
                "fetched_at": None,
            })

        rankings.sort(key=lambda r: r["rank"])
        return rankings
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")


@app.post("/api/match")
def match_journals(req: MatchRequest):
    journals = from_text(req.text)
    if not journals:
        return {"ranked": [], "unranked": []}
    rankings = req.custom_rankings if req.custom_rankings else load_rankings()
    matched = run_match(journals, rankings)
    ranked = sorted(collapse_duplicates(ranked_only(matched)), key=lambda j: j["rank"])
    unranked = [j for j in matched if j["rank"] is None]
    return {"ranked": ranked, "unranked": unranked}


@app.get("/api/submissions")
def list_all_submissions(storage=Depends(get_storage)):
    """All submissions across every story, sorted by date descending."""
    names = JournalNameResolver(load_rankings())
    rows = []
    for s in storage.list_stories():
        full = storage.load_story(s["slug"])
        if full is None:
            continue
        for sub in full.get("submitted_to", []):
            rows.append({
                "story_slug": s["slug"],
                "story_title": full["title"],
                "journal": sub.get("journal", ""),
                "journal_display": names.display(sub.get("journal", "")),
                "date": sub.get("date", ""),
                "outcome": sub.get("outcome", "pending"),
                "notes": sub.get("notes", ""),
            })
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


@app.get("/api/pending")
def list_pending(storage=Depends(get_storage)):
    return storage.list_all_pending()


@app.get("/api/rankings")
def get_rankings():
    return load_rankings()


# ---------------------------------------------------------------------------
# Journal summaries  (local mode only)
# ---------------------------------------------------------------------------

def _require_local() -> None:
    """Summary generation writes to data/, which is ephemeral on the hosted server
    and shared across all cloud users. Generate locally and commit the JSON instead."""
    if CLOUD_MODE:
        raise HTTPException(
            status_code=404,
            detail="Summary generation is local-mode only. Run it locally and commit "
                   "data/journal_summaries.json.",
        )


@app.post("/api/summaries/status")
def summaries_status(req: SummariesStatusRequest):
    """Counts for the generate button: how many journals are cached vs missing."""
    return status_for(req.journals)


@app.post("/api/summaries/generate")
async def summaries_generate(
    req: SummariesGenerateRequest,
    x_anthropic_key: str | None = Header(default=None),
):
    _require_local()
    effective_key = x_anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not effective_key and not req.dry_run:
        raise HTTPException(status_code=400, detail="No API key — provide X-Anthropic-Key header or set ANTHROPIC_API_KEY in .env")

    journals = req.journals
    if req.scope == "all":
        # The whole ranked list, for producing the artifact cloud users receive.
        journals = [j for j in load_rankings() if j.get("journal_url")]

    async def generate():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_gen():
            try:
                for line in generate_summaries(
                    journals,
                    api_key=effective_key,
                    force_refresh=req.force_refresh,
                    dry_run=req.dry_run,
                ):
                    asyncio.run_coroutine_threadsafe(queue.put(("line", line)), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("error", str(exc))), loop)
                return
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)

        future = loop.run_in_executor(_executor, run_gen)
        while True:
            kind, data = await queue.get()
            if kind == "line":
                yield f"data: {json.dumps({'line': data})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'error': data})}\n\n"
                break
        await future

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Export  (xlsx download)
# ---------------------------------------------------------------------------

@app.get("/api/export")
def export_xlsx(storage=Depends(get_storage)):
    try:
        import pandas as pd

        stories = storage.list_stories()
        rows = []
        for s in stories:
            full = storage.load_story(s["slug"])
            if full is None:
                continue
            for sub in full.get("submitted_to", []):
                rows.append({
                    "Story": full["title"],
                    "Word Count": full.get("word_count"),
                    "Style": full.get("style", ""),
                    "Journal": sub["journal"],
                    "Date": sub["date"],
                    "Outcome": sub["outcome"],
                    "Notes": sub.get("notes", ""),
                })

        df = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["Story", "Word Count", "Style", "Journal", "Date", "Outcome", "Notes"]
        )
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Submissions")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=submissions.xlsx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Data export  (zip download — for "download my data" / GDPR-style export)
# ---------------------------------------------------------------------------

@app.get("/api/export/data")
def export_user_data(storage=Depends(get_storage)):
    """Download all user data as a ZIP of CSVs and template text files."""
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            stories = storage.list_stories()

            # stories.csv
            s_buf = io.StringIO()
            w = csv.DictWriter(s_buf, fieldnames=["slug", "title", "word_count", "style", "description"])
            w.writeheader()
            w.writerows([{k: s.get(k, "") for k in ["slug", "title", "word_count", "style", "description"]} for s in stories])
            zf.writestr("stories.csv", s_buf.getvalue())

            # submissions.csv
            sub_buf = io.StringIO()
            sw = csv.DictWriter(sub_buf, fieldnames=["story_slug", "journal", "date", "outcome", "notes"])
            sw.writeheader()
            for story in stories:
                full = storage.load_story(story["slug"])
                if full:
                    for sub in full.get("submitted_to", []):
                        sw.writerow({
                            "story_slug": story["slug"],
                            "journal": sub.get("journal", ""),
                            "date": sub.get("date", ""),
                            "outcome": sub.get("outcome", ""),
                            "notes": sub.get("notes", ""),
                        })
            zf.writestr("submissions.csv", sub_buf.getvalue())

            # templates/*.txt
            for tmpl in storage.list_templates():
                content = storage.load_template(tmpl["name"])
                if content:
                    zf.writestr(f"templates/{tmpl['name']}.txt", content)

            # feedback.csv
            feedback_list = storage.list_feedback()
            if feedback_list:
                fb_buf = io.StringIO()
                fbw = csv.DictWriter(fb_buf, fieldnames=["journal", "story", "feedback_date", "text"])
                fbw.writeheader()
                for f in feedback_list:
                    fbw.writerow({
                        "journal": f.get("journal", ""),
                        "story": f.get("story", ""),
                        "feedback_date": f.get("feedback_date", ""),
                        "text": f.get("text", f.get("feedback_text", "")),
                    })
                zf.writestr("feedback.csv", fb_buf.getvalue())

        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=submissions_advisor_data.zip"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Agent  (SSE streaming)
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    x_anthropic_key: str | None = Header(default=None),
    storage=Depends(get_storage),
):
    effective_key = x_anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not effective_key:
        raise HTTPException(status_code=400, detail="No API key — provide X-Anthropic-Key header or set ANTHROPIC_API_KEY in .env")

    # Story/pending/feedback context is assembled here rather than in the browser, so
    # there's one copy of the prompt text and it can't go stale after log_submission
    # writes mid-conversation.
    slugs = list(dict.fromkeys(req.story_slugs))
    if len(slugs) > MAX_SELECTED_STORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many stories selected ({len(slugs)}); the limit is {MAX_SELECTED_STORIES}.",
        )
    selected = []
    for slug in slugs:
        story = storage.load_story(slug)
        if story is None:
            raise HTTPException(status_code=404, detail=f"Story not found: {slug}")
        selected.append(story)

    primary = req.primary_slug or (slugs[0] if slugs else None)
    if primary and primary not in slugs:
        raise HTTPException(status_code=400, detail="primary_slug must be one of story_slugs")

    story_context = format_selected_stories(selected, primary) if selected else None
    # Optional context degrades to empty rather than failing the turn: a missing Excel
    # workbook or a transient storage error shouldn't take the whole conversation down.
    try:
        pending = storage.list_all_pending()
    except Exception:
        pending = []
    try:
        roster_context = format_story_roster(storage.list_stories(), pending, set(slugs))
    except Exception:
        roster_context = ""
    try:
        editor_feedback = storage.list_feedback()
    except Exception:
        editor_feedback = []

    async def generate():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_gen():
            gen = stream_response(
                req.api_history,
                req.message,
                req.journals,
                storage,
                story_context=story_context,
                roster_context=roster_context,
                pending=pending,
                editor_feedback=editor_feedback,
                genre_mode=req.genre_mode,
                api_key=effective_key,
                allowed_slugs=set(slugs),
            )
            result: tuple[list, dict] = ([], {})
            try:
                while True:
                    chunk = next(gen)
                    asyncio.run_coroutine_threadsafe(queue.put(("text", chunk)), loop)
            except StopIteration as exc:
                result = exc.value
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("error", str(exc))), loop)
                return
            asyncio.run_coroutine_threadsafe(queue.put(("done", result)), loop)

        future = loop.run_in_executor(_executor, run_gen)

        while True:
            kind, data = await queue.get()
            if kind == "text":
                yield f"data: {json.dumps({'text': data})}\n\n"
            elif kind == "done":
                history, usage = data
                # A write tool ran, so the client's cached story/pending queries are
                # stale — tell it which keys to refetch rather than waiting for a reload.
                invalidate = (
                    ["pending", "stories", "story", "submissions"]
                    if usage.pop("wrote_data", False)
                    else []
                )
                try:
                    payload = json.dumps(
                        {"done": True, "history": history, "usage": usage, "invalidate": invalidate}
                    )
                except TypeError as exc:
                    # Never kill the stream mid-flight: surface a proper error
                    # frame so the client shows a message instead of a dead socket.
                    payload = json.dumps({"error": f"Could not serialize history: {exc}"})
                yield f"data: {payload}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'error': data})}\n\n"
                break

        await future

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "cloud_mode": CLOUD_MODE,
        "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


# ---------------------------------------------------------------------------
# Static files  (React dist/ — served last so /api routes take priority)
# SPA catch-all: serve index.html for any path that isn't an API route or a
# real file, so React Router can handle client-side navigation on hard refresh.
# ---------------------------------------------------------------------------

_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _dist.exists():
    _dist_root = _dist.resolve()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Resolve and confirm the path stays inside dist/ before serving, so
        # crafted paths like ../../etc/passwd can't escape the static root.
        file_path = (_dist / full_path).resolve()
        if file_path.is_file() and _dist_root in file_path.parents:
            return FileResponse(str(file_path))
        return FileResponse(str(_dist_root / "index.html"))
