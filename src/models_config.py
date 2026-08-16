"""Single source of truth for the Claude model the app calls.

Previously duplicated across agent.py, summarize_journals.py, and a literal in
api/main.py, so a model change meant three edits and could leave them disagreeing.
"""

# Conversational agent, journal summaries, and story-card generation all run on this.
MODEL = "claude-sonnet-4-6"
