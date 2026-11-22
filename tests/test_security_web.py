import re

import pytest

from app import create_app
from app.extensions import db
from app.models import Reader, User
from app.services import AuthService, BookService, UserService


@pytest.fixture
def web_users(app):
    auth = AuthService()
    password = "SecurityAcceptancePassword123!"
    admin = User(
        username="security_accept_admin",
        email="security-accept-admin@example.test",
        password_hash=auth.hash_password(password),
        role="ADMIN",
        is_active=True
    )
    librarian = User(
        username="security_accept_librarian",
        email="security-accept-librarian@example.test",
        password_hash=auth.hash_password(password),
        role="LIBRARIAN",
        is_active=True
    )
    reader = User(
        username="security_accept_reader",
        email="security-accept-reader@example.test",
        password_hash=auth.hash_password(password),
        role="READER",
        is_active=True
    )
    db.session.add_all([admin, librarian, reader])
    db.session.flush()
    db.session.add(Reader(
        user_id=reader.id,
        card_number="SECURITY-READER-001",
        first_name="Bezpieczny",
        last_name="Czytelnik"
    ))
    db.session.commit()
    return {
        "admin": admin,
        "librarian": librarian,
        "reader": reader,
        "password": password
    }


def csrf_token(response):
    match = re.search(
        r'name="csrf_token" value="([^"]+)"',
        response.get_data(as_text=True)
    )
    assert match
    return match.group(1)


def login(client, username, password):
    page = client.get("/login")
    return client.post(
        "/login",
        data={
            "csrf_token": csrf_token(page),
            "username": username,
            "password": password
        },
        follow_redirects=True
    )


def test_xss_is_escaped_and_search_input_is_not_sql(client, app):
    password = "SecurityRoutePassword123!"
    user = User(
        username="security_librarian",
        email="security-librarian@example.test",
        password_hash=AuthService().hash_password(password),
        role="LIBRARIAN",
        is_active=True
    )
    db.session.add(user)
    db.session.commit()
    BookService().create_book(user.id, "<script>alert(1)</script>")

    login(client, user.username, password)
    page = client.get("/catalog")
    injection = client.get("/catalog?q=%27%20OR%201%3D1--")

    html = page.get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert injection.status_code == 200


def test_inactive_user_cannot_create_a_session(client, app):
    password = "InactiveRoutePassword123!"
    user = User(
        username="inactive_web_user",
        email="inactive-web@example.test",
        password_hash=AuthService().hash_password(password),
        role="READER",
        is_active=False
    )
    db.session.add(user)
    db.session.commit()

    response = login(client, user.username, password)

    assert "Nieprawidłowy login lub hasło" in response.get_data(as_text=True)
    assert client.get("/dashboard").status_code == 302


def test_login_rate_guard_blocks_sixth_failed_attempt(client):
    for _ in range(5):
        page = client.get("/login", environ_overrides={"REMOTE_ADDR": "198.51.100.25"})
        response = client.post(
            "/login",
            data={
                "csrf_token": csrf_token(page),
                "username": "missing-user",
                "password": "invalid-password"
            },
            environ_overrides={"REMOTE_ADDR": "198.51.100.25"}
        )
        assert response.status_code == 200

    page = client.get("/login", environ_overrides={"REMOTE_ADDR": "198.51.100.25"})
    blocked = client.post(
        "/login",
        data={
            "csrf_token": csrf_token(page),
            "username": "missing-user",
            "password": "invalid-password"
        },
        environ_overrides={"REMOTE_ADDR": "198.51.100.25"}
    )

    assert blocked.status_code == 429


def test_authenticated_session_cookie_has_security_flags(client, web_users):
    page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token(page),
            "username": web_users["librarian"].username,
            "password": web_users["password"]
        },
        environ_overrides={"REMOTE_ADDR": "198.51.100.26"}
    )

    assert response.status_code == 302
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(cookie for cookie in cookies if cookie.startswith("session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie


def test_deactivated_account_is_removed_from_existing_session(client, web_users):
    login(client, web_users["reader"].username, web_users["password"])

    UserService().deactivate_user(web_users["admin"].id, web_users["reader"].id)

    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_production_configuration_requires_secret_key(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({
            "TESTING": False,
            "SECRET_KEY": None,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
        })


def test_html_error_page_is_rendered_outside_testing_mode():
    application = create_app({
        "TESTING": False,
        "SECRET_KEY": "error-page-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
    })
    try:
        response = application.test_client().get(
            "/route-that-does-not-exist",
            headers={"Accept": "text/html"}
        )

        assert response.status_code == 404
        assert "Nie znaleziono" in response.get_data(as_text=True)
    finally:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()
