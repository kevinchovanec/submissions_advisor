"""
Read/write the user's Excel submission tracking workbook.

Journal sheets ("Journals -- Literary", "Journals -- Genre"):
  Cols 0-11: Name | about_url | submission_url | Tier | Sim Sub | affiliation |
             Link | Genre | sub cost | Open | Rules | Pay
  Cols 12+:  Submission story | Submission Date | Submission decision  (repeating triplets)

Stories sheet:
  Title | Length | Genre | Out? | Rejections | Placed

Feedback sheet ("Editors Requesting More Work"):
  Journal | Work Sent | Date | Message
"""
from __future__ import annotations
from datetime import date as _date
from pathlib import Path

import openpyxl

_DATA_DIR = Path(__file__).parent.parent / "data"
_JOURNAL_SHEETS = ["Journals -- Literary", "Journals -- Genre"]
_FEEDBACK_SHEET_CANDIDATES = [
    "Editors Requesting More Work", "Feedback", "Editor Feedback", "Notes"
]
_TRIPLET_START_FALLBACK = 12  # used only if header detection fails

# Outcome normalisation: raw Excel value → canonical bucket
_REJECTED_VALUES = {"nope", "nop", "no reply", "no"}
_ACCEPTED_VALUES = {"yep", "yes", "accepted", "placed"}
_WITHDRAWN_VALUES = {"withdrawn"}


def _norm_outcome(val) -> str:
    if val is None:
        return "pending"
    s = str(val).strip().lower()
    if s in _REJECTED_VALUES:
        return "rejected"
    if s in _ACCEPTED_VALUES:
        return "accepted"
    if s in _WITHDRAWN_VALUES:
        return "withdrawn"
    return "pending"


def _find_workbook() -> Path:
    """Return path to whichever tracker file exists."""
    for name in ["submission_tracking.xlsx", "submissions.xlsx"]:
        p = _DATA_DIR / name
        if p.exists():
            return p
    return _DATA_DIR / "submissions.xlsx"  # fallback (may not exist)


WORKBOOK_PATH: Path = _find_workbook()


def _find_sheet(wb, candidates: list[str]):
    lower_map = {n.lower(): n for n in wb.sheetnames}
    for c in candidates:
        if c.lower() in lower_map:
            return wb[lower_map[c.lower()]]
    return None


def _triplet_start(ws) -> int:
    """Find 0-indexed column where submission triplets begin by locating 'Submission story' header."""
    for cell in ws[1]:
        if cell.value and "submission story" in str(cell.value).lower():
            return cell.column - 1  # cell.column is 1-indexed
    return _TRIPLET_START_FALLBACK


def _text(cell) -> str:
    v = cell.value
    return str(v).strip() if v is not None else ""


def _url(cell) -> str:
    if cell.hyperlink and cell.hyperlink.target:
        return cell.hyperlink.target
    v = cell.value
    if v and str(v).strip().startswith("http"):
        return str(v).strip()
    return ""


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def load(path: str | Path | None = None) -> dict:
    """Return {journals, stories, feedback} from the workbook."""
    path = Path(path) if path else WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(path), data_only=True)
    return {
        "journals": _load_all_journals(wb),
        "stories": _load_stories(wb),
        "feedback": _load_feedback(wb),
    }


def get_sheet_names(path: str | Path | None = None) -> list[str]:
    path = Path(path) if path else WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(path), read_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def story_view(journals: list[dict]) -> dict[str, dict]:
    """Pivot journals list into story-centric dict: story name → {pending, rejected, accepted, withdrawn}."""
    view: dict[str, dict] = {}
    for j in journals:
        for sub in j["submissions"]:
            story = sub["story"]
            if story not in view:
                view[story] = {"pending": [], "rejected": [], "accepted": [], "withdrawn": []}
            view[story][sub["outcome"]].append({
                "journal": j["name"],
                "url": j["url"],
                "date": sub["date"],
            })
    return view


# ---------------------------------------------------------------------------
# Internal loaders
# ---------------------------------------------------------------------------

def _load_all_journals(wb) -> list[dict]:
    journals = []
    for sheet_name in _JOURNAL_SHEETS:
        if sheet_name in wb.sheetnames:
            journals.extend(_load_journal_sheet(wb[sheet_name], sheet_name))
    return journals


def _load_journal_sheet(ws, sheet_name: str) -> list[dict]:
    ts = _triplet_start(ws)  # detect per-sheet where triplets begin
    journals = []
    for row in ws.iter_rows(min_row=2):
        if not row[0].value:
            continue
        name = _text(row[0])
        # Prefer about_url (col 1), submission_url (col 2), or Link (col 6)
        url = ""
        for col_idx in (1, 2, 6):
            if col_idx < len(row):
                u = _url(row[col_idx])
                if u:
                    url = u
                    break

        submissions = []
        i = ts
        while i < len(row):
            story = _text(row[i])
            if story:
                date_val = row[i + 1].value if i + 1 < len(row) else None
                outcome_raw = row[i + 2].value if i + 2 < len(row) else None
                submissions.append({
                    "story": story,
                    "date": date_val,
                    "outcome_raw": outcome_raw,
                    "outcome": _norm_outcome(outcome_raw),
                    "sheet": sheet_name,
                })
            i += 3

        journals.append({"name": name, "url": url, "sheet": sheet_name, "submissions": submissions})
    return journals


def _load_stories(wb) -> list[dict]:
    if "Stories" not in wb.sheetnames:
        return []
    stories = []
    for row in wb["Stories"].iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        stories.append({
            "title": str(row[0]).strip(),
            "word_count": row[1] if len(row) > 1 else None,
            "genre": str(row[2]).strip() if len(row) > 2 and row[2] else "",
            "rejections": int(row[4]) if len(row) > 4 and row[4] is not None else None,
            "placed": row[5] if len(row) > 5 else None,
        })
    return stories


def _load_feedback(wb) -> list[dict]:
    ws = _find_sheet(wb, _FEEDBACK_SHEET_CANDIDATES)
    if ws is None:
        return []
    feedback = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        feedback.append({
            "journal": str(row[0]).strip() if row[0] else "",
            "story": str(row[1]).strip() if len(row) > 1 and row[1] else "",
            "date": row[2] if len(row) > 2 else None,
            "text": str(row[3]).strip() if len(row) > 3 and row[3] else "",
        })
    return feedback


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------

def update_outcome(
    path: str | Path | None,
    journal_name: str,
    story_name: str,
    new_outcome_raw: str,  # use the workbook's convention: "Nope", "Yep", etc.
) -> None:
    """Update the outcome cell for a specific story/journal row."""
    path = Path(path) if path else WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(path))
    j_lower = journal_name.strip().lower()
    s_lower = story_name.strip().lower()

    for sheet_name in _JOURNAL_SHEETS:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        ts = _triplet_start(ws)
        for row in ws.iter_rows(min_row=2):
            if not row[0].value:
                continue
            if str(row[0].value).strip().lower() != j_lower:
                continue
            for i in range(ts, len(row) - 2, 3):
                if row[i].value and str(row[i].value).strip().lower() == s_lower:
                    row[i + 2].value = new_outcome_raw
                    wb.save(str(path))
                    return
            break  # journal found in this sheet, story not here

    raise ValueError(f"Submission '{story_name}' at '{journal_name}' not found")


def add_submission(
    path: str | Path | None,
    journal_name: str,
    story_name: str,
    sub_date,
    outcome_raw=None,  # None = pending (blank cell)
    default_sheet: str = "Journals -- Literary",
) -> None:
    """Append a new submission triplet to a journal row, creating the row if needed."""
    path = Path(path) if path else WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(path))
    j_lower = journal_name.strip().lower()
    target_sheet: str | None = None
    target_row: int | None = None

    for sheet_name in _JOURNAL_SHEETS:
        if sheet_name not in wb.sheetnames:
            continue
        for row in wb[sheet_name].iter_rows(min_row=2):
            if row[0].value and str(row[0].value).strip().lower() == j_lower:
                target_sheet = sheet_name
                target_row = row[0].row
                break
        if target_row:
            break

    if target_row is None:
        target_sheet = default_sheet if default_sheet in wb.sheetnames else _JOURNAL_SHEETS[0]
        ws = wb[target_sheet]
        target_row = ws.max_row + 1
        ws.cell(row=target_row, column=1).value = journal_name

    ws = wb[target_sheet]
    ts = _triplet_start(ws)
    col = ts + 1  # convert 0-indexed to 1-indexed for openpyxl cell access
    while ws.cell(row=target_row, column=col).value is not None:
        col += 3

    ws.cell(row=target_row, column=col).value = story_name
    ws.cell(row=target_row, column=col + 1).value = sub_date
    ws.cell(row=target_row, column=col + 2).value = outcome_raw
    wb.save(str(path))


def add_feedback(
    path: str | Path | None,
    journal_name: str,
    story_name: str,
    feedback_text: str,
    feedback_date=None,
) -> None:
    """Append a row to the feedback sheet."""
    path = Path(path) if path else WORKBOOK_PATH
    wb = openpyxl.load_workbook(str(path))
    ws = _find_sheet(wb, _FEEDBACK_SHEET_CANDIDATES)
    if ws is None:
        raise ValueError("Feedback sheet not found in workbook")
    ws.append([journal_name, story_name, feedback_date or _date.today().isoformat(), feedback_text])
    wb.save(str(path))


# ---------------------------------------------------------------------------
# Agent context formatting
# ---------------------------------------------------------------------------

def format_all_pending_for_agent(journals: list[dict]) -> str:
    """
    All currently-pending submissions across every story.
    Most journals don't allow simultaneous submissions, so these are off the table
    regardless of which story is being discussed.
    """
    pending = [
        (j["name"], sub["story"])
        for j in journals
        for sub in j["submissions"]
        if sub["outcome"] == "pending"
    ]
    if not pending:
        return ""
    lines = [
        "Journals with a submission currently under review (any story — "
        "do not suggest these unless the writer explicitly asks about them):"
    ]
    for journal, story in pending:
        lines.append(f"  - {journal} ({story})")
    return "\n".join(lines)


def tracker_submissions_for_agent(story_title: str, journals: list[dict]) -> str:
    """
    Find a story's submission history in the Excel tracker by title (case-insensitive)
    and return a formatted block for agent context.  Returns "" if no match.
    """
    title_lower = story_title.strip().lower()
    view = story_view(journals)
    matched = next((v for k, v in view.items() if k.strip().lower() == title_lower), None)
    if not matched:
        return ""
    lines = ["Submission history from tracker (do not suggest these journals):"]
    for bucket in ("pending", "rejected", "accepted", "withdrawn"):
        for entry in matched.get(bucket, []):
            lines.append(f"  - {entry['journal']} ({bucket})")
    return "\n".join(lines) if len(lines) > 1 else ""

def format_feedback_brief(feedback: list[dict]) -> str:
    """
    One-line-per-journal summary for the agent's opening context.
    Full messages are fetched on demand via the get_editor_feedback tool.
    """
    entries = [f for f in feedback if f.get("text")]
    if not entries:
        return ""
    lines = [
        "Journals that have sent encouraging notes or requested more work "
        "(call get_editor_feedback for the full message before recommending one of these):"
    ]
    for f in entries:
        date_val = f.get("date")
        if hasattr(date_val, "date"):
            date_str = f" ({date_val.date()})"
        elif date_val:
            date_str = f" ({str(date_val)[:10]})"
        else:
            date_str = ""
        line = f"- {f['journal']}{date_str}"
        if f.get("story"):
            line += f" on '{f['story']}'"
        lines.append(line)
    return "\n".join(lines)


def get_feedback_for_journal(feedback: list[dict], journal_name: str) -> str:
    """Return the full feedback text(s) for a given journal name."""
    j_lower = journal_name.strip().lower()
    matches = [f for f in feedback if f.get("journal", "").strip().lower() == j_lower]
    if not matches:
        return f"No editor feedback found for '{journal_name}'."
    parts = []
    for f in matches:
        date_val = f.get("date")
        date_str = f.get("date", "")
        if hasattr(date_val, "date"):
            date_str = str(date_val.date())
        elif date_val:
            date_str = str(date_val)[:10]
        header = f"From {f['journal']}"
        if f.get("story"):
            header += f" re '{f['story']}'"
        if date_str:
            header += f" ({date_str})"
        parts.append(f"{header}:\n{f['text']}")
    return "\n\n".join(parts)
