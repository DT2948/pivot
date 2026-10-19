"""Intel's official public Workday search and detail API."""

import re

import httpx

from pivot.fetchers.base import Fetcher
from pivot.fetchers.workday import _plain_text
from pivot.models import Job

BASE = "https://intel.wd1.myworkdayjobs.com"
API = f"{BASE}/wday/cxs/intel/External"
SEARCH_TERMS = ("new college graduate software", "software engineer", "compiler", "GPU software")


class IntelCareersFetcher(Fetcher):
    def __init__(self, source_priority: int = 20) -> None:
        super().__init__("Intel", "target_company", source_priority)

    def fetch(self) -> list[Job]:
        by_path = {}
        with httpx.Client(timeout=20, headers={"User-Agent": "PivotJobAlerts/0.1"}) as client:
            for term in SEARCH_TERMS:
                response = client.post(
                    f"{API}/jobs",
                    json={
                        "appliedFacets": {},
                        "limit": 20,
                        "offset": 0,
                        "searchText": term,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
                    raise ValueError("Intel malformed search response: jobPostings missing")
                for item in data["jobPostings"]:
                    if (
                        not isinstance(item, dict)
                        or not item.get("externalPath")
                        or not item.get("title")
                    ):
                        raise ValueError("Intel malformed job record")
                    title = item["title"]
                    if re.search(
                        r"\b(senior|sr|staff|principal|manager|director|lead|intern|fellow)\b",
                        title,
                        re.I,
                    ):
                        continue
                    if not re.search(
                        r"software|compiler|runtime|backend|infrastructure|research engineer",
                        title,
                        re.I,
                    ):
                        continue
                    by_path.setdefault(item["externalPath"], item)
            jobs = []
            # US paths first, but keep multilocation records for detail location resolution.
            items = sorted(by_path.items(), key=lambda pair: not pair[0].startswith("/job/US-"))
            for path, item in items[:20]:
                if not path.startswith("/job/") or ".." in path:
                    raise ValueError("Intel invalid job path")
                response = client.get(f"{API}{path}")
                response.raise_for_status()
                payload = response.json()
                info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
                if not isinstance(info, dict) or not info.get("jobDescription"):
                    raise ValueError("Intel malformed detail response: description missing")
                locations = [info.get("location"), *(info.get("additionalLocations") or [])]
                jobs.append(
                    Job(
                        source="Intel",
                        source_type="target_company",
                        company="Intel",
                        source_priority=self.source_priority,
                        external_id=str(info.get("jobReqId") or path.rsplit("_", 1)[-1]),
                        title=info.get("title") or item["title"],
                        location="; ".join(str(x) for x in locations if x),
                        url=f"{BASE}/External{path}",
                        description=_plain_text(info["jobDescription"]),
                        raw={"search": item, "detail": info},
                        verification_status="verified",
                    )
                )
        return jobs
