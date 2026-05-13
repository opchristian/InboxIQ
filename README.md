# InboxIQ

**InboxIQ** is an AI-powered inbox assistant that converts unstructured emails into structured tasks, deadlines, scheduling actions, and suggested replies.

## Problem

Important emails are buried in messy inboxes, making it easy to miss deadlines, follow-ups, and meeting updates.

## Solution

InboxIQ analyzes unstructured email content and turns it into structured action cards so you can see what matters at a glance.

## Current MVP features

- **Demo mode:** curated sample inbox emails for safe demos (always available, offline-friendly)
- **Live mode (optional):** Gmail OAuth + recent inbox fetch (`readonly` scope) — analyzes real connected inbox messages
- AI-ready classification workflow with structured task extraction
- Priority and category labels; deadlines and scheduling extraction
- Suggested reply generation with copy-to-clipboard in the UI
- Client-side search and filters (demo and live)
- JSON APIs: `/api/analyze` (demo dataset), `/api/live-analyze` (live Gmail)

## Tech stack

- Python
- Flask
- OpenAI API (optional with offline heuristic fallback)
- Gmail API + OAuth (optional live mode)
- HTML/CSS/JavaScript dashboard

## How to run locally

1. Install dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

2. Create a `.env` file from `.env.example` and set your OpenAI API key:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and assign your real key to `OPENAI_API_KEY`.

3. Start the app:

   ```bash
   python3 app.py
   ```

   Open the **demo** dashboard at [http://127.0.0.1:5000/](http://127.0.0.1:5000/). Demo JSON: [http://127.0.0.1:5000/api/analyze](http://127.0.0.1:5000/api/analyze).

## Live Gmail Sync Setup

Optional flow for analyzing real inbox threads (readonly Gmail scope):

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Enable **Gmail API** for that project.
3. Configure the **OAuth consent screen** (External or Internal as appropriate for your account).
4. Under **Credentials**, create an **OAuth client ID** of type **Desktop app**.
5. Download the OAuth client JSON file from the Console.
6. Rename it to `credentials.json`.
7. Place `credentials.json` in the **project root** next to `app.py` (same folder as this README).
8. Run `python3 app.py`.
9. Visit [http://127.0.0.1:5000/connect-gmail](http://127.0.0.1:5000/connect-gmail) and complete the browser sign-in flow.
10. After authorization, `token.json` is written locally (access + refresh tokens for your user — treat as secret).
11. Open **Live Inbox** at [http://127.0.0.1:5000/live-inbox](http://127.0.0.1:5000/live-inbox). Live JSON: [http://127.0.0.1:5000/api/live-analyze](http://127.0.0.1:5000/api/live-analyze).

**Do not commit `credentials.json` or `token.json`.** They are listed in `.gitignore`.

## Future improvements

- Save tasks to a database
- Calendar integration
- One-click reply drafting / send via Gmail API

## Security note

**Do not commit `.env`.** It contains secrets such as your OpenAI API key. Keep `.env` local and use `.env.example` only as a template without real credentials.
