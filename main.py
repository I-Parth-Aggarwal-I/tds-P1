"""
Telegram Data Analyst Bot — webhook server.

Receives a plain-text Telegram message, runs it through the LLM agent
(agent.py), and replies with exactly one JSON object:
    {"answer": <...>, "log_url": "https://..."}
"""

import os
import logging
from fastapi import FastAPI, Request
import requests as http

from agent import run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Simple in-memory per-chat history for multi-turn questions.
# NOTE: this resets if the free-tier instance restarts/sleeps. If you need
# it to survive restarts, swap this dict for a small SQLite file or a
# key-value store — not required for the assignment's grading flow.
CHAT_HISTORY: dict[int, list[str]] = {}
MAX_HISTORY = 6  # keep last N messages per chat

app = FastAPI()


def send_message(chat_id: int, text: str) -> None:
    resp = http.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    if not resp.ok:
        log.error("Telegram sendMessage failed: %s", resp.text)


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    # Basic check: the path itself acts as a shared secret so random
    # internet traffic can't trigger your agent.
    if secret != TELEGRAM_BOT_TOKEN:
        return {"ok": False}

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message["text"]

    history = CHAT_HISTORY.setdefault(chat_id, [])
    history.append(text)
    history[:] = history[-MAX_HISTORY:]

    try:
        answer_obj, log_url = run_agent(history)
        reply = {"answer": answer_obj, "log_url": log_url}
        import json as _json
        send_message(chat_id, _json.dumps(reply, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        log.exception("Agent run failed")
        send_message(chat_id, f'{{"answer": null, "log_url": "", "error": "{str(e)[:200]}"}}')

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
