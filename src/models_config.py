"""Single source of truth for the Claude model the app calls, and how it thinks.

Previously duplicated across agent.py, summarize_journals.py, and a literal in
api/main.py, so a model change meant three edits and could leave them disagreeing.
"""

# Conversational agent, journal summaries, and story-card generation all run on this.
MODEL = "claude-sonnet-5"

# On Sonnet 5, omitting `thinking` runs adaptive thinking — the opposite of Sonnet
# 4.6, where omitting it meant no thinking. Since max_tokens caps thinking AND
# response text together, that silently truncates any call with a tight budget. So
# both settings are explicit here rather than left to a default that changes between
# models.

# The conversational agent: thinking earns its cost on multi-story fit reasoning and
# tool selection. Streaming, so a large max_tokens carries no timeout risk.
AGENT_THINKING = {"type": "adaptive"}

# Structured extraction (journal summaries, story cards): the model emits a small
# JSON object against a tight token budget. Thinking would compete with that budget
# for no real gain, and a truncated reply is an outright parse failure.
EXTRACTION_THINKING = {"type": "disabled"}
