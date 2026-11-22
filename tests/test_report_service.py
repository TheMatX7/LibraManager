from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.exceptions import AuthorizationError, ValidationError
from app.extensions import db
from app.models import (
    Book,
    Category,
    Copy,
    Fine,
    Loan,
    Reader,
    Reservation,
    User
)
from app.services import PaymentService, ReportService


@pytest.fixture
def report_data(app):
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)

    admin = User(
        username="report_admin",
        email="report-admin@example.test",
        password_hash="not-used",
        role="ADMIN",
        is_active=True
    )
    librarian = User(
        username="report_librarian",
        email="report-librarian@example.test",
        password_hash="not-used",
        role="LIBRARIAN",
        is_active=True
    )
    reader_user = User(
        username="report_reader",
        email="report-reader@example.test",
        password_hash="not-used",
        role="READER",
        is_active=True
    )
    db.session.add_all([admin, librarian, reader_user])
    db.session.flush()

    reader = Reader(
        user_id=reader_user.id,
        card_number="REPORT-READER-001",
        first_name="Jan",
        last_name="Kowalski"
    )
    category = Category(name="=Formula category")
    db.session.add_all([reader, category])
    db.session.flush()

    active_book = Book(
        title="=Formula-safe book",
        category_id=category.id,
        is_archived=False
    )
    archived_book = Book(
        title="Archived report book",
        category_id=category.id,
        is_archived=True
    )
    db.session.add_all([active_book, archived_book])
    db.session.flush()

    available_copy = Copy(
        book_id=active_book.id,
        inventory_number="REPORT-COPY-AVAILABLE",
        status="AVAILABLE"
    )
    loaned_copy = Copy(
        book_id=archived_book.id,
        inventory_number="REPORT-COPY-LOANED",
        status="LOANED"
    )
    db.session.add_all([available_copy, loaned_copy])
    db.session.flush()

    returned_loan = Loan(
        copy_id=available_copy.id,
        reader_id=reader.id,
        borrowed_at=now - timedelta(days=12),
        due_date=now - timedelta(days=10),
        returned_at=now - timedelta(days=9),
        status="RETURNED"
    )
    active_loan = Loan(
        copy_id=loaned_copy.id,
        reader_id=reader.id,
        borrowed_at=now - timedelta(days=5),
        due_date=now - timedelta(days=1),
        status="ACTIVE"
    )
    db.session.add_all([returned_loan, active_loan])
    db.session.flush()

    fine = Fine(
        loan_id=returned_loan.id,
        amount=Decimal("10.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )
    reservation_waiting = Reservation(
        book_id=active_book.id,
        reader_id=reader.id,
        status="WAITING"
    )
    reservation_ready = Reservation(
        book_id=archived_book.id,
        reader_id=reader.id,
        status="READY"
    )
    db.session.add_all([fine, reservation_waiting, reservation_ready])
    db.session.commit()

    payment_service = PaymentService()
    payment_service.register_payment(
        librarian.id,
        fine.id,
        "4.00",
        "CASH"
    )
    payment_service.pay_full_fine(
        librarian.id,
        fine.id,
        "CARD"
    )

    return {
        "admin_id": admin.id,
        "librarian_id": librarian.id,
        "reader_user_id": reader_user.id,
        "category_id": category.id,
        "active_book_id": active_book.id,
        "archived_book_id": archived_book.id,
        "now": now
    }


def test_library_catalogue_and_loan_reports(report_data):
    service = ReportService()
    librarian_id = report_data["librarian_id"]
    now = report_data["now"]

    overview = service.get_library_overview(librarian_id, now=now)
    loans = service.get_loan_statistics(
        librarian_id,
        start_at=now - timedelta(days=20),
        end_at=now,
        now=now
    )
    reservations = service.get_reservation_statistics(librarian_id)
    top_books = service.get_most_borrowed_books(librarian_id)
    categories = service.get_category_statistics(librarian_id)

    assert overview == {
        "users": 3,
        "readers": 1,
        "books": 2,
        "active_books": 1,
        "archived_books": 1,
        "copies": 2,
        "available_copies": 1,
        "active_loans": 1,
        "overdue_loans": 1,
        "active_reservations": 2,
        "copy_statuses": {
            "AVAILABLE": 1,
            "LOANED": 1,
            "RESERVED": 0,
            "DAMAGED": 0,
            "LOST": 0
        }
    }
    assert loans == {
        "total_loans": 2,
        "active_loans": 1,
        "overdue_loans": 1,
        "loan_history": 1,
        "borrowed_in_period": 2,
        "returned_in_period": 1
    }
    assert reservations == {
        "total_reservations": 2,
        "active_reservations": 2,
        "statuses": {
            "WAITING": 1,
            "READY": 1,
            "FULFILLED": 0,
            "CANCELLED": 0,
            "EXPIRED": 0
        }
    }
    assert top_books == [
        {
            "book_id": report_data["active_book_id"],
            "title": "=Formula-safe book",
            "loan_count": 1
        },
        {
            "book_id": report_data["archived_book_id"],
            "title": "Archived report book",
            "loan_count": 1
        }
    ]
    assert categories == [
        {
            "category_id": report_data["category_id"],
            "name": "=Formula category",
            "book_count": 2,
            "copy_count": 2,
            "loan_count": 2
        }
    ]


def test_financial_reports_dashboard_and_csv_export(report_data):
    service = ReportService()
    librarian_id = report_data["librarian_id"]
    now = report_data["now"]

    financial = service.get_financial_statistics(librarian_id)
    period_report = service.get_financial_report(
        librarian_id,
        start_at=now - timedelta(minutes=1),
        end_at=now + timedelta(minutes=1)
    )
    dashboard = service.get_admin_dashboard(
        report_data["admin_id"],
        now=now
    )
    csv_export = service.export_csv(
        librarian_id,
        "most_borrowed_books"
    )

    assert financial == {
        "fines": {
            "total_fines": 1,
            "unpaid_fines": 0,
            "partially_paid_fines": 0,
            "paid_fines": 1,
            "total_amount": Decimal("10.00"),
            "total_paid": Decimal("10.00"),
            "total_unpaid": Decimal("0.00")
        },
        "payments": {
            "total_payments": 2,
            "cash_payments": 1,
            "card_payments": 1,
            "total_amount": Decimal("10.00"),
            "cash_total": Decimal("4.00"),
            "card_total": Decimal("6.00")
        },
        "outstanding_amount": Decimal("0.00"),
        "registered_payment_amount": Decimal("10.00")
    }
    assert period_report == {
        "start_at": now - timedelta(minutes=1),
        "end_at": now + timedelta(minutes=1),
        "payments": 2,
        "total_amount": Decimal("10.00"),
        "cash_total": Decimal("4.00"),
        "card_total": Decimal("6.00")
    }
    assert dashboard["library"]["overdue_loans"] == 1
    assert dashboard["financial"] == financial
    assert len(dashboard["recent_audit"]) == 3
    assert csv_export.splitlines()[0] == "book_id,loan_count,title"
    assert "'=Formula-safe book" in csv_export


def test_reports_enforce_rbac_and_validate_public_arguments(report_data):
    service = ReportService()
    reader_id = report_data["reader_user_id"]
    librarian_id = report_data["librarian_id"]

    with pytest.raises(AuthorizationError):
        service.get_library_overview(reader_id)

    with pytest.raises(AuthorizationError):
        service.export_csv(reader_id, "library_overview")

    with pytest.raises(AuthorizationError):
        service.get_admin_dashboard(librarian_id)

    with pytest.raises(ValidationError):
        service.get_most_borrowed_books(librarian_id, limit=True)

    with pytest.raises(ValidationError):
        service.get_most_borrowed_books(librarian_id, limit=101)

    with pytest.raises(ValidationError):
        service.get_financial_report(
            librarian_id,
            start_at=report_data["now"],
            end_at=report_data["now"] - timedelta(days=1)
        )

    with pytest.raises(ValidationError):
        service.export_csv(librarian_id, "not-a-report")


def test_report_edge_inputs_and_empty_export(app, report_data):
    service = ReportService()
    librarian_id = report_data["librarian_id"]
    utc_now = datetime.now(UTC)

    assert service._as_money(None) == Decimal("0.00")
    assert service._period_conditions(PaymentService.ZERO, None, None) == []

    with pytest.raises(ValidationError):
        service.validate_period(utc_now, None)

    # Both optional bounds are intentionally supported and the methods obtain
    # their own naive UTC reference time when no explicit `now` is supplied.
    assert service.get_library_overview(librarian_id)["users"] == 3
    assert service.get_loan_statistics(librarian_id)["total_loans"] == 2
    assert service.get_financial_report(librarian_id)["total_amount"] == (
        Decimal("10.00")
    )

    with pytest.raises(ValidationError):
        service.export_csv(librarian_id, "   ")
