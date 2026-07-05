from __future__ import annotations

from pathlib import Path

from pivot.fetchers.github_markdown import parse_markdown_jobs


def test_github_markdown_parser_from_fixture() -> None:
    markdown = Path("tests/fixtures/simplify_new_grad_sample.md").read_text()
    jobs = parse_markdown_jobs(markdown, "Simplify New Grad")

    assert len(jobs) == 3
    assert jobs[0].company == "Acme AI"
    assert jobs[0].url == "https://jobs.example.com/acme-backend"
    assert "closed" in jobs[1].repo_flags
    assert jobs[2].repo_sponsorship_flag == "no sponsorship"
