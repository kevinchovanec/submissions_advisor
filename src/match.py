"""
Fuzzy name matching between Duotrope journals and the ranked journal list.
Uses rapidfuzz token_sort_ratio with a default threshold of 85.
Matches below 95 are logged to stdout for manual review.
Supports manual_overrides.csv for human-corrected matches.
"""

import csv
import sys
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from ingest import normalize_name

OVERRIDES_PATH = Path(__file__).parent.parent / "data" / "manual_overrides.csv"
REVIEW_THRESHOLD = 95
DEFAULT_MATCH_THRESHOLD = 85


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------

def _load_overrides() -> dict[str, str]:
    """Returns {normalized_duotrope_name: normalized_ranked_name}.

    Both columns are run through normalize_name, so a row can be written with the
    names as they appear ("Dr. T.J. Eckleburg Review") rather than pre-normalized.
    """
    if not OVERRIDES_PATH.exists():
        return {}
    overrides = {}
    with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = normalize_name(row.get("duotrope_name", ""))
            val = normalize_name(row.get("krouse_name", ""))
            if key and val:
                overrides[key] = val
    return overrides


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match(
    journals: list[dict],
    rankings: list[dict],
    threshold: int = DEFAULT_MATCH_THRESHOLD,
) -> list[dict]:
    """
    Merge Duotrope journals with the ranked journal list.
    Each output dict contains all Duotrope fields plus:
      rank (int | None), match_confidence (float | None), matched_name (str | None)
    """
    overrides = _load_overrides()
    ranked_index = {r["normalized_name"]: r for r in rankings}
    ranked_names = list(ranked_index.keys())
    # Default-list keys were normalized with the source's asterisk still on, so
    # "*The Boiler" is keyed "the boiler" while a paste of "The Boiler" normalizes
    # to "boiler". The display name is clean now; index it too.
    by_clean_name = {normalize_name(r["name"]): r for r in rankings}

    results = []
    low_confidence = []

    for journal in journals:
        norm = journal["normalized_name"]
        entry = dict(journal)

        # Check manual override first, then an exact name
        override_key = overrides.get(norm)
        ranked = (
            (ranked_index.get(override_key) or by_clean_name.get(override_key)) if override_key
            else ranked_index.get(norm) or by_clean_name.get(norm)
        )
        if ranked:
            entry.update(_merge_ranked(ranked, confidence=100.0, via_override=bool(override_key)))
            entry["pasted_normalized_name"] = norm
            results.append(entry)
            continue

        # Fuzzy match
        result = process.extractOne(
            norm,
            ranked_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )

        if result:
            matched_name, score, _ = result
            ranked = ranked_index[matched_name]
            entry.update(_merge_ranked(ranked, confidence=float(score)))
            entry["pasted_normalized_name"] = norm
            if score < REVIEW_THRESHOLD:
                low_confidence.append((journal["display_name"], ranked["name"], score))
        else:
            entry.update({"rank": None, "match_confidence": None, "matched_name": None})

        results.append(entry)

    if low_confidence:
        print(f"\n--- {len(low_confidence)} low-confidence matches (below {REVIEW_THRESHOLD}) ---")
        for duotrope_name, ranked_name, score in sorted(low_confidence, key=lambda x: x[2]):
            # ASCII arrow: Windows consoles default to cp1252, where printing
            # '→' raises UnicodeEncodeError and would 500 the request.
            print(f"  {score:5.1f}  '{duotrope_name}'  ->  '{ranked_name}'")
        print(f"Add corrections to {OVERRIDES_PATH}\n")

    return results


def _merge_ranked(ranked: dict, confidence: float, via_override: bool = False) -> dict:
    return {
        "rank": ranked["rank"],
        "score": ranked.get("score"),
        "tier": ranked.get("tier"),
        "journal_url": ranked.get("journal_url"),
        "matched_name": ranked["name"],
        "match_confidence": confidence,
        # Adopt the ranked journal's identity. Matching resolved the pasted name to
        # this journal, and everything downstream — cached summaries, guideline
        # details, pending-submission exclusions — is keyed on the ranked name. Keeping
        # the pasted normalization here silently lost the summary for any journal
        # whose paste spelled it differently: "Georgia Review" against the ranked
        # "Georgia Review, The" looked like a journal with no summary at all.
        "normalized_name": ranked["normalized_name"],
        "pasted_normalized_name": None,  # filled in by the caller, which has it
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ranked_only(matched: list[dict]) -> list[dict]:
    return [j for j in matched if j["rank"] is not None]


def unranked_only(matched: list[dict]) -> list[dict]:
    return [j for j in matched if j["rank"] is None]


def collapse_duplicates(ranked: list[dict]) -> list[dict]:
    """
    One row per ranked journal. Pasting from Duotrope and The Submission Grinder
    lists the same journal under two spellings, and both resolve to one ranked
    entry. Keep the best-confidence match; drop the others only when they too are
    confident, since a low-confidence duplicate may be a different journal that
    fuzzed onto this one, and it stays visible so the writer can reject it.
    Order is preserved.
    """
    best: dict[str, dict] = {}
    for j in ranked:
        key = j["normalized_name"]
        if key not in best or (j["match_confidence"] or 0) > (best[key]["match_confidence"] or 0):
            best[key] = j
    return [
        j for j in ranked
        if best[j["normalized_name"]] is j or (j["match_confidence"] or 0) < REVIEW_THRESHOLD
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    sys.path.insert(0, str(Path(__file__).parent))
    from ingest import load as load_duotrope
    from scrape_rankings import load_rankings

    if len(sys.argv) < 2:
        print("Usage: python match.py <duotrope_export.csv>")
        sys.exit(1)

    journals = load_duotrope(sys.argv[1])
    rankings = load_rankings()
    results = match(journals, rankings)

    matched = ranked_only(results)
    print(f"\n{len(matched)} matched, {len(unranked_only(results))} unranked")
    for r in sorted(matched, key=lambda x: x["rank"])[:10]:
        print(f"  #{r['rank']:3d}  {r['display_name']}  ({r['match_confidence']:.0f}%)")
