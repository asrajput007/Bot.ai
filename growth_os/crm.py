import re
from datetime import date

from .db import dumps, in_clause, loads, new_id, now_iso, write_audit
from .errors import InvalidInput, NotFoundError

CAMPAIGN_STATUSES = ("planned", "active", "paused", "completed")
LEAD_STATUSES = ("new", "contacted", "replied", "qualified", "meeting_booked", "converted", "disqualified")
RESPONDED = ("replied", "qualified", "meeting_booked", "converted")
REACHED = ("contacted", *RESPONDED)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _campaign(row):
    if row:
        row["channels"] = loads(row["channels"], [])
    return row


def _parse_date(value, label):
    if not value:
        return ""
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise InvalidInput(f"{label} must be a valid date.") from exc


class CampaignRepo:
    def __init__(self, db):
        self.db = db

    def create(self, client_id, actor, *, name, objective="", audience="", channels=None, start_date="", end_date="",
               lead_objective="", owner="", status="planned"):
        name = (name or "").strip()
        if len(name) < 3:
            raise InvalidInput("Campaign name must be at least 3 characters.")
        if status not in CAMPAIGN_STATUSES:
            raise InvalidInput("Unsupported campaign status.")
        start, end = _parse_date(start_date, "Start date"), _parse_date(end_date, "End date")
        if start and end and end < start:
            raise InvalidInput("End date cannot be before the start date.")
        duplicate = self.db.one(
            "SELECT 1 FROM campaigns WHERE client_id=? AND LOWER(name)=LOWER(?)", (client_id, name)
        )
        if duplicate:
            raise InvalidInput("This client already has a campaign with that name.")
        campaign_id, ts = new_id(), now_iso()
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO campaigns (id, client_id, name, objective, audience, channels, start_date, end_date, lead_objective, status, owner, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, client_id, name, objective.strip(), audience.strip(), dumps(list(channels or [])),
                 start, end, lead_objective.strip(), status, owner, ts, ts),
            )
            write_audit(conn, actor, client_id, "campaign_created", "campaign", campaign_id, name)
        return self.get(campaign_id)

    def get(self, campaign_id):
        return _campaign(self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))

    def update(self, campaign_id, actor, **fields):
        current = self.get(campaign_id)
        if not current:
            raise NotFoundError("Campaign not found.")
        allowed = ("name", "objective", "audience", "channels", "start_date", "end_date", "lead_objective", "status", "owner")
        merged = {**current, **{key: value for key, value in fields.items() if key in allowed}}
        if len((merged["name"] or "").strip()) < 3:
            raise InvalidInput("Campaign name must be at least 3 characters.")
        if merged["status"] not in CAMPAIGN_STATUSES:
            raise InvalidInput("Unsupported campaign status.")
        start, end = _parse_date(merged["start_date"], "Start date"), _parse_date(merged["end_date"], "End date")
        if start and end and end < start:
            raise InvalidInput("End date cannot be before the start date.")
        with self.db.session() as conn:
            conn.execute(
                "UPDATE campaigns SET name=?, objective=?, audience=?, channels=?, start_date=?, end_date=?, lead_objective=?, status=?, owner=?, updated_at=? WHERE id=?",
                (merged["name"].strip(), merged["objective"], merged["audience"], dumps(list(merged["channels"])),
                 start, end, merged["lead_objective"], merged["status"], merged["owner"], now_iso(), campaign_id),
            )
            write_audit(conn, actor, current["client_id"], "campaign_updated", "campaign", campaign_id, merged["name"])
        return self.get(campaign_id)

    def list(self, client_ids, status=None, search=""):
        client_ids = list(client_ids)
        if not client_ids:
            return []
        clause, values = in_clause("client_id", client_ids)
        where, params = [clause], list(values)
        if status:
            where.append("status=?")
            params.append(status)
        if search:
            where.append("(LOWER(name) LIKE ? OR LOWER(objective) LIKE ?)")
            needle = f"%{search.lower()}%"
            params.extend([needle, needle])
        rows = self.db.query(f"SELECT * FROM campaigns WHERE {' AND '.join(where)} ORDER BY updated_at DESC", params)
        return [_campaign(row) for row in rows]


class LeadRepo:
    def __init__(self, db):
        self.db = db

    def create(self, client_id, actor, *, name, company="", role="", email="", source="", campaign_id="", owner="",
               notes="", next_follow_up=""):
        name = (name or "").strip()
        if len(name) < 2:
            raise InvalidInput("Prospect name is required.")
        email = (email or "").strip()
        if email and not EMAIL_RE.match(email):
            raise InvalidInput("Business email is not a valid email address.")
        if email and self.db.one("SELECT 1 FROM leads WHERE client_id=? AND LOWER(email)=LOWER(?)", (client_id, email)):
            raise InvalidInput("A lead with this email already exists for this client.")
        follow_up = _parse_date(next_follow_up, "Next follow-up")
        lead_id, ts = new_id(), now_iso()
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO leads (id, client_id, campaign_id, name, company, role, email, source, status, owner, notes, last_interaction, next_follow_up, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?, 'new', ?,?, '', ?,?,?)",
                (lead_id, client_id, campaign_id, name, company.strip(), role.strip(), email, source.strip(), owner,
                 notes.strip(), follow_up, ts, ts),
            )
            conn.execute(
                "INSERT INTO lead_activity (lead_id, client_id, ts, kind, note, actor) VALUES (?,?,?,?,?,?)",
                (lead_id, client_id, ts, "created", "Lead added", actor),
            )
            write_audit(conn, actor, client_id, "lead_created", "lead", lead_id, name)
        return self.get(lead_id)

    def get(self, lead_id):
        return self.db.one("SELECT * FROM leads WHERE id=?", (lead_id,))

    def update(self, lead_id, actor, **fields):
        current = self.get(lead_id)
        if not current:
            raise NotFoundError("Lead not found.")
        allowed = ("name", "company", "role", "email", "source", "campaign_id", "owner", "notes", "next_follow_up")
        merged = {**current, **{key: value for key, value in fields.items() if key in allowed}}
        if len((merged["name"] or "").strip()) < 2:
            raise InvalidInput("Prospect name is required.")
        email = (merged["email"] or "").strip()
        if email and not EMAIL_RE.match(email):
            raise InvalidInput("Business email is not a valid email address.")
        clash = self.db.one(
            "SELECT 1 FROM leads WHERE client_id=? AND LOWER(email)=LOWER(?) AND id<>? AND email<>''",
            (current["client_id"], email, lead_id),
        )
        if email and clash:
            raise InvalidInput("Another lead already uses this email for this client.")
        follow_up = _parse_date(merged["next_follow_up"], "Next follow-up")
        with self.db.session() as conn:
            conn.execute(
                "UPDATE leads SET name=?, company=?, role=?, email=?, source=?, campaign_id=?, owner=?, notes=?, next_follow_up=?, updated_at=? WHERE id=?",
                (merged["name"].strip(), merged["company"], merged["role"], email, merged["source"], merged["campaign_id"],
                 merged["owner"], merged["notes"], follow_up, now_iso(), lead_id),
            )
            write_audit(conn, actor, current["client_id"], "lead_updated", "lead", lead_id, merged["name"])
        return self.get(lead_id)

    def set_status(self, lead_id, status, actor):
        if status not in LEAD_STATUSES:
            raise InvalidInput("Unsupported lead status.")
        current = self.get(lead_id)
        if not current:
            raise NotFoundError("Lead not found.")
        if current["status"] == status:
            return current
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute(
                "UPDATE leads SET status=?, last_interaction=?, updated_at=? WHERE id=?", (status, ts, ts, lead_id)
            )
            conn.execute(
                "INSERT INTO lead_activity (lead_id, client_id, ts, kind, note, actor) VALUES (?,?,?,?,?,?)",
                (lead_id, current["client_id"], ts, "status", f"{current['status']} -> {status}", actor),
            )
            write_audit(conn, actor, current["client_id"], "lead_status", "lead", lead_id, f"{current['status']} -> {status}")
        return self.get(lead_id)

    def log_activity(self, lead_id, kind, note, actor, deliverable_id=""):
        current = self.get(lead_id)
        if not current:
            raise NotFoundError("Lead not found.")
        if not note.strip():
            raise InvalidInput("Add a short note describing the interaction.")
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO lead_activity (lead_id, client_id, ts, kind, note, actor, deliverable_id) VALUES (?,?,?,?,?,?,?)",
                (lead_id, current["client_id"], ts, kind, note.strip(), actor, deliverable_id),
            )
            conn.execute("UPDATE leads SET last_interaction=?, updated_at=? WHERE id=?", (ts, ts, lead_id))
            write_audit(conn, actor, current["client_id"], f"lead_{kind}", "lead", lead_id, note.strip()[:120])

    def activity(self, lead_id):
        return self.db.query("SELECT * FROM lead_activity WHERE lead_id=? ORDER BY id DESC", (lead_id,))

    def delete(self, lead_id, actor):
        current = self.get(lead_id)
        if not current:
            raise NotFoundError("Lead not found.")
        with self.db.session() as conn:
            conn.execute("DELETE FROM lead_activity WHERE lead_id=?", (lead_id,))
            conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
            write_audit(conn, actor, current["client_id"], "lead_deleted", "lead", lead_id, current["name"])

    def list(self, client_ids, status=None, campaign_id=None, owner=None, search=""):
        client_ids = list(client_ids)
        if not client_ids:
            return []
        clause, values = in_clause("client_id", client_ids)
        where, params = [clause], list(values)
        for column, value in (("status", status), ("campaign_id", campaign_id), ("owner", owner)):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if search:
            where.append("(LOWER(name) LIKE ? OR LOWER(company) LIKE ? OR LOWER(email) LIKE ?)")
            needle = f"%{search.lower()}%"
            params.extend([needle, needle, needle])
        return self.db.query(f"SELECT * FROM leads WHERE {' AND '.join(where)} ORDER BY updated_at DESC", params)
