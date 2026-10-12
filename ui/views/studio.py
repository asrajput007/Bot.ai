import json

import streamlit as st

from growth_os.errors import NotFoundError
from ui import assets_ui
from ui import components as ui
from ui import nav
from ui.context import current

CONTENT_TYPES = [
    "Thought-leadership post",
    "Founder story",
    "Service spotlight",
    "Customer problem explainer",
    "Industry commentary",
    "Lead magnet teaser",
]
CHANNELS = ["Multi-channel", "LinkedIn", "Email", "X"]
OBJECTIVES = [
    "Lead generation",
    "Authority and thought leadership",
    "Awareness",
    "Nurture existing leads",
    "Offer or event promotion",
]


def _examples(profile):
    pillar = profile.content_pillars[0] if profile.content_pillars else profile.industry
    return [
        f"Write a thought-leadership piece on {pillar} that shows our point of view and ends with a clear next step.",
        f"Share a founder story about a lesson learned in {profile.industry} and what it means for our clients.",
        f"Explain the most common mistake buyers make in {profile.industry} and how {profile.name} helps them avoid it.",
    ]


def _apply_example(client_id):
    choice = st.session_state.get(f"studio-ex-{client_id}")
    if choice:
        st.session_state[f"studio-brief-{client_id}"] = choice


def _client_strip(ctx, overview):
    profile = ctx.profile
    missing = profile.missing_for_run()
    ui.render(
        f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">'
        f'<span class="go-chip" style="margin:0"><strong>{ui.esc(profile.name)}</strong> · {ui.esc(profile.industry)}</span>'
        f'{ui.status_badge(overview["meta"]["status"])}'
        f'<span class="go-muted">Running as {ui.esc(ctx.user)}</span></div>'
    )
    if missing:
        st.warning(
            "This client's brand profile is incomplete (missing: " + ", ".join(missing) + "). Complete it before generating content.",
            icon="⚠️",
        )
        nav.link("clients", "Open Clients to complete the brand profile", ":material/groups:")
    return not missing


def _config(ctx):
    profile, settings = ctx.profile, ctx.service.settings
    cid = ctx.client_id
    campaigns = ctx.service.campaigns(ctx.user, cid)
    campaign_names = {"": "No campaign (standalone)", **{item["id"]: item["name"] for item in campaigns}}
    with st.container(border=True):
        left, right = st.columns([3, 2], gap="large")
        with left:
            brief = st.text_area(
                "Content brief",
                key=f"studio-brief-{cid}",
                height=230,
                max_chars=settings.brief_max_chars,
                placeholder="Describe what this piece should cover, who it is for and what you want readers to do.",
                help="The brief is the main input. Tone, audience and CTA default to the client's brand profile.",
            )
            st.caption(f"{len(brief.strip())}/{settings.brief_max_chars} characters, minimum {settings.brief_min_chars}")
            st.pills(
                "Start from an example",
                _examples(profile),
                key=f"studio-ex-{cid}",
                on_change=_apply_example,
                args=(cid,),
            )
        with right:
            content_type = st.selectbox("Content type", CONTENT_TYPES, key=f"studio-type-{cid}")
            channel = st.selectbox("Distribution channel", CHANNELS, key=f"studio-channel-{cid}")
            objective = st.selectbox("Campaign objective", OBJECTIVES, key=f"studio-objective-{cid}")
            campaign_id = st.selectbox(
                "Campaign",
                list(campaign_names),
                format_func=lambda value: campaign_names[value],
                key=f"studio-campaign-{cid}",
                help="Attach the output to a campaign. Create campaigns on the Campaigns page.",
            )
            cta = st.selectbox("Primary CTA", profile.cta_options() or [""], key=f"studio-cta-{cid}")
        with st.expander("Client brand profile summary"):
            ui.fields_grid(
                [
                    ("Founder", f"{profile.founder}" + (f", {profile.role}" if profile.role else "")),
                    ("Target audience", profile.audience),
                    ("Brand voice", profile.voice),
                    ("Positioning", profile.positioning),
                    ("Business goals", "; ".join(profile.business_goals)),
                ]
            )
            ui.render(ui.chips(profile.content_pillars))
            st.caption("The full profile is retrieved automatically for every run. Edit it on the Clients page.")
        with st.expander("Advanced settings"):
            a, b = st.columns(2)
            audience = a.text_input("Audience focus (optional)", key=f"studio-audience-{cid}", placeholder="Defaults to the client's target audience", max_chars=300)
            tone = b.text_input("Tone override (optional)", key=f"studio-tone-{cid}", placeholder="Defaults to the client's brand voice", max_chars=300)
            notes = st.text_area("Editorial notes (optional)", key=f"studio-notes-{cid}", height=90, max_chars=1000, placeholder="Anything the strategist must include or avoid.")
            c, d, e = st.columns(3)
            max_revisions = c.slider("Maximum drafts", 1, 5, settings.max_revisions, key=f"studio-maxrev-{cid}", help="How many strategist and judge rounds before escalating to a human.")
            min_score = d.slider("Minimum score per dimension", 1, 10, settings.min_score, key=f"studio-minscore-{cid}")
            min_average = e.slider("Minimum average score", 1.0, 10.0, float(settings.min_average), 0.1, key=f"studio-minavg-{cid}")
    options = {
        "content_type": content_type,
        "channel": channel,
        "objective": objective,
        "campaign_id": campaign_id,
        "primary_cta": cta,
        "audience": audience,
        "tone": tone,
        "editorial_notes": notes,
        "max_revisions": max_revisions,
        "min_score": min_score,
        "min_average": min_average,
    }
    return brief, options


def _outcome(artifact):
    record = artifact["record"]
    status, reason = record["status"], record["error"]
    if status == "blocked":
        ui.error_state("The brief was blocked by the input guardrail", f"{reason} Rephrase the brief as a plain description of the content you want.")
    elif status == "failed":
        ui.error_state("The pipeline failed", f"{reason} Your brief is unchanged. Check the model configuration and try again.")
    elif status == "escalated":
        st.warning(
            f"{reason} The best draft was saved for review. Use Revise Based on Feedback or approve it with an explicit override.",
            icon="⚠️",
        )
    else:
        st.success("All three stages completed. The assets are saved and waiting for approval.", icon="✅")


def _run_pipeline(ctx, brief, options):
    settings = ctx.service.settings
    cid = ctx.client_id
    if len(brief.strip()) < settings.brief_min_chars:
        st.error(f"Write a brief of at least {settings.brief_min_chars} characters so the strategist has something to work with.", icon="⚠️")
        return
    slot = st.empty()
    tracker = ui.PipelineTracker(slot, options["max_revisions"])
    ok, artifact = ui.attempt(
        ctx.service.run, ctx.user, cid, brief, tracker.on_event, options
    )
    if not ok:
        slot.empty()
        return
    record = artifact["record"]
    if record["status"] == "failed":
        tracker.fail(record["error"])
    st.session_state[f"board-{cid}"] = tracker.html()
    if artifact["package_id"]:
        package = ctx.service.package(ctx.user, artifact["package_id"])
        st.session_state[f"studio-root-{cid}"] = package["root_id"]
    _outcome(artifact)


def _metrics_strip(ctx, package):
    try:
        record = ctx.service.run_artifact(ctx.user, package["run_id"])["record"]
    except NotFoundError:
        return None
    versions = ctx.service.versions(ctx.user, package["id"])
    ui.kpi_grid(
        [
            {"label": "Version", "value": f"v{package['version']}", "caption": f"{len(versions)} version(s) in history", "accent": True},
            {"label": "Drafts in this run", "value": record["revisions"], "caption": "Strategist and judge rounds"},
            {"label": "Avg judge score", "value": record["avg_score"], "caption": "Mean of five dimensions, out of 10"},
            {"label": "End-to-end latency", "value": f"{record['latency_s']:.1f}s", "caption": f"Model calls: {record.get('llm_seconds', 0):.1f}s"},
            {"label": "Tokens used", "value": f"{record['input_tokens'] + record['output_tokens']:,}", "caption": f"{record['input_tokens']:,} in, {record['output_tokens']:,} out"},
            {"label": "Est. AI cost", "value": f"${record['cost_usd']:.4f}", "caption": "Estimate from configured list prices"},
        ]
    )
    return record


def _revise_panel(ctx, package, deliverables):
    last = package["rounds"][-1] if package["rounds"] else {}
    lines = []
    for source in ("required_revisions", "issues"):
        lines.extend(last.get(source, []))
    if last.get("revision_instructions"):
        lines.append(last["revision_instructions"])
    for item in deliverables:
        if item["approval_status"] == "changes_requested" and item["approval_note"]:
            lines.append(f"{item['label']}: {item['approval_note']}")
    if not lines:
        lines.extend(last.get("optional_refinements", []))
    default = "\n".join(f"- {line}" for line in dict.fromkeys(lines))
    with st.container(border=True):
        st.markdown("#### Revise based on feedback")
        st.caption(
            "The current version is preserved. The strategist produces a new version from this feedback, the judge re-evaluates it, "
            "and lead assets are regenerated if it passes."
        )
        feedback = st.text_area(
            "Feedback for the Content Strategist",
            value=default,
            key=f"revise-{package['id']}",
            height=150,
            placeholder="Describe what to change, for example: make the opening hook sharper and add a concrete example.",
        )
        slot = st.empty()
        if st.button("Revise Based on Feedback", type="primary", key=f"revise-go-{package['id']}", icon=":material/autorenew:"):
            tracker = ui.PipelineTracker(slot, package["options"].get("max_revisions", ctx.service.settings.max_revisions))
            ok, artifact = ui.attempt(ctx.service.revise, ctx.user, package["id"], feedback, tracker.on_event)
            if not ok:
                slot.empty()
                return
            if artifact["record"]["status"] == "failed":
                tracker.fail(artifact["record"]["error"])
            st.session_state[f"board-{ctx.client_id}"] = tracker.html()
            if artifact["package_id"]:
                ui.notify(f"Version {ctx.service.package(ctx.user, artifact['package_id'])['version']} created")
                st.rerun()
            _outcome(artifact)


def _versions_panel(ctx, package):
    versions = ctx.service.versions(ctx.user, package["id"])
    if len(versions) < 2:
        return
    with st.container(border=True):
        st.markdown("#### Version history")
        rows = []
        for version in versions:
            scores = list(version["rounds"][-1]["scores"].values()) if version["rounds"] else []
            rows.append(
                {
                    "Version": f"v{version['version']}",
                    "Created": ui.fmt_dt(version["created_at"]),
                    "Avg judge score": round(sum(scores) / len(scores), 1) if scores else None,
                    "Quality gate": "Passed" if version["quality"] == "passed" else "Failed",
                    "Working version": "Yes" if version["selected"] else "",
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")
        others = [version for version in versions if version["id"] != package["id"]]
        other = st.selectbox(
            "Compare the working version against",
            others,
            format_func=lambda version: f"v{version['version']} · {ui.fmt_dt(version['created_at'])}",
            key=f"compare-{package['id']}",
        )
        diff, old_tab, new_tab = st.tabs(["Differences", f"v{other['version']}", f"v{package['version']} (working)"])
        with diff:
            st.caption(f"Changes from v{other['version']} to v{package['version']}: red is removed, green is added.")
            st.markdown("**Headline**")
            st.markdown(ui.diff_markdown(other["draft"].get("headline", ""), package["draft"].get("headline", "")))
            st.markdown("**Body**")
            st.markdown(ui.diff_markdown(other["draft"].get("body", ""), package["draft"].get("body", "")))
        with old_tab:
            st.markdown(f"**{other['draft'].get('headline', '')}**")
            st.write(other["draft"].get("body", ""))
        with new_tab:
            st.markdown(f"**{package['draft'].get('headline', '')}**")
            st.write(package["draft"].get("body", ""))
        if st.button(f"Use v{other['version']} as the working version", key=f"use-version-{other['id']}", icon=":material/swap_horiz:"):
            ok, _ = ui.attempt(ctx.service.select_version, ctx.user, other["id"], success=f"v{other['version']} is now the working version")
            if ok:
                st.rerun()


def _results(ctx, package):
    deliverables = ctx.service.deliverables(ctx.user, ctx.client_id, package_id=package["id"])
    campaign_names = {item["id"]: item["name"] for item in ctx.service.campaigns(ctx.user, ctx.client_id)}
    audience = package["options"].get("audience") or ctx.profile.audience
    record = _metrics_strip(ctx, package)
    left, middle, right = st.columns([5, 4, 5], gap="medium")
    with left:
        st.markdown("### Stage 1 · Content Strategist")
        for item in (item for item in deliverables if item["kind"] == "strategy"):
            assets_ui.deliverable_card(ctx, item, "studio", campaign_names, ctx.profile, audience)
    with middle:
        st.markdown("### Stage 2 · LLM Judge")
        with st.container(border=True):
            assets_ui.judge_panel(package["rounds"])
    with right:
        st.markdown("### Stage 3 · Lead Gen Specialist")
        assets = [item for item in deliverables if item["kind"] != "strategy"]
        if not assets:
            ui.empty_state(
                "No lead assets for this version",
                "Lead assets are generated only after the judge approves the draft. Revise the draft based on the feedback to try again.",
            )
        else:
            for issue in package["asset_issues"]:
                st.warning(issue, icon="⚠️")
            emails, social, ctas = st.tabs(
                [f"Emails ({sum(i['kind'] == 'email' for i in assets)})", f"Social ({sum(i['kind'] == 'social' for i in assets)})", "CTAs"]
            )
            for tab, kind in ((emails, "email"), (social, "social"), (ctas, "cta")):
                with tab:
                    for item in (item for item in assets if item["kind"] == kind):
                        assets_ui.deliverable_card(ctx, item, "studio", campaign_names, ctx.profile, audience)
    _revise_panel(ctx, package, deliverables)
    _versions_panel(ctx, package)
    if record:
        artifact = ctx.service.run_artifact(ctx.user, package["run_id"])
        st.download_button(
            "Download full run as JSON",
            json.dumps(artifact, indent=2),
            file_name=f"growth-os-{package['run_id']}.json",
            mime="application/json",
            key=f"download-run-{package['id']}",
            icon=":material/download:",
        )


def _library(ctx):
    packages = ctx.service.packages(ctx.user, ctx.client_id, selected_only=True)
    if not packages:
        ui.empty_state("Nothing generated for this client yet", "Write a brief above and run Generate Growth Assets. Results are saved here for review, approval and revision.")
        return
    by_root = {package["root_id"]: package for package in packages}
    key = f"studio-root-{ctx.client_id}"
    if st.session_state.get(key) not in by_root:
        st.session_state[key] = packages[0]["root_id"]
    st.selectbox(
        "Open a saved package",
        list(by_root),
        format_func=lambda root: f"v{by_root[root]['version']} · {by_root[root]['draft'].get('headline', 'Untitled')[:70]} · {ui.fmt_dt(by_root[root]['created_at'])}",
        key=key,
    )
    _results(ctx, by_root[st.session_state[key]])


def render():
    ctx = current()
    overview = ctx.service.client_overview(ctx.user, ctx.client_id)
    ready = _client_strip(ctx, overview)
    brief, options = _config(ctx)
    run_col, hint_col = st.columns([2, 5], vertical_alignment="center")
    with run_col:
        clicked = st.button(
            "Generate Growth Assets", type="primary", disabled=not ready, key="studio-generate", icon=":material/rocket_launch:", width="stretch"
        )
    with hint_col:
        st.caption("Runs the strategist, judge and lead generation stages. Usually 20 to 60 seconds, longer if the model is busy. Identical concurrent requests are rejected.")
    board_key = f"board-{ctx.client_id}"
    if clicked:
        _run_pipeline(ctx, brief, options)
    elif st.session_state.get(board_key):
        st.caption("Last pipeline run")
        ui.render(st.session_state[board_key])
    st.divider()
    _library(ctx)
