"""
Builds the ranked output Excel spreadsheet from matched journal data.
Sheet 1: ranked journals sorted by rank.
Sheet 2: unranked journals for manual review.
"""

from pathlib import Path

import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "open_ranked_journals.xlsx"

RANKED_COLUMNS = [
    ("rank", "Rank"),
    ("score", "Score"),
    ("display_name", "Journal Name"),
    ("submit_url", "Submit URL"),
    ("about_url", "About URL"),
    ("match_confidence", "Match Confidence"),
]

UNRANKED_COLUMNS = [
    ("display_name", "Journal Name"),
    ("deadline", "Open Until"),
    ("response_days", "Response Time (days)"),
    ("pay_rate", "Pay"),
    ("submit_url", "Submit URL"),
]

HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
LOW_CONF_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")


def _build_df(journals: list[dict], columns: list[tuple]) -> pd.DataFrame:
    rows = []
    for j in journals:
        rows.append({label: j.get(field, "") for field, label in columns})
    return pd.DataFrame(rows)


def _style_sheet(ws, df: pd.DataFrame, url_cols: list[str]) -> None:
    # Header row
    for col_idx, col_name in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # Auto-width columns
    for col_idx, col_name in enumerate(df.columns, start=1):
        letter = get_column_letter(col_idx)
        max_len = max(
            len(str(col_name)),
            *(len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(2, ws.max_row + 1)),
            0,
        )
        ws.column_dimensions[letter].width = min(max_len + 4, 60)

    # Hyperlinks for URL columns
    for col_idx, col_name in enumerate(df.columns, start=1):
        if col_name in url_cols:
            for row_idx in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value and str(cell.value).startswith("http"):
                    cell.hyperlink = cell.value
                    cell.font = Font(color="0563C1", underline="single")

    # Highlight low-confidence rows (< 95) on ranked sheet
    if "Match Confidence" in df.columns:
        conf_col = list(df.columns).index("Match Confidence") + 1
        for row_idx in range(2, ws.max_row + 1):
            conf_cell = ws.cell(row=row_idx, column=conf_col)
            try:
                if conf_cell.value and float(conf_cell.value) < 95:
                    for c in range(1, ws.max_column + 1):
                        ws.cell(row=row_idx, column=c).fill = LOW_CONF_FILL
            except (ValueError, TypeError):
                pass

    ws.freeze_panes = "A2"


def build(journals: list[dict], output_path: Path | None = None) -> Path:
    path = Path(output_path) if output_path else OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    ranked = sorted(
        [j for j in journals if j.get("rank") is not None],
        key=lambda x: x["rank"],
    )
    unranked = [j for j in journals if j.get("rank") is None]

    df_ranked = _build_df(ranked, RANKED_COLUMNS)
    df_unranked = _build_df(unranked, UNRANKED_COLUMNS)

    url_cols = ["Submit URL", "About URL"]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_ranked.to_excel(writer, sheet_name="Ranked Journals", index=False)
        df_unranked.to_excel(writer, sheet_name="Unranked (Review)", index=False)

        _style_sheet(writer.sheets["Ranked Journals"], df_ranked, url_cols)
        _style_sheet(writer.sheets["Unranked (Review)"], df_unranked, url_cols)

    print(f"Output written: {path}  ({len(ranked)} ranked, {len(unranked)} unranked)")
    return path
