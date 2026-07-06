"""Microsoft Careers official API adapter."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job, SourceHealth

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1"
MICROSOFT_BASE = "https://apply.careers.microsoft.com"
MICROSOFT_CAREERS_HOME = f"{MICROSOFT_BASE}/careers"
MICROSOFT_SEARCH_ENDPOINT = f"{MICROSOFT_BASE}/api/pcsx/search"
MICROSOFT_DETAIL_ENDPOINT = f"{MICROSOFT_BASE}/api/pcsx/position_details"
MICROSOFT_DOMAIN = "microsoft.com"
MICROSOFT_SEARCH_TERMS = [
    "Software Engineer University Graduate",
    "Software Engineer New Grad",
    "Software Engineer New Graduate",
    "Software Engineer Early Career",
    "Software Engineer I",
    "Cloud Infrastructure Software Engineer Early Career",
    "Azure Backend Infrastructure Software Engineer",
    "Systems Software Engineer Early Career",
    "AI ML Infrastructure Software Engineer Early Career",
    "Site Reliability Engineer Early Career",
    "Production Engineer Early Career",
]

TITLE_INCLUDE_PATTERN = re.compile(
    r"software\s+engineer|site\s+reliability|production\s+engineer|systems?\s+software|"
    r"cloud|azure|infrastructure|backend|distributed\s+systems?|ai/?ml|machine\s+learning",
    re.I,
)
TITLE_EXCLUDE_PATTERN = re.compile(
    r"\b(senior|staff|principal|manager|director|lead)\b|\bhead\s+of\b|\bsr\.?\b",
    re.I,
)
EARLY_CAREER_TITLE_RE = re.compile(
    r"\bnew\s+grad(?:uate)?\b|\buniversity\s+grad(?:uate)?\b|\bnew\s+college\s+grad\b|"
    r"\bearly\s+career\b|\bsoftware\s+engineer\s+i\b",
    re.I,
)
THREE_PLUS_RE = re.compile(
    r"(?:minimum\s+qualifications?|requirements?|basic\s+qualifications?)"
    r"[\s\S]{0,700}?\b(?:3\+|4\+|5\+|6\+|7\+|8\+|9\+|10\+|"
    r"3\s+or\s+more|4\s+or\s+more|5\s+or\s+more|3\s+years?|4\s+years?|5\s+years?)",
    re.I,
)
ADVANCED_DEGREE_TITLE_RE = re.compile(
    r"\bph\.?d\.?\b|\bdoctoral\b|\bdoctorate\b|\bpostdoc(?:toral)?\b|"
    r"\bmaster'?s\b|\bmasters\b|\bm\.?s\.?\b",
    re.I,
)
ADVANCED_DEGREE_EXCLUSIVE_RE = re.compile(
    r"\bdoctoral\b|\bdoctorate\b|\bpostdoc(?:toral)?\b|advanced\s+degree\s+required|"
    r"currently\s+enrolled\s+in\s+a?\s*(?:master'?s|masters|ph\.?d\.?)|"
    r"pursuing\s+a?\s*(?:master'?s|masters|ph\.?d\.?)|"
    r"\bph\.?d\.?\s+(?:required|internship|university\s+grad|candidate|program)\b|"
    r"\bmaster'?s\s+(?:required|university\s+grad|candidate|program)\b|"
    r"minimum\s+qualifications?[\s\S]{0,300}?\b(?:master'?s|masters|ph\.?d\.?)\b",
    re.I,
)
BACHELORS_ACCEPTED_RE = re.compile(
    r"\bbachelor(?:'s|s)?\b|\bb\.?s\.?\b|\bundergraduate\b|"
    r"equivalent\s+practical\s+experience",
    re.I,
)


class MicrosoftCareersFetcher(Fetcher):
    """Fetch focused Microsoft jobs from the official careers API."""

    def __init__(
        self,
        source_priority: int = 20,
        timeout_seconds: float = 20.0,
        search_limit: int = 10,
        max_detail_requests: int = 20,
    ) -> None:
        super().__init__(
            name="Microsoft", source_type="target_company", source_priority=source_priority
        )
        self.timeout_seconds = timeout_seconds
        self.search_limit = search_limit
        self.max_detail_requests = max_detail_requests

    def safe_fetch(self) -> tuple[list[Job], SourceHealth]:
        """Fetch Microsoft jobs while reporting malformed public responses cleanly."""

        try:
            jobs = self.fetch()
        except (RuntimeError, httpx.HTTPError) as exc:
            LOGGER.warning("Source %s failed: %s", self.name, exc)
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

    def fetch(self) -> list[Job]:
        """Fetch Microsoft search results and enrich focused roles with details."""

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": MICROSOFT_CAREERS_HOME,
        }
        by_id: dict[str, dict[str, Any]] = {}
        with httpx.Client(
            timeout=self.timeout_seconds, headers=headers, follow_redirects=True
        ) as client:
            _bootstrap_session(client)
            for term in MICROSOFT_SEARCH_TERMS:
                response = client.get(_search_url(term, self.search_limit))
                response.raise_for_status()
                for item in _positions_from_payload(_json_response(response)):
                    title = _first_text(item, "name", "title")
                    if title and _is_focused_microsoft_title(title):
                        by_id.setdefault(_position_id(item), item)

            jobs: list[Job] = []
            for item in list(by_id.values())[: self.max_detail_requests]:
                detail = _fetch_microsoft_detail(client, _position_id(item))
                job = parse_microsoft_job(item, detail, self.source_priority)
                if _should_keep_microsoft_job(job):
                    jobs.append(job)
        LOGGER.info("Fetched %s focused Microsoft jobs", len(jobs))
        return jobs


def build_fetcher(source_priority: int = 20) -> MicrosoftCareersFetcher:
    """Build the Microsoft direct source adapter."""

    return MicrosoftCareersFetcher(source_priority=source_priority)


def parse_microsoft_search_jobs(payload: dict[str, Any], source_priority: int = 20) -> list[Job]:
    """Parse Microsoft Careers search JSON without detail enrichment."""

    jobs: list[Job] = []
    for item in _positions_from_payload(payload):
        title = _first_text(item, "name", "title")
        if title and _is_focused_microsoft_title(title):
            job = parse_microsoft_job(item, None, source_priority)
            if _should_keep_microsoft_job(job):
                jobs.append(job)
    return jobs


def parse_microsoft_job(
    item: dict[str, Any], detail: dict[str, Any] | None = None, source_priority: int = 20
) -> Job:
    """Normalize one Microsoft Careers position."""

    data = (detail or {}).get("data") if isinstance(detail, dict) else None
    info = data if isinstance(data, dict) else {}
    title = _first_text(info, "name", "title") or _first_text(item, "name", "title")
    external_id = _first_text(info, "id", "displayJobId", "atsJobId") or _position_id(item)
    display_id = _first_text(info, "displayJobId", "atsJobId") or _first_text(
        item, "displayJobId", "atsJobId"
    )
    description = _plain_text(_first_text(info, "jobDescription", "description"))
    location = _location_text(info) or _location_text(item)
    url = (
        _position_url(info) or _position_url(item) or f"{MICROSOFT_BASE}/careers/job/{external_id}"
    )
    return Job(
        source="Microsoft",
        source_type="target_company",
        source_priority=source_priority,
        company="Microsoft",
        external_id=display_id
        or external_id
        or hashlib.sha256(str(item).encode()).hexdigest()[:16],
        title=title or "Untitled Microsoft role",
        location=location,
        url=url,
        department=_first_text(info, "department")
        or _first_text(item, "department")
        or "Microsoft Careers",
        description=description or _plain_text(str(item.get("summary") or "")),
        posted_at=_first_text(info, "postedTs", "postingDate")
        or _first_text(item, "postedTs", "postingDate"),
        raw={"search": item, "detail": detail or {}},
        verification_status="verified",
    )


def _bootstrap_session(client: httpx.Client) -> None:
    response = client.get(
        MICROSOFT_CAREERS_HOME, headers={"Accept": "text/html,application/xhtml+xml"}
    )
    response.raise_for_status()
    match = re.search(r'<meta name="_csrf" content="([^"]+)"', response.text)
    if match:
        client.headers.update({"X-CSRFToken": match.group(1)})


def _search_url(term: str, limit: int) -> str:
    return (
        f"{MICROSOFT_SEARCH_ENDPOINT}?domain={MICROSOFT_DOMAIN}"
        f"&query={quote_plus(term)}&location=United+States&start=0&num={limit}"
    )


def _fetch_microsoft_detail(client: httpx.Client, position_id: str) -> dict[str, Any] | None:
    if not position_id:
        return None
    response = client.get(
        f"{MICROSOFT_DETAIL_ENDPOINT}?domain={MICROSOFT_DOMAIN}&position_id={position_id}"
    )
    response.raise_for_status()
    return _json_response(response)


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Microsoft public careers endpoint returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Microsoft public careers endpoint returned malformed JSON")
    return payload


def _positions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Microsoft public careers endpoint returned malformed JSON")
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise RuntimeError("Microsoft public careers endpoint returned malformed JSON")
    return [item for item in positions if isinstance(item, dict)]


def _is_focused_microsoft_title(title: str) -> bool:
    return bool(TITLE_INCLUDE_PATTERN.search(title)) and not TITLE_EXCLUDE_PATTERN.search(title)


def _should_keep_microsoft_job(job: Job) -> bool:
    title = job.title or ""
    description = job.description or ""
    combined = " ".join([title, description, job.department or ""])
    if not TITLE_INCLUDE_PATTERN.search(combined):
        return False
    if TITLE_EXCLUDE_PATTERN.search(title):
        return False
    if _advanced_degree_specific(title, description):
        return False
    return not (
        description
        and THREE_PLUS_RE.search(description)
        and not EARLY_CAREER_TITLE_RE.search(title)
    )


def _advanced_degree_specific(title: str, description: str | None) -> bool:
    if ADVANCED_DEGREE_TITLE_RE.search(title):
        return True
    if not description:
        return False
    if BACHELORS_ACCEPTED_RE.search(description) and re.search(
        r"\bbachelor(?:'s|s)?\b[\s\S]{0,160}\b(?:master'?s|masters|ph\.?d\.?)\b",
        description,
        re.I,
    ):
        return False
    return bool(ADVANCED_DEGREE_EXCLUSIVE_RE.search(description))


def _position_id(item: dict[str, Any]) -> str:
    return _first_text(item, "id", "positionId", "displayJobId", "atsJobId")


def _position_url(item: dict[str, Any]) -> str | None:
    path = _first_text(item, "positionUrl", "url")
    if not path:
        return None
    if path.startswith("http"):
        return path
    return urljoin(MICROSOFT_BASE, path)


def _location_text(item: dict[str, Any]) -> str | None:
    values = item.get("standardizedLocations") or item.get("locations") or item.get("location")
    if isinstance(values, str):
        return values.strip() or None
    if isinstance(values, list):
        parts = [str(value).strip() for value in values if str(value).strip()]
        return "; ".join(dict.fromkeys(parts)) or None
    return None


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str | int | float):
            return str(value).strip()
    return ""


def _plain_text(html: str | None) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:10000] or None
