from datetime import date

import streamlit as st

from growth_os import analytics
from growth_os.crm import LEAD_STATUSES
from ui import components as ui
from ui.context import client_scope, current

ACTIVITY_KINDS = {
    "note": "Note",
    "email_sent": "Email sent (manual)",
    "linkedin_message": "LinkedIn message (manual)",
    "call": "Call",
    "meeting": "Meeting",
}


@st.dialog("Add lead")
def _add_dialog(ctx, client_id, campaign_names):
    st.caption("Leads are recorded manually. No CRM or enrichment integration is configured.")
    with st.form("add-lead-form"):
        name = st.text_input("Prospect name")
        a, b = st.columns(2)
        company = a.text_input("Company")
        role = b.text_input("Role")
        email = st.text_input("Business email")
        c, d = st.columns(2)
        source = c.text_input("Source", placeholder="Outreach email, LinkedIn, referral")
        campaign = d.selectbox("Campaign", [""] + list(campaign_names), format_func=lambda value: campaign_names.get(value, "None"))
        owners = [""] + ctx.service.operators()
        e, f = st.columns(2)
        owner = e.selectbox("Assigned owner", owners, index=owners.index(ctx.user), format_func=lambda value: value or "Unassigned")
        follow_up = f.date_input("Next follow-up", value=None)
        notes = st.text_area("Notes", height=80)
        if st.form_submit_button("Add lead", type="primary"):
            ok, lead = ui.attempt(
                ctx.service.create_lead, ctx.user, client_id, name=name, company=company, role=role, email=email,
                source=source, campaign_id=campaign, owner=owner, notes=notes,
                next_follow_up=follow_up.isoformat() if follow_up else "", success="Lead added",
            )
            if ok:
                st.rerun()


def _lead_detail(ctx, lead, client_names, campaign_names, scope):
    svc, user = ctx.service, ctx.user
    key = f"{scope}-{lead['id']}"
    with st.container(border=True):
        head, state = st.columns([3, 2])
        head.markdown(f"### {lead['name']}")
        head.caption(f"{lead['role'] or 'Role not set'} at {lead['company'] or 'company not set'} · {client_names.get(lead['client_id'], '')}")
        with state:
            ui.render(ui.badges([ui.status_badge(lead["status"])]))
        left, right = st.columns(2, gap="large")
        with left:
            status = st.selectbox("Pipeline stage", LEAD_STATUSES, index=LEAD_STATUSES.index(lead["status"]), format_func=ui.label_for, key=f"{key}-status")
            if st.button("Update stage", key=f"{key}-status-save", disabled=status == lead["status"]):
                ok, _ = ui.attempt(svc.set_lead_status, user, lead["id"], status, success=f"Moved to {ui.label_for(status)}")
                if ok:
                    st.rerun()
            with st.form(f"{key}-edit"):
                name = st.text_input("Name", lead["name"])
                a, b = st.columns(2)
                company = a.text_input("Company", lead["company"])
                role = b.text_input("Role", lead["role"])
                email = st.text_input("Business email", lead["email"])
                c, d = st.columns(2)
                source = c.text_input("Source", lead["source"])
                options = [""] + list(campaign_names)
                campaign = d.selectbox("Campaign", options, index=options.index(lead["campaign_id"]) if lead["campaign_id"] in options else 0, format_func=lambda value: campaign_names.get(value, "None"))
                owners = [""] + svc.operators()
                e, f = st.columns(2)
                owner = e.selectbox("Owner", owners, index=owners.index(lead["owner"]) if lead["owner"] in owners else 0, format_func=lambda value: value or "Unassigned")
                follow = f.date_input("Next follow-up", value=date.fromisoformat(lead["next_follow_up"]) if lead["next_follow_up"] else None)
                notes = st.text_area("Notes", lead["notes"], height=90)
                if st.form_submit_button("Save lead", type="primary"):
                    ok, _ = ui.attempt(
                        svc.update_lead, user, lead["id"], name=name, company=company, role=role, email=email, source=source,
                        campaign_id=campaign, owner=owner, notes=notes, next_follow_up=follow.isoformat() if follow else "",
                        success="Lead saved",
                    )
                    if ok:
                        st.rerun()
            if ui.confirm_action("Delete lead", f"{key}-delete", f"Delete {lead['name']}?", "The lead and its activity log are permanently removed.", "Delete lead", icon=":material/delete:"):
                ok, _ = ui.attempt(svc.delete_lead, user, lead["id"], success="Lead deleted")
                if ok:
                    st.rerun()
        with right:
            st.markdown("**Outreach**")
            emails = svc.deliverables(user, lead["client_id"], kind="email", approval="approved")
            if emails:
                chosen = st.selectbox("Approved email", [item["id"] for item in emails], format_func=lambda value: next(f"{i['label']} · {i['content'].get('subject', '')[:50]}" for i in emails if i["id"] == value), key=f"{key}-email")
                email_item = next(item for item in emails if item["id"] == chosen)
                with st.popover("Copy email", icon=":material/content_copy:", width="stretch"):
                    st.code(email_item["content"].get("subject", ""), language=None, wrap_lines=True)
                    st.code(email_item["content"].get("body", ""), language=None, wrap_lines=True)
                st.caption("No sending integration is configured. Copy the email, send it yourself, then log it.")
                if st.button("Log as sent manually", key=f"{key}-log-email", icon=":material/outgoing_mail:"):
                    ok, _ = ui.attempt(svc.log_lead_activity, user, lead["id"], "email_sent", f"Sent: {email_item['content'].get('subject', '')}", email_item["id"])
                    if ok:
                        if lead["status"] == "new":
                            svc.set_lead_status(user, lead["id"], "contacted")
                        ui.notify("Outreach logged")
                        st.rerun()
            else:
                st.info("Approve an email asset for this client in Content Studio to use it for outreach.")
            st.markdown("**Log an interaction**")
            kind = st.selectbox("Type", list(ACTIVITY_KINDS), format_func=ACTIVITY_KINDS.get, key=f"{key}-kind")
            note = st.text_area("Note", key=f"{key}-note", height=80)
            if st.button("Log interaction", key=f"{key}-log", type="primary"):
                ok, _ = ui.attempt(svc.log_lead_activity, user, lead["id"], kind, note, success="Interaction logged")
                if ok:
                    st.rerun()
            st.markdown("**Activity**")
            for row in svc.lead_activity(user, lead["id"])[:12]:
                st.caption(f"{ui.fmt_dt(row['ts'])} · {row['kind'].replace('_', ' ')} · {row['note']} ({row['actor']})")


def body(ctx, client_id, scope):
    svc = ctx.service
    all_leads = svc.leads(ctx.user, client_id)
    campaigns = svc.campaigns(ctx.user, client_id)
    campaign_names = {item["id"]: item["name"] for item in campaigns}
    client_names = {client.id: client.name for client in ctx.clients}
    metrics = analytics.lead_metrics(all_leads)
    overdue, upcoming = analytics.follow_ups(all_leads)
    ui.kpi_grid(
        [
            {"label": "Leads", "value": metrics["total"], "caption": "Recorded manually", "accent": True},
            {"label": "Response rate", "value": None if metrics["response_rate"] is None else f"{metrics['response_rate']:.0%}", "caption": "Replied or beyond, of leads contacted"},
            {"label": "Meetings booked", "value": metrics["meetings"], "caption": "Currently in that stage"},
            {"label": "Converted", "value": metrics["converted"], "caption": "None yet" if not metrics["converted"] else ""},
            {"label": "Overdue follow-ups", "value": len(overdue), "caption": f"{len(upcoming)} upcoming"},
        ]
    )
    funnel = analytics.lead_funnel(all_leads)
    ui.render(
        '<div class="go-grid">'
        + "".join(
            f'<div class="go-kpi"><div class="label">{ui.esc(ui.label_for(row["stage"]))}</div><div class="value">{row["leads"]}</div></div>'
            for row in funnel
        )
        + "</div>"
    )
    controls = st.columns([3, 2, 2, 2, 2], vertical_alignment="bottom")
    search = controls[0].text_input("Search leads", placeholder="Name, company or email", key=f"{scope}-search")
    status = controls[1].selectbox("Stage", [""] + list(LEAD_STATUSES), format_func=lambda value: ui.label_for(value) if value else "All stages", key=f"{scope}-stage")
    campaign = controls[2].selectbox("Campaign", [""] + list(campaign_names), format_func=lambda value: campaign_names.get(value, "All campaigns"), key=f"{scope}-campaign")
    owners = [""] + svc.operators()
    owner = controls[3].selectbox("Owner", owners, format_func=lambda value: value or "All owners", key=f"{scope}-owner")
    target_client = client_id
    if controls[4].button("Add lead", icon=":material/person_add:", type="primary", width="stretch", key=f"{scope}-add"):
        if target_client:
            _add_dialog(ctx, target_client, campaign_names)
        else:
            st.warning("Select a specific client above before adding a lead.", icon="⚠️")
    leads = svc.leads(ctx.user, client_id, status=status or None, campaign_id=campaign or None, owner=owner or None, search=search.strip().lower())
    if not all_leads:
        ui.empty_state("No leads recorded", "Add prospects as you contact them. Outreach assets approved in Content Studio can be copied and logged here.")
        return
    if overdue:
        with st.expander(f"Overdue follow-ups ({len(overdue)})", expanded=True):
            for lead in overdue[:8]:
                st.markdown(f"- **{lead['name']}** ({client_names.get(lead['client_id'], '')}): due {ui.fmt_date(lead['next_follow_up'])}")
    today = date.today().isoformat()
    rows = [
        {
            "Prospect": lead["name"],
            "Company": lead["company"],
            "Role": lead["role"],
            "Email": lead["email"],
            "Stage": ui.label_for(lead["status"]),
            "Client": client_names.get(lead["client_id"], ""),
            "Campaign": campaign_names.get(lead["campaign_id"], ""),
            "Owner": lead["owner"],
            "Last interaction": ui.fmt_dt(lead["last_interaction"]) if lead["last_interaction"] else "None",
            "Next follow-up": (("Overdue: " if lead["next_follow_up"] < today and lead["status"] not in ("converted", "disqualified") else "") + ui.fmt_date(lead["next_follow_up"])) if lead["next_follow_up"] else "",
        }
        for lead in leads
    ]
    if not leads:
        ui.empty_state("No leads match these filters", "Clear a filter or search term.")
        return
    selection = st.dataframe(rows, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=f"{scope}-table")
    ui.csv_button("Export leads (CSV)", rows, "leads.csv", f"{scope}-export")
    picked = selection.selection.rows if selection and selection.selection else []
    if picked and picked[0] < len(leads):
        _lead_detail(ctx, leads[picked[0]], client_names, campaign_names, scope)
    else:
        st.caption("Select a row to open the lead, move it through the pipeline, log outreach or edit its details.")


def render():
    ctx = current()
    client_id = client_scope(ctx, "leads")
    body(ctx, client_id, "leads")
