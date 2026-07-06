# Configuration

`config/profile.yaml` is the main candidate profile. It should describe target roles, skills, projects, interests, and education. Do not add phone numbers.

`config/settings.yaml` options:

- `allow_internships`: allow internship and co-op postings when true.
- `allow_unknown_visa`: keep jobs with unknown sponsorship status.
- `reject_us_citizenship_required`: reject roles requiring U.S. citizenship.
- `reject_security_clearance_required`: reject roles requiring active clearance.
- `location_country`: currently `US`.
- `alert_thresholds.target_company`: Gemini-scored direct company alert threshold.
- `alert_thresholds.curated_repo`: Gemini-scored curated repo alert threshold.
- `alert_thresholds.unverified_source`: threshold when original posting verification is missing or failed.
- `alert_thresholds.rules_only_fallback` / `alert_thresholds.rule_only_fallback_alert_threshold`: legacy fallback names for rule-only thresholds.
- `alert_thresholds.target_company_rule_only_alert_threshold`: strict rule-only threshold for direct target-company sources, currently `9.0`.
- `alert_thresholds.curated_repo_rule_only_alert_threshold`: rule-only threshold for curated new-grad repo sources, currently `8.5`.
- `gemini.enabled`: enable optional Gemini scoring.
- `gemini.model`: Gemini model name.
- `gemini.max_jobs_per_run`: cap attempted AI calls per run. Failed attempts count toward the cap.
- `gemini.min_rule_score_before_gemini`: only send stronger target-company rule candidates to Gemini.
- `gemini.curated_min_rule_score_before_gemini`: lower default threshold for curated repo candidates, currently `5`.
- `email`: names of environment variables used for SMTP. Set `SMTP_USE_SSL=true` when using implicit SSL on port `465`; leave it false or unset for STARTTLS on port `587`.
- `debug`: toggles documenting generated artifacts.

`config/companies.yaml` contains `target_companies` and `github_markdown_sources`. Keep GitHub sources as raw Markdown URLs from `raw.githubusercontent.com`, not normal GitHub HTML pages.

Current direct target-company support is Anthropic through Greenhouse. Tesla, NVIDIA, Meta, Google, and Apple are configured as best-effort placeholders and report `not_implemented` until direct adapters exist. Simplify New Grad and SpeedyApply 2027 remain backup curated sources.

Rule-only alerts require `can_rule_alert=true`. Target-company roles also need a clear early-career signal such as new grad, university grad, new college grad, entry level, early career, software engineer I, 0-2 years, university hire, or graduate program. Curated repo roles need a strong new-grad signal and the curated rule-only score threshold.
