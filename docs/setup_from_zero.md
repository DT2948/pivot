# Setup From Zero

1. Create a GitHub account if you do not have one.
2. Create a new private or public repository for Pivot.
3. Clone it locally.
4. Add these project files and push them.
5. Install Python 3.11 or newer.
6. Create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

7. Run checks.

```powershell
ruff check .
pytest
python -m pivot.main --dry-run --no-gemini
```

8. Create a Gemini API key in Google AI Studio if you want optional AI scoring.
9. For Gmail, enable 2-Step Verification and create an App Password.
10. In GitHub, open repo Settings -> Secrets and variables -> Actions.
11. Add `GEMINI_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, and `ALERT_EMAIL_TO`.
12. Open the Actions tab and enable workflows if GitHub asks.
13. Choose `Pivot Job Alerts`, click Run workflow, and watch the logs.
14. Confirm that the job passes tests, runs Pivot, and commits JSON state changes.
15. Use `python -m pivot.main --send-test-email` locally to confirm SMTP settings before expecting scheduled alerts.
