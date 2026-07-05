"""Google careers placeholder adapter."""

from pivot.fetchers.base import PlaceholderFetcher


def build_fetcher() -> PlaceholderFetcher:
    """Return a graceful placeholder."""

    return PlaceholderFetcher("Google", "public careers data is unstable and parser is not implemented")
