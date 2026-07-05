"""Tesla careers placeholder adapter."""

from pivot.fetchers.base import PlaceholderFetcher


def build_fetcher() -> PlaceholderFetcher:
    """Return a graceful placeholder until a stable public adapter is added."""

    return PlaceholderFetcher("Tesla", "stable public Tesla parser not implemented")
