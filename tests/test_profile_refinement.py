import json
from types import SimpleNamespace

import pytest

from pivot.alerts import priority_group
from pivot.config import load_config
from pivot.filtering import score_job
from pivot.gemini_scorer import GeminiScorer
from pivot.models import Job
from pivot.scoring import final_alert_allowed, scored_from_rules


def job(
    company="Google",
    title="Software Engineer New Grad",
    description="Backend distributed systems Python.",
    location="United States",
    source_type="target_company",
):
    return Job(
        source=company,
        source_type=source_type,
        company=company,
        external_id="1",
        title=title,
        description=description,
        location=location,
        url="https://example.com/1",
    )


@pytest.mark.parametrize("company", ["Oracle", "Intel", "AMD"])
def test_new_targets_preserve_direct_sponsorship_exception(company):
    item = job(
        company,
        description="Bachelor's degree. Backend systems. No visa sponsorship. U.S. citizenship required. Active security clearance required.",
    )
    rule = score_job(item)
    assert rule.is_candidate
    assert final_alert_allowed(
        item,
        rule,
        {},
        score_source="gemini",
        gemini_valid=True,
        gemini_text="No visa sponsorship. U.S. citizenship required.",
    )[0]
    assert priority_group(scored_from_rules(item, rule, {}, "rules_only")) == "Target Companies"
    item.source_type = "curated_repo"
    assert not score_job(item).is_candidate


@pytest.mark.parametrize("company", ["Google", "Oracle", "Intel", "AMD"])
@pytest.mark.parametrize(
    "title,description",
    [
        ("Software Engineer New Grad", "Master's degree required. Backend infrastructure systems."),
        ("Research Scientist", "PhD required. ML infrastructure systems."),
        ("Physical Design Engineer New Grad", "RTL hardware design and AI systems."),
        ("Silicon Validation Engineer New Grad", "Hardware validation of GPU systems."),
        ("Senior Software Engineer", "Backend systems."),
        (
            "Software Engineer New Grad",
            "Minimum qualifications: 5 years of experience. Backend systems.",
        ),
    ],
)
def test_company_priority_never_bypasses_eligibility(company, title, description):
    assert not score_job(job(company, title, description)).is_candidate


@pytest.mark.parametrize("company", ["Oracle", "Intel", "AMD"])
@pytest.mark.parametrize(
    "location,eligible",
    [("Remote - US", True), ("Toronto, Canada; Austin, TX", True), ("Bangalore, India", False)],
)
def test_new_target_geography(company, location, eligible):
    assert score_job(job(company, location=location)).is_candidate == eligible


@pytest.mark.parametrize(
    "title,description",
    [
        (
            "Software Engineer, University Graduate",
            "Bachelor's degree. Programming and software engineering.",
        ),
        (
            "Software Engineer I, Backend",
            "Bachelor's or Master's or PhD degree. Distributed systems and storage.",
        ),
        ("GPU Software Engineer New Grad", "ROCm and runtime software performance."),
        (
            "Research Engineer",
            "Bachelor's degree accepted. Python implementation of distributed training and inference systems.",
        ),
        ("Full-Stack Software Engineer New Grad", "Backend infrastructure and databases."),
    ],
)
def test_general_and_systems_roles_are_eligible(title, description):
    result = score_job(job(title=title, description=description))
    assert result.is_candidate
    assert 0 <= result.score <= 10


def test_execution_synonyms_are_counted_once():
    first = score_job(job(description="ML systems."))
    second = score_job(
        job(description="ML systems, distributed training, model serving, inference systems.")
    )
    assert first.score == second.score
    assert first.reasons.count("ML systems execution") == 1


def test_generic_ai_word_does_not_raise_score():
    assert (
        score_job(job(description="Backend.")).score
        == score_job(job(description="Backend. AI AI AI.")).score
    )


@pytest.mark.parametrize(
    "company,source_type,direct",
    [
        ("Oracle", "target_company", True),
        ("Intel", "target_company", True),
        ("AMD", "target_company", True),
        ("Oracle", "curated_repo", False),
        ("Apple", "target_company", False),
    ],
)
def test_prompt_sponsorship_policy_and_profile_boundaries(company, source_type, direct):
    captured = {}

    def generate_content(**kwargs):
        captured.update(json.loads(kwargs["contents"]))
        return SimpleNamespace(text="{}")

    scorer = GeminiScorer({}, load_config("config")["profile"])
    scorer._score_one(
        SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
        job(company, source_type=source_type),
    )
    assert ("do not reject or penalize" in captured["sponsorship_policy"]) == direct
    assert "equally important" in captured["instruction"]
    assert "not a required career specialization" in captured["instruction"]
    assert captured["profile"]["candidate"]["education"]["gpa"] == 3.83


@pytest.mark.parametrize(
    "company,title",
    [
        ("Google", "Software Engineer, University Graduate"),
        ("Microsoft", "Software Engineer I"),
        ("Oracle", "Software Developer 1"),
        ("Intel", "Software Engineer, New College Graduate"),
    ],
)
def test_general_swe_without_specialist_keywords_reaches_review(company, title):
    assert score_job(job(company, title, "Bachelor's degree. Develop software.")).is_candidate


def test_degree_alternative_does_not_hide_separate_phd_requirement():
    item = job(
        description="Bachelor's or Master's in CS. PhD required for this role. Backend systems."
    )
    assert not score_job(item).is_candidate


@pytest.mark.parametrize(
    "description",
    [
        "A Master's degree in Computer Science is required.",
        "PhD-only applicants.",
        "Must have a Master's degree.",
    ],
)
def test_explicit_advanced_degree_requirements(description):
    assert not score_job(job(description=description + " Backend systems.")).is_candidate


def test_all_active_targets_use_direct_exception_and_google_first():
    from pivot.alerts import sort_alerts
    from pivot.targets import ACTIVE_TARGET_COMPANIES

    scores = []
    for company in sorted(ACTIVE_TARGET_COMPANIES):
        item = job(
            company,
            description="Bachelor's degree. Backend systems Python. No visa sponsorship. U.S. citizenship required. Active security clearance required.",
        )
        rule = score_job(item)
        assert rule.is_candidate
        assert final_alert_allowed(
            item,
            rule,
            {},
            score_source="gemini",
            gemini_valid=True,
            gemini_text="No visa sponsorship. U.S. citizenship required.",
        )[0]
        scores.append(scored_from_rules(item, rule, {}, "rules_only"))
        curated = item.model_copy(update={"source_type": "curated_repo"})
        assert not score_job(curated).is_candidate
    assert sort_alerts(scores)[0].job.company == "google"


@pytest.mark.parametrize("source_type", ["target_company", "curated_repo"])
def test_prompt_policy_for_every_active_company(source_type):
    from pivot.targets import ACTIVE_TARGET_COMPANIES

    for company in ACTIVE_TARGET_COMPANIES:
        captured = {}

        def generate_content(_captured=captured, **kwargs):
            _captured.update(json.loads(kwargs["contents"]))
            return SimpleNamespace(text="{}")

        scorer = GeminiScorer({}, {})
        scorer._score_one(
            SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
            job(company, source_type=source_type),
        )
        assert ("do not reject or penalize" in captured["sponsorship_policy"]) == (
            source_type == "target_company"
        )
