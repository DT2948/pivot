"""Oracle (including OCI) public Recruiting Cloud search and details."""

import json
import re

import httpx

from pivot.fetchers.base import Fetcher
from pivot.fetchers.workday import _plain_text
from pivot.models import Job

API = "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
SITE = "CX_45001"  # Published by the base element on careers.oracle.com.
SEARCH_TERMS = ("software new grad", "software developer 1", "OCI", "software engineer")


class OracleCareersFetcher(Fetcher):
    def __init__(self, source_priority: int = 20) -> None:
        super().__init__("Oracle", "target_company", source_priority)

    def fetch(self) -> list[Job]:
        records = {}
        with httpx.Client(timeout=20, headers={"User-Agent": "PivotJobAlerts/0.1"}) as client:
            for term in SEARCH_TERMS:
                response = client.get(
                    f"{API}/recruitingCEJobRequisitions",
                    params={
                        "onlyData": "true",
                        "expand": "requisitionList",
                        "finder": f"findReqs;siteNumber={SITE},keyword={term},limit=25,offset=0",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                items = payload.get("items") if isinstance(payload, dict) else None
                if (
                    not isinstance(items, list)
                    or not items
                    or not isinstance(items[0].get("requisitionList"), list)
                ):
                    raise ValueError("Oracle malformed search response: requisitionList missing")
                for item in items[0]["requisitionList"]:
                    if not isinstance(item, dict) or not item.get("Id") or not item.get("Title"):
                        raise ValueError("Oracle malformed job record")
                    title = item["Title"]
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
                    records.setdefault(str(item["Id"]), item)
            jobs = []
            items = sorted(
                records.items(), key=lambda pair: pair[1].get("PrimaryLocationCountry") != "US"
            )
            for job_id, item in items[:20]:
                if not job_id.isdigit():
                    raise ValueError("Oracle invalid requisition id")
                response = client.get(
                    f"{API}/recruitingCEJobRequisitionDetails",
                    params={
                        "onlyData": "true",
                        "expand": "all",
                        "finder": f"ById;Id={job_id},siteNumber={SITE}",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                details = payload.get("items") if isinstance(payload, dict) else None
                if not isinstance(details, list) or not details or not isinstance(details[0], dict):
                    raise ValueError("Oracle malformed detail response")
                info = details[0]
                description = _plain_text(
                    " ".join(
                        str(info.get(k) or "")
                        for k in (
                            "ExternalDescriptionStr",
                            "ExternalQualificationsStr",
                            "ExternalResponsibilitiesStr",
                        )
                    )
                )
                if not description:
                    raise ValueError("Oracle detail description missing")
                locations = [str(info.get("PrimaryLocation") or item.get("PrimaryLocation") or "")]
                secondary = info.get("secondaryLocations") or []
                if isinstance(secondary, str):
                    secondary = json.loads(secondary)
                if not isinstance(secondary, list):
                    raise ValueError("Oracle malformed secondary locations")
                for loc in secondary:
                    if isinstance(loc, dict):
                        locations.append(
                            str(
                                loc.get("Name")
                                or loc.get("LocationName")
                                or loc.get("PrimaryLocation")
                                or ""
                            )
                        )
                jobs.append(
                    Job(
                        source="Oracle",
                        source_type="target_company",
                        company="Oracle",
                        source_priority=self.source_priority,
                        external_id=job_id,
                        title=info.get("Title") or item["Title"],
                        location="; ".join(x for x in locations if x),
                        url=f"https://careers.oracle.com/en/sites/jobsearch/job/{job_id}",
                        description=description,
                        raw={"search": item, "detail": info},
                        verification_status="verified",
                    )
                )
        return jobs
