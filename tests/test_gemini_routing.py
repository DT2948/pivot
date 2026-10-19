from __future__ import annotations

from typing import Any

import pytest

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


def test_google_then_other_targets_then_curated_by_fit_with_two_attempts():
    pairs = [make_pair(i) for i in range(5)]
    for (job, _rule), company in zip(
        pairs, ("Acme", "Oracle", "Google", "Intel", "AMD"), strict=True
    ):
        job.company = company
    pairs[0][0].source_type = "curated_repo"
    pairs[1][1].score = 8
    pairs[3][1].score = 9.5
    pairs[4][1].score = 7
    scorer = FakeGeminiScorer([good_payload(), good_payload()], max_jobs=2)
    results = scorer.score(pairs)
    assert [x.job.company for x in results if x.score_source == "gemini"] == ["Google", "Intel"]
    assert scorer.attempts == 2


def test_ineligible_google_never_consumes_capacity():
    bad_job, bad_rule = make_pair(0)
    bad_job.company = "Google"
    bad_rule.is_candidate = False
    bad_rule.rejection_reasons = ["advanced degree required"]
    good_job, good_rule = make_pair(1)
    good_job.company = "AMD"
    scorer = FakeGeminiScorer([good_payload()], max_jobs=2)
    results = scorer.score([(bad_job, bad_rule), (good_job, good_rule)])
    assert scorer.attempts == 1
    assert [x.job.company for x in results if x.score_source == "gemini"] == ["AMD"]


def test_duplicate_posting_uses_one_attempt():
    pair = make_pair(0)
    duplicate = (pair[0].model_copy(), pair[1].model_copy())
    scorer = FakeGeminiScorer([good_payload()], max_jobs=2)
    assert len(scorer.score([pair, duplicate])) == 1
    assert scorer.attempts == 1


def test_reuses_valid_assessment_and_reapplies_current_rule_gates():
    from pivot.dedupe import job_key
    from pivot.state import update_seen

    pair = make_pair(0)
    scorer = FakeGeminiScorer([good_payload()], max_jobs=2)
    first = scorer.score([pair])
    scorer.seen = update_seen({}, first, set())
    assert scorer.seen[job_key(pair[0])]["assessment_cache"]
    scorer.score([pair])
    assert scorer.attempts == 1
    pair[1].is_candidate = False
    pair[1].rejection_reasons = ["degree mismatch"]
    assert not scorer.score([pair])[0].should_alert
    assert scorer.attempts == 1


def test_changed_profile_invalidates_assessment_cache():
    from pivot.state import update_seen

    pair = make_pair(0)
    scorer = FakeGeminiScorer([good_payload(), good_payload()], max_jobs=2)
    scorer.seen = update_seen({}, scorer.score([pair]), set())
    scorer.profile = {"interests": "new context"}
    scorer.score([pair])
    assert scorer.attempts == 2


def test_incomplete_assessment_falls_back_without_caching():
    scorer = FakeGeminiScorer([{"score": 9}], max_jobs=2)
    result = scorer.score([make_pair(0)])[0]
    assert result.score_source == "rules_fallback"
    assert result.assessment_cache is None


def test_delivered_unchanged_job_does_not_spend_review_budget():
    from pivot.dedupe import job_key
    from pivot.scoring import scored_from_rules
    from pivot.state import update_seen

    pair = make_pair(0)
    scorer = FakeGeminiScorer([], max_jobs=2)
    previous = scored_from_rules(*pair, scorer.settings, "rules_fallback")
    scorer.seen = update_seen({}, [previous], {job_key(pair[0])})
    scorer.score([pair])
    assert scorer.attempts == 0


def test_required_target_review_precedes_optional_google_review():
    google, optional = make_pair(0, required=False)
    google.company = "Google"
    target, required = make_pair(1)
    target.company = "Oracle"
    scorer = FakeGeminiScorer([good_payload()], max_jobs=1)
    results = scorer.score([(google, optional), (target, required)])
    assert [x.job.company for x in results if x.score_source == "gemini"] == ["Oracle"]


def test_changed_job_invalidates_assessment_cache():
    from pivot.state import update_seen

    pair = make_pair(0)
    scorer = FakeGeminiScorer([good_payload(), good_payload()], max_jobs=2)
    scorer.seen = update_seen({}, scorer.score([pair]), set())
    pair[0].description = "Meaningfully changed backend responsibilities."
    scorer.score([pair])
    assert scorer.attempts == 2


@pytest.mark.parametrize(
    "filename", ["gemini_scorer.py", "filtering.py", "scoring.py", "verification.py", "targets.py"]
)
def test_prompt_and_scoring_source_changes_invalidate_cache(monkeypatch, tmp_path, filename):
    from pivot import gemini_scorer
    from pivot.state import update_seen

    # Copy the real files, then change only temporary copies; no repository mutation.
    copies = []
    for source in gemini_scorer.SCORING_CONTEXT_FILES:
        target = tmp_path / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        copies.append(target)
    monkeypatch.setattr(gemini_scorer, "SCORING_CONTEXT_FILES", tuple(copies))
    pair = make_pair(0)
    first = FakeGeminiScorer([good_payload()])
    seen = update_seen({}, first.score([pair]), set())
    unchanged = FakeGeminiScorer([])
    unchanged.seen = seen
    unchanged.score([pair])
    assert unchanged.attempts == 0

    changed = tmp_path / filename
    text = changed.read_text(encoding="utf-8")
    if filename == "gemini_scorer.py":
        text = text.replace("equally important.", "equally important; updated preference.")
    else:
        text += "\n# Scoring policy changed.\n"
    changed.write_text(text, encoding="utf-8")
    updated = FakeGeminiScorer([good_payload(7)])
    updated.seen = seen
    result = updated.score([pair])[0]
    assert updated.attempts == 1
    assert result.final_score == 7


def test_pre_audit_cache_cannot_override_current_preferences():
    from pivot.dedupe import job_key

    pair = make_pair(0)
    scorer = FakeGeminiScorer([good_payload(7)])
    scorer.seen = {
        job_key(pair[0]): {
            "alerted_at": None,
            "assessment_cache": {
                "signature": "old-version-2-signature",
                "payload": good_payload(10),
            },
        }
    }
    assert scorer.score([pair])[0].final_score == 7
    assert scorer.attempts == 1


def test_scoring_fingerprint_is_stable_across_checkout_line_endings(monkeypatch, tmp_path):
    from pivot import gemini_scorer

    source = tmp_path / "gemini_scorer.py"
    monkeypatch.setattr(gemini_scorer, "SCORING_CONTEXT_FILES", (source,))
    source.write_bytes(b"prompt = 'same'\nrules = 'same'\n")
    linux = FakeGeminiScorer([])
    source.write_bytes(b"prompt = 'same'\r\nrules = 'same'\r\n")
    windows = FakeGeminiScorer([])
    assert linux._assessment_signature(make_pair(0)[0]) == windows._assessment_signature(
        make_pair(0)[0]
    )
