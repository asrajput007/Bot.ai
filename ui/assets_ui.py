from datetime import date, datetime, time, timedelta
from statistics import mean

import streamlit as st

from growth_os import guardrails
from growth_os.content import PLATFORM_LABELS, deliverable_text

from . import components as ui

SOCIAL_LIMITS = {"linkedin": guardrails.LINKEDIN_MAX, "x": guardrails.X_MAX}


def _hook(text):
    first = text.strip().split("\n")[0]
    for stop in (". ", "? ", "! "):
        if stop in first:
            first = first.split(stop)[0] + stop.strip()
            break
    return first[:140]


def strategy_body(content, audience):
    st.markdown(f"#### {content.get('headline', '')}")
    ui.fields_grid(
        [
            ("Campaign objective", content.get("campaign_objective")),
            ("Target audience", audience),
            ("Core message", content.get("core_message")),
            ("Content angle", content.get("content_angle")),
            ("Suggested hook", content.get("suggested_hook")),
            ("Recommended format", content.get("recommended_format")),
            ("Primary CTA", content.get("primary_cta")),
        ]
    )
    if content.get("audience_pain_points"):
        with st.expander("Audience pain points"):
            st.markdown("\n".join(f"- {item}" for item in content["audience_pain_points"]))
    if content.get("content_pillars"):
        ui.render(ui.chips(content["content_pillars"]))
    with st.expander("Full draft", expanded=True):
        st.write(content.get("body", ""))
    with st.expander("Key messages"):
        st.markdown("\n".join(f"- {item}" for item in content.get("key_messages", [])))
    if content.get("distribution_recommendations"):
        with st.expander("Distribution recommendations"):
            st.markdown("\n".join(f"- {item}" for item in content["distribution_recommendations"]))


def email_body(content):
    st.markdown(f"**Subject:** {content.get('subject', '')}")
    st.caption(f"Preview: {content.get('preview', '')}  ·  {len(content.get('subject', ''))}/{guardrails.EMAIL_SUBJECT_MAX} subject characters")
    st.write(content.get("body", ""))
    st.markdown(f"**CTA:** {content.get('cta', '')}")


def social_body(content, profile):
    text = content.get("text", "")
    st.caption(f"Opening hook: {_hook(text)}")
    st.write(text)
    tags = content.get("hashtags", [])
    if tags:
        st.caption(" ".join(f"#{tag.lstrip('#')}" for tag in tags))
    platform = content.get("platform", "")
    limit = SOCIAL_LIMITS.get(platform)
    length = len(text) + sum(len(tag) + 2 for tag in tags)
    if limit:
        over = length > limit
        st.caption(f"{'⚠ ' if over else ''}{length}/{limit} characters (post and hashtags)")
    cta = next((option for option in profile.cta_options() if option.lower() in text.lower()), "")
    if cta:
        st.caption(f"CTA in post: {cta}")


def cta_body(content, profile, campaign_name, audience):
    for cta in content.get("ctas", []):
        st.markdown(f"- **{cta}**")
    ui.fields_grid(
        [
            ("Intended audience", audience),
            ("Associated campaign", campaign_name or "None"),
            ("Destination URL", "Not configured"),
            ("Intended conversion", profile.primary_cta),
        ]
    )


def _copy(item):
    content = item["content"]
    with st.popover("Copy", icon=":material/content_copy:", width="stretch"):
        st.caption("Use the copy icon at the top right of each box.")
        if item["kind"] == "email":
            st.markdown("**Subject**")
            st.code(content.get("subject", ""), language=None, wrap_lines=True)
            st.markdown("**Body**")
            st.code(content.get("body", ""), language=None, wrap_lines=True)
        else:
            st.code(deliverable_text(item), language=None, wrap_lines=True)


def _approve(ctx, item, key):
    approved = item["approval_status"] == "approved"
    if item["quality"] != "passed" and not approved:
        confirmed = ui.confirm_action(
            "Approve", f"{key}-approve", "Approve despite the failed quality gate?",
            "This asset did not pass the automatic quality gate. Approving it records an explicit override in the audit log.",
            "Approve anyway", icon=":material/check:",
        )
        if confirmed:
            ok, _ = ui.attempt(ctx.service.approve, ctx.user, item["id"], True, success="Approved with quality override")
            if ok:
                st.rerun()
        return
    if st.button("Approved" if approved else "Approve", key=f"{key}-approve", disabled=approved, icon=":material/check:", width="stretch"):
        ok, _ = ui.attempt(ctx.service.approve, ctx.user, item["id"], success="Asset approved")
        if ok:
            st.rerun()


def _request_changes(ctx, item, key):
    with st.popover("Request revision", icon=":material/edit_note:", width="stretch"):
        note = st.text_area("What should change?", value=item.get("approval_note", "") if item["approval_status"] == "changes_requested" else "", key=f"{key}-note", height=100)
        if st.button("Send request", key=f"{key}-send-changes", type="primary"):
            ok, _ = ui.attempt(ctx.service.request_changes, ctx.user, item["id"], note, success="Revision requested")
            if ok:
                st.rerun()


def _plan(ctx, item, key):
    svc, user = ctx.service, ctx.user
    with st.expander("Plan or publish"):
        if item["publishing_status"] == "published":
            st.success(f"Recorded as published on {ui.fmt_dt(item['published_at'])}")
            if item["publish_note"]:
                st.caption(item["publish_note"])
            return
        if item["approval_status"] != "approved":
            st.info("Approve this asset before planning its publication.")
            return
        st.caption(
            "No publishing integration is configured, so publishing is manual. Planning a date adds the asset to the Content Calendar."
        )
        current = datetime.fromisoformat(item["scheduled_at"]) if item["scheduled_at"] else datetime.combine(date.today() + timedelta(days=1), time(9, 0))
        planned_date = st.date_input("Date", current.date(), key=f"{key}-date")
        planned_time = st.time_input("Time", current.time(), key=f"{key}-time")
        left, right = st.columns(2)
        if left.button("Update plan" if item["publishing_status"] == "scheduled" else "Plan", key=f"{key}-plan", type="primary", width="stretch"):
            ok, _ = ui.attempt(svc.schedule, user, item["id"], datetime.combine(planned_date, planned_time), success="Publication planned")
            if ok:
                st.rerun()
        if right.button("Remove plan", key=f"{key}-unplan", disabled=item["publishing_status"] != "scheduled", width="stretch"):
            ok, _ = ui.attempt(svc.unschedule, user, item["id"], success="Plan removed")
            if ok:
                st.rerun()
        st.divider()
        note = st.text_input("Where was it published? (optional)", key=f"{key}-pubnote")
        sure = st.checkbox("I published this manually", key=f"{key}-sure")
        if st.button("Record as published", key=f"{key}-publish", disabled=not sure):
            ok, _ = ui.attempt(svc.mark_published, user, item["id"], note, success="Recorded as manually published")
            if ok:
                st.rerun()


def _edit(ctx, item, key):
    content = item["content"]
    if item["publishing_status"] == "published":
        st.caption("Published content is locked. Use Revise Based on Feedback to create a new version.")
        return
    with st.expander("Edit draft"):
        with st.form(f"{key}-edit"):
            if item["kind"] == "email":
                subject = st.text_input("Subject", content.get("subject", ""))
                preview = st.text_input("Preview text", content.get("preview", ""))
                body = st.text_area("Body", content.get("body", ""), height=220)
                cta = st.text_input("CTA", content.get("cta", ""))
                updated = {**content, "subject": subject, "preview": preview, "body": body, "cta": cta}
            elif item["kind"] == "social":
                text = st.text_area("Post", content.get("text", ""), height=170)
                tags = st.text_input("Hashtags (comma separated)", ", ".join(content.get("hashtags", [])))
                updated = {**content, "text": text, "hashtags": [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]}
            elif item["kind"] == "cta":
                lines = st.text_area("CTAs (one per line)", "\n".join(content.get("ctas", [])), height=140)
                updated = {"ctas": [line.strip() for line in lines.splitlines() if line.strip()]}
            else:
                headline = st.text_input("Headline", content.get("headline", ""))
                body = st.text_area("Body", content.get("body", ""), height=300)
                messages = st.text_area("Key messages (one per line)", "\n".join(content.get("key_messages", [])), height=110)
                updated = {**content, "headline": headline, "body": body, "key_messages": [line.strip() for line in messages.splitlines() if line.strip()]}
            st.caption("Saving an edit returns the asset to pending approval and removes any publication plan.")
            if st.form_submit_button("Save changes", type="primary"):
                ok, result = ui.attempt(ctx.service.edit_deliverable, ctx.user, item["id"], updated)
                if ok:
                    warnings = result[1]
                    if warnings:
                        ui.notify("Saved with policy warnings: " + " ".join(warnings[:3]), "⚠️")
                    else:
                        ui.notify("Changes saved")
                    st.rerun()


def deliverable_card(ctx, item, scope, campaign_names=None, profile=None, audience=""):
    profile = profile or ctx.service.profile(ctx.user, item["client_id"])
    key = f"{scope}-{item['id']}"
    badge_items = [ui.status_badge(item["approval_status"]), ui.status_badge(item["publishing_status"])]
    if item["quality"] != "passed":
        badge_items.append(ui.badge("Quality gate failed", "error"))
    if item["edited"]:
        badge_items.append(ui.badge("Edited", "accent"))
    with st.container(border=True):
        head, state = st.columns([3, 3])
        with head:
            st.markdown(f"**{item['label']}**  ·  version {item['version']}")
            if item["kind"] == "social":
                st.caption(PLATFORM_LABELS.get(item["channel"], item["channel"].title()))
        with state:
            ui.render(ui.badges(badge_items))
        if item["approval_status"] == "changes_requested" and item["approval_note"]:
            st.warning(f"Requested changes: {item['approval_note']}", icon="📝")
        if item["kind"] == "strategy":
            strategy_body(item["content"], audience or profile.audience)
        elif item["kind"] == "email":
            email_body(item["content"])
        elif item["kind"] == "social":
            social_body(item["content"], profile)
        else:
            name = (campaign_names or {}).get(item["campaign_id"], "")
            cta_body(item["content"], profile, name, audience or profile.audience)
        first = st.columns(3)
        with first[0]:
            _copy(item)
        with first[1]:
            _approve(ctx, item, key)
        with first[2]:
            st.download_button(
                "Export", deliverable_text(item), file_name=f"{item['kind']}-{item['id']}.txt", mime="text/plain",
                key=f"{key}-export", icon=":material/download:", width="stretch",
            )
        _request_changes(ctx, item, key)
        _plan(ctx, item, key)
        _edit(ctx, item, key)


def judge_panel(rounds):
    if not rounds:
        ui.empty_state("No evaluation yet", "The judge runs after the strategist drafts content.")
        return
    last = rounds[-1]
    scores = last["scores"]
    overall = round(mean(scores.values()), 1)
    gate = ui.badge("Passed quality gate", "success") if last["passed"] else ui.badge("Below quality gate", "warning")
    ui.render(
        f'<div class="go-overall"><div><div class="go-muted">Overall (mean of dimensions)</div>'
        f'<div class="big">{overall}<small>/10</small></div></div>{gate}</div>'
    )
    ui.score_cards(scores)
    ui.bullets("What is working", last.get("strengths", []))
    ui.bullets("What needs improvement", last.get("issues", []))
    ui.bullets("Required revisions", last.get("required_revisions", []))
    ui.bullets("Optional refinements", last.get("optional_refinements", []))
    ui.bullets("Automatic guardrail findings", last.get("automatic_findings", []))
    if last.get("revision_instructions"):
        st.markdown("**Guidance for the next revision**")
        st.write(last["revision_instructions"])
    if len(rounds) > 1:
        with st.expander(f"Evaluation history ({len(rounds)} rounds)"):
            for item in rounds:
                values = list(item["scores"].values())
                verdict = "passed" if item["passed"] else "below the gate"
                st.markdown(f"**Round {item['round']}**: overall {round(mean(values), 1)}/10, lowest {min(values)}/10, {verdict}")
                if item.get("issues"):
                    st.caption("; ".join(item["issues"][:3]))
