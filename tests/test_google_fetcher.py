from __future__ import annotations

import httpx

from pivot.fetchers.google import (
    GoogleCareersFetcher,
    parse_google_detail_html,
    parse_google_jobs_from_html,
)

SEARCH_HTML = """
<html><body><main><ul>
<li class="lLd3Je">
  <a href="jobs/results/123-software-engineer-university-graduate-cloud?q=Software+Engineer">
    <h3>Software Engineer, University Graduate, Google Cloud</h3>
  </a>
  <span class="r0wTof">New York, NY, USA</span><span class="r0wTof">; Sunnyvale, CA, USA</span>
</li>
<li class="lLd3Je">
  <a href="jobs/results/124-senior-staff-software-engineer?q=Software+Engineer">
    <h3>Senior Staff Software Engineer, Infrastructure</h3>
  </a>
  <span class="r0wTof">New York, NY, USA</span>
</li>
<li class="lLd3Je">
  <a href="jobs/results/125-software-engineer-backend?q=Software+Engineer">
    <h3>Software Engineer, Backend</h3>
  </a>
  <span class="r0wTof">Seattle, WA, USA</span>
</li>
</ul></main></body></html>
"""

DETAIL_HTML = """
<html><body><main>
<h1>Software Engineer, University Graduate, Google Cloud</h1>
<h2>Minimum qualifications:</h2>
<ul><li>Bachelor's degree in Computer Science.</li></ul>
<p>Build distributed systems and cloud infrastructure.</p>
</main></body></html>
"""

THREE_YEAR_DETAIL_HTML = """
<html><body><main>
<h1>Software Engineer, Backend</h1>
<h2>Minimum qualifications:</h2>
<ul><li>3 years of experience with software development.</li></ul>
<p>Backend infrastructure work.</p>
</main></body></html>
"""


def test_google_parser_reads_result_cards_and_excludes_senior() -> None:
    jobs = parse_google_jobs_from_html(SEARCH_HTML)

    assert [job.external_id for job in jobs] == ["123", "125"]
    assert jobs[0].company == "Google"
    assert jobs[0].source_type == "target_company"
    assert jobs[0].title == "Software Engineer, University Graduate, Google Cloud"
    assert jobs[0].location == "New York, NY, USA; Sunnyvale, CA, USA"
    assert jobs[0].url.startswith("https://www.google.com/about/careers/applications/jobs/results/123")


def test_google_detail_parser_extracts_readable_content() -> None:
    text = parse_google_detail_html(DETAIL_HTML)

    assert text is not None
    assert "Minimum qualifications" in text
    assert "distributed systems" in text


def test_google_fetcher_success_with_mocked_official_pages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        if "jobs/results/?" in str(url):
            return httpx.Response(200, request=request, text=SEARCH_HTML)
        if "/123-" in str(url):
            return httpx.Response(200, request=request, text=DETAIL_HTML)
        if "/125-" in str(url):
            return httpx.Response(200, request=request, text=THREE_YEAR_DETAIL_HTML)
        return httpx.Response(404, request=request)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs = GoogleCareersFetcher(max_detail_requests=5).fetch()

    assert len(jobs) == 1
    assert jobs[0].external_id == "123"
    assert "cloud infrastructure" in (jobs[0].description or "")


def test_google_source_health_success_when_no_matching_roles(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, text="<html><body>No jobs</body></html>")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs, health = GoogleCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "success"
    assert health.fetched_count == 0


def test_google_source_health_failed_on_http_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request, text="Unavailable")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs, health = GoogleCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert "503" in (health.error or "")
