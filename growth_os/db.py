import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS client_profiles (
    client_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    custom INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS client_meta (
    client_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'onboarding',
    owner TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS onboarding_steps (
    client_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (client_id, step_key)
);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    name TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
    channels TEXT NOT NULL DEFAULT '[]',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    lead_objective TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    owner TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaigns_client ON campaigns(client_id);
CREATE TABLE IF NOT EXISTS packages (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    parent_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    selected INTEGER NOT NULL DEFAULT 1,
    brief TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '{}',
    draft TEXT NOT NULL DEFAULT '{}',
    assets TEXT,
    rounds TEXT NOT NULL DEFAULT '[]',
    asset_issues TEXT NOT NULL DEFAULT '[]',
    quality TEXT NOT NULL DEFAULT 'failed',
    status TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_packages_client ON packages(client_id);
CREATE INDEX IF NOT EXISTS idx_packages_root ON packages(root_id);
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    channel TEXT NOT NULL,
    content TEXT NOT NULL,
    previous_content TEXT,
    approval_status TEXT NOT NULL,
    approval_note TEXT NOT NULL DEFAULT '',
    publishing_status TEXT NOT NULL DEFAULT 'not_scheduled',
    scheduled_at TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    publish_note TEXT NOT NULL DEFAULT '',
    edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deliverables_client ON deliverables(client_id);
CREATE INDEX IF NOT EXISTS idx_deliverables_package ON deliverables(package_id);
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    owner TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    last_interaction TEXT NOT NULL DEFAULT '',
    next_follow_up TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_client ON leads(client_id);
CREATE TABLE IF NOT EXISTS lead_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    deliverable_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lead_activity_lead ON lead_activity(lead_id);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    client_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_client ON audit_events(client_id);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id():
    return uuid.uuid4().hex[:12]


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def loads(value, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def in_clause(column, values):
    values = list(values)
    return f"{column} IN ({','.join('?' for _ in values)})", values


def write_audit(conn, actor, client_id, action, entity="", entity_id="", detail=""):
    conn.execute(
        "INSERT INTO audit_events (ts, actor, client_id, action, entity, entity_id, detail) VALUES (?,?,?,?,?,?,?)",
        (now_iso(), actor, client_id, action, entity, entity_id, detail),
    )


class Database:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self._ready = False

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def session(self):
        with self._lock:
            conn = self._connect()
            try:
                if not self._ready:
                    conn.executescript(SCHEMA)
                    self._ready = True
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    def query(self, sql, params=()):
        with self.session() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.session() as conn:
            return conn.execute(sql, params).lastrowid

    def log(self, actor, client_id, action, entity="", entity_id="", detail=""):
        with self.session() as conn:
            write_audit(conn, actor, client_id, action, entity, entity_id, detail)

    def activity(self, client_ids=None, limit=50):
        if client_ids is not None:
            client_ids = list(client_ids)
            if not client_ids:
                return []
            clause, values = in_clause("client_id", client_ids)
            return self.query(
                f"SELECT * FROM audit_events WHERE {clause} ORDER BY id DESC LIMIT ?", (*values, limit)
            )
        return self.query("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
