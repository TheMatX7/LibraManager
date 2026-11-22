# LibraManager contribution rules

## Architecture

- Preserve the flow: CLI/Flask route → service → repository → SQLAlchemy model.
- Place business rules, authorization, validation, transactions and audit calls
  in services. Repositories are data access only and never commit themselves.
- All new write operations must use `BaseService.transaction()` (or participate
  in a documented surrounding transaction) and be rollback-safe.
- Do not access `db.session` directly from routes, templates or CLI menus.
- Existing SQLite schema changes require a migration/upgrade plan; never reset
  `database/library.db` as part of tests or development work.

## Security and data integrity

- Enforce RBAC in every public service method. Protect reader-owned resources
  from IDOR by verifying the reader relationship server-side.
- Use `Decimal` for money. Reject float, bool, non-finite, non-positive and
  values with more than two decimal places where a payment is expected.
- Payment history is append-only. Use `FineRepository.update_payment_state()`
  for conditional payment-state changes; do not replace it with assignment.
- Keep payment, fine-state and audit writes in one transaction. Never retry a
  potentially ambiguous financial operation automatically.
- Keep secrets in environment variables, keep production debugging disabled,
  and do not add production credentials to the repository.
- CSV export must neutralize spreadsheet formula cells beginning with `=`, `+`,
  `-`, or `@`.

## Testing and documentation

- Add behavior-focused pytest tests alongside any non-trivial service change:
  validation, authorization, rollback, financial consistency and regressions.
- Test SQLite concurrency using a temporary file database and independent app
  contexts/sessions when touching optimistic payment logic.
- Run a focused suite while iterating, then run the full suite before declaring
  a milestone complete. Do not change tests merely to hide a regression.
- Update `README.md` and `docs/DEVELOPMENT_PROGRESS.md` with actual commands,
  results, known limitations and the next continuation point.
- Preserve historical files in `backup/`. Make a dated/scope-specific backup
  before substantial source changes when Git history is unavailable.
