from __future__ import annotations

from pivot.dedupe import job_key
from pivot.models import Job, ScoredJob
from pivot.state import has_meaningful_change, update_seen


def scored(description: str) -> ScoredJob:
    job = Job(
        source="Test",
        source_type="target_company",
        source_priority=10,
        company="Acme",
        external_id="1",
        title="New Grad Software Engineer",
        location="New York, NY",
        url="https://example.com/job",
        description=description,
    )
    return ScoredJob(
        job=job,
        rule_score=9,
        final_score=9,
        score_source="rules_only",
        fit_summary="Good",
        should_alert=True,
        visa_assessment="unknown",
    )


def test_state_deduplication_and_alerted_at() -> None:
    item = scored("first description")
    seen = update_seen({}, [item], {job_key(item.job)})
    assert seen[job_key(item.job)]["times_seen"] == 1
    assert seen[job_key(item.job)]["alerted_at"] is not None


def test_changed_description_triggers_rescoring() -> None:
    first = scored("first description")
    seen = update_seen({}, [first], set())
    second = scored("changed description")
    assert has_meaningful_change(seen[job_key(first.job)], second)
