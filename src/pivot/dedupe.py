"""Job identity and cross-source deduplication."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from pivot.models import Job


def normalize_text(value: str | None) -> str:
    """Normalize text for stable keys."""

    return re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-")


def canonical_url(url: str) -> str:
    """Remove common tracking query strings from a URL."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def description_hash(description: str | None) -> str:
    """Hash the description text."""

    return hashlib.sha256((description or "").encode()).hexdigest()


def job_key(job: Job) -> str:
    """Stable seen-state key for a job."""

    url_hash = hashlib.sha256(canonical_url(job.url).encode()).hexdigest()[:16]
    return ":".join(
        [
            normalize_text(job.company),
            normalize_text(job.title),
            normalize_text(job.location),
            url_hash,
        ]
    )


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    """Deduplicate jobs, preferring direct company sources over curated repos."""

    chosen: dict[tuple[str, str], Job] = {}
    for job in jobs:
        key = (normalize_text(job.company), normalize_text(job.title))
        current = chosen.get(key)
        if current is None or _rank(job) < _rank(current):
            chosen[key] = job
    return list(chosen.values())


def _rank(job: Job) -> tuple[int, int]:
    source_rank = 0 if job.source_type == "target_company" else 1
    return (source_rank, job.source_priority)
