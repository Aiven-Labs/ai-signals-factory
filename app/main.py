"""Core app: proposals, approvals, inbound triage, daily tick, access grants.
Zero model calls on the default path. n8n calls these endpoints on a schedule."""
import base64
import hashlib
import json
import os
from datetime import date, datetime, timedelta

import psycopg
import psycopg.conninfo
from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from . import classify as clf
from . import notify, policy, preview, slots
from .schedule import STEPS, due_steps

app = FastAPI(title="Meetup factory core")


def _conninfo():
    """Validate the server cert against the Aiven project CA when provided."""
    url = os.environ["DATABASE_URL"]
    ca = os.environ.get("PROJECT_CA_CERT")
    if not ca:
        return url
    path = "/tmp/aiven-ca.pem"
    with open(path, "wb") as f:
        f.write(base64.b64decode(ca))
    return psycopg.conninfo.make_conninfo(url, sslmode="verify-ca", sslrootcert=path)


def db():
    with psycopg.connect(_conninfo(), row_factory=dict_row) as conn:
        yield conn


def auth(x_factory_token: str = Header(default="")):
    if not os.environ.get("FACTORY_TOKEN") or x_factory_token != os.environ["FACTORY_TOKEN"]:
        raise HTTPException(401, "bad token")


def audit(conn, actor, action, detail):
    conn.execute("INSERT INTO audit_log(actor, action, detail) VALUES (%s,%s,%s)",
                 (actor, action, json.dumps(detail)))


EVENT_KINDS = {"manual", "speaker_email", "public_post", "reminder", "cfp_review",
               "speaker_invite", "speaker_followup", "speaker_reply", "speaker_thanks", "speaker_reconfirm"}


def propose(conn, idem_key, kind, payload, requested_by="system", event_id=None):
    if kind in EVENT_KINDS and not event_id:
        raise HTTPException(422, f"{kind} proposals must belong to an event (event_id)")
    row = conn.execute(
        "INSERT INTO proposed_actions(idem_key, kind, payload, requested_by, event_id) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (idem_key) DO NOTHING RETURNING id",
        (idem_key, kind, json.dumps(payload), requested_by, event_id)).fetchone()
    if row:
        audit(conn, requested_by, "propose", {"id": row["id"], "kind": kind})
    return row["id"] if row else None


@app.get("/health")
def health():
    return {"ok": True}


class ProposalIn(BaseModel):
    idem_key: str
    kind: str
    payload: dict = {}
    requested_by: str = "system"
    event_id: int | None = None


@app.post("/proposals", dependencies=[Depends(auth)])
def create_proposal(p: ProposalIn, conn=Depends(db)):
    if p.event_id and not conn.execute("SELECT 1 FROM events WHERE id=%s", (p.event_id,)).fetchone():
        raise HTTPException(404, "unknown event")
    return {"id": propose(conn, p.idem_key, p.kind, p.payload, p.requested_by, p.event_id)}


@app.get("/proposals", dependencies=[Depends(auth)])
def list_proposals(status: str = "pending", conn=Depends(db)):
    return conn.execute("SELECT * FROM proposed_actions WHERE status=%s ORDER BY id", (status,)).fetchall()


class DecisionIn(BaseModel):
    decision: str            # approved | rejected
    decided_by: int          # organisers.id


SENT_COLUMN = {"speaker_invite": "invited_at", "speaker_followup": "followup_sent_at",
               "speaker_thanks": "thanks_sent_at", "speaker_reconfirm": "reconfirm_sent_at"}


def propose_invite(conn, event_id, speaker_id, fmt, title, kind="speaker_invite", once=False):
    """Ask the organisers to approve one specific email to one speaker. Nothing is sent until they do."""
    if once and conn.execute("SELECT 1 FROM proposed_actions WHERE kind=%s AND event_id=%s AND (payload->>'speaker_id')::int=%s "
                             "AND status IN ('pending','approved','done')", (kind, event_id, speaker_id)).fetchone():
        return None
    sp = conn.execute("SELECT name, email FROM speakers WHERE id=%s", (speaker_id,)).fetchone()
    n = conn.execute("SELECT count(*) AS n FROM proposed_actions WHERE kind=%s AND event_id=%s "
                     "AND (payload->>'speaker_id')::int=%s", (kind, event_id, speaker_id)).fetchone()["n"]
    label = preview.EMAIL_LABELS[kind] + " email"
    return propose(conn, f"{kind}:{event_id}:{speaker_id}:{n + 1}", kind,
                   {"summary": f"{label} to {sp['name']}", "speaker_id": speaker_id, "email": sp["email"],
                    "name": sp["name"], "title": title, "format": fmt, "event_id": event_id}, event_id=event_id)


def fill_slot(conn, event_id, fmt):
    """A slot freed up: invite the next eligible speaker from the waitlist (still needs approval to email)."""
    if not slots.can_invite(slot_counts(conn, event_id), fmt):
        return None
    nxt = conn.execute("SELECT speaker_id, talk_title FROM event_speakers WHERE event_id=%s AND state='pitched' "
                       "ORDER BY priority NULLS LAST, updated_at LIMIT 1", (event_id,)).fetchone()
    if not nxt:
        ev = conn.execute("SELECT title FROM events WHERE id=%s", (event_id,)).fetchone()
        propose(conn, f"noslot:{event_id}:{fmt}:{date.today().isoformat()}", "escalation",
                {"summary": f"No waitlisted speaker left for the free {fmt} slot at {ev['title']}. Check the CFP."},
                event_id=event_id)
        return None
    conn.execute("UPDATE event_speakers SET state='invited', format=%s, invited_at=NULL, followup_sent_at=NULL, "
                 "last_reply_at=NULL, reason=NULL, updated_at=now() WHERE event_id=%s AND speaker_id=%s",
                 (fmt, event_id, nxt["speaker_id"]))
    return propose_invite(conn, event_id, nxt["speaker_id"], fmt, nxt["talk_title"])


def slot_counts(conn, event_id) -> dict:
    rows = conn.execute("SELECT format, count(*) AS n FROM event_speakers WHERE event_id=%s AND state = ANY(%s) "
                        "AND format IS NOT NULL GROUP BY format", (event_id, list(slots.HOLDING))).fetchall()
    return {r["format"]: r["n"] for r in rows}


def apply_decision(conn, pid: int, decision: str, organiser_id: int, variant: str | None = None):
    org = conn.execute("SELECT * FROM organisers WHERE id=%s AND active", (organiser_id,)).fetchone()
    prop = conn.execute("SELECT * FROM proposed_actions WHERE id=%s FOR UPDATE", (pid,)).fetchone()
    if not org or not prop:
        raise HTTPException(404, "unknown organiser or proposal")
    if prop["status"] != "pending":
        raise HTTPException(409, f"already {prop['status']}")
    requester = prop["payload"].get("requester_id")
    if not policy.can_decide(org["role"], prop["kind"], org["id"], requester):
        audit(conn, org["name"], "decide_denied", {"id": pid, "kind": prop["kind"]})
        conn.commit()
        raise HTTPException(403, "role not allowed to decide this")
    if decision == "approved" and prop["kind"] == "speaker_reply" and variant not in ("confirmed", "declined", "review"):
        raise HTTPException(422, "Pick Confirmed, Declined or I'll handle")
    if decision == "approved" and prop["kind"] == "cfp_review":
        if variant not in slots.FORMATS:
            raise HTTPException(422, "Pick Main talk or Lightning talk to approve a talk proposal")
        counts = slot_counts(conn, prop["event_id"])
        if not slots.can_invite(counts, variant):
            raise HTTPException(409, f"No {variant} slot left ({slots.describe(counts)}). Decline someone first.")
    conn.execute("UPDATE proposed_actions SET status=%s, decided_by=%s, decided_at=now() WHERE id=%s",
                 (decision, org["id"], pid))
    if decision == "approved" and variant in ("main", "lightning"):
        conn.execute("UPDATE proposed_actions SET payload = payload || %s::jsonb WHERE id=%s",
                     (json.dumps({"format": variant}), pid))
        if prop["kind"] == "cfp_review":
            conn.execute("INSERT INTO event_speakers(event_id, speaker_id, talk_title, state, format) "
                         "VALUES (%s,%s,%s,'invited',%s) ON CONFLICT (event_id, speaker_id) "
                         "DO UPDATE SET state='invited', format=EXCLUDED.format, talk_title=EXCLUDED.talk_title, updated_at=now()",
                         (prop["event_id"], prop["payload"].get("speaker_id"), prop["payload"].get("title"), variant))
            propose_invite(conn, prop["event_id"], prop["payload"].get("speaker_id"), variant, prop["payload"].get("title"))
    sid, eid, fmt_row = prop["payload"].get("speaker_id"), prop["event_id"], None
    if sid and prop["kind"] in ("speaker_invite", "speaker_followup", "speaker_reply") and eid:
        fmt_row = (conn.execute("SELECT format FROM event_speakers WHERE event_id=%s AND speaker_id=%s", (eid, sid))
                   .fetchone() or {}).get("format")
        if prop["kind"] == "speaker_invite" and decision == "rejected":     # skipped: free the slot, next in line
            conn.execute("UPDATE event_speakers SET state='pitched', reason='invite skipped', updated_at=now() "
                         "WHERE event_id=%s AND speaker_id=%s", (eid, sid))
            fill_slot(conn, eid, fmt_row or prop["payload"].get("format"))
        if prop["kind"] == "speaker_reply" and decision == "approved":
            if variant == "confirmed":
                conn.execute("UPDATE event_speakers SET state='confirmed', updated_at=now() WHERE event_id=%s AND speaker_id=%s", (eid, sid))
                sp_row = conn.execute("SELECT format, talk_title, thanks_sent_at FROM event_speakers WHERE event_id=%s AND speaker_id=%s", (eid, sid)).fetchone()
                if sp_row and sp_row["thanks_sent_at"] is None:
                    propose_invite(conn, eid, sid, sp_row["format"], sp_row["talk_title"], kind="speaker_thanks", once=True)
            elif variant == "declined":
                conn.execute("UPDATE event_speakers SET state='declined', reason='declined by speaker', updated_at=now() "
                             "WHERE event_id=%s AND speaker_id=%s", (eid, sid))
                fill_slot(conn, eid, fmt_row or prop["payload"].get("format"))
    audit(conn, org["name"], decision, {"id": pid, "variant": variant})
    return {"id": pid, "status": decision, "by": org["name"], "kind": prop["kind"], "variant": variant}


@app.post("/proposals/{pid}/decide", dependencies=[Depends(auth)])
def decide(pid: int, d: DecisionIn, conn=Depends(db)):
    if d.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    return apply_decision(conn, pid, d.decision, d.decided_by)


def parse_submitted(v):
    """Form timestamp: a Sheets serial number or 'MM/DD/YYYY HH:MM:SS' or ISO. None if unreadable."""
    try:
        if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit():
            return datetime(1899, 12, 30) + timedelta(days=float(v))
        for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(str(v).strip()[:19], fmt)
            except ValueError:
                pass
    except (ValueError, TypeError, OverflowError):
        pass
    return None


class CfpIn(BaseModel):
    submitted: str | float | int | None = None
    email: str
    name: str = ""
    title: str = ""
    message: str = ""
    status: str = ""


@app.post("/cfp", dependencies=[Depends(auth)])
def cfp(r: CfpIn, conn=Depends(db)):
    """A talk proposal row from the CFP sheet. Only unreviewed, recent rows become proposals."""
    if r.status.strip():
        return {"skipped": "already reviewed"}
    when = parse_submitted(r.submitted)
    max_age = int(os.environ.get("CFP_MAX_AGE_DAYS", "45"))
    if when is None:
        return {"skipped": "unreadable timestamp"}
    if datetime.now() - when > timedelta(days=max_age):
        return {"skipped": "too old"}
    ev = next_event(conn)
    if not ev:
        return {"skipped": "no upcoming event to attach this to"}
    email = r.email.strip().lower()
    sp = conn.execute("INSERT INTO speakers(name, email, source_row) VALUES (%s,%s,%s) "
                      "ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                      (r.name.strip() or email, email, str(r.submitted))).fetchone()
    pid = propose(conn, f"cfp:{email}:{r.submitted}", "cfp_review",
                  {"summary": f"Talk proposal from {r.name or email}: {r.title}", "speaker_id": sp["id"],
                   "email": email, "name": r.name.strip(), "title": r.title.strip(), "message": r.message.strip()[:2000],
                   "event_id": ev["id"]}, event_id=ev["id"])
    return {"proposal": pid, "duplicate": pid is None}


def event_ctx(conn, event_id):
    """The event row and its host's name, for building previews and drafts."""
    ev = conn.execute("SELECT * FROM events WHERE id=%s", (event_id,)).fetchone() if event_id else None
    host = None
    if ev and ev["host_id"]:
        h = conn.execute("SELECT name FROM organisers WHERE id=%s", (ev["host_id"],)).fetchone()
        host = h["name"] if h else None
    return ev, host


def next_event(conn):
    return conn.execute("SELECT * FROM events WHERE status IN ('planning','confirmed') AND event_date >= %s "
                        "ORDER BY event_date LIMIT 1", (date.today(),)).fetchone()


class SpeakerStateIn(BaseModel):
    state: str          # invited | confirmed | declined | spoke


@app.post("/events/{event_id}/speakers/{speaker_id}/state", dependencies=[Depends(auth)])
def set_speaker_state(event_id: int, speaker_id: int, b: SpeakerStateIn, conn=Depends(db)):
    """Move a speaker through invited -> confirmed / declined / spoke. Declined and spoke free their slot."""
    if b.state not in ("invited", "confirmed", "declined", "spoke"):
        raise HTTPException(400, "state must be invited, confirmed, declined or spoke")
    r = conn.execute("UPDATE event_speakers SET state=%s, updated_at=now() WHERE event_id=%s AND speaker_id=%s "
                     "RETURNING format", (b.state, event_id, speaker_id)).fetchone()
    if not r:
        raise HTTPException(404, "that speaker is not invited to that event")
    audit(conn, "api", "speaker_state", {"event_id": event_id, "speaker_id": speaker_id, "state": b.state})
    return {"event_id": event_id, "speaker_id": speaker_id, "state": b.state, "slots": slots.describe(slot_counts(conn, event_id))}


@app.get("/events/{event_id}/speakers", dependencies=[Depends(auth)])
def event_speakers(event_id: int, conn=Depends(db)):
    rows = conn.execute("SELECT s.id AS speaker_id, s.name, es.state, es.format, es.talk_title FROM event_speakers es "
                        "JOIN speakers s ON s.id=es.speaker_id WHERE es.event_id=%s ORDER BY es.format, s.name", (event_id,)).fetchall()
    return {"slots": slots.describe(slot_counts(conn, event_id)), "speakers": rows}


@app.get("/speakers/awaiting", dependencies=[Depends(auth)])
def speakers_awaiting(conn=Depends(db)):
    """Invited speakers whose emails have gone out and who haven't replied yet (n8n looks for their replies)."""
    return conn.execute("SELECT es.event_id, es.speaker_id, s.email FROM event_speakers es JOIN speakers s ON s.id=es.speaker_id "
                        "WHERE (es.state='invited' AND es.invited_at IS NOT NULL AND es.last_reply_at IS NULL) "
                        "OR (es.state='confirmed' AND es.reconfirm_sent_at IS NOT NULL AND es.reconfirm_reply_at IS NULL)").fetchall()


class ReplyIn(BaseModel):
    email: str
    snippet: str = ""
    message_id: str


@app.post("/speakers/reply", dependencies=[Depends(auth)])
def speaker_reply(r: ReplyIn, conn=Depends(db)):
    """A speaker answered. Stop the follow-up and expiry timers and ask an organiser what it means."""
    row = conn.execute("SELECT es.event_id, es.speaker_id, es.talk_title, es.state, s.name FROM event_speakers es "
                       "JOIN speakers s ON s.id=es.speaker_id WHERE lower(s.email)=lower(%s) AND "
                       "((es.state='invited' AND es.invited_at IS NOT NULL AND es.last_reply_at IS NULL) OR "
                       "(es.state='confirmed' AND es.reconfirm_sent_at IS NOT NULL AND es.reconfirm_reply_at IS NULL))",
                       (r.email.strip(),)).fetchone()
    if not row:
        return {"skipped": "no speaker waiting on that address"}
    col = "reconfirm_reply_at" if row["state"] == "confirmed" else "last_reply_at"
    conn.execute(f"UPDATE event_speakers SET {col}=now(), updated_at=now() WHERE event_id=%s AND speaker_id=%s",
                 (row["event_id"], row["speaker_id"]))
    pid = propose(conn, f"reply:{row['event_id']}:{row['speaker_id']}:{r.message_id}", "speaker_reply",
                  {"summary": f"Reply from {row['name']}", "speaker_id": row["speaker_id"], "email": r.email.strip().lower(),
                   "name": row["name"], "title": row["talk_title"], "snippet": r.snippet[:1500],
                   "guess": clf.classify_rules(r.snippet), "event_id": row["event_id"]}, event_id=row["event_id"])
    return {"proposal": pid}


@app.get("/outbox", dependencies=[Depends(auth)])
def outbox(conn=Depends(db)):
    """One row per (pending, not yet announced proposal, organiser who may decide it and has Telegram linked)."""
    orgs = conn.execute("SELECT id, role, telegram_id FROM organisers WHERE active AND telegram_id IS NOT NULL").fetchall()
    out = []
    for p in conn.execute("SELECT * FROM proposed_actions WHERE status='pending' AND notified_at IS NULL ORDER BY id").fetchall():
        ev, host = event_ctx(conn, p["event_id"])
        text = f"Approval needed #{p['id']} [{p['kind']}]\n\n" + preview.render(p["kind"], p["payload"], ev, host)
        if p["kind"] == "cfp_review":
            text += f"\nSlots held now for this event: {slots.describe(slot_counts(conn, p['event_id']))}"
        for o in orgs:
            if policy.can_decide(o["role"], p["kind"], o["id"], p["payload"].get("requester_id")):
                out.append({"pid": p["id"], "kind": p["kind"], "text": text[:4000], "chat_id": o["telegram_id"]})
    # at-most-once: handing a proposal out marks it announced, so a flaky run can never send it twice
    for pid in {r["pid"] for r in out}:
        conn.execute("UPDATE proposed_actions SET notified_at=now() WHERE id=%s", (pid,))
    return out


@app.post("/proposals/{pid}/renotify", dependencies=[Depends(auth)])
def renotify(pid: int, conn=Depends(db)):
    """Announce a still-pending proposal again, e.g. if the chat message was lost."""
    conn.execute("UPDATE proposed_actions SET notified_at=NULL WHERE id=%s AND status='pending'", (pid,))
    return {"id": pid}


class TgDecisionIn(BaseModel):
    telegram_id: str
    decision: str
    variant: str | None = None


@app.post("/proposals/{pid}/decide_telegram", dependencies=[Depends(auth)])
def decide_telegram(pid: int, d: TgDecisionIn, conn=Depends(db)):
    """Called by n8n when an organiser presses a button. The decider is whoever owns that Telegram ID."""
    if d.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    org = conn.execute("SELECT id FROM organisers WHERE telegram_id=%s AND active", (d.telegram_id,)).fetchone()
    if not org:
        raise HTTPException(403, "not a linked organiser")
    return apply_decision(conn, pid, d.decision, org["id"], d.variant)


@app.get("/executor/queue", dependencies=[Depends(auth)])
def executor_queue(conn=Depends(db)):
    """Approved proposals, handed out once. No external system is called from here: until Gmail, Slack and
    LinkedIn credentials exist, the executor gives the approver the final text to use by hand.
    Handing a proposal out marks it done (at-most-once)."""
    out = []
    rows = conn.execute("SELECT p.*, o.telegram_id AS decider_chat, o.name AS decider FROM proposed_actions p "
                        "JOIN organisers o ON o.id = p.decided_by "
                        "WHERE p.status='approved' AND p.executed_at IS NULL ORDER BY p.id").fetchall()
    for p in rows:
        ev, host = event_ctx(conn, p["event_id"])
        artifact = preview.render(p["kind"], p["payload"], ev, host, final=True)
        email = preview.email_for(p["kind"], p["payload"], ev, host)
        if email:      # an approved email: stamp the send time now so a restart can never send it twice
            col = SENT_COLUMN[p["kind"]]
            conn.execute(f"UPDATE event_speakers SET {col}=now(), updated_at=now() WHERE event_id=%s AND speaker_id=%s",
                         (p["event_id"], p["payload"].get("speaker_id")))
            audit(conn, "executor", "email_released", {"id": p["id"], "kind": p["kind"], "to_speaker": p["payload"].get("speaker_id")})
        note = ("Sending the email to the speaker now, exactly as shown." if email
                else "Nothing was sent automatically (no sending account is connected for this).")
        text = f"Approved #{p['id']} [{p['kind']}] by {p['decider']}.\n{note}\n\n{artifact}"
        conn.execute("UPDATE proposed_actions SET status='done', executed_at=now() WHERE id=%s", (p["id"],))
        audit(conn, "executor", "handed_over", {"id": p["id"], "kind": p["kind"]})
        if p["decider_chat"]:
            out.append({"pid": p["id"], "kind": p["kind"], "chat_id": p["decider_chat"], "text": text[:4000],
                        "email": email})
    return out


@app.post("/proposals/{pid}/email_failed", dependencies=[Depends(auth)])
def email_failed(pid: int, conn=Depends(db)):
    """n8n could not send an approved email. Clear the sent stamp so timers don't run for an email that never left."""
    p = conn.execute("SELECT * FROM proposed_actions WHERE id=%s", (pid,)).fetchone()
    if not p or p["kind"] not in SENT_COLUMN:
        raise HTTPException(404, "not an email proposal")
    col = SENT_COLUMN[p["kind"]]
    conn.execute(f"UPDATE event_speakers SET {col}=NULL, updated_at=now() WHERE event_id=%s AND speaker_id=%s",
                 (p["event_id"], p["payload"].get("speaker_id")))
    conn.execute("UPDATE proposed_actions SET status='failed' WHERE id=%s", (pid,))
    audit(conn, "executor", "email_failed", {"id": pid})
    return {"id": pid, "status": "failed"}


@app.post("/proposals/{pid}/done", dependencies=[Depends(auth)])
def mark_done(pid: int, ok: bool = True, conn=Depends(db)):
    conn.execute("UPDATE proposed_actions SET status=%s WHERE id=%s AND status='approved'",
                 ("done" if ok else "failed", pid))
    audit(conn, "executor", "done" if ok else "failed", {"id": pid})
    return {"id": pid}


class InboundIn(BaseModel):
    channel: str
    sender: str
    body: str


@app.post("/inbound", dependencies=[Depends(auth)])
def inbound(m: InboundIn, conn=Depends(db)):
    intent, by = clf.classify(m.body)
    conn.execute("INSERT INTO inbound_messages(channel,sender,body,intent,handled_by) VALUES (%s,%s,%s,%s,%s)",
                 (m.channel, m.sender, m.body, intent, by))
    if by == "human" or intent in ("sponsor_enquiry", "speaker_pitch"):
        kind = "escalation"
        propose(conn, f"inbound:{m.channel}:{m.sender}:{hashlib.sha1(m.body.encode()).hexdigest()[:12]}", kind,
                {"summary": f"{intent} from {m.sender}: {m.body[:200]}", "intent": intent},
                event_id=(next_event(conn) or {}).get("id"))
    return {"intent": intent, "handled_by": by}


@app.post("/tick", dependencies=[Depends(auth)])
def tick(today: date | None = None, conn=Depends(db)):
    """Create proposals for every due, not-done checklist step of upcoming events."""
    today = today or date.today()
    created = 0
    for ev in conn.execute("SELECT * FROM events WHERE status IN ('planning','confirmed')").fetchall():
        done = {r["idem_key"].split(":")[-1] for r in conn.execute(
            "SELECT idem_key FROM proposed_actions WHERE idem_key LIKE %s AND status IN ('done','rejected')",
            (f"step:{ev['id']}:%",)).fetchall()}
        confirmed = conn.execute("SELECT count(*) AS n FROM event_speakers WHERE event_id=%s AND state='confirmed'",
                                 (ev["id"],)).fetchone()["n"]
        for s in due_steps(ev["event_date"], today, done, confirmed):
            if propose(conn, f"step:{ev['id']}:{s.key}", s.kind,
                       {"summary": f"{ev['title']}: {s.title}", "event_id": ev["id"], "step": s.key}, event_id=ev["id"]):
                created += 1
    followups = expired = 0
    for r in conn.execute("SELECT es.event_id, es.speaker_id, es.format, es.talk_title, es.followup_sent_at, "
                          "(now() - es.invited_at) AS age FROM event_speakers es JOIN events e ON e.id=es.event_id "
                          "WHERE es.state='invited' AND es.invited_at IS NOT NULL AND es.last_reply_at IS NULL "
                          "AND e.status IN ('planning','confirmed')").fetchall():
        if r["age"] >= timedelta(days=5):            # no reply: free the slot, offer it to the next speaker
            conn.execute("UPDATE event_speakers SET state='declined', reason='no reply after 5 days', updated_at=now() "
                         "WHERE event_id=%s AND speaker_id=%s", (r["event_id"], r["speaker_id"]))
            audit(conn, "tick", "speaker_expired", {"event_id": r["event_id"], "speaker_id": r["speaker_id"]})
            fill_slot(conn, r["event_id"], r["format"])
            expired += 1
        elif r["age"] >= timedelta(days=2) and r["followup_sent_at"] is None:
            if propose_invite(conn, r["event_id"], r["speaker_id"], r["format"], r["talk_title"], kind="speaker_followup", once=True):
                followups += 1
    reconfirms = 0
    for r in conn.execute("SELECT es.event_id, es.speaker_id, es.format, es.talk_title FROM event_speakers es "
                          "JOIN events e ON e.id=es.event_id WHERE es.state='confirmed' AND es.reconfirm_sent_at IS NULL "
                          "AND e.status IN ('planning','confirmed') AND e.event_date >= %s AND e.event_date <= %s",
                          (today, today + timedelta(days=2))).fetchall():
        if propose_invite(conn, r["event_id"], r["speaker_id"], r["format"], r["talk_title"], kind="speaker_reconfirm", once=True):
            reconfirms += 1
    return {"created": created, "followups_proposed": followups, "reconfirms_proposed": reconfirms,
            "expired": expired, "steps_defined": len(STEPS)}


class GrantIn(BaseModel):
    organiser_id: int
    systems: list[str]
    requested_by_id: int


AUTOMATED = {"github", "slack", "drive"}      # the rest are tracked manual steps


@app.post("/access/request", dependencies=[Depends(auth)])
def request_access(g: GrantIn, conn=Depends(db)):
    ids = []
    for system in g.systems:
        pid = propose(conn, f"grant:{g.organiser_id}:{system}", "access_grant",
                      {"summary": f"Grant {system} to organiser {g.organiser_id}",
                       "requester_id": g.requested_by_id, "organiser_id": g.organiser_id,
                       "system": system, "automated": system in AUTOMATED}, "access-manager")
        conn.execute("INSERT INTO access_grants(organiser_id, system, automated, proposal_id) "
                     "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (g.organiser_id, system, system in AUTOMATED, pid))
        ids.append(pid)
    return {"proposals": ids}
