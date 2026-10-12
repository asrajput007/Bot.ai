from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Growth OS", page_icon="🚀", layout="wide", initial_sidebar_state="auto")

from growth_os.errors import GrowthOSError
from ui import components as ui
from ui import nav, theme
from ui.context import get_service
from ui.views import analytics_view, calendar_view, campaigns, clients, history, leads, overview, settings_view, studio

LOGO = Path(__file__).parent / "ui" / "assets" / "logo.svg"

PAGE_SPECS = (
    ("overview", "Overview", ":material/space_dashboard:", overview.render, "Executive view of clients, content, campaigns and leads."),
    ("clients", "Clients", ":material/groups:", clients.render, "Client directory, brand profiles and onboarding."),
    ("studio", "Content Studio", ":material/auto_awesome:", studio.render, "Create, evaluate, refine, and prepare high-quality growth assets for every client."),
    ("calendar", "Content Calendar", ":material/calendar_month:", calendar_view.render, "Plan and track manual publication of approved content."),
    ("leads", "Lead Generation", ":material/contact_mail:", leads.render, "Track prospects from first contact to conversion."),
    ("campaigns", "Campaigns", ":material/campaign:", campaigns.render, "Persistent campaigns that tie strategy, assets and leads together."),
    ("analytics", "Analytics", ":material/monitoring:", analytics_view.render, "Outcomes grounded in recorded data, with gaps stated plainly."),
    ("history", "Run History", ":material/history:", history.render, "Every pipeline execution with outputs, costs and failure details."),
    ("settings", "Settings", ":material/settings:", settings_view.render, "Integrations, pipeline policy and access."),
)


def build_pages():
    pages = {}
    for index, (key, title, icon, func, _) in enumerate(PAGE_SPECS):
        pages[key] = st.Page(func, title=title, icon=icon, url_path=key, default=index == 0)
    nav.register(pages)
    return pages


def sync_identity(service):
    users = service.operators()
    if st.session_state.get("active_user") not in users:
        st.session_state["active_user"] = users[0]
    accessible = service.clients(st.session_state["active_user"])
    ids = [client.id for client in accessible]
    if st.session_state.get("active_client") not in ids:
        st.session_state["active_client"] = ids[0] if ids else None
    return users, accessible


def render_header(service, current_key):
    users, accessible = sync_identity(service)
    names = {client.id: client.name for client in accessible}
    spec = next(item for item in PAGE_SPECS if item[0] == current_key)
    left, middle, right = st.columns([5, 3, 2.6], vertical_alignment="bottom")
    with left:
        ui.render(
            f'<div class="go-crumb">Growth OS / {ui.esc(spec[1])}</div>'
            f'<h1 class="go-title">{ui.esc(spec[1])}</h1><p class="go-sub">{ui.esc(spec[4])}</p>'
        )
    with middle:
        if names:
            st.selectbox("Active client", list(names), format_func=lambda cid: names[cid], key="active_client")
        else:
            st.caption("No client workspaces available for this user.")
    with right:
        st.selectbox("Signed in as", users, key="active_user")
    return accessible


def render_sidebar(service, accessible):
    with st.sidebar:
        st.divider()
        configured = service.integrations()[0]["configured"]
        ui.render(
            f'<div class="go-muted">Workspace</div><div><strong>{ui.esc(st.session_state["active_user"])}</strong></div>'
            f'<div class="go-muted">{len(accessible)} client workspace(s) accessible</div><div style="margin-top:8px">'
            + ui.badge("AI model configured" if configured else "AI model not configured", "success" if configured else "error")
            + "</div>"
            '<div class="go-muted" style="margin-top:8px">Publishing is manual. No social, email or CRM integration is configured.</div>'
        )


def main():
    theme.inject()
    st.logo(str(LOGO), size="large")
    try:
        service = get_service()
    except GrowthOSError as exc:
        ui.error_state("Configuration problem", str(exc))
        st.stop()
    pages = build_pages()
    selected = st.navigation(list(pages.values()), position="sidebar")
    current_key = next(key for key, page in pages.items() if page == selected)
    accessible = render_header(service, current_key)
    render_sidebar(service, accessible)
    ui.flush_toasts()
    if not accessible:
        ui.empty_state("No client workspaces", "This user has no client access. Choose another user or ask an administrator.")
        st.stop()
    selected.run()


main()
