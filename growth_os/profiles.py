import re

from pydantic import ValidationError

from . import onboarding
from .db import Database, dumps, in_clause, loads, now_iso, write_audit
from .errors import InvalidInput, NotFoundError, UnknownClientError
from .prompts import ClientProfile

CLIENT_STATUSES = ("onboarding", "active", "paused", "completed")
LIST_FIELDS = (
    "offers",
    "proof_points",
    "banned_phrases",
    "forbidden_topics",
    "channels",
    "core_expertise",
    "content_pillars",
    "business_goals",
    "extra_ctas",
    "reference_material",
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "client"


def clean_profile_data(data):
    cleaned = dict(data)
    for key in LIST_FIELDS:
        if key not in cleaned:
            continue
        value = cleaned[key]
        if isinstance(value, str):
            value = value.splitlines()
        cleaned[key] = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    for key, value in list(cleaned.items()):
        if isinstance(value, str):
            cleaned[key] = value.strip()
    return cleaned


class SingleClientStore:
    def __init__(self, base, profile):
        self.universal = base.universal
        self.stages = base.stages
        self.operators = base.operators
        self._profile = profile

    def client(self, client_id):
        if client_id != self._profile.id:
            raise UnknownClientError(f"Unknown client: {client_id!r}")
        return self._profile

    def client_ids(self):
        return [self._profile.id]


class ClientDirectory:
    def __init__(self, db: Database, base):
        self.db = db
        self.base = base

    def _rows(self):
        return {row["client_id"]: row for row in self.db.query("SELECT * FROM client_profiles")}

    def all(self):
        rows = self._rows()
        profiles = []
        base_ids = set()
        for profile in self.base.clients:
            base_ids.add(profile.id)
            row = rows.get(profile.id)
            profiles.append(ClientProfile.model_validate(loads(row["data"], {})) if row else profile)
        custom = sorted(
            (row for cid, row in rows.items() if cid not in base_ids and row["custom"]),
            key=lambda row: row["created_at"],
        )
        profiles.extend(ClientProfile.model_validate(loads(row["data"], {})) for row in custom)
        return profiles

    def get(self, client_id):
        for profile in self.all():
            if profile.id == client_id:
                return profile
        raise UnknownClientError(f"Unknown client: {client_id!r}")

    def exists(self, client_id):
        return any(profile.id == client_id for profile in self.all())

    def created_by(self, client_id):
        row = self.db.one("SELECT created_by, custom FROM client_profiles WHERE client_id=?", (client_id,))
        return row["created_by"] if row and row["custom"] else ""

    def save(self, client_id, data, actor):
        current = self.get(client_id)
        merged = {**current.model_dump(), **clean_profile_data(data), "id": client_id}
        profile = self._validate(merged)
        email = profile.contact_email
        if email and not EMAIL_RE.match(email):
            raise InvalidInput("Contact email is not a valid email address.")
        ts = now_iso()
        with self.db.session() as conn:
            existing = conn.execute("SELECT 1 FROM client_profiles WHERE client_id=?", (client_id,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE client_profiles SET data=?, updated_at=?, updated_by=? WHERE client_id=?",
                    (dumps(profile.model_dump()), ts, actor, client_id),
                )
            else:
                conn.execute(
                    "INSERT INTO client_profiles (client_id, data, custom, created_by, created_at, updated_at, updated_by) VALUES (?,?,0,'',?,?,?)",
                    (client_id, dumps(profile.model_dump()), ts, ts, actor),
                )
            conn.execute(
                "INSERT INTO client_meta (client_id, updated_at) VALUES (?, ?) ON CONFLICT(client_id) DO UPDATE SET updated_at=excluded.updated_at",
                (client_id, ts),
            )
            write_audit(conn, actor, client_id, "brand_profile_updated", "client", client_id)
        return profile

    def create(self, data, actor):
        cleaned = clean_profile_data(data)
        name = cleaned.get("name", "")
        if not name:
            raise InvalidInput("Client name is required.")
        base_id = _slug(name)
        client_id, suffix = base_id, 2
        while self.exists(client_id):
            client_id = f"{base_id}-{suffix}"
            suffix += 1
        profile = self._validate({**cleaned, "id": client_id})
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO client_profiles (client_id, data, custom, created_by, created_at, updated_at, updated_by) VALUES (?,?,1,?,?,?,?)",
                (client_id, dumps(profile.model_dump()), actor, ts, ts, actor),
            )
            conn.execute(
                "INSERT INTO client_meta (client_id, status, owner, updated_at) VALUES (?, 'onboarding', ?, ?)",
                (client_id, actor, ts),
            )
            write_audit(conn, actor, client_id, "client_created", "client", client_id, name)
        return profile

    @staticmethod
    def _validate(data):
        try:
            profile = ClientProfile.model_validate(data)
        except ValidationError as exc:
            fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
            raise InvalidInput(f"Invalid brand profile: {fields}") from exc
        if not profile.name or not profile.founder or not profile.industry:
            raise InvalidInput("Client name, founder and industry are required.")
        return profile

    def meta(self, client_id):
        row = self.db.one("SELECT * FROM client_meta WHERE client_id=?", (client_id,))
        if row:
            return row
        return {"client_id": client_id, "status": "onboarding", "owner": "", "notes": "", "updated_at": ""}

    def metas(self, client_ids):
        client_ids = list(client_ids)
        if not client_ids:
            return {}
        clause, values = in_clause("client_id", client_ids)
        rows = {row["client_id"]: row for row in self.db.query(f"SELECT * FROM client_meta WHERE {clause}", values)}
        return {cid: rows.get(cid) or self.meta(cid) for cid in client_ids}

    def set_meta(self, client_id, actor, status=None, owner=None, notes=None):
        if status is not None and status not in CLIENT_STATUSES:
            raise InvalidInput(f"Status must be one of: {', '.join(CLIENT_STATUSES)}.")
        current = self.meta(client_id)
        updated = {
            "status": status if status is not None else current["status"],
            "owner": owner if owner is not None else current["owner"],
            "notes": notes if notes is not None else current["notes"],
        }
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO client_meta (client_id, status, owner, notes, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(client_id) DO UPDATE SET status=excluded.status, owner=excluded.owner, notes=excluded.notes, updated_at=excluded.updated_at",
                (client_id, updated["status"], updated["owner"], updated["notes"], now_iso()),
            )
            write_audit(conn, actor, client_id, "client_updated", "client", client_id, f"status={updated['status']}")

    def manual_steps(self, client_id):
        rows = self.db.query("SELECT step_key, done FROM onboarding_steps WHERE client_id=?", (client_id,))
        return {row["step_key"]: bool(row["done"]) for row in rows}

    def set_manual_step(self, client_id, key, done, actor):
        if key not in onboarding.MANUAL_KEYS:
            raise InvalidInput(f"Step {key!r} is derived from workspace data and cannot be set manually.")
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO onboarding_steps (client_id, step_key, done, updated_at, updated_by) VALUES (?,?,?,?,?) "
                "ON CONFLICT(client_id, step_key) DO UPDATE SET done=excluded.done, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (client_id, key, int(done), ts, actor),
            )
            conn.execute(
                "INSERT INTO client_meta (client_id, updated_at) VALUES (?, ?) ON CONFLICT(client_id) DO UPDATE SET updated_at=excluded.updated_at",
                (client_id, ts),
            )
            write_audit(conn, actor, client_id, "onboarding_step", "client", client_id, f"{key}={'done' if done else 'open'}")

    def onboarding(self, profile, stats):
        return onboarding.evaluate(profile, self.manual_steps(profile.id), stats)

    def require(self, client_id):
        if not self.exists(client_id):
            raise NotFoundError(f"Client {client_id!r} not found.")
