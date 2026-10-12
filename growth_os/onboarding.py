STEPS = (
    {"key": "record", "label": "Create client record", "kind": "auto", "hint": "Create the client in the directory."},
    {"key": "company", "label": "Capture company and founder details", "kind": "auto", "hint": "Add founder, role and industry in Brand Profile."},
    {"key": "audience", "label": "Define target audience", "kind": "auto", "hint": "Describe the target audience in Brand Profile."},
    {"key": "goals", "label": "Capture business goals", "kind": "auto", "hint": "Add at least one business goal in Brand Profile."},
    {"key": "voice", "label": "Configure brand voice", "kind": "auto", "hint": "Describe the brand voice and positioning in Brand Profile."},
    {"key": "pillars", "label": "Define content pillars", "kind": "auto", "hint": "Add content pillars in Brand Profile."},
    {"key": "reference", "label": "Add approved reference material", "kind": "auto", "hint": "Paste approved example posts or emails in Brand Profile."},
    {"key": "channels", "label": "Configure channels and integrations", "kind": "manual", "hint": "Confirm channels. Publishing integrations are not configured, so publishing is manual."},
    {"key": "strategy", "label": "Generate initial content strategy", "kind": "auto", "hint": "Run the pipeline in Content Studio."},
    {"key": "samples", "label": "Generate sample assets", "kind": "auto", "hint": "Complete one pipeline run that passes the quality gate."},
    {"key": "approved", "label": "Review and approve initial assets", "kind": "auto", "hint": "Approve at least one asset."},
    {"key": "launch", "label": "Mark the workspace ready for launch", "kind": "manual", "hint": "Available once every earlier step is complete."},
)

MANUAL_KEYS = tuple(step["key"] for step in STEPS if step["kind"] == "manual")


def evaluate(profile, manual, stats):
    auto = {
        "record": True,
        "company": bool(profile.founder and profile.industry and profile.role),
        "audience": bool(profile.audience),
        "goals": bool(profile.business_goals),
        "voice": bool(profile.voice and profile.positioning),
        "pillars": bool(profile.content_pillars),
        "reference": bool(profile.reference_material),
        "strategy": stats.get("packages", 0) > 0,
        "samples": stats.get("passed_packages", 0) > 0,
        "approved": stats.get("approved", 0) > 0,
    }
    steps = []
    for step in STEPS:
        done = auto[step["key"]] if step["kind"] == "auto" else bool(manual.get(step["key"]))
        steps.append({**step, "done": done})
    earlier_done = all(step["done"] for step in steps if step["key"] != "launch")
    for step in steps:
        if step["key"] == "launch":
            step["available"] = earlier_done
        else:
            step["available"] = True
    return steps


def progress(steps):
    done = sum(1 for step in steps if step["done"])
    return done, len(steps)


def current_step(steps):
    for step in steps:
        if not step["done"]:
            return step
    return None
