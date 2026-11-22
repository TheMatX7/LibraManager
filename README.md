# LibraManager

LibraManager is a layered Python/Flask library-management project.  The
business layer works through services and repositories over SQLite; HTTP and
CLI controllers must call those services rather than modifying models directly.

## Current implementation status

The service layer contains all fifteen planned services.  The most recently
completed modules are `PaymentService` and `ReportService`:

- Payments use `Decimal`, validate CASH/CARD methods, prevent overpayments and
  update a fine with an optimistic, conditional database update.
- A payment, its fine update, and audit records are written in one transaction.
- Reader payment history is isolated by server-side authorization checks.
- Reports provide dashboard aggregates, loan/reservation/catalogue/financial
  statistics, CSV output, and formula-injection-safe CSV cells.

The application includes an interactive CLI and a server-rendered Flask panel.
Both interfaces call the same service layer and database.  The HTTP panel has
separate administrator, librarian and reader dashboards, catalogue, readers,
circulation, reservations, finance, reports, settings and audit modules.

## Installation

Use Python 3.14 or a compatible Python version:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set a development secret in `.env` (do not commit a production secret):

```text
SECRET_KEY=replace-with-a-long-random-development-secret
```

The standard local database path is `database/library.db`.  Tests use isolated
in-memory or temporary SQLite databases and do not reset this database.

## Running the web application

```powershell
.\.venv\Scripts\python.exe run.py
```

Then check `http://127.0.0.1:5000/health`.

Open `http://127.0.0.1:5000/` to sign in. Do not use Flask's development server
as a production deployment server; enable HTTPS and set
`SESSION_COOKIE_SECURE=true` when deploying behind a TLS reverse proxy.

## Running the CLI

```powershell
.\.venv\Scripts\python.exe run.py --cli
```

The CLI offers role-specific options and delegates each operation to the same
services used by the web interface.

## Demonstration data

Only for a new, empty database:

```powershell
.\.venv\Scripts\python.exe run.py --seed-demo
```

This refuses to run when any user already exists. It prints newly generated
one-time demo passwords only to the local console; no static credential is
stored in the source code.

## Tests

Run the complete installed test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The financial/reporting regression subset is:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_payment_service.py `
  tests/test_payment_repository.py `
  tests/test_report_service.py -q
```

To regenerate coverage and JUnit reports, use:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app/services --cov-branch `
  --cov-report=html:docs/coverage/final `
  --cov-report=xml:docs/coverage/final/coverage.xml `
  --junitxml=docs/test_reports/final.xml
```

See [development progress](docs/DEVELOPMENT_PROGRESS.md) and the
[acceptance report](docs/ACCEPTANCE_REPORT.md) for verified results and
constraints. Read [security notes](docs/SECURITY.md) before deployment, and
use the [user guide](docs/USER_GUIDE.md) together with the
[presentation guide](docs/PRESENTATION_GUIDE.md) during a presentation.
