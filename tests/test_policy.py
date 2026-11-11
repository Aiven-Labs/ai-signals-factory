from app.policy import can, can_decide


def test_observer_cannot_propose():
    assert not can("observer", "propose")
    assert can("volunteer", "propose")


def test_organiser_decides_speaker_email_but_not_access():
    assert can_decide("organiser", "speaker_email", 2)
    assert not can_decide("organiser", "access_grant", 2)


def test_admin_cannot_self_approve_access_grant():
    assert can_decide("admin", "access_grant", decider_id=1, requester_id=2)
    assert not can_decide("admin", "access_grant", decider_id=1, requester_id=1)


def test_unknown_kind_denied():
    assert not can_decide("admin", "launch_missiles", 1)


def test_manual_steps_can_be_decided_by_volunteers_but_not_observers():
    assert can_decide("volunteer", "manual", 1)
    assert not can_decide("observer", "manual", 1)


def test_cfp_review_needs_speaker_contact_permission():
    assert can_decide("organiser", "cfp_review", 1) and not can_decide("volunteer", "cfp_review", 1)
