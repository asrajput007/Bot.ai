import streamlit as st

from growth_os.profiles import CLIENT_STATUSES
from ui import assets_ui
from ui import components as ui
from ui import nav
from ui.context import current
from ui.views import analytics_view, calendar_view, campaigns, leads

STATUS_FILTERS = ["all", *CLIENT_STATUSES]
CHANNEL_OPTIONS = ["linkedin", "x", "email"]
LIST_HELP = "One item per line."


def _open_workspace(client_id):
    st.session_state["workspace_client"] = client_id
    st.session_state["active_client"] = client_id


def _close_workspace():
    st.session_state.pop("workspace_client", None)


@st.dialog("Add client workspace")
def _add_client_dialog(service, user):
    st.caption("Create the record now and complete the brand profile during onboarding. Nothing needs to be finished in one sitting.")
    with st.form("add-client-form"):
        name = st.text_input("Company or client name")
        founder = st.text_input("Founder or executive name")
        role = st.text_input("Professional role", placeholder="Founder and CEO")
        industry = st.text_input("Industry and niche")
        if st.form_submit_button("Create client", type="primary"):
            ok, profile = ui.attempt(service.create_client, user, {"name": name, "founder": founder, "role": role, "industry": industry})
            if ok:
                _open_workspace(profile.id)
                ui.notify(f"{profile.name} created. Continue onboarding in the Brand Profile tab.")
                st.rerun()


def _card(ctx, overview, index):
    profile, meta, stats = overview["profile"], overview["meta"], overview["stats"]
    objective = profile.business_goals[0] if profile.business_goals else "Not set"
    contact = profile.contact_name or profile.founder
    with st.container(border=True):
        head, state = st.columns([3, 2])
        head.markdown(f"**{profile.name}**")
        with state:
            ui.render(ui.badges([ui.status_badge(meta["status"])]))
        st.caption(f"{profile.industry or 'Industry not set'}")
        ui.fields_grid(
            [
                ("Primary contact", f"{contact}" + (f" · {profile.role}" if profile.role else "")),
                ("Target audience", (profile.audience[:110] + "...") if len(profile.audience) > 110 else profile.audience or "Not set"),
                ("Growth objective", objective),
                ("Content", f"{stats['total']} asset(s), {stats['approved']} approved, {stats['published']} published"),
                ("Campaigns and leads", f"{overview['campaigns']} campaign(s), {overview['leads']} lead(s)"),
                ("Last activity", ui.fmt_dt(overview["last_activity"])),
            ]
        )
        st.progress(overview["done"] / overview["total"], text=f"Onboarding {overview['done']}/{overview['total']} steps")
        st.button(
            "Open workspace", key=f"open-{profile.id}", on_click=_open_workspace, args=(profile.id,),
            width="stretch", icon=":material/arrow_forward:",
        )


def _directory(ctx):
    cards = ctx.service.client_cards(ctx.user)
    top = st.columns([4, 3, 2], vertical_alignment="bottom")
    search = top[0].text_input("Search clients", placeholder="Search by name, industry, founder or audience", key="client-search")
    status = top[1].selectbox("Status", STATUS_FILTERS, format_func=lambda value: "All statuses" if value == "all" else ui.label_for(value), key="client-status")
    if top[2].button("Add client", icon=":material/add:", type="primary", width="stretch", key="client-add"):
        _add_client_dialog(ctx.service, ctx.user)
    counts = {value: sum(1 for card in cards if card["meta"]["status"] == value) for value in CLIENT_STATUSES}
    average = round(sum(card["done"] / card["total"] for card in cards) / len(cards) * 100) if cards else 0
    ui.kpi_grid(
        [
            {"label": "Client workspaces", "value": len(cards), "caption": "Accessible to you"},
            {"label": "Onboarding", "value": counts["onboarding"], "caption": "Not yet launched"},
            {"label": "Active", "value": counts["active"], "caption": "Launched workspaces"},
            {"label": "Avg onboarding progress", "value": f"{average}%", "caption": "Across accessible clients"},
        ]
    )
    needle = search.strip().lower()
    matches = [
        card for card in cards
        if (status == "all" or card["meta"]["status"] == status)
        and (not needle or needle in " ".join([card["profile"].name, card["profile"].industry, card["profile"].founder, card["profile"].audience]).lower())
    ]
    if not matches:
        ui.empty_state("No clients match these filters", "Clear the search or status filter, or add a new client workspace.")
        return
    for start in range(0, len(matches), 3):
        columns = st.columns(3, gap="medium")
        for column, card in zip(columns, matches[start:start + 3]):
            with column:
                _card(ctx, card, start)


def _overview_tab(ctx, overview):
    profile, meta, stats = overview["profile"], overview["meta"], overview["stats"]
    ui.kpi_grid(
        [
            {"label": "Content assets", "value": stats["total"], "caption": f"{stats['pending']} awaiting approval"},
            {"label": "Approved", "value": stats["approved"]},
            {"label": "Published (manual)", "value": stats["published"]},
            {"label": "Campaigns", "value": overview["campaigns"]},
            {"label": "Leads", "value": overview["leads"]},
        ]
    )
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Onboarding checklist")
            st.progress(overview["done"] / overview["total"], text=f"{overview['done']} of {overview['total']} steps complete")
            current_step = overview["current_step"]
            if current_step:
                st.info(f"Next: {current_step['label']}. {current_step['hint']}", icon="➡️")
            else:
                st.success("Every onboarding step is complete.", icon="✅")
            for step in overview["steps"]:
                mark, label = st.columns([1, 9], vertical_alignment="center")
                if step["kind"] == "manual":
                    checked = mark.checkbox(
                        step["label"], value=step["done"], key=f"step-{profile.id}-{step['key']}",
                        disabled=not step["available"], label_visibility="collapsed",
                    )
                    if checked != step["done"]:
                        ok, _ = ui.attempt(ctx.service.set_onboarding_step, ctx.user, profile.id, step["key"], checked, success="Onboarding updated")
                        if ok:
                            st.rerun()
                else:
                    mark.markdown("✅" if step["done"] else "⬜")
                suffix = "" if step["done"] else f" <span class='go-muted'>({step['hint']})</span>"
                label.markdown(f"{'~~' if step['done'] else ''}{step['label']}{'~~' if step['done'] else ''}{suffix}", unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            st.markdown("#### Workspace settings")
            status = st.selectbox("Status", CLIENT_STATUSES, index=CLIENT_STATUSES.index(meta["status"]), format_func=ui.label_for, key=f"meta-status-{profile.id}")
            owners = [""] + ctx.service.operators()
            owner = st.selectbox("Assigned owner", owners, index=owners.index(meta["owner"]) if meta["owner"] in owners else 0, format_func=lambda value: value or "Unassigned", key=f"meta-owner-{profile.id}")
            notes = st.text_area("Internal notes", meta["notes"], height=110, key=f"meta-notes-{profile.id}")
            st.caption(f"Last updated {ui.fmt_dt(meta['updated_at'])}")
            if st.button("Save workspace settings", key=f"meta-save-{profile.id}", type="primary"):
                ok, _ = ui.attempt(ctx.service.set_client_meta, ctx.user, profile.id, status, owner, notes, success="Workspace settings saved")
                if ok:
                    st.rerun()
        missing = [step for step in overview["steps"] if not step["done"]]
        if missing:
            with st.container(border=True):
                st.markdown("#### Missing configuration")
                st.markdown("\n".join(f"- {step['label']}" for step in missing))


def _lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def _brand_tab(ctx, profile):
    with st.form(f"brand-{profile.id}"):
        st.markdown("##### Identity")
        a, b, c = st.columns(3)
        name = a.text_input("Company name", profile.name)
        founder = b.text_input("Founder or executive", profile.founder)
        role = c.text_input("Professional role", profile.role)
        d, e = st.columns(2)
        industry = d.text_input("Industry and niche", profile.industry)
        audience = e.text_area("Target audience", profile.audience, height=100)
        st.markdown("##### Voice and positioning")
        f, g = st.columns(2)
        voice = f.text_area("Brand voice", profile.voice, height=100)
        writing_style = g.text_area("Writing style", profile.writing_style, height=100)
        positioning = f.text_area("Positioning", profile.positioning, height=100)
        uvp = g.text_area("Unique value proposition", profile.unique_value_proposition, height=100)
        st.markdown("##### Strategy")
        h, i, j = st.columns(3)
        expertise = h.text_area("Core expertise", "\n".join(profile.core_expertise), height=120, help=LIST_HELP)
        pillars = i.text_area("Content pillars", "\n".join(profile.content_pillars), height=120, help=LIST_HELP)
        goals = j.text_area("Business goals", "\n".join(profile.business_goals), height=120, help=LIST_HELP)
        k, l = st.columns(2)
        offers = k.text_area("Products or services", "\n".join(profile.offers), height=120, help=LIST_HELP)
        proof = l.text_area("Proof points (the only facts the AI may cite)", "\n".join(profile.proof_points), height=120, help=LIST_HELP)
        st.markdown("##### Calls to action and guardrails")
        m, n = st.columns(2)
        cta = m.text_input("Primary call to action", profile.primary_cta)
        extra = n.text_area("Additional calls to action", "\n".join(profile.extra_ctas), height=80, help=LIST_HELP)
        o, p = st.columns(2)
        banned = o.text_area("Banned phrases", "\n".join(profile.banned_phrases), height=100, help=LIST_HELP)
        forbidden = p.text_area("Prohibited topics or claims", "\n".join(profile.forbidden_topics), height=100, help=LIST_HELP)
        st.markdown("##### Channels, contact and reference material")
        q, r, s = st.columns(3)
        channels = q.multiselect("Channels", CHANNEL_OPTIONS, default=[value for value in profile.channels if value in CHANNEL_OPTIONS])
        contact_name = r.text_input("Primary contact name", profile.contact_name)
        contact_email = s.text_input("Primary contact email", profile.contact_email)
        reference = st.text_area(
            "Approved reference examples",
            "\n---\n".join(profile.reference_material),
            height=160,
            help="Paste approved posts or emails. Separate examples with a line containing three dashes. They guide style only.",
        )
        st.caption("Connected social accounts are not supported yet: no publishing integration is configured.")
        if st.form_submit_button("Save brand profile", type="primary"):
            data = {
                "name": name, "founder": founder, "role": role, "industry": industry, "audience": audience, "voice": voice,
                "writing_style": writing_style, "positioning": positioning, "unique_value_proposition": uvp,
                "core_expertise": _lines(expertise), "content_pillars": _lines(pillars), "business_goals": _lines(goals),
                "offers": _lines(offers), "proof_points": _lines(proof), "primary_cta": cta, "extra_ctas": _lines(extra),
                "banned_phrases": _lines(banned), "forbidden_topics": _lines(forbidden), "channels": channels,
                "contact_name": contact_name, "contact_email": contact_email,
                "reference_material": [block.strip() for block in reference.split("\n---\n") if block.strip()],
            }
            ok, _ = ui.attempt(ctx.service.save_profile, ctx.user, profile.id, data, success="Brand profile saved")
            if ok:
                st.rerun()


def _content_tab(ctx, client_id, profile):
    left, right, third = st.columns([2, 2, 2])
    approval = left.selectbox("Approval status", ["", "pending_approval", "needs_review", "changes_requested", "approved"], format_func=lambda value: "All" if not value else ui.label_for(value), key=f"cc-approval-{client_id}")
    kind = right.selectbox("Asset type", ["", "strategy", "email", "social", "cta"], format_func=lambda value: "All" if not value else value.capitalize(), key=f"cc-kind-{client_id}")
    with third:
        nav.link("studio", "Create new content in Content Studio", ":material/auto_awesome:")
    items = ctx.service.deliverables(ctx.user, client_id, approval=approval or None, kind=kind or None)
    if not items:
        ui.empty_state("No assets match", "Generate content in Content Studio, or clear the filters.")
        return
    names = {item["id"]: item["name"] for item in ctx.service.campaigns(ctx.user, client_id)}
    for item in items:
        assets_ui.deliverable_card(ctx, item, "client", names, profile)


def _activity_tab(ctx, client_id):
    events = ctx.service.activity(ctx.user, client_id, limit=150)
    if not events:
        ui.empty_state("No activity yet", "Actions in this workspace are recorded here.")
        return
    rows = [
        {"Time": ui.fmt_dt(event["ts"]), "User": event["actor"], "Action": event["action"].replace("_", " ").capitalize(), "Detail": event["detail"]}
        for event in events
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
    ui.csv_button("Export activity (CSV)", rows, f"activity-{client_id}.csv", f"act-export-{client_id}")


def _workspace(ctx, client_id):
    overview = ctx.service.client_overview(ctx.user, client_id)
    profile = overview["profile"]
    back, title = st.columns([1, 6], vertical_alignment="center")
    back.button("All clients", on_click=_close_workspace, icon=":material/arrow_back:", key="ws-back", width="stretch")
    with title:
        ui.render(
            f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span style="font-size:1.4rem;font-weight:700">{ui.esc(profile.name)}</span>'
            f'{ui.status_badge(overview["meta"]["status"])}<span class="go-muted">{ui.esc(profile.industry)} · {ui.esc(profile.founder)}</span></div>'
        )
    tabs = st.tabs(["Overview", "Brand Profile", "Content", "Calendar", "Campaigns", "Leads", "Analytics", "Activity History"])
    with tabs[0]:
        _overview_tab(ctx, overview)
    with tabs[1]:
        _brand_tab(ctx, profile)
    with tabs[2]:
        _content_tab(ctx, client_id, profile)
    with tabs[3]:
        calendar_view.body(ctx, client_id, "ws-cal")
    with tabs[4]:
        campaigns.body(ctx, client_id, "ws-camp")
    with tabs[5]:
        leads.body(ctx, client_id, "ws-lead")
    with tabs[6]:
        analytics_view.body(ctx, client_id, "ws-ana")
    with tabs[7]:
        _activity_tab(ctx, client_id)


def render():
    ctx = current()
    selected = st.session_state.get("workspace_client")
    if selected and selected in {client.id for client in ctx.clients}:
        _workspace(ctx, selected)
    else:
        st.session_state.pop("workspace_client", None)
        _directory(ctx)
