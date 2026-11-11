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
    "linkedin_announce": ("LinkedIn post (draft)", "{title} is on {date_long}{at_time} at {venue_full}.\n\n"
                          "Speakers to be announced.\n\nRegister: {luma}\n\n#AI #London #meetup"),
    "slack_announce": ("Slack #general message (draft)", "{title} is on {date_long}{at_time} at {venue_full}. "
                       "Register: {luma}. Reply here if you want to speak."),
    "reminder_2w": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                    "Two weeks to go: {title} on {date_long}{at_time} at {venue_full}. Register: {luma}."),
    "reminder_24h": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                     "Tomorrow: {title} at {venue_full}{at_time}. See you there! {luma}"),
    "thanks": ("Thank-you post for Meetup, Luma newsletter and LinkedIn (draft)",
               "Thank you to our speakers and everyone who came to {title}. "
               "Slides and the recording will follow."),
}


def _ctx(ev: dict, host: str | None) -> dict:
    d = ev["event_date"]
    venue = ev.get("venue") or "the venue (to be confirmed)"
    addr = (ev.get("venue_address") or "").strip()
    return {"title": ev["title"], "date": d.strftime("%-d %b %Y"), "date_long": d.strftime("%A %-d %B %Y"),
            "venue_name": venue, "venue_full": f"{venue}, {addr}" if addr else venue,
            "at_time": f" at {ev['start_time']}" if ev.get("start_time") else "",
            "luma": ev.get("luma_url") or "(Luma link to follow)", "host": host or "the AI Signals team"}


def _invite(name, title, ev, host, fmt=None):
    """Speaker invite from the template: returns (subject, body)."""
    c = _ctx(ev, host)
    raw = (TEMPLATES / "speaker_invite.txt").read_text().replace(" {{ TIME }}", c["at_time"])
    for k, v in {"{{ DATE }}": c["date_long"], "{{ VENUE }}": c["venue_full"],
                 "{{ NAME }}": name or "[speaker name]", "{{ TALK_TITLE }}": title or "[talk title]",
                 "{{ TALK_FORMAT }}": FORMATS.get(fmt, FORMATS[None]), "{{ ORGANISER }}": c["host"]}.items():
        raw = raw.replace(k, v)
    first, _, rest = raw.partition("\n")
    return first.removeprefix("Subject:").strip(), rest.strip()


def draft(kind: str, payload: dict, ev: dict | None, host: str | None = None) -> dict | None:
    """An email to create as a Gmail DRAFT (never sent) once the proposal is approved, or None."""
    if kind == "cfp_review" and ev and payload.get("email"):
        subject, body = _invite(payload.get("name"), payload.get("title"), ev, host, payload.get("format"))
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
    if kind == "cfp_review":
        who = f"{payload.get('name') or 'Unknown'} <{payload.get('email')}>"
        if final:
            d = draft(kind, payload, ev, host)
            return (f"Gmail draft for {who}:\nSubject: {d['subject']}\n\n{d['body']}" if d else
                    f"Proposal from {who}: no draft was made.")[:LIMIT]
        body = f"Talk: {payload.get('title') or '[no title]'}\n\n{(payload.get('message') or '')[:900]}"
        return (f"{head}New talk proposal from {who}\n\n{body}\n\nPick the format to approve: the Gmail DRAFT "
                f"invitation (not sent, you send it) is for {c['title']}. Reject = skip, no email.")[:LIMIT]
    if kind == "speaker_email":
        body = (TEMPLATES / "speaker_invite.txt").read_text().replace(" {{ TIME }}", c["at_time"])
        for k, v in {"{{ DATE }}": c["date_long"], "{{ VENUE }}": c["venue_full"], "{{ NAME }}": "[speaker name]",
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
