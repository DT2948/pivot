from __future__ import annotations

import pytest

from pivot.filtering import score_job
from pivot.gemini_scorer import normalize_gemini_score
from pivot.models import Job, RuleScore
from pivot.scoring import final_alert_allowed, scored_from_rules

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


def test_gemini_percent_style_scores_are_normalized() -> None:
    assert normalize_gemini_score(20) == 2.0
    assert normalize_gemini_score(30) == 3.0
    assert normalize_gemini_score(40) == 4.0
    assert normalize_gemini_score(85) == 8.5


def test_gemini_valid_decimal_score_is_preserved() -> None:
    assert normalize_gemini_score(8.7) == 8.7


@pytest.mark.parametrize("value", ["8.7", "bad", None, float("nan")])
def test_gemini_invalid_scores_fail(value: object) -> None:
    with pytest.raises(ValueError):
        normalize_gemini_score(value)


def test_fellowship_final_gate_blocks_gemini_alert_by_default() -> None:
    job = make_job("Anthropic Fellows Program", "AI systems fellowship.")
    rule = RuleScore(
        score=9.0,
        reasons=[],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=True,
        can_rule_alert=False,
        role_family="fellowship_program",
    )

    allowed, rejections = final_alert_allowed(
        job,
        rule,
        SETTINGS,
        score_source="gemini",
        gemini_valid=True,
        gemini_text="Strong fit.",
    )

    assert not allowed
    assert any("fellowship" in reason for reason in rejections)


def test_gemini_sponsorship_language_blocks_alert() -> None:
    job = make_job("Software Engineer I, Backend", "Entry level backend role.")
    rule = RuleScore(
        score=9.0,
        reasons=[],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=False,
        can_rule_alert=True,
        role_family="software_engineering",
    )

    allowed, rejections = final_alert_allowed(
        job,
        rule,
        SETTINGS,
        score_source="gemini",
        gemini_valid=True,
        gemini_text="The role has no visa sponsorship and must be authorized without sponsorship.",
    )

    assert not allowed
    assert any("sponsorship" in reason.lower() for reason in rejections)


def test_required_gemini_review_blocks_fallback_alert() -> None:
    job = make_job("Full-Stack Software Engineer, Reinforcement Learning", "ML systems.")
    rule = RuleScore(
        score=9.8,
        reasons=[],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=True,
        can_rule_alert=False,
        role_family="ml_ai_engineering",
    )

    allowed, rejections = final_alert_allowed(
        job,
        rule,
        SETTINGS,
        score_source="rules_fallback",
        gemini_valid=False,
    )

    assert not allowed
    assert any("required Gemini" in reason for reason in rejections)


def test_curated_repo_rule_only_score_8_9_can_alert_at_curated_threshold() -> None:
    settings = {"alert_thresholds": {"curated_repo_rule_only_alert_threshold": 8.5}}
    job = make_job(
        "Software Engineer New Grad - Production Infrastructure",
        "Infrastructure systems.",
        source_type="curated_repo",
    )
    rule = RuleScore(
        score=8.9,
        reasons=["new-grad", "production infrastructure"],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=False,
        can_rule_alert=True,
        role_family="systems_infrastructure",
    )

    scored = scored_from_rules(job, rule, settings, "rules_fallback")

    assert scored.should_alert


def test_curated_repo_rule_only_score_8_1_does_not_alert_at_curated_threshold() -> None:
    settings = {"alert_thresholds": {"curated_repo_rule_only_alert_threshold": 8.5}}
    job = make_job(
        "New Grad Software Engineer - Backend Rust",
        "Backend systems.",
        source_type="curated_repo",
    )
    rule = RuleScore(
        score=8.1,
        reasons=["new-grad", "backend", "Rust"],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=False,
        can_rule_alert=True,
        role_family="software_engineering",
    )

    scored = scored_from_rules(job, rule, settings, "rules_fallback")

    assert not scored.should_alert


def test_target_company_high_rule_score_without_gemini_does_not_alert() -> None:
    settings = {"alert_thresholds": {"target_company_rule_only_alert_threshold": 9.0}}
    job = make_job("Full-Stack Software Engineer, Reinforcement Learning", "ML systems.")
    rule = RuleScore(
        score=9.8,
        reasons=["software engineering", "AI/ML"],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=True,
        can_rule_alert=False,
        role_family="ml_ai_engineering",
    )

    scored = scored_from_rules(job, rule, settings, "rules_fallback")

    assert not scored.should_alert


def test_fellowship_still_blocked_with_curated_thresholds_present() -> None:
    settings = {
        "alert_thresholds": {
            "target_company_rule_only_alert_threshold": 9.0,
            "curated_repo_rule_only_alert_threshold": 8.5,
        }
    }
    job = make_job("Anthropic Fellows Program", "AI systems fellowship.")
    rule = RuleScore(
        score=9.9,
        reasons=["AI/ML"],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=True,
        can_rule_alert=False,
        role_family="fellowship_program",
    )

    scored = scored_from_rules(job, rule, settings, "rules_fallback")

    assert not scored.should_alert
