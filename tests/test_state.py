from __future__ import annotations

from pivot.dedupe import job_key
from pivot.models import Job, ScoredJob
from pivot.state import has_meaningful_change, is_new_or_changed, update_seen


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


def test_never_delivered_can_alert_later_without_posting_change():
    item = scored("unchanged")
    item.should_alert = False
    seen = update_seen({}, [item], set())
    item.should_alert = True
    item.final_score = 10
    assert is_new_or_changed(seen, item)


def test_delivered_not_resent_when_only_score_changes():
    item = scored("unchanged")
    seen = update_seen({}, [item], {job_key(item.job)})
    item.final_score = 10
    item.score_source = "gemini"
    assert not is_new_or_changed(seen, item)


def test_changed_posting_stays_retryable_after_nonalerting_discovery():
    item = scored("original")
    seen = update_seen({}, [item], {job_key(item.job)})
    changed = scored("changed")
    changed.should_alert = False
    seen = update_seen(seen, [changed], set())
    assert is_new_or_changed(seen, changed)
    seen = update_seen(seen, [changed], {job_key(changed.job)})
    assert not is_new_or_changed(seen, changed)


def test_legacy_missing_delivery_metadata_stays_conservative_after_migration():
    item = scored("legacy")
    seen = update_seen({}, [item], {job_key(item.job)})
    record = seen[job_key(item.job)]
    del record["alerted_at"]
    del record["alerted_snapshot"]
    del record["legacy_delivery_unknown"]
    assert not is_new_or_changed(seen, item)
    seen = update_seen(seen, [item], set())
    assert not is_new_or_changed(seen, item)


def test_legacy_explicit_null_delivery_metadata_remains_alertable():
    item = scored("legacy")
    seen = update_seen({}, [item], set())
    del seen[job_key(item.job)]["alerted_snapshot"]
    assert is_new_or_changed(seen, item)


def test_tracked_history_migrates_without_replaying_delivered_jobs(tmp_path):
    from copy import deepcopy
    from pathlib import Path

    from pivot.dedupe import description_hash
    from pivot.state import load_seen, save_seen

    tracked_path = Path(__file__).resolve().parents[1] / "data" / "seen_jobs.json"
    before = tracked_path.read_bytes()
    original = load_seen(tracked_path)
    working = deepcopy(original)
    items = []
    for key, record in working.items():
        # Bodies are not stored in seen state. Reconstruct an unchanged body and
        # its matching hash in the COPY, preserving every actual identity/timestamp.
        record["last_description_hash"] = description_hash("unchanged posting")
        item = scored("unchanged posting")
        item.job = Job(
            source=record["source"],
            source_type=record["source_type"],
            company=record["company"],
            external_id=key,
            title=record["title"],
            location=record.get("location"),
            url=record["url"],
            description="unchanged posting",
        )
        item.final_score = 10  # Simulate a better assessment under the new profile.
        assert job_key(item.job) == key
        assert is_new_or_changed(working, item) == (record["alerted_at"] is None)
        items.append(item)

    migrated = update_seen(working, items, set())
    temporary_state = tmp_path / "seen_jobs.json"
    save_seen(temporary_state, migrated)
    reloaded = load_seen(temporary_state)
    assert set(reloaded) == set(original)
    for item in items:
        key = job_key(item.job)
        assert reloaded[key]["first_seen_at"] == original[key]["first_seen_at"]
        assert reloaded[key]["alerted_at"] == original[key]["alerted_at"]
        assert is_new_or_changed(reloaded, item) == (original[key]["alerted_at"] is None)
    assert tracked_path.read_bytes() == before
