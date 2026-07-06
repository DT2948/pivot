from __future__ import annotations

from typing import Any

from pivot.gemini_scorer import GeminiScorer
from pivot.models import Job, RuleScore


class FakeGeminiScorer(GeminiScorer):
    def __init__(self, outcomes: list[Any], max_jobs: int = 5) -> None:
        super().__init__(
            {
                "gemini": {
                    "enabled": True,
                    "max_jobs_per_run": max_jobs,
                    "min_rule_score_before_gemini": 0,
                    "curated_min_rule_score_before_gemini": 0,
                    "max_unavailable_failures": 2,
                },
                "alert_thresholds": {
                    "target_company": 7,
                    "curated_repo": 8,
                    "rule_only_fallback_alert_threshold": 9,
                },
            },
            {},
        )
        self.api_key = "test-key"
        self.outcomes = outcomes
        self.attempts = 0

    def _build_client(self) -> object:
        return object()

    def _score_one(self, client: object, job: Job) -> dict[str, Any]:
        self.attempts += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_pair(
    index: int, *, required: bool = True, source_type: str = "target_company"
) -> tuple[Job, RuleScore]:
    job = Job(
        source="Test",
        source_type=source_type,
        source_priority=10,
        company="Acme",
        external_id=str(index),
        title=f"Software Engineer {index}",
        location="New York, NY",
        url=f"https://example.com/{index}",
        description="Backend systems.",
        verification_status="verified" if source_type == "target_company" else "unverified",
    )
    rule = RuleScore(
        score=9.0 - index * 0.01,
        reasons=["new-grad"],
        rejection_reasons=[],
        is_candidate=True,
        requires_gemini_review=required,
        can_rule_alert=not required,
        role_family="software_engineering",
    )
    return job, rule


def good_payload(score: float = 8.0) -> dict[str, Any]:
    return {
        "score": score,
        "fit_summary": "Good fit.",
        "matched_strengths": ["backend"],
        "concerns": [],
        "visa_assessment": "unknown",
        "should_alert": True,
    }


def test_max_gemini_jobs_limits_attempts() -> None:
    scorer = FakeGeminiScorer([good_payload()] * 10, max_jobs=5)
    scored = scorer.score([make_pair(i) for i in range(10)])

    assert scorer.attempts == 5
    assert sum(item.score_source == "gemini" for item in scored) == 5
    assert sum(item.score_source == "rules_fallback" for item in scored) == 5


def test_failed_calls_count_toward_cap() -> None:
    scorer = FakeGeminiScorer([RuntimeError("boom")] * 5 + [good_payload()], max_jobs=5)
    scored = scorer.score([make_pair(i) for i in range(6)])

    assert scorer.attempts == 5
    assert all(item.score_source == "rules_fallback" for item in scored)


def test_429_stops_remaining_gemini_scoring() -> None:
    scorer = FakeGeminiScorer([RuntimeError("429 RESOURCE_EXHAUSTED"), good_payload()], max_jobs=5)
    scored = scorer.score([make_pair(i) for i in range(3)])

    assert scorer.attempts == 1
    assert all(item.score_source == "rules_fallback" for item in scored)


def test_required_gemini_fallback_candidates_do_not_alert_after_failure() -> None:
    scorer = FakeGeminiScorer([RuntimeError("503 UNAVAILABLE")] * 2, max_jobs=5)
    scored = scorer.score([make_pair(i, required=True) for i in range(3)])

    assert scorer.attempts == 2
    assert all(item.score_source == "rules_fallback" for item in scored)
    assert all(not item.should_alert for item in scored)


def test_curated_rule_only_candidates_still_use_rule_gates() -> None:
    scorer = FakeGeminiScorer([], max_jobs=0)
    scored = scorer.score([make_pair(0, required=False, source_type="curated_repo")])

    assert scorer.attempts == 0
    assert scored[0].score_source == "rules_fallback"
    assert scored[0].can_rule_alert
