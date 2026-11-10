"""Send a message to organisers on Telegram and/or Slack. Falls back to stdout."""
import os

import httpx


def send(text: str) -> list[str]:
    sent = []
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   json={"chat_id": chat, "text": text}, timeout=15)
        sent.append("telegram")
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if hook:
        httpx.post(hook, json={"text": text}, timeout=15)
        sent.append("slack")
    if not sent:
        print("[notify]", text)
    return sent
