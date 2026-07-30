# Data-Analyst Telegram Bot

A Telegram bot for **TDS P1 Q5**. It receives a data-analysis question over
Telegram, works out the answer using an LLM (via [aipipe.org](https://aipipe.org)),
and replies with exactly one JSON object:

```json
{"answer": "<shape the question asks for>", "log_url": "https://raw.githubusercontent.com/<user>/<repo>/main/run.jsonl"}
```

Every message the bot sends or receives is appended to `run.jsonl`, which is
kept publicly readable so the grader can review it.

## How it works

```
Telegram message
      │
      ▼
handle_message()  ──log──▶  run.jsonl
      │
      ▼
aipipe.org (LLM)
      │
      ▼
{"answer": ..., "log_url": ...}  ──log──▶  run.jsonl  ──push──▶  GitHub
      │
      ▼
Telegram reply
```

- The system prompt tells the model to answer only the *last* message in a
  conversation (earlier messages are context for multi-turn questions).
- The bot always overwrites whatever `log_url` the model produces with the
  real, configured one, and never adds keys beyond what the question shape
  requires.
- `run.jsonl` is pushed to GitHub after every exchange, via the GitHub
  Contents API — no `git` install or SSH key needed on the host.
- The bot runs in **webhook mode** when a public URL is available (e.g. on
  Render), and falls back to **polling** for local testing — no tunnel
  needed to develop on your own machine.

## Project structure

```
.
├── bot.py             # the bot
├── requirements.txt    # python-telegram-bot[webhooks], openai
├── .env.example        # template for local environment variables
├── .gitignore          # excludes .env, __pycache__, session files
└── README.md
```

## Setup

### 1. Create the Telegram bot
Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.

### 2. Get an AI Pipe token
[aipipe.org/login](https://aipipe.org/login) with your student email → copy
the token (starts `eyJ...`).

### 3. Create a GitHub personal access token
GitHub → Settings → Developer settings → Personal access tokens →
Fine-grained tokens → scope it to **just this repo**, with **Contents:
Read and write** permission. Used to push `run.jsonl` updates via the
GitHub API.

### 4. Configure environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `AIPIPE_TOKEN` | ✅ | From aipipe.org/login |
| `LOG_URL` | ✅ | Public raw URL where `run.jsonl` will live, e.g. `https://raw.githubusercontent.com/<user>/<repo>/main/run.jsonl` |
| `GITHUB_TOKEN` | ✅ | Fine-grained PAT with Contents: Read and write on this repo |
| `GITHUB_REPO` | ✅ | `<user>/<repo>` |
| `AIPIPE_MODEL` | optional | Defaults to `gpt-5-mini` — check `aipipe.org/playground` for current model names |
| `GITHUB_LOG_PATH` | optional | Path of the log file in the repo (default `run.jsonl`) |
| `GITHUB_BRANCH` | optional | Defaults to the repo's default branch |
| `WEBHOOK_URL` | optional | Public base URL for Telegram to call. Auto-detected on Render — set manually only on other hosts |
| `PORT` | optional | Port to listen on in webhook mode. Auto-set on Render |

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in the values above
```

### 5. Test locally
```bash
export $(cat .env | xargs)   # or use python-dotenv
python bot.py
```
No `WEBHOOK_URL` set → the bot runs in polling mode. Message it from a
**fresh** Telegram chat with something like:
```
Reply with ONLY this JSON: {"answer": <15% of 200>, "log_url": "..."}
```

### 6. Host `run.jsonl` publicly
Commit `run.jsonl` into this repo and use the raw GitHub URL as `LOG_URL`:
```
https://raw.githubusercontent.com/<user>/<repo>/main/run.jsonl
```
Verify it with `wget <url>` in a fresh terminal (no login) — it should
print raw JSON lines, not an HTML page. If you see a webpage, you copied
the normal GitHub link instead of the "Raw" one.

### 7. Deploy (Render free Web Service)
Background Workers aren't on Render's free plan, but Web Services are — the
bot's webhook mode qualifies it as one.

1. render.com → New → **Web Service** → connect this repo.
2. Build command: `pip install -r requirements.txt`. Start command:
   `python bot.py`. Instance type: **Free**.
3. Add the required environment variables above. Leave `WEBHOOK_URL` and
   `PORT` blank — Render provides `RENDER_EXTERNAL_URL`/`PORT` automatically.
4. Deploy, then check the logs for:
   `Bot running with model=..., webhook=https://<service>.onrender.com/<hash>, port=10000`
5. Message the bot from your phone, from a fresh chat, to confirm it's
   replying from the live server.

Free Web Services sleep after ~15 minutes of inactivity and take a few
seconds to wake on the next request. If you see missed replies during
testing, an external uptime pinger (UptimeRobot, cron-job.org) hitting the
service's URL every ~10 minutes keeps it warm.

## Testing against the grading pipeline

The pipeline used for grading is public
([`Jivraj-18/tds-p1-t2-2026-telegram-bot`](https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot)).
It's a generic multi-question harness — the shipped sample question in
`evals/questions.json` doesn't include the `answer`/`log_url` wrapper, and
its `expected` field is a literal `"REPLACE_ME"` placeholder, so replace both
before using it to sanity-check correctness locally. The real graded
questions are private and separate.

```bash
python3 generate.py --students students.csv
python3 collect.py  --students students.csv
python3 grade.py    --students students.csv
```
Requires `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION_STRING`
in the pipeline's own `.env` — a **user account** login via its `login.py`
(bots can't message other bots).
