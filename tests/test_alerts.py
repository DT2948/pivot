from __future__ import annotations

from pivot.alerts import alert_subject, build_alert_records, priority_group, sort_alerts
from pivot.dedupe import job_key
from pivot.models import Job, ScoredJob


def scored(company: str, source: str, source_type: str, score: float = 9.0) -> ScoredJob:
    job = Job(
        source=source,
        source_type=source_type,
        source_priority=10 if source_type == "target_company" else 60,
        company=company,
        external_id=f"{company}-{source}-{score}",
        title="Software Engineer New Grad - Backend Infrastructure",
        location="New York, NY",
        url=f"https://example.com/{company}/{source}/{score}",
        description="Build backend systems and AI/ML infrastructure.",
        verification_status="verified" if source_type == "target_company" else "unverified",
    )
    return ScoredJob(
        job=job,
        rule_score=score,
        final_score=score,
        score_source="rules_fallback",
        fit_summary="Strong match",
        matched_strengths=["software engineering", "backend"],
        visa_assessment="unknown",
        should_alert=True,
        rule_reasons=["software engineering", "new-grad", "backend", "infrastructure"],
    )


def test_google_direct_role_sorts_before_all_others() -> None:
    items = [
        scored("Anthropic", "Anthropic", "target_company", 10),
        scored("Google", "Google", "target_company", 8),
        scored("Nuro", "Simplify New Grad", "curated_repo", 10),
    ]

    assert sort_alerts(items)[0].job.company == "Google"


def test_google_curated_sorts_before_other_target_curated() -> None:
    google_curated = scored("Google", "Simplify New Grad", "curated_repo", 8)
    meta_curated = scored("Meta", "Simplify New Grad", "curated_repo", 10)

    assert sort_alerts([meta_curated, google_curated]) == [google_curated, meta_curated]


def test_direct_target_company_sorts_before_non_target_curated() -> None:
    target = scored("Microsoft", "Microsoft", "target_company", 8)
    curated = scored("Nuro", "Simplify New Grad", "curated_repo", 10)

    assert sort_alerts([curated, target]) == [target, curated]


def test_target_company_curated_sorts_before_non_target_curated() -> None:
    target_curated = scored("NVIDIA", "Simplify New Grad", "curated_repo", 8)
    non_target = scored("Nuro", "Simplify New Grad", "curated_repo", 10)

    assert sort_alerts([non_target, target_curated]) == [target_curated, non_target]


def test_subject_uses_google_priority_wording_when_google_alerts_exist() -> None:
    assert alert_subject([scored("Google", "Google", "target_company")]) == (
        "Pivot: 1 new Google-priority job alert(s)"
    )


def test_subject_uses_target_company_wording_for_non_google_target_alerts() -> None:
    assert alert_subject([scored("Anthropic", "Anthropic", "target_company")]) == (
        "Pivot: 1 new target-company job alert(s)"
    )


def test_subject_uses_strong_match_wording_for_only_non_target_curated() -> None:
    assert alert_subject([scored("Nuro", "Simplify New Grad", "curated_repo")]) == (
        "Pivot: 1 new strong job match(es)"
    )


def test_alert_records_mark_already_seen_alerts_not_emailed() -> None:
    item = scored("Google", "Google", "target_company")
    seen = {job_key(item.job): {"title": item.job.title}}

    records = build_alert_records([item], seen)

    assert records[0].was_seen_before
    assert not records[0].emailed
    assert records[0].skip_reason == "already_seen"
    assert priority_group(item) == "Google Priority"