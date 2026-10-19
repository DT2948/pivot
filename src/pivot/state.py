"""Seen-job state management."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pivot.dedupe import description_hash, job_key
from pivot.models import ScoredJob


def load_seen(path: Path) -> dict[str, Any]:
    """Load seen job state."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle) or {}


def save_seen(path: Path, seen: dict[str, Any]) -> None:
    """Write seen job state."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(seen, handle, indent=2, sort_keys=True)
        handle.write("\n")


def has_meaningful_change(record: dict[str, Any], scored: ScoredJob) -> bool:
    """Return true when a seen job changed enough to rescore or alert."""

    job = scored.job
    return (
        record.get("title") != job.title
        or record.get("url") != job.url
        or record.get("last_description_hash") != description_hash(job.description)
    )


def is_new_or_changed(seen: dict[str, Any], scored: ScoredJob) -> bool:
    """Return true if a scored job has not been seen or changed meaningfully."""

    record = seen.get(job_key(scored.job))
    if record is None:
        return True
    # Explicit null means discovered but never delivered. Missing legacy metadata
    # is conservatively treated as delivered to avoid re-emailing old history.
    if (
        "alerted_at" in record
        and record["alerted_at"] is None
        and not record.get("legacy_delivery_unknown")
    ):
        return True
    baseline = record.get("alerted_snapshot") or record
    return has_meaningful_change(baseline, scored)


def update_seen(
    seen: dict[str, Any], scored_jobs: list[ScoredJob], alerted_keys: set[str]
) -> dict[str, Any]:
    """Update state after a successful normal run."""

    now = datetime.now(UTC).isoformat()
    for scored in scored_jobs:
        job = scored.job
        key = job_key(job)
        existing = seen.get(key, {})
        first_seen = existing.get("first_seen_at", now)
        alerted_at = existing.get("alerted_at")
        if key in alerted_keys:
            alerted_at = now
        snapshot = existing.get("alerted_snapshot")
        if key in alerted_keys:
            snapshot = {
                "title": job.title,
                "url": job.url,
                "last_description_hash": description_hash(job.description),
            }
        elif snapshot is None and existing and existing.get("alerted_at", "legacy") is not None:
            snapshot = {
                field: existing.get(field) for field in ("title", "url", "last_description_hash")
            }
        seen[key] = {
            **existing,
            "alerted_snapshot": snapshot,
            "legacy_delivery_unknown": existing.get(
                "legacy_delivery_unknown", bool(existing) and "alerted_at" not in existing
            )
            and key not in alerted_keys,
            "assessment_cache": scored.assessment_cache or existing.get("assessment_cache"),
            "first_seen_at": first_seen,
            "last_seen_at": now,
            "alerted_at": alerted_at,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "source_type": job.source_type,
            "last_score": scored.final_score,
            "score_source": scored.score_source,
            "last_description_hash": description_hash(job.description),
            "times_seen": int(existing.get("times_seen", 0)) + 1,
        }
    return seen
