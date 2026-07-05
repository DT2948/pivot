from __future__ import annotations

from pathlib import Path

from pivot.gemini_scorer import GeminiScorer
from pivot.main import filter_jobs
from pivot.models import Job


def test_dry_run_does_not_update_seen_state() -> None:
    before = Path("data/seen_jobs.json").read_text()
    after = Path("data/seen_jobs.json").read_text()
    assert before == after


def test_missing_gemini_key_falls_back_to_rules(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    job = Job(
        source="Test",
        source_type="target_company",
        source_priority=10,
        company="Acme",
        external_id="1",
        title="New Grad Software Engineer Backend",
        location="New York, NY",
        url="https://example.com/job",
        description="Python distributed systems cloud.",
    )
    pairs, _ = filter_jobs([job], {"allow_internships": False})
    scored = GeminiScorer({"gemini": {"enabled": True}}, {}, no_gemini=False).score(pairs)
    assert scored[0].score_source == "rules_fallback"
