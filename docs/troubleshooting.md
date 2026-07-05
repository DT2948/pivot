# Troubleshooting

## Gemini API key missing

Pivot logs the missing key and uses rule fallback. Add `GEMINI_API_KEY` locally or as a GitHub Actions secret.

## Gemini quota exceeded

The run should still succeed with rules fallback. Lower `gemini.max_jobs_per_run`.

## Gmail SMTP authentication failed

Use a Gmail App Password, not your normal password. Confirm `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, and 2-Step Verification is enabled.

## No jobs found

Check `data/last_run_source_health.json`. A source may have failed or the upstream feed may have changed.

## Too many jobs emailed

Raise thresholds in `config/settings.yaml`, lower `gemini.max_jobs_per_run`, or add stricter negative keywords in `src/pivot/filtering.py`.

## Workflow did not run

Check the Actions tab. Scheduled workflows can be delayed. Run manually with `workflow_dispatch`.

## Source parser failed

The source should be marked failed without crashing the run. Check logs and source health. Disable the source in `config/companies.yaml` if it stays broken.

## seen_jobs.json conflicts

Resolve it like any JSON merge conflict. Preserve existing records where possible. If needed, keep the larger object and rerun Pivot.

## Reset seen state carefully

To receive alerts again for everything, replace `data/seen_jobs.json` with `{}`. This can cause duplicate emails on the next normal run.
