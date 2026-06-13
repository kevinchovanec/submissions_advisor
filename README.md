# Submissions Advisor

A tool for short fiction writers to find the best open literary journals for each story. Cross-reference a list of open journals against a curated ranked list of ~550 literary and genre markets, get tailored AI recommendations, and track your submission history — all in one place.

---

## Two ways to use it

### Online app *(easiest)*

**[https://submissions-advisor.onrender.com](https://submissions-advisor.onrender.com)**

No installation required. Create an account, add your Anthropic API key, and start using it immediately. Your story metadata and submission history are stored securely in the cloud, accessible from any browser.

> **Privacy note:** We store your story titles, descriptions, and submission history — never the manuscript text itself. Your data is not used for any purpose other than displaying it back to you, and is never shared or sold. See the [privacy policy](https://submissions-advisor.onrender.com/privacy) in the app for full details. You can download or delete your data at any time from Settings.

### Local install *(recommended for maximum privacy)*

Clone the repo and run it on your own computer. Your stories and submission history live entirely on your machine and never leave it — the only outbound connections are to the Anthropic API when you actively use an AI feature, and to journal websites when the agent fetches submission guidelines.

---

## What it does

- **Ranks open journals** — paste results from Duotrope, The Submission Grinder, or any other source and get them back sorted by prestige, filtered to what's currently accepting submissions
- **Tracks your stories** — each story has a record with word count, style, description, and full submission history
- **Gives tailored advice** — describe your story to the AI agent and it reads journal guidelines on demand, factors in where you've already submitted, and recommends the best fits
- **Drafts cover letters** — the agent generates a personalized cover letter in your preferred style using your saved templates
- **Logs submissions** — tell the agent you're submitting somewhere and it records it so it won't suggest that journal again

---

## Using the online app

1. Go to the app URL above and click **Sign up**
2. Confirm your email address
3. Enter your Anthropic API key when prompted (see [Getting an API key](#getting-an-anthropic-api-key) below)
4. That's it — start with the Matcher tab

Your API key is stored in your browser session only and is cleared when you close the tab. It is never written to the database.

> **First load may be slow.** The free hosting tier sleeps after 15 minutes of inactivity. The first visit after a quiet period can take up to 60 seconds to wake up — the page will appear to hang and then load all at once. Subsequent requests are fast for as long as the app stays active.

---

## Local install

### What you'll need

1. **Git** — [git-scm.com](https://git-scm.com). On Windows, install "Git for Windows" and use the Git Bash or Anaconda Prompt terminal it provides.
2. **Miniconda** — [docs.conda.io/en/latest/miniconda.html](https://docs.conda.io/en/latest/miniconda.html). Installs Python and manages packages. (You do not need to install Python separately.)
3. **An Anthropic API key** — see below.

> **What is a terminal?** On Windows, open the Start menu and search for "Anaconda Prompt" — use that for all the commands below. On Mac, use the Terminal app (search for it with Spotlight).

### Step 1 — Download the project

```
git clone https://github.com/kevinchovanec/submissions_advisor.git
cd submissions_advisor
```

### Step 2 — Create the Python environment

```
conda create -n submission_advisor python=3.11
conda activate submission_advisor
pip install -r requirements.txt
```

You only need to do this once. In future sessions, just run `conda activate submission_advisor` before launching.

### Step 3 — Getting an Anthropic API key

The AI features run on Claude, made by Anthropic. You'll need an API key to use them. The journal matching and submission tracking features work without one.

1. Go to [console.anthropic.com](https://console.anthropic.com) and create an account
2. Click **API Keys** in the left sidebar → **Create Key**
3. Copy the key — you won't be able to see it again
4. Add a payment method under **Billing** — there's no free tier, but typical sessions cost a few cents. You can set a monthly spend limit.

> Keep your API key private. Don't share it or include it in files you upload anywhere.

Add the key to your local project:

1. Find the file `.env.example` in the project folder
2. Copy it and rename the copy to `.env`
3. Open `.env` and replace `your-key-here` with your key:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

The `.env` file is gitignored and never uploaded.

### Step 4 — Create your launcher

**Windows:**
1. Copy `launch.example.bat` → rename the copy to `launch.bat`
2. Open it in a text editor and replace `YOUR_USERNAME` with your Windows username
3. Double-click `launch.bat` — it activates the environment, starts the server, and opens the app in your browser
4. Right-click → **Send to → Desktop (create shortcut)** to keep it handy

**Mac/Linux:**
1. Copy `launch.example.sh` → rename the copy to `launch.sh`
2. Run `chmod +x launch.sh` to make it executable
3. Double-click it or run `./launch.sh`

The app opens at `http://localhost:8000`. Leave the terminal window open while using the app — closing it stops the server.

---

## Cover letter templates

The AI agent can draft cover letters using your personal templates. Three styles are supported:

- **short** — a bare-minimum letter with no bio, for journals that discourage lengthy letters
- **standard** — your default letter with a short first-person bio
- **bio** — includes a third-person bio paragraph, for journals that specifically request one

**Online app:** Create and edit your templates directly in the app under Settings → Templates.

**Local install:** Templates live in `data/cover_letter_templates/`. A generic example is at `data/cover_letter_templates/standard_example.md`. Copy it to `standard.md` and fill in your details:

```
cp data/cover_letter_templates/standard_example.md data/cover_letter_templates/standard.md
```

These files are gitignored and stay on your computer only.

---

## Using the app

The app has two mostly independent halves: **journal matching** and **story management + AI advice**. You can use either without the other.

### Journal matching

The Matcher tab cross-references a list of open journals against the built-in ranked list, returning only journals that are both open and ranked, sorted by prestige.

#### Getting a list of open journals

**[Duotrope](https://duotrope.com)** *(paid, ~$5/month)* — the most reliable source. Log in, run a search filtered to open markets and your preferred length, copy the results page, and paste into the Matcher.

**[The Submission Grinder](https://thesubmissiongrinder.com)** *(free)* — similar data. Copy and paste results from a search.

**Any plain text list** — paste journal names one per line. The app parses the first column of tab-separated text, so results tables from most submission tracking sites work.

Duotrope and The Submission Grinder show 50 results per page. Click **Add batch** after each page, then **Match journals** when you've loaded all pages.

> If you're not using Duotrope, you'll want to verify which journals are currently open before submitting — the app cross-references names, but doesn't check open/closed status itself.

#### Custom rankings

To use your own ranked list instead of the built-in one, upload an Excel or CSV file in the Matcher tab. Required columns: `rank`, `name`, `journal_url`. Optional: `score`, `tier`. Your custom list is used for the current session; click **Remove** to revert to the built-in rankings.

---

### Story management

The **Stories** tab is a personal database of your short fiction. Each story tracks title, word count, style, description, and full submission history.

#### Creating a story card

Click **New story** and fill in the form, or use **Generate card with AI** to let Claude suggest a title, style description, and summary from your manuscript text.

> **Privacy note:** The AI card generator sends your story text to the Anthropic API. If you prefer to keep your manuscript text off the internet, fill in the card manually — the description field only needs a few sentences.

#### Tracking submissions

From any story's detail view you can log a submission (journal, date, notes) and update outcomes as they arrive. The agent reads this history automatically and won't suggest journals you've already submitted to.

**Local install:** Submission history is also saved to `data/submission_tracking.xlsx` as a standalone spreadsheet backup.

---

### AI advisor

The **Discuss** tab is a chat interface with an AI literary advisor. Open a story from the Stories tab, then go to Discuss.

The agent knows your story's metadata, which journals you've already submitted to, the full ranked list with submission guideline summaries, and any editor feedback you've logged.

What you can ask it to do:
- **Recommend journals** — it reads submission guidelines on demand for journals it's seriously considering, then gives specific suggestions with honest assessments of fit and reach
- **Draft a cover letter** — "Draft a cover letter using my standard template." It fills in story-specific and journal-specific details automatically.
- **Log a submission** — "I'm going to submit to One Story." It records it so that journal won't be suggested again.
- **Discuss strategy** — comp titles, submission sequencing, style comparisons, anything else

---

## Your data and privacy

|  | Local install | Online app |
|---|---|---|
| Story files | On your computer only | Stored in Supabase (AWS) |
| Submission history | On your computer only | Stored in Supabase (AWS) |
| Manuscript text | Never stored anywhere | Never stored anywhere |
| AI sessions | Sent to Anthropic API | Sent to Anthropic API |
| API key | In your `.env` file | Browser session only, never in DB |

In both modes: your data is never sold, never used to train models, and never shared with third parties beyond Supabase (infrastructure) and Anthropic (AI features you actively use). Online users can download or delete all their data from the Settings page at any time.

Anthropic does not use API calls to train their models by default. See [Anthropic's privacy policy](https://www.anthropic.com/privacy) for details.

---

## Troubleshooting

**The app won't start / browser doesn't open** *(local)*
Make sure you ran `conda activate submission_advisor` before launching. If the browser shows an error, wait a few seconds and refresh — the server may still be starting.

**"No module named X" error** *(local)*
Run `pip install -r requirements.txt` again with the environment activated.

**The AI features don't work / "No API key"** *(local)*
Check that `.env` exists in the project folder and contains `ANTHROPIC_API_KEY=sk-ant-...`.

**A journal name didn't match correctly**
Add a manual correction to `data/manual_overrides.csv`:
```
duotrope_name,ranked_name
some journal name,correct ranked name
```
Names should be lowercase, with any leading "the" removed and punctuation stripped.

---

## Project structure

```
submissions_advisor/
├── api/
│   ├── main.py                        # FastAPI app — all endpoints
│   ├── dependencies.py                # auth middleware, storage injection
│   └── models.py                      # Pydantic request/response models
├── frontend/
│   ├── src/                           # React source (TypeScript + Vite)
│   ├── dist/                          # pre-built bundle (committed via CI)
│   └── package.json
├── src/
│   ├── agent.py                       # conversational AI agent
│   ├── ingest.py                      # journal list parser
│   ├── match.py                       # fuzzy name matching
│   ├── scrape_rankings.py             # rankings loader
│   ├── storage.py                     # storage interface (ABC)
│   ├── storage_local.py               # local file backend
│   ├── storage_supabase.py            # Supabase cloud backend
│   └── workbook.py                    # Excel tracker (local)
├── data/
│   ├── rankings_cache.json            # built-in ranked journal list (~550 journals)
│   ├── manual_overrides.csv           # hand-corrected name matches
│   ├── cover_letter_templates/        # your templates (gitignored)
│   │   └── standard_example.md
│   └── stories/                       # per-story files, local mode (gitignored)
├── sql/
│   └── schema.sql                     # Supabase schema (cloud mode)
├── .github/workflows/
│   └── build-frontend.yml             # rebuilds frontend/dist/ on push
├── launch_app.py                      # local launcher
├── launch.example.bat                 # Windows launcher template
├── launch.example.sh                  # Mac/Linux launcher template
├── requirements.txt
└── README.md
```
