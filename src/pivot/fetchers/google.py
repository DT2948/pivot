"""Google Careers official HTML adapter."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1"
GOOGLE_CAREERS_BASE = "https://www.google.com/about/careers/applications/"
GOOGLE_RESULTS_ENDPOINT = f"{GOOGLE_CAREERS_BASE}jobs/results/"
GOOGLE_SEARCH_TERMS = [
    "Software Engineer University Graduate United States",
    "Software Engineer Early Career United States",
    "Software Engineer New Graduate United States",
    "Systems Software Engineer University Graduate",
    "Infrastructure Software Engineer University Graduate",
    "Backend Software Engineer Early Career",
    "Machine Learning Infrastructure Software Engineer",
    "Site Reliability Engineer Early Career",
]

TITLE_INCLUDE_PATTERN = re.compile(
    r"software\s+engineer|university\s+graduate|new\s+grad(?:uate)?|early\s+career|"
    r"systems?\s+software|infrastructure|backend|distributed\s+systems?|"
    r"machine\s+learning\s+infrastructure|ai/?ml|cloud|site\s+reliability\s+engineer",
    re.I,
)
TITLE_EXCLUDE_PATTERN = re.compile(
    r"\b(senior|staff|principal|manager|director|lead)\b|\bhead\s+of\b|\bsr\.?\b",
    re.I,
)
EARLY_CAREER_PATTERN = re.compile(
    r"university\s+graduate|new\s+grad(?:uate)?|early\s+career|phd,?\s+early\s+career",
    re.I,
)
THREE_PLUS_REQUIREMENT_PATTERN = re.compile(
    r"(?:minimum\s+qualifications?|requirements?|basic\s+qualifications?)"
    r"[\s\S]{0,700}?\b(?:3\+|4\+|5\+|6\+|7\+|8\+|9\+|10\+|3\s+years?|4\s+years?|5\s+years?)",
    re.I,
)


class GoogleCareersFetcher(Fetcher):
    """Fetch focused Google jobs from official Google Careers pages."""

    def __init__(
        self,
        source_priority: int = 20,
        timeout_seconds: float = 20.0,
        max_results_per_query: int = 15,
        max_detail_requests: int = 20,
    ) -> None:
        super().__init__(name="Google", source_type="target_company", source_priority=source_priority)
        self.timeout_seconds = timeout_seconds
        self.max_results_per_query = max_results_per_query
        self.max_detail_requests = max_detail_requests

    def fetch(self) -> list[Job]:
        """Fetch Google Careers result pages and enrich focused roles with details."""

        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        by_url: dict[str, Job] = {}
        with httpx.Client(timeout=self.timeout_seconds, headers=headers, follow_redirects=True) as client:
            for term in GOOGLE_SEARCH_TERMS:
                response = client.get(f"{GOOGLE_RESULTS_ENDPOINT}?q={quote_plus(term)}")
                response.raise_for_status()
                for job in parse_google_jobs_from_html(
                    response.text,
                    source_priority=self.source_priority,
                    max_jobs=self.max_results_per_query,
                ):
                    by_url.setdefault(job.url, job)

            enriched: list[Job] = []
            for job in list(by_url.values())[: self.max_detail_requests]:
                detail_text = _fetch_google_detail(client, job.url)
                if detail_text and _requires_too_much_experience(job.title, detail_text):
                    continue
                enriched.append(
                    job.model_copy(update={"description": detail_text or job.description})
                )
        LOGGER.info("Fetched %s focused Google jobs", len(enriched))
        return enriched


def build_fetcher(source_priority: int = 20) -> GoogleCareersFetcher:
    """Build the Google direct source adapter."""

    return GoogleCareersFetcher(source_priority=source_priority)


def parse_google_jobs_from_html(
    html: str, source_priority: int = 20, max_jobs: int | None = None
) -> list[Job]:
    """Parse server-rendered Google Careers result cards."""

    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    cards = soup.select("li.lLd3Je") or soup.select("li")
    for card in cards:
        title_node = card.find(["h2", "h3"])
        if not title_node:
            continue
        title = title_node.get_text(" ", strip=True)
        if not _is_focused_google_title(title):
            continue
        link = _job_link(card)
        if not link:
            continue
        location = _location_text(card)
        url = urljoin(GOOGLE_CAREERS_BASE, link)
        external_id = _external_id_from_url(url) or hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:16]
        jobs.append(
            Job(
                source="Google",
                source_type="target_company",
                source_priority=source_priority,
                company="Google",
                external_id=external_id,
                title=title,
                location=location,
                url=url,
                department="Google Careers",
                description=card.get_text(" ", strip=True)[:4000],
                raw={"card_text": card.get_text(" ", strip=True)},
                verification_status="verified",
            )
        )
        if max_jobs is not None and len(jobs) >= max_jobs:
            break
    return jobs


def parse_google_detail_html(html: str) -> str | None:
    """Extract readable text from a Google Careers detail page."""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.body or soup
    text = main.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:10000] or None


def _fetch_google_detail(client: httpx.Client, url: str) -> str | None:
    response = client.get(url)
    response.raise_for_status()
    return parse_google_detail_html(response.text)


def _is_focused_google_title(title: str) -> bool:
    return bool(TITLE_INCLUDE_PATTERN.search(title)) and not TITLE_EXCLUDE_PATTERN.search(title)


def _requires_too_much_experience(title: str, description: str) -> bool:
    if EARLY_CAREER_PATTERN.search(title):
        return False
    return bool(THREE_PLUS_REQUIREMENT_PATTERN.search(description))


def _job_link(card: Any) -> str | None:
    for link in card.find_all("a", href=True):
        href = str(link.get("href") or "")
        if "jobs/results" in href:
            return href.strip('"')
    return None


def _location_text(card: Any) -> str | None:
    locations = [node.get_text(" ", strip=True) for node in card.select("span.r0wTof")]
    cleaned = [re.sub(r"^;\s*", "", value).strip() for value in locations if value.strip()]
    if cleaned:
        return "; ".join(dict.fromkeys(cleaned))
    text = card.get_text(" ", strip=True)
    match = re.search(r"place\s+([^|]+?)(?:\s+bar_chart|\s+Early|\s+Advanced|$)", text, re.I)
    return match.group(1).strip() if match else None


def _external_id_from_url(url: str) -> str | None:
    match = re.search(r"/jobs/results/(\d+)", url)
    return match.group(1) if match else None
