import calendar
from datetime import date, datetime, timedelta

import streamlit as st

from growth_os.content import deliverable_title
from ui import assets_ui
from ui import components as ui
from ui.context import client_scope, current

VIEWS = ["Month", "Week", "List"]
STATUS_FILTERS = {
    "all": "All statuses",
    "pending": "Pending approval",
    "attention": "Needs attention",
    "approved": "Approved, not planned",
    "scheduled": "Planned",
    "published": "Published (manual)",
}


def _planned_at(item):
    value = item["scheduled_at"] or item["published_at"]
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _matches(item, status):
    if status == "all":
        return True
    if status == "pending":
        return item["approval_status"] == "pending_approval"
    if status == "attention":
        return item["approval_status"] in ("needs_review", "changes_requested")
    if status == "approved":
        return item["approval_status"] == "approved" and item["publishing_status"] == "not_scheduled"
    return item["publishing_status"] == status


def _month_html(items_by_day, year, month, names):
    today = date.today()
    header = "".join(f"<th>{name}</th>" for name in calendar.day_abbr)
    rows = []
    for week in calendar.Calendar(0).monthdatescalendar(year, month):
        cells = []
        for day in week:
            classes = ("out " if day.month != month else "") + ("today" if day == today else "")
            entries = items_by_day.get(day, [])
            shown = "".join(
                f'<span class="it{" done" if item["publishing_status"] == "published" else ""}" title="{ui.esc(deliverable_title(item))}">'
                f'{(_planned_at(item) or datetime.min).strftime("%H:%M")} {ui.esc(names.get(item["client_id"], "")[:12])} · {ui.esc(item["label"])}</span>'
                for item in entries[:3]
            )
            more = f'<span class="go-muted">+{len(entries) - 3} more</span>' if len(entries) > 3 else ""
            cells.append(f'<td class="{classes.strip()}"><div class="d">{day.day}</div>{shown}{more}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<table class="go-cal" role="grid" aria-label="Content calendar"><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _shift_month(key, delta):
    current = st.session_state[key]
    month = current.month - 1 + delta
    st.session_state[key] = date(current.year + month // 12, month % 12 + 1, 1)


def _shift_week(key, delta):
    st.session_state[key] = st.session_state[key] + timedelta(days=7 * delta)


def body(ctx, client_id, scope):
    svc = ctx.service
    items = svc.deliverables(ctx.user, client_id)
    campaigns = svc.campaigns(ctx.user, client_id)
    campaign_names = {item["id"]: item["name"] for item in campaigns}
    client_names = {client.id: client.name for client in ctx.clients}
    filters = st.columns([2, 2, 2, 2])
    view = filters[0].segmented_control("View", VIEWS, default="Month", key=f"{scope}-view") or "Month"
    channel_options = sorted({item["channel"] for item in items if item["kind"] != "cta"})
    channels = filters[1].multiselect("Channels", channel_options, format_func=lambda value: value.upper() if value == "x" else value.title(), key=f"{scope}-channels")
    campaign = filters[2].selectbox("Campaign", [""] + list(campaign_names), format_func=lambda value: campaign_names.get(value, "All campaigns"), key=f"{scope}-campaign")
    status = filters[3].selectbox("Status", list(STATUS_FILTERS), format_func=STATUS_FILTERS.get, key=f"{scope}-status")
    pool = [
        item for item in items
        if item["kind"] != "cta"
        and (not channels or item["channel"] in channels)
        and (not campaign or item["campaign_id"] == campaign)
        and _matches(item, status)
    ]
    planned = [item for item in pool if _planned_at(item)]
    unplanned = [item for item in pool if not _planned_at(item)]
    if not items:
        ui.empty_state("Nothing to plan yet", "Generate and approve content in Content Studio. Approved assets can then be planned here.")
        return
    st.caption("Publishing is manual. Planned dates track when your team intends to publish; failed publishing is not tracked because no integration publishes on your behalf.")
    month_key, week_key = f"{scope}-month-date", f"{scope}-week-date"
    st.session_state.setdefault(month_key, date.today().replace(day=1))
    st.session_state.setdefault(week_key, date.today() - timedelta(days=date.today().weekday()))
    in_range = planned
    if view == "Month":
        nav_cols = st.columns([1, 1, 4, 1], vertical_alignment="center")
        nav_cols[0].button("Previous", key=f"{scope}-prev", icon=":material/chevron_left:", on_click=_shift_month, args=(month_key, -1), width="stretch")
        nav_cols[1].button("Next", key=f"{scope}-next", icon=":material/chevron_right:", on_click=_shift_month, args=(month_key, 1), width="stretch")
        anchor = st.session_state[month_key]
        nav_cols[2].markdown(f"### {anchor.strftime('%B %Y')}")
        by_day = {}
        for item in planned:
            by_day.setdefault(_planned_at(item).date(), []).append(item)
        for entries in by_day.values():
            entries.sort(key=_planned_at)
        ui.render(_month_html(by_day, anchor.year, anchor.month, client_names if client_id is None else {}))
        in_range = [item for item in planned if _planned_at(item).year == anchor.year and _planned_at(item).month == anchor.month]
    elif view == "Week":
        nav_cols = st.columns([1, 1, 4, 1], vertical_alignment="center")
        nav_cols[0].button("Previous", key=f"{scope}-wprev", icon=":material/chevron_left:", on_click=_shift_week, args=(week_key, -1), width="stretch")
        nav_cols[1].button("Next", key=f"{scope}-wnext", icon=":material/chevron_right:", on_click=_shift_week, args=(week_key, 1), width="stretch")
        start = st.session_state[week_key]
        nav_cols[2].markdown(f"### {start.strftime('%d %b')} to {(start + timedelta(days=6)).strftime('%d %b %Y')}")
        columns = st.columns(7)
        in_range = []
        for offset, column in enumerate(columns):
            day = start + timedelta(days=offset)
            entries = sorted((item for item in planned if _planned_at(item).date() == day), key=_planned_at)
            in_range.extend(entries)
            with column:
                with st.container(border=True):
                    st.markdown(f"**{day.strftime('%a %d')}**")
                    if not entries:
                        st.caption("Nothing planned")
                    for item in entries:
                        st.caption(f"{_planned_at(item).strftime('%H:%M')} · {item['label']}")
                        ui.render(ui.status_badge(item["publishing_status"]))
    else:
        rows = [
            {
                "When": _planned_at(item).strftime("%d %b %Y %H:%M"),
                "Client": client_names.get(item["client_id"], item["client_id"]),
                "Asset": item["label"],
                "Title": deliverable_title(item),
                "Channel": item["channel"],
                "Approval": ui.label_for(item["approval_status"]),
                "Publishing": ui.label_for(item["publishing_status"]),
                "Campaign": campaign_names.get(item["campaign_id"], ""),
            }
            for item in sorted(planned, key=_planned_at)
        ]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
            ui.csv_button("Export calendar (CSV)", rows, "content-calendar.csv", f"{scope}-export")
        else:
            ui.empty_state("No planned items match", "Approve an asset and use Plan or publish to add it to the calendar.")
    ui.page_section("Open an item", "View, edit, approve or plan any asset matching the filters.")
    options = [*sorted(in_range, key=_planned_at), *unplanned]
    if not options:
        st.caption("No assets match the current filters.")
        return
    labels = {item["id"]: f"{(_planned_at(item).strftime('%d %b %H:%M') if _planned_at(item) else 'Unplanned')} · {item['label']} · {deliverable_title(item)[:50]}" for item in options}
    chosen = st.selectbox("Asset", [item["id"] for item in options], format_func=labels.get, key=f"{scope}-open")
    item = next(item for item in options if item["id"] == chosen)
    assets_ui.deliverable_card(ctx, item, f"{scope}-open", campaign_names)


def render():
    ctx = current()
    client_id = client_scope(ctx, "calendar")
    body(ctx, client_id, "cal")
