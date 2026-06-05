# To-Do: Hosted Public Version

## Strategy

Single repo, two modes. The local version (current) stays as-is. A cloud mode activates when Supabase environment variables are present. Local users clone and run; everyone else uses the deployed app. One codebase, one place to fix bugs.

## Phase A — Finish local version (current focus)

- [ ] Polish any remaining local UX issues
- [ ] Verify cover letter templates work end-to-end
- [ ] Clean up `fill_missing_urls.py` from project root (can delete)
- [ ] Update README to reflect current state (Krouse references removed, SF rankings added, cover letters added)

## Phase B — Storage abstraction

Goal: make storage swappable without changing the rest of the app.

- [ ] Create `src/storage.py` with a clean interface:
  - `list_stories() → list[dict]`
  - `load_story(slug) → dict | None`
  - `save_story(slug, data) → None`
  - `log_submission(slug, journal, outcome, notes, date) → None`
  - `update_outcome(slug, journal, outcome) → None`
- [ ] Refactor `src/stories.py` to implement the file-based backend (current behavior, no functional change)
- [ ] Refactor `src/workbook.py` to sit behind the same interface (Excel becomes optional/local-only)
- [ ] Route all calls in `app.py` and `src/agent.py` through `storage.py`

## Phase C — Supabase backend

- [ ] Design schema:
  - `stories` — (id, user_id, slug, title, word_count, style, description, created_at)
  - `submissions` — (id, user_id, story_slug, journal, date, outcome, notes)
- [ ] Create `src/storage_supabase.py` implementing the same interface as `storage.py`
- [ ] Add auth flow to `app.py` (email/password via Supabase auth; gate whole app behind session check)
- [ ] Switch active backend based on env vars: if `SUPABASE_URL` + `SUPABASE_KEY` present → cloud; else → local files
- [ ] Cover letter templates: keep as committed repo files (shared defaults); optionally allow user-saved templates in Supabase later

## Phase D — Privacy and user rights

Required before any public launch.

- [ ] Write a privacy policy page — plain English, covering: what's stored (story metadata + submission history, not manuscripts), what's sent to Anthropic during AI sessions, that data is never sold, how to request deletion, contact info. Host as a static page or a tab in the app.
- [ ] Add **Delete my account** button in account/settings area — deletes Supabase auth account and all associated rows in `stories` and `submissions` tables
- [ ] Add **Download my data** button — exports all stories and submission history as a zip of Markdown files (matching the local format) or a single CSV; gives users a portable copy of their data
- [ ] Add API key handling note to privacy policy — keys are held in session state only, never written to the database
- [ ] Link to privacy policy from the app's login/signup screen

## Phase E — Deploy

- [ ] Set up Streamlit Community Cloud project pointing at this repo
- [ ] Add secrets: `SUPABASE_URL`, `SUPABASE_KEY` (API key supplied by each user at login, not stored as a secret)
- [ ] Add row-level security in Supabase so users only see their own stories/submissions
- [ ] Update README with live app URL and "use the hosted version" instructions
- [ ] Decide: single Streamlit deployment for all users, or instructions for self-hosting with own Supabase project

## Notes

- Rankings, cover letter templates, and journal summaries cache remain as committed files — shared by all users, no database needed
- The agent, matching, and cover letter logic need no changes for cloud mode
- Excel tracker becomes redundant once Supabase is live; local users can still export to Excel as a download
- Auth adds a new dependency — Supabase's Python client (`supabase`) needs to be added to `requirements.txt`
