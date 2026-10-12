from datetime import datetime

from pydantic import ValidationError

from .db import dumps, in_clause, loads, new_id, now_iso, write_audit
from .errors import InvalidInput, NotFoundError
from .schemas import Draft, Email, SocialPost

APPROVAL_STATES = ("pending_approval", "needs_review", "approved", "changes_requested")
PUBLISHING_STATES = ("not_scheduled", "scheduled", "published")
PLATFORM_LABELS = {"linkedin": "LinkedIn", "x": "X", "email": "Email", "strategy": "Strategy", "cta": "CTA"}
CTA_MAX = 80


def _package(row):
    if not row:
        return None
    for key, default in (("options", {}), ("draft", {}), ("assets", None), ("rounds", []), ("asset_issues", [])):
        row[key] = loads(row[key], default)
    return row


def _deliverable(row):
    if not row:
        return None
    rounds = loads(row.pop("rounds_json", None), [])
    row["content"] = loads(row["content"], {})
    row["previous_content"] = loads(row.get("previous_content"), None)
    if row["kind"] == "strategy":
        row["quality"] = "passed" if rounds and rounds[-1].get("passed") else "failed"
    return row


def deliverable_title(item):
    content = item["content"]
    if item["kind"] == "strategy":
        return content.get("headline") or item["label"]
    if item["kind"] == "email":
        return content.get("subject") or item["label"]
    if item["kind"] == "social":
        return (content.get("text") or item["label"])[:80]
    return "CTA set"


def deliverable_text(item):
    content = item["content"]
    if item["kind"] == "strategy":
        lines = [content.get("headline", ""), "", content.get("body", ""), "", "Key messages:"]
        lines.extend(f"- {message}" for message in content.get("key_messages", []))
        return "\n".join(lines).strip()
    if item["kind"] == "email":
        return f"Subject: {content.get('subject', '')}\nPreview: {content.get('preview', '')}\n\n{content.get('body', '')}\n\nCTA: {content.get('cta', '')}"
    if item["kind"] == "social":
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in content.get("hashtags", []))
        return f"{content.get('text', '')}\n\n{tags}".strip()
    return "\n".join(f"- {cta}" for cta in content.get("ctas", []))


def _specs(draft, assets, status, rounds):
    draft_ok = bool(rounds) and bool(rounds[-1].get("passed"))
    asset_state = "pending_approval" if status == "completed" else "needs_review"
    specs = [{
        "kind": "strategy", "label": "Strategy", "channel": "strategy", "content": draft,
        "approval_status": "pending_approval" if draft_ok else "needs_review",
    }]
    if assets:
        for index, email in enumerate(assets.get("emails", []), 1):
            specs.append({"kind": "email", "label": f"Email {index}", "channel": "email", "content": email})
        for post in assets.get("social_posts", []):
            label = f"{PLATFORM_LABELS.get(post['platform'], post['platform'])} post"
            specs.append({"kind": "social", "label": label, "channel": post["platform"], "content": post})
        specs.append({"kind": "cta", "label": "CTA set", "channel": "cta", "content": {"ctas": assets.get("ctas", [])}})
    return [{"approval_status": asset_state, **spec} for spec in specs]


def _validated_content(kind, content):
    try:
        if kind == "strategy":
            return Draft.model_validate(content).model_dump()
        if kind == "email":
            return Email.model_validate(content).model_dump()
        if kind == "social":
            return SocialPost.model_validate(content).model_dump()
        ctas = [cta.strip() for cta in content.get("ctas", []) if cta.strip()]
    except ValidationError as exc:
        raise InvalidInput("Edited content is incomplete or malformed.") from exc
    if not ctas:
        raise InvalidInput("At least one CTA is required.")
    if any(len(cta) > CTA_MAX for cta in ctas):
        raise InvalidInput(f"Each CTA must be {CTA_MAX} characters or fewer.")
    return {"ctas": ctas}


class ContentRepo:
    def __init__(self, db):
        self.db = db

    def save_package(self, *, client_id, campaign_id, run_id, brief, options, draft, assets, rounds, asset_issues, status, actor, parent_id=""):
        package_id = new_id()
        if parent_id:
            parent = self.package(parent_id)
            if not parent or parent["client_id"] != client_id:
                raise NotFoundError("Parent version not found for this client.")
            root_id = parent["root_id"]
            version = self.db.one("SELECT MAX(version) AS v FROM packages WHERE root_id=?", (root_id,))["v"] + 1
        else:
            root_id, version = package_id, 1
        quality = "passed" if status == "completed" else "failed"
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute("UPDATE packages SET selected=0 WHERE root_id=?", (root_id,))
            conn.execute(
                "INSERT INTO packages (id, client_id, campaign_id, run_id, root_id, parent_id, version, selected, brief, options, draft, assets, rounds, asset_issues, quality, status, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
                (
                    package_id, client_id, campaign_id, run_id, root_id, parent_id, version, brief,
                    dumps(options), dumps(draft), dumps(assets) if assets else None, dumps(rounds),
                    dumps(asset_issues), quality, status, actor, ts,
                ),
            )
            for spec in _specs(draft, assets, status, rounds):
                conn.execute(
                    "INSERT INTO deliverables (id, package_id, client_id, campaign_id, kind, label, channel, content, approval_status, created_at, updated_at, updated_by) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), package_id, client_id, campaign_id, spec["kind"], spec["label"], spec["channel"],
                     dumps(spec["content"]), spec["approval_status"], ts, ts, actor),
                )
            action = "version_created" if parent_id else "package_created"
            write_audit(conn, actor, client_id, action, "package", package_id, f"v{version} {quality}")
        return self.package(package_id)

    def package(self, package_id):
        return _package(self.db.one("SELECT * FROM packages WHERE id=?", (package_id,)))

    def packages(self, client_ids, limit=100, selected_only=False):
        client_ids = list(client_ids)
        if not client_ids:
            return []
        clause, values = in_clause("client_id", client_ids)
        extra = " AND selected=1" if selected_only else ""
        rows = self.db.query(
            f"SELECT * FROM packages WHERE {clause}{extra} ORDER BY created_at DESC, version DESC LIMIT ?",
            (*values, limit),
        )
        return [_package(row) for row in rows]

    def versions(self, root_id):
        rows = self.db.query("SELECT * FROM packages WHERE root_id=? ORDER BY version", (root_id,))
        return [_package(row) for row in rows]

    def select_version(self, package_id, actor):
        package = self.package(package_id)
        if not package:
            raise NotFoundError("Version not found.")
        with self.db.session() as conn:
            conn.execute("UPDATE packages SET selected=0 WHERE root_id=?", (package["root_id"],))
            conn.execute("UPDATE packages SET selected=1 WHERE id=?", (package_id,))
            write_audit(conn, actor, package["client_id"], "version_selected", "package", package_id, f"v{package['version']}")

    def deliverables(self, client_ids, approval=None, publishing=None, kind=None, channel=None, campaign_id=None,
                     package_id=None, selected_only=True, search="", limit=500):
        client_ids = list(client_ids)
        if not client_ids:
            return []
        clause, values = in_clause("d.client_id", client_ids)
        where, params = [clause], list(values)
        for column, value in (("d.approval_status", approval), ("d.publishing_status", publishing), ("d.kind", kind),
                              ("d.channel", channel), ("d.campaign_id", campaign_id), ("d.package_id", package_id)):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if selected_only and not package_id:
            where.append("(p.selected=1 OR d.publishing_status IN ('scheduled','published'))")
        if search:
            where.append("(LOWER(d.content) LIKE ? OR LOWER(d.label) LIKE ?)")
            needle = f"%{search.lower()}%"
            params.extend([needle, needle])
        rows = self.db.query(
            "SELECT d.*, p.version AS version, p.selected AS selected, p.quality AS quality, p.root_id AS root_id, p.run_id AS run_id, p.rounds AS rounds_json "
            f"FROM deliverables d JOIN packages p ON p.id=d.package_id WHERE {' AND '.join(where)} "
            "ORDER BY d.updated_at DESC LIMIT ?",
            (*params, limit),
        )
        return [_deliverable(row) for row in rows]

    def deliverable(self, deliverable_id):
        row = self.db.one(
            "SELECT d.*, p.version AS version, p.selected AS selected, p.quality AS quality, p.root_id AS root_id, p.run_id AS run_id, p.rounds AS rounds_json "
            "FROM deliverables d JOIN packages p ON p.id=d.package_id WHERE d.id=?",
            (deliverable_id,),
        )
        return _deliverable(row)

    def update_content(self, deliverable_id, content, actor):
        item = self.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        if item["publishing_status"] == "published":
            raise InvalidInput("Published content cannot be edited. Create a revision instead.")
        validated = _validated_content(item["kind"], content)
        if validated == item["content"]:
            return item
        approval = "needs_review" if item["quality"] != "passed" else "pending_approval"
        with self.db.session() as conn:
            conn.execute(
                "UPDATE deliverables SET content=?, previous_content=?, edited=1, approval_status=?, approval_note='', "
                "publishing_status='not_scheduled', scheduled_at='', updated_at=?, updated_by=? WHERE id=?",
                (dumps(validated), dumps(item["content"]), approval, now_iso(), actor, deliverable_id),
            )
            write_audit(conn, actor, item["client_id"], "asset_edited", "deliverable", deliverable_id, item["label"])
        return self.deliverable(deliverable_id)

    def set_approval(self, deliverable_id, status, actor, note="", override=False):
        if status not in ("approved", "changes_requested", "pending_approval"):
            raise InvalidInput("Unsupported approval status.")
        item = self.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        if status == "approved" and item["quality"] != "passed" and not override:
            raise InvalidInput("This asset did not pass the quality gate. Confirm the override to approve it.")
        if status == "changes_requested" and not note.strip():
            raise InvalidInput("Describe the changes you need.")
        updates = {"approval_status": status, "approval_note": note.strip()}
        if status != "approved":
            updates.update(publishing_status="not_scheduled", scheduled_at="")
        with self.db.session() as conn:
            conn.execute(
                "UPDATE deliverables SET approval_status=?, approval_note=?, publishing_status=COALESCE(?, publishing_status), "
                "scheduled_at=COALESCE(?, scheduled_at), updated_at=?, updated_by=? WHERE id=?",
                (updates["approval_status"], updates["approval_note"], updates.get("publishing_status"),
                 updates.get("scheduled_at"), now_iso(), actor, deliverable_id),
            )
            write_audit(conn, actor, item["client_id"], f"asset_{status}", "deliverable", deliverable_id, item["label"])
        return self.deliverable(deliverable_id)

    def schedule(self, deliverable_id, when, actor):
        item = self.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        if item["approval_status"] != "approved":
            raise InvalidInput("Approve the asset before planning its publication.")
        if item["publishing_status"] == "published":
            raise InvalidInput("This asset is already marked as published.")
        stamp = when.replace(microsecond=0, tzinfo=None).isoformat() if isinstance(when, datetime) else str(when)
        with self.db.session() as conn:
            conn.execute(
                "UPDATE deliverables SET publishing_status='scheduled', scheduled_at=?, updated_at=?, updated_by=? WHERE id=?",
                (stamp, now_iso(), actor, deliverable_id),
            )
            write_audit(conn, actor, item["client_id"], "asset_scheduled", "deliverable", deliverable_id, stamp)
        return self.deliverable(deliverable_id)

    def unschedule(self, deliverable_id, actor):
        item = self.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        if item["publishing_status"] != "scheduled":
            raise InvalidInput("This asset is not scheduled.")
        with self.db.session() as conn:
            conn.execute(
                "UPDATE deliverables SET publishing_status='not_scheduled', scheduled_at='', updated_at=?, updated_by=? WHERE id=?",
                (now_iso(), actor, deliverable_id),
            )
            write_audit(conn, actor, item["client_id"], "asset_unscheduled", "deliverable", deliverable_id)
        return self.deliverable(deliverable_id)

    def mark_published(self, deliverable_id, note, actor):
        item = self.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        if item["approval_status"] != "approved":
            raise InvalidInput("Only approved assets can be recorded as published.")
        with self.db.session() as conn:
            conn.execute(
                "UPDATE deliverables SET publishing_status='published', published_at=?, publish_note=?, updated_at=?, updated_by=? WHERE id=?",
                (now_iso(), note.strip(), now_iso(), actor, deliverable_id),
            )
            write_audit(conn, actor, item["client_id"], "asset_published_manually", "deliverable", deliverable_id, note.strip())
        return self.deliverable(deliverable_id)

    def stats(self, client_id):
        row = self.db.one(
            "SELECT COUNT(DISTINCT root_id) AS packages, SUM(CASE WHEN quality='passed' THEN 1 ELSE 0 END) AS passed FROM packages WHERE client_id=?",
            (client_id,),
        )
        deliverables = self.db.one(
            "SELECT SUM(CASE WHEN approval_status='approved' THEN 1 ELSE 0 END) AS approved, COUNT(*) AS total, "
            "SUM(CASE WHEN publishing_status='published' THEN 1 ELSE 0 END) AS published, "
            "SUM(CASE WHEN approval_status IN ('pending_approval','needs_review') THEN 1 ELSE 0 END) AS pending "
            "FROM deliverables d JOIN packages p ON p.id=d.package_id WHERE d.client_id=? AND "
            "(p.selected=1 OR d.publishing_status IN ('scheduled','published'))",
            (client_id,),
        )
        return {
            "packages": row["packages"] or 0,
            "passed_packages": row["passed"] or 0,
            "approved": deliverables["approved"] or 0,
            "total": deliverables["total"] or 0,
            "published": deliverables["published"] or 0,
            "pending": deliverables["pending"] or 0,
        }
