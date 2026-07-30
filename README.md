# Data-Analyst Telegram Bot — setup notes

## 1. Create the bot
Telegram → `@BotFather` → `/newbot`. Copy the token it gives you.

## 2. Get an aipipe.org token
`aipipe.org/login` with your student email → copy the token (starts `eyJ...`).

## 3. Install and configure
```
pip install -r requirements.txt
cp .env.example .env   # fill in the values below
```
- `TELEGRAM_BOT_TOKEN`, `AIPIPE_TOKEN` — as above.
- `LOG_URL` — the raw URL you intend `run.jsonl` to live at, e.g.
  `https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/run.jsonl`
  (needs a real value even before you've pushed anything, since the bot
  writes this exact string into every reply).
- `GITHUB_TOKEN` — a fine-grained personal access token
  (github.com → Settings → Developer settings → Personal access tokens →
  Fine-grained tokens), scoped to just this one repo, with **Contents:
  Read and write** permission. This lets the bot push `run.jsonl` updates
  through GitHub's API without needing git installed/authenticated on
  whatever host you deploy to.
- `GITHUB_REPO` — `YOUR_USERNAME/YOUR_REPO`.

## 4. Test locally
```
export $(cat .env | xargs)   # or use python-dotenv if you prefer
python bot.py
```
Message your bot from a **fresh Telegram chat** (not one you've already
tested from) with something like:
`Reply with ONLY this JSON: {"answer": <15% of 200>, "log_url": "..."}`

## 5. Test against the real grading pipeline
The zip you have (`Jivraj-18/tds-p1-t2-2026-telegram-bot`) is the actual
harness used for grading. It's a **generic multi-question pipeline** — the
one sample question in `evals/questions.json` doesn't include the
`answer`/`log_url` wrapper, but that's just a placeholder for local testing.
The real, private questions for this assignment will ask for that wrapper
directly, so your bot doesn't need to guess the shape — it always follows
whatever the incoming message says.

To dry-run it yourself, first make your **own** roster CSV — don't use
`students.example.csv` as-is, its `telegram_bot_username` is a fake
placeholder (`student1_tds_bot`) that Telegram can't resolve, which shows up
as a `bad_bot` result:
```
echo "email,github_url,telegram_bot_username" > students.csv
echo "you@example.edu,https://github.com/YOU/YOUR_REPO,your_real_bot_username" >> students.csv
```
Also edit `evals/questions.json` and replace the shipped `"REPLACE_ME"`
placeholder with the actual correct answer — otherwise `grade.py` will
always report 0/1 even if your bot's answer is right, since it's comparing
against a placeholder string. This file is only for your own local testing;
the real graded questions are private and separate.

Then:
```
python3 generate.py --students students.csv   # -> inputs.json, key.json
python3 collect.py  --students students.csv   # sends messages, records replies
python3 grade.py    --students students.csv   # -> data/<slug>/grade.json
```
This needs your own `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`/`TELEGRAM_SESSION_STRING`
in the pipeline's own `.env` (see its README) — these are a **user account**
login (via `login.py`), separate from your bot's token, because bots can't
message other bots.

## 6. Host run.jsonl publicly
Simplest option: commit `run.jsonl` into this repo and use the raw GitHub URL:
```
https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/run.jsonl
```
Verify with `wget <url>` in a fresh terminal (no login) — it should print raw
JSON lines, not an HTML page. If you see a webpage, you copied the normal
GitHub link instead of the "Raw" one.

## 7. Push to a **public** GitHub repo
Before pushing, make sure `bot.py` has no hardcoded tokens (it doesn't — it
reads them from the environment). The included `.gitignore` already excludes
`.env` and session/cache files — commit and push everything else, including
`run.jsonl` once you've generated it locally, so the raw URL resolves
immediately rather than waiting on the bot's first push cycle.

## 8. Deploy so it's always on
Render.com (Background Worker) or Railway.app: connect the repo, set the
start command to `python bot.py`, add all six environment variables
(`TELEGRAM_BOT_TOKEN`, `AIPIPE_TOKEN`, `LOG_URL`, `GITHUB_TOKEN`,
`GITHUB_REPO`, and optionally `AIPIPE_MODEL`) in the dashboard, deploy. Then
message the bot from your phone to confirm it's replying from the live
server, not your laptop.

## 9. Register
Submit: `https://github.com/YOUR_USERNAME/YOUR_REPO, your_bot_username`
