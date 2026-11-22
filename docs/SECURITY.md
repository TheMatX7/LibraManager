# Security notes

## Controls implemented

- Authentication is performed by `AuthService`; passwords use Werkzeug's
  scrypt hashes and application code never stores plaintext passwords.
- Authorization is enforced in public service methods and again at route level.
  Reader-owned loans, reservations, fines and payments use reader access checks
  to prevent IDOR.
- Flask-WTF CSRF protection covers all POST forms. Session replacement on login
  preserves only the CSRF secret, preventing session fixation.
- Cookies are HTTP-only and `SameSite=Lax`. Set `SESSION_COOKIE_SECURE=true`
  in an HTTPS deployment.
- Login throttling limits an IP address to five failed attempts over five
  minutes in a single process. A multi-worker deployment should additionally
  use shared proxy/cache rate limiting.
- Application responses set CSP, `X-Frame-Options: DENY`, `nosniff` and a
  restrictive referrer policy.
- ORM repositories and parameterized SQLAlchemy statements prevent SQL
  injection; templates autoescape output. CSV cells that can be interpreted as
  spreadsheet formulae are prefixed safely.
- Payment/fine/audit writes use one transaction and an optimistic conditional
  fine update. The system never automatically retries ambiguous payment calls.

## Deployment requirements

1. Set a long random `SECRET_KEY` in the environment; production startup fails
   if it is absent.
2. Run behind HTTPS, enable `SESSION_COOKIE_SECURE`, disable development mode,
   and use a production WSGI server/reverse proxy.
3. Restrict file permissions on `.env` and `database/library.db`; back up the
   database through an operational process, not test commands.
4. Use an external/shared rate limiter when running multiple application
   processes.

## Remaining operational considerations

The built-in login throttle is intentionally lightweight rather than a full
account-lockout system. There is no email recovery or external payment gateway;
both require additional infrastructure and policy decisions.
