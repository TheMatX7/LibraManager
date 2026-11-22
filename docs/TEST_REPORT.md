# Test report — final acceptance

## Result

Full regression completed successfully on 2026-11-22 after the final
CLI/WWW/security and visual-QA changes:

- 1750 passed
- duration: 219.37 seconds (3:39)
- Services statement/branch coverage: 97%

The run used Python 3.14.5, pytest 9.2.0, coverage 7.17.4 and pytest-cov 7.1.0.

## Command

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app/services --cov-branch `
  --cov-report=term-missing `
  --cov-report=html:docs/coverage/final `
  --cov-report=xml:docs/coverage/final/coverage.xml `
  --junitxml=docs/test_reports/final.xml -q
```

## Generated artifacts

- `coverage/final/index.html` — interactive HTML coverage report
- `coverage/final/coverage.xml` — machine-readable coverage report
- `test_reports/final.xml` — JUnit report

## Service coverage highlights

| Service | Coverage |
| --- | ---: |
| FineService | 100% |
| PaymentService | 98% |
| ReportService | 98% |
| All services | 97% |

The payment tests include partial and final settlement, RBAC/IDOR checks,
validation, audit atomicity, rollback and two independent SQLite sessions. The
report tests cover dashboard aggregates, financial reports, CSV formula
protection, role checks, limits and reporting-period validation. HTTP tests
cover CSRF, authentication, server-side role restrictions, report export,
security headers, secure cookies, brute-force throttling, forced logout and
production error handling; CLI and demo bootstrap tests verify their service
integration.
