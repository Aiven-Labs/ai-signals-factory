"""Core app: proposals, approvals, inbound triage, daily tick, access grants.
Zero model calls on the default path. n8n calls these endpoints on a schedule."""
import base64
import hashlib
import json
import os
from datetime import date

import psycopg
import psycopg.conninfo
from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from . import classify as clf
from . import notify, policy
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


def notify_organisers(conn, pid, kind, summary):
    """Send the proposal to every active organiser whose role may decide it and who has Telegram linked."""
    orgs = conn.execute("SELECT id, role, telegram_id FROM organisers WHERE active AND telegram_id IS NOT NULL").fetchall()
    chats = [o["telegram_id"] for o in orgs if policy.can_decide(o["role"], kind, o["id"], None)]
    return notify.proposal(chats, pid, kind, summary)


def propose(conn, idem_key, kind, payload, requested_by="system"):
    row = conn.execute(
        "INSERT INTO proposed_actions(idem_key, kind, payload, requested_by) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (idem_key) DO NOTHING RETURNING id",
        (idem_key, kind, json.dumps(payload), requested_by)).fetchone()
    if row:
        audit(conn, requested_by, "propose", {"id": row["id"], "kind": kind})
        notify_organisers(conn, row["id"], kind, payload.get("summary", ""))
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


@app.post("/proposals/{pid}/notify", dependencies=[Depends(auth)])
def renotify(pid: int, conn=Depends(db)):
    p = conn.execute("SELECT * FROM proposed_actions WHERE id=%s AND status='pending'", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "no such pending proposal")
    return {"sent_to": len(notify_organisers(conn, pid, p["kind"], p["payload"].get("summary", "")))}


@app.post("/telegram")
def telegram(update: dict, x_telegram_bot_api_secret_token: str = Header(default=""), conn=Depends(db)):
    """Telegram webhook. Only button presses from linked organisers change anything."""
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret or x_telegram_bot_api_secret_token != secret:
        raise HTTPException(401, "bad secret")
    cb = update.get("callback_query")
    if not cb:
        return {"ok": True}
    who = str(cb["from"]["id"])
    org = conn.execute("SELECT id FROM organisers WHERE telegram_id=%s AND active", (who,)).fetchone()
    if not org:
        notify.answer(cb["id"], "You are not a linked organiser.")
        return {"ok": True}
    action, _, pid = (cb.get("data") or "").partition(":")
    decision = {"a": "approved", "r": "rejected"}.get(action)
    if not decision or not pid.isdigit():
        return {"ok": True}
    msg = cb.get("message") or {}
    try:
        r = apply_decision(conn, int(pid), decision, org["id"])
    except HTTPException as e:
        notify.answer(cb["id"], str(e.detail))
        return {"ok": True}
    notify.answer(cb["id"], f"{decision.capitalize()}.")
    if msg:
        notify.edit(msg["chat"]["id"], msg["message_id"], f"#{pid} [{r['kind']}] {decision} by {r['by']}")
    return {"ok": True}


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
