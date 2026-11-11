"""Plain-text preview of what a proposal would do, shown to organisers before they decide.
Pure string work, no model calls. Unknown values stay as [placeholders] rather than being invented."""
import pathlib

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates" / "emails"
LIMIT = 3600  # Telegram caps messages at 4096 characters

MANUAL = {
    "venue": "Confirm the venue with {venue_name} for {date}. Check capacity, AV, catering rules and the cleaning fee.",
    "meetup": "Schedule the event on Meetup: copy the previous event and update title, date ({date}) and venue.",
    "luma": "Schedule the event on Luma: copy the previous event and update title, date ({date}) and venue.",
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
    "linkedin_announce": ("LinkedIn post (draft)", "{title} is on {date_long} at {venue_name}.\n\n"
                          "Talks: [speakers and titles to confirm]\n\nRegister: [Luma link]\n\n#AI #London #meetup"),
    "slack_announce": ("Slack #general message (draft)", "{title} is on {date_long} at {venue_name}. "
                       "Register: [Luma link]. Talks: [to confirm]. Reply here if you want to speak."),
    "reminder_2w": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                    "Two weeks to go: {title} on {date_long} at {venue_name}. Register: [Luma link]."),
    "reminder_24h": ("Reminder post for Meetup, Luma newsletter, Slack and LinkedIn (draft)",
                     "Tomorrow: {title} at {venue_name}, doors [time]. See you there! [Luma link]"),
    "thanks": ("Thank-you post for Meetup, Luma newsletter and LinkedIn (draft)",
               "Thank you to our speakers and everyone who came to {title}. "
               "Slides and the recording will follow."),
}


def _ctx(ev: dict, host: str | None) -> dict:
    d = ev["event_date"]
    return {"title": ev["title"], "date": d.strftime("%-d %b %Y"), "date_long": d.strftime("%A %-d %B %Y"),
            "venue_name": (ev.get("venue") or "[venue]"), "host": host or "[host]"}


def render(kind: str, payload: dict, ev: dict | None, host: str | None = None) -> str:
    """Text for the Telegram message. `payload` is the proposal payload; `ev` the events row (or None)."""
    step = payload.get("step")
    if not ev:
        return payload.get("summary", "")
    c = _ctx(ev, host)
    head = f"{c['title']} - {c['date']} - {c['venue_name']}\n\n"
    if kind == "speaker_email":
        body = (TEMPLATES / "speaker_invite.txt").read_text()
        for k, v in {"{{ DATE }}": c["date_long"], "{{ TIME }}": "[time]", "{{ VENUE }}": c["venue_name"],
                     "{{ NAME }}": "[speaker name]", "{{ TALK_TITLE }}": "[talk title]",
                     "{{ TALK_FORMAT }}": "[full talk / lightning talk]", "{{ ORGANISER }}": c["host"]}.items():
            body = body.replace(k, v)
        text = head + "ACTION: send this email to each speaker marked 'pitched' for this event (none recorded yet).\n\n" + body
    elif kind == "public_post" and step in POSTS:
        label, tpl = POSTS[step]
        text = head + f"ACTION: publish this {label}:\n\n" + tpl.format(**c)
    elif step in MANUAL:
        text = head + "ACTION (done by a person, the factory does nothing automatically):\n" + MANUAL[step].format(**c)
    else:
        text = head + payload.get("summary", "")
    text += "\n\nApprove = go-ahead recorded. Reject = skip it. Nothing is sent from here yet."
    return text[:LIMIT]
