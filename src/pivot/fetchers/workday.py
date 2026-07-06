"""NVIDIA Workday careers adapter."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1"

NVIDIA_CAREERS_BASE = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
NVIDIA_CXS_BASE = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
NVIDIA_SEARCH_ENDPOINT = f"{NVIDIA_CXS_BASE}/jobs"

NVIDIA_SEARCH_TERMS = [
    "new college grad software engineer",
    "new grad software engineer",
    "university graduate software engineer",
    "systems software new college grad",
    "compiler new college grad",
    "compiler software engineer",
    "infrastructure software engineer",
    "backend software engineer",
    "AI ML infrastructure software engineer",
]

TITLE_INCLUDE_PATTERN = re.compile(
    r"new\s+college\s+grad|new\s+grad|university\s+graduate|software\s+engineer|"
    r"systems?\s+software|compiler|infrastructure|backend|ai/?ml\s+infrastructure",
    re.I,
)
TITLE_EXCLUDE_PATTERN = re.compile(
    r"\b(senior|staff|principal|manager|director|lead)\b|\bhead\s+of\b|\bsr\.?\b",
    re.I,
)


class NvidiaWorkdayFetcher(Fetcher):
    """Fetch focused NVIDIA jobs from the official Workday careers API."""

    def __init__(
        self,
        source_priority: int = 20,
        timeout_seconds: float = 20.0,
        search_limit: int = 20,
        max_detail_requests: int = 20,
    ) -> None:
        super().__init__(name="NVIDIA", source_type="target_company", source_priority=source_priority)
        self.timeout_seconds = timeout_seconds
        self.search_limit = search_limit
        self.max_detail_requests = max_detail_requests

    def fetch(self) -> list[Job]:
        """Fetch search results and enrich matching jobs with detail descriptions."""

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        by_path: dict[str, dict[str, Any]] = {}
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            for term in NVIDIA_SEARCH_TERMS:
                payload = {"appliedFacets": {}, "limit": self.search_limit, "offset": 0, "searchText": term}
                response = client.post(NVIDIA_SEARCH_ENDPOINT, json=payload)
                response.raise_for_status()
                for item in response.json().get("jobPostings", []):
                    external_path = str(item.get("externalPath") or "")
                    if external_path and _is_focused_nvidia_title(str(item.get("title") or "")):
                        by_path.setdefault(external_path, item)

            jobs: list[Job] = []
            for item in list(by_path.values())[: self.max_detail_requests]:
                detail = _fetch_nvidia_detail(client, str(item.get("externalPath") or ""))
                jobs.append(parse_nvidia_job(item, detail, self.source_priority))
        LOGGER.info("Fetched %s focused NVIDIA jobs", len(jobs))
        return jobs


def build_nvidia_fetcher(source_priority: int = 20) -> NvidiaWorkdayFetcher:
    """Build the NVIDIA direct source adapter."""

    return NvidiaWorkdayFetcher(source_priority=source_priority)


def parse_nvidia_search_jobs(
    payload: dict[str, Any], source_priority: int = 20
) -> list[Job]:
    """Parse NVIDIA Workday search JSON without detail enrichment."""

    jobs: list[Job] = []
    for item in payload.get("jobPostings", []):
        title = str(item.get("title") or "")
        if _is_focused_nvidia_title(title):
            jobs.append(parse_nvidia_job(item, None, source_priority))
    return jobs


def parse_nvidia_job(
    item: dict[str, Any], detail: dict[str, Any] | None = None, source_priority: int = 20
) -> Job:
    """Normalize one NVIDIA Workday job posting."""

    info = (detail or {}).get("jobPostingInfo") or {}
    title = str(info.get("title") or item.get("title") or "Untitled NVIDIA role")
    external_path = str(item.get("externalPath") or info.get("externalPath") or "")
    raw_id = _nvidia_job_id(item, info, external_path)
    description = _plain_text(info.get("jobDescription"))
    location = _nvidia_location(item, info)
    return Job(
        source="NVIDIA",
        source_type="target_company",
        source_priority=source_priority,
        company="NVIDIA",
        external_id=raw_id,
        title=title,
        location=location,
        url=f"{NVIDIA_CAREERS_BASE}{external_path}" if external_path else str(info.get("externalUrl") or ""),
        department=info.get("jobFamily") or info.get("jobProfile"),
        description=description,
        posted_at=item.get("postedOn") or info.get("postedOn"),
        raw={"search": item, "detail": detail or {}},
        verification_status="verified",
    )


def _fetch_nvidia_detail(client: httpx.Client, external_path: str) -> dict[str, Any] | None:
    if not external_path:
        return None
    response = client.get(f"{NVIDIA_CXS_BASE}{external_path}")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else None


def _is_focused_nvidia_title(title: str) -> bool:
    return bool(TITLE_INCLUDE_PATTERN.search(title)) and not TITLE_EXCLUDE_PATTERN.search(title)


def _nvidia_job_id(item: dict[str, Any], info: dict[str, Any], external_path: str) -> str:
    bullet_fields = item.get("bulletFields") or []
    for value in [info.get("id"), *bullet_fields, external_path]:
        if value:
            return str(value)
    return hashlib.sha256(str(item).encode()).hexdigest()[:16]


def _nvidia_location(item: dict[str, Any], info: dict[str, Any]) -> str | None:
    locations = info.get("locations") or []
    if isinstance(locations, list) and locations:
        names = [str(loc.get("descriptor") or loc.get("name") or "") for loc in locations if isinstance(loc, dict)]
        joined = "; ".join(name for name in names if name)
        if joined:
            return joined
    return item.get("locationsText") or info.get("location")


def _plain_text(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
