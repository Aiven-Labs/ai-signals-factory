from datetime import date

from app.schedule import STEPS, due_date, due_steps

EVENT = date(2026, 12, 8)


def test_nothing_due_far_ahead():
    assert due_steps(EVENT, date(2026, 9, 1)) == []


def test_month_before_releases_announcement_steps():
    keys = {s.key for s in due_steps(EVENT, date(2026, 11, 8))}
    assert {"venue", "luma", "slack_announce"} <= keys
    assert "reminder_2w" not in keys


def test_done_steps_are_skipped():
    keys = {s.key for s in due_steps(EVENT, date(2026, 11, 8), done={"venue"})}
    assert "venue" not in keys


def test_post_event_steps_become_due_after():
    assert "thanks" not in {s.key for s in due_steps(EVENT, EVENT)}
    assert "thanks" in {s.key for s in due_steps(EVENT, date(2026, 12, 9))}
    assert "recording" in {s.key for s in due_steps(EVENT, date(2026, 12, 15))}


def test_every_step_has_unique_key():
    assert len({s.key for s in STEPS}) == len(STEPS)
    assert due_date(EVENT, STEPS[0]) == date(2026, 11, 8)


def test_parse_submitted_formats():
    from app.main import parse_submitted
    assert parse_submitted("10/16/2025 14:00:07").year == 2025
    assert parse_submitted(46000.45237).year == 2025
    assert parse_submitted("garbage") is None


def test_event_bound_kinds_require_an_event():
    import pytest
    from fastapi import HTTPException
    from app.main import EVENT_KINDS, propose
    assert {"manual", "speaker_email", "public_post", "cfp_review"} <= EVENT_KINDS
    with pytest.raises(HTTPException):
        propose(None, "k", "manual", {})
