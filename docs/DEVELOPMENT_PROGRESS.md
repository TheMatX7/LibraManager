# LibraManager — development progress

## Current stage

Stages 9.17–9.18 and stages 10–15 are complete. The project contains a
service-backed interactive CLI, Flask web panel, responsive HTML/CSS/JS
frontend, role-specific dashboards, security controls, safe demo bootstrap,
system/integration tests and final presentation documentation. The application
is ready for a controlled academic demonstration.

## Completed in this work session

- Audited the current source, repositories, tests, database models and existing
  backups. The workspace has no Git metadata, so no Git operations were used.
- Created `backup/9_17_4_5_pre_payment_completion/` before changing the
  payment implementation.
- Completed the 30-method public/internal `PaymentService` contract:
  registration, complete settlement, history, own-history access, totals,
  method totals, summaries and count.
- Added `PaymentRepository.get_total_by_method()`.
- Enforced payment-history authorization, including non-enumerable missing
  payment IDs for readers.
- Added payment regression tests covering partial/full payment, audit events,
  input validation, overpayment, rollback and a true two-session SQLite race.
- Implemented `ReportService` and exported it from `app.services`.
- Added library, loan, reservation, top-book, category, financial and admin
  dashboard reports; added whitelisted, formula-injection-safe CSV export.
- Added ReportService RBAC, period and limit tests.
- Created this progress document, `AGENTS.md`, and the project README.
- Added `LibraryCLI`, launched with `python run.py --cli`. It uses the same
  services as the browser panel for login, catalogue, circulation,
  reservations, payments, profile and staff reporting operations.
- Replaced the diagnostic root page with an authenticated Flask web panel;
  `/health` remains the JSON diagnostic endpoint. The corresponding contract
  test was deliberately updated and explains the new behavior.
- Added administrator, librarian and reader dashboards and Polish pages for
  catalogue, authors, categories, copies, readers, users, loans, reservations,
  fines, payments, reports, settings, audit and profile operations.
- Added Flask-WTF CSRF protection, session hardening, in-process failed-login
  throttling, CSP/security headers, server-side role checks and HTTP tests.
- Added `run.py --seed-demo`, which only operates on an empty database and
  prints randomly generated demo credentials locally.
- Completed CRUD acceptance review for books, authors, categories, copies,
  readers and users; added polished HTML error pages and a no-op favicon route.
- Added final browser QA evidence in `docs/screenshots/acceptance/`, a complete
  presentation scenario and `docs/ACCEPTANCE_REPORT.md`.
- Added acceptance tests for cookie flags, forced logout after deactivation,
  production secret enforcement and non-debug HTML errors.

## Changed files

- `app/services/payment_service.py`
- `app/repositories/payment_repository.py`
- `app/services/report_service.py`
- `app/services/__init__.py`
- `tests/test_payment_service.py`
- `tests/test_report_service.py`
- `app/cli/console.py`
- `app/routes/web.py`
- `app/__init__.py`
- `app/templates/` and `app/static/`
- `app/demo.py`
- `tests/test_cli.py`
- `tests/test_web.py`
- `tests/test_demo.py`
- `tests/test_security_web.py`
- `.gitignore`
- `docs/SECURITY.md`
- `README.md`
- `AGENTS.md`
- `docs/DEVELOPMENT_PROGRESS.md`
- `docs/PRESENTATION_GUIDE.md`
- `docs/ACCEPTANCE_REPORT.md`
- `docs/screenshots/acceptance/reader-dashboard.png`

## Architectural decisions

- Money remains `Decimal` at service and repository boundaries. The report
  layer normalizes SQL aggregate results to `Decimal('0.01')` precision.
- Fine payment updates retain the repository's conditional update, which makes
  a stale state fail rather than allowing a second payment.
- A concurrent SQLite loser may get either a stale-state rejection or SQLite's
  write-lock database error. Both are safe rejections; the service does not
  retry a financial request automatically because the caller cannot know if a
  payment was accepted after a transport failure.
- Reporting stays read-only. CSV accepts only a fixed report-name allow-list;
  it cannot execute arbitrary SQL or ORM expressions.
- Database timestamps are the existing schema's naive UTC datetimes. Report
  period arguments deliberately require the same format.

## Verified tests

Executed with `.\.venv\Scripts\python.exe`:

| Command | Result |
| --- | --- |
| `-m pytest tests/test_payment_repository.py -q` (baseline) | 31 passed |
| `-m pytest tests/test_payment_service.py tests/test_payment_repository.py -q` | 49 passed |
| `-m pytest tests/test_report_service.py tests/test_payment_service.py tests/test_payment_repository.py -q` | 52 passed |
| `-m compileall -q app tests` | passed |
| Full `-m pytest --cov=app/services --cov-branch ... -q` | 1729 passed in 198.45 s; 96% Services coverage |
| Full `-m pytest --cov=app/services --cov-branch ... -q` after CLI/WWW/security work | 1739 passed in 202.41 s; 97% Services coverage |
| Focused `tests/test_security_web.py tests/test_web.py -q` after final QA changes | 16 passed |
| Full `-m pytest --cov=app/services --cov-branch ... -q` after final acceptance changes | 1750 passed in 219.37 s; 97% Services coverage |

Current artifacts from the full regression:

- HTML coverage: `docs/coverage/final/index.html`
- XML coverage: `docs/coverage/final/coverage.xml`
- JUnit XML: `docs/test_reports/final.xml`

The final coverage command included branch coverage. Critical financial
services measured 100% for `FineService`, 98% for `PaymentService`, and 98%
for `ReportService`; overall `app/services` coverage is 97%. The few uncovered
payment branches defend impossible inconsistent fine states already rejected by
the consistency guard; report gaps are `None`/datetime CSV formatting edges.

## Known limitations and next continuation point

1. For deployment beyond an academic localhost demo, add a production WSGI
   configuration, HTTPS proxy, external rate limiting and an operational
   database backup job.
2. A future iteration may add email-based password recovery and an external
   payment gateway; neither is required by the current scope.
