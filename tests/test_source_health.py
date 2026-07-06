from __future__ import annotations

from pivot.fetchers.base import PlaceholderFetcher


def test_placeholder_fetcher_reports_not_implemented() -> None:
    jobs, health = PlaceholderFetcher("Tesla", "parser not implemented").safe_fetch()

    assert jobs == []
    assert health.status == "not_implemented"
    assert health.error == "parser not implemented"
