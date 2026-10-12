import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent


def _text(name, default=""):
    return os.getenv(name, default).strip().strip('"').strip("'")


def _number(name, default, cast=float):
    raw = _text(name)
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    endpoint: str
    api_version: str
    deployment: str
    prompt_file: Path
    data_dir: Path
    max_revisions: int
    asset_attempts: int
    min_score: int
    min_average: float
    brief_min_chars: int
    brief_max_chars: int
    daily_runs_per_client: int
    request_timeout: float
    strategist_temperature: float
    judge_temperature: float
    lead_temperature: float
    price_in_per_million: float
    price_out_per_million: float
    hourly_rate: float
    minutes_manual_draft: float
    minutes_manual_email: float
    minutes_manual_post: float
    minutes_manual_cta: float
    minutes_human_review: float
    target_clients: int
    model_label: str = "Growth OS Language Model"


def load_settings(require_llm=True):
    load_dotenv(ROOT / ".env")
    settings = Settings(
        api_key=_text("AZURE_OPENAI_API_KEY"),
        endpoint=_text("AZURE_OPENAI_ENDPOINT"),
        api_version=_text("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        deployment=_text("AZURE_DEPLOYMENT_NAME"),
        prompt_file=Path(_text("PROMPT_FILE", str(ROOT / "prompt.json"))),
        data_dir=Path(_text("GROWTH_OS_DATA_DIR", str(ROOT / "data"))),
        max_revisions=_number("MAX_REVISIONS", 3, int),
        asset_attempts=_number("ASSET_ATTEMPTS", 3, int),
        min_score=_number("JUDGE_MIN_SCORE", 7, int),
        min_average=_number("JUDGE_MIN_AVERAGE", 7.8),
        brief_min_chars=_number("BRIEF_MIN_CHARS", 15, int),
        brief_max_chars=_number("BRIEF_MAX_CHARS", 1500, int),
        daily_runs_per_client=_number("DAILY_RUNS_PER_CLIENT", 40, int),
        request_timeout=_number("LLM_TIMEOUT_SECONDS", 90.0),
        strategist_temperature=_number("STRATEGIST_TEMPERATURE", 0.7),
        judge_temperature=_number("JUDGE_TEMPERATURE", 0.0),
        lead_temperature=_number("LEAD_TEMPERATURE", 0.6),
        price_in_per_million=_number("PRICE_INPUT_PER_MILLION", 0.15),
        price_out_per_million=_number("PRICE_OUTPUT_PER_MILLION", 0.60),
        hourly_rate=_number("ROI_HOURLY_RATE", 60.0),
        minutes_manual_draft=_number("ROI_MINUTES_DRAFT", 90.0),
        minutes_manual_email=_number("ROI_MINUTES_EMAIL", 20.0),
        minutes_manual_post=_number("ROI_MINUTES_POST", 10.0),
        minutes_manual_cta=_number("ROI_MINUTES_CTA", 5.0),
        minutes_human_review=_number("ROI_MINUTES_REVIEW", 10.0),
        target_clients=_number("TARGET_CLIENTS", 12, int),
        model_label=_text("MODEL_DISPLAY_NAME", "Growth OS Language Model"),
    )
    if require_llm:
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_API_KEY", settings.api_key),
                ("AZURE_OPENAI_ENDPOINT", settings.endpoint),
                ("AZURE_DEPLOYMENT_NAME", settings.deployment),
            )
            if not value
        ]
        if missing:
            raise ConfigError("Missing required environment variables: " + ", ".join(missing))
    if settings.max_revisions < 1 or settings.asset_attempts < 1:
        raise ConfigError("MAX_REVISIONS and ASSET_ATTEMPTS must be at least 1")
    return settings
