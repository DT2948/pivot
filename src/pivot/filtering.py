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

POSITIVE_KEYWORDS = [
    "software engineer",
    "swe",
    "backend",
    "infrastructure",
    "systems",
    "platform",
    "distributed systems",
    "cloud",
    "ai",
    "ml",
    "machine learning",
    "data platform",
    "university graduate",
    "new grad",
    "new graduate",
    "early career",
    "entry level",
    "software engineer i",
    "2027 grad",
    "compiler",
    "performance",
    "storage",
    "networking",
    "databases",
]
NEGATIVE_KEYWORDS = [
    "senior",
    "staff",
    "principal",
    "manager",
    "director",
    "lead",
    "phd required",
    "5+ years",
    "7+ years",
    "internship",
    "co-op",
    "frontend-only",
    "mobile-only",
    "product manager",
    "program manager",
    "qa-only",
    "it support",
    "help desk",
    "hardware-only",
    "advanced degree required",
]
US_LOCATION_HINTS = [
    "united states",
    "usa",
    "u.s.",
    "remote-us",
    "remote us",
    "new york",
    "san francisco",
    "seattle",
    "austin",
    "boston",
    "california",
]
US_STATE_CODES = {"ca", "ny", "wa", "tx", "pa", "ma"}

def score_job(job: Job, settings: dict[str, Any] | None = None) -> RuleScore:
    """Apply deterministic filters and return a 0-10 rule score."""

    settings = settings or {}
    text = _job_text(job)
    lower = text.lower()
    reasons: list[str] = []
    rejections: list[str] = []
    score = 0.0

    positives = [kw for kw in POSITIVE_KEYWORDS if kw in lower]
    if positives:
        score += min(4.0, 1.2 + len(positives) * 0.55)
        reasons.append(f"role keywords: {', '.join(positives[:5])}")
    else:
        rejections.append("no strong software/backend/systems/AI role keyword")

    if _has_new_grad_signal(lower):
        score += 2.0
        reasons.append("new-grad or early-career signal")
    elif re.search(r"\b0\s*-\s*2\b|\b0-2\s+years|\b1\+?\s+years", lower):
        score += 1.0
        reasons.append("plausibly 0-2 years")
    elif job.source_type == "curated_repo":
        rejections.append("repo role lacks clear new-grad signal")

    if any(kw in lower for kw in ["backend", "systems", "infrastructure", "platform"]):
        score += 1.5
        reasons.append("backend/systems/infrastructure alignment")
    if any(kw in lower for kw in ["distributed", "cloud", "aws", "docker", "kubernetes"]):
        score += 1.0
        reasons.append("distributed/cloud infrastructure alignment")
    if any(kw in lower for kw in ["machine learning", "pytorch", "ml systems", "ai"]):
        score += 1.0
        reasons.append("AI/ML systems alignment")
    if any(kw in lower for kw in ["python", "c++", " c ", "networkx", "pytorch"]):
        score += 0.7
        reasons.append("matches candidate technical skills")

    for kw in NEGATIVE_KEYWORDS:
        if kw in lower:
            score -= 2.5
            rejections.append(f"negative keyword: {kw}")

    if not settings.get("allow_internships", False) and re.search(r"\bintern(ship)?\b|\bco-op\b", lower):
        rejections.append("internship/co-op while internships are disabled")

    if not _is_us_or_remote_us(job.location):
        score -= 2.0
        rejections.append("non-US or unclear non-US location")

    repo_text = " ".join(job.repo_flags).lower()
    if "closed" in repo_text:
        rejections.append("repo marks job as closed")
    if "advanced degree" in repo_text:
        rejections.append("repo marks advanced degree required")
    if "u.s. citizenship" in repo_text and settings.get("reject_us_citizenship_required", True):
        rejections.append("repo marks U.S. citizenship required")
    if "security clearance" in repo_text and settings.get("reject_security_clearance_required", True):
        rejections.append("repo marks security clearance required")
    if "no sponsorship" in repo_text:
        score -= 1.0
        reasons.append("repo no-sponsorship flag treated as unverified concern")

    visa_signal = job.visa_signal
    if visa_signal == "unknown":
        visa_signal = detect_visa_signal(job.description or text)
    if visa_signal == "false":
        rejections.append("original posting indicates no sponsorship/citizenship/clearance issue")
    elif visa_signal == "true":
        score += 1.0
        reasons.append("positive sponsorship signal")

    if settings.get("reject_us_citizenship_required", True) and requires_us_citizenship(text):
        rejections.append("U.S. citizenship required")
    if settings.get("reject_security_clearance_required", True) and requires_security_clearance(text):
        rejections.append("security clearance required")

    if job.source_type == "target_company":
        score += 0.5
        reasons.append("direct target-company source")
    elif job.verification_status != "verified":
        score -= 0.8
        reasons.append("unverified curated repo source")

    score = max(0.0, min(10.0, round(score, 2)))
    hard_rejections = [
        reason
        for reason in rejections
        if not reason.startswith("repo marks") or "no-sponsorship" not in reason
    ]
    is_candidate = score >= 5.5 and not hard_rejections
    return RuleScore(score=score, reasons=reasons, rejection_reasons=rejections, is_candidate=is_candidate)


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
    return any(
        phrase in lower
        for phrase in [
            "new grad",
            "new graduate",
            "university graduate",
            "early career",
            "entry level",
            "software engineer i",
            "2027",
            "2026",
        ]
    )


def _is_us_or_remote_us(location: str | None) -> bool:
    if not location:
        return True
    lower = location.lower()
    if "remote" in lower and ("us" in lower or "united states" in lower):
        return True
    if any(hint in lower for hint in US_LOCATION_HINTS):
        return True
    tokens = {token.lower() for token in re.findall(r"\b[A-Za-z]{2}\b", location)}
    return bool(tokens & US_STATE_CODES)






