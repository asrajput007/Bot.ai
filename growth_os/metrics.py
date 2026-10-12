import json
import threading
from datetime import datetime, timedelta, timezone
from statistics import mean

_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


class RunStore:
    def __init__(self, data_dir):
        self._dir = data_dir
        self._runs = data_dir / "runs.jsonl"
        self._artifacts = data_dir / "artifacts"

    def _ensure(self):
        self._artifacts.mkdir(parents=True, exist_ok=True)

    def append(self, record, artifact=None):
        with _LOCK:
            self._ensure()
            with self._runs.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if artifact is not None:
                path = self._artifacts / f"{record['run_id']}.json"
                path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    def load(self):
        if not self._runs.exists():
            return []
        records = []
        with self._runs.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def artifact(self, run_id):
        path = self._artifacts / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def runs_today(self, client_id):
        today = _now().date().isoformat()
        return sum(
            1
            for record in self.load()
            if record["client_id"] == client_id
            and record["ts"][:10] == today
            and record["status"] != "blocked"
        )


PIPELINE_VERSION = "growth-os-3-stage-v2"


def build_record(run_id, user, client, state, total_seconds, settings, error=None, kind="generate", campaign_id=""):
    usage_log = state.get("usage_log", [])
    input_tokens = sum(item["input_tokens"] for item in usage_log)
    output_tokens = sum(item["output_tokens"] for item in usage_log)
    cost = (
        input_tokens * settings.price_in_per_million + output_tokens * settings.price_out_per_million
    ) / 1_000_000
    rounds = state.get("rounds", [])
    final_scores = rounds[-1]["scores"].values() if rounds else []
    stage_seconds = {}
    for item in usage_log:
        stage_seconds[item["stage"]] = round(stage_seconds.get(item["stage"], 0.0) + item["seconds"], 3)
    assets = state.get("assets") or {}
    status = "failed" if error else state.get("status", "failed")
    completed = _now()
    started = completed - timedelta(seconds=total_seconds)
    return {
        "run_id": run_id,
        "ts": completed.isoformat(),
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "kind": kind,
        "user": user,
        "client_id": client.id if client else state.get("client_id", ""),
        "client_name": client.name if client else "",
        "campaign_id": campaign_id,
        "brief": state.get("brief", ""),
        "model": settings.model_label,
        "pipeline_version": PIPELINE_VERSION,
        "status": status,
        "error": error or state.get("reason", ""),
        "revisions": state.get("revision", 0),
        "first_pass": bool(rounds and rounds[0]["passed"]),
        "avg_score": round(mean(final_scores), 2) if final_scores else 0.0,
        "min_score": min(final_scores) if final_scores else 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "latency_s": round(total_seconds, 3),
        "llm_seconds": round(sum(stage_seconds.values()), 3),
        "stage_seconds": stage_seconds,
        "emails": len(assets.get("emails", [])),
        "posts": len(assets.get("social_posts", [])),
        "ctas": len(assets.get("ctas", [])),
        "guardrail_flags": len(state.get("guardrail_flags", [])),
        "package_id": "",
    }


def manual_minutes(record, settings):
    return (
        settings.minutes_manual_draft
        + record["emails"] * settings.minutes_manual_email
        + record["posts"] * settings.minutes_manual_post
        + record["ctas"] * settings.minutes_manual_cta
    )


def summarise(records, settings):
    total = len(records)
    completed = [r for r in records if r["status"] == "completed"]
    generated = [r for r in records if r["status"] in ("completed", "escalated")]
    saved_minutes = sum(max(manual_minutes(r, settings) - settings.minutes_human_review, 0) for r in completed)
    hours_saved = saved_minutes / 60
    value = hours_saved * settings.hourly_rate
    cost = sum(r["cost_usd"] for r in records)
    assets = sum(r["emails"] + r["posts"] + r["ctas"] for r in completed)
    latencies = [r["latency_s"] for r in generated]
    clients = {}
    users = {}
    for record in records:
        entry = clients.setdefault(
            record["client_id"],
            {"client": record["client_name"] or record["client_id"], "runs": 0, "completed": 0, "escalated": 0, "cost_usd": 0.0},
        )
        entry["runs"] += 1
        entry["completed"] += record["status"] == "completed"
        entry["escalated"] += record["status"] == "escalated"
        entry["cost_usd"] = round(entry["cost_usd"] + record["cost_usd"], 6)
        users[record["user"]] = users.get(record["user"], 0) + 1
    usage = {
        "runs": total,
        "completed": len(completed),
        "escalated": sum(r["status"] == "escalated" for r in records),
        "blocked": sum(r["status"] == "blocked" for r in records),
        "failed": sum(r["status"] == "failed" for r in records),
        "active_clients": len(clients),
        "target_clients": settings.target_clients,
        "assets_delivered": assets,
        "first_pass_rate": round(sum(r["first_pass"] for r in generated) / len(generated), 3) if generated else 0.0,
        "avg_revisions": round(mean(r["revisions"] for r in generated), 2) if generated else 0.0,
        "avg_judge_score": round(mean(r["avg_score"] for r in generated), 2) if generated else 0.0,
        "guardrail_flags": sum(r["guardrail_flags"] for r in records),
        "p50_latency_s": round(_percentile(latencies, 0.5), 1),
        "p95_latency_s": round(_percentile(latencies, 0.95), 1),
        "total_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in records),
    }
    impact = {
        "hours_saved": round(hours_saved, 1),
        "value_usd": round(value, 2),
        "ai_cost_usd": round(cost, 4),
        "cost_per_run_usd": round(cost / total, 4) if total else 0.0,
        "cost_per_asset_usd": round(cost / assets, 4) if assets else 0.0,
        "roi_multiple": round(value / cost, 1) if cost else 0.0,
        "founder_touch_minutes": 0,
        "automation_rate": round(len(completed) / total, 3) if total else 0.0,
    }
    return {
        "usage": usage,
        "impact": impact,
        "by_client": sorted(clients.values(), key=lambda item: -item["runs"]),
        "by_user": [{"user": user, "runs": count} for user, count in sorted(users.items(), key=lambda kv: -kv[1])],
    }
