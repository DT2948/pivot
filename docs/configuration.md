# Configuration

`config/profile.yaml` is the main candidate profile. It should describe target roles, skills, projects, interests, and education. Do not add phone numbers.

`config/settings.yaml` options:

- `allow_internships`: allow internship and co-op postings when true.
- `allow_unknown_visa`: keep jobs with unknown sponsorship status.
- `reject_us_citizenship_required`: reject roles requiring U.S. citizenship.
- `reject_security_clearance_required`: reject roles requiring active clearance.
- `location_country`: currently `US`.
- `alert_thresholds.target_company`: direct company alert threshold.
- `alert_thresholds.curated_repo`: curated repo alert threshold.
- `alert_thresholds.unverified_source`: threshold when original posting verification is missing or failed.
- `alert_thresholds.rules_only_fallback` / `alert_thresholds.rule_only_fallback_alert_threshold`: stricter rule-only threshold when Gemini is unavailable or disabled; rule-only alerts also require an alertable role family and `can_rule_alert=true`.
- `gemini.enabled`: enable optional Gemini scoring.
- `gemini.model`: Gemini model name.
- `gemini.max_jobs_per_run`: cap AI calls per run.
- `gemini.min_rule_score_before_gemini`: only send stronger target-company rule candidates to Gemini.
- `gemini.curated_min_rule_score_before_gemini`: lower default threshold for curated repo candidates, currently `5`.
- `email`: names of environment variables used for SMTP. Set `SMTP_USE_SSL=true` when using implicit SSL on port `465`; leave it false or unset for STARTTLS on port `587`.
- `debug`: toggles documenting generated artifacts.

`config/companies.yaml` contains `target_companies` and `github_markdown_sources`. Keep GitHub sources as raw Markdown URLs from `raw.githubusercontent.com`, not normal GitHub HTML pages.



