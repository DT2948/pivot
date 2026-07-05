"""Apple careers placeholder adapter."""

from pivot.fetchers.base import PlaceholderFetcher


def build_fetcher() -> PlaceholderFetcher:
    """Return a graceful placeholder."""

    return PlaceholderFetcher("Apple", "best-effort public careers parser not implemented")
