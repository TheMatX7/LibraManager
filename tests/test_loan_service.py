import pytest

from datetime import timedelta
from decimal import Decimal

from app.extensions import db

from app.models import (
    User,
    Reader,
    Book,
    Copy,
    Loan,
    Fine,
    Reservation,
    AuditLog
)

from app.services import LoanService

from app.exceptions import (
    ValidationError,
    BusinessRuleError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError,
    InactiveAccountError,
    CopyUnavailableError,
    LoanLimitExceededError,
    LoanAlreadyReturnedError
)


# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
def service(app):
    return LoanService()


@pytest.fixture
def data(service):

    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash="test_hash",
        role="ADMIN",
        is_active=True
    )

    librarian = User(
        username="librarian",
        email="librarian@example.com",
        password_hash="test_hash",
        role="LIBRARIAN",
        is_active=True
    )

    user = User(
        username="reader",
        email="reader@example.com",
        password_hash="test_hash",
        role="READER",
        is_active=True
    )

    other_user = User(
        username="reader2",
        email="reader2@example.com",
        password_hash="test_hash",
        role="READER",
        is_active=True
    )

    db.session.add_all([
        admin,
        librarian,
        user,
        other_user
    ])

    db.session.flush()

    reader = Reader(
        user_id=user.id,
        card_number="LIB-000001",
        first_name="Jan",
        last_name="Kowalski"
    )

    other_reader = Reader(
        user_id=other_user.id,
        card_number="LIB-000002",
        first_name="Anna",
        last_name="Nowak"
    )

    book = Book(
        title="Test book",
        is_archived=False
    )

    db.session.add_all([
        reader,
        other_reader,
        book
    ])

    db.session.flush()

    copies = [
        Copy(
            book_id=book.id,
            inventory_number=f"INV-{number:03d}",
            status="AVAILABLE"
        )
        for number in range(1, 8)
    ]

    db.session.add_all(copies)

    db.session.commit()

    return {
        "admin": admin,
        "librarian": librarian,
        "user": user,
        "other_user": other_user,
        "reader": reader,
        "other_reader": other_reader,
        "book": book,
        "copies": copies,
        "copy": copies[0]
    }


@pytest.fixture
def loan(service, data):

    return service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        data["copy"].id
    )


def make_overdue(service, loan, days=3):

    now = service.now()

    loan.borrowed_at = now - timedelta(
        days=40
    )

    loan.due_date = now - timedelta(
        days=days
    ) + timedelta(minutes=1)

    db.session.commit()

    return loan


# ==========================================
# BORROW TESTS
# ==========================================

def test_borrow_book(service, data, loan):

    assert loan.id is not None
    assert loan.status == "ACTIVE"
    assert loan.reader_id == data["reader"].id
    assert loan.copy_id == data["copy"].id


def test_borrow_changes_copy_status(data, loan):

    assert data["copy"].status == "LOANED"


def test_default_loan_period(loan):

    assert (
        loan.due_date - loan.borrowed_at
    ).days == 30


def test_borrow_has_no_return_date(loan):

    assert loan.returned_at is None


def test_librarian_can_borrow(service, data):

    loan = service.borrow_book(
        data["librarian"].id,
        data["reader"].id,
        data["copy"].id
    )

    assert loan.status == "ACTIVE"


def test_reader_cannot_borrow(service, data):

    with pytest.raises(AuthorizationError):

        service.borrow_book(
            data["user"].id,
            data["reader"].id,
            data["copy"].id
        )


def test_unauthenticated_borrow(service, data):

    with pytest.raises(AuthenticationError):

        service.borrow_book(
            None,
            data["reader"].id,
            data["copy"].id
        )


def test_inactive_staff_cannot_borrow(
    service, data
):

    data["librarian"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.borrow_book(
            data["librarian"].id,
            data["reader"].id,
            data["copy"].id
        )


def test_inactive_reader_cannot_borrow(
    service, data
):

    data["user"].is_active = False
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copy"].id
        )


def test_nonexistent_reader(service, data):

    with pytest.raises(NotFoundError):

        service.borrow_book(
            data["admin"].id,
            99999,
            data["copy"].id
        )


def test_nonexistent_copy(service, data):

    with pytest.raises(NotFoundError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            99999
        )


@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_invalid_reader_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.borrow_book(
            data["admin"].id,
            invalid_id,
            data["copy"].id
        )


@pytest.mark.parametrize(
    "invalid_id",
    [None, 0, -1, True, "1", 1.5]
)
def test_invalid_copy_id(
    service, data, invalid_id
):

    with pytest.raises(ValidationError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            invalid_id
        )


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED", "DAMAGED", "LOST"]
)
def test_unavailable_copy(
    service, data, status
):

    data["copy"].status = status
    db.session.commit()

    with pytest.raises(CopyUnavailableError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copy"].id
        )


def test_archived_book(service, data):

    data["book"].is_archived = True
    db.session.commit()

    with pytest.raises(CopyUnavailableError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copy"].id
        )


def test_double_borrow(service, data, loan):

    with pytest.raises(CopyUnavailableError):

        service.borrow_book(
            data["admin"].id,
            data["other_reader"].id,
            data["copy"].id
        )


def test_active_loan_with_wrong_copy_status(
    service, data, loan
):

    data["copy"].status = "AVAILABLE"
    db.session.commit()

    with pytest.raises(CopyUnavailableError):

        service.borrow_book(
            data["admin"].id,
            data["other_reader"].id,
            data["copy"].id
        )


# ==========================================
# LIMIT TESTS
# ==========================================

def test_default_loan_limit(service, data):

    for copy in data["copies"][:5]:

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            copy.id
        )

    with pytest.raises(LoanLimitExceededError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copies"][5].id
        )


def test_custom_loan_limit(service, data):

    service.setting_service.update(
        "MAX_ACTIVE_LOANS", 1
    )

    service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        data["copies"][0].id
    )

    with pytest.raises(LoanLimitExceededError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copies"][1].id
        )


def test_custom_loan_period(service, data):

    service.setting_service.update(
        "LOAN_PERIOD_DAYS", 14
    )

    loan = service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        data["copy"].id
    )

    assert (
        loan.due_date - loan.borrowed_at
    ).days == 14


def test_return_frees_loan_limit(
    service, data, loan
):

    service.setting_service.update(
        "MAX_ACTIVE_LOANS", 1
    )

    service.return_book(
        data["admin"].id,
        loan.id
    )

    new_loan = service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        data["copies"][1].id
    )

    assert new_loan.status == "ACTIVE"


def test_remaining_limit(
    service, data, loan
):

    result = service.get_remaining_loan_limit(
        data["admin"].id,
        data["reader"].id
    )

    assert result == 4


# ==========================================
# RESERVATION TESTS
# ==========================================

def _reservation_for_borrow(service, data, reader_key="other_reader",
                            status="WAITING"):
    now = service.now()
    reservation = Reservation(
        book_id=data["book"].id,
        reader_id=data[reader_key].id,
        reserved_at=now,
        expires_at=now + timedelta(days=3) if status == "READY" else None,
        status=status
    )
    if status == "READY":
        data["copies"][0].status = "RESERVED"
    db.session.add(reservation)
    db.session.commit()
    return reservation


def test_ready_reservation_allows_other_copy(service, data):
    reservation = _reservation_for_borrow(service, data, status="READY")
    copy = data["copies"][1]
    loan = service.borrow_book(data["admin"].id, data["reader"].id, copy.id)
    assert loan.status == "ACTIVE"
    assert loan.copy_id == copy.id
    assert copy.status == "LOANED"
    assert data["copy"].status == "RESERVED"
    assert reservation.status == "READY"


def test_reserved_copy_blocks_normal_borrow(service, data):
    reservation = _reservation_for_borrow(service, data, status="READY")
    with pytest.raises(CopyUnavailableError):
        service.borrow_book(
            data["admin"].id, data["reader"].id, data["copy"].id
        )
    assert reservation.status == "READY"
    assert data["copy"].status == "RESERVED"
    assert Loan.query.count() == 0


def test_waiting_reservation_has_priority(service, data):
    for copy in data["copies"][1:]:
        copy.status = "DAMAGED"
    reservation = _reservation_for_borrow(service, data)
    with pytest.raises(CopyUnavailableError):
        service.borrow_book(
            data["admin"].id, data["reader"].id, data["copy"].id
        )
    assert Loan.query.count() == 0
    assert reservation.status == "WAITING"
    assert reservation.expires_at is None
    assert data["copy"].status == "AVAILABLE"
    assert AuditLog.query.filter_by(action="RESERVATION_READY").count() == 0


def test_waiting_reservation_allows_surplus_copy(service, data):
    reservation = _reservation_for_borrow(service, data)
    copy = data["copies"][-1]
    loan = service.borrow_book(data["admin"].id, data["reader"].id, copy.id)
    assert loan.status == "ACTIVE"
    assert loan.copy_id == copy.id
    assert reservation.status == "READY"
    assert reservation.expires_at is not None
    assert data["copy"].status == "RESERVED"
    assert copy.status == "LOANED"
    assert sum(c.status == "RESERVED" for c in data["copies"]) == 1


def test_queue_processing_rollback(service, data, monkeypatch):
    reservation = _reservation_for_borrow(service, data)

    def fail_creation(*args, **kwargs):
        raise RuntimeError("Simulated loan creation failure")

    monkeypatch.setattr(service, "_create_loan", fail_creation)
    with pytest.raises(RuntimeError, match="Simulated loan creation failure"):
        service.borrow_book(
            data["admin"].id, data["reader"].id, data["copies"][-1].id
        )
    assert reservation.status == "WAITING"
    assert reservation.expires_at is None
    assert Loan.query.count() == 0
    assert all(c.status == "AVAILABLE" for c in data["copies"])
    assert AuditLog.query.filter_by(action="RESERVATION_READY").count() == 0


def test_reader_cannot_borrow_own_reserved_copy(service, data):
    reservation = _reservation_for_borrow(
        service, data, reader_key="reader", status="READY"
    )
    with pytest.raises(CopyUnavailableError):
        service.borrow_book(
            data["admin"].id, data["reader"].id, data["copy"].id
        )
    assert reservation.status == "READY"
    assert data["copy"].status == "RESERVED"
    assert Loan.query.count() == 0


def test_reader_cannot_bypass_own_reservation_with_surplus(service, data):
    reservation = _reservation_for_borrow(
        service, data, reader_key="reader", status="READY"
    )
    copy = data["copies"][1]
    with pytest.raises(BusinessRuleError, match="active reservation"):
        service.borrow_book(data["admin"].id, data["reader"].id, copy.id)
    assert reservation.status == "READY"
    assert data["copy"].status == "RESERVED"
    assert copy.status == "AVAILABLE"
    assert Loan.query.count() == 0


@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_inactive_reservation_allows_borrow(
    service, data, status
):

    reservation = Reservation(
        book_id=data["book"].id,
        reader_id=data["other_reader"].id,
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    loan = service.borrow_book(
        data["admin"].id,
        data["reader"].id,
        data["copy"].id
    )

    assert loan.status == "ACTIVE"


# ==========================================
# RETURN TESTS
# ==========================================

def test_return_book(service, data, loan):

    result = service.return_book(
        data["admin"].id,
        loan.id
    )

    assert result.status == "RETURNED"
    assert result.returned_at is not None


def test_return_changes_copy_status(
    service, data, loan
):

    service.return_book(
        data["admin"].id,
        loan.id
    )

    assert data["copy"].status == "AVAILABLE"


def test_return_without_fine(
    service, data, loan
):

    service.return_book(
        data["admin"].id,
        loan.id
    )

    assert (
        service.fine_repository.get_by_loan(
            loan.id
        ) is None
    )


def test_librarian_can_return(
    service, data, loan
):

    result = service.return_book(
        data["librarian"].id,
        loan.id
    )

    assert result.status == "RETURNED"


def test_reader_cannot_return(
    service, data, loan
):

    with pytest.raises(AuthorizationError):

        service.return_book(
            data["user"].id,
            loan.id
        )


def test_double_return(service, data, loan):

    service.return_book(
        data["admin"].id,
        loan.id
    )

    with pytest.raises(LoanAlreadyReturnedError):

        service.return_book(
            data["admin"].id,
            loan.id
        )


def test_return_nonexistent_loan(
    service, data
):

    with pytest.raises(NotFoundError):

        service.return_book(
            data["admin"].id,
            99999
        )


def test_return_inactive_reader(
    service, data, loan
):

    data["user"].is_active = False
    db.session.commit()

    result = service.return_book(
        data["admin"].id,
        loan.id
    )

    assert result.status == "RETURNED"


def test_return_inconsistent_copy(
    service, data, loan
):

    data["copy"].status = "AVAILABLE"
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.return_book(
            data["admin"].id,
            loan.id
        )


# ==========================================
# OVERDUE TESTS
# ==========================================

def test_not_overdue(service, data, loan):

    assert service.is_overdue(
        data["admin"].id,
        loan.id
    ) is False


def test_overdue(service, data, loan):

    make_overdue(service, loan)

    assert service.is_overdue(
        data["admin"].id,
        loan.id
    ) is True


def test_overdue_days(service, data, loan):

    make_overdue(service, loan, 3)

    assert service.get_overdue_days(
        data["admin"].id,
        loan.id
    ) == 3


def test_future_due_date(
    service, data, loan
):

    assert service.get_overdue_days(
        data["admin"].id,
        loan.id
    ) == 0


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (-1, 0),
        (0, 0),
        (1, 1),
        (3600, 1),
        (86399, 1),
        (86400, 1),
        (86401, 2),
        (172800, 2)
    ]
)
def test_overdue_day_boundaries(
    service, seconds, expected
):

    due_date = service.now()

    reference_date = due_date + timedelta(
        seconds=seconds
    )

    assert service._calculate_overdue_days(
        due_date,
        reference_date
    ) == expected


def test_overdue_list(service, data, loan):

    make_overdue(service, loan)

    result = service.get_overdue_loans(
        data["admin"].id
    )

    assert loan in result


def test_returned_loan_not_overdue(
    service, data, loan
):

    make_overdue(service, loan)

    service.return_book(
        data["admin"].id,
        loan.id
    )

    assert service.is_overdue(
        data["admin"].id,
        loan.id
    ) is False


# ==========================================
# FINE TESTS
# ==========================================

def test_calculate_zero_fine(
    service, data, loan
):

    amount = service.calculate_fine(
        data["admin"].id,
        loan.id
    )

    assert amount == Decimal("0.00")


def test_calculate_overdue_fine(
    service, data, loan
):

    make_overdue(service, loan, 3)

    amount = service.calculate_fine(
        data["admin"].id,
        loan.id
    )

    assert amount == Decimal("3.00")


def test_custom_daily_fine(
    service, data, loan
):

    service.setting_service.update(
        "FINE_PER_DAY", Decimal("2.50")
    )

    make_overdue(service, loan, 3)

    amount = service.calculate_fine(
        data["admin"].id,
        loan.id
    )

    assert amount == Decimal("7.50")


def test_return_creates_fine(
    service, data, loan
):

    make_overdue(service, loan, 3)

    service.return_book(
        data["admin"].id,
        loan.id
    )

    fine = service.fine_repository.get_by_loan(
        loan.id
    )

    assert fine is not None
    assert fine.amount == Decimal("3.00")
    assert fine.paid_amount == Decimal("0.00")
    assert fine.status == "UNPAID"


def test_zero_daily_fine(
    service, data, loan
):

    service.setting_service.update(
        "FINE_PER_DAY", 0
    )

    make_overdue(service, loan)

    service.return_book(
        data["admin"].id,
        loan.id
    )

    assert (
        service.fine_repository.get_by_loan(
            loan.id
        ) is None
    )


def test_saved_fine_does_not_change(
    service, data, loan
):

    make_overdue(service, loan, 3)

    service.return_book(
        data["admin"].id,
        loan.id
    )

    service.setting_service.update(
        "FINE_PER_DAY", 10
    )

    assert service.calculate_fine(
        data["admin"].id,
        loan.id
    ) == Decimal("3.00")


def test_fine_calculation_does_not_create_record(
    service, data, loan
):

    make_overdue(service, loan)

    service.calculate_fine(
        data["admin"].id,
        loan.id
    )

    assert (
        service.fine_repository.get_by_loan(
            loan.id
        ) is None
    )


def test_existing_fine_blocks_return(
    service, data, loan
):

    fine = Fine(
        loan_id=loan.id,
        amount=Decimal("5.00"),
        paid_amount=Decimal("0.00"),
        status="UNPAID"
    )

    db.session.add(fine)
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.return_book(
            data["admin"].id,
            loan.id
        )


# ==========================================
# CANCEL TESTS
# ==========================================

def test_cancel_loan(service, data, loan):

    result = service.cancel_loan(
        data["admin"].id,
        loan.id,
        "Incorrect registration"
    )

    assert result.status == "CANCELLED"
    assert result.returned_at is None
    assert data["copy"].status == "AVAILABLE"


def test_librarian_cannot_cancel(
    service, data, loan
):

    with pytest.raises(AuthorizationError):

        service.cancel_loan(
            data["librarian"].id,
            loan.id,
            "Test reason"
        )


def test_reader_cannot_cancel(
    service, data, loan
):

    with pytest.raises(AuthorizationError):

        service.cancel_loan(
            data["user"].id,
            loan.id,
            "Test reason"
        )


@pytest.mark.parametrize(
    "reason",
    [None, "", "   ", 123, "a" * 1001]
)
def test_invalid_cancel_reason(
    service, data, loan, reason
):

    with pytest.raises(ValidationError):

        service.cancel_loan(
            data["admin"].id,
            loan.id,
            reason
        )


def test_cannot_cancel_overdue_loan(
    service, data, loan
):

    make_overdue(service, loan)

    with pytest.raises(BusinessRuleError):

        service.cancel_loan(
            data["admin"].id,
            loan.id,
            "Test reason"
        )


def test_cancelled_loan_cannot_be_returned(
    service, data, loan
):

    service.cancel_loan(
        data["admin"].id,
        loan.id,
        "Incorrect registration"
    )

    with pytest.raises(BusinessRuleError):

        service.return_book(
            data["admin"].id,
            loan.id
        )


def test_cancelled_loan_has_zero_fine(
    service, data, loan
):

    service.cancel_loan(
        data["admin"].id,
        loan.id,
        "Incorrect registration"
    )

    assert service.calculate_fine(
        data["admin"].id,
        loan.id
    ) == Decimal("0.00")


# ==========================================
# READ AND ACCESS TESTS
# ==========================================

def test_get_by_id(service, data, loan):

    result = service.get_by_id(
        data["admin"].id,
        loan.id
    )

    assert result.id == loan.id


def test_reader_gets_own_loan(
    service, data, loan
):

    result = service.get_by_id(
        data["user"].id,
        loan.id
    )

    assert result.id == loan.id


def test_reader_cannot_get_other_loan(
    service, data, loan
):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            data["other_user"].id,
            loan.id
        )


def test_get_all(service, data, loan):

    result = service.get_all(
        data["admin"].id
    )

    assert loan in result


def test_reader_cannot_get_all(
    service, data
):

    with pytest.raises(AuthorizationError):

        service.get_all(
            data["user"].id
        )


def test_get_by_reader(
    service, data, loan
):

    result = service.get_by_reader(
        data["admin"].id,
        data["reader"].id
    )

    assert loan in result


def test_reader_cannot_get_other_history(
    service, data, loan
):

    with pytest.raises(AuthorizationError):

        service.get_by_reader(
            data["other_user"].id,
            data["reader"].id
        )


def test_get_by_copy(service, data, loan):

    result = service.get_by_copy(
        data["admin"].id,
        data["copy"].id
    )

    assert loan in result


def test_get_active_loans(
    service, data, loan
):

    assert loan in service.get_active_loans(
        data["admin"].id
    )


def test_get_active_by_reader(
    service, data, loan
):

    assert loan in service.get_active_by_reader(
        data["user"].id,
        data["reader"].id
    )


def test_get_active_by_copy(
    service, data, loan
):

    result = service.get_active_by_copy(
        data["admin"].id,
        data["copy"].id
    )

    assert result.id == loan.id


def test_get_own_loans(service, data, loan):

    assert loan in service.get_own_loans(
        data["user"].id
    )


def test_get_own_active_loans(
    service, data, loan
):

    assert loan in service.get_own_active_loans(
        data["user"].id
    )


def test_other_reader_has_no_loans(
    service, data, loan
):

    assert service.get_own_loans(
        data["other_user"].id
    ) == []


def test_count(service, data, loan):

    assert service.count(
        data["admin"].id
    ) == 1


def test_count_active_by_reader(
    service, data, loan
):

    assert service.count_active_by_reader(
        data["user"].id,
        data["reader"].id
    ) == 1


def test_get_by_status(service, data, loan):

    assert loan in service.get_by_status(
        data["admin"].id,
        "active"
    )


@pytest.mark.parametrize(
    "status",
    [None, "", "UNKNOWN", "OVERDUE", 123]
)
def test_invalid_status(
    service, data, status
):

    with pytest.raises(ValidationError):

        service.get_by_status(
            data["admin"].id,
            status
        )


# ==========================================
# AUDIT TESTS
# ==========================================

def test_borrow_audit(service, data, loan):

    audit = AuditLog.query.filter_by(
        action="LOAN_CREATED"
    ).first()

    assert audit is not None
    assert audit.user_id == data["admin"].id


def test_return_audit(service, data, loan):

    service.return_book(
        data["admin"].id,
        loan.id
    )

    audit = AuditLog.query.filter_by(
        action="LOAN_RETURNED"
    ).first()

    assert audit is not None


def test_cancel_audit(service, data, loan):

    service.cancel_loan(
        data["admin"].id,
        loan.id,
        "Incorrect registration"
    )

    audit = AuditLog.query.filter_by(
        action="LOAN_CANCELLED"
    ).first()

    assert audit is not None


def test_fine_audit(service, data, loan):

    make_overdue(service, loan)

    service.return_book(
        data["admin"].id,
        loan.id
    )

    audit = AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).first()

    assert audit is not None


# ==========================================
# TRANSACTION TESTS
# ==========================================

def fail_audit(*args, **kwargs):

    raise RuntimeError("Simulated audit failure")


def test_borrow_rollback(
    service, data, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(RuntimeError):

        service.borrow_book(
            data["admin"].id,
            data["reader"].id,
            data["copy"].id
        )

    assert Loan.query.count() == 0
    assert data["copy"].status == "AVAILABLE"


def test_return_rollback(
    service, data, loan, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(RuntimeError):

        service.return_book(
            data["admin"].id,
            loan.id
        )

    assert loan.status == "ACTIVE"
    assert loan.returned_at is None
    assert data["copy"].status == "LOANED"


def test_fine_rollback(
    service, data, loan, monkeypatch
):

    make_overdue(service, loan)

    original_log = service.audit_service.log

    def fail_return_audit(
        action,
        *args,
        **kwargs
    ):

        if action == "LOAN_RETURNED":

            raise RuntimeError(
                "Simulated return audit failure"
            )

        return original_log(
            action,
            *args,
            **kwargs
        )

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_return_audit
    )

    with pytest.raises(RuntimeError):

        service.return_book(
            data["admin"].id,
            loan.id
        )

    assert Fine.query.count() == 0
    assert loan.status == "ACTIVE"
    assert data["copy"].status == "LOANED"

    assert AuditLog.query.filter_by(
        action="FINE_CREATED"
    ).count() == 0


def test_cancel_rollback(
    service, data, loan, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(RuntimeError):

        service.cancel_loan(
            data["admin"].id,
            loan.id,
            "Incorrect registration"
        )

    assert loan.status == "ACTIVE"
    assert data["copy"].status == "LOANED"
