from __future__ import annotations

from pivot.filtering import score_job
from pivot.models import Job
from pivot.scoring import scored_from_rules

SETTINGS = {"alert_thresholds": {"rule_only_fallback_alert_threshold": 9.0}}


def make_job(title: str, description: str, source_type: str = "target_company") -> Job:
    return Job(
        source="Test",
        source_type=source_type,
        source_priority=10,
        company="TestCo",
        external_id=title,
        title=title,
        location="New York, NY",
        url=f"https://example.com/{title.replace(' ', '-')}",
        description=description,
        verification_status="verified" if source_type == "target_company" else "unverified",
    )


def test_fellowship_rule_fallback_never_alerts() -> None:
    job = make_job("Anthropic Fellows Program, ML Systems & Performance", "ML systems performance.")
    rule = score_job(job, SETTINGS)
    scored = scored_from_rules(job, rule, SETTINGS, "rules_only")

    assert rule.is_candidate
    assert rule.requires_gemini_review
    assert not rule.can_rule_alert
    assert not scored.should_alert


def test_curated_new_grad_rule_fallback_can_alert_when_threshold_met() -> None:
    job = make_job(
        "Software Engineer New Grad - Production Infrastructure",
        "Infrastructure platform distributed systems backend Python.",
        source_type="curated_repo",
    )
    rule = score_job(job, SETTINGS)
    scored = scored_from_rules(job, rule, SETTINGS, "rules_only")

    assert rule.can_rule_alert
    assert scored.should_alert == (rule.score >= 9.0)
