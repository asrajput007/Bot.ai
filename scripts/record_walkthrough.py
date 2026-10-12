import argparse
import re
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {"width": 1600, "height": 1000}


def chapter(page, title):
    print(f"Recording: {title}", flush=True)
    page.evaluate(
        """title => {
            let card = document.getElementById("growth-os-chapter");
            if (!card) {
                card = document.createElement("div");
                card.id = "growth-os-chapter";
                Object.assign(card.style, {
                    position: "fixed",
                    top: "18px",
                    right: "24px",
                    zIndex: "2147483647",
                    padding: "10px 16px",
                    borderRadius: "10px",
                    background: "rgba(13, 18, 32, 0.92)",
                    color: "#f3f5fb",
                    border: "1px solid rgba(135, 155, 255, 0.45)",
                    boxShadow: "0 6px 24px rgba(0, 0, 0, 0.35)",
                    font: "600 15px system-ui, sans-serif",
                    pointerEvents: "none"
                });
                document.body.appendChild(card);
            }
            card.textContent = "GROWTH OS  /  " + title;
        }""",
        title,
    )
    page.wait_for_timeout(1200)


def click_tab(page, name):
    tab = page.get_by_role("tab", name=name)
    tab.wait_for(timeout=30000)
    tab.click(force=True)
    page.wait_for_timeout(500)


def settle(page, timeout=180000):
    page.wait_for_selector('[data-testid="stSidebar"]', timeout=timeout)
    page.wait_for_function(
        """() => !document.querySelector('[data-testid="stStatusWidget"]')
            && !document.querySelector('[data-testid="stSkeleton"]')""",
        timeout=timeout,
    )
    page.wait_for_timeout(700)


def go(page, base_url, path, title):
    page.goto(f"{base_url.rstrip('/')}/{path.lstrip('/')}")
    settle(page)
    chapter(page, title)


def choose(page, label, option):
    page.wait_for_function(
        """label => [...document.querySelectorAll('[data-testid="stSelectbox"]')]
            .some(widget => (widget.innerText || "").split("\\n")[0].trim() === label)""",
        arg=label,
        timeout=30000,
    )
    widgets = page.get_by_test_id("stSelectbox")
    widget = next(
        (
            widgets.nth(index)
            for index in range(widgets.count())
            if widgets.nth(index).inner_text().splitlines()[0].strip() == label
        ),
        None,
    )
    if widget is None:
        raise AssertionError(f"Selectbox not found: {label}")
    widget.click()
    choices = page.get_by_role("option", name=re.compile(option, re.I))
    choices.first.wait_for(timeout=30000)
    choices.first.click()
    settle(page)


def capture(page, base_url):
    page.goto(base_url)
    settle(page)
    chapter(page, "Overview and portfolio")

    go(page, base_url, "clients", "Client directory and onboarding")
    if not page.get_by_text("Northstar Demo Studio", exact=True).count():
        page.get_by_role("button", name="Add client").click()
        page.locator('input[aria-label="Company or client name"]').fill("Northstar Demo Studio")
        page.locator('input[aria-label="Founder or executive name"]').fill("Taylor Morgan")
        page.locator('input[aria-label="Professional role"]').fill("Founder and CEO")
        page.locator('input[aria-label="Industry and niche"]').fill("B2B software")
        page.get_by_role("button", name="Create client").click()
        settle(page)
        chapter(page, "New client workspace")
        page.get_by_role("button", name="All clients").click()
        settle(page)
    choose(page, "Active client", "Northwind")
    page.get_by_role("button", name="Open workspace").first.click()
    settle(page)
    chapter(page, "Brand profile and onboarding")
    click_tab(page, "Brand Profile")
    settle(page)
    reference = page.get_by_label("Approved reference examples")
    reference.fill("We helped a growing team make its customer onboarding more consistent.")
    page.get_by_role("button", name="Save brand profile").click()
    settle(page)
    for tab in ("Overview", "Content", "Calendar", "Campaigns", "Leads", "Analytics", "Activity History"):
        click_tab(page, tab)
        settle(page)
    page.get_by_role("button", name="All clients").click()
    settle(page)

    go(page, base_url, "campaigns", "Campaign planning")
    if not page.get_by_text("Northstar Growth Sprint", exact=True).count():
        page.get_by_role("button", name=re.compile("New campaign")).click()
        page.locator('input[aria-label="Campaign name"]').fill("Northstar Growth Sprint")
        page.locator('textarea[aria-label="Campaign objective"]').fill(
            "Build executive awareness and generate qualified discovery conversations."
        )
        page.locator('input[aria-label="Lead generation objective"]').fill("Book 10 discovery calls")
        page.get_by_role("button", name="Create campaign").click()
        settle(page)
    page.get_by_role("button", name="Open campaign").first.click(force=True)
    settle(page)
    chapter(page, "Campaign workspace")
    page.get_by_role("tab", name="Overview").wait_for(timeout=30000)
    for tab in ("Overview", "Strategy", "Assets", "Leads", "Schedule", "Analytics", "Activity"):
        click_tab(page, tab)
        settle(page)

    go(page, base_url, "studio", "Content strategy, judging and lead assets")
    if not page.locator("h3:has-text('Stage 1')").count():
        brief = page.locator('textarea[aria-label="Content brief"]')
        brief.fill(
            "Explain how a focused onboarding process helps B2B software teams turn product interest "
            "into a useful first customer outcome. Give practical advice for an operations leader and "
            "invite them to discuss improving their onboarding journey."
        )
        choose(page, "Campaign", "Northstar Growth Sprint")
        page.get_by_role("button", name="Generate Growth Assets").click()
        page.wait_for_selector("h3:has-text('Stage 1')", timeout=600000)
        settle(page, timeout=600000)
    chapter(page, "Three-stage content pipeline results")
    click_tab(page, re.compile("Emails"))
    settle(page)
    approve = page.get_by_role("button", name=re.compile("Approve$"))
    if approve.count():
        approve.first.click()
        settle(page)
        override = page.get_by_role("button", name="Approve anyway")
        if override.count():
            override.click()
            settle(page)
    page.get_by_text("Plan or publish").nth(1).click()
    page.get_by_role("button", name=re.compile("^(Plan|Update plan)$")).first.click()
    settle(page)
    click_tab(page, re.compile("Social"))
    settle(page)
    revision = page.get_by_role("button", name=re.compile("Request revision"))
    revision.first.click()
    feedback = page.locator('textarea[aria-label="What should change?"]:visible').first
    feedback.wait_for(state="visible", timeout=30000)
    feedback.fill(
        "Use a more specific opening and make the next step clearer."
    )
    page.get_by_role("button", name="Send request").first.click()
    settle(page)
    chapter(page, "Review, approval and publication planning")
    click_tab(page, re.compile("CTAs"))
    settle(page)
    if not page.get_by_text("Version history", exact=True).count():
        feedback = page.locator('textarea[aria-label="Feedback for the Content Strategist"]:visible').first
        feedback.fill("Tighten the opening and make the practical next step clearer.")
        page.get_by_role("button", name=re.compile("Revise Based on Feedback")).click()
        page.get_by_text("Version history", exact=True).wait_for(timeout=600000)
        settle(page, timeout=600000)
    chapter(page, "Version history and human revision")
    page.get_by_role("tab", name="Differences").scroll_into_view_if_needed()
    click_tab(page, "Differences")
    click_tab(page, re.compile(r"v1"))
    click_tab(page, re.compile("working"))
    page.get_by_role("button", name="Download full run as JSON").scroll_into_view_if_needed()
    page.wait_for_timeout(800)

    go(page, base_url, "calendar", "Content calendar")
    for view in ("Week", "List", "Month"):
        page.get_by_text(view, exact=True).click()
        settle(page)

    go(page, base_url, "leads", "Lead generation and follow-up")
    if not page.get_by_text("Jordan Lee", exact=True).count():
        page.get_by_role("button", name=re.compile("Add lead")).first.click()
        page.locator('input[aria-label="Prospect name"]').fill("Jordan Lee")
        page.locator('input[aria-label="Company"]').fill("Example Operations")
        page.locator('input[aria-label="Role"]').fill("VP of Operations")
        page.locator('input[aria-label="Business email"]').fill("jordan.lee@example.com")
        page.locator('input[aria-label="Source"]').fill("Content campaign")
        page.locator('textarea[aria-label="Notes"]').fill("Interested in improving the onboarding journey.")
        page.get_by_role("button", name="Add lead").last.click()
        settle(page)
    if page.get_by_text("Select a row to open the lead", exact=False).count():
        page.locator('[data-testid="stDataFrame"]').click(position={"x": 17, "y": 54})
        page.get_by_text("Pipeline stage", exact=True).wait_for(timeout=30000)
        settle(page)
    choose(page, "Pipeline stage", "Contacted")
    stage_update = page.get_by_role("button", name="Update stage")
    if not stage_update.is_disabled():
        stage_update.click()
        settle(page)
    activity_note = "Sent a follow-up after sharing the campaign resource."
    if not page.get_by_text(activity_note, exact=True).count():
        page.locator('textarea[aria-label="Note"]:visible').fill(activity_note)
        page.get_by_role("button", name="Log interaction").click()
        settle(page)
    chapter(page, "Lead lifecycle and activity tracking")

    go(page, base_url, "analytics", "Business outcomes and impact")
    for tab in ("Content and AI usage", "ROI model", "Business outcomes"):
        click_tab(page, tab)
        settle(page)

    go(page, base_url, "history", "Run history and auditability")
    page.get_by_text("Northstar", exact=False).first.wait_for()
    table = page.locator('[data-testid="stDataFrame"]').first
    table.click(position={"x": 17, "y": 54})
    page.get_by_role("button", name="Export run (JSON)").wait_for(timeout=30000)
    page.get_by_role("button", name="Export run (JSON)").first.scroll_into_view_if_needed()
    page.wait_for_timeout(1200)

    go(page, base_url, "settings", "Settings, policy and access")
    for tab in ("Pipeline policy", "Access", "Prompt library", "Integrations"):
        click_tab(page, tab)
        settle(page)
    chapter(page, "Growth OS walkthrough complete")
    page.wait_for_timeout(2200)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8502")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "recordings" / "growth-os-walkthrough.webm",
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    video = None
    failure = None
    with tempfile.TemporaryDirectory(prefix="growth-os-video-") as video_dir:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=video_dir,
                record_video_size=VIEWPORT,
            )
            page = context.new_page()
            page.on("pageerror", lambda error: print(f"Browser error: {error}"))
            video = page.video
            try:
                capture(page, args.url)
            except Exception as error:
                failure = error
            finally:
                context.close()
                browser.close()
            if video:
                shutil.copy2(video.path(), args.output)
    if failure:
        raise failure
    print(f"Walkthrough video saved to {args.output}")


if __name__ == "__main__":
    main()
