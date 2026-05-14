# Product Intelligence

> Upload customer feedback. Get the top 5 pain points, a sentiment dashboard, a full PRD, and engineering tickets — all powered by AI.

This is the full implementation of the brief: a single application that turns raw customer voice into structured product intelligence.

---

## What's inside

All seven features from the spec, working end-to-end:

| # | Feature | Where it lives |
|---|---|---|
| 1 | **Smart Data Intake** — CSV upload, paste raw text, auto-detect text column, dedup, preview | `backend/intake.py` |
| 2 | **AI Insight Engine** — top 5 pain points ranked, with citations to actual users | `backend/insights.py` + `backend/llm_client.py` |
| 3 | **Natural Language Query** — ask any question, get an answer grounded in your data | `backend/query.py` |
| 4 | **PRD Generator** — one click on an insight produces a full PRD | `backend/prd.py` |
| 5 | **Insight Dashboard** — pain point cards, sentiment donut, trending topics, voice of customer | `frontend/index.html` |
| 6 | **Dev Task Generator** — break a PRD into engineering tickets, export as text | `backend/prd.py` |
| 7 | **Auth + Workspace** — Clerk-based signup/login, per-user datasets | `backend/auth.py` |

Plus PDF and Markdown export of any PRD.

---

## Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite (zero setup) + Google Gemini SDK + ReportLab (PDFs)
- **Frontend:** Single-page app, vanilla JS, Tailwind via CDN, Chart.js for the sentiment donut
- **Auth:** [Clerk](https://clerk.com) — managed authentication with email + Google sign-in via Clerk's pre-built UI components
- **Database:** SQLite by default — switch `DATABASE_URL` in `.env` for Postgres
- **AI provider:** Google Gemini (free tier — no credit card required)

> Why these choices? Two reasons. First, the spec asked for a working product, and SQLite + a single Python server means you can run this with one command. Second, the AI quality depends on the prompts, not the framework — so the engineering choices that matter live in `backend/llm_client.py`.

---

## Prerequisites

1. **Python 3.10 or newer** — check with `python --version` (Windows) or `python3 --version` (Mac/Linux)
2. **A Google Gemini API key** — get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). No credit card needed. Free tier is enough to test the app end-to-end.
3. **A Clerk account** — sign up free at [clerk.com](https://clerk.com), create an application (pick Email + Google as sign-in methods), and copy the Publishable Key and Secret Key from the API Keys page. Free tier covers 50,000 monthly users.

That's it. No Node, no Postgres, no Redis, no Docker.

> **Heads-up on the deployment files in this repo.** You'll see `render.yaml`, `Procfile`, and `runtime.txt` at the project root. These are only used when deploying to Render (see "Going to production" below). They are completely ignored when running locally — you can safely leave them alone, and you don't need a Render account to run the app on your laptop.

---

## Quick start

### macOS / Linux

```bash
cd product-intelligence
chmod +x run.sh
./run.sh
```

### Windows

Double-click `run.bat`, or from a terminal:

```cmd
cd product-intelligence
run.bat
```

The launcher will:
1. Create a Python virtual environment in `.venv/` (first run only)
2. Install all dependencies
3. Copy `.env.example` to `.env` if it doesn't exist
4. Start the server on `http://localhost:8000`

### Add your API key

After the first run, **open `.env` and replace `your-gemini-api-key-here`** with your actual Gemini API key:

```
GEMINI_API_KEY=AIzaSy...your-actual-key...
```

Then restart the server (Ctrl+C, then `./run.sh` or `run.bat` again). Without the key, intake and dashboard will work, but the AI features will return an error.

---

## Manual install (if the launchers don't work)

```bash
cd product-intelligence
python -m venv .venv
.venv\Scripts\activate              # on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # on macOS/Linux: cp .env.example .env
# edit .env and add your API key
uvicorn backend.main:app --reload --port 8000
```

Then open http://localhost:8000.

---

## How to use it

### 1. Sign up

Open http://localhost:8000. Sign up via Clerk's pre-built component using your email (Clerk emails you a verification code) or Google sign-in. Each user gets their own isolated workspace stored in the local database.

### 2. Upload data

Click **Datasets** in the sidebar. You have two options:

- **Upload a CSV** — drag any CSV with a feedback/comment/review column. The app auto-detects the text column, deduplicates, and shows a preview before saving. There's a `sample-feedback.csv` included in the project root if you want to try it instantly.
- **Paste text** — paste feedback directly. Each line (or paragraph separated by blank lines) becomes one feedback item.

### 3. Run the AI analysis

Click **Dashboard**, pick your dataset, and click **Run AI analysis**.

In ~10–30 seconds, you get:
- Top 5 pain points, ranked by frequency × emotional intensity
- Each pain point shows: who's affected, the emotional tone, a recommendation, and citations to the actual customers who said it
- An overall sentiment donut (positive / neutral / negative)
- Trending topics
- Voice of customer feed with real quotes

### 4. Ask anything

Click **Ask anything**. Type questions like:
- "Why are users churning?"
- "What do power users love?"
- "What's the most common mobile bug?"

You get an answer using only your dataset, with citations linking to the specific customers who said it.

### 5. Generate a PRD

On any pain point card, click **📄 Generate PRD**. The system writes a full Product Requirements Document with:
- Problem statement
- Who's affected
- Measurable success metrics
- User stories (As a... I want... so that...)
- Acceptance criteria

### 6. Generate dev tasks

Open any PRD, click **⚙️ Generate dev tasks**. The PRD gets broken into 5–10 engineering tickets, each with:
- A concrete title
- Context (why it matters + relevant user feedback)
- Acceptance criteria

### 7. Export

From any PRD page:
- **⬇️ Export PDF** — share with stakeholders or print
- **⬇️ Export Markdown** — paste straight into Notion / Linear / Confluence
- **⬇️ Download tasks (.txt)** — paste into Jira / Linear / GitHub Issues

---

## Project layout

```
product-intelligence/
├── backend/
│   ├── __init__.py
│   ├── main.py              ← FastAPI app + serves the frontend
│   ├── database.py          ← SQLAlchemy models (User, Dataset, Insight, PRD, DevTask)
│   ├── auth.py              ← Clerk session token verification + auto-provisioning
│   ├── llm_client.py        ← All AI prompts live here (the heart of the product)
│   ├── intake.py            ← CSV upload, text paste, cleaning, dedup, preview
│   ├── insights.py          ← AI Insight Engine endpoints
│   ├── query.py             ← Natural language Q&A
│   └── prd.py               ← PRD + dev tasks + PDF/Markdown export
├── frontend/
│   └── index.html           ← Entire SPA (auth, dashboard, datasets, query, PRDs)
├── requirements.txt
├── .env.example
├── sample-feedback.csv      ← 25 realistic feedback items to test with
├── run.sh                   ← macOS/Linux launcher
├── run.bat                  ← Windows launcher
└── README.md                ← This file
```

---

## API reference (for the curious)

All endpoints are under `/api`. All except `/api/health` and `/api/config` require a Bearer token (a Clerk session token, supplied by Clerk's frontend SDK).

### Auth
Authentication is handled by [Clerk](https://clerk.com). Users sign up and log in via Clerk's pre-built UI components in the frontend. The backend verifies Clerk's session JWTs against Clerk's JWKS endpoint and auto-provisions a User row on first authenticated request.
- `GET /api/auth/me` — current user (returns `{id, email}`)
- `POST /api/auth/me` — `{email}` → updates the cached email for the current user

### Public (no auth)
- `GET /api/health` — health check, returns `{ok, llm_configured}`
- `GET /api/config` — returns `{clerk_publishable_key, clerk_enabled}` for frontend init

### Intake
- `POST /api/intake/upload-csv` — multipart file → preview with `upload_token`
- `POST /api/intake/save` — `{upload_token, name, text_column, label_column?}` → dataset
- `POST /api/intake/paste` — `{name, text}` → dataset
- `GET /api/intake/datasets` — list user's datasets
- `GET /api/intake/datasets/{id}/items` — list feedback items
- `DELETE /api/intake/datasets/{id}` — delete

### Insights
- `POST /api/insights/datasets/{id}/run` — run AI analysis
- `GET /api/insights/datasets/{id}` — fetch stored report

### Query
- `POST /api/query/ask` — `{dataset_id, question}` → `{answer, key_points, citations}`

### PRDs
- `POST /api/prd/from-insight/{insight_id}` — generate
- `GET /api/prd/` — list
- `GET /api/prd/{id}` — fetch
- `DELETE /api/prd/{id}`
- `POST /api/prd/{id}/tasks` — generate dev tasks
- `GET /api/prd/{id}/tasks` — list dev tasks
- `GET /api/prd/{id}/export.pdf` — download PDF
- `GET /api/prd/{id}/export.md` — download Markdown

There's also auto-generated docs at `http://localhost:8000/docs` once the server is running.

---

## Costs and quotas

The app uses **Google Gemini** through the free tier. As of the time of writing, the free tier on `gemini-2.5-flash-lite` allows roughly:

- **20 requests per day** on a brand-new account (Google has tightened free-tier limits over time; older accounts may see higher quotas)
- **10 requests per minute**
- **No cost** — no credit card required

A single full workflow uses about 4 requests (1 analysis + 1 query + 1 PRD + 1 dev-task generation), so the free tier is enough for several end-to-end demos per day. If you hit the daily limit, the quota resets at midnight Pacific Time (~12:30 PM IST).

If you want higher limits, you can add billing in Google AI Studio. Costs at the time of writing for `gemini-2.5-flash-lite` are roughly:
- One full analysis: less than $0.001
- One PRD: less than $0.001
- One set of dev tasks: less than $0.001

You can switch models by editing `GEMINI_MODEL` in `.env`. Options:
- `gemini-2.5-flash-lite` — default, fastest, free-tier friendly
- `gemini-2.5-flash` — more capable, smaller free quota
- `gemini-2.5-pro` — most capable, paid only

---

## Troubleshooting

**"GEMINI_API_KEY is not set"**
Open `.env`, add your key, restart the server.

**"Could not parse CSV"**
The intake module tries multiple encodings (UTF-8, UTF-8-with-BOM, Windows-1252, Latin-1) and separators (comma, tab, semicolon). If parsing still fails, re-export the CSV from Excel as "CSV UTF-8 (Comma delimited)" or from Google Sheets as "Comma-separated values."

**"No analysis yet"**
You haven't run the analysis on this dataset. Click **Run AI analysis** on the dashboard.

**Port 8000 already in use**
Edit `run.sh` / `run.bat` and change `--port 8000` to e.g. `--port 8765`.

**"Analysis failed: 429 RESOURCE_EXHAUSTED"**
You've hit Gemini's free-tier rate limit. Either wait until the per-minute window passes (~60 seconds) or until midnight PT for the daily reset. Or switch to `gemini-2.5-flash-lite` in `.env` if you're using a model with stricter quotas.

**The server starts but the page shows nothing**
Check the terminal for errors. Make sure `frontend/index.html` exists. Try opening `http://localhost:8000/docs` to confirm the API is up — if that works, the issue is just the frontend file.

---

## Going to production

This is built as a hackathon-grade MVP with production-friendly seams:

- **Swap SQLite for Postgres**: change `DATABASE_URL` in `.env` to `postgresql://...`
- **Swap or extend auth**: Clerk is already in place — you can add more sign-in methods (passkeys, Microsoft, etc.) from the Clerk dashboard with zero code changes
- **Lock down CORS**: set `ALLOWED_ORIGINS` env var (comma-separated origins) in `backend/main.py`
- **Move uploads to S3 or Supabase Storage**: replace `_PREVIEW_CACHE` in `intake.py` with object storage
- **Add background workers** (Celery/RQ) for analysis runs that exceed 30s

Note: SQLite does not work on ephemeral cloud platforms like Render because the local filesystem gets wiped on every redeploy. Switch to Postgres before deploying.

### Deploying to Render (one-click)

This repo ships with a `render.yaml` Blueprint for free-tier deployment to Render:

1. Sign up at [render.com](https://render.com) using GitHub.
2. In the dashboard, click **+ New → Blueprint**.
3. Connect this repository. Render reads `render.yaml` and provisions both the web service and a free Postgres database.
4. When prompted, paste your `GEMINI_API_KEY`. Other env vars are auto-configured.
5. Wait 5–8 minutes for the first build. You'll get a public URL like `https://product-intelligence-xxxx.onrender.com`.

**Notes:**
- Render's free Postgres expires after 90 days. Either pay for permanent Postgres, recreate the database, or migrate to a permanent free provider (Neon, Supabase).
- Render's free web tier sleeps after 15 minutes of inactivity. First request after sleep takes 30–60 seconds. Use a free uptime monitor (e.g., UptimeRobot pinging `/api/health` every 5 minutes) to keep it warm.
- Gemini's free API tier has geographic restrictions. Use the `oregon` or `frankfurt` Render regions, not `singapore` (Gemini API blocks Singapore data centers as of writing).

---

## License

Build whatever you want with this. Attribution appreciated but not required.
