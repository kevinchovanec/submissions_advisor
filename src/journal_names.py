"""
One display name per journal.

Submissions and editor notes carry whatever the writer typed, so one journal turns
up under several spellings - "Dr. T. J. Eckleburg Review", "T J Eckleburg Review",
"Eckleburg" - against the ranked "Dr. T.J. Eckleburg Review". The resolver maps a
typed name to the ranked spelling for display only. Stored names never change:
outcome edits and deletes find a submission by the name it was logged under.

A name resolves when it is, in order:
  1. listed in data/manual_overrides.csv,
  2. the same as a ranked name once spaces are dropped ("T. J." vs "T.J."), or
  3. a fuzzy match at REVIEW_THRESHOLD or above.
Anything else displays as typed. The bar is higher than the matcher's 85 because a
wrong guess here would relabel the writer's own history.
"""

from __future__ import annotations

from rapidfuzz import fuzz, process

from ingest import normalize_name
from match import REVIEW_THRESHOLD, _load_overrides


def _compact(norm: str) -> str:
    return norm.replace(" ", "")


class JournalNameResolver:
    def __init__(self, rankings: list[dict]):
        self._ranked = {r["normalized_name"]: r["name"] for r in rankings}
        # Stored keys were normalized with the source list's asterisk still on, so
        # "*The Boiler" kept its "the"; the cleaned name normalizes as typed would.
        self._aliases = {normalize_name(r["name"]): r["normalized_name"] for r in rankings}
        self._compact = {_compact(k): k for k in self._ranked}
        self._overrides = _load_overrides()
        self._cache: dict[str, str] = {}

    def display(self, name: str) -> str:
        """The ranked spelling of `name` if it resolves to a ranked journal, else `name`."""
        if not name or not name.strip():
            return name
        if name not in self._cache:
            key = self._resolve(normalize_name(name))
            self._cache[name] = self._ranked[key] if key else name
        return self._cache[name]

    def _resolve(self, norm: str) -> str | None:
        override = self._overrides.get(norm)
        if override in self._ranked:
            return override
        if override in self._aliases:
            return self._aliases[override]
        if norm in self._ranked:
            return norm
        if norm in self._aliases:
            return self._aliases[norm]
        if _compact(norm) in self._compact:
            return self._compact[_compact(norm)]
        hit = process.extractOne(
            norm, list(self._ranked), scorer=fuzz.token_sort_ratio, score_cutoff=REVIEW_THRESHOLD,
        )
        return hit[0] if hit else None
