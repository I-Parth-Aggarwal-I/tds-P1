"""
Run this ONCE after your Render service is live, to point Telegram at it.

Usage:
    TELEGRAM_BOT_TOKEN=... python set_webhook.py https://your-app.onrender.com
"""
import os
import sys
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
base_url = sys.argv[1].rstrip("/")
webhook_url = f"{base_url}/webhook/{token}"

resp = requests.post(
    f"https://api.telegram.org/bot{token}/setWebhook",
    json={"url": webhook_url},
)
print(resp.status_code, resp.json())
