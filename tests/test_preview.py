from datetime import date

from app import preview

EV = {"title": "AI Signals #37", "event_date": date(2026, 12, 8), "venue": "Tessl", "start_time": "18:00"}


def test_speaker_email_proposal_shows_template_with_event_details():
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


def test_cfp_review_card_is_triage_only():
    pl = {"name": "Mary", "email": "m@example.com", "title": "AI in health", "message": "Hello"}
    t = preview.render("cfp_review", pl, EV)
    assert "Mary <m@example.com>" in t and "AI Signals #37" in t and "approve before anything is sent" in t
    assert preview.email_for("cfp_review", pl, EV) is None


def test_invite_and_followup_emails_are_exact_and_complete():
    pl = {"name": "Anusha", "email": "a@example.com", "title": "From Models to Markets", "format": "main"}
    inv = preview.email_for("speaker_invite", pl, EV, "Alper")
    assert inv["to"] == "a@example.com" and "8 December" in inv["subject"] and "Main talk (30-40 minutes)" in inv["body"]
    assert "within 5 days" in inv["body"] and "[" not in inv["body"] and "{{" not in inv["body"] and "at 18:00" in inv["body"]
    fol = preview.email_for("speaker_followup", pl, EV, "Alper")
    assert fol["subject"].startswith("Re:") and "haven't heard back" in fol["body"] and "{{" not in fol["body"]
    card = preview.render("speaker_invite", pl, EV, "Alper")
    assert "Send = this exact email" in card and inv["body"] in card


def test_reply_card_shows_the_reply():
    t = preview.render("speaker_reply", {"name": "A", "email": "a@example.com", "title": "T", "snippet": "Yes, happy to!",
                                         "guess": "speaker_confirm"}, EV)
    assert "Yes, happy to!" in t and "sounds like a yes" in t
