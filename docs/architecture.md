# Architecture

Pivot has a simple batch pipeline.

Fetchers load jobs from public sources. `GreenhouseFetcher` supports Anthropic through the public board API. `NvidiaWorkdayFetcher` uses NVIDIA's official Workday CXS careers API. `GoogleCareersFetcher` parses official Google Careers result/detail pages. `TeslaCareersFetcher` uses Tesla's official careers API and reports `failed` if Tesla blocks the runner with a 403. `GitHubMarkdownAdapter` reads raw Markdown from curated public repos. Meta and Apple are currently best-effort placeholder adapters with source health status `not_implemented` until stable public parsers are implemented.

Every source becomes a normalized `Job` model. This gives filtering, scoring, email, and state code one common shape.

Filtering is deterministic and cheap. It classifies role family, checks role keywords, seniority, location, internships, citizenship, clearance, and sponsorship language before Gemini is considered. Location detection recognizes U.S. state abbreviations, common city aliases such as SF/NYC/LA/DC/Bay Area, and mixed U.S./non-U.S. location strings when at least one location is clearly U.S.

Alert gating is conservative. Target-company roles without a clear new-grad or early-career signal require Gemini review before emailing. Curated repo roles can rule-alert when they have a strong new-grad signal, pass hard filters, and meet the curated rule-only threshold. Fellowship/program, sales, legal, finance, product-management, support, hard no-sponsorship, citizenship, and clearance roles cannot alert by default for curated/unverified sources. Direct target-company roles keep sponsorship, citizenship, and clearance text as debug context instead of alert blockers.

Gemini scoring is optional. Only candidates above the configured rule-score floor are sent, and only up to `gemini.max_jobs_per_run` attempted calls. Scores are validated on a 0-10 scale; percent-style scores such as 40 are normalized to 4.0. Missing keys, invalid scores, quota errors, 503 bursts, and API failures fall back safely to rules. Required-Gemini candidates that fall back do not alert.

Email uses SMTP. Strong new matches are sent after scoring. Test email mode skips fetching and state updates.

State lives in `data/seen_jobs.json`. Jobs are keyed by normalized company, title, location, and canonical URL hash. Meaningful title, URL, or description changes allow rescoring.

GitHub Actions runs lint, tests, and Pivot. It uploads last-run debug JSON files as workflow artifacts and commits only `data/seen_jobs.json` back to the repo when the seen state changes.
