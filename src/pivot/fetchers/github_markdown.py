"""Raw GitHub Markdown job repo adapter."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from pivot.fetchers.base import Fetcher
from pivot.models import Job
from pivot.verification import detect_visa_signal

LOGGER = logging.getLogger(__name__)
USER_AGENT = "PivotJobAlerts/0.1 (+https://github.com/)"

FLAG_PATTERNS = {
    "no sponsorship": re.compile(r"no\s+sponsor|does\s+not\s+sponsor|without\s+sponsorship", re.I),
    "U.S. citizenship required": re.compile(r"u\.?s\.?\s+citizen|citizenship", re.I),
    "security clearance required": re.compile(r"clearance", re.I),
    "closed": re.compile(r"closed|expired", re.I),
    "advanced degree required": re.compile(r"phd|required\s+master", re.I),
    "FAANG+": re.compile(r"faang|\bmeta\b|\bgoogle\b|\bapple\b|\bamazon\b|\bnetflix\b", re.I),
}


@dataclass(frozen=True)
class MarkdownSource:
    """Config for one raw Markdown source."""

    name: str
    raw_url: str
    source_priority: int = 60
    verify_original: bool = False


class GitHubMarkdownAdapter(Fetcher):
    """Fetch and parse raw Markdown job tables."""

    def __init__(self, source: MarkdownSource, timeout_seconds: float = 20.0) -> None:
        super().__init__(source.name, "curated_repo", source.source_priority)
        self.source = source
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Job]:
        """Fetch raw Markdown and parse jobs."""

        with httpx.Client(timeout=self.timeout_seconds, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(self.source.raw_url)
            response.raise_for_status()
        return parse_markdown_jobs(
            response.text,
            source=self.name,
            raw_url=self.source.raw_url,
            source_priority=self.source_priority,
        )


def parse_markdown_jobs(
    markdown: str,
    source: str,
    raw_url: str = "fixture://markdown",
    source_priority: int = 60,
) -> list[Job]:
    """Extract job rows from common Markdown table formats."""

    if "<table" in markdown.lower():
        html_jobs = _parse_html_tables(markdown, source, raw_url, source_priority)
        if html_jobs:
            return html_jobs

    jobs: list[Job] = []
    category = None
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            category = stripped.lstrip("#").strip()
            continue
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [_clean_markdown_cell(cell) for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or _looks_like_header(cells):
            continue
        company, title, location, url, age = _map_cells(cells)
        if not company or not title or not url:
            continue
        flags = _extract_flags(" ".join(cells))
        external_id = hashlib.sha256(f"{company}|{title}|{location}|{url}".encode()).hexdigest()[:16]
        sponsorship_flag = "no sponsorship" if "no sponsorship" in flags else None
        jobs.append(
            Job(
                source=source,
                source_type="curated_repo",
                source_priority=source_priority,
                company=company,
                external_id=external_id,
                title=title,
                location=location,
                url=url,
                department=category,
                posted_at=age,
                raw={"cells": cells, "raw_url": raw_url},
                repo_flags=flags,
                repo_sponsorship_flag=sponsorship_flag,
                visa_signal="unknown",
                verified_sponsorship_signal="unknown",
                verification_status="unverified",
            )
        )
    return jobs


def verify_original_posting(job: Job, timeout_seconds: float = 10.0) -> Job:
    """Best-effort fetch of the original posting to verify sponsorship and description."""

    try:
        with httpx.Client(timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(job.url, follow_redirects=True)
            response.raise_for_status()
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    except Exception as exc:  # noqa: BLE001 - verification failure should not drop jobs
        LOGGER.info("Could not verify %s at %s: %s", job.title, job.url, exc)
        return job.model_copy(update={"verification_status": "failed"})
    visa_signal = detect_visa_signal(text)
    return job.model_copy(
        update={
            "description": text[:8000],
            "visa_signal": visa_signal,
            "verified_sponsorship_signal": visa_signal,
            "verification_status": "verified",
        }
    )


def _looks_like_header(cells: list[str]) -> bool:
    lowered = [cell.lower() for cell in cells]
    return "company" in lowered[0] and any("role" in c or "title" in c for c in lowered)


def _map_cells(cells: list[str]) -> tuple[str, str, str | None, str, str | None]:
    company = cells[0]
    title = cells[1] if len(cells) > 1 else ""
    location = cells[2] if len(cells) > 2 else None
    url = ""
    for cell in cells:
        url_match = re.search(r"https?://[^\s)>\]]+", cell)
        if url_match:
            url = url_match.group(0)
            break
    if not url and len(cells) > 3:
        url = cells[3]
    age = cells[-1] if len(cells) > 4 else None
    return company, title, location, url, age


def _clean_markdown_cell(cell: str) -> str:
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.I)
    cell = re.sub(r"<[^>]+>", " ", cell)
    cell = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", cell)
    cell = re.sub(r"\[([^\]]+)]\(([^)]+)\)", r"\1 \2", cell)
    return re.sub(r"\s+", " ", cell).strip()


def _extract_flags(text: str) -> list[str]:
    return [name for name, pattern in FLAG_PATTERNS.items() if pattern.search(text)]



def _parse_html_tables(
    markdown: str,
    source: str,
    raw_url: str,
    source_priority: int,
) -> list[Job]:
    soup = BeautifulSoup(markdown, "html.parser")
    jobs: list[Job] = []
    category = None
    last_company = None
    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in {"h2", "h3"}:
            category = element.get_text(" ", strip=True)
            continue
        for row in element.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            company = cells[0].get_text(" ", strip=True)
            if company == "\u21b3" and last_company:
                company = last_company
            elif company:
                last_company = company
            title = cells[1].get_text(" ", strip=True)
            location = cells[2].get_text(" ", strip=True)
            url = _best_application_url(cells[3])
            age = cells[4].get_text(" ", strip=True) if len(cells) > 4 else None
            if not company or not title or not url:
                continue
            image_labels = " ".join(img.get("alt", "") for img in row.find_all("img"))
            row_text = row.get_text(" ", strip=True)
            flags = _extract_flags(f"{row_text} {image_labels}")
            external_id = hashlib.sha256(f"{company}|{title}|{location}|{url}".encode()).hexdigest()[:16]
            sponsorship_flag = "no sponsorship" if "no sponsorship" in flags else None
            jobs.append(
                Job(
                    source=source,
                    source_type="curated_repo",
                    source_priority=source_priority,
                    company=company,
                    external_id=external_id,
                    title=title,
                    location=location,
                    url=url,
                    department=category,
                    posted_at=age,
                    raw={"raw_url": raw_url, "row_text": row_text},
                    repo_flags=flags,
                    repo_sponsorship_flag=sponsorship_flag,
                    verification_status="unverified",
                )
            )
    return jobs


def _best_application_url(cell) -> str:
    links = [link.get("href", "") for link in cell.find_all("a")]
    for url in links:
        if url and "simplify.jobs/p/" not in url:
            return url
    return links[0] if links else ""

