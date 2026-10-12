import re

from .errors import GuardrailViolation
from .schemas import Draft, LeadAssets

INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+.{0,40}(instructions?|rules?|prompts?)",
        r"(reveal|show|print|repeat|leak|output)\s+.{0,40}(system|hidden|developer|initial)\s+(prompt|message|instructions?)",
        r"you\s+are\s+now\s+",
        r"\bjailbreak\b",
        r"</?\s*(system|brief|assistant)\s*>",
        r"override\s+.{0,30}(rules?|guardrails?|policy|policies)",
        r"(switch|change)\s+(to\s+)?(another|different|other)\s+client",
    )
]

ABSOLUTE_CLAIMS = re.compile(
    r"\b(guarantee[ds]?|risk[- ]free|overnight\s+(success|results?)|get\s+rich|no\s+effort|effortless(ly)?|instant(ly)?\s+(results?|growth|rich))\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
STAT_RE = re.compile(r"\$\s?\d[\d,.]*\s?[kmb]?\b|\b\d[\d,.]*\s?%|\b\d[\d,.]*\s?x\b", re.IGNORECASE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

DRAFT_WORDS = (120, 450)
EMAIL_SUBJECT_MAX = 70
EMAIL_WORDS = (40, 180)
LINKEDIN_MAX = 1300
X_MAX = 280
CTA_MAX = 80
EMAIL_COUNT = 2
CTA_COUNT = (3, 5)


def sanitize_brief(brief):
    cleaned = CONTROL_RE.sub("", brief or "")
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def check_brief(brief, min_chars, max_chars):
    cleaned = sanitize_brief(brief)
    issues = []
    if len(cleaned) < min_chars:
        issues.append(f"Brief is too short (minimum {min_chars} characters).")
    if len(cleaned) > max_chars:
        issues.append(f"Brief is too long (maximum {max_chars} characters).")
    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            issues.append("Brief contains instruction-override or prompt-extraction language.")
            break
    if issues:
        raise GuardrailViolation(issues)
    return cleaned


def _normalise_numbers(text):
    return re.sub(r"\s*(per\s?cent|percent)\b", "%", text, flags=re.IGNORECASE)


def _stat_tokens(text):
    return {
        re.sub(r"\s+", "", match.group(0)).lower().rstrip(".,")
        for match in STAT_RE.finditer(_normalise_numbers(text))
    }


def allowed_stats(client, brief, *extra):
    corpus = " ".join(
        [brief, *client.proof_points, *client.offers, client.positioning, *extra]
    )
    return _stat_tokens(corpus)


def scan_text(text, client, universal, allowed):
    issues = []
    lowered = text.lower()
    for phrase in {*(p.lower() for p in universal.banned_phrases), *(p.lower() for p in client.banned_phrases)}:
        if phrase and phrase in lowered:
            issues.append(f"Banned phrase used: '{phrase}'.")
    for topic in client.forbidden_topics:
        if topic.lower() in lowered:
            issues.append(f"Forbidden topic mentioned: '{topic}'.")
    for match in ABSOLUTE_CLAIMS.finditer(text):
        issues.append(f"Unsupported absolute claim: '{match.group(0)}'.")
    if EMAIL_RE.search(text):
        issues.append("Contains an email address that is not in the client profile.")
    if PHONE_RE.search(text):
        issues.append("Contains a phone number that is not in the client profile.")
    if URL_RE.search(text):
        issues.append("Contains a URL that is not in the client profile.")
    for token in sorted(_stat_tokens(text) - allowed):
        issues.append(f"Unverified statistic '{token}' is not in the client profile or brief.")
    return list(dict.fromkeys(issues))


def _words(text):
    return len(text.split())


def draft_text(draft):
    return "\n".join(
        [
            draft.headline,
            draft.body,
            draft.core_message,
            draft.suggested_hook,
            *draft.key_messages,
            *draft.audience_pain_points,
        ]
    )


def check_free_text(label, text, max_chars):
    cleaned = sanitize_brief(text)
    issues = []
    if len(cleaned) > max_chars:
        issues.append(f"{label} is too long (maximum {max_chars} characters).")
    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            issues.append(f"{label} contains instruction-override or prompt-extraction language.")
            break
    if issues:
        raise GuardrailViolation(issues)
    return cleaned


def check_parameters(parameters, max_chars=400):
    cleaned = {}
    for key, value in (parameters or {}).items():
        if isinstance(value, str) and value.strip():
            cleaned[key] = check_free_text(key.replace("_", " ").title(), value, max_chars if key != "editorial_notes" else 1000)
    return cleaned


def check_draft(draft, client, universal, brief):
    issues = []
    count = _words(draft.body)
    low, high = DRAFT_WORDS
    if count < low or count > high:
        issues.append(f"Draft body has {count} words; it must be between {low} and {high}.")
    if not draft.headline.strip():
        issues.append("Draft headline is empty.")
    if not 2 <= len(draft.key_messages) <= 5:
        issues.append("Draft must carry between 2 and 5 key messages.")
    if client.primary_cta.lower() not in draft.body.lower():
        issues.append(f"Draft must close with the client's primary CTA: '{client.primary_cta}'.")
    issues.extend(scan_text(draft_text(draft), client, universal, allowed_stats(client, brief)))
    return issues


def assets_text(assets):
    parts = []
    for email in assets.emails:
        parts.extend([email.subject, email.preview, email.body, email.cta])
    for post in assets.social_posts:
        parts.extend([post.text, *post.hashtags])
    parts.extend(assets.ctas)
    return "\n".join(parts)


def post_length(post):
    return len(post.text) + sum(len(tag) + 2 for tag in post.hashtags)


def check_assets(assets: LeadAssets, client, universal, brief, draft: Draft):
    issues = []
    if len(assets.emails) != EMAIL_COUNT:
        issues.append(f"Exactly {EMAIL_COUNT} emails are required, got {len(assets.emails)}.")
    for index, email in enumerate(assets.emails, 1):
        if not email.subject.strip() or len(email.subject) > EMAIL_SUBJECT_MAX:
            issues.append(f"Email {index} subject must be 1 to {EMAIL_SUBJECT_MAX} characters.")
        words = _words(email.body)
        if not EMAIL_WORDS[0] <= words <= EMAIL_WORDS[1]:
            issues.append(f"Email {index} body has {words} words; it must be between {EMAIL_WORDS[0]} and {EMAIL_WORDS[1]}.")
        if not email.cta.strip():
            issues.append(f"Email {index} has no CTA.")
    platforms = [post.platform for post in assets.social_posts]
    if platforms.count("linkedin") != 1 or platforms.count("x") != 1 or len(platforms) != 2:
        issues.append("Exactly one LinkedIn post and one X post are required.")
    for post in assets.social_posts:
        limit = LINKEDIN_MAX if post.platform == "linkedin" else X_MAX
        if post_length(post) > limit:
            issues.append(
                f"{post.platform} post is {post_length(post)} characters including hashtags, over the {limit} limit. "
                f"Rewrite it to at most {limit - 30} characters, keeping the core message and CTA."
            )
    low, high = CTA_COUNT
    if not low <= len(assets.ctas) <= high:
        issues.append(f"{low} to {high} CTAs are required, got {len(assets.ctas)}.")
    for cta in assets.ctas:
        if len(cta) > CTA_MAX:
            issues.append(f"CTA exceeds {CTA_MAX} characters: '{cta[:30]}...'.")
    if not any(client.primary_cta.lower() in cta.lower() for cta in assets.ctas):
        issues.append(f"At least one CTA must contain '{client.primary_cta}' verbatim.")
    allowed = allowed_stats(client, brief, draft_text(draft))
    issues.extend(scan_text(assets_text(assets), client, universal, allowed))
    return issues


def passes_policy(verdict, automatic_issues, min_score, min_average):
    values = verdict.scores.values()
    if automatic_issues:
        return False
    return min(values) >= min_score and sum(values) / len(values) >= min_average
