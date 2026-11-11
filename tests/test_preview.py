from datetime import date

from app import preview

EV = {"title": "AI Signals #37", "event_date": date(2026, 12, 8), "venue": "Tessl", "start_time": "18:00",
      "talks_start": "18:30", "end_time": "21:00", "speaker_arrival": "18:15",
      "venue_address": "Fora - York House, 210 Pentonville Rd, London N1 9JY"}


def test_speaker_email_proposal_shows_template_with_event_details():
    t = preview.render("speaker_email", {"step": "speakers"}, EV, "Alper")
    assert "Subject: Speaking at AI Signals on Tuesday 8 December 2026" in t
    assert "organiser bot" in t and "Alper" not in t and "{{" not in t and "Nothing is sent" in t and "Doors open at 6pm" in t


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
    assert inv["body"].rstrip().endswith("(on behalf of the AI Signals organisers)") and "Alper" not in inv["body"]
    assert "5 days" not in inv["body"] and "another speaker" not in inv["body"] and "[" not in inv["body"] and "{{" not in inv["body"]
    assert "Venue: Tessl, Fora - York House, 210 Pentonville Rd, London N1 9JY" in inv["body"]
    assert "Schedule: Doors open at 6pm, talks start at 6:30pm and we finish by 9pm." in inv["body"]
    fol = preview.email_for("speaker_followup", pl, EV, "Alper")
    assert fol["subject"].startswith("Re:") and "haven't heard back" in fol["body"] and "{{" not in fol["body"]
    card = preview.render("speaker_invite", pl, EV, "Alper")
    assert "Send = this exact email" in card and inv["body"] in card


def test_reply_card_shows_the_reply():
    t = preview.render("speaker_reply", {"name": "A", "email": "a@example.com", "title": "T", "snippet": "Yes, happy to!",
                                         "guess": "speaker_confirm"}, EV)
    assert "Yes, happy to!" in t and "sounds like a yes" in t


def test_schedule_sentence_handles_missing_parts():
    from app.preview import _schedule, _t
    assert _t("18:00") == "6pm" and _t("18:30") == "6:30pm" and _t("09:05") == "9:05am" and _t("00:00") == "12am"
    assert _schedule({"start_time": "18:00"}) == "Doors open at 6pm."
    assert _schedule({}) == ""


def test_thanks_and_reconfirm_emails():
    pl = {"name": "Anusha", "email": "a@example.com", "title": "From Models to Markets", "format": "main"}
    for kind in ("speaker_thanks", "speaker_reconfirm"):
        b = preview.email_for(kind, pl, EV)["body"]
        assert "{{" not in b and "[" not in b, kind
        assert "HDMI and USB-C" in b and "arrive by 6:15pm" in b, kind
        assert "https://aisignals.org.uk" in b and "calendar.google.com/calendar/appointments" in b, kind
    t = preview.email_for("speaker_thanks", pl, EV)["body"]
    assert "https://aisignals.org.uk/privacy" in t and "two days before" in t
    assert "Send = this exact email" in preview.render("speaker_reconfirm", pl, EV)


def test_invite_keeps_reply_cta_but_has_no_timescale():
    pl = {"name": "A", "email": "a@example.com", "title": "T", "format": "main"}
    for kind in ("speaker_invite", "speaker_followup"):
        b = preview.email_for(kind, pl, EV)["body"]
        assert "Please reply to this email to let us know if you can make it." in b, kind
        assert "days" not in b and "another speaker" not in b, kind
