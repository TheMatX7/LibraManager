import pytest

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User, Book, Copy


def test_database_tables(app):
    inspector = inspect(db.engine)

    tables = inspector.get_table_names()

    assert len(tables) == 13


def test_foreign_keys_enabled(app):
    result = db.session.execute(
        text("PRAGMA foreign_keys")
    ).scalar()

    assert result == 1


def test_valid_user(app):
    user = User(
        username="testadmin",
        email="admin@example.com",
        password_hash=generate_password_hash("Test123"),
        role="ADMIN"
    )

    db.session.add(user)
    db.session.commit()

    assert user.id is not None


def test_invalid_user_role(app):
    user = User(
        username="invaliduser",
        email="invalid@example.com",
        password_hash=generate_password_hash("Test123"),
        role="SUPERUSER"
    )

    db.session.add(user)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_empty_book_title(app):
    book = Book(title="")

    db.session.add(book)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_invalid_publication_year(app):
    book = Book(
        title="Test Book",
        publication_year=9999
    )

    db.session.add(book)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_invalid_foreign_key(app):
    copy = Copy(
        book_id=999999,
        inventory_number="TEST-001",
        status="AVAILABLE"
    )

    db.session.add(copy)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_invalid_copy_status(app):
    book = Book(title="Test Book")

    db.session.add(book)
    db.session.commit()

    copy = Copy(
        book_id=book.id,
        inventory_number="TEST-002",
        status="UNKNOWN"
    )

    db.session.add(copy)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"


def test_index_endpoint(client):
    response = client.get("/")

    # The diagnostic JSON endpoint was intentionally replaced by the web
    # application entry point.  Health remains the machine-readable contract.
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
