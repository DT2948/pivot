"""Meta Careers official GraphQL adapter."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1"
META_BASE = "https://www.metacareers.com"
META_GRAPHQL_ENDPOINT = f"{META_BASE}/api/graphql/"
META_SEARCH_DOC_ID = "27807005005556827"
META_SEARCH_FRIENDLY_NAME = "CPJobSearchSourceQuery"
META_SEARCH_TERMS = [
    "Software Engineer New Grad",
    "Software Engineer University Grad",
    "Software Engineer University Graduate",
    "Software Engineer Early Career",
    "Production Engineer New Grad",
    "Infrastructure Software Engineer University Graduate",
    "Systems Software Engineer University Graduate",
    "AI ML Infrastructure Software Engineer University Graduate",
]

TITLE_INCLUDE_PATTERN = re.compile(
    r"software\s+engineer|production\s+engineer|university\s+grad(?:uate)?|new\s+grad(?:uate)?|"
    r"early\s+career|systems?|infrastructure|backend|machine\s+learning|ai/?ml",
    re.I,
)
TITLE_EXCLUDE_PATTERN = re.compile(
    r"\b(senior|staff|principal|manager|director|lead)\b|\bhead\s+of\b|\bsr\.?\b",
    re.I,
)
EARLY_CAREER_TITLE_RE = re.compile(
    r"\bnew\s+grad(?:uate)?\b|\buniversity\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b|\bearly\s+career\b",
    re.I,
)
THREE_PLUS_RE = re.compile(
    r"(?:minimum\s+qualifications?|requirements?|basic\s+qualifications?)"
    r"[\s\S]{0,700}?\b(?:3\+|4\+|5\+|6\+|7\+|8\+|9\+|10\+|3\s+years?|4\s+years?|5\s+years?)",
    re.I,
)
ADVANCED_DEGREE_RE = re.compile(
    r"\bph\.?d\.?\b|\bdoctoral\b|\bdoctorate\b|\bpostdoc(?:toral)?\b|"
    r"\bmaster'?s\s+(?:required|university\s+grad|candidate|program)\b|"
    r"\bmasters\s+(?:required|university\s+grad|candidate|program)\b|"
    r"currently\s+enrolled\s+in\s+a?\s*(?:master'?s|masters|ph\.?d\.?)|"
    r"pursuing\s+a?\s*(?:master'?s|masters|ph\.?d\.?)|advanced\s+degree\s+required",
    re.I,
)
BACHELORS_ACCEPTED_RE = re.compile(r"\bbachelor(?:'s|s)?\b|\bb\.?s\.?\b|equivalent\s+practical\s+experience", re.I)


class MetaCareersFetcher(Fetcher):
    """Fetch focused Meta jobs from the official Meta Careers GraphQL endpoint."""

    def __init__(
        self,
        source_priority: int = 20,
        timeout_seconds: float = 20.0,
        max_results: int = 30,
    ) -> None:
        super().__init__(name="Meta", source_type="target_company", source_priority=source_priority)
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results

    def fetch(self) -> list[Job]:
        """Fetch Meta Careers search suggestions and normalize focused roles.

        Meta exposes the relevant job-search operation through its official Careers client.
        Some runners may receive an HTML error for anonymous GraphQL requests; that should
        surface as source health `failed`, not as a placeholder success.
        """

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{META_BASE}/jobsearch/",
        }
        by_id: dict[str, Job] = {}
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            for term in META_SEARCH_TERMS:
                payload = _search_payload(term)
                response = client.post(META_GRAPHQL_ENDPOINT, data=payload)
                response.raise_for_status()
                jobs = parse_meta_jobs_response(response.json(), self.source_priority)
                for job in jobs:
                    by_id.setdefault(job.external_id, job)
                    if len(by_id) >= self.max_results:
                        break
                if len(by_id) >= self.max_results:
                    break
        LOGGER.info("Fetched %s focused Meta jobs", len(by_id))
        return list(by_id.values())


def build_fetcher(source_priority: int = 20) -> MetaCareersFetcher:
    """Build the Meta direct source adapter."""

    return MetaCareersFetcher(source_priority=source_priority)


def parse_meta_jobs_response(payload: dict[str, Any], source_priority: int = 20) -> list[Job]:
    """Parse Meta Careers GraphQL search JSON into normalized jobs."""

    jobs: list[Job] = []
    for item in _extract_meta_job_items(payload):
        title = _first_text(item, "title", "name", "job_title")
        description = _plain_text(_first_text(item, "description", "job_description", "summary"))
        combined = " ".join([title, description, _location_text(item) or ""])
        if not title or not _is_focused_meta_role(title, combined):
            continue
        if _advanced_degree_specific(title, description):
            continue
        if description and THREE_PLUS_RE.search(description) and not EARLY_CAREER_TITLE_RE.search(title):
            continue
        jobs.append(_normalize_meta_job(item, title, description, source_priority))
    return jobs


def _search_payload(term: str) -> dict[str, str]:
    return {
        "doc_id": META_SEARCH_DOC_ID,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": META_SEARCH_FRIENDLY_NAME,
        "variables": json.dumps(
            {"search_input": {"q": term, "results_per_page": "FIVE"}}, separators=(",", ":")
        ),
    }


def _extract_meta_job_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    search = payload.get("data", {}).get("job_search_with_featured_jobs")
    if isinstance(search, dict):
        items = search.get("all_jobs") or search.get("featured_jobs") or []
        return [item for item in items if isinstance(item, dict)]
    return [item for item in _walk_dicts(payload) if _looks_like_job(item)]


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _looks_like_job(item: dict[str, Any]) -> bool:
    return bool(_first_text(item, "id", "job_id", "requisition_id")) and bool(
        _first_text(item, "title", "name", "job_title")
    )


def _normalize_meta_job(
    item: dict[str, Any], title: str, description: str | None, source_priority: int
) -> Job:
    external_id = _first_text(item, "id", "job_id", "requisition_id")
    if not external_id:
        external_id = hashlib.sha256(f"{title}|{_location_text(item)}".encode()).hexdigest()[:16]
    return Job(
        source="Meta",
        source_type="target_company",
        source_priority=source_priority,
        company="Meta",
        external_id=external_id,
        title=title,
        location=_location_text(item),
        url=_meta_job_url(item, external_id),
        department=_department_text(item),
        description=description,
        raw=item,
        verification_status="verified",
    )


def _is_focused_meta_role(title: str, combined_text: str) -> bool:
    return bool(TITLE_INCLUDE_PATTERN.search(combined_text)) and not TITLE_EXCLUDE_PATTERN.search(title)


def _advanced_degree_specific(title: str, description: str | None) -> bool:
    if ADVANCED_DEGREE_RE.search(title):
        return True
    if not description:
        return False
    if BACHELORS_ACCEPTED_RE.search(description) and re.search(
        r"\bbachelor(?:'s|s)?\b[\s\S]{0,120}\b(?:master'?s|masters|ph\.?d\.?)\b",
        description,
        re.I,
    ):
        return False
    return bool(ADVANCED_DEGREE_RE.search(description))


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str | int | float):
            return str(value).strip()
    return ""


def _location_text(item: dict[str, Any]) -> str | None:
    value = item.get("locations") or item.get("location")
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                text = _first_text(entry, "name", "location_display_name", "city", "state", "country")
                if text:
                    parts.append(text)
        return "; ".join(dict.fromkeys(parts)) or None
    if isinstance(value, dict):
        return _first_text(value, "name", "location_display_name", "city", "state", "country") or None
    return None


def _department_text(item: dict[str, Any]) -> str | None:
    value = item.get("team") or item.get("teams")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                text = _first_text(entry, "team_display_name", "name")
                if text:
                    parts.append(text)
        return "; ".join(parts) or None
    return None


def _meta_job_url(item: dict[str, Any], external_id: str) -> str:
    url = _first_text(item, "url", "uri", "job_url")
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return f"{META_BASE}{url}"
    return f"{META_BASE}/jobs/{external_id}/"


def _plain_text(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
