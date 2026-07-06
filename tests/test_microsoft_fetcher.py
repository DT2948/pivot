from __future__ import annotations

import httpx

from pivot.fetchers.microsoft import (
    MicrosoftCareersFetcher,
    parse_microsoft_search_jobs,
)

SEARCH_PAYLOAD = {
    "status": 200,
    "data": {
        "positions": [
            {
                "id": 1970393556000001,
                "displayJobId": "200000001",
                "name": "Software Engineer, University Graduate",
                "locations": ["United States, Washington, Redmond"],
                "standardizedLocations": ["Redmond, WA, US"],
                "department": "Software Engineering",
                "positionUrl": "/careers/job/1970393556000001",
            },
            {
                "id": 1970393556000002,
                "displayJobId": "200000002",
                "name": "Senior Software Engineer",
                "locations": ["United States, Washington, Redmond"],
                "department": "Software Engineering",
                "positionUrl": "/careers/job/1970393556000002",
            },
        ]
    },
}

DETAIL_PAYLOAD = {
    "status": 200,
    "data": {
        "id": 1970393556000001,
        "displayJobId": "200000001",
        "name": "Software Engineer, University Graduate",
        "locations": ["United States, Washington, Redmond"],
        "standardizedLocations": ["Redmond, WA, US"],
        "department": "Software Engineering",
        "positionUrl": "/careers/job/1970393556000001",
        "jobDescription": (
            "<p>Build Azure backend infrastructure and distributed systems.</p>"
            "<p>Minimum qualifications: Bachelor's degree or equivalent practical experience.</p>"
        ),
    },
}


def test_microsoft_parser_keeps_focused_roles_and_excludes_senior() -> None:
    jobs = parse_microsoft_search_jobs(SEARCH_PAYLOAD)

    assert len(jobs) == 1
    assert jobs[0].company == "Microsoft"
    assert jobs[0].source_type == "target_company"
    assert jobs[0].external_id == "200000001"
    assert jobs[0].title == "Software Engineer, University Graduate"
    assert jobs[0].location == "Redmond, WA, US"
    assert jobs[0].url == "https://apply.careers.microsoft.com/careers/job/1970393556000001"


def test_microsoft_fetcher_success_with_mocked_api(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url, headers=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        if str(url).endswith("/careers"):
            return httpx.Response(200, request=request, text='<meta name="_csrf" content="token">')
        if "position_details" in str(url):
            return httpx.Response(200, request=request, json=DETAIL_PAYLOAD)
        return httpx.Response(200, request=request, json=SEARCH_PAYLOAD)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs = MicrosoftCareersFetcher(max_detail_requests=5).fetch()

    assert len(jobs) == 1
    assert jobs[0].external_id == "200000001"
    assert "Azure backend infrastructure" in (jobs[0].description or "")


def test_microsoft_source_health_failed_on_http_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url, headers=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request, text="unavailable")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs, health = MicrosoftCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert "503" in (health.error or "")


def test_microsoft_source_health_failed_on_malformed_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url, headers=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url)
        if str(url).endswith("/careers"):
            return httpx.Response(200, request=request, text="<html></html>")
        return httpx.Response(200, request=request, text="not json")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs, health = MicrosoftCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert health.error == "Microsoft public careers endpoint returned malformed JSON"
