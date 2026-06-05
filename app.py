"""
Streamlit UI for Submissions Advisor.
Run with: streamlit run app.py
"""

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import anthropic as _anthropic

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ingest import from_csv, from_html, from_text, normalize_name
from scrape_rankings import load_rankings, load_custom_rankings_from_excel, clear_custom_rankings, CUSTOM_CACHE_PATH
from match import match, ranked_only, unranked_only
from fetch_about import fetch_about_pages
from agent import stream_response
from summarize_journals import missing_summaries, generate_summaries, no_url_count
from find_urls import find_missing_urls
from stories import (
    list_stories, load_story, create_story, update_story,
    log_submission, update_submission_outcome, format_for_agent, submitted_journals,
    sync_from_tracker,
)
from workbook import (
    load as load_workbook,
    get_sheet_names,
    story_view,
    update_outcome as wb_update_outcome,
    add_submission as wb_add_submission,
    add_feedback as wb_add_feedback,
    tracker_submissions_for_agent,
    format_all_pending_for_agent,
    WORKBOOK_PATH,
)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Submissions Advisor",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Submissions Advisor")
st.caption("Find the best open journals for your story, ranked by prestige score.")


def _fmt_date(d) -> str:
    if d is None:
        return ""
    if hasattr(d, "date"):
        return d.date().isoformat()
    return str(d)[:10]


# Accumulated journal list persists across pastes
if "journals" not in st.session_state:
    st.session_state.journals = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # display only (text)
if "api_history" not in st.session_state:
    st.session_state.api_history = []   # full API messages including tool blocks
if "active_story_slug" not in st.session_state:
    st.session_state.active_story_slug = None
if "ai_prefill" not in st.session_state:
    st.session_state.ai_prefill = {}
if "genre_mode" not in st.session_state:
    st.session_state.genre_mode = "Literary"


# ---------------------------------------------------------------------------
# Sidebar — rankings cache
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Rankings")
    try:
        _all_rankings = load_rankings()
        _custom = CUSTOM_CACHE_PATH.exists()
    except Exception as e:
        st.error(f"Could not load rankings: {e}")
        _all_rankings = []
        _custom = False

    genre_mode = st.radio(
        "Genre",
        ["Literary", "Science Fiction"],
        index=0 if st.session_state.genre_mode == "Literary" else 1,
        horizontal=True,
    )
    if genre_mode != st.session_state.genre_mode:
        st.session_state.genre_mode = genre_mode
        st.session_state.api_history = []
        st.session_state.chat_history = []

    _cat = "literary" if genre_mode == "Literary" else "sf"
    rankings = [r for r in _all_rankings if r.get("category", "literary") == _cat]
    st.success(f"{len(rankings)} {genre_mode.lower()} journals ranked{'  (custom)' if _custom else ''}")

    st.divider()
    st.header("Options")
    threshold = st.slider("Match threshold", min_value=70, max_value=100, value=85,
                          help="Lower = more matches but less accurate")
    fetch_about = st.checkbox("Fetch about pages", value=False,
                              help="Makes network requests — slow on first run, cached after")


# ---------------------------------------------------------------------------
# Main — Duotrope input
# ---------------------------------------------------------------------------

tab_paste, tab_upload, tab_stories, tab_tracker, tab_feedback, tab_discuss = st.tabs(
    ["Paste Duotrope data", "Upload CSV", "Stories", "Tracker", "Editor Notes", "Discuss"]
)

with tab_paste:
    st.markdown(
        "Duotrope shows 50 results per page. Paste each page in turn and click "
        "**Add batch** — journals accumulate across pastes. Click **Clear** to start over."
    )
    pasted = st.text_area("Paste Duotrope results here", height=200,
                          placeholder="Santa Monica Review\tGeneral\tShort Story\t...")

    col_add, col_clear = st.columns([1, 1])
    with col_add:
        add_clicked = st.button("Add batch", key="add_paste")
    with col_clear:
        if st.button("Clear all", key="clear_paste"):
            st.session_state.journals = []
            st.rerun()

    if add_clicked and pasted.strip():
        try:
            if "<" in pasted and ">" in pasted:
                new_journals = from_html(pasted)
            else:
                new_journals = from_text(pasted)

            if not new_journals:
                st.warning("No journals found in that paste.")
            else:
                # Append, deduplicating by normalized_name
                existing_names = {j["normalized_name"] for j in st.session_state.journals}
                added = [j for j in new_journals if j["normalized_name"] not in existing_names]
                st.session_state.journals.extend(added)
                st.success(f"Added {len(added)} journals ({len(new_journals) - len(added)} duplicates skipped). "
                           f"**{len(st.session_state.journals)} total** — paste the next page or click Match below.")
        except Exception as e:
            st.error(f"Could not parse pasted data: {e}")

with tab_upload:
    st.markdown("Upload a previous results CSV to restore a session, or a raw Duotrope export to match.")

    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    if st.button("Load CSV", key="load_upload") and uploaded:
        try:
            content = uploaded.read()
            df_up = pd.read_csv(pd.io.common.BytesIO(content))
            cols = [c.lower() for c in df_up.columns]

            # Detect a previous results CSV by the presence of "duotrope name" and "rank"
            if "duotrope name" in cols and "rank" in cols:
                from ingest import normalize_name
                restored = []
                for _, row in df_up.iterrows():
                    name = str(row.get("Duotrope Name", row.get("duotrope name", ""))).strip()
                    if not name or name == "nan":
                        continue
                    restored.append({
                        "display_name": name,
                        "normalized_name": normalize_name(name),
                        "rank": int(row["Rank"]) if not pd.isna(row.get("Rank")) else None,
                        "score": row.get("Score") if not pd.isna(row.get("Score", float("nan"))) else None,
                        "matched_name": str(row.get("Ranked Name", row.get("Krouse Name", ""))) or None,
                        "match_confidence": None,
                        "submit_url": str(row.get("Submit", "")) if not pd.isna(row.get("Submit", float("nan"))) else "",
                        "about_url": str(row.get("About", "")) if not pd.isna(row.get("About", float("nan"))) else "",
                        "deadline": "rolling",
                        "response_days": None,
                        "pay_rate": "",
                    })
                st.session_state.last_matched = restored
                st.session_state.rejected_matches = set()
                st.success(f"Restored {len(restored)} journals from previous results. Go to Match & Results below.")
            else:
                # Raw Duotrope export — add to journal list for matching
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                new_journals = from_csv(tmp_path)
                os.unlink(tmp_path)
                if not new_journals:
                    st.warning("No journals found in the CSV.")
                else:
                    existing_names = {j["normalized_name"] for j in st.session_state.journals}
                    added = [j for j in new_journals if j["normalized_name"] not in existing_names]
                    st.session_state.journals.extend(added)
                    st.success(f"Added {len(added)} journals. {len(st.session_state.journals)} total.")
        except Exception as e:
            st.error(f"Could not parse CSV: {e}")

    st.divider()
    st.subheader("Custom rankings")
    st.markdown(
        "Upload your own ranked journal list instead of the default. "
        "Excel must have columns **`rank`** (integer) and **`name`** (journal name). "
        "Optional: `score`, `journal_url`, `tier`."
    )
    if CUSTOM_CACHE_PATH.exists():
        st.info(f"Custom rankings active — {len(load_rankings())} journals loaded.")
        if st.button("Clear custom rankings (revert to default)", key="clear_custom"):
            clear_custom_rankings()
            st.success("Reverted to default rankings.")
            st.rerun()
    custom_wb = st.file_uploader("Upload custom rankings (Excel)", type=["xlsx", "xls"], key="custom_rankings_upload")
    if st.button("Load custom rankings", key="load_custom_rankings") and custom_wb:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(custom_wb.read())
                tmp_path = tmp.name
            loaded = load_custom_rankings_from_excel(tmp_path)
            os.unlink(tmp_path)
            st.success(f"Loaded {len(loaded)} journals from custom rankings. Reloading...")
            st.rerun()
        except Exception as e:
            st.error(f"Could not load custom rankings: {e}")


# ---------------------------------------------------------------------------
# Match & Results
# ---------------------------------------------------------------------------

st.divider()

journals = st.session_state.journals

if journals:
    st.write(f"**{len(journals)} journals loaded.** Ready to match.")
    run_match = st.button("Match against rankings", type="primary")
else:
    st.caption("No journals loaded yet — paste a batch above.")
    run_match = False

if run_match and not rankings:
    st.error("Rankings not loaded. Check that data/rankings_cache.json exists.")

if run_match and journals and rankings:
    with st.spinner("Matching against rankings..."):
        matched = match(journals, rankings, threshold=threshold)
    if fetch_about:
        with st.spinner("Fetching about pages..."):
            matched = fetch_about_pages(matched)
    st.session_state.last_matched = matched
    st.session_state.rejected_matches = set()  # reset rejections on new match run

# Render results whenever we have them (persists across reruns)
if st.session_state.get("last_matched"):
    matched = st.session_state.last_matched
    rejected = st.session_state.get("rejected_matches", set())

    # Apply rejections in-place on the stored list
    for j in matched:
        if j["normalized_name"] in rejected and j.get("rank") is not None:
            j["_rejected"] = True
        else:
            j.pop("_rejected", None)

    ranked = [j for j in ranked_only(matched) if not j.get("_rejected")]
    unranked = unranked_only(matched) + [j for j in ranked_only(matched) if j.get("_rejected")]

    st.subheader(f"Results — {len(ranked)} matched, {len(unranked_only(matched))} unranked")

    # ------------------------------------------------------------------
    # Low-confidence review panel
    # ------------------------------------------------------------------
    LOW_CONF = 95
    low_conf = [
        j for j in ranked
        if (j.get("match_confidence") or 100) < LOW_CONF and not j.get("_rejected")
    ]
    if low_conf:
        with st.expander(f"⚠️ Review {len(low_conf)} low-confidence matches", expanded=True):
            st.caption(
                "These Duotrope names matched a ranked journal below 95% confidence. "
                "Check both names and reject any that are wrong."
            )
            for j in sorted(low_conf, key=lambda x: x.get("match_confidence", 0)):
                col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 1])
                col_a.markdown(f"**{j['display_name']}**")
                col_b.markdown(f"→ *{j.get('matched_name', '')}*")
                col_c.markdown(f"{j['match_confidence']:.0f}%")
                if col_d.button("Reject", key=f"reject_{j['normalized_name']}"):
                    st.session_state.rejected_matches.add(j["normalized_name"])
                    st.rerun()

    # ------------------------------------------------------------------
    # Main results table
    # ------------------------------------------------------------------
    if ranked:
        df = pd.DataFrame([
            {
                "Rank": j["rank"],
                "Score": j.get("score"),
                "Duotrope Name": j["display_name"],
                "Ranked Name": j.get("matched_name", ""),
                "Submit": j["submit_url"],
                "About": j.get("about_url", ""),
                "Confidence": f"{j['match_confidence']:.0f}%" if j["match_confidence"] else "",
            }
            for j in sorted(ranked, key=lambda x: x["rank"])
        ])

        st.dataframe(
            df,
            use_container_width=True,
            column_config={
                "Submit": st.column_config.LinkColumn("Submit"),
                "About": st.column_config.LinkColumn("About"),
            },
            hide_index=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv_bytes, "matched_journals.csv", "text/csv")
        with col2:
            from output import build
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp_path = Path(tmp.name)
            build(matched, output_path=tmp_path)
            with open(tmp_path, "rb") as f:
                xlsx_bytes = f.read()
            os.unlink(tmp_path)
            st.download_button("Download Excel", xlsx_bytes, "matched_journals.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    unranked_display = unranked_only(matched)
    if unranked_display:
        with st.expander(f"Unranked journals ({len(unranked_display)}) — not in ranked list"):
            df_u = pd.DataFrame([
                {"Journal": j["display_name"], "Submit": j["submit_url"]}
                for j in unranked_display
            ])
            st.dataframe(df_u, use_container_width=True,
                         column_config={"Submit": st.column_config.LinkColumn("Submit")},
                         hide_index=True)


# ---------------------------------------------------------------------------
# Stories tab
# ---------------------------------------------------------------------------

with tab_stories:
    stories = list_stories()

    # Sync from tracker (runs once on demand)
    if WORKBOOK_PATH.exists():
        if st.button("Sync submission history from tracker", key="sync_tracker"):
            try:
                _wb_sync = load_workbook(WORKBOOK_PATH)
                _view_sync = story_view(_wb_sync["journals"])
                _total_added = 0
                for _s in stories:
                    _title = _s["title"]
                    _subs_flat = [
                        {"journal": e["journal"], "date": e["date"], "outcome": bucket}
                        for bucket, entries in _view_sync.get(_title, {}).items()
                        for e in entries
                    ]
                    _total_added += sync_from_tracker(_s["slug"], _subs_flat)
                if _total_added:
                    st.success(f"Synced {_total_added} submission(s) from tracker into story files.")
                    stories = list_stories()  # refresh
                else:
                    st.info("Stories are already up to date with the tracker.")
            except Exception as _e:
                st.error(f"Sync failed: {_e}")
        st.divider()

    col_list, col_detail = st.columns([1, 2])

    with col_list:
        st.subheader("Your stories")
        if stories:
            options = {s["title"]: s["slug"] for s in stories}
            selected_title = st.radio(
                "Select a story",
                list(options.keys()),
                index=0,
                label_visibility="collapsed",
            )
            if st.button("Load into Discuss", type="primary"):
                new_slug = options[selected_title]
                if new_slug != st.session_state.active_story_slug:
                    st.session_state.active_story_slug = new_slug
                    st.session_state.api_history = []
                    st.session_state.chat_history = []
                st.success(f"'{selected_title}' loaded — go to the Discuss tab.")
        else:
            selected_title = None
            st.caption("No stories yet. Create one on the right.")

        st.divider()
        st.subheader("New story")

        # AI card generator — collapsed by default; only shown when API key is set
        if os.environ.get("ANTHROPIC_API_KEY"):
            with st.expander("Generate card with AI", expanded=False):
                ai_text = st.text_area(
                    "Paste story text",
                    height=150,
                    placeholder="Paste your story or an excerpt here...",
                    key="ai_story_text_input",
                )
                st.caption(
                    "⚠️ This will send your story text to the Claude API. "
                    "Only paste text you are comfortable sharing with Anthropic."
                )
                ai_consent = st.checkbox(
                    "I understand and consent to sending my story text to Claude",
                    key="ai_consent_cb",
                )
                if st.button(
                    "Generate card",
                    disabled=not (ai_consent and ai_text.strip()),
                    key="ai_gen_btn",
                ):
                    with st.spinner("Generating card..."):
                        try:
                            _client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                            _wc = len(ai_text.split())
                            _prompt = (
                                "Read this story and return a JSON object with exactly these keys:\n"
                                '- "title": a suggested working title (string, or null if not obvious)\n'
                                '- "style": brief aesthetic description, 3-8 words'
                                ' (e.g. "lyric realism, second person")\n'
                                '- "description": 2-3 sentence summary suitable for submission tracking\n\n'
                                "Return only valid JSON, no other text.\n\n"
                                f"Story:\n{ai_text[:6000]}"
                            )
                            _resp = _client.messages.create(
                                model="claude-sonnet-4-6",
                                max_tokens=400,
                                messages=[{"role": "user", "content": _prompt}],
                            )
                            _raw = _resp.content[0].text.strip()
                            # Strip markdown code fences if Claude wraps the JSON
                            _raw = re.sub(r"^```(?:json)?\s*", "", _raw)
                            _raw = re.sub(r"\s*```$", "", _raw.strip())
                            _data = json.loads(_raw)
                            st.session_state.ai_prefill = {
                                "title": _data.get("title") or "",
                                "word_count": _wc,
                                "style": _data.get("style") or "",
                                "description": _data.get("description") or "",
                            }
                            st.rerun()
                        except Exception as _e:
                            st.error(f"Generation failed: {_e}")

        _prefill = st.session_state.ai_prefill
        if _prefill:
            st.info("AI-generated — review and edit before saving.")

        with st.form("new_story"):
            new_title = st.text_input("Title *", value=_prefill.get("title", ""))
            new_wc = st.number_input(
                "Word count",
                min_value=0,
                step=100,
                value=int(_prefill.get("word_count") or 0),
            )
            new_style = st.text_input(
                "Style / aesthetic",
                value=_prefill.get("style", ""),
                placeholder="lyric realism, second person",
            )
            new_desc = st.text_area(
                "Description",
                height=120,
                value=_prefill.get("description", ""),
                placeholder="What's the story about?",
            )
            if st.form_submit_button("Create story"):
                if new_title.strip():
                    create_story(new_title.strip(), new_wc or None, new_style.strip(), new_desc.strip())
                    st.session_state.ai_prefill = {}
                    st.success(f"Created '{new_title}'")
                    st.rerun()
                else:
                    st.warning("Title is required.")

    with col_detail:
        if stories and selected_title:
            slug = {s["title"]: s["slug"] for s in stories}[selected_title]
            post = load_story(slug)

            st.subheader(selected_title)

            with st.expander("Edit story details", expanded=False):
                with st.form("edit_story"):
                    e_wc = st.number_input("Word count", min_value=0, step=100,
                                           value=post.get("word_count") or 0)
                    e_style = st.text_input("Style / aesthetic", value=post.get("style", ""))
                    e_desc = st.text_area("Description", value=post.content, height=150)
                    if st.form_submit_button("Save changes"):
                        update_story(slug, e_wc or None, e_style.strip(), e_desc.strip())
                        st.success("Saved.")
                        st.rerun()

            submissions = post.get("submitted_to", [])
            st.markdown(f"**Word count:** {post.get('word_count') or '—'}")
            st.markdown(f"**Style:** {post.get('style') or '—'}")
            st.markdown(f"**Description:** {post.content.strip() or '—'}")

            st.divider()
            st.subheader("Submission log")

            if submissions:
                import pandas as pd
                df_sub = pd.DataFrame(submissions)[["journal", "date", "outcome", "notes"]]
                df_sub.columns = ["Journal", "Date", "Outcome", "Notes"]
                st.dataframe(df_sub, use_container_width=True, hide_index=True)

                st.markdown("**Update an outcome:**")
                with st.form("update_outcome"):
                    journal_names = [s["journal"] for s in submissions]
                    upd_journal = st.selectbox("Journal", journal_names)
                    upd_outcome = st.selectbox("New outcome", ["pending", "rejected", "accepted", "withdrawn"])
                    upd_notes = st.text_input("Notes (optional)")
                    if st.form_submit_button("Update"):
                        update_submission_outcome(slug, upd_journal, upd_outcome, upd_notes)
                        if WORKBOOK_PATH.exists():
                            _raw_map = {"rejected": "Nope", "accepted": "Yep", "withdrawn": "Withdrawn", "pending": None}
                            _raw_val = _raw_map.get(upd_outcome)
                            if _raw_val:
                                try:
                                    wb_update_outcome(WORKBOOK_PATH, upd_journal, post.get("title", slug), _raw_val)
                                except ValueError:
                                    # Submission not in Excel yet — add it now with the new outcome
                                    _sub_entry = next(
                                        (s for s in submissions if s["journal"].strip().lower() == upd_journal.strip().lower()),
                                        {},
                                    )
                                    _sub_date = _sub_entry.get("date") or _dt.date.today()
                                    wb_add_submission(WORKBOOK_PATH, upd_journal, post.get("title", slug), _sub_date, _raw_val)
                        st.success("Updated.")
                        st.rerun()
            else:
                st.caption("No submissions logged yet.")

            st.divider()
            st.subheader("Log a submission")
            with st.form("log_submission"):
                sub_journal = st.text_input("Journal name")
                sub_notes = st.text_input("Notes (optional)")
                if st.form_submit_button("Log as submitted (pending)"):
                    if sub_journal.strip():
                        log_submission(slug, sub_journal.strip(), "pending", sub_notes.strip())
                        if WORKBOOK_PATH.exists():
                            try:
                                wb_add_submission(WORKBOOK_PATH, sub_journal.strip(), post.get("title", slug), _dt.date.today())
                            except Exception as _e:
                                st.warning(f"Saved to story file but could not update Excel tracker: {_e}")
                        st.success(f"Logged submission to {sub_journal}.")
                        st.rerun()
                    else:
                        st.warning("Journal name is required.")


# ---------------------------------------------------------------------------
# Tracker tab — story cards from submission workbook
# ---------------------------------------------------------------------------

with tab_tracker:
    if not WORKBOOK_PATH.exists():
        st.info(
            "Place your submissions Excel file in the `data/` folder as `submissions.xlsx` or "
            "`submission_tracking.xlsx`. You can also upload it here."
        )
        uploaded_wb = st.file_uploader("Upload submissions workbook", type=["xlsx", "xls"], key="wb_upload")
        if uploaded_wb:
            dest = WORKBOOK_PATH.parent / "submission_tracking.xlsx"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as _f:
                _f.write(uploaded_wb.read())
            st.success(f"Saved to data/{dest.name}.")
            st.rerun()
    else:
        try:
            wb_data = load_workbook(WORKBOOK_PATH)
            wb_ok = True
        except Exception as _e:
            st.error(f"Could not read workbook: {_e}")
            st.caption(f"Available sheets: {', '.join(get_sheet_names(WORKBOOK_PATH))}")
            wb_ok = False
            wb_data = {"journals": [], "stories": [], "feedback": []}

        col_hdr, col_reload = st.columns([5, 1])
        with col_hdr:
            n_subs = sum(len(j["submissions"]) for j in wb_data["journals"])
            n_pending = sum(
                1 for j in wb_data["journals"]
                for sub in j["submissions"]
                if sub["outcome"] == "pending"
            )
            st.caption(
                f"{WORKBOOK_PATH.name} — "
                f"{len(wb_data['journals'])} journals · "
                f"{n_subs} submissions · "
                f"{n_pending} pending · "
                f"{len(wb_data['stories'])} stories · "
                f"{len(wb_data['feedback'])} editor notes"
            )
        with col_reload:
            if st.button("Reload", key="wb_reload"):
                st.rerun()

        if wb_ok:
            view = story_view(wb_data["journals"])
            wb_stories = wb_data["stories"]

            # Build ordered title list: Stories sheet first, then any journal-only names
            stories_sheet_titles = [s["title"] for s in wb_stories]
            journal_only_titles = [t for t in sorted(view.keys()) if t not in stories_sheet_titles]
            all_titles = sorted(
                stories_sheet_titles + journal_only_titles,
                key=lambda t: (
                    -len(view.get(t, {}).get("pending", [])),
                    -sum(len(v) for v in view.get(t, {}).values()),
                ),
            )


            # ----------------------------------------------------------------
            # Story cards
            # ----------------------------------------------------------------
            st.subheader("Story status")

            if not all_titles:
                st.caption("No stories found. Check your sheet names: expected 'Journals -- Literary', 'Stories', 'Editors Requesting More Work'.")
            else:
                for title in all_titles:
                    subs = view.get(title, {"pending": [], "rejected": [], "accepted": [], "withdrawn": []})
                    n_pending = len(subs["pending"])
                    n_rejected = len(subs["rejected"])
                    n_accepted = len(subs["accepted"])

                    meta = next((s for s in wb_stories if s["title"] == title), {})
                    wc = meta.get("word_count")
                    wc_str = f" · {int(wc):,} words" if wc else ""

                    badge = f"{n_pending} out · {n_rejected} rejected"
                    if n_accepted:
                        badge += f" · {n_accepted} accepted ✓"
                    header = f"**{title}**{wc_str} — {badge}"

                    with st.expander(header, expanded=n_pending > 0):
                        if subs["pending"]:
                            st.markdown("**Currently out:**")
                            for sub in subs["pending"]:
                                c_name, c_date, c_mark = st.columns([3, 2, 2])
                                link = f"[{sub['journal']}]({sub['url']})" if sub["url"] else sub["journal"]
                                c_name.markdown(link)
                                c_date.caption(_fmt_date(sub["date"]))
                                # Safe widget key: hash to avoid special chars
                                _key = "mark_" + hashlib.md5(f"{title}|{sub['journal']}".encode()).hexdigest()[:8]
                                new_out = c_mark.selectbox(
                                    "Mark as",
                                    ["—", "Nope (rejected)", "Yep (accepted)", "Withdrawn"],
                                    key=_key,
                                    label_visibility="collapsed",
                                )
                                if new_out != "—":
                                    raw_val = {"Nope (rejected)": "Nope", "Yep (accepted)": "Yep", "Withdrawn": "Withdrawn"}[new_out]
                                    norm_val = {"Nope": "rejected", "Yep": "accepted", "Withdrawn": "withdrawn"}[raw_val]
                                    try:
                                        wb_update_outcome(WORKBOOK_PATH, sub["journal"], title, raw_val)
                                        # Mirror to Markdown file
                                        _slug = next((s["slug"] for s in list_stories() if s["title"].strip().lower() == title.strip().lower()), None)
                                        if _slug:
                                            update_submission_outcome(_slug, sub["journal"], norm_val)
                                        st.success(f"{sub['journal']} → {new_out}.")
                                        st.rerun()
                                    except Exception as _e:
                                        st.error(f"Could not update: {_e}")

                        if subs["rejected"]:
                            names = ", ".join(r["journal"] for r in subs["rejected"])
                            st.markdown(f"**Rejected ({n_rejected}):** {names}")

                        if subs["accepted"]:
                            for a in subs["accepted"]:
                                st.markdown(f"**Accepted:** {a['journal']} ✓")

                        if subs["withdrawn"]:
                            names = ", ".join(r["journal"] for r in subs["withdrawn"])
                            st.markdown(f"**Withdrawn:** {names}")

                        if n_pending + n_rejected + n_accepted + len(subs["withdrawn"]) == 0:
                            st.caption("No submissions logged yet for this story.")

            # ----------------------------------------------------------------
            # Log new submission
            # ----------------------------------------------------------------
            st.divider()
            st.subheader("Log new submission")
            with st.form("wb_log_sub"):
                lc1, lc2, lc3 = st.columns([2, 2, 1])
                sub_story = lc1.selectbox("Story", all_titles or ["(no stories)"])
                sub_journal = lc2.text_input("Journal name")
                sub_date = lc3.date_input("Date", value=_dt.date.today())
                if st.form_submit_button("Log submission"):
                    if sub_story and sub_journal.strip():
                        try:
                            wb_add_submission(WORKBOOK_PATH, sub_journal.strip(), sub_story, sub_date)
                            # Mirror to Markdown file
                            _slug = next((s["slug"] for s in list_stories() if s["title"].strip().lower() == sub_story.strip().lower()), None)
                            if _slug:
                                log_submission(_slug, sub_journal.strip(), "pending")
                            st.success(f"Logged '{sub_story}' → {sub_journal}.")
                            st.rerun()
                        except Exception as _e:
                            st.error(f"Could not log: {_e}")
                    else:
                        st.warning("Both story and journal name are required.")



# ---------------------------------------------------------------------------
# Editor Notes tab
# ---------------------------------------------------------------------------

with tab_feedback:
    if not WORKBOOK_PATH.exists():
        st.info("No workbook loaded. Add your submissions Excel file via the Tracker tab.")
    else:
        try:
            _fb_data = load_workbook(WORKBOOK_PATH)["feedback"]
            _fb_ok = True
        except Exception as _e:
            st.error(f"Could not read workbook: {_e}")
            _fb_data = []
            _fb_ok = False

        if _fb_ok:
            if _fb_data:
                for _fb in _fb_data:
                    _date_str = _fmt_date(_fb.get("date"))
                    _story_str = _fb.get("story") or ""
                    _header = _fb["journal"]
                    if _story_str:
                        _header += f" — {_story_str}"
                    if _date_str:
                        _header += f" ({_date_str})"
                    with st.expander(_header):
                        st.write(_fb["text"])
            else:
                st.caption("No editor notes recorded yet.")

        st.divider()
        st.subheader("Add editor note")
        with st.form("fb_add_note"):
            fc1, fc2, fc3 = st.columns([2, 2, 1])
            fb_j = fc1.text_input("Journal")
            fb_s = fc2.text_input("Story")
            fb_d = fc3.date_input("Date", value=_dt.date.today())
            fb_t = st.text_area("Feedback text", height=120)
            if st.form_submit_button("Save note"):
                if fb_j.strip() and fb_t.strip():
                    try:
                        wb_add_feedback(WORKBOOK_PATH, fb_j.strip(), fb_s.strip(), fb_t.strip(), fb_d)
                        st.success("Note saved.")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Could not save: {_e}")
                else:
                    st.warning("Journal and feedback text are required.")


# ---------------------------------------------------------------------------
# Discuss tab — conversational agent
# ---------------------------------------------------------------------------

with tab_discuss:
    matched_journals = st.session_state.get("last_matched", [])
    _rejected = st.session_state.get("rejected_matches", set())

    def accepted_ranked(journals):
        return [j for j in ranked_only(journals) if j.get("normalized_name") not in _rejected]

    active_slug = st.session_state.active_story_slug
    story_context = format_for_agent(active_slug) if active_slug else None

    editor_feedback = []
    pending_context = ""
    if WORKBOOK_PATH.exists():
        try:
            _wb = load_workbook(WORKBOOK_PATH)
            editor_feedback = _wb["feedback"]
            pending_context = format_all_pending_for_agent(_wb["journals"])
            # Append per-story tracker history to story context if a story is active
            if story_context and active_slug:
                _post = load_story(active_slug)
                _title = _post.get("title", "") if _post else ""
                if _title:
                    _tracker_subs = tracker_submissions_for_agent(_title, _wb["journals"])
                    if _tracker_subs:
                        story_context = story_context + "\n\n" + _tracker_subs
        except Exception:
            pass

    if not matched_journals:
        st.info("Match your Duotrope journals first (Paste tab), then come back here to discuss your story.")
    else:
        # Summary generation — check for missing, offer to generate
        ranked_journals = accepted_ranked(matched_journals)
        missing = missing_summaries(ranked_journals)
        no_url = no_url_count(ranked_journals)
        if missing or no_url:
            parts = []
            if missing:
                parts.append(f"{len(missing)} can be generated")
            if no_url:
                parts.append(f"{no_url} have no URL yet")
            st.info(f"{len(missing) + no_url} journals without summaries — {', '.join(parts)}.")
            if no_url and st.button(f"Find {no_url} missing URLs via DuckDuckGo", key="find_urls"):
                progress = st.empty()
                for status in find_missing_urls(ranked_journals):
                    progress.caption(status)
                progress.empty()
                # Patch in-memory journals with newly found URLs from rankings cache
                updated_rankings = {r["normalized_name"]: r for r in load_rankings()}
                for j in st.session_state.last_matched:
                    norm = j.get("normalized_name")
                    if norm and not j.get("journal_url"):
                        new_url = updated_rankings.get(norm, {}).get("journal_url")
                        if new_url:
                            j["journal_url"] = new_url
                st.rerun()

            if missing and st.button(f"Generate {len(missing)} summaries", key="gen_summaries"):
                progress = st.empty()
                for status in generate_summaries(missing):
                    progress.caption(status)
                progress.empty()
                st.rerun()
        col_header, col_clear = st.columns([4, 1])
        with col_header:
            if story_context:
                post = load_story(active_slug)
                st.write(f"**{len(accepted_ranked(matched_journals))} journals loaded · Active story: {post.get('title')}**")
            else:
                st.write(f"**{len(accepted_ranked(matched_journals))} journals loaded.** Select a story in the Stories tab, or just describe your story below.")
        with col_clear:
            if st.button("New conversation"):
                st.session_state.chat_history = []
                st.session_state.api_history = []
                st.rerun()

        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("Set the ANTHROPIC_API_KEY environment variable to use the agent.")
        else:
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            user_input = st.chat_input("Describe your story, ask for advice, or ask about a specific journal...")
            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)

                with st.chat_message("assistant"):
                    response_placeholder = st.empty()
                    full_response = ""
                    updated_api_history = None
                    try:
                        gen = stream_response(
                            st.session_state.api_history,
                            user_input,
                            accepted_ranked(matched_journals),
                            story_context=story_context,
                            editor_feedback=editor_feedback or None,
                            pending_context=pending_context,
                            genre_mode=st.session_state.genre_mode,
                        )
                        for chunk in gen:
                            full_response += chunk
                            response_placeholder.markdown(full_response + "▌")
                        response_placeholder.markdown(full_response)
                        try:
                            gen.send(None)
                        except StopIteration as e:
                            updated_api_history = e.value
                    except Exception as e:
                        response_placeholder.error(f"Agent error: {e}")

                if full_response:
                    st.session_state.chat_history.append({"role": "assistant", "content": full_response})
                if updated_api_history is not None:
                    st.session_state.api_history = updated_api_history
