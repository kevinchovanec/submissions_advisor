"""
FastAPI backend for Submissions Advisor.

Local mode:  uvicorn api.main:app --reload
Cloud mode:  set SUPABASE_URL + SUPABASE_KEY, then same command.

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
from .dependencies import CLOUD_MODE, get_sb_client, get_storage, get_user_id
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
    TemplateUpsert,
)
from scrape_rankings import load_rankings
from match import match as run_match, ranked_only

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Submissions Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=10)


# ---------------------------------------------------------------------------
# Auth  (cloud mode only)
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
def auth_login(req: LoginRequest, sb=Depends(get_sb_client)):
    try:
        resp = sb.auth.sign_in_with_password({"email": req.email, "password": req.password})
        return {
            "user_id": resp.user.id,
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/auth/signup")
def auth_signup(req: SignupRequest, sb=Depends(get_sb_client)):
    try:
        sb.auth.sign_up({"email": req.email, "password": req.password})
        return {"message": "Account created — check your email to confirm."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/refresh")
def auth_refresh(req: RefreshRequest, sb=Depends(get_sb_client)):
    try:
        resp = sb.auth.refresh_session(req.refresh_token)
        return {
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
            "user_id": resp.user.id,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/auth/logout")
def auth_logout(sb=Depends(get_sb_client), user_id: str = Depends(get_user_id)):
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    return {"message": "Logged out"}


@app.delete("/api/auth/account")
def delete_account(sb=Depends(get_sb_client), user_id: str = Depends(get_user_id)):
    """Delete all user data and remove the auth account. Requires service role key."""
    for table in ["conversations", "feedback", "templates", "submissions", "stories"]:
        sb.table(table).delete().eq("user_id", user_id).execute()
    try:
        sb.auth.admin.delete_user(user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Your submission data was deleted, but the auth account could not be removed. "
                "Set SUPABASE_KEY to your service role key to enable full account deletion. "
                f"Details: {e}"
            ),
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
    return story


@app.put("/api/stories/{slug}")
def update_story(slug: str, req: StoryUpdate, storage=Depends(get_storage)):
    storage.update_story(slug, req.word_count, req.style, req.description)
    return {"ok": True}


@app.post("/api/stories/generate-card")
def generate_card(req: GenerateCardRequest, x_anthropic_key: str | None = Header(default=None)):
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
            model="claude-sonnet-4-6",
            max_tokens=400,
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


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

@app.delete("/api/stories/{slug}")
def delete_story(slug: str, storage=Depends(get_storage)):
    storage.delete_story(slug)
    return {"ok": True}


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
    return storage.list_feedback()


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

def _get_conv_client():
    """Return the raw Supabase client; raise 404 in local mode."""
    if not CLOUD_MODE:
        raise HTTPException(status_code=404, detail="Conversations not available in local mode")
    from .dependencies import _sb_client
    return _sb_client


@app.get("/api/conversations/{story_slug}")
def list_conversations(story_slug: str, user_id: str = Depends(get_user_id)):
    sb = _get_conv_client()
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
def save_conversation(story_slug: str, req: ConversationSave, user_id: str = Depends(get_user_id)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")
    sb = _get_conv_client()
    sb.table("conversations").insert({
        "user_id": user_id,
        "story_slug": story_slug,
        "messages": [m.model_dump() for m in req.messages],
    }).execute()
    return {"ok": True}


@app.delete("/api/conversations/{story_slug}/{conv_id}")
def delete_conversation(story_slug: str, conv_id: str, user_id: str = Depends(get_user_id)):
    sb = _get_conv_client()
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
    ranked = sorted(ranked_only(matched), key=lambda j: j["rank"])
    unranked = [j for j in matched if j["rank"] is None]
    return {"ranked": ranked, "unranked": unranked}


@app.get("/api/submissions")
def list_all_submissions(storage=Depends(get_storage)):
    """All submissions across every story, sorted by date descending."""
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
    async def generate():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_gen():
            gen = stream_response(
                req.api_history,
                req.message,
                req.journals,
                storage,
                story_context=req.story_context,
                editor_feedback=req.editor_feedback,
                pending_context=req.pending_context,
                genre_mode=req.genre_mode,
                api_key=effective_key,
            )
            updated_history = None
            try:
                while True:
                    chunk = next(gen)
                    asyncio.run_coroutine_threadsafe(queue.put(("text", chunk)), loop)
            except StopIteration as exc:
                updated_history = exc.value
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("error", str(exc))), loop)
                return
            asyncio.run_coroutine_threadsafe(queue.put(("done", updated_history)), loop)

        future = loop.run_in_executor(_executor, run_gen)

        while True:
            kind, data = await queue.get()
            if kind == "text":
                yield f"data: {json.dumps({'text': data})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'done': True, 'history': data})}\n\n"
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
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = _dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_dist / "index.html"))
