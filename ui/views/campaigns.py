from datetime import date

import streamlit as st

from growth_os import analytics
from growth_os.crm import CAMPAIGN_STATUSES
from ui import assets_ui
from ui import components as ui
from ui.context import client_scope, current

CHANNELS = ["linkedin", "x", "email"]


def _open(scope, campaign_id):
    st.session_state[f"{scope}-open"] = campaign_id


def _close(scope):
    st.session_state.pop(f"{scope}-open", None)


def _date_or_none(value):
    return date.fromisoformat(value) if value else None


@st.dialog("New campaign")
def _create_dialog(ctx, client_id, profile):
    with st.form("new-campaign-form"):
        name = st.text_input("Campaign name")
        objective = st.text_area("Campaign objective", height=80)
        audience = st.text_input("Target audience", value=profile.audience[:200])
        channels = st.multiselect("Channels", CHANNELS, default=[value for value in profile.channels if value in CHANNELS])
        a, b = st.columns(2)
        start = a.date_input("Start date", value=None)
        end = b.date_input("End date", value=None)
        lead_objective = st.text_input("Lead generation objective", placeholder="Book 10 discovery calls")
        owners = [""] + ctx.service.operators()
        owner = st.selectbox("Assigned owner", owners, index=owners.index(ctx.user), format_func=lambda value: value or "Unassigned")
        if st.form_submit_button("Create campaign", type="primary"):
            ok, created = ui.attempt(
                ctx.service.create_campaign, ctx.user, client_id, name=name, objective=objective, audience=audience,
                channels=channels, start_date=start.isoformat() if start else "", end_date=end.isoformat() if end else "",
                lead_objective=lead_objective, owner=owner, success="Campaign created",
            )
            if ok:
                st.rerun()


def _stats(ctx, campaign):
    items = ctx.service.deliverables(ctx.user, campaign["client_id"], campaign_id=campaign["id"])
    leads = ctx.service.leads(ctx.user, campaign["client_id"], campaign_id=campaign["id"])
    return items, leads, analytics.content_metrics(items), analytics.lead_metrics(leads)


def _card(ctx, campaign, client_names, scope):
    items, leads, content, lead_stats = _stats(ctx, campaign)
    with st.container(border=True):
        head, state = st.columns([3, 2])
        head.markdown(f"**{campaign['name']}**")
        head.caption(client_names.get(campaign["client_id"], ""))
        with state:
            ui.render(ui.badges([ui.status_badge(campaign["status"])]))
        ui.fields_grid(
            [
                ("Objective", campaign["objective"] or "Not set"),
                ("Dates", f"{ui.fmt_date(campaign['start_date'])} to {ui.fmt_date(campaign['end_date'])}"),
                ("Channels", ", ".join(campaign["channels"]) or "Not set"),
                ("Owner", campaign["owner"] or "Unassigned"),
                ("Assets", f"{content['total']} ({content['approved']} approved, {content['published']} published)"),
                ("Leads", f"{lead_stats['total']} ({lead_stats['converted']} converted)"),
            ]
        )
        st.button("Open campaign", key=f"{scope}-open-{campaign['id']}", on_click=_open, args=(scope, campaign["id"]), width="stretch", icon=":material/arrow_forward:")


def _detail(ctx, campaign, client_names, scope):
    svc = ctx.service
    items, leads, content, lead_stats = _stats(ctx, campaign)
    back, title = st.columns([1, 6], vertical_alignment="center")
    back.button("All campaigns", key=f"{scope}-back", on_click=_close, args=(scope,), icon=":material/arrow_back:", width="stretch")
    with title:
        ui.render(
            f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span style="font-size:1.35rem;font-weight:700">{ui.esc(campaign["name"])}</span>'
            f'{ui.status_badge(campaign["status"])}<span class="go-muted">{ui.esc(client_names.get(campaign["client_id"], ""))}</span></div>'
        )
    tabs = st.tabs(["Overview", "Strategy", "Assets", "Leads", "Schedule", "Analytics", "Activity"])
    key = f"{scope}-{campaign['id']}"
    with tabs[0]:
        with st.form(f"{key}-edit"):
            name = st.text_input("Campaign name", campaign["name"])
            objective = st.text_area("Objective", campaign["objective"], height=80)
            audience = st.text_input("Target audience", campaign["audience"])
            channels = st.multiselect("Channels", CHANNELS, default=[value for value in campaign["channels"] if value in CHANNELS])
            a, b, c = st.columns(3)
            start = a.date_input("Start date", _date_or_none(campaign["start_date"]))
            end = b.date_input("End date", _date_or_none(campaign["end_date"]))
            status = c.selectbox("Status", CAMPAIGN_STATUSES, index=CAMPAIGN_STATUSES.index(campaign["status"]), format_func=ui.label_for)
            lead_objective = st.text_input("Lead generation objective", campaign["lead_objective"])
            owners = [""] + svc.operators()
            owner = st.selectbox("Owner", owners, index=owners.index(campaign["owner"]) if campaign["owner"] in owners else 0, format_func=lambda value: value or "Unassigned")
            if st.form_submit_button("Save campaign", type="primary"):
                ok, _ = ui.attempt(
                    svc.update_campaign, ctx.user, campaign["id"], name=name, objective=objective, audience=audience,
                    channels=channels, start_date=start.isoformat() if start else "", end_date=end.isoformat() if end else "",
                    status=status, lead_objective=lead_objective, owner=owner, success="Campaign saved",
                )
                if ok:
                    st.rerun()
    profile = svc.profile(ctx.user, campaign["client_id"])
    with tabs[1]:
        strategies = [item for item in items if item["kind"] == "strategy"]
        if not strategies:
            ui.empty_state("No strategy attached", "Select this campaign in Content Studio when generating content.")
        for item in strategies:
            assets_ui.deliverable_card(ctx, item, f"{key}-strategy", {campaign["id"]: campaign["name"]}, profile, campaign["audience"])
    with tabs[2]:
        assets = [item for item in items if item["kind"] != "strategy"]
        if not assets:
            ui.empty_state("No assets yet", "Assets generated for this campaign appear here for approval.")
        for item in assets:
            assets_ui.deliverable_card(ctx, item, f"{key}-assets", {campaign["id"]: campaign["name"]}, profile, campaign["audience"])
    with tabs[3]:
        if not leads:
            ui.empty_state("No leads linked", "Link leads to this campaign on the Lead Generation page.")
        else:
            st.dataframe(
                [{"Prospect": lead["name"], "Company": lead["company"], "Stage": ui.label_for(lead["status"]), "Owner": lead["owner"]} for lead in leads],
                hide_index=True, width="stretch",
            )
    with tabs[4]:
        planned = sorted((item for item in items if item["scheduled_at"]), key=lambda item: item["scheduled_at"])
        if not planned:
            ui.empty_state("Nothing planned", "Approve assets and use Plan or publish to schedule manual publication.")
        else:
            st.dataframe(
                [{"When": ui.fmt_dt(item["scheduled_at"]), "Asset": item["label"], "Status": ui.label_for(item["publishing_status"])} for item in planned],
                hide_index=True, width="stretch",
            )
    with tabs[5]:
        ui.kpi_grid(
            [
                {"label": "Assets", "value": content["total"]},
                {"label": "Approved", "value": content["approved"]},
                {"label": "Published (manual)", "value": content["published"]},
                {"label": "Leads", "value": lead_stats["total"]},
                {"label": "Conversion rate", "value": None if lead_stats["conversion_rate"] is None else f"{lead_stats['conversion_rate']:.0%}", "caption": "Converted leads of all leads"},
                {"label": "Engagement", "value": None, "caption": "Needs LinkedIn, X or email analytics integration"},
            ]
        )
    with tabs[6]:
        events = [event for event in svc.activity(ctx.user, campaign["client_id"], limit=300) if event["entity_id"] == campaign["id"]]
        runs = [record for record in svc.run_records(ctx.user, campaign["client_id"]) if record.get("campaign_id") == campaign["id"]]
        rows = [{"Time": ui.fmt_dt(event["ts"]), "User": event["actor"], "Action": event["action"].replace("_", " ").capitalize(), "Detail": event["detail"]} for event in events]
        rows += [{"Time": ui.fmt_dt(record["ts"]), "User": record["user"], "Action": f"Pipeline run ({record['kind']})", "Detail": ui.label_for(record["status"])} for record in runs]
        if rows:
            st.dataframe(sorted(rows, key=lambda row: row["Time"], reverse=True), hide_index=True, width="stretch")
        else:
            ui.empty_state("No activity", "Changes to this campaign are recorded here.")


def body(ctx, client_id, scope):
    svc = ctx.service
    client_names = {client.id: client.name for client in ctx.clients}
    open_id = st.session_state.get(f"{scope}-open")
    if open_id:
        campaign = next((item for item in svc.campaigns(ctx.user, client_id) if item["id"] == open_id), None)
        if campaign:
            _detail(ctx, campaign, client_names, scope)
            return
        _close(scope)
    controls = st.columns([3, 2, 2], vertical_alignment="bottom")
    search = controls[0].text_input("Search campaigns", placeholder="Name or objective", key=f"{scope}-search")
    status = controls[1].selectbox("Status", [""] + list(CAMPAIGN_STATUSES), format_func=lambda value: ui.label_for(value) if value else "All statuses", key=f"{scope}-status")
    if controls[2].button("New campaign", type="primary", icon=":material/add:", width="stretch", key=f"{scope}-new"):
        if client_id:
            _create_dialog(ctx, client_id, svc.profile(ctx.user, client_id))
        else:
            st.warning("Select a specific client above before creating a campaign.", icon="⚠️")
    campaigns = svc.campaigns(ctx.user, client_id, status=status or None, search=search.strip())
    if not campaigns:
        ui.empty_state("No campaigns yet", "A campaign groups strategy, assets and leads for one client objective. Create one, then select it in Content Studio.")
        return
    for start in range(0, len(campaigns), 3):
        columns = st.columns(3, gap="medium")
        for column, campaign in zip(columns, campaigns[start:start + 3]):
            with column:
                _card(ctx, campaign, client_names, scope)


def render():
    ctx = current()
    client_id = client_scope(ctx, "campaigns")
    body(ctx, client_id, "camp")
