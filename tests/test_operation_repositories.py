from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db

from app.models import (
    User,
    Reader,
    Book,
    Copy,
    Loan,
    Reservation,
    Fine,
    Payment,
    AuditLog,
    Setting
)

from app.repositories import (
    LoanRepository,
    ReservationRepository,
    FineRepository,
    PaymentRepository,
    AuditRepository,
    SettingRepository
)


@pytest.fixture
def operation_data(app):

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    user = User(
        username="operation_user",
        email="operation@example.com",
        password_hash="test_hash",
        role="READER",
        is_active=True
    )

    book = Book(
        title="Testowa ksiazka",
        is_archived=False
    )

    db.session.add_all([user, book])
    db.session.flush()

    reader = Reader(
        user_id=user.id,
        card_number="LIB-TEST-001",
        first_name="Jan",
        last_name="Testowy"
    )

    copy = Copy(
        book_id=book.id,
        inventory_number="INV-TEST-001",
        status="LOANED"
    )

    db.session.add_all([reader, copy])
    db.session.flush()

    loan = Loan(
        copy_id=copy.id,
        reader_id=reader.id,
        borrowed_at=now - timedelta(days=40),
        due_date=now - timedelta(days=10),
        status="ACTIVE"
    )

    reservation = Reservation(
        book_id=book.id,
        reader_id=reader.id,
        reserved_at=now,
        status="WAITING"
    )

    db.session.add_all([loan, reservation])
    db.session.flush()

    fine = Fine(
        loan_id=loan.id,
        amount=Decimal("10.00"),
        paid_amount=Decimal("4.00"),
        status="PARTIALLY_PAID"
    )

    db.session.add(fine)
    db.session.flush()

    payment = Payment(
        fine_id=fine.id,
        amount=Decimal("4.00"),
        method="CASH"
    )

    audit = AuditLog(
        user_id=user.id,
        action="TEST_ACTION",
        description="Test dziennika operacji"
    )

    setting = Setting(
        key="MAX_ACTIVE_LOANS",
        value="5",
        description="Limit wypozyczen"
    )

    db.session.add_all([payment, audit, setting])
    db.session.commit()

    return {
        "user": user,
        "reader": reader,
        "book": book,
        "copy": copy,
        "loan": loan,
        "reservation": reservation,
        "fine": fine,
        "payment": payment,
        "audit": audit,
        "setting": setting
    }


# ==========================================
# LOAN REPOSITORY
# ==========================================

def test_loans_by_reader(operation_data):
    repo = LoanRepository()

    assert len(
        repo.get_by_reader(operation_data["reader"].id)
    ) == 1


def test_loans_by_copy(operation_data):
    repo = LoanRepository()

    assert len(
        repo.get_by_copy(operation_data["copy"].id)
    ) == 1


def test_active_loans(operation_data):
    repo = LoanRepository()

    assert len(repo.get_active_loans()) == 1


def test_active_loans_by_reader(operation_data):
    repo = LoanRepository()

    assert len(
        repo.get_active_by_reader(
            operation_data["reader"].id
        )
    ) == 1


def test_active_loan_by_copy(operation_data):
    repo = LoanRepository()

    assert repo.get_active_by_copy(
        operation_data["copy"].id
    ).id == operation_data["loan"].id


def test_count_active_loans(operation_data):
    repo = LoanRepository()

    assert repo.count_active_by_reader(
        operation_data["reader"].id
    ) == 1


def test_overdue_loans(operation_data):
    repo = LoanRepository()

    assert len(repo.get_overdue_loans()) == 1


# ==========================================
# RESERVATION REPOSITORY
# ==========================================

def test_reservations_by_reader(operation_data):
    repo = ReservationRepository()

    assert len(
        repo.get_by_reader(operation_data["reader"].id)
    ) == 1


def test_reservations_by_book(operation_data):
    repo = ReservationRepository()

    assert len(
        repo.get_by_book(operation_data["book"].id)
    ) == 1


def test_waiting_reservations(operation_data):
    repo = ReservationRepository()

    assert len(
        repo.get_waiting_by_book(
            operation_data["book"].id
        )
    ) == 1


def test_active_reservations(operation_data):
    repo = ReservationRepository()

    assert len(
        repo.get_active_by_reader(
            operation_data["reader"].id
        )
    ) == 1


def test_count_active_reservations(operation_data):
    repo = ReservationRepository()

    assert repo.count_active_by_reader(
        operation_data["reader"].id
    ) == 1


def test_expired_reservations(operation_data):
    repo = ReservationRepository()

    reservation = operation_data["reservation"]

    reservation.status = "READY"
    reservation.expires_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(days=1)
    )

    db.session.commit()

    assert len(repo.get_expired_reservations()) == 1


# ==========================================
# FINE REPOSITORY
# ==========================================

def test_fine_by_loan(operation_data):
    repo = FineRepository()

    assert repo.get_by_loan(
        operation_data["loan"].id
    ).id == operation_data["fine"].id


def test_fines_by_reader(operation_data):
    repo = FineRepository()

    assert len(
        repo.get_by_reader(operation_data["reader"].id)
    ) == 1


def test_unpaid_fines(operation_data):
    repo = FineRepository()

    assert len(repo.get_unpaid_fines()) == 1


def test_total_unpaid_fines(operation_data):
    repo = FineRepository()

    assert repo.get_total_unpaid_by_reader(
        operation_data["reader"].id
    ) == Decimal("6.00")


# ==========================================
# PAYMENT REPOSITORY
# ==========================================

def test_payments_by_fine(operation_data):
    repo = PaymentRepository()

    assert len(
        repo.get_by_fine(operation_data["fine"].id)
    ) == 1


def test_payments_by_method(operation_data):
    repo = PaymentRepository()

    assert len(repo.get_by_method("CASH")) == 1


def test_total_payments_by_fine(operation_data):
    repo = PaymentRepository()

    assert repo.get_total_by_fine(
        operation_data["fine"].id
    ) == Decimal("4.00")


def test_total_payments(operation_data):
    repo = PaymentRepository()

    assert repo.get_total_payments() == Decimal("4.00")


# ==========================================
# AUDIT REPOSITORY
# ==========================================

def test_audit_by_user(operation_data):
    repo = AuditRepository()

    assert len(
        repo.get_by_user(operation_data["user"].id)
    ) == 1


def test_audit_by_action(operation_data):
    repo = AuditRepository()

    assert len(repo.get_by_action("TEST_ACTION")) == 1


def test_recent_audit_logs(operation_data):
    repo = AuditRepository()

    assert len(repo.get_recent(limit=1)) == 1


# ==========================================
# SETTING REPOSITORY
# ==========================================

def test_setting_by_key(operation_data):
    repo = SettingRepository()

    assert repo.get_by_key(
        "MAX_ACTIVE_LOANS"
    ).value == "5"


def test_setting_value(operation_data):
    repo = SettingRepository()

    assert repo.get_value("MAX_ACTIVE_LOANS") == "5"


def test_default_setting_value(operation_data):
    repo = SettingRepository()

    assert repo.get_value(
        "NON_EXISTENT_SETTING",
        "default"
    ) == "default"


def test_create_setting(operation_data):
    repo = SettingRepository()

    repo.set_value(
        "LOAN_PERIOD_DAYS",
        30,
        "Czas wypozyczenia"
    )

    db.session.commit()

    assert repo.get_value("LOAN_PERIOD_DAYS") == "30"


def test_update_setting(operation_data):
    repo = SettingRepository()

    repo.set_value("MAX_ACTIVE_LOANS", 10)

    db.session.commit()

    assert repo.get_value("MAX_ACTIVE_LOANS") == "10"