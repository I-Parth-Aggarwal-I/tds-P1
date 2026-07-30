#!/usr/bin/env python3
"""
Data-Analyst Telegram Bot — TDS P1 Q5

Listens for Telegram messages, asks an LLM (via aipipe.org) to work out the
answer, and replies with exactly one JSON object:

    {"answer": <shape the question asks for>, "log_url": "<public run.jsonl URL>"}

Every incoming/outgoing message is appended to run.jsonl, which must be
hosted somewhere public and reachable with a plain `wget` (see README.md).

Required environment variables (never hardcode these — see .env.example):
    TELEGRAM_BOT_TOKEN   from @BotFather
    AIPIPE_TOKEN         from aipipe.org/login
    LOG_URL              the public raw URL where run.jsonl will live
    GITHUB_TOKEN         a GitHub personal access token with write access to
                         the repo below (Settings -> Developer settings ->
                         Fine-grained tokens -> scope it to just this repo,
                         Contents: Read and write)
    GITHUB_REPO          "your_username/your_repo"
Optional:
    AIPIPE_MODEL         defaults to "gpt-5-mini" — check aipipe.org/playground
                          for the current list of available model names
    GITHUB_LOG_PATH      path of the log file inside the repo (default run.jsonl)
    GITHUB_BRANCH        defaults to the repo's default branch

Log pushes go through the GitHub Contents API (not the git CLI), so this
works on any host without a configured git client or SSH key — only a
plain HTTPS token is needed.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]
LOG_URL = os.environ["LOG_URL"]
AIPIPE_MODEL = os.environ.get("AIPIPE_MODEL", "gpt-5-mini")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_LOG_PATH = os.environ.get("GITHUB_LOG_PATH", "run.jsonl")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH")

client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=AIPIPE_TOKEN)

LOG_FILE = Path("run.jsonl")
HISTORY_TURNS = 6          # how many past turns to keep for multi-turn context
PUSH_LOG_EVERY = 1         # push to GitHub every N exchanges (log lines are tiny)

conversation_history: dict[int, list[dict]] = {}
_exchange_count = 0

SYSTEM_PROMPT = (
    "You are a careful data analyst answering exam questions sent over Telegram. "
    "The user's LAST message states a data-analysis question and specifies the exact "
    "JSON shape your reply must take — normally a top-level object with an \"answer\" "
    "key holding the value in the requested shape, plus a \"log_url\" key. Work out "
    "the real answer using public data you know (e.g. MOSPI statistics), general "
    "knowledge, or arithmetic on any numbers given in the message. Earlier messages "
    "in this conversation are context only — always answer the LAST message. "
    "Reply with ONLY the JSON object the message asks for and nothing else: no "
    "explanation, no markdown, no code fences — just the raw JSON on one line. "
    "Include a \"log_url\" key with any placeholder string value; the bot will "
    "overwrite it with the real URL automatically."
)


def log_event(event: dict) -> None:
    event["timestamp"] = time.time()
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _github_api(method: str, url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def maybe_push_log() -> None:
    """Push run.jsonl to GitHub (via the Contents API) every few exchanges so
    LOG_URL stays current. Best-effort: a failed push is logged but never
    crashes the bot. No-ops quietly if GITHUB_TOKEN/GITHUB_REPO aren't set."""
    global _exchange_count
    _exchange_count += 1
    if _exchange_count % PUSH_LOG_EVERY != 0:
        return
    if not (GITHUB_TOKEN and GITHUB_REPO):
        print("[warn] GITHUB_TOKEN/GITHUB_REPO not set — log_url will go stale")
        return

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LOG_PATH}"
    content_b64 = base64.b64encode(LOG_FILE.read_bytes()).decode()

    sha = None
    try:
        current = _github_api("GET", api_url)
        sha = current.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 just means the file doesn't exist yet — fine, we'll create it
            print(f"[warn] could not check existing log on GitHub: {e}")
            return

    payload = {"message": "log update", "content": content_b64}
    if sha:
        payload["sha"] = sha
    if GITHUB_BRANCH:
        payload["branch"] = GITHUB_BRANCH

    try:
        _github_api("PUT", api_url, payload)
    except Exception as e:
        print(f"[warn] could not push log via GitHub API: {e}")


def extract_json(text: str) -> dict:
    """Best-effort: parse the model's reply as JSON even if it added stray
    text or code fences around the object."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"model reply had no JSON object: {text!r}")
    return json.loads(text[start:end + 1])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    log_event({"type": "incoming", "chat_id": chat_id, "text": user_text})

    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=AIPIPE_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history[-HISTORY_TURNS:],
        )
        raw_reply = response.choices[0].message.content.strip()
        parsed = extract_json(raw_reply)
        if not isinstance(parsed, dict):
            parsed = {"answer": parsed}
    except Exception as e:
        # Reply anyway so the exchange doesn't time out — a wrong answer
        # still beats a missed reply.
        print(f"[warn] LLM call/parse failed: {e}")
        parsed = {"answer": None}

    parsed["log_url"] = LOG_URL  # always the real URL — never trust the model's guess
    final_reply = json.dumps(parsed)

    history.append({"role": "assistant", "content": final_reply})
    log_event({"type": "outgoing", "chat_id": chat_id, "text": final_reply})
    maybe_push_log()

    await update.message.reply_text(final_reply)


def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"Bot is running with model={AIPIPE_MODEL}... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
