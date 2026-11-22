from datetime import datetime, UTC, timedelta

import pytest

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import (
    User,
    Reader,
    Book,
    Copy,
    Loan,
    Reservation,
    Fine,
    Payment
)


@pytest.fixture
def sample_data(app):
    user = User(
        username="reader01",
        email="reader01@example.com",
        password_hash=generate_password_hash("Test123"),
        role="READER"
    )

    reader = Reader(
        user=user,
        card_number="CARD-001",
        first_name="Jan",
        last_name="Kowalski"
    )

    book = Book(
        title="Test Book",
        publication_year=2020
    )

    copy = Copy(
        book=book,
        inventory_number="INV-001",
        status="AVAILABLE"
    )

    db.session.add_all([user, reader, book, copy])
    db.session.commit()

    return {
        "user": user,
        "reader": reader,
        "book": book,
        "copy": copy
    }


@pytest.fixture
def sample_loan(sample_data):
    loan = Loan(
        copy_id=sample_data["copy"].id,
        reader_id=sample_data["reader"].id,
        due_date=(
            datetime.now(UTC).replace(tzinfo=None)
            + timedelta(days=30)
        ),
        status="ACTIVE"
    )

    db.session.add(loan)
    db.session.commit()

    return loan


@pytest.fixture
def sample_fine(sample_loan):
    fine = Fine(
        loan_id=sample_loan.id,
        amount=20,
        paid_amount=0,
        status="UNPAID"
    )

    db.session.add(fine)
    db.session.commit()

    return fine


def assert_constraint_error(constraint_name):
    with pytest.raises(IntegrityError) as error:
        db.session.commit()

    db.session.rollback()

    assert constraint_name in str(error.value.orig)


def test_duplicate_username(sample_data):
    user = User(
        username="reader01",
        email="another@example.com",
        password_hash=generate_password_hash("Test123"),
        role="READER"
    )

    db.session.add(user)

    assert_constraint_error("users.username")


def test_duplicate_email(sample_data):
    user = User(
        username="another_reader",
        email="reader01@example.com",
        password_hash=generate_password_hash("Test123"),
        role="READER"
    )

    db.session.add(user)

    assert_constraint_error("users.email")


def test_empty_reader_first_name(sample_data):
    sample_data["reader"].first_name = ""

    assert_constraint_error("check_reader_first_name")


def test_empty_reader_last_name(sample_data):
    sample_data["reader"].last_name = ""

    assert_constraint_error("check_reader_last_name")


def test_invalid_loan_status(sample_loan):
    sample_loan.status = "UNKNOWN"

    assert_constraint_error("check_loan_status")


def test_invalid_reservation_status(sample_data):
    reservation = Reservation(
        book_id=sample_data["book"].id,
        reader_id=sample_data["reader"].id,
        status="UNKNOWN"
    )

    db.session.add(reservation)

    assert_constraint_error("check_reservation_status")


def test_negative_fine(sample_fine):
    sample_fine.amount = -10

    assert_constraint_error("check_fine_amount")


def test_fine_overpayment(sample_fine):
    sample_fine.paid_amount = 100

    assert_constraint_error("check_fine_paid_amount")


def test_invalid_fine_status(sample_fine):
    sample_fine.status = "UNKNOWN"

    assert_constraint_error("check_fine_status")


def test_zero_payment(sample_fine):
    payment = Payment(
        fine_id=sample_fine.id,
        amount=0,
        method="CASH"
    )

    db.session.add(payment)

    assert_constraint_error("check_payment_amount")


def test_negative_payment(sample_fine):
    payment = Payment(
        fine_id=sample_fine.id,
        amount=-10,
        method="CASH"
    )

    db.session.add(payment)

    assert_constraint_error("check_payment_amount")


def test_invalid_payment_method(sample_fine):
    payment = Payment(
        fine_id=sample_fine.id,
        amount=10,
        method="UNKNOWN"
    )

    db.session.add(payment)

    assert_constraint_error("check_payment_method")