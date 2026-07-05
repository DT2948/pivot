"""Job source adapters."""

from pivot.fetchers.base import Fetcher
from pivot.fetchers.github_markdown import GitHubMarkdownAdapter
from pivot.fetchers.greenhouse import GreenhouseFetcher

__all__ = ["Fetcher", "GitHubMarkdownAdapter", "GreenhouseFetcher"]
