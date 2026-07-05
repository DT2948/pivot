from __future__ import annotations

from pivot.filtering import score_job
from pivot.models import Job

SETTINGS = {
    "allow_internships": False,
    "reject_us_citizenship_required": True,
    "reject_security_clearance_required": True,
}


def make_job(title: str, description: str, location: str | None = "New York, NY", **kwargs: object) -> Job:
    return Job(
        source="Test",
        source_type=str(kwargs.pop("source_type", "target_company")),
        source_priority=10,
        company="TestCo",
        external_id=title,
        title=title,
        location=location,
        url=f"https://example.com/{title.replace(' ', '-')}",
        description=description,
        repo_flags=list(kwargs.pop("repo_flags", [])),
        verification_status=str(kwargs.pop("verification_status", "verified")),  # type: ignore[arg-type]
    )


def test_positive_new_grad_backend_role() -> None:
    job = make_job("New Grad Software Engineer Backend", "Python distributed systems cloud role.")
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.score >= 7


def test_positive_systems_platform_role() -> None:
    job = make_job("Software Engineer I, Systems Platform", "Entry level infrastructure and storage.")
    assert score_job(job, SETTINGS).is_candidate


def test_positive_ai_ml_infrastructure_role() -> None:
    job = make_job("New Graduate AI/ML Infrastructure Engineer", "PyTorch ML systems platform work.")
    assert score_job(job, SETTINGS).is_candidate


def test_reject_senior_staff_principal_manager_roles() -> None:
    for title in ["Senior Software Engineer", "Staff Engineer", "Principal Engineer", "Engineering Manager"]:
        assert not score_job(make_job(title, "Backend platform systems."), SETTINGS).is_candidate


def test_reject_non_us_role() -> None:
    job = make_job("New Grad Software Engineer Backend", "Python systems.", location="Toronto, Canada")
    assert not score_job(job, SETTINGS).is_candidate


def test_reject_explicit_no_sponsorship() -> None:
    job = make_job("New Grad Software Engineer", "Must be authorized to work without sponsorship.")
    assert not score_job(job, SETTINGS).is_candidate


def test_reject_us_citizenship_required() -> None:
    job = make_job("New Grad Software Engineer", "U.S. citizenship required.")
    assert not score_job(job, SETTINGS).is_candidate


def test_reject_security_clearance_required() -> None:
    job = make_job("New Grad Software Engineer", "Active security clearance required.")
    assert not score_job(job, SETTINGS).is_candidate


def test_keep_unknown_sponsorship() -> None:
    job = make_job("New Grad Software Engineer Backend", "Python systems role.")
    assert score_job(job, SETTINGS).is_candidate


def test_repo_no_sponsorship_flag_not_hard_reject_unverified() -> None:
    job = make_job(
        "New Grad Software Engineer Backend",
        "Python systems role.",
        source_type="curated_repo",
        repo_flags=["no sponsorship"],
        verification_status="unverified",
    )
    score = score_job(job, SETTINGS)
    assert "repo no-sponsorship flag treated as unverified concern" in score.reasons
    assert "original posting indicates no sponsorship/citizenship/clearance issue" not in score.rejection_reasons
