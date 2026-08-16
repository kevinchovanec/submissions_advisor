# Tests

Two tiers, split by whether they cost money.

## Deterministic suite — no API key, no network

```
"C:\Users\kevin\anaconda3\envs\submission_advisor\python.exe" -m pytest tests/ -v
```

Covers the behaviours that have regressed before or would fail silently:

| File | What it pins down |
|---|---|
| `test_agent_context.py` | Pending journals are marked ⛔ even when the stored name differs from the ranked name (`Georgia Review` vs `The Georgia Review`); the roster excludes loaded stories and carries counts, not full history; the journal block comes first and holds the 1h cache breakpoint. |
| `test_pagefetch.py` | Same-site links survive the nav strip; cross-host, social, `mailto:`, and fragment links don't; SSRF guards reject loopback, private, link-local, and a redirect onto an internal address. |
| `test_summaries.py` | The three refresh gates. Most importantly: chrome (dates, countdowns, years) is normalized away, while a word-limit or fee change is **not** — and when a page changed but the extracted fields didn't, the stored prose is preserved byte-for-byte. |
| `test_tool_loop.py` | The loop stops at `MAX_TOOL_ITERATIONS` and at the fetch budget; failed tools are flagged `is_error`; `log_submission` refuses a story that isn't loaded. |

`FakeStorage` in `conftest.py` implements `StorageBackend` in memory, so nothing
touches `data/` or Supabase. `isolated_summaries` redirects the summary cache to a
temp dir.

## Behavioural eval — needs a key, costs tokens

```
set ANTHROPIC_API_KEY=sk-...
python evals/run_eval.py
```

Five scenarios against a real model call. This is the only check on the prompt
changes — that the agent actually declines to recommend a journal with a pending
submission, doesn't send two stories to one journal, surfaces a better roster story,
refuses to log an unloaded story, and reasons about length fit. Skips cleanly with no
key set; exits non-zero on failure.

Run it after editing `SYSTEM_PROMPT`, since nothing else catches a prompt regression.
