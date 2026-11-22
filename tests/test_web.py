import re

import pytest

from app.extensions import db
from app.models import Reader, User
from app.services import AuthService, AuthorService
from app.services import (
    BookService,
    CategoryService,
    CopyService,
    ReaderService,
    UserService,
)


def csrf_token(response):
    match = re.search(
        r'name="csrf_token" value="([^"]+)"',
        response.get_data(as_text=True)
    )
    assert match, "CSRF token should be included in every writable form"
    return match.group(1)


@pytest.fixture
def web_users(app):
    auth = AuthService()
    password = "WebInterfacePassword123!"
    admin = User(
        username="web_admin",
        email="web-admin@example.test",
        password_hash=auth.hash_password(password),
        role="ADMIN",
        is_active=True
    )
    librarian = User(
        username="web_librarian",
        email="web-librarian@example.test",
        password_hash=auth.hash_password(password),
        role="LIBRARIAN",
        is_active=True
    )
    reader_user = User(
        username="web_reader",
        email="web-reader@example.test",
        password_hash=auth.hash_password(password),
        role="READER",
        is_active=True
    )
    db.session.add_all([admin, librarian, reader_user])
    db.session.flush()
    db.session.add(Reader(
        user_id=reader_user.id,
        card_number="WEB-READER-001",
        first_name="Jan",
        last_name="Kowalski"
    ))
    db.session.commit()

    return {
        "password": password,
        "admin": admin,
        "librarian": librarian,
        "reader": reader_user
    }


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


def test_public_health_login_and_security_headers(client, web_users):
    health = client.get("/health")
    login_page = client.get("/login")

    assert health.get_json() == {"status": "healthy"}
    assert login_page.status_code == 200
    assert "Content-Security-Policy" in login_page.headers
    assert login_page.headers["X-Frame-Options"] == "DENY"

    response = login(
        client,
        web_users["librarian"].username,
        web_users["password"]
    )

    assert response.status_code == 200
    assert "Dzień dobry" in response.get_data(as_text=True)


def test_post_routes_require_csrf_token(client, web_users):
    login(client, web_users["librarian"].username, web_users["password"])

    response = client.post(
        "/authors",
        data={"first_name": "Jan", "last_name": "BezTokena"}
    )

    assert response.status_code == 400


def test_librarian_creates_author_through_service(client, web_users):
    login(client, web_users["librarian"].username, web_users["password"])
    page = client.get("/authors")

    response = client.post(
        "/authors",
        data={
            "csrf_token": csrf_token(page),
            "first_name": "Jan",
            "last_name": "HTTP"
        },
        follow_redirects=True
    )

    assert response.status_code == 200
    authors = AuthorService().search(
        web_users["librarian"].id,
        "HTTP"
    )
    assert [(author.first_name, author.last_name) for author in authors] == [
        ("Jan", "HTTP")
    ]


def test_reader_cannot_use_staff_or_administration_routes(client, web_users):
    login(client, web_users["reader"].username, web_users["password"])

    assert client.get("/users", follow_redirects=True).status_code == 200
    assert client.get("/reports", follow_redirects=True).status_code == 200

    payment_page = client.get("/payments")
    response = client.post(
        "/payments",
        data={
            "csrf_token": csrf_token(payment_page),
            "fine_id": "1",
            "amount": "1.00",
            "method": "CASH"
        },
        follow_redirects=True
    )

    content = response.get_data(as_text=True)
    assert "Czytelnik nie może rejestrować płatności" in content


def test_staff_dashboard_and_csv_report_are_service_backed(client, web_users):
    login(client, web_users["librarian"].username, web_users["password"])

    report_page = client.get("/reports")
    export = client.get("/reports/library_overview.csv")

    assert report_page.status_code == 200
    assert "Raporty biblioteki" in report_page.get_data(as_text=True)
    assert export.status_code == 200
    assert export.mimetype == "text/csv"
    assert b"available_copies" in export.data


def test_librarian_catalogue_support_crud_routes(client, web_users):
    librarian_id = web_users["librarian"].id
    login(client, web_users["librarian"].username, web_users["password"])

    authors = AuthorService()
    author = authors.create_author(librarian_id, "Anna", "Przed")
    edit_page = client.get(f"/authors/{author.id}/edit")
    response = client.post(
        f"/authors/{author.id}/edit",
        data={
            "csrf_token": csrf_token(edit_page),
            "first_name": "Anna",
            "last_name": "Po"
        },
        follow_redirects=True
    )
    assert response.status_code == 200
    assert authors.get_by_id(librarian_id, author.id).last_name == "Po"

    delete_page = client.get("/authors")
    response = client.post(
        f"/authors/{author.id}/delete",
        data={"csrf_token": csrf_token(delete_page)},
        follow_redirects=True
    )
    assert response.status_code == 200
    assert authors.search(librarian_id, "Po") == []

    category = CategoryService().create_category(librarian_id, "Do edycji")
    book = BookService().create_book(
        librarian_id, "Książka do egzemplarza", category_id=category.id
    )
    copy = CopyService().create_copy(librarian_id, book.id, "WEB-CRUD-001")
    copy_page = client.get(f"/copies/{copy.id}/edit")
    response = client.post(
        f"/copies/{copy.id}/edit",
        data={
            "csrf_token": csrf_token(copy_page),
            "inventory_number": "WEB-CRUD-002"
        },
        follow_redirects=True
    )
    assert response.status_code == 200
    assert CopyService().get_by_id(librarian_id, copy.id).inventory_number == (
        "WEB-CRUD-002"
    )


def test_administrator_can_change_staff_role_through_route(client, web_users):
    login(client, web_users["admin"].username, web_users["password"])
    target = web_users["librarian"]
    edit_page = client.get(f"/users/{target.id}/edit")
    response = client.post(
        f"/users/{target.id}/edit",
        data={"csrf_token": csrf_token(edit_page), "role": "ADMIN"},
        follow_redirects=True
    )

    assert response.status_code == 200
    assert UserService().get_by_id(web_users["admin"].id, target.id).role == "ADMIN"


def test_staff_book_reader_and_account_crud_work_through_http(client, web_users):
    librarian_id = web_users["librarian"].id
    login(client, web_users["librarian"].username, web_users["password"])

    category = CategoryService().create_category(librarian_id, "CRUD web")
    book = BookService().create_book(
        librarian_id,
        "Tytuł przed edycją",
        "9780306406157",
        category_id=category.id,
    )

    edit_page = client.get(f"/books/{book.id}/edit")
    response = client.post(
        f"/books/{book.id}/edit",
        data={
            "csrf_token": csrf_token(edit_page),
            "title": "Tytuł po edycji",
            "isbn": "9780306406157",
            "publisher": "Wydawnictwo testowe",
            "publication_year": "2024",
            "category_id": str(category.id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Tytuł po edycji" in response.get_data(as_text=True)

    catalog_page = client.get("/catalog?q=po+edycji")
    assert "Tytuł po edycji" in catalog_page.get_data(as_text=True)
    response = client.post(
        f"/books/{book.id}/archive",
        data={"csrf_token": csrf_token(catalog_page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert BookService().get_by_id(librarian_id, book.id, include_archived=True).is_archived

    archived_page = client.get("/catalog?archived=1")
    response = client.post(
        f"/books/{book.id}/restore",
        data={"csrf_token": csrf_token(archived_page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert not BookService().get_by_id(librarian_id, book.id, include_archived=True).is_archived

    reader = ReaderService().get_all(librarian_id)[0]
    reader_page = client.get(f"/readers/{reader.id}/edit")
    response = client.post(
        f"/readers/{reader.id}/edit",
        data={
            "csrf_token": csrf_token(reader_page),
            "first_name": "Janusz",
            "last_name": "Kowalski",
            "phone": "+48 500 111 222",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert ReaderService().get_by_id(librarian_id, reader.id).first_name == "Janusz"



def test_administrator_can_toggle_staff_account_through_route(client, web_users):
    login(client, web_users["admin"].username, web_users["password"])
    target = web_users["librarian"]
    users_page = client.get("/users?role=LIBRARIAN")
    assert target.username in users_page.get_data(as_text=True)

    response = client.post(
        f"/users/{target.id}/toggle",
        data={"csrf_token": csrf_token(users_page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert not UserService().get_by_id(web_users["admin"].id, target.id).is_active

    users_page = client.get("/users?role=LIBRARIAN")
    client.post(
        f"/users/{target.id}/toggle",
        data={"csrf_token": csrf_token(users_page)},
        follow_redirects=True,
    )
    assert UserService().get_by_id(web_users["admin"].id, target.id).is_active
