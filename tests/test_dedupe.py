from __future__ import annotations

from pivot.dedupe import dedupe_jobs
from pivot.models import Job


def make_job(source_type: str, source_priority: int) -> Job:
    return Job(
        source="Direct" if source_type == "target_company" else "Repo",
        source_type=source_type,
        source_priority=source_priority,
        company="Acme",
        external_id=f"{source_type}-{source_priority}",
        title="New Grad Software Engineer",
        location="New York, NY",
        url=f"https://example.com/{source_type}",
    )


def test_same_job_across_sources_prefers_direct_company_source() -> None:
    jobs = dedupe_jobs([make_job("curated_repo", 1), make_job("target_company", 99)])
    assert len(jobs) == 1
    assert jobs[0].source_type == "target_company"
