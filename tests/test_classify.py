import os

from app.classify import classify, classify_rules


def test_rules_catch_common_cases():
    assert classify_rules("Yes, I can do the 8th") == "speaker_confirm"
    assert classify_rules("Sorry, I can't make it") == "speaker_decline"
    assert classify_rules("We would like to sponsor your event") == "sponsor_enquiry"
    assert classify_rules("I'd love to give a talk on LangGraph") == "speaker_pitch"


def test_unknown_goes_to_human_without_model(monkeypatch):
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    assert classify("what time does the lift stop running?") == ("unknown", "human")


def test_rule_hit_never_calls_model(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "http://127.0.0.1:1")   # would fail if called
    assert classify("Happy to speak") == ("speaker_confirm", "rule")
