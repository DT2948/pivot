"""Rule and threshold based scoring helpers."""

from __future__ import annotations

from typing import Any

from pivot.models import Job, RuleScore, ScoredJob
from pivot.verification import detect_visa_signal

BLOCKED_ALERT_FAMILIES = {"sales", "legal", "finance", "product_management", "support"}
HARD_REJECTION_PATTERNS = [
    "no sponsorship",
    "no cpt",
    "no opt",
    "citizenship",
    "clearance",
    "without sponsorship",
]


def threshold_for(job: Job, settings: dict[str, Any], score_source: str) -> float:
    """Return the alert threshold for a job."""

    thresholds = settings.get("alert_thresholds", {})
    if score_source in {"rules_only", "rules_fallback"}:
        return float(
            thresholds.get(
                "rule_only_fallback_alert_threshold", thresholds.get("rules_only_fallback", 9.0)
            )
        )
    if job.verification_status in {"unverified", "failed"}:
        return float(thresholds.get("unverified_source", 9))
    if job.source_type == "curated_repo":
        return float(thresholds.get("curated_repo", 8))
    return float(thresholds.get("target_company", 7))


def final_alert_allowed(
    job: Job,
    rule: RuleScore,
    settings: dict[str, Any],
    *,
    score_source: str,
    gemini_valid: bool,
    gemini_text: str = "",
) -> tuple[bool, list[str]]:
    """Apply final hard gates that no scorer is allowed to bypass."""

    rejection_reasons = list(rule.rejection_reasons)
    role_family = rule.role_family
    if role_family == "fellowship_program" and not settings.get("allow_fellowship_alerts", False):
        rejection_reasons.append("fellowship/program roles are not allowed to alert by default")
    if role_family in BLOCKED_ALERT_FAMILIES:
        rejection_reasons.append(f"blocked alert role family: {role_family}")
    if _has_hard_rejection(rejection_reasons):
        rejection_reasons.append("hard rejection blocks alert")
    if gemini_text and detect_visa_signal(gemini_text) == "false":
        rejection_reasons.append(
            "Gemini assessment indicates sponsorship/citizenship/clearance concern"
        )
    if not rule.can_rule_alert and not gemini_valid:
        rejection_reasons.append("cannot rule-alert without a valid Gemini score")
    if rule.requires_gemini_review and (score_source != "gemini" or not gemini_valid):
        rejection_reasons.append("required Gemini review did not produce a valid score")
    return not rejection_reasons, rejection_reasons


def scored_from_rules(
    job: Job, rule: RuleScore, settings: dict[str, Any], source: str
) -> ScoredJob:
    """Convert a rule score into a final scored job."""

    threshold = threshold_for(job, settings, source)
    gate_allowed, final_rejections = final_alert_allowed(
        job,
        rule,
        settings,
        score_source=source,
        gemini_valid=False,
    )
    concerns = final_rejections.copy()
    if job.visa_signal == "unknown":
        concerns.append("visa sponsorship unknown")
    if rule.requires_gemini_review:
        concerns.append("requires Gemini review before alert")
    return ScoredJob(
        job=job,
        rule_score=rule.score,
        final_score=rule.score,
        score_source=source,
        fit_summary="Rule-based fit based on role family, seniority, location, and sponsorship signals.",
        matched_strengths=rule.reasons,
        concerns=concerns,
        visa_assessment=f"Visa signal: {job.visa_signal}",
        should_alert=rule.is_candidate
        and rule.can_rule_alert
        and rule.score >= threshold
        and gate_allowed,
        requires_gemini_review=rule.requires_gemini_review,
        can_rule_alert=rule.can_rule_alert,
        role_family=rule.role_family,
        rule_reasons=rule.reasons,
        rejection_reasons=final_rejections,
    )


def _has_hard_rejection(rejection_reasons: list[str]) -> bool:
    text = " ".join(rejection_reasons).lower()
    return any(pattern in text for pattern in HARD_REJECTION_PATTERNS)
