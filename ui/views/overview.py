from datetime import date, timedelta

import streamlit as st

from growth_os import analytics
from ui import components as ui
from ui import nav
from ui.context import current


def _recommended_actions(cards, content, overdue, campaigns, records):
    actions = []
    if content["pending"]:
        actions.append(("studio", f"Review {content['pending']} asset(s) awaiting approval", ":material/fact_check:"))
    if overdue:
        actions.append(("leads", f"Follow up with {len(overdue)} lead(s) past their follow-up date", ":material/notification_important:"))
    stalled = [card for card in cards if card["meta"]["status"] == "onboarding" and card["current_step"]]
    if stalled:
        card = stalled[0]
        actions.append(("clients", f"Continue onboarding {card['profile'].name}: {card['current_step']['label']}", ":material/groups:"))
    attention = [r for r in records if r["status"] in ("failed", "escalated", "blocked")][:1]
    if attention:
        actions.append(("history", f"Investigate the latest {ui.label_for(attention[0]['status']).lower()} run for {attention[0]['client_name']}", ":material/error:"))
    if not campaigns:
        actions.append(("campaigns", "Create the first campaign for an onboarded client", ":material/campaign:"))
    if not records:
        actions.append(("studio", "Run the pipeline for a client to produce the first assets", ":material/auto_awesome:"))
    return actions


def render():
    ctx = current()
    svc = ctx.service
    cards = svc.client_cards(ctx.user)
    deliverables = svc.deliverables(ctx.user)
    leads = svc.leads(ctx.user)
    campaigns = svc.campaigns(ctx.user)
    records = list(reversed(svc.run_records(ctx.user)))
    events = svc.activity(ctx.user, limit=12)
    names = {card["profile"].id: card["profile"].name for card in cards}
    content = analytics.content_metrics(deliverables)
    lead_stats = analytics.lead_metrics(leads)
    overdue, upcoming = analytics.follow_ups(leads)
    active = sum(1 for card in cards if card["meta"]["status"] == "active")
    onboarding = sum(1 for card in cards if card["meta"]["status"] == "onboarding")
    posts = sum(1 for item in deliverables if item["kind"] == "social" and item["publishing_status"] == "published")
    conversion = lead_stats["conversion_rate"] if lead_stats["total"] >= 5 else None
    ui.kpi_grid(
        [
            {"label": "Active clients", "value": active, "caption": f"{onboarding} onboarding of {len(cards)}", "accent": True},
            {"label": "Content assets created", "value": content["total"], "caption": "Current working versions"},
            {"label": "Awaiting approval", "value": content["pending"], "caption": f"{content['changes_requested']} with changes requested"},
            {"label": "Posts published", "value": posts, "caption": "Social posts recorded as published manually"},
            {"label": "Leads generated", "value": lead_stats["total"], "caption": f"{len(overdue)} overdue follow-up(s)"},
            {"label": "Campaign conversion", "value": None if conversion is None else f"{conversion:.0%}", "caption": "Shown once at least 5 leads exist"},
        ]
    )
    with st.container(border=True):
        st.markdown("#### Recommended next actions")
        actions = _recommended_actions(cards, content, overdue, campaigns, records)
        if not actions:
            st.success("Nothing needs attention right now.", icon="✅")
        for page, label, icon in actions:
            nav.link(page, label, icon)
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            st.markdown("#### Pending content approvals")
            pending = [item for item in deliverables if item["approval_status"] in ("pending_approval", "needs_review", "changes_requested")][:6]
            if not pending:
                st.caption("No assets are waiting for approval.")
            for item in pending:
                ui.render(
                    f'<div style="display:flex;justify-content:space-between;gap:8px;margin:6px 0"><span>{ui.esc(names.get(item["client_id"], ""))} · {ui.esc(item["label"])}</span>'
                    f'{ui.status_badge(item["approval_status"])}</div>'
                )
            nav.link("studio", "Open Content Studio", ":material/auto_awesome:")
    with right:
        with st.container(border=True):
            st.markdown("#### Upcoming publishing schedule")
            horizon = (date.today() + timedelta(days=14)).isoformat()
            upcoming_items = sorted(
                (item for item in deliverables if item["publishing_status"] == "scheduled" and item["scheduled_at"][:10] >= date.today().isoformat()),
                key=lambda item: item["scheduled_at"],
            )
            if not upcoming_items:
                st.caption("Nothing is planned. Approve assets and plan their publication.")
            for item in upcoming_items[:6]:
                ui.render(
                    f'<div style="display:flex;justify-content:space-between;gap:8px;margin:6px 0"><span>{ui.esc(ui.fmt_dt(item["scheduled_at"]))} · {ui.esc(names.get(item["client_id"], ""))} · {ui.esc(item["label"])}</span>'
                    f'{ui.badge("Within 14 days", "info") if item["scheduled_at"][:10] <= horizon else ""}</div>'
                )
            nav.link("calendar", "Open Content Calendar", ":material/calendar_month:")
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            st.markdown("#### Campaign performance")
            if not campaigns:
                st.caption("No campaigns yet.")
            else:
                rows = []
                for campaign in campaigns[:8]:
                    c_items = [item for item in deliverables if item["campaign_id"] == campaign["id"]]
                    c_leads = [lead for lead in leads if lead["campaign_id"] == campaign["id"]]
                    rows.append({"Campaign": campaign["name"], "Client": names.get(campaign["client_id"], ""), "Status": ui.label_for(campaign["status"]), "Assets": len(c_items), "Leads": len(c_leads)})
                st.dataframe(rows, hide_index=True, width="stretch")
            nav.link("campaigns", "Open Campaigns", ":material/campaign:")
    with right:
        with st.container(border=True):
            st.markdown("#### Client onboarding progress")
            for card in sorted(cards, key=lambda c: c["done"])[:8]:
                st.progress(card["done"] / card["total"], text=f"{card['profile'].name}: {card['done']}/{card['total']}")
            nav.link("clients", "Open Clients", ":material/groups:")
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            st.markdown("#### Recent AI pipeline executions")
            if not records:
                st.caption("No pipeline runs yet.")
            for record in records[:6]:
                ui.render(
                    f'<div style="display:flex;justify-content:space-between;gap:8px;margin:6px 0"><span>{ui.esc(record["client_name"])} · {ui.esc(ui.fmt_dt(record["ts"]))} · score {record["avg_score"] or "n/a"}</span>'
                    f'{ui.status_badge(record["status"])}</div>'
                )
            nav.link("history", "Open Run History", ":material/history:")
    with right:
        with st.container(border=True):
            st.markdown("#### Needs attention")
            problems = [r for r in records if r["status"] in ("failed", "blocked", "escalated")][:5]
            integrations = [item for item in svc.integrations() if not item["configured"]]
            if not problems and not overdue:
                st.caption("No failed runs or overdue follow-ups.")
            for record in problems:
                ui.render(
                    f'<div style="margin:6px 0">{ui.status_badge(record["status"])} {ui.esc(record["client_name"])}: {ui.esc((record["error"] or "")[:110])}</div>'
                )
            for lead in overdue[:3]:
                ui.render(f'<div style="margin:6px 0">{ui.badge("Follow-up overdue", "warning")} {ui.esc(lead["name"])} (due {ui.esc(ui.fmt_date(lead["next_follow_up"]))})</div>')
            st.caption(f"{len(integrations)} integration(s) not configured. See Settings.")
    with st.container(border=True):
        st.markdown("#### Recent activity")
        if not events:
            st.caption("Actions across your clients are recorded here.")
        for event in events:
            st.caption(f"{ui.fmt_dt(event['ts'])} · {event['actor']} · {event['action'].replace('_', ' ')} · {names.get(event['client_id'], '')} {event['detail']}")
