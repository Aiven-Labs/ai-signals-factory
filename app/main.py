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
from . import notify, policy, preview
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


def propose(conn, idem_key, kind, payload, requested_by="system"):
    row = conn.execute(
        "INSERT INTO proposed_actions(idem_key, kind, payload, requested_by) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (idem_key) DO NOTHING RETURNING id",
        (idem_key, kind, json.dumps(payload), requested_by)).fetchone()
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


@app.post("/proposals", dependencies=[Depends(auth)])
def create_proposal(p: ProposalIn, conn=Depends(db)):
    return {"id": propose(conn, p.idem_key, p.kind, p.payload, p.requested_by)}


@app.get("/proposals", dependencies=[Depends(auth)])
def list_proposals(status: str = "pending", conn=Depends(db)):
    return conn.execute("SELECT * FROM proposed_actions WHERE status=%s ORDER BY id", (status,)).fetchall()


class DecisionIn(BaseModel):
    decision: str            # approved | rejected
    decided_by: int          # organisers.id


def apply_decision(conn, pid: int, decision: str, organiser_id: int):
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
    conn.execute("UPDATE proposed_actions SET status=%s, decided_by=%s, decided_at=now() WHERE id=%s",
                 (decision, org["id"], pid))
    audit(conn, org["name"], decision, {"id": pid})
    return {"id": pid, "status": decision, "by": org["name"], "kind": prop["kind"]}


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
    email = r.email.strip().lower()
    sp = conn.execute("INSERT INTO speakers(name, email, source_row) VALUES (%s,%s,%s) "
                      "ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                      (r.name.strip() or email, email, str(r.submitted))).fetchone()
    pid = propose(conn, f"cfp:{email}:{r.submitted}", "cfp_review",
                  {"summary": f"Talk proposal from {r.name or email}: {r.title}", "speaker_id": sp["id"],
                   "email": email, "name": r.name.strip(), "title": r.title.strip(), "message": r.message.strip()[:2000]})
    return {"proposal": pid, "duplicate": pid is None}


def next_event(conn):
    return conn.execute("SELECT * FROM events WHERE status IN ('planning','confirmed') AND event_date >= %s "
                        "ORDER BY event_date LIMIT 1", (date.today(),)).fetchone()


@app.get("/outbox", dependencies=[Depends(auth)])
def outbox(conn=Depends(db)):
    """One row per (pending, not yet announced proposal, organiser who may decide it and has Telegram linked)."""
    orgs = conn.execute("SELECT id, role, telegram_id FROM organisers WHERE active AND telegram_id IS NOT NULL").fetchall()
    out = []
    for p in conn.execute("SELECT * FROM proposed_actions WHERE status='pending' AND notified_at IS NULL ORDER BY id").fetchall():
        ev = host = None
        if p["payload"].get("event_id"):
            ev = conn.execute("SELECT * FROM events WHERE id=%s", (p["payload"]["event_id"],)).fetchone()
            if ev and ev["host_id"]:
                h = conn.execute("SELECT name FROM organisers WHERE id=%s", (ev["host_id"],)).fetchone()
                host = h["name"] if h else None
        text = f"Approval needed #{p['id']} [{p['kind']}]\n\n" + preview.render(p["kind"], p["payload"], ev, host)
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


@app.post("/proposals/{pid}/decide_telegram", dependencies=[Depends(auth)])
def decide_telegram(pid: int, d: TgDecisionIn, conn=Depends(db)):
    """Called by n8n when an organiser presses a button. The decider is whoever owns that Telegram ID."""
    if d.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    org = conn.execute("SELECT id FROM organisers WHERE telegram_id=%s AND active", (d.telegram_id,)).fetchone()
    if not org:
        raise HTTPException(403, "not a linked organiser")
    return apply_decision(conn, pid, d.decision, org["id"])


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
        ev = host = None
        if p["payload"].get("event_id"):
            ev = conn.execute("SELECT * FROM events WHERE id=%s", (p["payload"]["event_id"],)).fetchone()
            if ev and ev["host_id"]:
                h = conn.execute("SELECT name FROM organisers WHERE id=%s", (ev["host_id"],)).fetchone()
                host = h["name"] if h else None
        if p["kind"] == "cfp_review":
            ev = next_event(conn)
            host = None
            if ev and ev["host_id"]:
                h = conn.execute("SELECT name FROM organisers WHERE id=%s", (ev["host_id"],)).fetchone()
                host = h["name"] if h else None
        artifact = preview.render(p["kind"], p["payload"], ev, host, final=True)
        draft = preview.draft(p["kind"], p["payload"], ev, host)
        note = ("A Gmail draft is being created in Drafts (NOT sent). Check and send it yourself."
                if draft else "Nothing was sent automatically (no sending account is connected for this).")
        text = f"Approved #{p['id']} [{p['kind']}] by {p['decider']}.\n{note}\n\n{artifact}"
        conn.execute("UPDATE proposed_actions SET status='done', executed_at=now() WHERE id=%s", (p["id"],))
        audit(conn, "executor", "handed_over", {"id": p["id"], "kind": p["kind"]})
        if p["decider_chat"]:
            out.append({"pid": p["id"], "kind": p["kind"], "chat_id": p["decider_chat"], "text": text[:4000],
                        "draft": draft})
    return out


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
                {"summary": f"{intent} from {m.sender}: {m.body[:200]}", "intent": intent})
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
        for s in due_steps(ev["event_date"], today, done):
            if propose(conn, f"step:{ev['id']}:{s.key}", s.kind,
                       {"summary": f"{ev['title']}: {s.title}", "event_id": ev["id"], "step": s.key}):
                created += 1
    return {"created": created, "steps_defined": len(STEPS)}


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
