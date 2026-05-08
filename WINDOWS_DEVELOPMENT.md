# Windows Development Setup (No Docker)

This project can run locally on Windows with SQLite and in-memory Celery, so Docker/Postgres/Redis are not required for development.

## 1) Run setup

From the project root in PowerShell:

```powershell
.\scripts\setup_windows_dev.ps1
```

If your default Python is not 3.12/3.13, pass an explicit interpreter:

```powershell
.\scripts\setup_windows_dev.ps1 -PythonExe "C:\path\to\python.exe"
```

What setup does:
1. Creates `.venv`
2. Installs `requirements.txt`
3. Creates `.env.local` from `.env.local.example` (if missing)
4. Runs migrations and `manage.py check`

## 2) Start the app

```powershell
.\scripts\run_windows_dev.ps1
```

Default URL: `http://127.0.0.1:8000/`

## 3) Local environment behavior

`.env.local` is loaded before `.env`, so local values override Docker/production values.

By default local config uses:
1. SQLite (`DATABASE_URL` blank)
2. In-memory Celery broker/result backend
3. `CELERY_TASK_ALWAYS_EAGER=True` (task calls run in-process)

## Notes

1. PDF generation uses WeasyPrint. On Windows, extra native libraries may be required for PDF export views.
2. If you want Postgres/Redis locally, set `DATABASE_URL`, `REDIS_URL`, and Celery variables in `.env.local`.
