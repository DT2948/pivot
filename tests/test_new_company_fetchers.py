"""Mock the actual official response shapes; never use network in tests."""

import httpx
import pytest

from pivot.config import load_config
from pivot.fetchers.amd import AMDCareersFetcher
from pivot.fetchers.intel import IntelCareersFetcher
from pivot.fetchers.oracle import OracleCareersFetcher
from pivot.filtering import score_job
from pivot.main import build_fetchers

CLASSES = (OracleCareersFetcher, IntelCareersFetcher, AMDCareersFetcher)
DESCRIPTION = (
    "Bachelor's degree. New graduate software engineer building backend distributed systems."
)


def response_payload(company, detail=False):
    if company == "Oracle":
        if detail:
            return {
                "items": [
                    {
                        "Id": "123",
                        "Title": "Software Engineer New Grad, OCI",
                        "PrimaryLocation": "United States",
                        "secondaryLocations": '[{"Name": "Toronto, Canada"}]',
                        "ExternalDescriptionStr": "<p>" + DESCRIPTION + "</p>",
                        "ExternalQualificationsStr": "Bachelor's degree",
                        "ExternalResponsibilitiesStr": "Python",
                    }
                ]
            }
        row = {
            "Id": "123",
            "Title": "Software Engineer New Grad, OCI",
            "PrimaryLocationCountry": "US",
        }
        return {"items": [{"requisitionList": [row, row]}]}
    if company == "Intel":
        if detail:
            return {
                "jobPostingInfo": {
                    "jobReqId": "JR123",
                    "title": "Compiler Software Engineer New College Graduate",
                    "location": "US, Oregon, Hillsboro",
                    "additionalLocations": ["Toronto, Canada"],
                    "jobDescription": "<p>" + DESCRIPTION + "</p>",
                }
            }
        row = {
            "externalPath": "/job/US-Oregon-Hillsboro/Compiler_JR123",
            "title": "Compiler Software Engineer New College Graduate",
        }
        return {"jobPostings": [row, row]}
    row = {
        "data": {
            "req_id": "123",
            "slug": "123",
            "title": "GPU Software Engineer New Grad",
            "city": "Austin",
            "state": "Texas",
            "country": "United States",
            "description": DESCRIPTION,
        }
    }
    return {"jobs": [row, row]}


def mock_client(monkeypatch, handler):
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )


@pytest.mark.parametrize("cls", CLASSES)
def test_success_description_identity_and_duplicate_searches(monkeypatch, cls):
    name = cls().name
    requests = []

    def handler(request):
        requests.append(request)
        detail = "Details" in request.url.path or "/job/" in request.url.path
        return httpx.Response(200, json=response_payload(name, detail))

    mock_client(monkeypatch, handler)
    jobs, health = cls().safe_fetch()
    assert health.status == "success"
    assert health.fetched_count == 1
    assert len(jobs) == 1
    assert jobs[0].company == name
    assert jobs[0].source_type == "target_company"
    assert "backend distributed systems" in jobs[0].description
    assert "<p>" not in jobs[0].description
    assert jobs[0].url.startswith("https://")
    assert jobs[0].verification_status == "verified"
    assert score_job(jobs[0]).is_candidate
    assert len(requests) <= 5


@pytest.mark.parametrize("cls", CLASSES)
@pytest.mark.parametrize(
    "mode", ["403", "429", "timeout", "html", "missing_list", "bad_row", "bad_detail"]
)
def test_source_failure_is_honest_and_isolated(monkeypatch, cls, mode):
    name = cls().name

    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("read timeout", request=request)
        if mode.isdigit():
            return httpx.Response(int(mode))
        if mode == "html":
            return httpx.Response(200, text="<html>Access denied</html>")
        if mode == "missing_list":
            return httpx.Response(200, json={"message": "not jobs"})
        if mode == "bad_row":
            return httpx.Response(
                200, json={"jobs": [{}], "jobPostings": [{}], "items": [{"requisitionList": [{}]}]}
            )
        detail = "Details" in request.url.path or "/job/" in request.url.path
        if detail or name == "AMD":
            return httpx.Response(
                200,
                json={"items": [{}], "jobPostingInfo": {}, "jobs": [{"data": {"req_id": "123"}}]},
            )
        return httpx.Response(200, json=response_payload(name))

    mock_client(monkeypatch, handler)
    jobs, health = cls().safe_fetch()
    assert jobs == []
    assert health.status == "failed"
    assert health.error
    assert health.fetched_count == 0


def test_configuration_builds_new_sources_and_keeps_apple_paused():
    fetchers = build_fetchers(load_config("config")["companies"])
    names = {x.name for x in fetchers}
    assert {"Oracle", "Intel", "AMD"} <= names
    assert "Apple" not in names


@pytest.mark.parametrize("cls", CLASSES)
def test_valid_empty_search_is_success(monkeypatch, cls):
    payload = {
        "Oracle": {"items": [{"requisitionList": []}]},
        "Intel": {"jobPostings": []},
        "AMD": {"jobs": []},
    }[cls().name]
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=payload))
    jobs, health = cls().safe_fetch()
    assert jobs == []
    assert health.status == "success"
