from __future__ import annotations

from pivot.fetchers.workday import parse_nvidia_job, parse_nvidia_search_jobs


def test_nvidia_search_parser_keeps_focused_new_grad_and_excludes_senior() -> None:
    payload = {
        "jobPostings": [
            {
                "title": "Systems Software Engineer - New College Grad 2026",
                "externalPath": "/job/US-OR-Hillsboro/Systems-Software-Engineer---New-College-Grad-2026_JR2017083",
                "locationsText": "US, OR, Hillsboro",
                "postedOn": "Posted 30+ Days Ago",
                "bulletFields": ["JR2017083"],
            },
            {
                "title": "Senior Compiler Engineer",
                "externalPath": "/job/US-OR-Hillsboro/Senior-Compiler-Engineer_JR2015674",
                "locationsText": "US, OR, Hillsboro",
                "bulletFields": ["JR2015674"],
            },
            {
                "title": "Account Executive",
                "externalPath": "/job/US-CA-Santa-Clara/Account-Executive_JR1",
                "locationsText": "US, CA, Santa Clara",
                "bulletFields": ["JR1"],
            },
        ]
    }

    jobs = parse_nvidia_search_jobs(payload)

    assert len(jobs) == 1
    assert jobs[0].company == "NVIDIA"
    assert jobs[0].title == "Systems Software Engineer - New College Grad 2026"
    assert jobs[0].external_id == "JR2017083"
    assert jobs[0].location == "US, OR, Hillsboro"
    assert jobs[0].source_type == "target_company"
    assert jobs[0].verification_status == "verified"


def test_nvidia_detail_parser_uses_description_and_locations() -> None:
    item = {
        "title": "Compiler Engineer - AI Inference",
        "externalPath": "/job/US-CA-Santa-Clara/AI-Compiler-Engineer_JR2014497-1",
        "locationsText": "US, CA, Santa Clara",
        "bulletFields": ["JR2014497"],
    }
    detail = {
        "jobPostingInfo": {
            "id": "abc123",
            "title": "Compiler Engineer - AI Inference",
            "jobDescription": "<p>Build compiler infrastructure for AI inference.</p>",
            "locations": [{"descriptor": "Santa Clara, CA"}],
            "jobFamily": "Engineering",
        }
    }

    job = parse_nvidia_job(item, detail)

    assert job.external_id == "abc123"
    assert job.location == "Santa Clara, CA"
    assert job.department == "Engineering"
    assert job.description == "Build compiler infrastructure for AI inference."
    assert job.url.endswith("/job/US-CA-Santa-Clara/AI-Compiler-Engineer_JR2014497-1")
