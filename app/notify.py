"""Tell organisers things. Telegram buttons for approvals; Slack webhook and stdout as fallbacks."""
import os

import httpx

API = "https://api.telegram.org/bot{}/{}"


def _tg(method: str, **body):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        return None
    try:
        return httpx.post(API.format(tok, method), json=body, timeout=15).json()
    except Exception as e:  # never let a chat failure break the core flow
        print("[telegram error]", type(e).__name__)
        return None


def proposal(chat_ids: list[str], pid: int, kind: str, summary: str) -> list[str]:
    """Send one proposal with Approve / Reject buttons to each organiser chat."""
    sent = []
    for chat in chat_ids:
        r = _tg("sendMessage", chat_id=chat, text=f"Approval needed #{pid} [{kind}]\n{summary}",
                reply_markup={"inline_keyboard": [[
                    {"text": "Approve", "callback_data": f"a:{pid}"},
                    {"text": "Reject", "callback_data": f"r:{pid}"}]]})
        if r and r.get("ok"):
            sent.append(chat)
    if not chat_ids:
        print(f"[notify] approval needed #{pid} [{kind}]: {summary}")
    return sent


def answer(callback_id: str, text: str):
    _tg("answerCallbackQuery", callback_query_id=callback_id, text=text)


def edit(chat_id, message_id, text: str):
    _tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text)


def send(text: str) -> list[str]:
    sent = []
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if chat and _tg("sendMessage", chat_id=chat, text=text):
        sent.append("telegram")
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if hook:
        httpx.post(hook, json={"text": text}, timeout=15)
        sent.append("slack")
    if not sent:
        print("[notify]", text)
    return sent
