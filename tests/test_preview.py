from datetime import date

from app import preview

EV = {"title": "AI Signals #37", "event_date": date(2026, 12, 8), "venue": "Tessl", "start_time": "18:00"}


def test_speaker_email_shows_real_draft_and_no_unfilled_template_vars():
    t = preview.render("speaker_email", {"step": "speakers"}, EV, "Alper")
    assert "Subject: Speaking at AI Signals on Tuesday 8 December 2026" in t
    assert "Alper" in t and "{{" not in t and "Nothing is sent" in t and "[time]" not in t and "at 18:00" in t


def test_post_and_manual_previews():
    assert "publish this LinkedIn post" in preview.render("public_post", {"step": "linkedin_announce"}, EV)
    assert "done by a person" in preview.render("manual", {"step": "venue"}, EV)


def test_falls_back_to_summary_without_event():
    assert preview.render("manual", {"summary": "x"}, None) == "x"


def test_posts_have_no_bracket_placeholders():
    for step in preview.POSTS:
        t = preview.render("public_post", {"step": step}, EV, final=True)
        assert "[" not in t and "{" not in t, step


def test_final_text_has_no_header_or_footer():
    t = preview.render("public_post", {"step": "slack_announce"}, EV, final=True)
    assert t.startswith("AI Signals #37 is on") and "Approve =" not in t and "ACTION" not in t
    assert "Subject:" in preview.render("speaker_email", {"step": "speakers"}, EV, "A", final=True)


def test_cfp_review_preview_and_draft():
    pl = {"name": "Mary", "email": "m@example.com", "title": "AI in health", "message": "Hello"}
    t = preview.render("cfp_review", pl, EV)
    assert "Mary <m@example.com>" in t and "AI Signals #37" in t and "DRAFT" in t
    d = preview.draft("cfp_review", pl, EV, "Alper")
    assert d["to"] == "m@example.com" and "8 December" in d["subject"] and "AI in health" in d["body"]
    assert "[" not in d["body"] and "Lightning" not in d["body"] and "whichever suits you" in d["body"]
    pl["format"] = "lightning"
    assert "Lightning talk (up to 15 minutes)" in preview.draft("cfp_review", pl, EV, "A")["body"]
    assert preview.draft("manual", {}, EV) is None
