from collections import Counter
from datetime import date, datetime

from .crm import LEAD_STATUSES, REACHED, RESPONDED


def _day(value):
    return str(value)[:10]


def in_range(value, start, end):
    if not value:
        return False
    day = _day(value)
    if start and day < start.isoformat():
        return False
    if end and day > end.isoformat():
        return False
    return True


def content_metrics(deliverables):
    total = len(deliverables)
    count = Counter(item["approval_status"] for item in deliverables)
    published = sum(1 for item in deliverables if item["publishing_status"] == "published")
    scheduled = sum(1 for item in deliverables if item["publishing_status"] == "scheduled")
    approved = count.get("approved", 0)
    return {
        "total": total,
        "approved": approved,
        "pending": count.get("pending_approval", 0) + count.get("needs_review", 0),
        "changes_requested": count.get("changes_requested", 0),
        "scheduled": scheduled,
        "published": published,
        "publish_rate": round(published / approved, 3) if approved else None,
    }


def lead_metrics(leads):
    total = len(leads)
    reached = sum(1 for lead in leads if lead["status"] in REACHED)
    responded = sum(1 for lead in leads if lead["status"] in RESPONDED)
    return {
        "total": total,
        "reached": reached,
        "responded": responded,
        "response_rate": round(responded / reached, 3) if reached else None,
        "meetings": sum(1 for lead in leads if lead["status"] == "meeting_booked"),
        "converted": sum(1 for lead in leads if lead["status"] == "converted"),
        "conversion_rate": round(sum(1 for lead in leads if lead["status"] == "converted") / total, 3) if total else None,
    }


def lead_funnel(leads):
    counts = Counter(lead["status"] for lead in leads)
    return [{"stage": status, "leads": counts.get(status, 0)} for status in LEAD_STATUSES]


def series_by_day(rows, field, start=None, end=None):
    counts = Counter(_day(row[field]) for row in rows if in_range(row.get(field), start, end))
    return [{"date": day, "count": counts[day]} for day in sorted(counts)]


def follow_ups(leads, today=None):
    today = (today or date.today()).isoformat()
    open_leads = [lead for lead in leads if lead["next_follow_up"] and lead["status"] not in ("converted", "disqualified")]
    overdue = sorted((lead for lead in open_leads if lead["next_follow_up"] < today), key=lambda lead: lead["next_follow_up"])
    upcoming = sorted((lead for lead in open_leads if lead["next_follow_up"] >= today), key=lambda lead: lead["next_follow_up"])
    return overdue, upcoming


def to_date(value):
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None
