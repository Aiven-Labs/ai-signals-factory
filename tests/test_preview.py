from datetime import date

from app import preview

EV = {"title": "AI Signals #37", "event_date": date(2026, 12, 8), "venue": "Tessl"}


def test_speaker_email_shows_real_draft_and_no_unfilled_template_vars():
    t = preview.render("speaker_email", {"step": "speakers"}, EV, "Alper")
    assert "Subject: Speaking at AI Signals on Tuesday 8 December 2026" in t
    assert "Alper" in t and "{{" not in t and "Nothing is sent" in t


def test_post_and_manual_previews():
    assert "publish this LinkedIn post" in preview.render("public_post", {"step": "linkedin_announce"}, EV)
    assert "done by a person" in preview.render("manual", {"step": "venue"}, EV)


def test_falls_back_to_summary_without_event():
    assert preview.render("manual", {"summary": "x"}, None) == "x"
