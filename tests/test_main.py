from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pivot import main as pivot_main
from pivot.dedupe import description_hash, job_key
from pivot.gemini_scorer import GeminiScorer
from pivot.main import filter_jobs
from pivot.models import Job, ScoredJob


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


def main_scored(company: str = "Google", *, should_alert: bool = True) -> ScoredJob:
    job = Job(
        source=company,
        source_type="target_company",
        source_priority=10,
        company=company,
        external_id=f"{company}-1",
        title="Software Engineer New Grad",
        location="New York, NY",
        url=f"https://example.com/{company}",
        description="Backend systems.",
    )
    return ScoredJob(
        job=job,
        rule_score=9,
        final_score=9,
        score_source="rules_fallback",
        fit_summary="Good",
        should_alert=should_alert,
        visa_assessment="unknown",
        rule_reasons=["software engineering", "new-grad"],
    )


class FakeScorer:
    def __init__(self, scored: list[ScoredJob]) -> None:
        self.scored = scored

    def score(self, pairs):  # type: ignore[no-untyped-def]
        return self.scored


def setup_main(monkeypatch, scored: list[ScoredJob], seen: dict | None = None):  # type: ignore[no-untyped-def]
    saved: dict[str, object] = {"called": False, "seen": None}
    monkeypatch.setattr(
        pivot_main,
        "parse_args",
        lambda: SimpleNamespace(
            dry_run=False,
            send_test_email=False,
            max_gemini_jobs=None,
            no_gemini=True,
            config_dir="config",
            log_level="INFO",
        ),
    )
    monkeypatch.setattr(
        pivot_main,
        "load_config",
        lambda _: {"settings": {}, "profile": {}, "companies": {"target_companies": []}},
    )
    monkeypatch.setattr(pivot_main, "write_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(pivot_main, "build_fetchers", lambda _: [])
    monkeypatch.setattr(pivot_main, "fetch_all", lambda _: ([], []))
    monkeypatch.setattr(pivot_main, "dedupe_jobs", lambda jobs: jobs)
    monkeypatch.setattr(pivot_main, "filter_jobs", lambda jobs, settings: ([], []))
    monkeypatch.setattr(pivot_main, "GeminiScorer", lambda *args, **kwargs: FakeScorer(scored))
    monkeypatch.setattr(pivot_main, "load_seen", lambda path: dict(seen or {}))

    def fake_save(path, value):  # type: ignore[no-untyped-def]
        saved["called"] = True
        saved["seen"] = value

    monkeypatch.setattr(pivot_main, "save_seen", fake_save)
    return saved


def test_already_seen_alerts_are_not_emailed_again(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    item = main_scored()
    sent: list[list[ScoredJob]] = []
    record = {
        "title": item.job.title,
        "url": item.job.url,
        "last_description_hash": description_hash(item.job.description),
    }
    saved = setup_main(monkeypatch, [item], {job_key(item.job): record})
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: True)
    monkeypatch.setattr(pivot_main, "send_alert_email", lambda jobs, health: sent.append(jobs))

    assert pivot_main.main() == 0

    assert sent == []
    assert saved["called"] is True


def test_jobs_are_marked_seen_only_after_successful_email(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    item = main_scored()
    saved = setup_main(monkeypatch, [item], {})
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: True)
    monkeypatch.setattr(pivot_main, "send_alert_email", lambda jobs, health: None)

    assert pivot_main.main() == 0

    seen = saved["seen"]
    assert isinstance(seen, dict)
    assert seen[job_key(item.job)]["alerted_at"] is not None


def test_email_failure_does_not_mark_jobs_seen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    item = main_scored()
    saved = setup_main(monkeypatch, [item], {})
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: True)

    def fail_send(jobs, health):  # type: ignore[no-untyped-def]
        raise RuntimeError("smtp down")

    monkeypatch.setattr(pivot_main, "send_alert_email", fail_send)

    with pytest.raises(RuntimeError, match="smtp down"):
        pivot_main.main()

    assert saved["called"] is False


def test_missing_smtp_config_with_new_alerts_fails_clearly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    item = main_scored()
    saved = setup_main(monkeypatch, [item], {})
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: False)
    monkeypatch.setattr(pivot_main, "missing_email_config", lambda: ["SMTP_HOST"])

    with pytest.raises(RuntimeError, match="Missing SMTP configuration"):
        pivot_main.main()

    assert saved["called"] is False


def test_no_new_alerts_does_not_require_smtp_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    saved = setup_main(monkeypatch, [main_scored(should_alert=False)], {})
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: False)

    assert pivot_main.main() == 0

    assert saved["called"] is True


def test_previously_discovered_but_never_delivered_job_is_emailed(monkeypatch):
    from pivot.state import update_seen

    item = main_scored(should_alert=False)
    seen = update_seen({}, [item], set())
    item.should_alert = True
    saved = setup_main(monkeypatch, [item], seen)
    sent = []
    monkeypatch.setattr(pivot_main, "email_config_present", lambda: True)
    monkeypatch.setattr(pivot_main, "send_alert_email", lambda jobs, health: sent.extend(jobs))
    assert pivot_main.main() == 0
    assert sent == [item]
    assert saved["seen"][job_key(item.job)]["alerted_at"] is not None


def test_dry_run_never_sends_or_persists_even_with_alertable_job(monkeypatch):
    saved = setup_main(monkeypatch, [main_scored()], {})
    args = pivot_main.parse_args()
    args.dry_run = True
    monkeypatch.setattr(pivot_main, "parse_args", lambda: args)

    def unexpected_send(*args):
        raise AssertionError("dry run must not send")

    monkeypatch.setattr(pivot_main, "send_alert_email", unexpected_send)
    assert pivot_main.main() == 0
    assert not saved["called"]


def test_production_entry_point_builds_new_sources_without_email_or_state_writes(
    monkeypatch, tmp_path
):
    from pivot.fetchers.amd import AMDCareersFetcher
    from pivot.fetchers.intel import IntelCareersFetcher
    from pivot.fetchers.oracle import OracleCareersFetcher
    from pivot.models import SourceHealth

    config_dir = Path(__file__).resolve().parents[1] / "config"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        pivot_main,
        "parse_args",
        lambda: SimpleNamespace(
            dry_run=True,
            send_test_email=False,
            max_gemini_jobs=None,
            no_gemini=True,
            config_dir=str(config_dir),
            log_level="INFO",
        ),
    )
    fetched = []
    real_build = pivot_main.build_fetchers

    def build_with_mocked_io(companies):
        sources = real_build(companies)
        for source in sources:

            def safe_fetch(source=source):
                fetched.append(source)
                return [], SourceHealth(
                    source=source.name, source_type=source.source_type, status="success"
                )

            monkeypatch.setattr(source, "safe_fetch", safe_fetch)
        return sources

    monkeypatch.setattr(pivot_main, "build_fetchers", build_with_mocked_io)

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must never send or save state")

    monkeypatch.setattr(pivot_main, "send_alert_email", forbidden)
    monkeypatch.setattr(pivot_main, "save_seen", forbidden)
    assert pivot_main.main() == 0
    assert {type(source) for source in fetched} >= {
        OracleCareersFetcher,
        IntelCareersFetcher,
        AMDCareersFetcher,
    }
    assert "Apple" not in {source.name for source in fetched}
    assert not (tmp_path / "data" / "seen_jobs.json").exists()
