from __future__ import annotations

import json
from pathlib import Path

from pivot.fetchers.greenhouse import parse_greenhouse_jobs


def test_greenhouse_parser_from_fixture() -> None:
    payload = json.loads(Path("tests/fixtures/greenhouse_anthropic.json").read_text())
    jobs = parse_greenhouse_jobs(payload, "Anthropic")

    assert len(jobs) == 1
    assert jobs[0].company == "Anthropic"
    assert jobs[0].title == "Software Engineer, Backend - Early Career"
    assert jobs[0].location == "San Francisco, CA"
    assert "distributed systems" in (jobs[0].description or "")
