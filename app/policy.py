"""Roles and permissions. Pure functions, no I/O, so they are easy to test."""

ROLES = ("admin", "organiser", "volunteer", "observer")

# action -> roles allowed to perform it
PERMISSIONS = {
    "view": {"admin", "organiser", "volunteer", "observer"},
    "propose": {"admin", "organiser", "volunteer"},
    "approve_speaker_contact": {"admin", "organiser"},
    "approve_public_post": {"admin", "organiser"},
    "approve_reply": {"admin", "organiser"},
    "approve_manual_step": {"admin", "organiser", "volunteer"},
    "approve_access_grant": {"admin"},
    "manage_organisers": {"admin"},
}

# proposal kind -> permission needed to decide it
KIND_PERMISSION = {
    "speaker_email": "approve_speaker_contact",
    "public_post": "approve_public_post",
    "reply": "approve_reply",
    "escalation": "approve_reply",
    "access_grant": "approve_access_grant",
    "reminder": "approve_public_post",
    "manual": "approve_manual_step",
    "cfp_review": "approve_speaker_contact",
}


def can(role: str, action: str) -> bool:
    return role in PERMISSIONS.get(action, set())


def can_decide(role: str, kind: str, decider_id, requester_id=None) -> bool:
    """Decide a proposal. Access grants can never be self-approved."""
    needed = KIND_PERMISSION.get(kind)
    if needed is None or not can(role, needed):
        return False
    if kind == "access_grant" and requester_id is not None and decider_id == requester_id:
        return False
    return True
