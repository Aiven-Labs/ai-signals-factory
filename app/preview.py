"""Plain-text preview of what a proposal would do, shown to organisers before they decide.
Pure string work, no model calls. Every proposal belongs to an event, and event details come from the
events table (time, venue, address, Luma link). Where a detail genuinely isn't known yet the text says so
in words instead of leaving a [placeholder]."""
import pathlib

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates" / "emails"
LIMIT = 3600  # Telegram caps messages at 4096 characters

FORMATS = {
    "main": "Main talk (30-40 minutes)",
    "lightning": "Lightning talk (up to 15 minutes)",
    None: "Main talk (30-40 minutes) or lightning talk (up to 15 minutes), whichever suits you",
}

MANUAL = {
    "venue": "Confirm the venue with {venue_name} for {date}. Check capacity, AV, catering rules and the cleaning fee.",
    "meetup": "Schedule the event on Meetup: copy the previous event and update title, date ({date}) and venue ({venue_name}).",
    "luma": "Schedule the event on Luma: copy the previous event and update title, date ({date}) and venue ({venue_name}).",
    "website": "Add the event to the Squarespace site: copy the previous event and update it, then add the Luma event "
               "button as an embed button (Luma 'more' settings).",
    "host_av": "Confirm who is hosting on the night and who is recording. Pick up AV kit if needed.",
    "slides": "Create the slide deck from the template: "
              "https://docs.google.com/presentation/d/1tjsFMNhRRQpwLCq7iK2hKbAi1NI4Xx5SLh2rpPY5djQ/edit",
    "catering": "Organise catering for {date} (Daemon-sponsored events: ask Motse Lehata on Slack; others: hugh.evans.dev@gmail.com).",
    "close_registration": "Close registration and share the guest list with the venue.",
    "recording": "Upload the edited recording to YouTube and add it to the event page on the website.",
}

POSTS = {
    "linkedin_announce": ("LinkedIn post (draft)", "{title} is on {date_long} at {venue_full}.\n{schedule}\n\n"
                          "Speakers to be announced.\n\nRegister: {luma}\n\n#AI #London #meetup"),
    "slack_announce": ("Slack #general message (draft)", "{title} is on {date_long} at {venue_full}. {schedule} "
                       "Register: {luma}. Reply here if you want to speak."),
    "reminder_2w": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                    "Two weeks to go: {title} on {date_long} at {venue_full}. {schedule} Register: {luma}."),
    "reminder_24h": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                     "Tomorrow: {title} at {venue_full}. {schedule} See you there! {luma}"),
    "thanks": ("Thank-you post for Meetup, Luma newsletter and LinkedIn (draft)",
               "Thank you to our speakers and everyone who came to {title}. "
               "Slides and the recording will follow."),
}


WEBSITE_URL = "https://aisignals.org.uk"
PRIVACY_URL = "https://aisignals.org.uk/privacy"
BOOKING_URL = "https://calendar.google.com/calendar/appointments/schedules/AcZssZ2hNYtGgGwkaZWBdXlgso2afLmIporkPcjWceXpcP2g9IWeKZ4znbFojaCNx_ObgPG8KsOXkCyF"


def _t(hhmm: str) -> str:
    """'18:30' -> '6:30pm', '18:00' -> '6pm'."""
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return f"{h % 12 or 12}{':%02d' % m if m else ''}{'pm' if h >= 12 else 'am'}"


def _schedule(ev: dict) -> str:
    parts = []
    if ev.get("start_time"):
        parts.append(f"doors open at {_t(ev['start_time'])}")
    if ev.get("talks_start"):
        parts.append(f"talks start at {_t(ev['talks_start'])}")
    if ev.get("end_time"):
        parts.append(f"we finish by {_t(ev['end_time'])}")
    if not parts:
        return ""
    return (", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]).capitalize() + "."


def _ctx(ev: dict, host: str | None) -> dict:
    d = ev["event_date"]
    venue = ev.get("venue") or "the venue (to be confirmed)"
    addr = (ev.get("venue_address") or "").strip()
    return {"title": ev["title"], "date": d.strftime("%-d %b %Y"), "date_long": d.strftime("%A %-d %B %Y"),
            "venue_name": venue, "venue_full": f"{venue}, {addr}" if addr else venue,
            "at_time": "", "schedule": _schedule(ev),
            "arrival": _t(ev["speaker_arrival"]) if ev.get("speaker_arrival") else "the start of the doors-open time",
            "luma": ev.get("luma_url") or "(Luma link to follow)", "host": host or "the AI Signals team"}


def _invite(name, title, ev, host, fmt=None, template="speaker_invite"):
    """Speaker email from a template: returns (subject, body)."""
    c = _ctx(ev, host)
    raw = (TEMPLATES / f"{template}.txt").read_text().replace("{{ TIME }}", c["at_time"])
    for k, v in {"{{ DATE }}": c["date_long"], "{{ VENUE }}": c["venue_full"], "{{ SCHEDULE }}": c["schedule"], "{{ ARRIVAL }}": c["arrival"],
                 "{{ WEBSITE_URL }}": WEBSITE_URL, "{{ PRIVACY_URL }}": PRIVACY_URL, "{{ BOOKING_URL }}": BOOKING_URL,
                 "{{ NAME }}": name or "[speaker name]", "{{ TALK_TITLE }}": title or "[talk title]",
                 "{{ TALK_FORMAT }}": FORMATS.get(fmt, FORMATS[None]), "{{ ORGANISER }}": c["host"]}.items():
        raw = raw.replace(k, v)
    first, _, rest = raw.partition("\n")
    return first.removeprefix("Subject:").strip(), rest.strip()


EMAIL_TEMPLATES = {"speaker_invite": "speaker_invite", "speaker_followup": "speaker_followup",
                   "speaker_thanks": "speaker_thanks", "speaker_reconfirm": "speaker_reconfirm"}
EMAIL_LABELS = {"speaker_invite": "Invitation", "speaker_followup": "Follow-up", "speaker_thanks": "Thank-you",
                "speaker_reconfirm": "Reconfirmation"}


def email_for(kind: str, payload: dict, ev: dict | None, host: str | None = None) -> dict | None:
    """The exact email that goes out if this proposal is approved, or None for kinds that send nothing."""
    if kind in EMAIL_TEMPLATES and ev and payload.get("email"):
        subject, body = _invite(payload.get("name"), payload.get("title"), ev, host, payload.get("format"),
                                EMAIL_TEMPLATES[kind])
        return {"to": payload["email"], "subject": subject, "body": body}
    return None


def render(kind: str, payload: dict, ev: dict | None, host: str | None = None, final: bool = False) -> str:
    """Text for the Telegram message. `payload` is the proposal payload; `ev` the events row (or None).
    final=True returns only the artifact itself (email body, post text, instruction), no header or footer."""
    step = payload.get("step")
    if not ev:
        return payload.get("summary", "")
    c = _ctx(ev, host)
    head = "" if final else f"EVENT: {c['title']} - {c['date']} - {c['venue_name']}\n\n"
    if kind in EMAIL_TEMPLATES:
        e = email_for(kind, payload, ev, host)
        who = f"{payload.get('name') or 'Unknown'} <{payload.get('email')}>"
        if final:
            return f"Email to {who}:\nSubject: {e['subject']}\n\n{e['body']}"[:LIMIT]
        label = EMAIL_LABELS[kind]
        return (f"{head}{label} email, ready to send. Check it carefully.\n\nTo: {who}\nSubject: {e['subject']}\n\n"
                f"{e['body']}\n\nSend = this exact email goes out now from the AI Signals Gmail. Skip = nothing is sent.")[:LIMIT]
    if kind == "speaker_reply":
        who = f"{payload.get('name') or 'Unknown'} <{payload.get('email')}>"
        guess = {"speaker_confirm": "sounds like a yes", "speaker_decline": "sounds like a no"}.get(payload.get("guess"), "unclear")
        if final:
            return f"Recorded reply from {who}."
        return (f"{head}Reply from {who} about \"{payload.get('title')}\" ({guess}):\n\n{(payload.get('snippet') or '')[:900]}"
                f"\n\nConfirmed = they're speaking (frees nothing, unlocks announcements). Declined = frees the slot and "
                f"starts the next speaker. I'll handle = I'll reply myself.")[:LIMIT]
    if kind == "cfp_review":
        who = f"{payload.get('name') or 'Unknown'} <{payload.get('email')}>"
        if final:
            return (f"Talk proposal from {who}: slot held. An invitation email will follow for your Send approval "
                    f"(nothing is emailed yet).")
        body = f"Talk: {payload.get('title') or '[no title]'}\n\n{(payload.get('message') or '')[:900]}"
        return (f"{head}New talk proposal from {who}\n\n{body}\n\nPick the format to hold a slot. You'll then get the "
                f"invitation email to approve before anything is sent. Reject = skip.")[:LIMIT]
    if kind == "speaker_email":
        body = (TEMPLATES / "speaker_invite.txt").read_text().replace("{{ TIME }}", c["at_time"])
        for k, v in {"{{ DATE }}": c["date_long"], "{{ VENUE }}": c["venue_full"], "{{ SCHEDULE }}": c["schedule"], "{{ NAME }}": "[speaker name]",
                     "{{ TALK_TITLE }}": "[talk title]", "{{ TALK_FORMAT }}": FORMATS[None],
                     "{{ ORGANISER }}": c["host"]}.items():
            body = body.replace(k, v)
        text = body if final else head + "ACTION: send this email to each speaker marked 'pitched' for this event (none recorded yet).\n\n" + body
    elif kind == "public_post" and step in POSTS:
        label, tpl = POSTS[step]
        text = tpl.format(**c) if final else head + f"ACTION: publish this {label}:\n\n" + tpl.format(**c)
    elif step in MANUAL:
        text = MANUAL[step].format(**c) if final else head + "ACTION (done by a person, the factory does nothing automatically):\n" + MANUAL[step].format(**c)
    else:
        text = head + payload.get("summary", "")
    if final:
        return text[:LIMIT]
    text += "\n\nApprove = go-ahead recorded. Reject = skip it. Nothing is sent from here yet."
    return text[:LIMIT]
