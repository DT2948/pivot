"""Meta careers placeholder adapter."""

from pivot.fetchers.base import PlaceholderFetcher


def build_fetcher() -> PlaceholderFetcher:
    """Return a graceful placeholder."""

    return PlaceholderFetcher("Meta", "best-effort public careers parser not implemented")
