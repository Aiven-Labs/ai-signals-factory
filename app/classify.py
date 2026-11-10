"""Tier 0: rules. Tier 1: optional small model (OpenAI-compatible, e.g. Ollama on
Nevia) under a daily budget. Anything unsure becomes an 'unknown' for a human."""
import json
import os
import re

import httpx

RULES = [
    ("speaker_confirm", re.compile(r"\b(yes|confirm(ed)?|i('| a)m available|happy to|can do)\b", re.I)),
    ("speaker_decline", re.compile(r"\b(can'?t|cannot|unable|decline|not available|no longer)\b", re.I)),
    ("sponsor_enquiry", re.compile(r"\b(sponsor(ship)?|partner(ship)?|advertis)", re.I)),
    ("speaker_pitch", re.compile(r"\b(talk|speak(er|ing)?|present(ation)?|cfp|proposal)\b", re.I)),
]
INTENTS = ["speaker_confirm", "speaker_decline", "sponsor_enquiry", "speaker_pitch", "general"]


def classify_rules(text: str) -> str | None:
    for intent, rx in RULES:
        if rx.search(text):
            return intent
    return None


def classify_model(text: str) -> str | None:
    """Ask the small model. Returns None if disabled, over budget, or unsure."""
    base = os.environ.get("MODEL_BASE_URL")
    if not base:
        return None
    prompt = (f"Classify this message as one of {', '.join(INTENTS)}. "
              f"Reply with only the label.\n\n{text[:1500]}")
    try:
        r = httpx.post(base.rstrip("/") + "/v1/chat/completions", timeout=30,
                       headers={"Authorization": "Bearer " + os.environ.get("MODEL_API_KEY", "")},
                       json={"model": os.environ.get("MODEL_NAME", "qwen2.5:1.5b"),
                             "messages": [{"role": "user", "content": prompt}],
                             "max_tokens": 8, "temperature": 0})
        label = r.json()["choices"][0]["message"]["content"].strip().lower()
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None
    return label if label in INTENTS else None


def classify(text: str, allow_model: bool = True) -> tuple[str, str]:
    """Return (intent, handled_by). handled_by is rule | model | human."""
    hit = classify_rules(text)
    if hit:
        return hit, "rule"
    if allow_model:
        guess = classify_model(text)
        if guess and guess != "general":
            return guess, "model"
    return "unknown", "human"
