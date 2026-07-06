from __future__ import annotations

from pivot.filtering import score_job
from pivot.models import Job

SETTINGS = {
    "allow_internships": False,
    "reject_us_citizenship_required": True,
    "reject_security_clearance_required": True,
}


def make_job(
    title: str, description: str, location: str | None = "New York, NY", **kwargs: object
) -> Job:
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
    job = make_job(
        "Software Engineer I, Systems Platform", "Entry level infrastructure and storage."
    )
    assert score_job(job, SETTINGS).is_candidate


def test_positive_ai_ml_infrastructure_role() -> None:
    job = make_job(
        "New Graduate AI/ML Infrastructure Engineer", "PyTorch ML systems platform work."
    )
    assert score_job(job, SETTINGS).is_candidate


def test_reject_senior_staff_principal_manager_roles() -> None:
    for title in [
        "Senior Software Engineer",
        "Staff Engineer",
        "Principal Engineer",
        "Engineering Manager",
    ]:
        assert not score_job(make_job(title, "Backend platform systems."), SETTINGS).is_candidate


def test_reject_non_us_role() -> None:
    job = make_job(
        "New Grad Software Engineer Backend", "Python systems.", location="Toronto, Canada"
    )
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
    assert (
        "original posting indicates no sponsorship/citizenship/clearance issue"
        not in score.rejection_reasons
    )


def test_is_us_location_examples_from_dry_run() -> None:
    examples = [
        "Raleigh, NC",
        "Jacksonville, FL",
        "Washington, DC",
        "Chicago, IL",
        "Denver, CO",
        "SF",
        "NYC",
        "LA",
        "Mountain View, CA",
        "Remote in USA",
        "Remote - US",
        "Remote-Friendly, United States",
        "United States",
        "Toronto, Canada / NYC",
    ]
    for location in examples:
        job = make_job("New Grad Software Engineer Backend", "Python systems.", location=location)
        assert "non-US or unclear non-US location" not in score_job(job, SETTINGS).rejection_reasons


def test_title_seniority_not_triggered_by_description_staff_or_lead() -> None:
    job = make_job(
        "Full-Stack Software Engineer, Reinforcement Learning",
        "Work with staff across research teams, show leadership, and lead projects in Python systems.",
    )
    score = score_job(job, SETTINGS)
    assert not any("staff" in reason or "lead" in reason for reason in score.rejection_reasons)


def test_staff_software_engineer_rejected_from_title() -> None:
    job = make_job("Staff Software Engineer, Backend", "Backend platform systems.")
    assert not score_job(job, SETTINGS).is_candidate


def test_engineering_manager_rejected_from_title() -> None:
    job = make_job("Engineering Manager, Platform", "Platform systems.")
    assert not score_job(job, SETTINGS).is_candidate


def test_team_lead_rejected_from_title() -> None:
    job = make_job("Software Engineer, Team Lead", "Backend platform systems.")
    assert not score_job(job, SETTINGS).is_candidate


def test_lead_projects_description_not_hard_rejected() -> None:
    job = make_job("Software Engineer", "You will lead projects on backend platform systems.")
    assert not any("lead" in reason for reason in score_job(job, SETTINGS).rejection_reasons)


def test_new_grad_backend_rust_score_floor() -> None:
    job = make_job("New Grad Software Engineer - Backend Rust", "Backend platform systems.")
    assert score_job(job, SETTINGS).score >= 6.5


def test_new_grad_performance_score_floor() -> None:
    job = make_job(
        "Software Engineer New Grad - Performance", "Performance engineering for systems."
    )
    assert score_job(job, SETTINGS).score >= 6.5


def test_compiler_new_grad_score_floor() -> None:
    job = make_job("Compiler Engineer New Grad", "Compiler and performance engineering.")
    assert score_job(job, SETTINGS).score >= 6.0


def test_production_infrastructure_new_grad_score_floor() -> None:
    job = make_job(
        "Software Engineer New Grad - Production Infrastructure",
        "Infrastructure, platform, and distributed systems.",
    )
    assert score_job(job, SETTINGS).score >= 7.0


def test_curated_new_grad_backend_rust_score_floor() -> None:
    job = make_job(
        "New Grad Software Engineer - Backend Rust",
        "Backend platform systems.",
        source_type="curated_repo",
        verification_status="unverified",
    )
    assert score_job(job, SETTINGS).score >= 6.5


def test_curated_production_infrastructure_score_floor() -> None:
    job = make_job(
        "Software Engineer New Grad - Production Infrastructure",
        "Infrastructure and platform systems.",
        source_type="curated_repo",
        verification_status="unverified",
    )
    assert score_job(job, SETTINGS).score >= 7.0


def test_curated_new_grad_performance_score_floor() -> None:
    job = make_job(
        "Software Engineer New Grad - Performance",
        "",
        source_type="curated_repo",
        verification_status="unverified",
    )
    assert score_job(job, SETTINGS).score >= 6.5


def test_curated_generic_software_engineer_new_grad_reaches_review() -> None:
    job = make_job(
        "Software Engineer - New Grad",
        "",
        location="San Jose, CA",
        source_type="curated_repo",
        verification_status="unverified",
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.score >= 5.0


def test_anthropic_fellows_program_does_not_rule_alert() -> None:
    job = make_job("Anthropic Fellows Program", "AI safety research and engineering program.")
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.role_family == "fellowship_program"
    assert score.requires_gemini_review
    assert not score.can_rule_alert


def test_fellows_program_ml_systems_requires_gemini_review() -> None:
    job = make_job(
        "Anthropic Fellows Program, ML Systems & Performance", "ML systems performance work."
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.role_family == "fellowship_program"
    assert score.requires_gemini_review
    assert not score.can_rule_alert


def test_commercial_counsel_classified_legal_not_candidate() -> None:
    score = score_job(make_job("Commercial Counsel", "Contracts and legal work."), SETTINGS)
    assert score.role_family == "legal"
    assert not score.is_candidate
    assert not score.can_rule_alert


def test_strategic_account_executive_classified_sales_not_candidate() -> None:
    score = score_job(make_job("Strategic Account Executive", "Enterprise sales role."), SETTINGS)
    assert score.role_family == "sales"
    assert not score.is_candidate
    assert not score.can_rule_alert


def test_finance_systems_integration_engineer_does_not_rule_alert() -> None:
    job = make_job(
        "Finance Systems Integration Engineer", "Integrate finance systems and internal tools."
    )
    score = score_job(job, SETTINGS)
    assert score.role_family == "finance"
    assert not score.can_rule_alert


def test_product_finance_strategy_does_not_rule_alert() -> None:
    score = score_job(
        make_job("Product Finance & Strategy", "Finance and strategy role."), SETTINGS
    )
    assert score.role_family == "finance"
    assert not score.can_rule_alert


def test_security_labs_engineer_requires_gemini_review() -> None:
    job = make_job("Security Labs Engineer", "Security research and evaluation work.")
    score = score_job(job, SETTINGS)
    assert score.role_family == "security_engineering"
    assert score.requires_gemini_review
    assert not score.can_rule_alert


def test_platform_hardware_security_requires_gemini_unless_software_heavy() -> None:
    ambiguous = score_job(
        make_job("Platform Hardware Security", "Hardware security analysis."), SETTINGS
    )
    assert ambiguous.role_family == "security_engineering"
    assert ambiguous.requires_gemini_review
    assert not ambiguous.can_rule_alert

    software_heavy = score_job(
        make_job(
            "Platform Security Software Engineer", "Distributed systems security engineering."
        ),
        SETTINGS,
    )
    assert software_heavy.role_family == "systems_infrastructure"


def test_palantir_production_infrastructure_can_rule_alert() -> None:
    job = make_job(
        "Software Engineer New Grad - Production Infrastructure",
        "Infrastructure and platform systems.",
        source_type="curated_repo",
        verification_status="unverified",
    )
    score = score_job(job, SETTINGS)
    assert score.role_family == "systems_infrastructure"
    assert score.can_rule_alert


def test_n1_backend_rust_can_rule_alert() -> None:
    job = make_job(
        "New Grad Software Engineer - Backend Rust",
        "Backend platform systems.",
        source_type="curated_repo",
        verification_status="unverified",
    )
    score = score_job(job, SETTINGS)
    assert score.role_family == "software_engineering"
    assert score.can_rule_alert


def test_nuro_performance_can_rule_alert() -> None:
    job = make_job(
        "Software Engineer New Grad - Performance",
        "Performance engineering.",
        source_type="curated_repo",
        verification_status="unverified",
    )
    score = score_job(job, SETTINGS)
    assert score.role_family in {"systems_infrastructure", "software_engineering"}
    assert score.can_rule_alert


def test_full_stack_rl_stays_candidate() -> None:
    job = make_job(
        "Full-Stack Software Engineer, Reinforcement Learning",
        "Build ML systems and product infrastructure.",
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.role_family in {"software_engineering", "ml_ai_engineering"}


def test_target_company_full_stack_rl_requires_gemini_without_early_career_signal() -> None:
    job = make_job(
        "Full-Stack Software Engineer, Reinforcement Learning",
        "Build ML systems and product infrastructure.",
        source_type="target_company",
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert score.requires_gemini_review
    assert not score.can_rule_alert


def test_target_company_early_career_engineering_can_rule_alert() -> None:
    job = make_job(
        "Software Engineer I, ML Infrastructure",
        "Entry level ML infrastructure role for 0-2 years of experience.",
        source_type="target_company",
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert not score.requires_gemini_review
    assert score.can_rule_alert


def test_target_company_university_hire_signal_can_rule_alert() -> None:
    job = make_job(
        "Software Engineer, Backend",
        "University hire graduate program for backend systems engineering.",
        source_type="target_company",
    )
    score = score_job(job, SETTINGS)
    assert score.is_candidate
    assert not score.requires_gemini_review
    assert score.can_rule_alert

def test_google_direct_university_grad_swe_candidate_ignores_sponsorship_text() -> None:
    job = Job(
        source="Google",
        source_type="target_company",
        source_priority=20,
        company="Google",
        external_id="google-ugrad",
        title="Software Engineer, University Graduate, Cloud Infrastructure",
        location="New York, NY, USA",
        url="https://www.google.com/about/careers/applications/jobs/results/123",
        description=(
            "University graduate role building distributed systems, backend infrastructure, "
            "and cloud services. Must be authorized to work without sponsorship. "
            "U.S. citizenship required. Active security clearance required."
        ),
        verification_status="verified",
    )

    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert score.can_rule_alert
    assert "Google direct source" in score.reasons
    assert "university graduate signal" in score.reasons
    assert not any("sponsorship" in reason.lower() for reason in score.rejection_reasons)
    assert not any("citizenship" in reason.lower() for reason in score.rejection_reasons)
    assert not any("clearance" in reason.lower() for reason in score.rejection_reasons)


def test_curated_repo_no_sponsorship_still_blocks_candidate() -> None:
    job = make_job(
        "Software Engineer New Grad - Backend",
        "Must be authorized to work without sponsorship. Backend systems role.",
        source_type="curated_repo",
        verification_status="unverified",
    )

    score = score_job(job, SETTINGS)

    assert not score.is_candidate
    assert any("sponsorship" in reason.lower() for reason in score.rejection_reasons)

def make_meta_job(title: str, description: str, location: str | None = "Menlo Park, CA") -> Job:
    return Job(
        source="Meta",
        source_type="target_company",
        source_priority=20,
        company="Meta",
        external_id=title,
        title=title,
        location=location,
        url=f"https://www.metacareers.com/jobs/{title.replace(' ', '-')}",
        description=description,
        verification_status="verified",
    )


def test_meta_software_engineer_new_grad_candidate() -> None:
    job = make_meta_job(
        "Software Engineer, New Grad",
        "Build backend infrastructure and distributed systems for production services.",
    )
    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert score.can_rule_alert
    assert "Meta direct source" in score.reasons
    assert "undergraduate new-grad signal" in score.reasons


def test_meta_software_engineer_university_graduate_candidate() -> None:
    job = make_meta_job(
        "Software Engineer, University Graduate",
        "Bachelor's degree in Computer Science. Build systems infrastructure and backend services.",
    )
    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert score.can_rule_alert
    assert "university graduate signal" in score.reasons


def test_university_graduate_wording_is_not_advanced_degree_blocked() -> None:
    job = make_meta_job(
        "Software Engineer, University Graduate",
        "New graduate role for Bachelor's degree candidates working on software systems.",
    )
    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert not any("degree" in reason.lower() for reason in score.rejection_reasons)


def test_meta_senior_staff_manager_rejected() -> None:
    for title in [
        "Senior Software Engineer, Infrastructure",
        "Staff Software Engineer, Backend",
        "Engineering Manager, Systems",
    ]:
        assert not score_job(make_meta_job(title, "Backend infrastructure systems."), SETTINGS).is_candidate


def test_three_plus_years_rejected_unless_explicit_early_career_title() -> None:
    description = "Minimum qualifications: 3 years of experience with software development. Backend systems."

    generic = score_job(make_meta_job("Software Engineer, Backend", description), SETTINGS)
    early = score_job(make_meta_job("Software Engineer, Early Career", description), SETTINGS)

    assert not generic.is_candidate
    assert any("years-of-experience" in reason for reason in generic.rejection_reasons)
    assert early.is_candidate
    assert not any("years-of-experience" in reason for reason in early.rejection_reasons)


def test_phd_specific_role_rejected() -> None:
    job = make_meta_job(
        "Software Engineer, PhD University Grad",
        "PhD candidates only. Machine learning infrastructure role.",
    )
    score = score_job(job, SETTINGS)

    assert not score.is_candidate
    assert any("PhD-specific" in reason for reason in score.rejection_reasons)


def test_masters_specific_role_rejected() -> None:
    job = make_meta_job(
        "Software Engineer, Master's University Grad",
        "Currently enrolled in a Master's program. Backend infrastructure role.",
    )
    score = score_job(job, SETTINGS)

    assert not score.is_candidate
    assert any("Master" in reason for reason in score.rejection_reasons)


def test_bachelors_or_masters_not_rejected_solely_for_masters_mention() -> None:
    job = make_meta_job(
        "Software Engineer, University Graduate",
        "Minimum qualifications: Bachelor's, Master's, or PhD in Computer Science. Build backend systems.",
    )
    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert not any("Master" in reason or "PhD" in reason for reason in score.rejection_reasons)


def test_meta_direct_sponsorship_and_citizenship_text_does_not_block() -> None:
    job = make_meta_job(
        "Software Engineer, New Grad",
        "Backend systems. Must be authorized to work without sponsorship. U.S. citizenship required.",
    )
    score = score_job(job, SETTINGS)

    assert score.is_candidate
    assert not any("sponsorship" in reason.lower() for reason in score.rejection_reasons)
    assert not any("citizenship" in reason.lower() for reason in score.rejection_reasons)
