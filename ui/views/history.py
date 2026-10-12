import json
from datetime import date, timedelta

import streamlit as st

from growth_os import analytics
from growth_os.errors import NotFoundError
from ui import assets_ui
from ui import components as ui
from ui import nav
from ui.context import client_scope, current

STATUSES = ["completed", "escalated", "blocked", "failed"]


def _open_in_studio(client_id, package_root):
    st.session_state["active_client"] = client_id
    if package_root:
        st.session_state[f"studio-root-{client_id}"] = package_root


def _details(ctx, record, scope):
    svc = ctx.service
    try:
        artifact = svc.run_artifact(ctx.user, record["run_id"])
    except NotFoundError:
        artifact = None
    started = record.get("started_at") or record["ts"]
    with st.container(border=True):
        head, state = st.columns([3, 2])
        head.markdown(f"### Run {record['run_id']}")
        head.caption(f"{record['client_name']} · {record['user']} · {record.get('kind', 'generate')}")
        with state:
            ui.render(ui.badges([ui.status_badge(record["status"])]))
        ui.fields_grid(
            [
                ("Content brief", record.get("brief") or (artifact or {}).get("brief", "Not recorded")),
                ("Started", ui.fmt_dt(started)),
                ("Completed", ui.fmt_dt(record.get("completed_at") or record["ts"])),
                ("AI model", svc.settings.model_label),
                ("Pipeline version", record.get("pipeline_version") or "Not recorded"),
                ("Package", record.get("package_id") or "None saved"),
            ]
        )
        total_tokens = record["input_tokens"] + record["output_tokens"]
        ui.kpi_grid(
            [
                {"label": "Quality score", "value": record["avg_score"] or None, "caption": "Mean of five dimensions, out of 10"},
                {"label": "End-to-end latency", "value": f"{record['latency_s']:.1f}s", "caption": "Whole pipeline including guardrails"},
                {"label": "Model call time", "value": f"{record.get('llm_seconds', 0):.1f}s", "caption": "Time spent waiting on the AI service"},
                {"label": "Tokens used", "value": f"{total_tokens:,}", "caption": f"{record['input_tokens']:,} in, {record['output_tokens']:,} out, as reported by the AI service. Billed tokens are not exposed."},
                {"label": "Estimated cost", "value": f"${record['cost_usd']:.4f}", "caption": "Estimate from configured list prices, not an invoice"},
                {"label": "Guardrail flags", "value": record["guardrail_flags"], "caption": f"{record['revisions']} draft(s)"},
            ]
        )
        if record["error"]:
            ui.error_state("Why this run did not complete cleanly", record["error"])
        if record.get("stage_seconds"):
            st.caption("Model time by stage: " + ", ".join(f"{stage} {seconds:.1f}s" for stage, seconds in record["stage_seconds"].items()))
        actions = st.columns(4)
        with actions[0]:
            if artifact:
                st.download_button("Export run (JSON)", json.dumps(artifact, indent=2), file_name=f"run-{record['run_id']}.json", mime="application/json", key=f"{scope}-json-{record['run_id']}", icon=":material/download:", width="stretch")
        with actions[1]:
            package_id = record.get("package_id")
            if package_id:
                try:
                    root = svc.package(ctx.user, package_id)["root_id"]
                except NotFoundError:
                    root = ""
                if st.button("Open in Content Studio", key=f"{scope}-studio-{record['run_id']}", icon=":material/open_in_new:", width="stretch"):
                    _open_in_studio(record["client_id"], root)
                    nav.go("studio")
        with actions[2]:
            if record.get("kind", "generate") == "revise":
                st.caption("Revisions depend on a saved version and cannot be re-run safely.")
            elif artifact and ui.confirm_action("Re-run with same brief", f"{scope}-rerun-{record['run_id']}", "Re-run this brief?", "This starts a new pipeline run and creates a new package. The original run is kept untouched.", "Re-run", icon=":material/replay:"):
                ok, result = ui.attempt(svc.run, ctx.user, record["client_id"], artifact["brief"], None, artifact.get("options"))
                if ok:
                    ui.notify(f"Re-run finished with status {ui.label_for(result['record']['status'])}")
                    st.rerun()
        if not artifact:
            st.caption("The stored output for this run is no longer available.")
            return
        strategy, judge, assets = st.tabs(["Stage 1 · Strategy", "Stage 2 · Judge", "Stage 3 · Assets"])
        with strategy:
            if artifact.get("draft"):
                assets_ui.strategy_body(artifact["draft"], "")
            else:
                st.caption("No draft was produced.")
        with judge:
            assets_ui.judge_panel(artifact.get("rounds", []))
        with assets:
            if artifact.get("assets"):
                for email in artifact["assets"]["emails"]:
                    with st.container(border=True):
                        assets_ui.email_body(email)
                for post in artifact["assets"]["social_posts"]:
                    with st.container(border=True):
                        st.markdown(f"**{post['platform'].upper()}**")
                        st.write(post["text"])
                st.markdown("**CTAs**")
                st.markdown("\n".join(f"- {cta}" for cta in artifact["assets"]["ctas"]))
            else:
                st.caption("No lead assets were generated for this run.")


def body(ctx, client_id, scope):
    records = list(reversed(ctx.service.run_records(ctx.user, client_id)))
    if not records:
        ui.empty_state("No pipeline runs yet", "Run the pipeline in Content Studio. Every execution is recorded here with its output, cost and failures.")
        nav.link("studio", "Go to Content Studio", ":material/auto_awesome:")
        return
    today = date.today()
    controls = st.columns([3, 3, 3, 2])
    search = controls[0].text_input("Search", placeholder="Run ID, brief or client", key=f"{scope}-search")
    statuses = controls[1].multiselect("Status", STATUSES, format_func=ui.label_for, key=f"{scope}-status")
    kinds = controls[2].multiselect("Type", ["generate", "revise"], format_func=str.capitalize, key=f"{scope}-kind")
    window = controls[3].selectbox("Period", ["All time", "Last 7 days", "Last 30 days"], key=f"{scope}-period")
    start = {"All time": None, "Last 7 days": today - timedelta(days=7), "Last 30 days": today - timedelta(days=30)}[window]
    needle = search.strip().lower()
    filtered = [
        r for r in records
        if (not statuses or r["status"] in statuses)
        and (not kinds or r.get("kind", "generate") in kinds)
        and (start is None or analytics.in_range(r["ts"], start, today))
        and (not needle or needle in f"{r['run_id']} {r.get('brief', '')} {r['client_name']}".lower())
    ]
    if not filtered:
        ui.empty_state("No runs match these filters", "Clear the search or filters to see more runs.")
        return
    rows = [
        {
            "Run": r["run_id"], "Time": ui.fmt_dt(r["ts"]), "Client": r["client_name"], "Type": r.get("kind", "generate").capitalize(),
            "Status": ui.label_for(r["status"]), "Score": r["avg_score"], "Latency (s)": round(r["latency_s"], 1),
            "Tokens": r["input_tokens"] + r["output_tokens"], "Est. cost ($)": r["cost_usd"], "User": r["user"],
        }
        for r in filtered
    ]
    selection = st.dataframe(rows, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=f"{scope}-table")
    ui.csv_button("Export runs (CSV)", rows, "run-history.csv", f"{scope}-csv")
    picked = selection.selection.rows if selection and selection.selection else []
    if picked and picked[0] < len(filtered):
        _details(ctx, filtered[picked[0]], scope)
    else:
        st.caption("Select a run to see its output, cost, timings and any failure reason.")


def render():
    ctx = current()
    client_id = client_scope(ctx, "history")
    body(ctx, client_id, "hist")
