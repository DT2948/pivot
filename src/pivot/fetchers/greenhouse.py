"""Greenhouse public board adapter."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1 (+https://github.com/)"


class GreenhouseFetcher(Fetcher):
    """Fetch jobs from a Greenhouse public board API."""

    def __init__(
        self,
        name: str,
        board_token: str,
        source_priority: int = 10,
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(name=name, source_type="target_company", source_priority=source_priority)
        self.board_token = board_token
        self.timeout_seconds = timeout_seconds

    @property
    def endpoint(self) -> str:
        """Greenhouse jobs endpoint."""

        return (
            "https://boards-api.greenhouse.io/v1/boards/"
            f"{self.board_token}/jobs?content=true"
        )

    def fetch(self) -> list[Job]:
        """Fetch and parse Greenhouse jobs."""

        with httpx.Client(timeout=self.timeout_seconds, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(self.endpoint)
            response.raise_for_status()
            payload = response.json()
        return parse_greenhouse_jobs(payload, self.name, self.source_priority)


def _plain_text(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def parse_greenhouse_jobs(payload: dict[str, Any], source: str, source_priority: int = 10) -> list[Job]:
    """Parse Greenhouse API JSON into normalized jobs."""

    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        departments = item.get("departments") or []
        department = ", ".join(d.get("name", "") for d in departments if d.get("name")) or None
        raw_id = str(item.get("id") or hashlib.sha256(str(item).encode()).hexdigest()[:16])
        location = (item.get("location") or {}).get("name")
        jobs.append(
            Job(
                source=source,
                source_type="target_company",
                source_priority=source_priority,
                company=source,
                external_id=raw_id,
                title=item.get("title") or "Untitled role",
                location=location,
                url=item.get("absolute_url") or item.get("url") or "",
                department=department,
                description=_plain_text(item.get("content")),
                updated_at=item.get("updated_at"),
                raw=item,
                verification_status="verified",
            )
        )
    LOGGER.info("Parsed %s Greenhouse jobs for %s", len(jobs), source)
    return jobs
