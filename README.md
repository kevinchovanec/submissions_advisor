# Submissions Advisor

A tool for short fiction writers to find the best open literary journals for each story. Paste in results from a Duotrope search, and the app cross-references them against a curated ranked list of ~550 literary and genre journals — ranked by a weighted prestige score drawn from prize wins, circulation, and pay — and returns a prioritized list. A conversational AI agent lets you describe your story, get tailored journal recommendations, and draft cover letters, all in one place.

---

## What it does

- **Ranks open journals** — paste Duotrope search results and get them back sorted by prestige, filtered to what's currently accepting submissions
- **Tracks your stories** — each story has its own file recording word count, style, description, and full submission history
- **Gives tailored advice** — describe your story to the AI agent and it reads journal guidelines on demand, factors in where you've already submitted, and recommends the best fits
- **Drafts cover letters** — the agent can generate a personalized cover letter in your preferred style using your saved templates
- **Logs submissions** — tell the agent you're submitting somewhere and it records it automatically so it won't suggest that journal again

---

## Before you start

You'll need three things installed on your computer:

1. **Git** — for downloading the project. Get it at [git-scm.com](https://git-scm.com). On Windows, install "Git for Windows" and use the Git Bash terminal it provides.
2. **Miniconda** — installs Python and manages the packages the app needs. Get it at [docs.conda.io/en/latest/miniconda.html](https://docs.conda.io/en/latest/miniconda.html). Choose the version for your operating system. (You do not need to install Python separately — Miniconda handles it.)
3. **An Anthropic API key** — the AI agent runs on Claude. Sign up at [console.anthropic.com](https://console.anthropic.com), create an account, and generate an API key. There is a small per-use cost; typical usage runs a few cents per session.

> **What is a terminal?** On Windows, open the Start menu and search for "Anaconda Prompt" (installed with Miniconda) — use that for all the commands below. On Mac, use the Terminal app (search for it with Spotlight).

---

## Setup

### Step 1 — Download the project

Open your terminal and run these commands one at a time. After each one, wait for it to finish before running the next.

```
git clone https://github.com/YOUR-USERNAME/submissions_advisor.git
cd submissions_advisor
```

> `git clone` downloads a copy of the project to your computer. `cd submissions_advisor` moves you into the project folder.

### Step 2 — Create the Python environment

```
conda create -n submission_advisor python=3.11
conda activate submission_advisor
pip install -r requirements.txt
```

> This creates an isolated Python environment called `submission_advisor` and installs all the packages the app needs. You only need to do this once. Every time you open a new terminal session, you'll need to run `conda activate submission_advisor` again before launching the app.

### Step 3 — Get an Anthropic API key

The AI agent runs on Claude, made by Anthropic. You'll need an API key to use it.

1. Go to [console.anthropic.com](https://console.anthropic.com) and create an account
2. Once logged in, click **API Keys** in the left sidebar
3. Click **Create Key**, give it a name (e.g. "submissions advisor"), and copy the key that appears — you won't be able to see it again
4. You'll also need to add a payment method under **Billing**. There is no free tier, but costs are very low — typical sessions run a few cents. You can set a monthly spend limit for peace of mind.

> Keep your API key private. Don't share it with anyone or include it in files you upload to the internet.

Now add the key to the project so the app can find it:

**Simplest option — use the included `.env` file (works on all platforms):**

1. In the project folder, find the file called `.env.example`
2. Make a copy of it and rename the copy to `.env`
3. Open `.env` in any text editor and replace `your-key-here` with your actual key:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
4. Save the file. The app loads it automatically on startup.

The `.env` file is gitignored — it stays on your computer only and is never uploaded.

**Alternative — set it as a system environment variable (persists across projects):**

On Windows (Anaconda Prompt):
```
setx ANTHROPIC_API_KEY "your-key-here"
```
Close and reopen the terminal after running this.

On Mac/Linux (Terminal):
```
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.zshrc && source ~/.zshrc
```

### Step 4 — Launch the app

```
conda activate submission_advisor
streamlit run app.py
```

The app opens automatically in your browser at `http://localhost:8501`. Leave the terminal window open while using the app — closing it stops the server.

**Optional: create a desktop shortcut**

A `launch.example.bat` file is included in the project folder. Copy it, rename the copy to `launch.bat`, and replace `YOUR_USERNAME` with your Windows username. Double-clicking it will activate the environment and launch the app without opening a terminal manually. Right-click → **Send to → Desktop (create shortcut)** to put it on your desktop.

---

## Cover letter templates (optional)

The AI agent can draft cover letters using your personal templates. Templates are stored as plain text files in `data/cover_letter_templates/`. Three template styles are supported:

- **short** (`data/cover_letter_templates/short.md`) — a bare-minimum letter with no bio, for journals that prefer brevity or discourage lengthy cover letters
- **standard** (`data/cover_letter_templates/standard.md`) — your default letter with a short first-person bio
- **bio** (`data/cover_letter_templates/bio.md`) — includes a third-person bio paragraph, for journals that specifically request one

A generic example is included at `data/cover_letter_templates/standard_example.md`. Copy it to `standard.md` and fill in your personal details:

```
cp data/cover_letter_templates/standard_example.md data/cover_letter_templates/standard.md
```

Then open `standard.md` in any text editor and replace the bracketed placeholders with your information. These files are gitignored — they stay on your computer only and are never uploaded.

---

## Using the app

The app has two mostly independent halves: **journal matching** (which requires a Duotrope subscription) and **story management + AI advice** (which requires an Anthropic API key). You can use either half without the other.

### Genre mode

Use the **Genre** selector in the sidebar to switch between literary and science fiction rankings. The two lists are ranked independently — switching resets the conversation.

---

### Journal matching

The matching feature works with [Duotrope](https://duotrope.com), which requires a paid subscription. It cross-references Duotrope's list of currently open journals against the built-in ranked list and returns only the journals that are both open and ranked, sorted by prestige.

1. Log into Duotrope and run a search — filter by open markets, fiction, your preferred length, etc.
2. Select all results on the page (Ctrl+A or Cmd+A in the results area), copy, and paste into the **Paste Duotrope data** tab
3. Click **Add batch** — Duotrope shows 50 results per page, so repeat for each page
4. Click **Match against rankings**
5. If any matches are flagged as uncertain, a review panel appears — check them and reject any that look wrong
6. Download the ranked list as Excel or CSV

To pick up where you left off in a previous session, upload your previously downloaded CSV via the **Upload CSV** tab — the app recognizes it and restores your results without re-pasting.

#### Custom rankings

If you want to use your own ranked list of journals instead of the built-in one, upload an Excel file via the **Upload CSV** tab. The file needs at minimum a `rank` column and a `name` column. A `score` column and a `journal_url` column are optional but recommended. Your custom list takes precedence over the defaults for as long as it's uploaded; remove it to revert.

---

### Story management

The **Stories** tab is a personal database of your short fiction. Each story has its own record tracking title, word count, style, description, and full submission history.

#### Creating a story card

Click **New story** and fill in the form manually, or use the **Generate card with AI** expander to let Claude do it:

1. Expand **Generate card with AI**
2. Paste in your story text (or a substantial excerpt)
3. Check the consent box — this sends your text to the Anthropic API
4. Click **Generate card** — Claude reads the story and suggests a title, word count, style description, and one-paragraph summary
5. Review and edit the generated fields before saving

> **Privacy note:** The AI card generator sends your story text to Claude via the Anthropic API. If you'd prefer to keep your story text off the internet entirely, fill in the card manually instead — the style and description fields are short and easy to write yourself.

#### Tracking submissions

From any story's detail view in the **Stories** tab you can:

- **Log a submission** — record that you submitted to a journal, with date and optional notes. This prevents the agent from suggesting that journal again for this story.
- **Update an outcome** — mark a submission as accepted, rejected, or withdrawn once you hear back

All submission history is also mirrored to an Excel file (`data/submission_tracking.xlsx`) in your project folder, so you have a standalone spreadsheet backup of your full submission history across all stories.

#### Story files

Stories are stored as plain text files in `data/stories/` on your computer. You can open and edit them directly in any text editor if you prefer:

```
---
title: "The Glass Wall"
word_count: 4200
style: "lyric realism, second person"
submitted_to:
  - journal: "Ploughshares"
    date: "2026-05-01"
    outcome: pending
    notes: ""
---

A story about a woman returning to her childhood home...
```

---

### AI advisor

The **Discuss** tab is a chat interface with an AI literary advisor. Load a story first from the **Stories** tab, then go to **Discuss**.

The agent knows:
- Your story's title, word count, style, and description
- Which journals you've already submitted to (and won't re-suggest them)
- The full ranked list of open journals, including summaries of their submission guidelines
- Any encouraging feedback you've received from editors

What you can ask it to do:
- **Recommend journals** — it reads submission guidelines on demand for any journals it's seriously considering, then gives specific, ranked suggestions with honest assessments of fit and reach
- **Draft a cover letter** — ask for a cover letter in any of your saved template styles (e.g., "Draft a cover letter using my standard template"). It fills in the story title, word count, and journal-specific details automatically.
- **Log a submission** — tell it "I'm going to submit to One Story" and it records the submission in your story file
- **Discuss strategy** — comp titles, style comparisons, submission sequencing, anything else useful

The agent only fetches journal pages when it's seriously considering a journal — it doesn't read every page upfront, which keeps sessions fast and costs low.

---

## Your data and privacy

- **Story files and submission history** are stored only on your computer in `data/stories/` and are never uploaded anywhere
- **The Excel tracker** lives in `data/submission_tracking.xlsx` on your computer
- **The AI agent** sends your story description and journal information to the Anthropic API when you use the Discuss tab. Anthropic does not use API calls to train their models by default. Your cover letter templates are only sent to the API when you ask for a cover letter.
- **API costs** are billed to your Anthropic account. Typical sessions cost a few cents. You can monitor usage at [console.anthropic.com](https://console.anthropic.com).

---

## Troubleshooting

**The app won't start / "streamlit: command not found"**
Make sure you ran `conda activate submission_advisor` in the same terminal window before running `streamlit run app.py`.

**"No module named X" error**
Run `pip install -r requirements.txt` again with the environment activated.

**The AI features don't work / "API key not found"**
Double-check that your API key is set. In your terminal, run `echo $ANTHROPIC_API_KEY` (Mac/Linux) or `echo %ANTHROPIC_API_KEY%` (Windows) — it should print your key. If it prints nothing, revisit Step 3.

**A journal name didn't match correctly**
Add a manual correction to `data/manual_overrides.csv`:
```
duotrope_name,ranked_name
some journal name,correct ranked name
```
Names should be lowercase, with any leading "the" removed and punctuation stripped — the same way the app normalizes them internally.

---

## Project structure

```
submissions_advisor/
├── data/
│   ├── rankings_cache.json            # built-in ranked journal list (~550 journals)
│   ├── custom_rankings_cache.json     # your uploaded rankings, if any (gitignored)
│   ├── manual_overrides.csv           # hand-corrected name matches
│   ├── cover_letter_templates/        # your cover letter templates
│   │   ├── standard_example.md        # generic starting point (tracked in git)
│   │   ├── short.md                   # your short template (gitignored)
│   │   ├── standard.md                # your standard template (gitignored)
│   │   └── bio.md                     # your bio template (gitignored)
│   └── stories/                       # per-story files (gitignored)
├── docs/
│   └── to_do.md                       # roadmap for hosted public version
├── outputs/                           # exported Excel files (gitignored)
├── src/
│   ├── agent.py                       # conversational AI agent
│   ├── cover_letters.py               # template loader
│   ├── fetch_about.py                 # journal page fetcher
│   ├── ingest.py                      # Duotrope paste parser
│   ├── match.py                       # fuzzy name matching
│   ├── output.py                      # Excel export builder
│   ├── scrape_rankings.py             # rankings loader
│   ├── stories.py                     # story file read/write
│   ├── summarize_journals.py          # journal summary cache
│   └── workbook.py                    # submission tracker Excel read/write
├── app.py                             # Streamlit UI
├── requirements.txt
└── README.md
```
