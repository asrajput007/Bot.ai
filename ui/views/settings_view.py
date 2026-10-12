import streamlit as st

from ui import components as ui
from ui.context import current


def render():
    ctx = current()
    svc = ctx.service
    s = svc.settings
    tabs = st.tabs(["Integrations", "Pipeline policy", "Access", "Prompt library"])
    with tabs[0]:
        ui.page_section("Integrations", "Anything not configured is shown honestly and handled as a manual workflow.")
        for item in svc.integrations():
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment="center")
                left.markdown(f"**{item['name']}**")
                left.caption(item["detail"])
                with right:
                    ui.render(ui.badges([ui.badge("Configured", "success") if item["configured"] else ui.badge("Not configured", "neutral")]))
        st.caption("API keys are read from .env on the server and never shown in the interface.")
    with tabs[1]:
        ui.page_section("Pipeline policy", "Defaults applied to every run. Override per run in Content Studio under Advanced settings.")
        ui.kpi_grid(
            [
                {"label": "Maximum drafts", "value": s.max_revisions, "caption": "MAX_REVISIONS"},
                {"label": "Min score per dimension", "value": s.min_score, "caption": "JUDGE_MIN_SCORE"},
                {"label": "Min average score", "value": s.min_average, "caption": "JUDGE_MIN_AVERAGE"},
                {"label": "Asset attempts", "value": s.asset_attempts, "caption": "ASSET_ATTEMPTS"},
                {"label": "Daily runs per client", "value": s.daily_runs_per_client, "caption": "DAILY_RUNS_PER_CLIENT"},
                {"label": "Brief length", "value": f"{s.brief_min_chars} to {s.brief_max_chars}", "caption": "BRIEF_MIN_CHARS, BRIEF_MAX_CHARS"},
                {"label": "Model timeout", "value": f"{s.request_timeout:g}s", "caption": "Server setting"},
                {"label": "AI model", "value": s.model_label, "caption": "MODEL_DISPLAY_NAME (display label only)"},
            ]
        )
        st.caption("Change these in .env and restart the app. ROI assumptions are documented on the Analytics page.")
    with tabs[2]:
        ui.page_section("Access", "Client access is enforced in the backend for every read and write.")
        names = {client.id: client.name for client in svc.clients()}
        matrix = svc.access.matrix()
        rows = [{"Operator": user, "Clients": len(ids), "Workspaces": ", ".join(names[cid] for cid in ids)} for user, ids in matrix.items()]
        st.dataframe(rows, hide_index=True, width="stretch")
        st.warning(
            "Operators are an identity stub chosen from a dropdown, not real authentication. A production deployment needs SSO and per-user sessions.",
            icon="⚠️",
        )
    with tabs[3]:
        ui.page_section("Prompt library", "The universal base prompt injected ahead of every client profile.")
        universal = svc.base_store.universal
        st.markdown(f"**Role context**\n\n{universal.role_context}")
        ui.bullets("Rules", universal.rules)
        ui.bullets("Output format", universal.output_format)
        ui.bullets("Validation", universal.validation)
        ui.bullets("Globally banned phrases", universal.banned_phrases)
        for stage, text in svc.base_store.stages.items():
            with st.expander(f"Stage instructions: {stage}"):
                st.write(text)
