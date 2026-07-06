"""Rule-based filtering and scoring."""

from __future__ import annotations

import re
from typing import Any

from pivot.models import Job, RuleScore
from pivot.verification import (
    detect_visa_signal,
    requires_security_clearance,
    requires_us_citizenship,
)

ROLE_POSITIVE_PATTERNS: list[tuple[str, str, float]] = [
    ("software engineering", r"\bsoftware\s+engineer(?:ing)?\b|\bswe\b", 1.8),
    (
        "new-grad",
        r"\bnew\s+grad(?:uate)?\b|\buniversity\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b",
        3.0,
    ),
    ("early-career", r"\bearly\s+career\b|\bentry\s+level\b|\bsoftware\s+engineer\s+i\b", 1.8),
    ("backend", r"\bback\s*end\b|\bbackend\b", 1.5),
    ("Rust", r"\brust\b", 1.0),
    ("performance", r"\bperformance\b", 1.2),
    ("compiler engineering", r"\bcompiler\s+engineer(?:ing)?\b", 2.2),
    ("compiler", r"\bcompiler\b", 1.2),
    ("production infrastructure", r"\bproduction\s+infrastructure\b", 2.0),
    ("infrastructure", r"\binfrastructure\b", 1.3),
    ("platform", r"\bplatform\b", 1.0),
    ("systems", r"\bsystems?\b", 1.0),
    ("distributed systems", r"\bdistributed\s+systems?\b", 1.2),
    ("ML infrastructure", r"\bml\s+infrastructure\b|\bai\s+infrastructure\b", 1.2),
    (
        "AI/ML",
        r"\bai\b|\bml\b|\bmachine\s+learning\b|\bml\s+systems?\b|\breinforcement\s+learning\b",
        0.8,
    ),
    ("cloud", r"\bcloud\b|\baws\b|\bdocker\b|\bkubernetes\b|\bcontainers?\b", 0.7),
    ("data platform", r"\bdata\s+platform\b", 0.9),
    ("storage/networking/databases", r"\bstorage\b|\bnetworking\b|\bdatabases?\b", 0.7),
    ("Python/C++/PyTorch", r"\bpython\b|\bc\+\+\b|\bpytorch\b|\bnetworkx\b", 0.5),
]

TITLE_SENIORITY_NEGATIVES = [
    ("senior", r"\bsenior\+?\b"),
    ("staff", r"\bstaff\+?\b"),
    ("principal", r"\bprincipal\b"),
    ("manager", r"\bmanager\b"),
    ("director", r"\bdirector\b"),
    ("lead", r"\blead\b"),
    ("head of", r"\bhead\s+of\b"),
]

OTHER_HARD_NEGATIVES = [
    ("frontend-only", r"\bfrontend-only\b|\bfront-end only\b"),
    ("mobile-only", r"\bmobile-only\b|\bmobile only\b"),
    ("QA-only", r"\bqa-only\b|\bqa only\b"),
    ("IT support", r"\bit\s+support\b|\bhelp\s+desk\b"),
    ("hardware-only", r"\bhardware-only\b|\bhardware only\b"),
    ("advanced degree required", r"\bphd\s+required\b|\badvanced\s+degree\s+required\b"),
]

TARGET_COMPANIES = {"anthropic", "nvidia", "tesla", "google", "microsoft", "meta", "apple"}
NON_TARGET_HARD_REJECT_FAMILIES = {"sales", "legal", "product_management", "support"}
NON_RULE_ALERT_FAMILIES = {
    "sales",
    "legal",
    "finance",
    "product_management",
    "support",
    "fellowship_program",
    "research_scientist",
    "security_engineering",
}
RULE_ALERT_FAMILIES = {
    "software_engineering",
    "systems_infrastructure",
    "ml_ai_engineering",
    "data_engineering",
}

EXPERIENCE_REQUIREMENT_RE = re.compile(
    r"(?:requirements?|qualifications?|minimum qualifications?|basic qualifications?)"
    r"[\s\S]{0,700}?\b(?:3\+|4\+|5\+|6\+|7\+|8\+|9\+|10\+|"
    r"3\s+or\s+more|4\s+or\s+more|5\s+or\s+more|7\s+or\s+more|"
    r"3\s+years?|4\s+years?|5\s+years?|7\s+years?)",
    re.I,
)
TITLE_EXPLICIT_EARLY_CAREER_RE = re.compile(
    r"\bnew\s+grad(?:uate)?\b|\buniversity\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b|\bearly\s+career\b",
    re.I,
)
BACHELORS_ACCEPTED_RE = re.compile(
    r"\bbachelor(?:'s|s)?\b|\bb\.?s\.?\b|\bundergraduate\b|"
    r"equivalent\s+practical\s+experience",
    re.I,
)
ADVANCED_DEGREE_TITLE_PATTERNS: list[tuple[str, str]] = [
    ("doctoral/postdoctoral role", r"\bdoctoral\b|\bdoctorate\b|\bpostdoc(?:toral)?\b"),
    ("PhD-specific role", r"\bph\.?d\.?\b|\bphd\s+internship\b|\bphd\s+university\s+grad"),
    (
        "Master's-specific role",
        r"\bmaster'?s\b|\bmasters\b|\bm\.?s\.?\b|\bmaster'?s\s+university\s+grad",
    ),
]
ADVANCED_DEGREE_EXCLUSIVE_PATTERNS: list[tuple[str, str]] = [
    ("doctoral/postdoctoral role", r"\bdoctoral\b|\bdoctorate\b|\bpostdoc(?:toral)?\b"),
    ("advanced-degree-only role", r"\badvanced\s+degree\s+required\b"),
    (
        "Master's/PhD-specific role",
        r"currently\s+enrolled\s+in\s+a?\s*(?:master'?s|masters|ph\.?d\.?)",
    ),
    ("Master's/PhD-specific role", r"pursuing\s+a?\s*(?:master'?s|masters|ph\.?d\.?)"),
    (
        "PhD-specific role",
        r"\bph\.?d\.?\s+(?:required|internship|university\s+grad|candidate|program)\b",
    ),
    ("Master's-specific role", r"\bmaster'?s\s+(?:required|university\s+grad|candidate|program)\b"),
    (
        "advanced-degree-only role",
        r"minimum\s+qualifications?[\s\S]{0,300}?\b(?:master'?s|masters|ph\.?d\.?)\b",
    ),
    (
        "graduate research role",
        r"\bgraduate\s+research\s+role\b|\bresearch\s+scientist[\s\S]{0,120}\bph\.?d\.?\b",
    ),
]

US_STATE_CODES = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}
US_STATE_NAMES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
    "district of columbia",
}
US_LOCATION_PHRASES = [
    r"\bunited\s+states\b",
    r"\bu\.s\.a?\.?\b",
    r"\busa\b",
    r"\bus\b",
    r"\bremote\s*(?:-|in|,)?\s*(?:usa|u\.s\.?|us|united\s+states)\b",
    r"\bremote-friendly,?\s+united\s+states\b",
]
US_CITY_ALIASES = [
    r"\bsf\b",
    r"\bsan\s+francisco\b",
    r"\bnyc\b",
    r"\bnew\s+york\s+city\b",
    r"\bla\b",
    r"\blos\s+angeles\b",
    r"\bbay\s+area\b",
    r"\bdc\b",
    r"\bwashington,?\s+dc\b",
    r"\bmountain\s+view\b",
    r"\braleigh\b",
    r"\bjacksonville\b",
    r"\bchicago\b",
    r"\bdenver\b",
]
NON_US_ONLY_HINTS = [
    "canada",
    "toronto",
    "vancouver",
    "montreal",
    "london",
    "united kingdom",
    "uk",
    "india",
    "singapore",
    "australia",
    "germany",
    "france",
    "netherlands",
    "ireland",
    "japan",
]


def score_job(job: Job, settings: dict[str, Any] | None = None) -> RuleScore:
    """Apply deterministic filters and return a 0-10 rule score."""

    settings = settings or {}
    text = _job_text(job)
    lower = text.lower()
    title_lower = job.title.lower()
    description = job.description or ""
    role_family = classify_role_family(job)
    direct_target_company = _is_direct_target_company(job)
    strong_new_grad = has_strong_new_grad_signal(job, settings)
    title_clear_engineering = _title_is_clear_engineering(job.title)
    reasons: list[str] = [f"role_family: {role_family}"]
    rejections: list[str] = []
    score = 0.0

    matched_positive = False
    for label, pattern, weight in ROLE_POSITIVE_PATTERNS:
        if re.search(pattern, lower, re.I):
            matched_positive = True
            score += weight
            reasons.append(label)

    if not matched_positive:
        rejections.append("no strong software/backend/systems/AI role keyword")

    if re.search(r"\bsoftware\s+engineer\b", title_lower, re.I) and re.search(
        r"\bnew\s+grad(?:uate)?\b", title_lower, re.I
    ):
        score += 1.2
        reasons.append("new-grad software engineer title alignment")

    if re.search(r"\bnew\s+grad(?:uate)?\b", title_lower, re.I) and re.search(
        r"\bperformance\b", title_lower, re.I
    ):
        score += 0.9
        reasons.append("new-grad performance title alignment")

    if re.search(r"\b0\s*-\s*2\b|\b0-2\s+years\b|\b1\+?\s+years\b", lower):
        score += 0.8
        reasons.append("plausibly 0-2 years")
    elif re.search(r"\buniversity\s+hire\b|\bgraduate\s+program\b", lower):
        score += 0.8
        reasons.append("early-career hiring program signal")
    elif job.source_type == "curated_repo" and not strong_new_grad:
        rejections.append("repo role lacks clear new-grad signal")

    for label, pattern in TITLE_SENIORITY_NEGATIVES:
        if re.search(pattern, title_lower, re.I):
            score -= 3.0
            rejections.append(f"title seniority mismatch: {label}")

    for label, pattern in OTHER_HARD_NEGATIVES:
        if re.search(pattern, lower, re.I):
            score -= 2.5
            rejections.append(f"negative keyword: {label}")

    degree_rejection = _advanced_degree_rejection_reason(job)
    if degree_rejection:
        score -= 4.0
        rejections.append(degree_rejection)

    if EXPERIENCE_REQUIREMENT_RE.search(description) and not TITLE_EXPLICIT_EARLY_CAREER_RE.search(
        job.title
    ):
        score -= 2.5
        rejections.append("years-of-experience mismatch")

    if not settings.get("allow_internships", False) and re.search(
        r"\bintern(ship)?\b|\bco-op\b", title_lower
    ):
        rejections.append("internship/co-op while internships are disabled")

    if not is_us_location(job.location):
        score -= 2.0
        rejections.append("non-US or unclear non-US location")

    if role_family in NON_TARGET_HARD_REJECT_FAMILIES:
        score -= 5.0
        rejections.append(f"non-target role family: {role_family}")
    elif role_family == "finance":
        score -= 3.0
        reasons.append("finance role family requires human/Gemini review")

    repo_text = " ".join(job.repo_flags).lower()
    if "closed" in repo_text:
        rejections.append("repo marks job as closed")
    if "advanced degree" in repo_text:
        rejections.append("repo marks advanced degree required")
    if "u.s. citizenship" in repo_text and settings.get("reject_us_citizenship_required", True):
        rejections.append("repo marks U.S. citizenship required")
    if "security clearance" in repo_text and settings.get(
        "reject_security_clearance_required", True
    ):
        rejections.append("repo marks security clearance required")
    if "no sponsorship" in repo_text:
        score -= 1.0
        reasons.append("repo no-sponsorship flag treated as unverified concern")

    if not direct_target_company:
        visa_signal = job.visa_signal
        if visa_signal == "unknown":
            visa_signal = detect_visa_signal(job.description or text)
        if visa_signal == "false":
            rejections.append(
                "original posting indicates no sponsorship/citizenship/clearance issue"
            )
        elif visa_signal == "true":
            score += 1.0
            reasons.append("positive sponsorship signal")

        if settings.get("reject_us_citizenship_required", True) and requires_us_citizenship(text):
            rejections.append("U.S. citizenship required")
        if settings.get("reject_security_clearance_required", True) and requires_security_clearance(
            text
        ):
            rejections.append("security clearance required")

    if job.source_type == "target_company":
        score += 0.5
        reasons.append("direct target-company source")
        if job.company.lower() == "google" or job.source.lower() == "google":
            reasons.append("Google direct source")
        if job.company.lower() == "meta" or job.source.lower() == "meta":
            reasons.append("Meta direct source")
        if job.company.lower() == "microsoft" or job.source.lower() == "microsoft":
            reasons.append("Microsoft direct source")
        if re.search(r"\buniversity\s+grad(?:uate)?\b", lower, re.I):
            reasons.append("university graduate signal")
        if re.search(
            r"\bnew\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b|\bearly\s+career\b", lower, re.I
        ):
            reasons.append("undergraduate new-grad signal")
    elif job.verification_status != "verified":
        score -= 0.4
        reasons.append("unverified curated repo source")

    score = max(0.0, min(10.0, round(score, 2)))
    hard_rejections = [
        reason
        for reason in rejections
        if not reason.startswith("repo marks") or "no-sponsorship" not in reason
    ]
    can_rule_alert = _can_rule_alert(
        job=job,
        role_family=role_family,
        strong_new_grad=strong_new_grad,
        title_clear_engineering=title_clear_engineering,
        hard_rejections=hard_rejections,
    )
    requires_gemini_review = _requires_gemini_review(
        job=job,
        role_family=role_family,
        can_rule_alert=can_rule_alert,
        strong_new_grad=strong_new_grad,
        title_clear_engineering=title_clear_engineering,
    )
    is_candidate = score >= 5.0 and not hard_rejections
    if (
        role_family == "fellowship_program"
        and job.source_type == "target_company"
        and not hard_rejections
    ):
        is_candidate = True
    if role_family == "finance" and title_clear_engineering and not hard_rejections:
        is_candidate = score >= 3.5
    return RuleScore(
        score=score,
        reasons=reasons,
        rejection_reasons=rejections,
        is_candidate=is_candidate,
        requires_gemini_review=requires_gemini_review,
        can_rule_alert=can_rule_alert,
        role_family=role_family,
    )


def classify_role_family(job: Job) -> str:
    """Classify a job into a broad role family using title-first matching."""

    title = job.title.lower()
    description = (job.description or "").lower()

    if re.search(r"\bfellows?\s+program\b|\bfellowship\b", title):
        return "fellowship_program"
    if re.search(r"\bcommercial\s+counsel\b|\bcounsel\b|\blegal\b|\battorney\b|\blawyer\b", title):
        return "legal"
    if re.search(r"\baccount\s+executive\b|\bstrategic\s+account\b|\bsales\b|\brenewals?\b", title):
        return "sales"
    if re.search(r"\bfinance\b|\bfinancial\b|\baccounting\b", title):
        return "finance"
    if re.search(r"\bproduct\s+management\b|\bproduct\s+manager\b", title):
        return "product_management"
    if re.search(r"\bsupport\b|\bcustomer\s+success\b", title) and not re.search(
        r"\bdeveloper\s+support\s+engineer\b|\bsupport\s+engineering\b", title
    ):
        return "support"
    if re.search(r"\bresearch\s+scientist\b|\bscientist\b", title):
        return "research_scientist"
    if re.search(r"\bsecurity\b", title):
        if _title_is_software_heavy(title):
            return "systems_infrastructure"
        return "security_engineering"
    if re.search(r"\bresearch\s+engineer\b", title):
        return "research_engineering"
    if re.search(r"\bdata\s+engineer\b|\bdata\s+platform\b", title):
        return "data_engineering"
    if re.search(
        r"\bml\b|\bai\b|\bmachine\s+learning\b|\breinforcement\s+learning\b|\bmodel\b", title
    ) and re.search(
        r"\bengineer\b|\bsoftware\b|\bsystems?\b|\binfrastructure\b|\bplatform\b", title
    ):
        return "ml_ai_engineering"
    if (
        re.search(r"\bsoftware\s+engineer\b", title)
        and re.search(r"\bbackend\b", title)
        and not re.search(
            r"\binfrastructure\b|\bplatform\b|\bsystems?\b|\bcompiler\b|\bperformance\b", title
        )
    ):
        return "software_engineering"
    if re.search(
        r"\binfrastructure\b|\bplatform\b|\bsystems?\b|\bcompiler\b|\bperformance\b", title
    ) and re.search(r"\bengineer\b|\bsoftware\b", title):
        return "systems_infrastructure"
    if re.search(r"\bsoftware\s+engineer\b|\bfull-?stack\b|\bbackend\b", title):
        return "software_engineering"

    if re.search(
        r"\bsoftware\b|\binfrastructure\b|\bplatform\b|\bdistributed\s+systems\b", description
    ):
        return "software_engineering"
    return "unknown"


def has_strong_new_grad_signal(job: Job, settings: dict[str, Any] | None = None) -> bool:
    """Return true for explicit new-grad, early-career, or configured grad-year signals."""

    settings = settings or {}
    text = _job_text(job).lower()
    patterns = [
        r"\bnew\s+grad(?:uate)?\b",
        r"\buniversity\s+grad(?:uate)?\b",
        r"\bnew\s+college\s+grad\b",
        r"\bentry\s+level\b",
        r"\bearly\s+career\b",
        r"\bsoftware\s+engineer\s+i\b",
        r"\bcompiler\s+engineer\s+new\s+grad\b",
        r"\b0\s*-\s*2\b|\b0-2\s+years\b",
        r"\buniversity\s+hire\b",
        r"\bgraduate\s+program\b",
        r"\b2027\b",
    ]
    if settings.get("allow_2026_new_grad", True):
        patterns.append(r"\b2026\b")
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def is_us_location(location: str | None) -> bool:
    """Return true when a location string clearly includes at least one US location."""

    if not location:
        return True
    normalized = _normalize_location(location)
    parts = [
        part.strip()
        for part in re.split(r"\s*(?:\||/|;|\bor\b|\band\b)\s*", normalized)
        if part.strip()
    ]
    parts = parts or [normalized]
    has_us = any(_location_part_is_us(part) for part in parts)
    has_non_us = any(_location_part_is_non_us(part) for part in parts)
    return has_us or not has_non_us and False


def _advanced_degree_rejection_reason(job: Job) -> str | None:
    title = job.title.lower()
    description = (job.description or "").lower()
    for reason, pattern in ADVANCED_DEGREE_TITLE_PATTERNS:
        if re.search(pattern, title, re.I):
            return reason

    for reason, pattern in ADVANCED_DEGREE_EXCLUSIVE_PATTERNS:
        if not re.search(pattern, description, re.I):
            continue
        if "minimum" in pattern and BACHELORS_ACCEPTED_RE.search(description):
            continue
        return reason
    return None


def _is_direct_target_company(job: Job) -> bool:
    return job.source_type == "target_company" and job.company.lower() in TARGET_COMPANIES


def _can_rule_alert(
    job: Job,
    role_family: str,
    strong_new_grad: bool,
    title_clear_engineering: bool,
    hard_rejections: list[str],
) -> bool:
    if hard_rejections:
        return False
    if role_family in NON_RULE_ALERT_FAMILIES:
        return False
    if role_family not in RULE_ALERT_FAMILIES:
        return False
    if job.source_type == "curated_repo":
        return strong_new_grad
    if job.source_type == "target_company":
        return strong_new_grad
    return strong_new_grad or title_clear_engineering


def _requires_gemini_review(
    job: Job,
    role_family: str,
    can_rule_alert: bool,
    strong_new_grad: bool,
    title_clear_engineering: bool,
) -> bool:
    if role_family in NON_RULE_ALERT_FAMILIES or role_family in {"research_engineering", "unknown"}:
        return True
    if job.source_type == "target_company" and not strong_new_grad:
        return True
    return not can_rule_alert


def _title_is_clear_engineering(title: str) -> bool:
    lower = title.lower()
    if (
        classify_role_family(
            Job(
                source="classification",
                source_type="internal",
                company="classification",
                external_id=title,
                title=title,
                url="https://example.com",
            )
        )
        in RULE_ALERT_FAMILIES
    ):
        return True
    return bool(
        re.search(
            r"\bsoftware\s+engineer\b|\bbackend\b|\bsystems?\s+engineer\b|\bml\s+engineer\b", lower
        )
    )


def _title_is_software_heavy(title: str) -> bool:
    return bool(
        re.search(
            r"\bsoftware\b|\binfrastructure\b|\bsystems?\b|\bdistributed\b|\bbackend\b|\bcompiler\b",
            title,
            re.I,
        )
    )


def _location_part_is_us(part: str) -> bool:
    lower = part.lower().strip()
    if any(re.search(pattern, lower, re.I) for pattern in US_LOCATION_PHRASES):
        return True
    if any(re.search(pattern, lower, re.I) for pattern in US_CITY_ALIASES):
        return True
    if any(state in lower for state in US_STATE_NAMES):
        return True
    tokens = {token.lower() for token in re.findall(r"\b[A-Za-z]{2}\b", part)}
    return bool(tokens & US_STATE_CODES)


def _location_part_is_non_us(part: str) -> bool:
    lower = part.lower()
    return any(re.search(rf"\b{re.escape(hint)}\b", lower) for hint in NON_US_ONLY_HINTS)


def _normalize_location(location: str) -> str:
    normalized = location.replace("Remote-Friendly", "Remote Friendly")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _job_text(job: Job) -> str:
    return " ".join(
        part
        for part in [
            job.company,
            job.title,
            job.location or "",
            job.department or "",
            job.description or "",
            " ".join(job.repo_flags),
        ]
        if part
    )


def _has_new_grad_signal(lower: str) -> bool:
    return bool(
        re.search(
            r"\bnew\s+grad(?:uate)?\b|\buniversity\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b|"
            r"\bearly\s+career\b|\bentry\s+level\b|\bsoftware\s+engineer\s+i\b|\b0\s*-\s*2\b|\b0-2\s+years\b|\buniversity\s+hire\b|\bgraduate\s+program\b|\b2027\b|\b2026\b",
            lower,
            re.I,
        )
    )
