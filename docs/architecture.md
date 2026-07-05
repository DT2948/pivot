# Architecture

Pivot has a simple batch pipeline.

Fetchers load jobs from public sources. `GreenhouseFetcher` supports Anthropic through the public board API. `GitHubMarkdownAdapter` reads raw Markdown from curated public repos. Placeholder company adapters return empty lists with clear warnings until stable public parsers are implemented.

Every source becomes a normalized `Job` model. This gives filtering, scoring, email, and state code one common shape.

Filtering is deterministic and cheap. It checks role keywords, seniority, location, internships, citizenship, clearance, and sponsorship language before Gemini is considered.

Gemini scoring is optional. Only candidates above `gemini.min_rule_score_before_gemini` are sent, and only up to `gemini.max_jobs_per_run`. Missing keys, quota errors, and API failures fall back to rules.

Email uses SMTP. Strong new matches are sent after scoring. Test email mode skips fetching and state updates.

State lives in `data/seen_jobs.json`. Jobs are keyed by normalized company, title, location, and canonical URL hash. Meaningful title, URL, or description changes allow rescoring.

GitHub Actions runs lint, tests, Pivot, then commits changed JSON state and debug files back to the repo.
