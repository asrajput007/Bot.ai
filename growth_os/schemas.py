from typing import Literal

from pydantic import BaseModel, Field


class Draft(BaseModel):
    headline: str = Field(description="Hook headline for the piece")
    body: str = Field(description="Full marketing copy, plain text with paragraph breaks. Must not repeat the key messages list.")
    key_messages: list[str] = Field(description="Two to five core messages the copy carries")
    campaign_objective: str = Field(default="", description="What this piece should achieve for the client")
    audience_pain_points: list[str] = Field(default_factory=list, description="Two to four pains of the target audience addressed by the piece")
    core_message: str = Field(default="", description="The single message the audience should remember")
    content_angle: str = Field(default="", description="The angle or narrative frame used")
    suggested_hook: str = Field(default="", description="The opening line or hook")
    recommended_format: str = Field(default="", description="Best format and channel for this piece")
    content_pillars: list[str] = Field(default_factory=list, description="Client content pillars this piece supports")
    distribution_recommendations: list[str] = Field(default_factory=list, description="How to distribute and repurpose the piece")
    primary_cta: str = Field(default="", description="The primary call to action used in the closing")


class JudgeScores(BaseModel):
    brand_voice: int = Field(ge=1, le=10)
    audience_fit: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    compliance: int = Field(ge=1, le=10)
    lead_potential: int = Field(ge=1, le=10)

    def values(self):
        return list(self.model_dump().values())


class JudgeVerdict(BaseModel):
    scores: JudgeScores
    strengths: list[str] = Field(default_factory=list, description="What is working and should be kept")
    issues: list[str] = Field(default_factory=list, description="What needs improvement")
    required_revisions: list[str] = Field(default_factory=list, description="Must-fix changes before approval")
    optional_refinements: list[str] = Field(default_factory=list, description="Nice-to-have improvements")
    revision_instructions: str = ""


class Email(BaseModel):
    subject: str
    preview: str
    body: str
    cta: str


class SocialPost(BaseModel):
    platform: Literal["linkedin", "x"]
    text: str
    hashtags: list[str] = Field(default_factory=list)


class LeadAssets(BaseModel):
    emails: list[Email]
    social_posts: list[SocialPost]
    ctas: list[str]
