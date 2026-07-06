# Troubleshooting

## Gemini API key missing

Pivot logs the missing key and uses rule fallback. Add `GEMINI_API_KEY` locally or as a GitHub Actions secret.

## Gemini quota exceeded

The run should still succeed with safe rules fallback. Pivot counts attempted Gemini calls, stops when `gemini.max_jobs_per_run` is reached, and stops Gemini scoring immediately after a 429 quota or `RESOURCE_EXHAUSTED` error. Required-Gemini candidates that were not scored will not alert.

## Gemini returned scores above 10

Pivot expects Gemini scores on a 0-10 scale. Percent-style scores from 10 to 100 are normalized by dividing by 10, and invalid scores fall back safely. If this keeps happening, inspect the prompt in `src/pivot/gemini_scorer.py` and `data/last_run_candidates.json`.

## Gmail SMTP authentication failed

Use a Gmail App Password, not your normal password. Confirm `SMTP_HOST=smtp.gmail.com` and 2-Step Verification is enabled. Use `SMTP_PORT=587` with STARTTLS, or `SMTP_PORT=465` with `SMTP_USE_SSL=true`.

## No jobs found

Check `data/last_run_source_health.json`. A source may have failed or the upstream feed may have changed.

## Too many jobs emailed

Raise thresholds in `config/settings.yaml`, lower `gemini.max_jobs_per_run`, or add stricter negative keywords in `src/pivot/filtering.py`.

## Workflow did not run

Check the Actions tab. Scheduled workflows can be delayed. Run manually with `workflow_dispatch`.

## Source parser failed

The source should be marked `failed` without crashing the run. Tesla may report `failed` with a 403 when its official careers API blocks the runner. Placeholder adapters are marked `not_implemented`, which is expected for Meta and Apple until direct adapters exist. Check logs and source health. Disable a broken real source in `config/companies.yaml` if it stays broken.

## Strong curated role did not alert

Check `can_rule_alert`, `role_family`, `rejection_reasons`, and `final_score` in `data/last_run_candidates.json`. Curated repo rule-only alerts need a strong new-grad signal and must meet `alert_thresholds.curated_repo_rule_only_alert_threshold`, currently `8.5`.

## seen_jobs.json conflicts

Resolve it like any JSON merge conflict. Preserve existing records where possible. If needed, keep the larger object and rerun Pivot.

## Reset seen state carefully

To receive alerts again for everything, replace `data/seen_jobs.json` with `{}`. This can cause duplicate emails on the next normal run.
