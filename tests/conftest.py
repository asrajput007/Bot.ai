from dataclasses import replace

import pytest

from growth_os.config import load_settings
from growth_os.llm import Usage
from growth_os.prompts import load_store
from growth_os.schemas import Draft, Email, JudgeScores, JudgeVerdict, LeadAssets, SocialPost

SETTINGS = load_settings(require_llm=False)
STORE = load_store(SETTINGS.prompt_file)


def good_scores(value=9):
    return JudgeScores(brand_voice=value, audience_fit=value, clarity=value, compliance=value, lead_potential=value)


def make_draft(client, extra=""):
    body = " ".join(["Finance leaders told me the same thing again and again about slow settlement."] * 14)
    body += f" {extra} Next step: {client.primary_cta}."
    return Draft(
        headline="Settlement speed is a margin decision",
        body=body,
        key_messages=["Speed protects margin", "Transparency builds trust"],
    )


def make_assets(client, extra=""):
    body = " ".join(["Here is a practical idea you can apply this week to your own team."] * 6)
    return LeadAssets(
        emails=[
            Email(subject="A practical idea for your team", preview="One idea, five minutes", body=body + extra, cta=client.primary_cta),
            Email(subject="Following up on the idea", preview="A quick follow up", body=body, cta=client.primary_cta),
        ],
        social_posts=[
            SocialPost(platform="linkedin", text="A short founder story about what we learned.", hashtags=["leadership"]),
            SocialPost(platform="x", text="One lesson from this quarter.", hashtags=["growth"]),
        ],
        ctas=[client.primary_cta, "Read the story", "Talk to our team"],
    )


class FakeLLM:
    def __init__(self, client, verdicts, draft_extra="", asset_extras=("",)):
        self.client = client
        self.verdicts = list(verdicts)
        self.draft_extra = draft_extra
        self.asset_extras = list(asset_extras)
        self.calls = []

    def structured(self, schema, system, user, temperature):
        self.calls.append((schema.__name__, system, user))
        usage = Usage(input_tokens=1000, output_tokens=500, seconds=0.01)
        if schema is Draft:
            return make_draft(self.client, self.draft_extra), usage
        if schema is JudgeVerdict:
            scores = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
            issues = [] if min(scores.values()) >= 7 else ["Voice is generic."]
            return JudgeVerdict(scores=scores, issues=issues, revision_instructions="Sharpen the voice." if issues else ""), usage
        extra = self.asset_extras.pop(0) if len(self.asset_extras) > 1 else self.asset_extras[0]
        return make_assets(self.client, extra), usage


@pytest.fixture
def client():
    return STORE.clients[0]


@pytest.fixture
def settings(tmp_path):
    return replace(SETTINGS, data_dir=tmp_path)


def service_with(settings, llm):
    from growth_os.service import GrowthService

    return GrowthService(settings=settings, llm=llm)


BRIEF = "Explain why settlement speed matters for exporters this quarter."
GOOD = good_scores(9)
BAD = good_scores(4)
