"""Event checklist, taken from the AI Signals board. Pure logic: given the event
date and today's date, which steps are due? No tokens, no I/O."""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    days_before: int          # negative = after the event
    kind: str                 # reminder | public_post | speaker_email | manual


STEPS = [
    Step("venue", "Confirm venue", 30, "manual"),
    Step("speakers", "Confirm speakers", 30, "speaker_email"),
    Step("meetup", "Schedule event on Meetup", 30, "manual"),
    Step("luma", "Schedule event on Luma", 30, "manual"),
    Step("website", "Add event to website (Squarespace) with Luma button", 30, "manual"),
    Step("linkedin_announce", "Post event on LinkedIn", 30, "public_post"),
    Step("slack_announce", "Announce in Slack #general", 30, "public_post"),
    Step("reminder_2w", "Reminder: Meetup, Luma, Slack, LinkedIn", 14, "public_post"),
    Step("host_av", "Confirm host, recorder and AV kit", 7, "manual"),
    Step("slides", "Create slide deck from template", 2, "manual"),
    Step("catering", "Organise catering", 2, "manual"),
    Step("reminder_24h", "Reminder: Meetup, Luma, Slack, LinkedIn", 1, "public_post"),
    Step("close_registration", "Close registration and share guest list", 1, "manual"),
    Step("thanks", "Thank speakers and attendees", -1, "public_post"),
    Step("recording", "Upload edited recording to YouTube and website", -7, "manual"),
]


def due_date(event_date: date, step: Step) -> date:
    return event_date - timedelta(days=step.days_before)


# The event must not be advertised or listed anywhere until at least this many speakers have confirmed.
GATED_STEPS = {"meetup", "luma", "linkedin_announce"}
MIN_CONFIRMED_SPEAKERS = 1


def due_steps(event_date: date, today: date, done: set[str] | None = None,
              confirmed_speakers: int | None = None) -> list[Step]:
    """Steps whose due date has arrived and that are not done, oldest first.
    When confirmed_speakers is given, gated steps wait until enough speakers have confirmed."""
    done = done or set()
    blocked = GATED_STEPS if (confirmed_speakers is not None and confirmed_speakers < MIN_CONFIRMED_SPEAKERS) else set()
    out = [s for s in STEPS if s.key not in done and s.key not in blocked and due_date(event_date, s) <= today]
    return sorted(out, key=lambda s: due_date(event_date, s))
