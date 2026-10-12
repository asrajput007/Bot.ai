import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from growth_os import analytics
from growth_os.crm import LEAD_STATUSES
from ui import components as ui
from ui.context import client_scope, current


def _range(scope):
    today = date.today()
    chosen = st.date_input("Date range", (today - timedelta(days=30), today), key=f"{scope}-range", max_value=today)
    if isinstance(chosen, (list, tuple)):
        if len(chosen) == 2:
            return chosen[0], chosen[1]
        if len(chosen) == 1:
            return chosen[0], today
    return today - timedelta(days=30), today


def _frame(rows, columns):
    return pd.DataFrame(rows, columns=columns)


def _pct(value):
    return None if value is None else f"{value:.0%}"


def _outcomes(ctx, client_id, start, end, scope):
    svc = ctx.service
    deliverables = svc.deliverables(ctx.user, client_id)
    leads = svc.leads(ctx.user, client_id)
    campaigns = svc.campaigns(ctx.user, client_id)
    created = [item for item in deliverables if analytics.in_range(item["created_at"], start, end)]
    new_leads = [lead for lead in leads if analytics.in_range(lead["created_at"], start, end)]
    content = analytics.content_metrics(deliverables)
    lead_stats = analytics.lead_metrics(leads)
    ui.kpi_grid(
        [
            {"label": "Content generated", "value": len(created), "caption": "Assets created in the date range", "accent": True},
            {"label": "Content approved", "value": content["approved"], "caption": "All time, current working versions"},
            {"label": "Content published", "value": content["published"], "caption": "Recorded manually"},
            {"label": "Publishing completion", "value": _pct(content["publish_rate"]), "caption": "Published of approved"},
            {"label": "Engagement rate", "value": None, "caption": "Needs LinkedIn, X and email analytics integrations"},
            {"label": "Leads generated", "value": len(new_leads), "caption": "Added in the date range"},
            {"label": "Lead response rate", "value": _pct(lead_stats["response_rate"]), "caption": "Replied or beyond, of leads contacted"},
            {"label": "Meetings booked", "value": lead_stats["meetings"], "caption": "Currently in that stage"},
            {"label": "Conversion rate", "value": _pct(lead_stats["conversion_rate"]), "caption": "Converted of all leads"},
        ]
    )
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Content production over time**")
        series = analytics.series_by_day(created, "created_at", start, end)
        if series:
            st.bar_chart(_frame(series, ["date", "count"]), x="date", y="count", height=260)
        else:
            st.caption("No assets were created in this date range.")
    with right:
        st.markdown("**Lead funnel**")
        if leads:
            funnel = _frame(analytics.lead_funnel(leads), ["stage", "leads"])
            funnel["stage"] = pd.Categorical([ui.label_for(stage) for stage in funnel["stage"]], categories=[ui.label_for(stage) for stage in LEAD_STATUSES], ordered=True)
            st.bar_chart(funnel, x="stage", y="leads", height=260)
        else:
            st.caption("No leads recorded yet.")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Channel performance (production, not engagement)**")
        channel_rows = {}
        for item in deliverables:
            if item["kind"] == "cta":
                continue
            row = channel_rows.setdefault(item["channel"], {"channel": item["channel"], "created": 0, "approved": 0, "published": 0})
            row["created"] += 1
            row["approved"] += item["approval_status"] == "approved"
            row["published"] += item["publishing_status"] == "published"
        if channel_rows:
            st.dataframe(list(channel_rows.values()), hide_index=True, width="stretch")
        else:
            st.caption("No assets yet.")
    with right:
        st.markdown("**Conversion trend**")
        converted = [lead for lead in leads if lead["status"] == "converted"]
        trend = analytics.series_by_day(converted, "updated_at", start, end)
        if trend:
            st.line_chart(_frame(trend, ["date", "count"]), x="date", y="count", height=220)
        else:
            st.caption("No conversions recorded in this range.")
    st.markdown("**Campaign performance**")
    names = {client.id: client.name for client in ctx.clients}
    rows = []
    for campaign in campaigns:
        c_items = [item for item in deliverables if item["campaign_id"] == campaign["id"]]
        c_leads = [lead for lead in leads if lead["campaign_id"] == campaign["id"]]
        rows.append(
            {
                "Campaign": campaign["name"], "Client": names.get(campaign["client_id"], ""), "Status": ui.label_for(campaign["status"]),
                "Assets": len(c_items), "Approved": sum(i["approval_status"] == "approved" for i in c_items),
                "Published": sum(i["publishing_status"] == "published" for i in c_items), "Leads": len(c_leads),
                "Converted": sum(l["status"] == "converted" for l in c_leads),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No campaigns yet.")
    return deliverables, leads, campaigns


def _usage(ctx, client_id, start, end, scope):
    records = [r for r in ctx.service.run_records(ctx.user, client_id) if analytics.in_range(r["ts"], start, end)]
    if not records:
        ui.empty_state("No pipeline runs in this range", "Run the pipeline in Content Studio or widen the date range.")
        return records
    done = [r for r in records if r["status"] in ("completed", "escalated")]
    usage = ctx.service.summary(ctx.user, client_id)["usage"]
    ui.kpi_grid(
        [
            {"label": "Runs", "value": len(records), "caption": f"{sum(r['status'] == 'completed' for r in records)} completed, {sum(r['status'] == 'escalated' for r in records)} escalated"},
            {"label": "First-pass approval", "value": _pct(sum(r["first_pass"] for r in done) / len(done)) if done else None, "caption": "Judge approved the first draft"},
            {"label": "Avg judge score", "value": round(sum(r["avg_score"] for r in done) / len(done), 2) if done else None, "caption": "Out of 10"},
            {"label": "Blocked or failed", "value": sum(r["status"] in ("blocked", "failed") for r in records)},
            {"label": "p50 / p95 end-to-end latency", "value": f"{usage['p50_latency_s']}s / {usage['p95_latency_s']}s", "caption": "All time, selected clients"},
            {"label": "Tokens used", "value": f"{sum(r['input_tokens'] + r['output_tokens'] for r in records):,}"},
        ]
    )
    frame = pd.DataFrame(
        [{"date": r["ts"][:10], "score": r["avg_score"], "cost": r["cost_usd"]} for r in done]
    ).groupby("date", as_index=False).agg(score=("score", "mean"), cost=("cost", "sum"))
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Average judge score by day**")
        st.line_chart(frame, x="date", y="score", height=240)
    with right:
        st.markdown("**Estimated AI cost by day (USD)**")
        st.bar_chart(frame, x="date", y="cost", height=240)
    names = {client.id: client.name for client in ctx.clients}
    by_client = pd.DataFrame([{"client": names.get(r["client_id"], r["client_id"]), "runs": 1} for r in records]).groupby("client", as_index=False).sum()
    st.markdown("**Client activity (pipeline runs)**")
    st.bar_chart(by_client, x="client", y="runs", height=240)
    return records


def _roi(ctx, client_id):
    summary = ctx.service.summary(ctx.user, client_id)
    impact, usage = summary["impact"], summary["usage"]
    if not usage["runs"]:
        ui.empty_state("No runs yet", "ROI is computed from completed pipeline runs.")
        return
    ui.kpi_grid(
        [
            {"label": "Hours saved (estimate)", "value": impact["hours_saved"], "accent": True},
            {"label": "Value created (estimate)", "value": f"${impact['value_usd']:,.0f}"},
            {"label": "AI cost (estimate)", "value": f"${impact['ai_cost_usd']:.4f}", "caption": "From reported token usage and configured list prices"},
            {"label": "ROI multiple (estimate)", "value": f"{impact['roi_multiple']:,.0f}x"},
            {"label": "Cost per asset", "value": f"${impact['cost_per_asset_usd']:.4f}"},
            {"label": "Automation rate", "value": _pct(impact["automation_rate"]), "caption": "Runs completed without escalation"},
        ]
    )
    s = ctx.service.settings
    st.caption(
        f"These figures are assumption-based, not measured outcomes. Manual effort is assumed at {s.minutes_manual_draft:g} min per long-form piece, "
        f"{s.minutes_manual_email:g} per email, {s.minutes_manual_post:g} per social post and {s.minutes_manual_cta:g} per CTA, minus "
        f"{s.minutes_human_review:g} min of human review, at ${s.hourly_rate:g}/hour. Change them with the ROI_* variables in .env."
    )
    st.dataframe(summary["by_client"], hide_index=True, width="stretch")


def body(ctx, client_id, scope):
    start, end = _range(scope)
    outcomes, usage, roi = st.tabs(["Business outcomes", "Content and AI usage", "ROI model"])
    with outcomes:
        deliverables, leads, campaigns = _outcomes(ctx, client_id, start, end, scope)
    with usage:
        records = _usage(ctx, client_id, start, end, scope)
    with roi:
        _roi(ctx, client_id)
    ui.page_section("Reports", "Exports respect your client access and the selected scope.")
    columns = st.columns(4)
    with columns[0]:
        ui.csv_button("Pipeline runs (CSV)", [{k: v for k, v in r.items() if k != "stage_seconds"} for r in records], "runs.csv", f"{scope}-runs")
    with columns[1]:
        ui.csv_button("Content assets (CSV)", [{"client_id": d["client_id"], "asset": d["label"], "channel": d["channel"], "approval": d["approval_status"], "publishing": d["publishing_status"], "planned_for": d["scheduled_at"], "created_at": d["created_at"]} for d in deliverables], "content.csv", f"{scope}-content")
    with columns[2]:
        ui.csv_button("Leads (CSV)", [{k: v for k, v in lead.items() if k != "notes"} for lead in leads], "leads.csv", f"{scope}-leads")
    with columns[3]:
        summary = ctx.service.summary(ctx.user, client_id)
        st.download_button("Summary (JSON)", json.dumps(summary, indent=2), file_name="summary.json", mime="application/json", key=f"{scope}-summary", icon=":material/download:", width="stretch")
    st.caption("PDF client reports are not implemented. CSV and JSON exports are available above.")


def render():
    ctx = current()
    client_id = client_scope(ctx, "analytics")
    body(ctx, client_id, "ana")
