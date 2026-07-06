from __future__ import annotations

import httpx

from pivot.fetchers.meta import (
    MetaCareersFetcher,
    build_meta_search_request,
    parse_meta_jobs_response,
)

META_PAYLOAD = {
    "data": {
        "job_search_with_featured_jobs": {
            "all_jobs": [
                {
                    "id": "111",
                    "title": "Software Engineer, New Grad",
                    "locations": ["Menlo Park, CA", "New York, NY"],
                    "description": "Build backend infrastructure and distributed systems.",
                    "teams": [{"team_display_name": "University Grad - Engineering"}],
                },
                {
                    "id": "222",
                    "title": "Staff Software Engineer, Infrastructure",
                    "locations": ["Menlo Park, CA"],
                    "description": "Infrastructure role.",
                },
                {
                    "id": "333",
                    "title": "Software Engineer, PhD University Grad",
                    "locations": ["Seattle, WA"],
                    "description": "PhD candidates only.",
                },
            ]
        }
    }
}


def test_meta_search_request_construction() -> None:
    request = build_meta_search_request("Software Engineer University Graduate")

    assert request["method"] == "POST"
    assert request["url"] == "https://www.metacareers.com/api/graphql/"
    assert request["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert request["headers"]["X-FB-Friendly-Name"] == "CPJobSearchSourceQuery"
    assert request["data"]["doc_id"] == "27807005005556827"
    assert request["data"]["fb_api_req_friendly_name"] == "CPJobSearchSourceQuery"
    assert "Software Engineer University Graduate" in request["data"]["variables"]


def test_meta_parser_keeps_focused_undergrad_roles_and_excludes_staff_phd() -> None:
    jobs = parse_meta_jobs_response(META_PAYLOAD)

    assert len(jobs) == 1
    assert jobs[0].company == "Meta"
    assert jobs[0].source_type == "target_company"
    assert jobs[0].external_id == "111"
    assert jobs[0].title == "Software Engineer, New Grad"
    assert jobs[0].location == "Menlo Park, CA; New York, NY"
    assert jobs[0].department == "University Grad - Engineering"
    assert jobs[0].url == "https://www.metacareers.com/jobs/111/"


def test_meta_parser_allows_normal_university_graduate_wording() -> None:
    payload = {
        "data": {
            "job_search_with_featured_jobs": {
                "all_jobs": [
                    {
                        "id": "444",
                        "title": "Software Engineer, University Graduate",
                        "locations": ["Menlo Park, CA"],
                        "description": "Bachelor's degree. Build backend infrastructure systems.",
                    }
                ]
            }
        }
    }

    jobs = parse_meta_jobs_response(payload)

    assert len(jobs) == 1
    assert jobs[0].external_id == "444"


def test_meta_fetcher_success_with_mocked_graphql(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(self, url, data=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json=META_PAYLOAD)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    jobs = MetaCareersFetcher().fetch()

    assert len(jobs) == 1
    assert jobs[0].external_id == "111"


def test_meta_source_health_success_with_zero_matches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(self, url, data=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"data": {"job_search_with_featured_jobs": {"all_jobs": []}}},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    jobs, health = MetaCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "success"
    assert health.fetched_count == 0


def test_meta_source_health_failed_on_graphql_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(self, url, data=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", url)
        return httpx.Response(400, request=request, text="Sorry, something went wrong")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    jobs, health = MetaCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert health.error == "Meta public careers endpoint returned 400"


def test_meta_source_health_failed_on_malformed_graphql_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(self, url, data=None):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, text="not json")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    jobs, health = MetaCareersFetcher().safe_fetch()

    assert jobs == []
    assert health.status == "failed"
    assert health.error == "Meta public careers endpoint returned malformed JSON"
