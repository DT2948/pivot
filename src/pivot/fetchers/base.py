"""Base fetcher types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pivot.models import Job, SourceHealth

LOGGER = logging.getLogger(__name__)


class Fetcher(ABC):
    """Base class for source adapters."""

    name: str
    source_type: str
    source_priority: int

    def __init__(self, name: str, source_type: str, source_priority: int = 50) -> None:
        self.name = name
        self.source_type = source_type
        self.source_priority = source_priority

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Fetch jobs from the source."""

    def safe_fetch(self) -> tuple[list[Job], SourceHealth]:
        """Fetch jobs while converting source failures into health records."""

        try:
            jobs = self.fetch()
        except Exception as exc:  # noqa: BLE001 - source isolation is intentional
            LOGGER.exception("Source %s failed", self.name)
            return [], SourceHealth(
                source=self.name,
                source_type=self.source_type,
                status="failed",
                fetched_count=0,
                error=str(exc),
            )
        return jobs, SourceHealth(
            source=self.name,
            source_type=self.source_type,
            status="success",
            fetched_count=len(jobs),
        )


class PlaceholderFetcher(Fetcher):
    """A graceful placeholder for company sources without a stable adapter yet."""

    def __init__(self, name: str, reason: str, source_priority: int = 40) -> None:
        super().__init__(name=name, source_type="target_company", source_priority=source_priority)
        self.reason = reason

    def fetch(self) -> list[Job]:
        """Return no jobs and log the missing adapter."""

        LOGGER.warning("%s adapter is not implemented yet: %s", self.name, self.reason)
        return []
