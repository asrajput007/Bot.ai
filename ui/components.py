import csv
import difflib
import html
import io
import re
import time
from datetime import datetime

import streamlit as st

from growth_os.errors import GrowthOSError

ICONS = {"success": "✓", "warning": "!", "error": "✕", "info": "●", "accent": "●", "neutral": "○"}

STATUS = {
    "approved": ("Approved", "success"),
    "pending_approval": ("Pending approval", "warning"),
    "needs_review": ("Needs review", "error"),
    "changes_requested": ("Changes requested", "warning"),
    "not_scheduled": ("Not scheduled", "neutral"),
    "scheduled": ("Planned", "info"),
    "published": ("Published (manual)", "success"),
    "completed": ("Completed", "success"),
    "escalated": ("Escalated", "warning"),
    "blocked": ("Blocked", "error"),
    "failed": ("Failed", "error"),
    "passed": ("Passed", "success"),
    "onboarding": ("Onboarding", "info"),
    "active": ("Active", "success"),
    "paused": ("Paused", "warning"),
    "planned": ("Planned", "info"),
    "new": ("New", "info"),
    "contacted": ("Contacted", "accent"),
    "replied": ("Replied", "accent"),
    "qualified": ("Qualified", "accent"),
    "meeting_booked": ("Meeting booked", "success"),
    "converted": ("Converted", "success"),
    "disqualified": ("Disqualified", "neutral"),
}

STAGE_DEFS = (
    ("guard", "Brief validation"),
    ("strategist", "Stage 1 · Content Strategist"),
    ("judge", "Stage 2 · LLM Judge"),
    ("lead_gen", "Stage 3 · Lead Gen Specialist"),
)
STAGE_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "completed": "Completed",
    "revision": "Needs revision",
    "failed": "Failed",
}
STAGE_ICONS = {"queued": "○", "completed": "✓", "revision": "↻", "failed": "✕"}


def esc(value):
    return html.escape(str(value if value is not None else ""))


def render(markup):
    st.markdown(markup, unsafe_allow_html=True)


def label_for(status):
    return STATUS.get(status, (str(status).replace("_", " ").capitalize(), "neutral"))[0]


def badge(label, tone="neutral"):
    return f'<span class="go-badge {tone}"><span aria-hidden="true">{ICONS.get(tone, "○")}</span>{esc(label)}</span>'


def status_badge(status):
    label, tone = STATUS.get(status, (str(status).replace("_", " ").capitalize(), "neutral"))
    return badge(label, tone)


def badges(items):
    return f'<div class="go-badges">{"".join(items)}</div>'


def chips(items):
    if not items:
        return ""
    return "".join(f'<span class="go-chip">{esc(item)}</span>' for item in items)


def fmt_dt(value):
    if not value:
        return "Never"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if parsed.tzinfo:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.strftime("%d %b %Y, %H:%M")


def fmt_date(value):
    if not value:
        return "Not set"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return str(value)


def page_section(title, sub=""):
    render(f'<div class="go-section">{esc(title)}</div>' + (f'<p class="go-section-sub">{esc(sub)}</p>' if sub else ""))


def kpi_grid(items):
    cells = []
    for item in items:
        value = item.get("value")
        classes = "go-kpi" + (" na" if value is None else "") + (" accent" if item.get("accent") else "")
        shown = "Not available" if value is None else esc(value)
        caption = f'<div class="caption">{esc(item.get("caption", ""))}</div>' if item.get("caption") else ""
        cells.append(f'<div class="{classes}"><div class="label">{esc(item["label"])}</div><div class="value">{shown}</div>{caption}</div>')
    render(f'<div class="go-grid">{"".join(cells)}</div>')


def empty_state(title, body):
    render(f'<div class="go-empty"><div class="t">{esc(title)}</div><div class="b">{esc(body)}</div></div>')


def error_state(title, body=""):
    render(f'<div class="go-error"><div class="t">{esc(title)}</div><div class="b">{esc(body)}</div></div>')


def fields_grid(pairs):
    cells = [
        f'<div class="go-field"><div class="k">{esc(key)}</div><div class="v">{esc(value)}</div></div>'
        for key, value in pairs
        if value
    ]
    if cells:
        render(f'<div class="go-fields">{"".join(cells)}</div>')


def score_class(value):
    if value >= 8:
        return ""
    return "low" if value >= 6 else "bad"


def score_cards(scores):
    cells = []
    for name, value in scores.items():
        cells.append(
            f'<div class="go-score {score_class(value)}"><div class="k">{esc(name.replace("_", " "))}</div>'
            f'<div class="v">{value}<small>/10</small></div><div class="bar"><span style="width:{value * 10}%"></span></div></div>'
        )
    render(f'<div class="go-scores">{"".join(cells)}</div>')


def bullets(title, items, empty=""):
    if not items:
        if empty:
            st.caption(f"{title}: {empty}")
        return
    st.markdown(f"**{title}**")
    st.markdown("\n".join(f"- {item}" for item in items))


def notify(message, icon="✅"):
    st.session_state.setdefault("_toasts", []).append((message, icon))


def flush_toasts():
    for message, icon in st.session_state.pop("_toasts", []):
        st.toast(message, icon=icon)


def attempt(fn, *args, success=None, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except GrowthOSError as exc:
        st.error(str(exc), icon="⚠️")
        return False, None
    if success:
        notify(success)
    return True, result


@st.dialog("Please confirm")
def _confirm_dialog(key, title, message, confirm_label):
    st.markdown(f"**{title}**")
    st.write(message)
    left, right = st.columns(2)
    if left.button(confirm_label, type="primary", key=f"{key}-yes", width="stretch"):
        st.session_state[f"{key}-confirmed"] = True
        st.rerun()
    if right.button("Cancel", key=f"{key}-no", width="stretch"):
        st.rerun()


def confirm_action(label, key, title, message, confirm_label="Confirm", disabled=False, icon=None):
    if st.button(label, key=f"{key}-trigger", disabled=disabled, icon=icon, width="stretch"):
        _confirm_dialog(key, title, message, confirm_label)
    return st.session_state.pop(f"{key}-confirmed", False)


def copy_popover(label, text, key=None):
    with st.popover(label, width="stretch"):
        st.caption("Use the copy icon at the top right of the box.")
        st.code(text or "", language=None, wrap_lines=True)


def to_csv(rows):
    if not rows:
        return ""
    buffer = io.StringIO()
    columns = list(rows[0].keys())
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in columns})
    return buffer.getvalue()


def csv_button(label, rows, filename, key):
    st.download_button(
        label,
        to_csv(rows),
        file_name=filename,
        mime="text/csv",
        key=key,
        disabled=not rows,
        icon=":material/download:",
        width="stretch",
    )


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~$])")


def _escape_md(text):
    return _MD_SPECIAL.sub(r"\\\1", text)


def diff_markdown(old, new):
    old_words, new_words = old.split(), new.split()
    pieces = []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old_words, new_words, autojunk=False).get_opcodes():
        if tag == "equal":
            pieces.append(_escape_md(" ".join(old_words[a1:a2])))
            continue
        if tag in ("delete", "replace"):
            pieces.append(":red[~~" + _escape_md(" ".join(old_words[a1:a2])) + "~~]")
        if tag in ("insert", "replace"):
            pieces.append(":green[**" + _escape_md(" ".join(new_words[b1:b2])) + "**]")
    return " ".join(piece for piece in pieces if piece)


class PipelineTracker:
    def __init__(self, placeholder, max_revisions):
        self.placeholder = placeholder
        self.max_revisions = max_revisions
        self.drafts = 0
        self.stages = {
            key: {"state": "queued", "detail": "", "started": None, "seconds": None, "stamp": ""}
            for key, _ in STAGE_DEFS
        }
        self._start("guard", "Checking brief and parameters")
        self.render()

    def _start(self, key, detail=""):
        self.stages[key].update(
            state="running", detail=detail, started=time.perf_counter(), seconds=None, stamp=datetime.now().strftime("%H:%M:%S")
        )

    def _finish(self, key, state, detail=""):
        stage = self.stages[key]
        started = stage["started"]
        stage.update(state=state, detail=detail, seconds=(time.perf_counter() - started) if started else None)

    def on_event(self, node, update):
        if node == "guard_input":
            if update.get("status") == "blocked":
                self._finish("guard", "failed", update.get("reason", "Blocked by input guardrail"))
            else:
                self._finish("guard", "completed", "Brief and parameters accepted")
                self._start("strategist", "Drafting strategy")
        elif node == "strategist":
            self.drafts = update.get("revision", self.drafts + 1)
            self._finish("strategist", "completed", f"Draft {self.drafts} ready")
            self._start("judge", "Scoring against brand rules")
        elif node == "judge":
            if update.get("status") == "passed":
                self._finish("judge", "completed", "Quality gate passed")
                self._start("lead_gen", "Generating assets")
            else:
                self._finish("judge", "revision", f"Draft {self.drafts} below the quality gate")
                if self.drafts < self.max_revisions:
                    self._start("strategist", f"Revising (draft {self.drafts + 1} of up to {self.max_revisions})")
        elif node == "lead_gen":
            if update.get("status") == "completed":
                self._finish("lead_gen", "completed", "Assets generated and validated")
            else:
                self._finish("lead_gen", "revision", "Output guardrails flagged the assets")
        elif node == "escalate":
            self.stages["judge"]["detail"] = "Escalated to human review"
        self.render()

    def fail(self, message):
        for stage in self.stages.values():
            if stage["state"] == "running":
                stage.update(state="failed", detail=message)
                stage["seconds"] = time.perf_counter() - stage["started"] if stage["started"] else None
        self.render()

    def html(self):
        cells = []
        for key, name in STAGE_DEFS:
            stage = self.stages[key]
            state = stage["state"]
            icon = '<span class="go-spin" aria-hidden="true"></span>' if state == "running" else f'<span aria-hidden="true">{STAGE_ICONS[state]}</span>'
            timing = ""
            if stage["stamp"] and state != "queued":
                timing = f"Started {stage['stamp']}"
                if stage["seconds"] is not None:
                    timing += f" · {stage['seconds']:.1f}s"
            cells.append(
                f'<div class="go-stage" data-state="{state}" role="status"><div class="name">{esc(name)}</div>'
                f'<div class="state">{icon}<span>{STAGE_LABELS[state]}</span></div>'
                f'<div class="detail">{esc(stage["detail"])}</div><div class="detail">{esc(timing)}</div></div>'
            )
        return f'<div class="go-stages">{"".join(cells)}</div>'

    def render(self):
        self.placeholder.markdown(self.html(), unsafe_allow_html=True)
