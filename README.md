# Pivot

Pivot monitors new-grad software engineering roles and turns noisy job feeds into a personalized shortlist.

Pivot is a personal, zero-cost job alert system. It fetches public target-company postings and raw Markdown job feeds, normalizes them, filters for Darsh Tejusinghani's new-grad SWE profile, optionally scores a small capped set with Gemini free tier, and emails only strong new matches.

## What It Does

- Runs locally with `python -m pivot.main`.
- Runs every 6 hours with GitHub Actions.
- Supports Anthropic through Greenhouse, NVIDIA through Workday, Tesla through its official careers API, plus SimplifyJobs and SpeedyApply raw Markdown backup sources.
- Keeps Meta, Google, and Apple configured as graceful best-effort placeholders until direct adapters are implemented.
- Uses deterministic filtering before Gemini to control cost and noise.
- Falls back safely to rules if Gemini is missing, over quota, unavailable, or broken.
- Tracks seen jobs in `data/seen_jobs.json`.
- Writes ignored debug artifacts: `data/last_run_candidates.json`, `data/last_run_rejections.json`, and `data/last_run_source_health.json`.

## What It Does Not Do

Pivot does not run a website or always-on server. It does not use GitHub Pages. GitHub Actions temporarily runs the Python script on a schedule.

It also does not scrape LinkedIn, bypass CAPTCHAs, use proxies, use paid APIs, use paid databases, or require a resume PDF.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ruff check .
pytest
python -m pivot.main --dry-run --no-gemini
```

For Gemini scoring, create a free Gemini API key in Google AI Studio and set `GEMINI_API_KEY`.

For Gmail SMTP, use `smtp.gmail.com` with either port `587` and STARTTLS or port `465` with `SMTP_USE_SSL=true`. Enable 2-Step Verification, create a Gmail App Password, and store it as `SMTP_PASSWORD`. Never commit it.

Required email variables:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
ALERT_EMAIL_FROM=your-email@gmail.com
ALERT_EMAIL_TO=your-email@gmail.com
```

For implicit SSL, use:

```text
SMTP_PORT=465
SMTP_USE_SSL=true
```

Send a test email:

```powershell
python -m pivot.main --send-test-email
```

## CLI

```powershell
python -m pivot.main --dry-run
python -m pivot.main --send-test-email
python -m pivot.main --max-gemini-jobs 5
python -m pivot.main --no-gemini
python -m pivot.main --config-dir config
python -m pivot.main --log-level INFO
```

Dry-runs fetch, filter, score, print source health, and write debug artifacts. They do not send email or update `seen_jobs.json`.

## GitHub Actions Setup

Push this repo to GitHub, then add repository secrets under Settings -> Secrets and variables -> Actions:

- `GEMINI_API_KEY` optional
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USE_SSL` optional
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`

Open the Actions tab, choose `Pivot Job Alerts`, and run it manually once with `workflow_dispatch`. The schedule is `17 */6 * * *`; edit `.github/workflows/pivot.yml` to change it. Disable the workflow from the Actions tab if needed.

## Configuration

- Edit `config/profile.yaml` to tune Darsh's scoring profile.
- Edit `config/settings.yaml` for thresholds, internship policy, visa handling, Gemini limits, and SMTP env var names.
- Edit `config/companies.yaml` to enable or disable sources.

To add a Greenhouse company, add a target company with `adapter: greenhouse` and its public board token. To add a GitHub job repo, add a raw `raw.githubusercontent.com` Markdown URL under `github_markdown_sources`.

Rule-only alerts use stricter source-specific thresholds. Target-company roles without a clear new-grad or early-career signal require Gemini review before they can alert. Curated repo roles can rule-alert at the curated threshold only when they have a strong new-grad signal, pass all hard filters, and meet `curated_repo_rule_only_alert_threshold`.

Gemini scores are normalized to Pivot's 0-10 scale. The run stops Gemini scoring at `gemini.max_jobs_per_run` attempted calls, treats 429 quota errors as a run-level stop, and falls back safely for required-Gemini candidates that could not be scored.

## Debugging Alerts

Inspect `data/last_run_rejections.json` to see why jobs were rejected. Inspect `data/last_run_candidates.json` to see jobs that passed filtering, including `role_family`, `requires_gemini_review`, and `can_rule_alert`. Source failures are in `data/last_run_source_health.json`.

## Privacy

Do not commit phone numbers, secrets, app passwords, or unnecessary personal data. `config/profile.yaml` is the primary scoring input. A resume is optional and should be redacted; see `docs/resume/README.md`.

## Current Limitations

NVIDIA is implemented through its official Workday careers API. Tesla is implemented against its official careers API, but that endpoint may return 403 from some runners and will report `failed` rather than `not_implemented` when blocked. Meta, Google, and Apple remain graceful placeholders. Anthropic, NVIDIA, Simplify New Grad, and SpeedyApply 2027 are the useful working sources today.
