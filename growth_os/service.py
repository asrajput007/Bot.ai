import hashlib
import logging
import threading
import time
import uuid
from dataclasses import replace

from . import guardrails, metrics, onboarding
from .access import AccessPolicy
from .config import load_settings
from .content import ContentRepo, deliverable_text
from .crm import CampaignRepo, LeadRepo
from .db import Database
from .errors import (
    BudgetExceededError,
    DuplicateRunError,
    GrowthOSError,
    InvalidInput,
    NotFoundError,
)
from .graph import build_graph, run_stream
from .llm import AzureLLM
from .profiles import ClientDirectory, SingleClientStore
from .prompts import load_store
from .schemas import Draft

TEXT_OPTIONS = ("content_type", "channel", "objective", "audience", "tone", "editorial_notes")
MIN_FEEDBACK_CHARS = 10
MAX_FEEDBACK_CHARS = 2000
log = logging.getLogger("growth_os.service")


class GrowthService:
    def __init__(self, settings=None, llm=None):
        self.settings = settings or load_settings()
        self.base_store = load_store(self.settings.prompt_file)
        self.store = self.base_store
        self.db = Database(self.settings.data_dir / "growth_os.db")
        self.directory = ClientDirectory(self.db, self.base_store)
        self.access = AccessPolicy(self.base_store.operators, self.base_store.operator_access, self.directory)
        self.content = ContentRepo(self.db)
        self.campaign_repo = CampaignRepo(self.db)
        self.lead_repo = LeadRepo(self.db)
        self.runs = metrics.RunStore(self.settings.data_dir)
        self._llm = llm or AzureLLM(self.settings)
        self._inflight = set()
        self._guard = threading.Lock()

    def operators(self):
        return self.access.operators()

    def _scope(self, user, client_id=None):
        self.access.validate_user(user)
        if client_id:
            self.access.require(user, client_id)
            return [client_id]
        return self.access.client_ids(user)

    def clients(self, user=None):
        if user is None:
            return self.directory.all()
        allowed = set(self._scope(user))
        return [profile for profile in self.directory.all() if profile.id in allowed]

    def profile(self, user, client_id):
        self.access.require(user, client_id)
        return self.directory.get(client_id)

    def client_overview(self, user, client_id):
        self.access.require(user, client_id)
        profile = self.directory.get(client_id)
        stats = self.content.stats(client_id)
        steps = self.directory.onboarding(profile, stats)
        done, total = onboarding.progress(steps)
        last = self.db.one("SELECT MAX(ts) AS ts FROM audit_events WHERE client_id=?", (client_id,))
        return {
            "profile": profile,
            "meta": self.directory.meta(client_id),
            "stats": stats,
            "steps": steps,
            "done": done,
            "total": total,
            "current_step": onboarding.current_step(steps),
            "campaigns": len(self.campaign_repo.list([client_id])),
            "leads": len(self.lead_repo.list([client_id])),
            "last_activity": (last or {}).get("ts") or "",
        }

    def client_cards(self, user):
        return [self.client_overview(user, profile.id) for profile in self.clients(user)]

    def save_profile(self, user, client_id, data):
        self.access.require(user, client_id)
        return self.directory.save(client_id, data, user)

    def create_client(self, user, data):
        self.access.validate_user(user)
        return self.directory.create(data, user)

    def set_client_meta(self, user, client_id, status=None, owner=None, notes=None):
        self.access.require(user, client_id)
        if owner and owner not in self.operators():
            raise InvalidInput("Owner must be a known operator.")
        self.directory.set_meta(client_id, user, status=status, owner=owner, notes=notes)

    def set_onboarding_step(self, user, client_id, key, done):
        overview = self.client_overview(user, client_id)
        step = next((item for item in overview["steps"] if item["key"] == key), None)
        if not step:
            raise InvalidInput("Unknown onboarding step.")
        if done and not step["available"]:
            raise InvalidInput("Complete the earlier onboarding steps first.")
        self.directory.set_manual_step(client_id, key, done, user)
        if key == "launch":
            self.directory.set_meta(client_id, user, status="active" if done else "onboarding")

    def _clean_options(self, profile, options):
        options = dict(options or {})
        cleaned = {key: str(options[key]).strip() for key in TEXT_OPTIONS if options.get(key)}
        cta = options.get("primary_cta") or profile.primary_cta
        if cta not in profile.cta_options():
            raise InvalidInput("Primary CTA must be one of the client's configured calls to action.")
        cleaned["primary_cta"] = cta
        campaign_id = options.get("campaign_id") or ""
        if campaign_id:
            campaign = self.campaign_repo.get(campaign_id)
            if not campaign or campaign["client_id"] != profile.id:
                raise InvalidInput("The selected campaign does not belong to this client.")
        cleaned["campaign_id"] = campaign_id
        limits = {"max_revisions": (1, 5, int), "min_score": (1, 10, int), "min_average": (1, 10, float)}
        for key, (low, high, cast) in limits.items():
            if options.get(key) is not None:
                value = cast(options[key])
                if not low <= value <= high:
                    raise InvalidInput(f"{key.replace('_', ' ').capitalize()} must be between {low} and {high}.")
                cleaned[key] = value
        return cleaned

    def _run_settings(self, options):
        overrides = {key: options[key] for key in ("max_revisions", "min_score", "min_average") if key in options}
        return replace(self.settings, **overrides)

    def run(self, user, client_id, brief, on_event=None, options=None, kind="generate", seed=None, parent_id=""):
        self.access.require(user, client_id)
        profile = self.directory.get(client_id)
        missing = profile.missing_for_run()
        if missing:
            raise InvalidInput("Complete the brand profile before generating content. Missing: " + ", ".join(missing) + ".")
        options = self._clean_options(profile, options)
        used = self.runs.runs_today(client_id)
        if used >= self.settings.daily_runs_per_client:
            raise BudgetExceededError(
                f"Daily run limit of {self.settings.daily_runs_per_client} reached for {profile.name}."
            )
        key = hashlib.sha1(f"{client_id}|{kind}|{parent_id}|{brief}".encode("utf-8")).hexdigest()
        with self._guard:
            if key in self._inflight:
                raise DuplicateRunError("An identical request is already running. Wait for it to finish.")
            self._inflight.add(key)
        try:
            return self._execute(user, profile, brief, on_event, options, kind, seed, parent_id)
        finally:
            with self._guard:
                self._inflight.discard(key)

    def _execute(self, user, profile, brief, on_event, options, kind, seed, parent_id):
        run_settings = self._run_settings(options)
        run_profile = profile.model_copy(update={"primary_cta": options["primary_cta"]})
        graph = build_graph(self._llm, SingleClientStore(self.base_store, run_profile), run_settings)
        initial = {
            "client_id": profile.id,
            "brief": brief,
            "parameters": {key: options[key] for key in TEXT_OPTIONS if key in options},
        }
        if seed:
            initial.update(draft=seed["draft"], feedback=seed["feedback"])
        run_id = uuid.uuid4().hex[:12]
        state = {}
        error = None
        started = time.perf_counter()
        try:
            run_stream(graph, initial, state, on_event)
        except GrowthOSError as exc:
            error = str(exc)
        except Exception:
            log.exception("Unexpected error during a pipeline run")
            error = "An unexpected error occurred. Details were written to the server log."
        total_seconds = time.perf_counter() - started
        record = metrics.build_record(
            run_id, user, profile, state, total_seconds, run_settings, error, kind, options.get("campaign_id", "")
        )
        if not error and state.get("status") in ("completed", "escalated") and state.get("draft"):
            package = self.content.save_package(
                client_id=profile.id,
                campaign_id=options.get("campaign_id", ""),
                run_id=run_id,
                brief=state["brief"],
                options=options,
                draft=state["draft"],
                assets=state.get("assets"),
                rounds=state.get("rounds", []),
                asset_issues=state.get("asset_issues", []),
                status=state["status"],
                actor=user,
                parent_id=parent_id,
            )
            record["package_id"] = package["id"]
        artifact = {
            "record": record,
            "brief": state.get("brief", brief),
            "options": options,
            "rounds": state.get("rounds", []),
            "draft": state.get("draft"),
            "assets": state.get("assets"),
            "asset_issues": state.get("asset_issues", []),
            "package_id": record["package_id"],
            "prompt_preview": state.get("prompts", {}).get("strategist", ""),
        }
        self.runs.append(record, artifact)
        self.db.log(user, profile.id, "pipeline_run", "run", run_id, f"{kind} {record['status']}")
        return artifact

    def revise(self, user, package_id, feedback, on_event=None):
        package = self._owned_package(user, package_id)
        cleaned = guardrails.check_free_text("Revision feedback", feedback, MAX_FEEDBACK_CHARS)
        if len(cleaned) < MIN_FEEDBACK_CHARS:
            raise InvalidInput("Revision feedback must describe what to change (at least 10 characters).")
        seed = {"draft": package["draft"], "feedback": cleaned}
        return self.run(
            user, package["client_id"], package["brief"], on_event, package["options"],
            kind="revise", seed=seed, parent_id=package_id,
        )

    def _owned_package(self, user, package_id):
        package = self.content.package(package_id)
        if not package:
            raise NotFoundError("Package not found.")
        self.access.require(user, package["client_id"])
        return package

    def packages(self, user, client_id=None, limit=100, selected_only=False):
        return self.content.packages(self._scope(user, client_id), limit, selected_only)

    def package(self, user, package_id):
        return self._owned_package(user, package_id)

    def versions(self, user, package_id):
        package = self._owned_package(user, package_id)
        return self.content.versions(package["root_id"])

    def select_version(self, user, package_id):
        self._owned_package(user, package_id)
        self.content.select_version(package_id, user)

    def deliverables(self, user, client_id=None, **filters):
        return self.content.deliverables(self._scope(user, client_id), **filters)

    def _owned_deliverable(self, user, deliverable_id):
        item = self.content.deliverable(deliverable_id)
        if not item:
            raise NotFoundError("Asset not found.")
        self.access.require(user, item["client_id"])
        return item

    def deliverable(self, user, deliverable_id):
        return self._owned_deliverable(user, deliverable_id)

    def edit_deliverable(self, user, deliverable_id, content):
        item = self._owned_deliverable(user, deliverable_id)
        updated = self.content.update_content(deliverable_id, content, user)
        profile = self.directory.get(item["client_id"])
        package = self.content.package(item["package_id"])
        allowed = guardrails.allowed_stats(
            profile, package["brief"], guardrails.draft_text(Draft.model_validate(package["draft"]))
        )
        warnings = guardrails.scan_text(deliverable_text(updated), profile, self.base_store.universal, allowed)
        return updated, warnings

    def approve(self, user, deliverable_id, override=False):
        self._owned_deliverable(user, deliverable_id)
        return self.content.set_approval(deliverable_id, "approved", user, override=override)

    def request_changes(self, user, deliverable_id, note):
        self._owned_deliverable(user, deliverable_id)
        return self.content.set_approval(deliverable_id, "changes_requested", user, note=note)

    def schedule(self, user, deliverable_id, when):
        self._owned_deliverable(user, deliverable_id)
        return self.content.schedule(deliverable_id, when, user)

    def unschedule(self, user, deliverable_id):
        self._owned_deliverable(user, deliverable_id)
        return self.content.unschedule(deliverable_id, user)

    def mark_published(self, user, deliverable_id, note=""):
        self._owned_deliverable(user, deliverable_id)
        return self.content.mark_published(deliverable_id, note, user)

    def _owned_campaign(self, user, campaign_id):
        campaign = self.campaign_repo.get(campaign_id)
        if not campaign:
            raise NotFoundError("Campaign not found.")
        self.access.require(user, campaign["client_id"])
        return campaign

    def campaigns(self, user, client_id=None, status=None, search=""):
        return self.campaign_repo.list(self._scope(user, client_id), status, search)

    def campaign(self, user, campaign_id):
        return self._owned_campaign(user, campaign_id)

    def create_campaign(self, user, client_id, **fields):
        self.access.require(user, client_id)
        return self.campaign_repo.create(client_id, user, **fields)

    def update_campaign(self, user, campaign_id, **fields):
        self._owned_campaign(user, campaign_id)
        return self.campaign_repo.update(campaign_id, user, **fields)

    def _check_lead_campaign(self, client_id, campaign_id):
        if campaign_id:
            campaign = self.campaign_repo.get(campaign_id)
            if not campaign or campaign["client_id"] != client_id:
                raise InvalidInput("The selected campaign does not belong to this client.")

    def leads(self, user, client_id=None, **filters):
        return self.lead_repo.list(self._scope(user, client_id), **filters)

    def _owned_lead(self, user, lead_id):
        lead = self.lead_repo.get(lead_id)
        if not lead:
            raise NotFoundError("Lead not found.")
        self.access.require(user, lead["client_id"])
        return lead

    def lead(self, user, lead_id):
        return self._owned_lead(user, lead_id)

    def create_lead(self, user, client_id, **fields):
        self.access.require(user, client_id)
        self._check_lead_campaign(client_id, fields.get("campaign_id", ""))
        if fields.get("owner") and fields["owner"] not in self.operators():
            raise InvalidInput("Owner must be a known operator.")
        return self.lead_repo.create(client_id, user, **fields)

    def update_lead(self, user, lead_id, **fields):
        lead = self._owned_lead(user, lead_id)
        self._check_lead_campaign(lead["client_id"], fields.get("campaign_id", ""))
        if fields.get("owner") and fields["owner"] not in self.operators():
            raise InvalidInput("Owner must be a known operator.")
        return self.lead_repo.update(lead_id, user, **fields)

    def set_lead_status(self, user, lead_id, status):
        self._owned_lead(user, lead_id)
        return self.lead_repo.set_status(lead_id, status, user)

    def log_lead_activity(self, user, lead_id, kind, note, deliverable_id=""):
        lead = self._owned_lead(user, lead_id)
        if deliverable_id:
            item = self._owned_deliverable(user, deliverable_id)
            if item["client_id"] != lead["client_id"]:
                raise InvalidInput("The selected asset belongs to a different client.")
        self.lead_repo.log_activity(lead_id, kind, note, user, deliverable_id)

    def lead_activity(self, user, lead_id):
        self._owned_lead(user, lead_id)
        return self.lead_repo.activity(lead_id)

    def delete_lead(self, user, lead_id):
        self._owned_lead(user, lead_id)
        self.lead_repo.delete(lead_id, user)

    def activity(self, user, client_id=None, limit=50):
        return self.db.activity(self._scope(user, client_id), limit)

    def run_records(self, user, client_id=None):
        allowed = set(self._scope(user, client_id))
        return [record for record in self.runs.load() if record["client_id"] in allowed]

    def run_artifact(self, user, run_id):
        artifact = self.runs.artifact(run_id)
        if not artifact:
            raise NotFoundError("Run output not found.")
        self.access.require(user, artifact["record"]["client_id"])
        return {key: value for key, value in artifact.items() if key != "prompt_preview"}

    def summary(self, user=None, client_id=None):
        records = self.run_records(user, client_id) if user else self.runs.load()
        return metrics.summarise(records, self.settings)

    def integrations(self):
        s = self.settings
        return [
            {"name": "AI content generation service", "configured": bool(s.api_key and s.endpoint and s.deployment),
             "detail": "Configured on the server. Connection details and credentials are never shown in the interface."},
            {"name": "LinkedIn publishing", "configured": False, "detail": "No integration. Approved posts are exported and recorded as manually published."},
            {"name": "X publishing", "configured": False, "detail": "No integration. Approved posts are exported and recorded as manually published."},
            {"name": "Email sending", "configured": False, "detail": "No sending integration. Outreach is copied or exported and logged manually."},
            {"name": "Engagement analytics", "configured": False, "detail": "Needs LinkedIn, X and email platform analytics APIs."},
            {"name": "CRM sync", "configured": False, "detail": "Leads live in the built-in lead tracker only."},
        ]
