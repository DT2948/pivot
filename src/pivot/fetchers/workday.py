"""Workday/custom placeholder adapter."""

from pivot.fetchers.base import PlaceholderFetcher


def build_nvidia_fetcher() -> PlaceholderFetcher:
    """Return a graceful NVIDIA placeholder."""

    return PlaceholderFetcher("NVIDIA", "stable public NVIDIA endpoint not implemented")
