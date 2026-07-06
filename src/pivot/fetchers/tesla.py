"""Tesla official careers adapter."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from typing import Any

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1 (+https://github.com/)"
TESLA_CAREERS_BASE = "https://www.tesla.com/careers"
TESLA_SEARCH_ENDPOINT = "https://www.tesla.com/cua-api/apps/careers/jobs/search"
TESLA_SEARCH_TERMS = ["software", "backend", "infrastructure", "vehicle software", "AI"]

TITLE_INCLUDE_PATTERN = re.compile(
    r"software|backend|infrastructure|vehicle\s+software|firmware|autopilot|robotics|"
    r"machine\s+learning|\bai\b|new\s+grad|new\s+college\s+grad|entry\s+level|intern",
    re.I,
)
TITLE_EXCLUDE_PATTERN = re.compile(
    r"\b(senior|staff|principal|manager|director|lead)\b|\bhead\s+of\b|\bsr\.?\b",
    re.I,
)


class TeslaCareersFetcher(Fetcher):
    """Fetch focused Tesla jobs from the official careers JSON API."""

    def __init__(
        self,
        source_priority: int = 20,
        timeout_seconds: float = 20.0,
        search_limit: int = 25,
    ) -> None:
        super().__init__(name="Tesla", source_type="target_company", source_priority=source_priority)
        self.timeout_seconds = timeout_seconds
        self.search_limit = search_limit

    def fetch(self) -> list[Job]:
        """Fetch Tesla careers search results.

        Tesla's public careers API may return Akamai 403s from some runners. That is allowed
        to surface as source health `failed`; it is still a real adapter, not a placeholder.
        """

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.tesla.com/careers/search/",
        }
        seen_ids: set[str] = set()
        jobs: list[Job] = []
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            for term in TESLA_SEARCH_TERMS:
                params = {"query": term, "limit": str(self.search_limit)}
                response = client.get(TESLA_SEARCH_ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()
                for job in parse_tesla_jobs(payload, self.source_priority):
                    if job.external_id not in seen_ids:
                        seen_ids.add(job.external_id)
                        jobs.append(job)
        LOGGER.info("Fetched %s focused Tesla jobs", len(jobs))
        return jobs


def build_fetcher(source_priority: int = 20) -> TeslaCareersFetcher:
    """Build the Tesla direct source adapter."""

    return TeslaCareersFetcher(source_priority=source_priority)


def parse_tesla_jobs(payload: dict[str, Any], source_priority: int = 20) -> list[Job]:
    """Parse Tesla careers JSON into normalized focused jobs.

    The endpoint has changed shape over time, so this parser accepts common wrappers such as
    `jobs`, `results`, `listings`, `data`, and `response.results`.
    """

    jobs: list[Job] = []
    for item in _candidate_items(payload):
        title = _first_text(item, "title", "jobTitle", "name", "position")
        focus_text = " ".join(
            [
                title,
                _first_text(item, "department", "team", "category", "businessUnit"),
                _first_text(item, "description", "jobDescription", "summary"),
            ]
        )
        if not title or not _is_focused_tesla_role(focus_text, title):
            continue
        jobs.append(_normalize_tesla_job(item, title, source_priority))
    return jobs


def _normalize_tesla_job(item: dict[str, Any], title: str, source_priority: int) -> Job:
    external_id = _first_text(item, "id", "jobId", "reqId", "requisitionId", "jobReqId")
    url = _tesla_url(item, external_id)
    if not external_id:
        external_id = hashlib.sha256(f"{title}|{url}|{_location_text(item)}".encode()).hexdigest()[:16]
    return Job(
        source="Tesla",
        source_type="target_company",
        source_priority=source_priority,
        company="Tesla",
        external_id=external_id,
        title=title,
        location=_location_text(item),
        url=url,
        department=_first_text(item, "department", "team", "category", "businessUnit") or None,
        description=_plain_text(_first_text(item, "description", "jobDescription", "summary")),
        posted_at=_first_text(item, "postedDate", "posted_at", "createdAt", "datePosted") or None,
        raw=item,
        verification_status="verified",
    )


def _candidate_items(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    queue: list[Any] = [payload]
    while queue:
        value = queue.pop(0)
        if isinstance(value, list):
            if all(isinstance(item, dict) for item in value):
                for item in value:
                    if _looks_like_job(item):
                        yield item
                    else:
                        queue.append(item)
            continue
        if not isinstance(value, dict):
            continue
        if _looks_like_job(value):
            yield value
            continue
        for key in ("jobs", "results", "listings", "positions", "data", "response", "searchResults"):
            if key in value:
                queue.append(value[key])


def _looks_like_job(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("title", "jobTitle", "name", "position")) and any(
        key in value for key in ("id", "jobId", "reqId", "requisitionId", "url", "applyUrl")
    )


def _is_focused_tesla_role(text: str, title: str) -> bool:
    return bool(TITLE_INCLUDE_PATTERN.search(text)) and not TITLE_EXCLUDE_PATTERN.search(title)


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str | int | float):
            return str(value).strip()
    return ""


def _location_text(item: dict[str, Any]) -> str | None:
    value = item.get("location") or item.get("locations")
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        parts = [
            str(value.get(key) or "").strip()
            for key in ("city", "state", "region", "country", "name")
            if value.get(key)
        ]
        return ", ".join(dict.fromkeys(parts)) or None
    if isinstance(value, list):
        parts = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                text = _location_text({"location": entry})
                if text:
                    parts.append(text)
        return "; ".join(parts) or None
    pieces = [_first_text(item, "city"), _first_text(item, "state"), _first_text(item, "country")]
    return ", ".join(piece for piece in pieces if piece) or None


def _tesla_url(item: dict[str, Any], external_id: str) -> str:
    url = _first_text(item, "url", "applyUrl", "externalUrl", "jobUrl")
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return f"https://www.tesla.com{url}"
    if external_id:
        return f"{TESLA_CAREERS_BASE}/search/job/{external_id}"
    return TESLA_CAREERS_BASE


def _plain_text(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
