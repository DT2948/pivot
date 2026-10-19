"""AMD's official public careers API; descriptions are included in search."""

import httpx

from pivot.fetchers.base import Fetcher
from pivot.fetchers.workday import _plain_text
from pivot.models import Job

API = "https://careers.amd.com/api/jobs"
SEARCH_TERMS = ("new graduate software", "software", "compiler", "ROCm")


class AMDCareersFetcher(Fetcher):
    def __init__(self, source_priority: int = 20) -> None:
        super().__init__("AMD", "target_company", source_priority)

    def fetch(self) -> list[Job]:
        jobs = {}
        with httpx.Client(timeout=20, headers={"User-Agent": "PivotJobAlerts/0.1"}) as client:
            for term in SEARCH_TERMS:
                response = client.get(
                    API,
                    params={
                        "keywords": term,
                        "location": "United States",
                        "limit": 20,
                        "page": 1,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                    raise ValueError("AMD malformed search response: jobs missing")
                for row in data["jobs"]:
                    item = row.get("data") if isinstance(row, dict) else None
                    if not isinstance(item, dict) or not all(
                        item.get(k) for k in ("req_id", "title", "description", "slug")
                    ):
                        raise ValueError("AMD malformed job record: identity/description missing")
                    slug = str(item["slug"])
                    if not slug.isdigit():
                        raise ValueError("AMD invalid job slug")
                    location = ", ".join(
                        str(item[k]) for k in ("city", "state", "country") if item.get(k)
                    )
                    jobs.setdefault(
                        str(item["req_id"]),
                        Job(
                            source="AMD",
                            source_type="target_company",
                            company="AMD",
                            source_priority=self.source_priority,
                            external_id=str(item["req_id"]),
                            title=item["title"],
                            location=location or item.get("location_name"),
                            url=f"https://careers.amd.com/careers-home/jobs/{slug}",
                            description=_plain_text(item["description"]),
                            raw=item,
                            verification_status="verified",
                        ),
                    )
        return list(jobs.values())
