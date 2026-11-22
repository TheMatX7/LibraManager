"""Explicit, non-destructive demonstration-data bootstrap for presentations."""

import secrets
from datetime import timedelta

from app.exceptions import BusinessRuleError
from app.extensions import db
from app.models import User
from app.services import (
    AuthService,
    AuthorService,
    BookService,
    CategoryService,
    CopyService,
    LoanService,
    PaymentService,
    ReaderService,
    ReservationService,
    SettingService,
    UserService
)


def _password():
    return f"Demo!{secrets.token_urlsafe(16)}"


def seed_demo_data():
    """Create a complete presentation dataset only in an empty database.

    Passwords are generated on every run and returned to the caller; no demo
    credential is stored in source control.  The function refuses to operate
    once any user exists, avoiding accidental modification of a real library.
    """

    if UserService().repository.count() != 0:
        raise BusinessRuleError(
            "Demo data can only be created in an empty database."
        )

    passwords = {
        "admin": _password(),
        "librarian": _password(),
        "reader": _password()
    }
    auth = AuthService()
    admin = User(
        username="demo_admin",
        email="admin.demo@libramanager.local",
        password_hash=auth.hash_password(passwords["admin"]),
        role="ADMIN",
        is_active=True
    )
    db.session.add(admin)
    db.session.commit()

    settings = SettingService()
    settings.initialize_defaults()
    users = UserService()
    readers = ReaderService()
    categories = CategoryService()
    authors = AuthorService()
    books = BookService()
    copies = CopyService()
    loans = LoanService()
    reservations = ReservationService()
    payments = PaymentService()

    librarian = users.create_user(
        admin.id, "demo_librarian", "librarian.demo@libramanager.local",
        passwords["librarian"], role="LIBRARIAN"
    )
    reader_one = readers.register_reader(
        librarian.id, "demo_reader", "reader.demo@libramanager.local",
        passwords["reader"], "Alicja", "Nowak", "+48 501 234 567"
    )
    reader_two = readers.register_reader(
        librarian.id, "demo_reader_two", "reader.two.demo@libramanager.local",
        _password(), "Jan", "Kowalski", "+48 502 765 432"
    )
    category = categories.create_category(
        librarian.id, "Literatura współczesna", "Pozycje prezentacyjne"
    )
    author = authors.create_author(librarian.id, "Olga", "Tokarczuk")
    book_one = books.create_book(
        librarian.id, "Księgi Jakubowe", "9788308064191",
        "Przykładowa pozycja katalogowa.", "Wydawnictwo Literackie", 2014,
        category.id, [author.id]
    )
    book_two = books.create_book(
        librarian.id, "Prowadź swój pług przez kości umarłych", "9788308057940",
        category_id=category.id, author_ids=[author.id]
    )
    copy_one = copies.create_copy(librarian.id, book_one.id, "DEMO-001")
    copy_two = copies.create_copy(librarian.id, book_one.id, "DEMO-002")
    copy_three = copies.create_copy(librarian.id, book_two.id, "DEMO-003")

    # Active loan plus waiting reservation demonstrate ordinary circulation.
    loans.borrow_book(librarian.id, reader_one.id, copy_one.id)
    reservations.create_reservation(librarian.id, reader_two.id, book_one.id)

    # The next returned loan is deliberately backdated only in this isolated,
    # new demo database so that the real return service creates a real fine.
    historic = loans.borrow_book(librarian.id, reader_one.id, copy_three.id)
    historic.due_date = loans.now() - timedelta(days=3)
    db.session.commit()
    returned = loans.return_book(librarian.id, historic.id)
    fine = returned.fine
    if fine is not None:
        payments.register_payment(librarian.id, fine.id, "1.00", "CARD")

    # The FIFO queue correctly reserves the second available copy for reader two.
    assert copy_two.status == "RESERVED"

    return {
        "administrator": {"username": admin.username, "password": passwords["admin"]},
        "librarian": {"username": librarian.username, "password": passwords["librarian"]},
        "reader": {"username": reader_one.user.username, "password": passwords["reader"]}
    }
