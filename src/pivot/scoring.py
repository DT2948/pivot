"""Rule and threshold based scoring helpers."""

from __future__ import annotations

from typing import Any

from pivot.models import Job, RuleScore, ScoredJob


def threshold_for(job: Job, settings: dict[str, Any], score_source: str) -> float:
    """Return the alert threshold for a job."""

    thresholds = settings.get("alert_thresholds", {})
    if score_source in {"rules_only", "rules_fallback"}:
        return float(thresholds.get("rules_only_fallback", 8.5))
    if job.verification_status in {"unverified", "failed"}:
        return float(thresholds.get("unverified_source", 9))
    if job.source_type == "curated_repo":
        return float(thresholds.get("curated_repo", 8))
    return float(thresholds.get("target_company", 7))


def scored_from_rules(job: Job, rule: RuleScore, settings: dict[str, Any], source: str) -> ScoredJob:
    """Convert a rule score into a final scored job."""

    threshold = threshold_for(job, settings, source)
    concerns = rule.rejection_reasons.copy()
    if job.visa_signal == "unknown":
        concerns.append("visa sponsorship unknown")
    return ScoredJob(
        job=job,
        rule_score=rule.score,
        final_score=rule.score,
        score_source=source,
        fit_summary="Rule-based fit based on role, seniority, location, and sponsorship signals.",
        matched_strengths=rule.reasons,
        concerns=concerns,
        visa_assessment=f"Visa signal: {job.visa_signal}",
        should_alert=rule.is_candidate and rule.score >= threshold,
    )
