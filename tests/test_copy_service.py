
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db

from app.models import (
    User,
    Book,
    Copy,
    Reader,
    Loan,
    Reservation,
    AuditLog
)

from app.services import CopyService

from app.exceptions import (
    ValidationError,
    DuplicateError,
    BusinessRuleError,
    NotFoundError,
    AuthorizationError,
    AuthenticationError,
    InactiveAccountError
)


# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
def service(app):

    return CopyService()


@pytest.fixture
def users(service):

    result = {}

    for role in ("ADMIN", "LIBRARIAN", "READER"):

        user = User(
            username=role.lower(),
            email=f"{role.lower()}@example.com",
            password_hash="test_hash",
            role=role,
            is_active=True
        )

        db.session.add(user)

        result[role.lower()] = user

    db.session.commit()

    return result


@pytest.fixture
def book(service):

    book = Book(
        title="Wiedźmin",
        is_archived=False
    )

    db.session.add(book)
    db.session.commit()

    return book


@pytest.fixture
def copy(service, users, book):

    return service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )


@pytest.fixture
def reader(users):

    reader = Reader(
        user_id=users["reader"].id,
        card_number="LIB-001",
        first_name="Jan",
        last_name="Kowalski"
    )

    db.session.add(reader)
    db.session.commit()

    return reader


def create_loan(copy, reader, status="ACTIVE"):

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    loan = Loan(
        copy_id=copy.id,
        reader_id=reader.id,
        borrowed_at=now - timedelta(days=5),
        due_date=now + timedelta(days=25),
        status=status,
        returned_at=(
            now if status == "RETURNED" else None
        )
    )

    db.session.add(loan)
    db.session.commit()

    return loan


def create_reservation(
    book,
    reader,
    status="WAITING"
):

    reservation = Reservation(
        book_id=book.id,
        reader_id=reader.id,
        status=status
    )

    db.session.add(reservation)
    db.session.commit()

    return reservation


# ==========================================
# CREATE
# ==========================================

def test_create_copy(service, users, book):

    copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    assert copy.id is not None
    assert copy.book_id == book.id
    assert copy.inventory_number == "INV-001"
    assert copy.status == "AVAILABLE"
    assert copy.added_at is not None


def test_create_multiple_copies(
    service, users, book, copy
):

    second = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    assert second.id != copy.id
    assert second.book_id == copy.book_id


def test_create_by_librarian(
    service, users, book
):

    copy = service.create_copy(
        users["librarian"].id,
        book.id,
        "INV-001"
    )

    assert copy.id is not None


def test_reader_cannot_create(
    service, users, book
):

    with pytest.raises(AuthorizationError):

        service.create_copy(
            users["reader"].id,
            book.id,
            "INV-001"
        )


def test_authentication_required(
    service, book
):

    with pytest.raises(AuthenticationError):

        service.create_copy(
            None,
            book.id,
            "INV-001"
        )


def test_inactive_account(
    service, users, book
):

    users["admin"].is_active = False
    db.session.commit()

    with pytest.raises(InactiveAccountError):

        service.create_copy(
            users["admin"].id,
            book.id,
            "INV-001"
        )


def test_nonexistent_book(service, users):

    with pytest.raises(NotFoundError):

        service.create_copy(
            users["admin"].id,
            999,
            "INV-001"
        )


def test_cannot_create_for_archived_book(
    service, users, book
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.create_copy(
            users["admin"].id,
            book.id,
            "INV-001"
        )


# ==========================================
# VALIDATION
# ==========================================

@pytest.mark.parametrize(
    "number",
    [
        "",
        "   ",
        None,
        123,
        True,
        "INV 001",
        "INV@001",
        "INV.001",
        "-INV",
        "A" * 51,
        "ŁÓDŹ-001"
    ]
)
def test_invalid_inventory_number(
    service, users, book, number
):

    with pytest.raises(ValidationError):

        service.create_copy(
            users["admin"].id,
            book.id,
            number
        )


@pytest.mark.parametrize(
    "number,expected",
    [
        ("inv-001", "INV-001"),
        ("  INV-001  ", "INV-001"),
        ("lib/2026/001", "LIB/2026/001"),
        ("lib_001", "LIB_001"),
        ("12345", "12345"),
        ("A" * 50, "A" * 50)
    ]
)
def test_valid_inventory_number(
    service, users, book, number, expected
):

    copy = service.create_copy(
        users["admin"].id,
        book.id,
        number
    )

    assert copy.inventory_number == expected


@pytest.mark.parametrize(
    "number",
    [
        "INV-001",
        "inv-001",
        "  Inv-001  "
    ]
)
def test_duplicate_inventory_number(
    service, users, book, copy, number
):

    with pytest.raises(DuplicateError):

        service.create_copy(
            users["admin"].id,
            book.id,
            number
        )


def test_inventory_unique_across_books(
    service, users, copy
):

    other_book = Book(
        title="Inna książka"
    )

    db.session.add(other_book)
    db.session.commit()

    with pytest.raises(DuplicateError):

        service.create_copy(
            users["admin"].id,
            other_book.id,
            copy.inventory_number
        )


def test_legacy_inventory_duplicate(
    service, users, book
):

    db.session.add(
        Copy(
            book_id=book.id,
            inventory_number="inv-001"
        )
    )

    db.session.commit()

    with pytest.raises(DuplicateError):

        service.create_copy(
            users["admin"].id,
            book.id,
            "INV-001"
        )


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -1, "1", 1.5]
)
def test_invalid_book_id(
    service, users, value
):

    with pytest.raises(ValidationError):

        service.create_copy(
            users["admin"].id,
            value,
            "INV-001"
        )


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -1, "1"]
)
def test_invalid_copy_id(
    service, users, value
):

    with pytest.raises(ValidationError):

        service.get_by_id(
            users["admin"].id,
            value
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        123,
        "",
        "UNKNOWN",
        "BORROWED"
    ]
)
def test_invalid_status(
    service, users, copy, value
):

    with pytest.raises(ValidationError):

        service.change_status(
            users["admin"].id,
            copy.id,
            value
        )


# ==========================================
# READ
# ==========================================

def test_get_by_id(service, users, copy):

    result = service.get_by_id(
        users["admin"].id,
        copy.id
    )

    assert result.id == copy.id


def test_get_unknown_copy(service, users):

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["admin"].id,
            999
        )


def test_get_by_inventory_number(
    service, users, copy
):

    result = service.get_by_inventory_number(
        users["admin"].id,
        "inv-001"
    )

    assert result.id == copy.id


def test_unknown_inventory_number(
    service, users
):

    with pytest.raises(NotFoundError):

        service.get_by_inventory_number(
            users["admin"].id,
            "INV-999"
        )


def test_get_all(service, users, copy):

    result = service.get_all(
        users["admin"].id
    )

    assert len(result) == 1


def test_get_by_book_id(
    service, users, book, copy
):

    result = service.get_by_book_id(
        users["admin"].id,
        book.id
    )

    assert len(result) == 1
    assert result[0].id == copy.id


def test_get_by_status(
    service, users, copy
):

    result = service.get_by_status(
        users["admin"].id,
        "available"
    )

    assert len(result) == 1
    assert result[0].id == copy.id


def test_count(service, users, copy):

    assert service.count(
        users["admin"].id
    ) == 1


def test_reader_cannot_list_inventory(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.get_all(
            users["reader"].id
        )


def test_reader_cannot_get_copy(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.get_by_id(
            users["reader"].id,
            copy.id
        )


def test_reader_cannot_search_inventory(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.search(
            users["reader"].id,
            "INV"
        )


def test_archived_copy_hidden(
    service, users, copy, book
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(NotFoundError):

        service.get_by_id(
            users["admin"].id,
            copy.id
        )

    assert service.get_all(
        users["admin"].id
    ) == []


def test_staff_archived_access(
    service, users, copy, book
):

    book.is_archived = True
    db.session.commit()

    result = service.get_by_id(
        users["librarian"].id,
        copy.id,
        include_archived=True
    )

    assert result.id == copy.id


def test_reader_cannot_access_archive(
    service, users, book, copy
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(AuthorizationError):

        service.get_all(
            users["reader"].id,
            include_archived=True
        )


@pytest.mark.parametrize(
    "value",
    [None, 1, "true"]
)
def test_invalid_include_archived(
    service, users, value
):

    with pytest.raises(ValidationError):

        service.get_all(
            users["admin"].id,
            include_archived=value
        )


# ==========================================
# SEARCH
# ==========================================

@pytest.mark.parametrize(
    "query",
    ["INV", "inv", "001", "  inv-001  "]
)
def test_search_copy(
    service, users, copy, query
):

    result = service.search(
        users["admin"].id,
        query
    )

    assert len(result) == 1
    assert result[0].id == copy.id


def test_search_no_results(
    service, users, copy
):

    assert service.search(
        users["admin"].id,
        "UNKNOWN"
    ) == []


@pytest.mark.parametrize(
    "query",
    ["", None, 123, "   ", "A" * 51]
)
def test_invalid_search(
    service, users, query
):

    with pytest.raises(ValidationError):

        service.search(
            users["admin"].id,
            query
        )


def test_search_sorted(
    service, users, book
):

    for number in (
        "INV-003",
        "INV-001",
        "INV-002"
    ):

        service.create_copy(
            users["admin"].id,
            book.id,
            number
        )

    result = service.search(
        users["admin"].id,
        "INV"
    )

    assert [
        copy.inventory_number for copy in result
    ] == [
        "INV-001",
        "INV-002",
        "INV-003"
    ]


# ==========================================
# UPDATE
# ==========================================

def test_update_copy(service, users, copy):

    result = service.update_copy(
        users["admin"].id,
        copy.id,
        "INV-999"
    )

    assert result.inventory_number == "INV-999"


def test_update_preserves_book(
    service, users, copy
):

    old_book_id = copy.book_id

    service.update_copy(
        users["admin"].id,
        copy.id,
        "INV-999"
    )

    assert copy.book_id == old_book_id


def test_update_by_librarian(
    service, users, copy
):

    service.update_copy(
        users["librarian"].id,
        copy.id,
        "INV-999"
    )

    assert copy.inventory_number == "INV-999"


def test_reader_cannot_update(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.update_copy(
            users["reader"].id,
            copy.id,
            "INV-999"
        )


def test_update_same_inventory_number(
    service, users, copy
):

    result = service.update_copy(
        users["admin"].id,
        copy.id,
        "inv-001"
    )

    assert result.inventory_number == "INV-001"


def test_update_duplicate_number(
    service, users, book, copy
):

    service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    with pytest.raises(DuplicateError):

        service.update_copy(
            users["admin"].id,
            copy.id,
            "INV-002"
        )

    assert copy.inventory_number == "INV-001"


def test_invalid_update_preserves_data(
    service, users, copy
):

    with pytest.raises(ValidationError):

        service.update_copy(
            users["admin"].id,
            copy.id,
            ""
        )

    assert copy.inventory_number == "INV-001"


def test_cannot_update_archived_copy(
    service, users, copy, book
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.update_copy(
            users["admin"].id,
            copy.id,
            "INV-999"
        )


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED"]
)
def test_cannot_update_managed_copy(
    service, users, copy, status
):

    copy.status = status
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.update_copy(
            users["admin"].id,
            copy.id,
            "INV-999"
        )


# ==========================================
# STATUS MANAGEMENT
# ==========================================

def test_mark_damaged(
    service, users, copy
):

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    assert copy.status == "DAMAGED"


def test_mark_lost(service, users, copy):

    service.mark_lost(
        users["admin"].id,
        copy.id
    )

    assert copy.status == "LOST"


@pytest.mark.parametrize(
    "status",
    ["DAMAGED", "LOST"]
)
def test_restore_availability(
    service, users, copy, status
):

    copy.status = status
    db.session.commit()

    service.restore_availability(
        users["admin"].id,
        copy.id
    )

    assert copy.status == "AVAILABLE"


def test_change_status_by_librarian(
    service, users, copy
):

    service.mark_damaged(
        users["librarian"].id,
        copy.id
    )

    assert copy.status == "DAMAGED"


def test_reader_cannot_change_status(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.mark_lost(
            users["reader"].id,
            copy.id
        )


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED"]
)
def test_managed_status_cannot_be_set_manually(
    service, users, copy, status
):

    with pytest.raises(BusinessRuleError):

        service.change_status(
            users["admin"].id,
            copy.id,
            status
        )

    assert copy.status == "AVAILABLE"


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED"]
)
def test_managed_copy_cannot_change_status(
    service, users, copy, status
):

    copy.status = status
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.restore_availability(
            users["admin"].id,
            copy.id
        )


def test_active_loan_blocks_status_change(
    service, users, copy, reader
):

    create_loan(copy, reader)

    with pytest.raises(BusinessRuleError):

        service.mark_lost(
            users["admin"].id,
            copy.id
        )


def test_returned_loan_allows_status_change(
    service, users, copy, reader
):

    create_loan(
        copy,
        reader,
        status="RETURNED"
    )

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    assert copy.status == "DAMAGED"


def test_status_whitespace(
    service, users, copy
):

    service.change_status(
        users["admin"].id,
        copy.id,
        "  damaged  "
    )

    assert copy.status == "DAMAGED"


def test_status_change_idempotent(
    service, users, copy
):

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    logs = AuditLog.query.filter_by(
        action="COPY_STATUS_CHANGED"
    ).all()

    assert len(logs) == 1


def test_archived_copy_status_locked(
    service, users, copy, book
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.mark_lost(
            users["admin"].id,
            copy.id
        )


# ==========================================
# RESERVATION PROTECTION
# ==========================================


def test_waiting_reservation_allows_creation(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    assert copy.id is not None
    assert copy.status == "RESERVED"
    assert reservation.status == "READY"
    assert reservation.expires_at is not None


def test_reservation_creation_audit(
    service, users, book, reader
):

    create_reservation(book, reader)

    service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    assert AuditLog.query.filter_by(
        action="COPY_CREATED"
    ).count() == 1

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 1


def test_ready_reservation_allows_extra_copy(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    first = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    second = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    assert first.status == "RESERVED"
    assert second.status == "AVAILABLE"
    assert reservation.status == "READY"


def test_ready_reservation_allows_damage(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    reserved = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    available = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    service.mark_damaged(
        users["admin"].id,
        available.id
    )

    assert available.status == "DAMAGED"
    assert reserved.status == "RESERVED"
    assert reservation.status == "READY"


def test_ready_reservation_allows_loss(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    reserved = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    available = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    service.mark_lost(
        users["admin"].id,
        available.id
    )

    assert available.status == "LOST"
    assert reserved.status == "RESERVED"
    assert reservation.status == "READY"


@pytest.mark.parametrize(
    "status",
    ["DAMAGED", "LOST"]
)
def test_restored_copy_processes_reservation(
    service, users, copy, book, reader, status
):

    copy.status = status
    db.session.commit()

    reservation = create_reservation(
        book, reader
    )

    service.restore_availability(
        users["admin"].id,
        copy.id
    )

    assert copy.status == "RESERVED"
    assert reservation.status == "READY"
    assert reservation.expires_at is not None


def test_reserved_copy_remains_protected(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    with pytest.raises(BusinessRuleError):

        service.mark_damaged(
            users["admin"].id,
            copy.id
        )

    with pytest.raises(BusinessRuleError):

        service.mark_lost(
            users["admin"].id,
            copy.id
        )

    assert copy.status == "RESERVED"
    assert reservation.status == "READY"


def test_creation_reservation_rollback(
    service, users, book, reader, monkeypatch
):

    reservation = create_reservation(
        book, reader
    )

    original_process = (
        service.reservation_service._process_queue
    )

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated reservation failure."
        )

    monkeypatch.setattr(
        service.reservation_service,
        "_process_queue",
        fail_queue
    )

    with pytest.raises(RuntimeError):

        service.create_copy(
            users["admin"].id,
            book.id,
            "INV-001"
        )

    assert Copy.query.count() == 0
    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert AuditLog.query.filter_by(
        action="COPY_CREATED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 0


def test_restore_reservation_rollback(
    service, users, copy, book,
    reader, monkeypatch
):

    copy.status = "DAMAGED"
    db.session.commit()

    reservation = create_reservation(
        book, reader
    )

    original_process = (
        service.reservation_service._process_queue
    )

    def fail_queue(*args, **kwargs):

        original_process(*args, **kwargs)

        raise RuntimeError(
            "Simulated reservation failure."
        )

    monkeypatch.setattr(
        service.reservation_service,
        "_process_queue",
        fail_queue
    )

    with pytest.raises(RuntimeError):

        service.restore_availability(
            users["admin"].id,
            copy.id
        )

    assert copy.status == "DAMAGED"
    assert reservation.status == "WAITING"
    assert reservation.expires_at is None

    assert AuditLog.query.filter_by(
        action="COPY_STATUS_CHANGED"
    ).count() == 0

    assert AuditLog.query.filter_by(
        action="RESERVATION_READY"
    ).count() == 0


def test_new_copy_respects_fifo(
    service, users, book, reader
):

    second_user = User(
        username="reader2",
        email="reader2@example.com",
        password_hash="test_hash",
        role="READER",
        is_active=True
    )

    db.session.add(second_user)
    db.session.flush()

    second_reader = Reader(
        user_id=second_user.id,
        card_number="LIB-002",
        first_name="Anna",
        last_name="Nowak"
    )

    db.session.add(second_reader)
    db.session.commit()

    first_reservation = create_reservation(
        book, reader
    )

    second_reservation = create_reservation(
        book, second_reader
    )

    now = service.reservation_service.now()

    first_reservation.reserved_at = (
        now - timedelta(hours=2)
    )

    second_reservation.reserved_at = (
        now - timedelta(hours=1)
    )

    db.session.commit()

    first_copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-001"
    )

    assert first_copy.status == "RESERVED"
    assert first_reservation.status == "READY"
    assert second_reservation.status == "WAITING"

    second_copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    assert second_copy.status == "RESERVED"
    assert second_reservation.status == "READY"


def test_reserved_pool_consistency(
    service, users, book, reader
):

    reservation = create_reservation(
        book, reader
    )

    for number in range(1, 4):

        service.create_copy(
            users["admin"].id,
            book.id,
            f"INV-{number:03d}"
        )

    reserved_count = Copy.query.filter_by(
        book_id=book.id,
        status="RESERVED"
    ).count()

    ready_count = Reservation.query.filter_by(
        book_id=book.id,
        status="READY"
    ).count()

    available_count = Copy.query.filter_by(
        book_id=book.id,
        status="AVAILABLE"
    ).count()

    assert reservation.status == "READY"
    assert reserved_count == ready_count
    assert reserved_count == 1
    assert available_count == 2

@pytest.mark.parametrize(
    "status",
    ["FULFILLED", "CANCELLED", "EXPIRED"]
)
def test_inactive_reservation_allows_creation(
    service, users, book, reader, status
):

    create_reservation(book, reader, status)

    copy = service.create_copy(
        users["admin"].id,
        book.id,
        "INV-002"
    )

    assert copy.status == "AVAILABLE"


# ==========================================
# DELETE
# ==========================================

def test_delete_copy(service, users, copy):

    copy_id = copy.id

    assert service.delete_copy(
        users["admin"].id,
        copy_id
    ) is True

    assert db.session.get(
        Copy,
        copy_id
    ) is None


def test_delete_by_librarian(
    service, users, copy
):

    assert service.delete_copy(
        users["librarian"].id,
        copy.id
    ) is True


def test_reader_cannot_delete(
    service, users, copy
):

    with pytest.raises(AuthorizationError):

        service.delete_copy(
            users["reader"].id,
            copy.id
        )


def test_delete_unknown_copy(
    service, users
):

    with pytest.raises(NotFoundError):

        service.delete_copy(
            users["admin"].id,
            999
        )


@pytest.mark.parametrize(
    "status",
    ["ACTIVE", "RETURNED", "CANCELLED"]
)
def test_loan_history_blocks_delete(
    service, users, copy, reader, status
):

    create_loan(copy, reader, status)

    with pytest.raises(BusinessRuleError):

        service.delete_copy(
            users["admin"].id,
            copy.id
        )


@pytest.mark.parametrize(
    "status",
    ["LOANED", "RESERVED"]
)
def test_managed_copy_cannot_be_deleted(
    service, users, copy, status
):

    copy.status = status
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.delete_copy(
            users["admin"].id,
            copy.id
        )


def test_archived_copy_cannot_be_deleted(
    service, users, copy, book
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(BusinessRuleError):

        service.delete_copy(
            users["admin"].id,
            copy.id
        )


def test_reservation_blocks_delete(
    service, users, copy, book, reader
):

    create_reservation(book, reader)

    with pytest.raises(BusinessRuleError):

        service.delete_copy(
            users["admin"].id,
            copy.id
        )


# ==========================================
# AVAILABILITY
# ==========================================

def test_available_copies(
    service, users, book, copy
):

    result = service.get_available_copies(
        users["admin"].id,
        book.id
    )

    assert len(result) == 1


def test_reader_cannot_list_available_copies(
    service, users, book, copy
):

    with pytest.raises(AuthorizationError):

        service.get_available_copies(
            users["reader"].id,
            book.id
        )


def test_reader_can_count_available_copies(
    service, users, book, copy
):

    assert service.count_available_copies(
        users["reader"].id,
        book.id
    ) == 1


def test_count_without_copies(
    service, users, book
):

    assert service.count_available_copies(
        users["reader"].id,
        book.id
    ) == 0


def test_is_available(
    service, users, book, copy
):

    assert service.is_available(
        users["reader"].id,
        book.id
    ) is True


def test_unavailable_book(
    service, users, book, copy
):

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    assert service.is_available(
        users["reader"].id,
        book.id
    ) is False


def test_archived_availability_hidden(
    service, users, book, copy
):

    book.is_archived = True
    db.session.commit()

    with pytest.raises(NotFoundError):

        service.count_available_copies(
            users["reader"].id,
            book.id
        )


def test_availability_excludes_other_statuses(
    service, users, book, copy
):

    for index, status in enumerate(
        ["LOANED", "RESERVED", "DAMAGED", "LOST"],
        start=2
    ):

        db.session.add(
            Copy(
                book_id=book.id,
                inventory_number=f"INV-{index:03d}",
                status=status
            )
        )

    db.session.commit()

    assert service.count_available_copies(
        users["admin"].id,
        book.id
    ) == 1


# ==========================================
# AUDIT
# ==========================================

def test_creation_audit(
    service, users, copy
):

    log = AuditLog.query.filter_by(
        action="COPY_CREATED"
    ).one()

    assert log.user_id == users["admin"].id


def test_update_audit(
    service, users, copy
):

    service.update_copy(
        users["admin"].id,
        copy.id,
        "INV-999"
    )

    log = AuditLog.query.filter_by(
        action="COPY_UPDATED"
    ).one()

    assert log.user_id == users["admin"].id


def test_status_audit(
    service, users, copy
):

    service.mark_damaged(
        users["admin"].id,
        copy.id
    )

    log = AuditLog.query.filter_by(
        action="COPY_STATUS_CHANGED"
    ).one()

    assert "AVAILABLE -> DAMAGED" in log.description


def test_delete_audit(
    service, users, copy
):

    service.delete_copy(
        users["admin"].id,
        copy.id
    )

    log = AuditLog.query.filter_by(
        action="COPY_DELETED"
    ).one()

    assert log.user_id == users["admin"].id


# ==========================================
# TRANSACTIONS
# ==========================================

def fail_audit(*args, **kwargs):

    raise BusinessRuleError(
        "Simulated audit failure."
    )


def test_create_rollback(
    service, users, book, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.create_copy(
            users["admin"].id,
            book.id,
            "INV-001"
        )

    assert Copy.query.count() == 0


def test_update_rollback(
    service, users, copy, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.update_copy(
            users["admin"].id,
            copy.id,
            "INV-999"
        )

    assert copy.inventory_number == "INV-001"


def test_status_rollback(
    service, users, copy, monkeypatch
):

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.mark_damaged(
            users["admin"].id,
            copy.id
        )

    assert copy.status == "AVAILABLE"


def test_delete_rollback(
    service, users, copy, monkeypatch
):

    copy_id = copy.id

    monkeypatch.setattr(
        service.audit_service,
        "log",
        fail_audit
    )

    with pytest.raises(BusinessRuleError):

        service.delete_copy(
            users["admin"].id,
            copy_id
        )

    assert db.session.get(
        Copy,
        copy_id
    ) is not None
