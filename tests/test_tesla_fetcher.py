from __future__ import annotations

import httpx

from pivot.fetchers.tesla import TeslaCareersFetcher, parse_tesla_jobs


def test_tesla_parser_keeps_focused_roles_and_excludes_senior() -> None:
    payload = {
        "response": {
            "results": [
                {
                    "id": "228749",
                    "title": "Software Engineer, Vehicle Software",
                    "location": {"city": "Palo Alto", "state": "CA", "country": "United States"},
                    "department": "Vehicle Software",
                    "description": "<p>Build vehicle software systems.</p>",
                    "url": "/careers/search/job/228749",
                },
                {
                    "id": "228750",
                    "title": "Senior Software Engineer, Autopilot",
                    "location": "Austin, TX",
                    "department": "Autopilot",
                },
                {
                    "id": "228751",
                    "title": "Service Advisor",
                    "location": "Fremont, CA",
                    "department": "Service",
                },
            ]
        }
    }

    jobs = parse_tesla_jobs(payload)

    assert len(jobs) == 1
    assert jobs[0].company == "Tesla"
    assert jobs[0].title == "Software Engineer, Vehicle Software"
    assert jobs[0].external_id == "228749"
    assert jobs[0].location == "Palo Alto, CA, United States"
    assert jobs[0].department == "Vehicle Software"
    assert jobs[0].description == "Build vehicle software systems."
    assert jobs[0].url == "https://www.tesla.com/careers/search/job/228749"


def test_tesla_parser_includes_internship_and_entry_level_roles() -> None:
    payload = {
        "jobs": [
            {
                "jobId": "intern-1",
                "jobTitle": "Internship, AI Infrastructure Software Engineer",
                "locations": ["Fremont, CA", "Palo Alto, CA"],
                "team": "AI Infrastructure",
            },
            {
                "jobId": "entry-1",
                "jobTitle": "Entry Level Backend Software Engineer",
                "city": "Austin",
                "state": "TX",
                "country": "United States",
                "team": "Factory Software",
            },
        ]
    }

    jobs = parse_tesla_jobs(payload)

    assert [job.external_id for job in jobs] == ["intern-1", "entry-1"]
    assert jobs[0].location == "Fremont, CA; Palo Alto, CA"
    assert jobs[1].location == "Austin, TX, United States"


def test_tesla_fetcher_reports_failed_health_for_blocked_endpoint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_get(self, url, params=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(403, request=request, text="Access Denied")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    jobs, health = TeslaCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert "403" in (health.error or "")
